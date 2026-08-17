# -*- coding: utf-8 -*-
"""Do lançamento do ERP ao arquivo de remessa CNAB 240 — a regra, sem tela.

Puro de propósito, como o `relatorio.py`: quem abre janela é o
`pagamentos_frame.py`. Aqui só entram decisões, e cada uma delas é sobre
mandar ou não mandar dinheiro.

O que este módulo assume, e por quê
-----------------------------------

**A remessa sai da memória do "1. Buscar", não da planilha.** A planilha é
relatório; relê-la seria reparsear texto formatado para reconstruir número.

**Só entra o que foi MARCADO.** Quem confere ignora linhas de propósito, e o
app não sabe distinguir "deixei para depois" de "não vi". Por isso a lista
nasce com o APTO marcado e o ATENÇÃO desmarcado, e desmarcar é um ato.

**Impedimento não é o mesmo que desmarcado.** Desmarcar é escolha sua;
impedimento é o pagamento que não *pode* sair, e ele nem aparece marcável.
São três famílias, e todas vêm de regra que já existia na planilha:

- a observação que **manda pagar outra pessoa** (`precisa_de_olhar_humano`).
  Enquanto quem paga é gente, alguém lê a observação. Na remessa não há quem
  leia, e o dinheiro iria para a chave do cadastro — pessoa errada, valor
  certo, sem erro na tela;
- **pagamento parcial** como boleto: o código de barras carrega o valor cheio;
- **falta o dado que o layout exige** — linha digitável que não fecha nos
  dígitos verificadores, ou Pix sem o CPF/CNPJ do favorecido.

**O Pix vale para qualquer tipo de chave, e quem paga isso é o cadastro.** O
segmento B exige tipo e número de inscrição do favorecido (07.3B e 08.3B,
obrigatórios), e o lançamento não traz o documento — nem o id do participante,
só o nome (`paidTo`). O documento vem do cadastro de Contatos do ERP
(`mc_api.listar_participantes`), ligado pelo NOME. Medido em 13/08/2026 sobre
300 lançamentos e 455 participantes: **296 casaram e todos tinham documento**;
as 4 sobras eram `paidTo` igual a "-".

Sem o cadastro (falha de rede, sessão caída), sobra o caso em que a própria
chave é um CPF/CNPJ. Ninguém inventa documento de favorecido aqui.
"""
from __future__ import annotations

import datetime as _dt
import re
from dataclasses import dataclass
from decimal import Decimal

import ocr_boleto
import regras_pagamento as regras

#: Motivos de impedimento, em texto que vai para a tela e para o "ficou de fora".
MOTIVO_MAO = "a observação manda pagar outra pessoa"
MOTIVO_PARCIAL = "pagamento parcial — boleto não se paga pela metade"
MOTIVO_LINHA = "a linha digitável não fecha nos dígitos verificadores"
MOTIVO_SEM_CHAVE = "sem dados de pagamento"
MOTIVO_SEM_DOCUMENTO = ("o favorecido não está no cadastro de Contatos do ERP, "
                        "e o segmento B exige o CPF/CNPJ de quem recebe")
MOTIVO_COPIA_COLA = ("Pix copia-e-cola (BR Code): é outro produto na remessa "
                     "(QR Code), que o passo 3 ainda não monta — pague à mão")
MOTIVO_CHAVE_AMBIGUA = ("chave Pix de onze dígitos sem tipo declarado — CPF e "
                        "celular têm os dois onze, e não bate com o cadastro")
MOTIVO_JA_PAGO = "já pago"
#: O aviso "PAGAR PARA <pessoa>" manda o dinheiro para quem NÃO é o favorecido
#: do lançamento. O segmento B carrega UM par nome/documento, e os dois lados
#: vinham de origens diferentes: o nome e o documento do FORNECEDOR (do cadastro
#: de Contatos, casado pelo `paidTo`) com a chave Pix DA PESSOA. Os campos
#: 07.3B/08.3B passavam a contradizer a Informação 12, e o validador não vê —
#: ou o banco recusa o registro, ou paga sob documento de terceiro.
#: A observação equivalente ("PAGAR À MÃO") já era impedimento; o anexo não era,
#: e ainda por cima nascia MARCADO, porque a planilha o classifica como APTO.
MOTIVO_REEMBOLSO = ("reembolso: o aviso manda pagar outra pessoa, e a remessa só "
                    "sabe declarar um favorecido — pague à mão")
