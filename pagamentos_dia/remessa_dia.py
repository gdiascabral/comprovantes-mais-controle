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
from pathlib import Path

from . import ocr_boleto
from . import regras_pagamento as regras

#: Motivos de impedimento, em texto que vai para a tela e para o "ficou de fora".
MOTIVO_MAO = "a observação manda pagar outra pessoa"
MOTIVO_PARCIAL = "pagamento parcial — boleto não se paga pela metade"
MOTIVO_LINHA = "a linha digitável não fecha nos dígitos verificadores"
#: A ficha de arrecadação (48 dígitos começando em 8) SAI na remessa desde
#: 30/08/2026, no produto dela: segmento O, serviço 22, forma 11.
#:
#: Ela já saiu uma vez no produto ERRADO — em 17/08/2026 duas guias viajaram
#: como título de cobrança, e o banco aceitou. A resposta de então foi excluí-la
#: (`MOTIVO_ARRECADACAO`), o que era o certo enquanto o app não sabia montar o
#: outro produto. Agora sabe, e a exclusão deixou de ser resposta: o conserto
#: de mandar no produto errado é mandar no produto certo, não deixar de mandar.
#:
#: O que SEPARA os dois continua sendo o formato da linha, e não o favorecido:
#: a conversão para 44 dígitos não denuncia nada, porque a ficha converte como
#: qualquer boleto.

#: A exceção, e é uma só: o Sicoob ainda não aceita pagar esta concessionária
#: por arrecadação. Fica aqui como REGRA NOMEADA, e não espalhada numa
#: condição, porque o dia em que o banco aceitar isto é uma linha a remover —
#: some a tupla, some o motivo, e nada mais no módulo precisa saber.
#:
#: Casa por PEDAÇO do nome, sem acento e sem caixa, como o resto do app compara
#: favorecido (`_chave`): o ERP escreve o nome da concessionária de mais de um
#: jeito, e exigir igualdade exata deixaria a exceção passar batido.
ARRECADACAO_NAO_ACEITA = ("SANESC",)
MOTIVO_SANESC = "SANESC — o Sicoob ainda não aceita; pague à parte"

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
#:
#: Desde 19/08/2026 isto deixou de ser o impedimento de TODO reembolso: quando
#: o `reembolso.identificar` acha nome e documento DA PESSOA — na mesma fonte,
#: para não se contradizerem —, o segmento B declara ela dos dois lados e o
#: pagamento sai. O que sobra aqui é a rede de baixo, para o registro que
#: chegou sem passar por aquela decisão; não achando quem recebe, o motivo
#: vem de lá e diz o que falta.
MOTIVO_REEMBOLSO = ("reembolso: não se descobriu quem recebe, e a remessa só "
                    "sabe declarar um favorecido — pague à mão")
#: A planilha trata divergência de valor como alarme, e está certa: lá a linha
#: existe para alguém abrir o boleto e olhar. Aqui ela viraria dinheiro saindo
#: pelo valor do LANÇAMENTO, que é justamente o lado que o boleto contradiz —
#: e a janela vinha sem mostrar o motivo, a um clique de ser marcada.
MOTIVO_VALOR_DIVERGE = ("o boleto diz um valor e o lançamento diz outro — "
                        "confira o documento antes de pagar")
#: Preenchido com o número da remessa anterior: "já saiu na remessa nº 000031".
MOTIVO_JA_ENVIADO = "já saiu na remessa nº {nsa:06d} de {quando}"
#: O convênio é da CONTA, não da empresa (04/09/2026): o Sicoob dá um por
#: conta corrente, e uma holding daqui tem nove — a principal e oito
#: subcontas. Vazio é o estado normal de quem ainda não aderiu, e por isso o
#: recado diz os DOIS passos: a adesão é no banco, o número é no painel.
MOTIVO_SEM_CONVENIO = ("esta conta não tem convênio de remessa cadastrado — "
                       "faça a adesão no SicoobNet e cadastre o número no "
                       "painel")
