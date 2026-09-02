# -*- coding: utf-8 -*-
"""Costura as peças: recebimentos -> imóveis -> obra -> contrato -> destino.

Não sabe que existe interface. Recebe a `MCApi` de uma sessão aberta e devolve
uma lista de `Achado` — um por casa financiada no mês, cada um dizendo o que
foi resolvido e o que faltou.

`revisao` é campo de primeira classe, não exceção: uma casa sem contrato, sem
obra ou sem empresa é um resultado normal do mês, e a aba mostra o motivo. Só
erro de infraestrutura (sessão caída, API fora) sobe como exceção.

A ordem das duas metades tem uma razão prática: o `downloadUrl` dos anexos é
URL pré-assinada do S3 com `Expires` curto, então **listar e baixar têm de
acontecer na mesma execução**. Por isso `levantar()` só monta a lista e
`arquivar()` baixa logo em seguida, em vez de guardar URLs para depois.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import util

from . import conferencia as conf
from .destino import (caminho_longo, empresa_de, nome_arquivo,
                      pasta_do_contrato)
from .escolha import contrato_de
from .regras import Imovel, imoveis_do_mes


@dataclass
class Achado:
    """Uma casa financiada no mês, com tudo que se sabe dela."""

    imovel: Imovel
    obra_id: str = ""
    cliente_erp: str = ""
    empresa: str = ""
    endereco: dict = field(default_factory=dict)
    anexo: dict = field(default_factory=dict)
    #: Todos os anexos da obra, como vieram do ERP. É o que a janela de
    #: resolver mostra quando o app não soube escolher sozinho — antes esta
    #: lista era lida e jogada fora, e a pessoa ficava sem saída pela tela.
    anexos_da_obra: list = field(default_factory=list)
    destino: Path | None = None
    revisao: str = ""
    #: Entra nesta rodada de arquivamento. Quem decide é a aba (a marcação da
    #: tabela); o padrão é False para ninguém arquivar por esquecimento.
    marcado: bool = False
    contrato_manual: bool = False
    empresa_manual: bool = False
    resultado_conferencia: dict = field(default_factory=dict)
    arquivado: bool = False

    @property
    def contrato(self) -> str:
        return (self.anexo or {}).get("filename", "")

    @property
    def resumo(self) -> str:
        i = self.imovel
        return (f"{i.obra} {i.rotulo} · {i.comprador} · "
                f"R$ {i.valor_financiamento:,.2f}")


def _garantir_acesso(api, log=print) -> None:
    """Deixa a API pronta para os DOIS back-ends antes da primeira leitura.

    Os recebimentos saem de um; as obras, os anexos e o contrato saem do
    outro — e o cabeçalho de autenticação de cada um só passa a existir depois
    que o navegador faz uma requisição de verdade naquela tela.

    A garantia mora aqui, e não na aba, porque quem sabe que precisa dos dois é
    este módulo: a aba anunciava "Preparando o acesso aos anexos..." e não
    preparava nada, e a busca morria em "Credenciais de anexos ainda não
    capturadas" logo depois de "Lendo as obras..." — mensagem que não diz o que
    fazer e some do caminho de quem só queria os contratos do mês."""
    if not api.garantir_credenciais_anexos(log):
        raise RuntimeError(
            "não consegui preparar o acesso ao cadastro de obras e anexos do "
            "Mais Controle.\n"
            "Abra a tela de Pagamentos no Chrome, entre em um pagamento "
            "qualquer e rode de novo.")


def _primeiro_dia(ano: int, mes: int) -> str:
    return f"{ano:04d}-{mes:02d}-01"


def _ultimo_dia(ano: int, mes: int) -> str:
    import calendar
    return f"{ano:04d}-{mes:02d}-{calendar.monthrange(ano, mes)[1]:02d}"


def levantar(api, ano: int, mes: int, empresas, log=print,
             cancelar=None) -> list[Achado]:
    """Passo 1: quem financiou, qual o contrato e para qual empresa vai.

    Não baixa nem grava nada. É o que a aba mostra ANTES de o usuário mandar
    arquivar — e é onde um erro do mapa cliente→empresa aparece."""
    _garantir_acesso(api, log)
    inicio, fim = _primeiro_dia(ano, mes), _ultimo_dia(ano, mes)
    log(f"Lendo os recebimentos de {inicio} a {fim}...")
    registros = api.listar_recebimentos(inicio, fim, log)

    if not registros:
        log("Nenhum recebimento de venda no período.")
        log("Confira o mês: isso costuma ser filtro errado, não mês parado.")
        return []

    imoveis = imoveis_do_mes(registros, log)
    if not imoveis:
        log(f"{len(registros)} recebimento(s) de venda, nenhum com "
            "financiamento. Vazio é resposta, não falha.")
        return []
    log(f"{len(imoveis)} casa(s) com financiamento recebido no mês.")

    log("Lendo as obras...")
    obras = api.listar_obras(log)
    por_nome = {util.norm_espaco(o.get("name")): o for o in obras}

    achados = [Achado(imovel=i, revisao=i.revisao) for i in imoveis]

    # Só as obras que interessam, e uma vez cada (o mesmo lote tem 2 casas).
    ids: list[str] = []
    for a in achados:
        if a.revisao:
            continue
        obra = por_nome.get(util.norm_espaco(a.imovel.obra))
        if obra is None:
            a.revisao = (f"não achei a obra \"{a.imovel.obra}\" no cadastro "
                         "do Mais Controle")
            continue
        a.obra_id = obra.get("id") or ""
        a.cliente_erp = ((obra.get("customer") or {}).get("name") or "").strip()
        if a.obra_id and a.obra_id not in ids:
            ids.append(a.obra_id)

    if not ids:
        return achados

    log(f"Lendo os anexos de {len(ids)} obra(s)...")
    anexos_por_obra = api.anexos_de_obras(ids, log, cancelar=cancelar)

    for a in achados:
        if a.revisao or not a.obra_id:
            continue
        a.anexos_da_obra = anexos_por_obra.get(a.obra_id) or []
        anexo, motivo = contrato_de(a.anexos_da_obra, a.imovel.unidade)
        if anexo is None:
            a.revisao = motivo
        else:
            a.anexo = anexo

        # A empresa é resolvida mesmo sem contrato: as duas pendências são
        # independentes, e a janela de resolver só deve perguntar o que
        # realmente falta.
        empresa = empresa_de(a.cliente_erp, empresas)
        if empresa is None:
            a.revisao = a.revisao or _sem_empresa(a.cliente_erp)
        else:
            a.empresa = empresa.nome

    for a in achados:
        a.marcado = not a.revisao and bool(a.anexo)
    return achados


# ------------------------------------------------- resolver à mão
def _sem_empresa(cliente_erp: str) -> str:
    return (f"o cliente \"{cliente_erp or '(sem cliente)'}\" não está mapeado "
            "em nenhuma empresa (clientes_erp no contas_sicoob.json)")


def pode_resolver(achado: Achado) -> bool:
    """Dá para decidir alguma coisa à mão nesta casa?

    Sem obra no cadastro do ERP não há anexo para escolher nem cliente para
    mapear: a casa está fora do alcance da tela, e abrir a janela só ofereceria
    uma lista vazia."""
    return bool(achado.obra_id)


def que_falta(achado: Achado) -> str:
    """O motivo que AINDA impede o arquivamento; "" quando não há mais."""
    if not achado.obra_id:
        return achado.revisao
    if not achado.anexo:
        return achado.revisao or "falta escolher o contrato desta casa"
    if not achado.empresa:
        return _sem_empresa(achado.cliente_erp)
    return ""


def aplicar_resolucao(achado: Achado, anexo: dict | None = None,
                      empresa_nome: str = "") -> str:
    """Aplica o que a pessoa decidiu e devolve o que ainda falta.

    Devolver o que falta, em vez de sim/não, é o que deixa a janela resolver
    metade do problema sem mentir: escolher o contrato de uma casa cujo cliente
    continua sem empresa não arquiva nada, e a linha tem de seguir dizendo por
    quê. Só sai marcada a casa que não deve mais nada."""
    if anexo is not None:
        achado.anexo = anexo
        achado.contrato_manual = True
    if empresa_nome:
        achado.empresa = empresa_nome
        achado.empresa_manual = True
    achado.revisao = que_falta(achado)
    achado.marcado = not achado.revisao
    return achado.revisao


def chave_da_casa(achado: Achado) -> tuple[str, int]:
    """Identidade da casa entre uma busca e outra: obra + unidade."""
    return (util.norm_espaco(achado.imovel.obra), achado.imovel.unidade)


def reaplicar(achados: list[Achado], escolhas: dict, log=print) -> int:
    """Devolve as escolhas de contrato feitas à mão a uma lista recém-buscada.

    Guardamos o NOME do arquivo, não o anexo: a busca refeita traz outro
    objeto, com `downloadUrl` novo (o do S3 expira em minutos). Se o nome sumiu
    da obra, a casa volta a perguntar em vez de arquivar um arquivo que ninguém
    olhou."""
    voltaram = 0
    for a in achados:
        nome = escolhas.get(chave_da_casa(a))
        if not nome:
            continue
        alvo = next((x for x in a.anexos_da_obra
                     if util.norm_espaco(x.get("filename") or "")
                     == util.norm_espaco(nome)), None)
        if alvo is None:
            log(f"  a escolha anterior não está mais na obra: {nome}")
            continue
        aplicar_resolucao(a, anexo=alvo)
        voltaram += 1
    return voltaram


def preparar_destino(achado: Achado, raiz: Path, ano: int, mes: int,
                     nome_do_mes, nome_pasta_empresa) -> str:
    """Preenche `achado.destino`. Devolve "" ou o motivo de não dar."""
    if not achado.empresa or not achado.anexo:
        return achado.revisao or "sem empresa ou sem contrato"
    pasta = pasta_do_contrato(raiz, ano, mes, achado.empresa,
                              nome_do_mes, nome_pasta_empresa)
    alvo = pasta / nome_arquivo(achado.imovel.obra, achado.imovel.unidade,
                                achado.imovel.comprador,
                                achado.anexo.get("extension") or ".pdf")
    passou = caminho_longo(alvo)
    if passou:
        return (f"o caminho ficaria com {passou} caracteres, acima do limite "
                f"de 260 do Windows:\n{str(alvo).replace(chr(92), '/')}")
    achado.destino = alvo
    return ""


def esperado_da_conferencia(achado: Achado) -> dict:
    """O que o contrato precisa dizer, montado do que o ERP informou."""
    end = achado.endereco or {}
    return {
        "rua": end.get("address") or "",
        "complemento": end.get("complement") or "",
        "unidade": achado.imovel.unidade,
        "comprador": achado.imovel.comprador,
        "valor_financiamento": achado.imovel.valor_financiamento,
    }


def arquivar(api, achados: list[Achado], raiz: Path, ano: int, mes: int,
             nome_do_mes, nome_pasta_empresa, texto_do_pdf,
             log=print, cancelar=None, progresso=None) -> list[Achado]:
    """Passo 2: baixa, confere o conteúdo e grava só o que passou.

    `texto_do_pdf(bytes) -> str` entra por parâmetro para este módulo não
    depender do OCR (que arrasta pdfplumber e Tesseract): quem sabe ler PDF é
    a aba, e aqui só se decide o que fazer com o texto."""
    # Repetido de propósito: entre buscar e arquivar o ERP pode ter derrubado a
    # sessão (ele aceita uma por usuário), e aí a API é outra, sem cabeçalho
    # nenhum. Custa nada quando já está capturado.
    _garantir_acesso(api, log)
    # `marcado` é a decisão de quem confere, tomada na tabela. Sem ela aqui, o
    # passo 2 arquivaria de novo o que a pessoa tirou da rodada de propósito.
    prontos = [a for a in achados if a.marcado and not a.revisao and a.anexo]
    total = len(prontos)
    for i, achado in enumerate(prontos, 1):
        if cancelar and cancelar():
            log("⏹ Interrompido — o que já foi arquivado continua no lugar.")
            break
        if progresso:
            progresso(i, total)

        # O endereço só existe no detalhe da obra, e é dele que saem a rua e a
        # quadra/lote da conferência.
        if not achado.endereco:
            try:
                achado.endereco = (api.detalhe_da_obra(achado.obra_id)
                                   .get("address") or {})
            except Exception as e:
                achado.revisao = f"não consegui ler o endereço da obra: {e}"
                continue

        motivo = preparar_destino(achado, raiz, ano, mes, nome_do_mes,
                                  nome_pasta_empresa)
        if motivo:
            achado.revisao = motivo
            continue

        dados = api.baixar_anexo(achado.anexo.get("downloadUrl"))
        if not dados:
            achado.revisao = ("o download do contrato falhou ou veio vazio "
                              "(a URL do S3 expira: rode a busca de novo)")
            continue

        resultado = conf.conferir(texto_do_pdf(dados),
                                  esperado_da_conferencia(achado))
        achado.resultado_conferencia = resultado

        if not conf.pode_gravar(resultado):
            pontos = ", ".join(conf.divergencias(resultado))
            achado.revisao = f"o conteúdo do contrato diverge em: {pontos}"
            log(f"  [{i}/{total}] RETIDO {achado.resumo} — {pontos}")
            continue

        try:
            achado.destino.parent.mkdir(parents=True, exist_ok=True)
            achado.destino.write_bytes(dados)
        except OSError as e:
            achado.revisao = f"não consegui gravar: {e}"
            continue

        # "Arquivado" só depois de o arquivo existir com tamanho maior que
        # zero. Dizer que arquivou sem o arquivo no disco é o tipo de mentira
        # que só aparece no fechamento, meses depois.
        if not achado.destino.is_file() or achado.destino.stat().st_size <= 0:
            achado.revisao = "o arquivo não ficou no disco depois de gravar"
            continue

        achado.arquivado = True
        rs = conf.ressalvas(resultado)
        extra = f"  (ressalvas: {', '.join(rs)})" if rs else ""
        log(f"  [{i}/{total}] ok {achado.resumo}{extra}")

    return achados