#: A planilha trata divergência de valor como alarme, e está certa: lá a linha
#: existe para alguém abrir o boleto e olhar. Aqui ela viraria dinheiro saindo
#: pelo valor do LANÇAMENTO, que é justamente o lado que o boleto contradiz —
#: e a janela vinha sem mostrar o motivo, a um clique de ser marcada.
MOTIVO_VALOR_DIVERGE = ("o boleto diz um valor e o lançamento diz outro — "
                        "confira o documento antes de pagar")
#: Preenchido com o número da remessa anterior: "já saiu na remessa nº 000031".
MOTIVO_JA_ENVIADO = "já saiu na remessa nº {nsa:06d} de {quando}"
MOTIVO_SEM_CONVENIO = "empresa sem convênio de remessa cadastrado"
MOTIVO_FORA_SICOOB = "a remessa CNAB 240 é do Sicoob; esta conta é de outro banco"
MOTIVO_CONTA_DESCONHECIDA = "conta não está no mapa (contas_mc.json)"

#: O "seu número" tem 20 posições no layout, e é o que o banco devolve
#: idêntico no retorno.
TAMANHO_SEU_NUMERO = 20

_OC = re.compile(r"\bOC\s*:?\s*(\d{2,7})", re.I)


# --------------------------------------------------------------------------
# Quem paga
# --------------------------------------------------------------------------
@dataclass
class Pagador:
    """A conta pagadora — é dela que sai o header do arquivo."""

    conta_erp: str
    empresa: str
    razao_social: str
    cnpj: str
    convenio: str
    agencia: str
    dv_agencia: str
    conta: str
    dv_conta: str

    def como_empresa_cnab(self):
        from cnab240 import Empresa

        return Empresa(
            nome=self.razao_social or self.empresa,
            documento=self.cnpj,
            convenio=self.convenio,
            agencia=self.agencia,
            dv_agencia=self.dv_agencia,
            conta=self.conta,
            dv_conta=self.dv_conta,
            # G012 só existe para banco cujo DV da conta tem DUAS posições
            # ("preencher com a 2ª posição deste dígito"). As do Sicoob têm
            # uma, então não há segunda e o campo fica branco — validado
            # contra o SicoobNet em 13/08/2026.
            dv_ag_conta="",
        )


def _partes(texto: str) -> tuple[str, str]:
    """"12.345-6" -> ("000000012345", "4"); "4321-0" -> ("4321", "0")."""
    limpo = re.sub(r"[^\d-]", "", texto or "")
    numero, _, dv = limpo.partition("-")
    return numero, dv


def resolver_pagador(conta_erp: str, mapa_mc, empresas) -> tuple[Pagador | None, str]:
    """A conta do ERP vira empresa + conta do Sicoob, ou o motivo de não virar.

    Usa o mapa que já existe (`contas_mc.json`) em vez de um terceiro cadastro.
    Julho de 2026 já ficou partido uma vez porque dois mapas discordavam sobre
    a mesma conta; um mapa a mais é uma divergência a mais esperando acontecer.
    """
    destino = mapa_mc.de(conta_erp) if mapa_mc else None
    if destino is None:
        return None, MOTIVO_CONTA_DESCONHECIDA
    if destino.banco.strip().upper() != "SICOOB":
        return None, MOTIVO_FORA_SICOOB

    empresa = next((e for e in (empresas or [])
                    if _chave(e.nome) == _chave(destino.empresa)), None)
    if empresa is None:
        return None, f"empresa {destino.empresa} não está no contas_sicoob.json"
    if not (getattr(empresa, "convenio", "") or "").strip():
        return None, MOTIVO_SEM_CONVENIO

    conta = next((c for c in empresa.contas
                  if _chave(c.pasta) == _chave(destino.pasta)), None)
    if conta is None:
        return None, f"a conta {destino.pasta} não está cadastrada em {empresa.nome}"

    numero, dv_conta = _partes(conta.numero)
    agencia, dv_agencia = _partes(getattr(conta, "agencia", "") or "")
    if not (numero and dv_conta and agencia):
        return None, "falta agência ou conta no cadastro da empresa"

    return Pagador(
        conta_erp=conta_erp,
        empresa=empresa.nome,
        razao_social=getattr(empresa, "razao_social", "") or empresa.nome,
        cnpj=getattr(empresa, "cnpj", "") or "",
        convenio=empresa.convenio.strip(),
        agencia=agencia,
        dv_agencia=dv_agencia,
        conta=numero,
        dv_conta=dv_conta,
    ), ""