MOTIVO_FORA_SICOOB = "a remessa CNAB 240 é do Sicoob; esta conta é de outro banco"
#: Conta COM banco em branco no `contas_mc.json` caía no motivo acima — e
#: "esta conta é de outro banco" manda conferir o banco errado: não há outro
#: banco, há um campo vazio. O motivo próprio diz onde consertar.
MOTIVO_SEM_BANCO = ("conta sem banco no cadastro (contas_mc.json) — "
                    "corrija no painel")
MOTIVO_CONTA_DESCONHECIDA = "conta não está no mapa (contas_mc.json)"
#: Duas contas da MESMA empresa na MESMA pasta e nenhum `sufixo` para separá-las:
#: o app não tem como saber de qual delas o dinheiro sai, e escolher a primeira
#: é pagar pela conta errada com header, pasta e nome de arquivo idênticos aos
#: da certa — nada denunciaria. Recusar é a única falha aceitável aqui.
MOTIVO_CONTA_AMBIGUA = ("há mais de uma conta nesta pasta e o sufixo não "
                        "desempata — cadastre o sufixo no painel")

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

    **A conta pagadora é achada por pasta E `sufixo`.** Só pela pasta não
    serve: há empresa no cadastro com QUATRO contas Sicoob na mesma pasta
    "SICOOB", e o que as separa é o `sufixo` — o mesmo campo, com o mesmo
    nome, dos dois lados (`contas_mc.Destino` e `sicoob_contas.Conta`), que já
    desempata o nome do arquivo do extrato. Enquanto ele era ignorado, as
    quatro viravam a MESMA conta pagadora: o dinheiro sairia de uma conta que
    ninguém escolheu, e header, pasta e nome de arquivo ficavam idênticos aos
    da conta certa — não havia o que conferir depois. O sufixo só é cobrado
    quando há mais de uma candidata; a empresa de uma conta por pasta, que é a
    maioria, continua resolvendo sem cadastrar nada.

    **O convênio vem da CONTA, e sem herança.** Ele morava na empresa, e para
    empresa de uma conta só isso dava no mesmo — até 04/09/2026, quando os
    números foram lidos no SicoobNet e o desenho apareceu: o Sicoob dá um
    convênio por CONTA CORRENTE, e uma holding daqui tem nove, a principal e
    oito subcontas. Por isso a checagem desceu para depois de a conta estar
    escolhida, e por isso não existe `or empresa.convenio`: herdar faria uma
    subconta ainda não aderida sair com o número da principal, e o convênio é
    o campo 07.0 do header e o nome da sequência do NSA. O desfecho bom disso
    é o banco recusar o arquivo — e o NSA já foi queimado, porque ele entra no
    conteúdo antes de o arquivo existir.
    """
    destino = mapa_mc.de(conta_erp) if mapa_mc else None
    if destino is None:
        return None, MOTIVO_CONTA_DESCONHECIDA
    if not destino.banco.strip():
        return None, MOTIVO_SEM_BANCO
    if destino.banco.strip().upper() != "SICOOB":
        return None, MOTIVO_FORA_SICOOB

    empresa = next((e for e in (empresas or [])
                    if _chave(e.nome) == _chave(destino.empresa)), None)
    if empresa is None:
        return None, f"empresa {destino.empresa} não está no contas_sicoob.json"

    candidatas = [c for c in empresa.contas
                  if _chave(c.pasta) == _chave(destino.pasta)]
    if len(candidatas) > 1:
        candidatas = [c for c in candidatas
                      if _chave(c.sufixo or "") == _chave(destino.sufixo or "")]
    if not candidatas:
        return None, f"a conta {destino.pasta} não está cadastrada em {empresa.nome}"
    if len(candidatas) > 1:
        return None, MOTIVO_CONTA_AMBIGUA
    conta = candidatas[0]

    # A checagem do convênio vem DEPOIS de achar a conta, e não podia vir
    # antes: é a conta que tem convênio, e antes daqui não há conta para
    # perguntar. Nunca `or empresa.convenio` — herdar é o caminho para uma
    # subconta ainda não aderida sair com o número da principal, e o desfecho
    # bom disso é o banco recusar o arquivo depois de o NSA ter sido queimado.
    convenio = (getattr(conta, "convenio", "") or "").strip()
    if not convenio:
        return None, MOTIVO_SEM_CONVENIO

    numero, dv_conta = _partes(conta.numero)
    agencia, dv_agencia = _partes(getattr(conta, "agencia", "") or "")
    if not (numero and dv_conta and agencia):
        return None, "falta agência ou conta no cadastro da empresa"

    return Pagador(
        conta_erp=conta_erp,
        empresa=empresa.nome,
        razao_social=getattr(empresa, "razao_social", "") or empresa.nome,
        cnpj=getattr(empresa, "cnpj", "") or "",
        convenio=convenio,
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
    #: Ficha de arrecadação (48 dígitos começando em 8): vai no segmento O,
    #: não no J. O `tipo` continua "Boleto" porque é o que a planilha
    #: classificou e é por ele que a tela agrupa — o que muda é o PRODUTO.
    arrecadacao: bool = False
    #: Só o boleto bancário tem: sai do fator de vencimento do código de
    #: barras. Ficha de arrecadação não carrega o campo, e fica None.
    vencimento: "_dt.date | None" = None
    #: As duas colunas que a conferência mostra e que só existiam dentro da
    #: `descricao`, coladas com o resto. Quem confere procura por OC e por
    #: centro de custo — em coluna, não no meio de uma frase.
    oc: str = ""
    centro_custo: str = ""
    chave: str = ""
    documento_favorecido: str = ""
    forma_iniciacao: str = ""      # domínio G100 do segmento B
    seu_numero: str = ""
    marcado: bool = False
    impedimento: str = ""
    #: Esta linha paga QUEM NÃO É o favorecido do lançamento — o `favorecido`
    #: acima já é o da pessoa, não o do fornecedor. A tela precisa saber para
    #: dizer isso em voz alta, e é por isso que a linha nasce desmarcada.
    reembolso: bool = False
    reembolso_origem: str = ""     # de onde saiu o documento da pessoa
    #: O favorecido do LANÇAMENTO — o fornecedor que o reembolso devolve.
    #: Guardado porque o `favorecido` acima deixou de ser ele, e sem este
    #: campo a tela não teria como dizer de que compra o reembolso veio.
    reembolso_de: str = ""
    #: "já saiu na remessa nº 000001 de 17/08/2026" — vazio quando não saiu.
    #: Era `impedimento`, e a linha vinha sem caixa: reenviar UM pagamento
    #: obrigava a `descartar()` a remessa inteira. Virou aviso porque o envio
    #: anterior falha de verdade (arquivo recusado, pagamento que não caiu), e
    #: aí este pagamento precisa ir de novo. A linha nasce desmarcada.
    ja_enviado: str = ""

    @property
    def pode(self) -> bool:
        return not self.impedimento

    @property
    def apto(self) -> bool:
        """A planilha já classificou; aqui só se lê o veredito dela."""
        return self.status.startswith("APTO")


_SEQ = re.compile(r"^(\d{6})-(\d{4})")


def _itens_de(remessa) -> list:
    """Os itens de uma remessa, venha ela da nuvem ou do espelho local.

    São duas formas para a mesma coisa, e ler só uma delas é ler zero item na
    outra — sem erro, sem aviso: a nuvem (`nuvem.registro.Registro.remessas`,
    que o `Espelhado` repassa e é o que o app usa) devolve DICT com a chave
    `remessa_item`; o `cnab240.Historico` devolve objeto `RemessaGerada` com
    `.itens`. Enquanto isto lia só `.itens`, a conferência do "seu número"
    devolvia 0 contra o registro de verdade.

    O mesmo par de nomes já é aceito em `retorno_dia._itens_da_remessa`, pelo
    mesmo motivo.
    """
    if isinstance(remessa, dict):
        return list(remessa.get("remessa_item") or remessa.get("itens") or [])
    return list(getattr(remessa, "remessa_item", None)
                or getattr(remessa, "itens", None) or [])


def _seu_numero_de(item) -> str:
    """O "seu número" do item, dict (nuvem) ou objeto (espelho local)."""
    if isinstance(item, dict):
        return str(item.get("seu_numero") or "")
    return str(getattr(item, "seu_numero", "") or "")


def sequencia_ja_usada(historico, quando: _dt.date) -> int:
    """A maior ordem do DIA que já saiu em alguma remessa viva. 0 se nenhuma.

    O "seu número" nasce `260820-0007`, e a ordem recomeçava do 1 a cada
    geração. Isso bastava enquanto o dia tinha uma remessa só. Em 20/08/2026 o
    reenvio passou a ser possível, e a segunda remessa do dia repetiu QUATRO
    números da primeira (`260820-0007` a `260820-0010`).

    Não é detalhe de numeração: o "seu número" é o que o banco devolve no
    retorno para casar cada pagamento. Repetido, ele casa com o pagamento
    errado — e foi por isso que o espelho local recusou a remessa nº 000003
    daquele dia, enquanto a nuvem a aceitou.

    Nunca levanta: registro fora do ar devolve 0, e a numeração volta a ser a
    de antes. Perder a remessa por causa da conferência seria pior.

    Lê as DUAS formas de remessa (`_itens_de`) porque a proteção só vale se
    enxergar o registro de verdade: contra a nuvem, que devolve dicts, ela
    devolvia 0 calada — e 0 aqui é a segunda remessa do dia recomeçando em
    0001 e repetindo os "seus números" da primeira.
    """
    if historico is None:
        return 0
    prefixo = f"{quando:%y%m%d}-"
    maior = 0
    try:
        for remessa in historico.remessas():
            for item in _itens_de(remessa):
                seu = _seu_numero_de(item)
                if not seu.startswith(prefixo):
                    continue
                achado = _SEQ.match(seu)
                if achado:
                    maior = max(maior, int(achado.group(2)))
    except Exception:
        return 0
    return maior


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


def arrecadacao_recusada(favorecido: str) -> str:
    """O motivo de esta ficha não poder sair, ou "" quando pode.

    Uma função, e não um `if` dentro do `_impedimento`, porque é ela que os
    testes apontam e é ela que some inteira quando o banco passar a aceitar."""
    alvo = _chave(favorecido)
    if any(_chave(nome) in alvo for nome in ARRECADACAO_NAO_ACEITA):
        return MOTIVO_SANESC
    return ""


def _impedimento(registro: dict, documento: str, forma: str) -> str:
    if registro.get("status", "").startswith("JÁ PAGO"):
        return MOTIVO_JA_PAGO
    if "PAGAR À MÃO" in (registro.get("obs") or ""):
        return MOTIVO_MAO
    if registro.get("reembolso"):
        # Não é mais "reembolso não sai". É "reembolso sai declarando a
        # PESSOA, quando se sabe quem ela é" — e quem sabe disso é o
        # `reembolso.identificar`, que já rodou na planilha. Aqui só se lê o
        # veredito dele: redescobri-lo seria uma segunda regra sobre a mesma
        # linha, e duas regras sobre a mesma linha divergem.
        if registro.get("reembolso_impedimento"):
            return registro["reembolso_impedimento"]
        if not (registro.get("reembolso_nome")
                and registro.get("reembolso_documento")):
            return MOTIVO_REEMBOLSO
    if registro.get("valor_diverge"):
        return MOTIVO_VALOR_DIVERGE

    dados = (registro.get("dados") or "").strip()
    if not dados:
        return MOTIVO_SEM_CHAVE

    if registro.get("tipo") == "Boleto":
        if registro.get("parcial"):
            return MOTIVO_PARCIAL
        # A ficha de arrecadação CONVERTE para 44 dígitos como qualquer boleto,
        # então a conversão não a denuncia — quem a separa é o formato da linha.
        # A separação continua valendo; o que mudou foi o desfecho: em vez de
        # sair da remessa, ela vai para o lote do produto dela.
        if ocr_boleto.eh_arrecadacao(dados):
            return arrecadacao_recusada(registro.get("favorecido") or "")
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
    # Continua de onde o dia parou, em vez de recomeçar do 1: duas remessas
    # no mesmo dia não podem repetir "seu número".
    sequencia = sequencia_ja_usada(historico, quando)
    saida: dict[str, list[Candidato]] = {}

    for conta, registros in sorted(contas.items()):
        linhas: list[Candidato] = []
        for registro in registros:
            dados = (registro.get("dados") or "").strip()
            # O documento do favorecido vale para os DOIS produtos. No Pix ele
            # é obrigatório (segmento B, 07.3B/08.3B) e decide se a linha sai;
            # no boleto ele identifica o CEDENTE no J-52, e a falta dele não
            # impede o pagamento — só empobrece o arquivo. Resolver aqui, e não
            # dentro do ramo do Pix, é o que faz o boleto parar de sair com a
            # inscrição do cedente zerada.
            # Quem recebe. No reembolso NÃO é o favorecido do lançamento: o
            # aviso "PAGAR PARA" manda o dinheiro para outra pessoa, e o
            # segmento B tem de declarar ELA nos dois campos. Nome e documento
            # trocam JUNTOS, e só quando vieram juntos da mesma fonte — meia
            # troca reconstruiria exatamente a contradição que fechou o
            # reembolso (nome de um, documento de outro).
            e_reembolso = bool(registro.get("reembolso"))
            if e_reembolso and registro.get("reembolso_documento"):
                favorecido = registro.get("reembolso_nome") or ""
                do_cadastro = registro.get("reembolso_documento") or ""
            else:
                favorecido = registro.get("favorecido") or ""
                do_cadastro = documento_do_cadastro(registro, participantes)
            # O cadastro não garante documento que FECHA. A remessa recusada em
            # 20/08/2026 saiu com um favorecido cadastrado com CPF de
            # preenchimento — onze dígitos, DV que não fecha — e o banco
            # devolveu o arquivo inteiro ("campo Número de Inscrição do
            # Favorecido, possui valor inválido"). Onze dígitos era a única
            # conferência no caminho: `TipoInscricao.por_documento` mede o
            # TAMANHO para escolher entre CPF e CNPJ, não o dígito verificador,
            # e daí em diante ninguém mais perguntou.
            #
            # Conferir aqui, e não dentro do ramo do Pix, é o que faz o
            # documento inválido virar IMPEDIMENTO em vez de virar arquivo: o
            # `_impedimento` só sabe testar se o documento EXISTE, e um CPF de
            # preenchimento existe. Vale também para o boleto, onde ele
            # identifica o cedente no J-52 — lá branco já era aceito, e branco é
            # melhor que um documento que aponta para ninguém.
            do_cadastro = documento_valido(do_cadastro)
            documento = forma = ""
            if registro.get("tipo") == "Pix":
                documento = do_cadastro or documento_valido(dados)
                forma = forma_de_iniciacao(dados, do_cadastro)

            impedimento = _impedimento(registro, documento, forma)
            # O código de barras sai ANTES da consulta ao histórico: é ele a
            # chave natural de "este boleto já saiu?". Custa o mesmo que sairia
            # depois, e evita perguntar ao histórico com a mão vazia.
            codigo = (ocr_boleto.codigo_de_barras(dados)
                      if registro.get("tipo") == "Boleto" else "")
            # Não vira impedimento: vira aviso. Só se pergunta ao histórico
            # quando nada mais barra a linha — perguntar antes seria enfeitar
            # com "já saiu" uma linha que não ia sair de qualquer jeito.
            ja_enviado = ("" if impedimento else
                          _ja_enviado(historico, codigo, registro.get("id")))

            candidato = Candidato(
                # Fora do `if not impedimento` de propósito: é o PRODUTO da
                # linha, e não o veredito sobre ela. A ficha recusada continua
                # sendo ficha, e a conferência precisa dizer isso ao lado do
                # motivo — senão "o Sicoob ainda não aceita" fica sem sujeito.
                arrecadacao=(registro.get("tipo") == "Boleto"
                             and ocr_boleto.eh_arrecadacao(dados)),
                oc=str(registro.get("oc") or ""),
                centro_custo=str(registro.get("centro_custo") or ""),
                id=str(registro.get("id") or ""),
                conta_erp=conta,
                tipo=registro.get("tipo") or "",
                valor=float(registro.get("valor") or 0),
                favorecido=favorecido,
                descricao=registro.get("descricao") or "",
                status=registro.get("status") or "",
                obs=registro.get("obs") or "",
                impedimento=impedimento,
                ja_enviado=ja_enviado,
                reembolso=e_reembolso,
                reembolso_origem=registro.get("reembolso_origem") or "",
                reembolso_de=(registro.get("favorecido") or "") if e_reembolso else "",
            )
            if not impedimento:
                sequencia += 1
                candidato.seu_numero = _seu_numero(quando, sequencia,
                                                   candidato.descricao)
                if candidato.tipo == "Boleto":
                    candidato.codigo_barras = codigo
                    # `vencimento_da_linha` já devolve None para a ficha: só o
                    # boleto bancário carrega o fator de vencimento.
                    candidato.vencimento = ocr_boleto.vencimento_da_linha(dados)
                    # Identifica o cedente no J-52. Vazio não impede o
                    # pagamento — o boleto se paga pelo código de barras —,
                    # mas quem abrir o arquivo depois não descobre quem
                    # recebeu, e foi essa a queixa da primeira remessa real.
                    candidato.documento_favorecido = do_cadastro
                else:
                    candidato.chave = dados
                    candidato.documento_favorecido = documento
                    candidato.forma_iniciacao = forma
                # Nasce marcado o que a planilha julgou APTO. O duvidoso pede
                # um clique — o normal segue sozinho.
                #
                # O reembolso é a exceção, e é APTO ("APTO* (reembolso)"): é a
                # única linha em que o app TROCA o favorecido por conta
                # própria, e quem confere o total não tem como perceber isso
                # sozinho. Um clique explícito é o preço de o dinheiro ir para
                # alguém que não é o favorecido do lançamento.
                #
                # O reenvio nasce desmarcado pela mesma razão, e mais forte:
                # ali marcar é o MESMO pagamento saindo duas vezes.
                candidato.marcado = (candidato.apto and not e_reembolso
                                     and not ja_enviado)
            linhas.append(candidato)
        if linhas:
            saida[conta] = linhas
    return saida


# --------------------------------------------------------------------------
# O arquivo
# --------------------------------------------------------------------------
#: 40 posições, campo 18.1 (G031) do header de lote.
TAMANHO_MENSAGEM_LOTE = 40


def etiqueta_do_banco(c) -> str:
    """O texto que a tela de pendências do banco vai mostrar nesta linha.

    É a descrição da planilha — o jeito como o dono reconhece o pagamento.
    Medido em 20/08/2026, na remessa 000003: o boleto ocupava esse espaço com
    o nome do fornecedor (campo `09.3J`, 30 posições) e o Pix não ocupava
    nada (as 38 primeiras de `24.3A` iam em branco), então metade das linhas
    chegava ao banco sem dizer coisa alguma.

    Descrição vazia cai para o nome do fornecedor: em branco, a coluna não
    identificaria nada, e a linha ficaria pior do que era antes.

    Quem recebe de verdade NÃO depende disto: o boleto é roteado pelo código
    de barras e o Pix pela chave. A identidade continua no J-52 (nome e
    documento do cedente) e, no Pix, no campo 15.3A.
    """
    return (c.descricao or "").strip() or c.favorecido


def _mensagem_do_lote(quando: _dt.date) -> str:
    """O único texto livre que o layout oferece para um lote de boletos.

    O segmento J **não tem campo de descrição** — os 40 caracteres do header
    de lote são tudo que existe, e saíam em branco. Não dá para descrever
    pagamento por pagamento (o Internet Banking mostra, como "Observação", o
    nome do cedente do próprio título), mas dá para dizer de onde o lote veio,
    que é o que faltava para quem abre a tela do banco e não reconhece o
    arquivo.
    """
    return f"PAGAMENTOS DO DIA {quando:%d/%m/%Y}"[:TAMANHO_MENSAGEM_LOTE]


def montar_arquivo(pagador: Pagador, candidatos, nsa: int,
                   quando: _dt.date | None = None):
    """Um `ArquivoRemessa` com até TRÊS lotes: boletos, arrecadação e Pix.

    Um lote só aceita um tipo de transação, mas o mesmo arquivo aceita vários
    lotes — daí um arquivo por CONTA, e não um por produto. Confirmado contra
    o SicoobNet em 13/08/2026.

    A ficha de arrecadação é o terceiro, e é lote SEPARADO por exigência do
    layout, não por organização: ela muda o header do lote inteiro (serviço 22
    e forma 11, seção 9.1 do guia v3.3), e header é por lote. Mandá-la junto
    dos boletos foi o erro de 17/08/2026.
    """
    from cnab240 import (ArquivoRemessa, DadosJ52, Favorecido,
                         FormaIniciacaoPix, FormaLancamento, PagamentoConvenio,
                         PagamentoTitulo, PixTransferencia, TipoServico)

    quando = quando or _dt.date.today()
    marcados = [c for c in candidatos if c.marcado and c.pode]
    if not marcados:
        raise ValueError(f"{pagador.conta_erp}: nenhum pagamento marcado")

    empresa = pagador.como_empresa_cnab()
    arquivo = ArquivoRemessa(empresa, nsa=nsa, data_geracao=quando)

    boletos = [c for c in marcados if c.tipo == "Boleto" and not c.arrecadacao]
    fichas = [c for c in marcados if c.tipo == "Boleto" and c.arrecadacao]
    pix = [c for c in marcados if c.tipo == "Pix"]

    if boletos:
        lote = arquivo.novo_lote(
            "TITULOS_COBRANCA",
            tipo_servico=TipoServico.PAGAMENTO_FORNECEDOR,
            forma_lancamento=FormaLancamento.TITULO_OUTROS_BANCOS,
            mensagem=_mensagem_do_lote(quando),
        )
        for c in boletos:
            lote.adicionar(PagamentoTitulo(
                valor=Decimal(str(c.valor)),
                data_pagamento=quando,
                seu_numero=c.seu_numero,
                codigo_barras=c.codigo_barras,
                # 30 posições que o Internet Banking mostra como "Observação"
                # — o único texto nosso que aparece na linha do boleto.
                nome_cedente=etiqueta_do_banco(c),
                # O vencimento sai do PRÓPRIO código de barras (fator de
                # vencimento), e não do ERP: é o dado que o banco emitiu, já
                # conferido por dígito verificador. Saía zerado à toa. Ficha
                # de arrecadação não tem o campo, e aí continua None.
                vencimento=c.vencimento,
                # Sacado somos nós; cedente é quem recebe. O documento do
                # cedente vem do cadastro de Contatos do ERP — antes ficava
                # zerado porque só o Pix consultava o cadastro, e o J-52 saía
                # com "quem recebe" pela metade: nome sim, inscrição 0.
                # Sacador não existe nestes pagamentos (é o avalista/terceiro),
                # e inventar um seria pior que deixá-lo em branco.
                j52=DadosJ52(sacado_nome=empresa.nome,
                             sacado_documento=empresa.documento,
                             cedente_nome=c.favorecido,
                             cedente_documento=c.documento_favorecido),
            ))

    if fichas:
        # Serviço 22 e forma 11: os dois vêm da seção 9 do guia, e os dois
        # moram no HEADER — é por isso que a ficha não cabe no lote do boleto.
        lote = arquivo.novo_lote(
            "CONVENIOS_COM_CODIGO_BARRAS",
            tipo_servico=TipoServico.CONTAS_TRIBUTOS_IMPOSTOS,
            forma_lancamento=FormaLancamento.CONTAS_TRIBUTOS_COD_BARRAS,
            mensagem=_mensagem_do_lote(quando),
        )
        for c in fichas:
            lote.adicionar(PagamentoConvenio(
                valor=Decimal(str(c.valor)),
                data_pagamento=quando,
                seu_numero=c.seu_numero,
                codigo_barras=c.codigo_barras,
                # 09.3O, 30 posições: é o nome que aparece no extrato e no
                # Internet Banking. O favorecido do lançamento É a
                # concessionária — não há segundo cadastro a consultar.
                nome_concessionaria=c.favorecido,
                # 10.3O é "Data do Vencimento (Nominal)". A ficha de
                # arrecadação NÃO carrega vencimento no código de barras (só o
                # boleto bancário tem fator de vencimento), então aqui vai
                # None e o campo sai zerado — que é o que o layout espera de
                # um campo nominal que não se conhece. Inventar a data de hoje
                # seria afirmar um vencimento que ninguém verificou.
                vencimento=c.vencimento,
            ))

    if pix:
        lote = arquivo.novo_lote(
            "PIX_TRANSFERENCIA",
            tipo_servico=TipoServico.PAGAMENTO_FORNECEDOR,
            forma_lancamento=FormaLancamento.PIX_TRANSFERENCIA,
            mensagem=_mensagem_do_lote(quando),
        )
        for c in pix:
            lote.adicionar(PixTransferencia(
                valor=Decimal(str(c.valor)),
                data_pagamento=quando,
                seu_numero=c.seu_numero,
                forma_iniciacao=FormaIniciacaoPix(c.forma_iniciacao),
                mensagem=etiqueta_do_banco(c),
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


def _nome_de_pasta(texto: str, se_vazio: str) -> str:
    r"""Um pedaço de nome que o Windows aceita como pasta.

    Tira `\ / : * ? " < > |`, que o sistema recusa, e ponto ou espaço no fim,
    que ele aceita criar e depois não consegue abrir."""
    limpo = re.sub(r'[\/:*?"<>|]+', " ", (texto or "")).strip(" .")
    limpo = re.sub(r"\s{2,}", " ", limpo)
    return limpo[:60] or se_vazio


def pasta_do_pagador(destino, pagador: Pagador) -> "Path":
    """`<destino>/<EMPRESA>/SICOOB <ag>-<conta>` — uma pasta por conta pagadora.

    Cada conta gera o SEU arquivo, e misturá-los numa pasta só era um convite
    a subir o arquivo de uma conta no acesso de outra: os nomes são parecidos,
    o NSA é sequencial por convênio e a conferência acontece no SicoobNet,
    depois do envio. Separado, a pasta aberta já é a resposta.

    Dois níveis, e não um nome comprido: uma empresa costuma ter mais de uma
    conta, e é a empresa que se procura primeiro.

    "SICOOB" no nome não é enfeite nem chute: a remessa CNAB 240 do app é do
    Sicoob (ver `MOTIVO_FORA_SICOOB`), e escrever o banco deixa a pasta pronta
    para o dia em que houver outro.
    """
    empresa = _nome_de_pasta(pagador.empresa, "EMPRESA")
    conta = _nome_de_pasta(f"SICOOB {pagador.agencia}-{pagador.conta}".strip(),
                           "SICOOB")
    return Path(destino) / empresa / conta


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


#: Não é impedimento: é escolha de quem conferiu. Sai na mesma lista porque a
#: lista responde "o que NÃO foi pago hoje", e para quem lê depois tanto faz
#: se a linha caiu por regra ou por decisão — some do arquivo do mesmo jeito.
MOTIVO_DESMARCADO = "você desmarcou na conferência"


def fora(contas_preparadas: dict) -> list[dict]:
    """O que não entra, com o motivo. Omitir não é apagar.

    Duas famílias, e a distinção importa: a linha IMPEDIDA nunca teve caixa
    para marcar, e a DESMARCADA foi tirada à mão. Até 19/08/2026 só a primeira
    era relatada — a segunda sumia calada, que é exatamente o defeito que esta
    função existe para não deixar acontecer. A janela mostrava, o fechamento
    levava junto, e nada em lugar nenhum dizia que aquele pagamento não saiu.
    """
    return [{"conta": c.conta_erp, "tipo": c.tipo, "valor": c.valor,
             "favorecido": c.favorecido, "descricao": c.descricao,
             "motivo": c.impedimento or MOTIVO_DESMARCADO}
            for linhas in contas_preparadas.values() for c in linhas
            if c.impedimento or not c.marcado]