def _chave(s: str) -> str:
    import util

    return util.norm_espaco(s or "")


# --------------------------------------------------------------------------
# O que pode sair
# --------------------------------------------------------------------------
@dataclass
class Candidato:
    """Uma linha da janela de conferência."""

    id: str
    conta_erp: str
    tipo: str                  # "Boleto" | "Pix"
    valor: float
    favorecido: str
    descricao: str
    status: str
    obs: str = ""
    codigo_barras: str = ""
    chave: str = ""
    documento_favorecido: str = ""
    forma_iniciacao: str = ""      # domínio G100 do segmento B
    seu_numero: str = ""
    marcado: bool = False
    impedimento: str = ""

    @property
    def pode(self) -> bool:
        return not self.impedimento

    @property
    def apto(self) -> bool:
        """A planilha já classificou; aqui só se lê o veredito dela."""
        return self.status.startswith("APTO")


def _seu_numero(quando: _dt.date, sequencia: int, descricao: str) -> str:
    """`260813-0007-OC5825` — data, ordem do dia e a OC, quando cabe.

    São 20 posições que **nós** definimos e o banco devolve idênticas no
    retorno; é por elas que o app reencontra o lançamento. A OC entra só para
    quem for conferir de olho, e é a primeira coisa a ser cortada.
    """
    base = f"{quando:%y%m%d}-{sequencia:04d}"
    achado = _OC.search(descricao or "")
    if achado:
        sufixo = f"-OC{achado.group(1)}"
        if len(base) + len(sufixo) <= TAMANHO_SEU_NUMERO:
            return base + sufixo
    return base


def documento_do_cadastro(registro: dict, participantes: dict | None) -> str:
    """O CPF/CNPJ do favorecido segundo o cadastro de Contatos do ERP.

    A ligação é pelo NOME (`paidTo` × `participants.name`), porque o lançamento
    não traz o id do participante. Medido em 13/08/2026: dos 300 lançamentos do
    dia, 296 casaram e todos os 296 tinham documento; as 4 sobras eram
    `paidTo` igual a "-".

    Separado do `documento_do_favorecido` de propósito: só o que veio do
    CADASTRO pode desempatar o tipo da chave. Se a resposta pudesse vir da
    própria chave, a comparação "os dígitos são o documento" confirmaria a si
    mesma, e onze dígitos de celular passariam por CPF.
    """
    nome = _chave(registro.get("favorecido") or "")
    return (participantes or {}).get(nome, "")


def documento_do_favorecido(registro: dict, participantes: dict | None) -> str:
    """O CPF/CNPJ de quem recebe: primeiro o cadastro, depois a própria chave.

    O cadastro vem primeiro porque é dado declarado, e vale para QUALQUER tipo
    de chave. A chave só entra quando ela mesma é um CPF/CNPJ — e aí é o
    próprio documento, não uma inferência.
    """
    return (documento_do_cadastro(registro, participantes)
            or documento_valido(registro.get("dados") or ""))


#: Do nome do tipo de chave (regras_pagamento) para o domínio G100 do
#: segmento B. São os mesmos cinco casos, com nomes diferentes dos dois lados.
_FORMA_POR_TIPO = {
    regras.CHAVE_TELEFONE: "01",
    regras.CHAVE_EMAIL: "02",
    regras.CHAVE_CNPJ: "03",
    regras.CHAVE_CPF: "03",
    regras.CHAVE_ALEATORIA: "04",
}


def forma_de_iniciacao(chave: str, documento_do_cadastro: str = "") -> str:
    """O código G100 da chave Pix, ou "" quando ela continua ambígua.

    O tipo declarado manda ("PIX CNPJ", "PIX CELULAR"). Quando ninguém
    declarou e sobram onze dígitos crus — CPF e celular têm os dois onze —,
    só o CADASTRO desempata: se os dígitos são o documento que o ERP tem para
    aquele favorecido, é chave CPF. Não sendo, continua ambíguo e o pagamento
    fica de fora; chutar entre os dois é escolher para quem o dinheiro vai.

    O segundo argumento tem de vir do cadastro, e não do documento já
    resolvido: usando o resolvido, uma chave que é um CPF válido confirmaria a
    si mesma e a trava dos onze dígitos deixaria de existir.
    """
    tipo = regras.tipo_de_chave_pix(chave)
    if tipo:
        return _FORMA_POR_TIPO.get(tipo, "")
    if documento_do_cadastro and re.sub(r"\D", "", chave) == documento_do_cadastro:
        return "03"
    return ""


def _impedimento(registro: dict, documento: str, forma: str) -> str:
    if registro.get("status", "").startswith("JÁ PAGO"):
        return MOTIVO_JA_PAGO
    if "PAGAR À MÃO" in (registro.get("obs") or ""):
        return MOTIVO_MAO
    if registro.get("reembolso"):
        return MOTIVO_REEMBOLSO
    if registro.get("valor_diverge"):
        return MOTIVO_VALOR_DIVERGE

    dados = (registro.get("dados") or "").strip()
    if not dados:
        return MOTIVO_SEM_CHAVE

    if registro.get("tipo") == "Boleto":
        if registro.get("parcial"):
            return MOTIVO_PARCIAL
        if not ocr_boleto.codigo_de_barras(dados):
            return MOTIVO_LINHA
        return ""

    if registro.get("tipo") == "Pix":
        # Copia-e-cola não é chave: é o BR Code inteiro, com valor e
        # beneficiário embutidos, e vira outro PRODUTO (Pix QR Code, segmento
        # J-52-Pix). Cai antes do documento porque nem chega a precisar dele.
        if regras.tipo_de_chave_pix(registro.get("dados") or "") == regras.CHAVE_COPIA_COLA:
            return MOTIVO_COPIA_COLA
        # O tipo da chave deixou de decidir: o que o segmento B exige é o
        # documento do favorecido, e ele vem do cadastro para telefone, e-mail
        # e aleatória do mesmo jeito que para CPF/CNPJ.
        if not documento:
            return MOTIVO_SEM_DOCUMENTO
        if not forma:
            return MOTIVO_CHAVE_AMBIGUA
        return ""

    return f"forma de pagamento sem remessa: {registro.get('tipo') or '?'}"


def _ja_enviado(historico, codigo_barras: str, referencia) -> str:
    """"Este boleto/lançamento já saiu numa remessa?" — "" quando não saiu.

    O histórico sabia responder isto desde que existe (`envio_de` e
    `envio_da_referencia`) e **ninguém perguntava**. A única trava contra
    repetir era o "seu número", que começa com a data do dia — logo, ela só
    pega repetição dentro do MESMO dia. Refazer o dia seguinte com o título
    ainda aberto (porque o retorno do banco não foi lido) mandava o mesmo
    boleto de novo, com NSA novo, validador limpo e nenhum alarme.

    Pergunta pelas DUAS chaves porque elas falham em situações diferentes: o
    código de barras identifica o título mesmo que o lançamento tenha sido
    recriado no ERP, e a referência (o id do lançamento) pega o Pix, que não
    tem código de barras.

    Só remessa VIVA conta — `descartar()` existe justamente para devolver o
    direito de reenviar, e o histórico já filtra isso sozinho.
    """
    if historico is None:
        return ""
    for chave, procurar in ((codigo_barras, historico.envio_de),
                            (str(referencia or ""), historico.envio_da_referencia)):
        if not chave:
            continue
        achado = procurar(chave)
        if not achado:
            continue
        remessa = achado[0]
        quando = getattr(remessa, "gerado_em", None)
        return MOTIVO_JA_ENVIADO.format(
            nsa=remessa.nsa,
            quando=f"{quando:%d/%m/%Y}" if quando else "data desconhecida")
    return ""


def preparar(contas: dict, participantes: dict | None = None,
             quando: _dt.date | None = None, historico=None) -> dict:
    """`{conta do ERP: [Candidato, ...]}` a partir do resultado da planilha.

    Recebe o `Resultado.contas` do `relatorio.montar_registros`, para que a
    remessa e a planilha não possam discordar sobre a mesma linha: as duas leem
    o mesmo veredito.

    `participantes` é o `{nome normalizado: CPF/CNPJ}` do cadastro de Contatos
    do ERP (`mc_api.listar_participantes`). Sem ele, só sai Pix cuja chave já
    seja o próprio documento.

    `historico` é o `cnab240.Historico`. Passando-o, o que já saiu numa remessa
    viva vira IMPEDIMENTO em vez de sair de novo — a trava que faltava contra
    pagar duas vezes em dias diferentes. Sem ele a função continua funcionando
    igual, e é assim que os testes de regra a chamam.
    """
    quando = quando or _dt.date.today()
    sequencia = 0
    saida: dict[str, list[Candidato]] = {}

    for conta, registros in sorted(contas.items()):
        linhas: list[Candidato] = []
        for registro in registros:
            dados = (registro.get("dados") or "").strip()
            documento = forma = ""
            if registro.get("tipo") == "Pix":
                do_cadastro = documento_do_cadastro(registro, participantes)
                documento = do_cadastro or documento_valido(dados)
                forma = forma_de_iniciacao(dados, do_cadastro)

            impedimento = _impedimento(registro, documento, forma)
            # O código de barras sai ANTES da consulta ao histórico: é ele a
            # chave natural de "este boleto já saiu?". Custa o mesmo que sairia
            # depois, e evita perguntar ao histórico com a mão vazia.
            codigo = (ocr_boleto.codigo_de_barras(dados)
                      if registro.get("tipo") == "Boleto" else "")
            if not impedimento:
                impedimento = _ja_enviado(historico, codigo, registro.get("id"))

            candidato = Candidato(
                id=str(registro.get("id") or ""),
                conta_erp=conta,
                tipo=registro.get("tipo") or "",
                valor=float(registro.get("valor") or 0),
                favorecido=registro.get("favorecido") or "",
                descricao=registro.get("descricao") or "",
                status=registro.get("status") or "",
                obs=registro.get("obs") or "",
                impedimento=impedimento,
            )
            if not impedimento:
                sequencia += 1
                candidato.seu_numero = _seu_numero(quando, sequencia,
                                                   candidato.descricao)
                if candidato.tipo == "Boleto":
                    candidato.codigo_barras = codigo
                else:
                    candidato.chave = dados
                    candidato.documento_favorecido = documento
                    candidato.forma_iniciacao = forma
                # Nasce marcado o que a planilha julgou APTO. O duvidoso pede
                # um clique — o normal segue sozinho.
                candidato.marcado = candidato.apto
            linhas.append(candidato)
        if linhas:
            saida[conta] = linhas
    return saida


# --------------------------------------------------------------------------
# O arquivo
# --------------------------------------------------------------------------
def montar_arquivo(pagador: Pagador, candidatos, nsa: int,
                   quando: _dt.date | None = None):
    """Um `ArquivoRemessa` com até dois lotes: boletos e Pix.

    Um lote só aceita um tipo de transação, mas o mesmo arquivo aceita vários
    lotes — daí um arquivo por CONTA, e não um por produto. Confirmado contra
    o SicoobNet em 13/08/2026.
    """
    from cnab240 import (ArquivoRemessa, DadosJ52, Favorecido,
                         FormaIniciacaoPix, FormaLancamento, PagamentoTitulo,
                         PixTransferencia, TipoServico)

    quando = quando or _dt.date.today()
    marcados = [c for c in candidatos if c.marcado and c.pode]
    if not marcados:
        raise ValueError(f"{pagador.conta_erp}: nenhum pagamento marcado")

    empresa = pagador.como_empresa_cnab()
    arquivo = ArquivoRemessa(empresa, nsa=nsa, data_geracao=quando)

    boletos = [c for c in marcados if c.tipo == "Boleto"]
    pix = [c for c in marcados if c.tipo == "Pix"]

    if boletos:
        lote = arquivo.novo_lote(
            "TITULOS_COBRANCA",
            tipo_servico=TipoServico.PAGAMENTO_FORNECEDOR,
            forma_lancamento=FormaLancamento.TITULO_OUTROS_BANCOS,
        )
        for c in boletos:
            lote.adicionar(PagamentoTitulo(
                valor=Decimal(str(c.valor)),
                data_pagamento=quando,
                seu_numero=c.seu_numero,
                codigo_barras=c.codigo_barras,
                nome_cedente=c.favorecido,
                # O sacado somos nós, e é o único dos três que se sabe com
                # certeza. Cedente e sacador são condicionais no layout, e o
                # que o ERP tem do fornecedor é só o nome.
                j52=DadosJ52(sacado_nome=empresa.nome,
                             sacado_documento=empresa.documento,
                             cedente_nome=c.favorecido),
            ))

    if pix:
        lote = arquivo.novo_lote(
            "PIX_TRANSFERENCIA",
            tipo_servico=TipoServico.PAGAMENTO_FORNECEDOR,
            forma_lancamento=FormaLancamento.PIX_TRANSFERENCIA,
        )
        for c in pix:
            lote.adicionar(PixTransferencia(
                valor=Decimal(str(c.valor)),
                data_pagamento=quando,
                seu_numero=c.seu_numero,
                forma_iniciacao=FormaIniciacaoPix(c.forma_iniciacao),
                # A chave é a chave — telefone, e-mail ou aleatória vão como
                # estão. O documento é campo à parte (07.3B/08.3B) e vem do
                # cadastro de Contatos, não da chave.
                chave=c.chave,
                favorecido=Favorecido(nome=c.favorecido,
                                      documento=c.documento_favorecido),
            ))

    return arquivo


def nome_do_arquivo(pagador: Pagador, nsa: int) -> str:
    """`REM_ACME_000031.REM` — legível na pasta e único por remessa."""
    empresa = re.sub(r"[^A-Za-z0-9]+", "-", pagador.empresa).strip("-").upper()
    return f"REM_{empresa}_{nsa:06d}.REM"


def referencias(candidatos) -> dict:
    """`{seu número: id do lançamento}` — o de-para que o retorno percorre."""
    return {c.seu_numero: c.id for c in candidatos
            if c.marcado and c.pode and c.seu_numero and c.id}


# --------------------------------------------------------------------------
# Onde mora o CPF/CNPJ do favorecido — a pergunta em aberto do Pix
# --------------------------------------------------------------------------
#
# O segmento B exige o documento de quem recebe (campos 07.3B e 08.3B,
# obrigatórios) em QUALQUER Pix, não só nos de chave CPF/CNPJ. Quando a chave é
# telefone, e-mail ou aleatória, esse dado tem de vir de outro lugar — e o app
# lê hoje só três campos do `overview` (`comment`, `purchaseOrder.number`,
# `documentNumber`), de um payload que traz mais.
#
# Em vez de chutar o nome do campo, varremos o que já veio na memória do
# "1. Buscar" e relatamos ONDE existe documento válido. O diagnóstico não
# imprime documento nenhum: só o caminho, em quantos lançamentos apareceu e
# **quantos valores distintos** — que é o que separa o CNPJ do fornecedor (um
# por lançamento) do CNPJ da própria empresa (o mesmo em todos).


#: Os dígitos verificadores mudaram de casa para `regras_pagamento`, que é o
#: módulo que a remessa E o relatório já importam: a planilha precisa da mesma
#: resposta para não exibir uma chave Pix que o OCR leu errado. Os nomes
#: continuam aqui porque é por eles que o resto do módulo — e os testes —
#: chamam; o que não existe mais é uma segunda implementação.
_dv_cpf = regras._dv_cpf
_dv_cnpj = regras._dv_cnpj
documento_valido = regras.documento_valido


def documentos_em(payload, prefixo: str = "") -> dict:
    """`{caminho: documento}` de todo CPF/CNPJ válido dentro do payload."""
    achados: dict[str, str] = {}
    if isinstance(payload, dict):
        for chave, valor in payload.items():
            achados.update(documentos_em(valor, f"{prefixo}.{chave}" if prefixo else str(chave)))
    elif isinstance(payload, list):
        for item in payload:                      # o índice não interessa: o
            achados.update(documentos_em(item, f"{prefixo}[]"))   # caminho, sim
    else:
        documento = documento_valido(payload)
        if documento and prefixo:
            achados[prefixo] = documento
    return achados


def diagnostico_documentos(overviews: dict) -> list[tuple[str, int, int]]:
    """`[(caminho, em quantos lançamentos, quantos valores distintos)]`.

    Ordenado pelo que mais varia: um caminho com muitos valores distintos é
    candidato a ser o documento do FORNECEDOR; um com valor único em todos os
    lançamentos é a própria empresa, e não serve para o segmento B.
    """
    onde: dict[str, list[str]] = {}
    for overview in (overviews or {}).values():
        for caminho, documento in documentos_em(overview).items():
            onde.setdefault(caminho, []).append(documento)
    return sorted(((caminho, len(vistos), len(set(vistos)))
                   for caminho, vistos in onde.items()),
                  key=lambda t: (-t[2], -t[1]))


def fora(contas_preparadas: dict) -> list[dict]:
    """O que não entra, com o motivo. Omitir não é apagar."""
    return [{"conta": c.conta_erp, "tipo": c.tipo, "valor": c.valor,
             "favorecido": c.favorecido, "descricao": c.descricao,
             "motivo": c.impedimento}
            for linhas in contas_preparadas.values() for c in linhas
            if c.impedimento]
