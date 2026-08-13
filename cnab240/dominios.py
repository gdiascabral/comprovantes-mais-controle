"""Acesso aos domínios da seção 13 do manual e decodificação de ocorrências."""

from __future__ import annotations

from enum import StrEnum

from .spec import dominios as _dominios

BANCO_SICOOB = "756"
VERSAO_LAYOUT_ARQUIVO = "087"


class TipoInscricao(StrEnum):
    """G005."""

    ISENTO = "0"
    CPF = "1"
    CNPJ = "2"
    PIS_PASEP = "3"
    OUTROS = "9"

    @classmethod
    def por_documento(cls, documento: str) -> "TipoInscricao":
        digitos = "".join(c for c in str(documento) if c.isdigit())
        if len(digitos) == 11:
            return cls.CPF
        if len(digitos) == 14:
            return cls.CNPJ
        raise ValueError(
            f"não dá para inferir o tipo de inscrição de {documento!r} "
            "(esperado 11 dígitos para CPF ou 14 para CNPJ)"
        )


class TipoServico(StrEnum):
    """G025 — apenas os usados em pagamentos."""

    PAGAMENTO_FORNECEDOR = "20"
    CONTAS_TRIBUTOS_IMPOSTOS = "22"
    PAGAMENTO_SALARIOS = "30"
    PAGAMENTO_HONORARIOS = "32"
    PAGAMENTO_BOLSA_AUXILIO = "33"
    PAGAMENTO_REMUNERACAO = "77"
    PAGAMENTO_BENEFICIOS = "90"
    PAGAMENTOS_DIVERSOS = "98"


class FormaLancamento(StrEnum):
    """G029."""

    CREDITO_CONTA_CORRENTE = "01"
    CREDITO_CONTA_POUPANCA = "05"
    CONTAS_TRIBUTOS_COD_BARRAS = "11"
    DARF_NORMAL = "16"
    GPS = "17"
    DARF_SIMPLES = "18"
    TITULO_PROPRIO_BANCO = "30"
    TITULO_OUTROS_BANCOS = "31"
    TED_OUTRA_TITULARIDADE = "41"
    TED_MESMA_TITULARIDADE = "43"
    PIX_TRANSFERENCIA = "45"
    PIX_QRCODE = "47"


class Camara(StrEnum):
    """P001."""

    TED = "018"
    PIX = "009"


class FormaIniciacaoPix(StrEnum):
    """G100."""

    CHAVE_TELEFONE = "01"
    CHAVE_EMAIL = "02"
    CHAVE_CPF_CNPJ = "03"
    CHAVE_ALEATORIA = "04"
    DADOS_BANCARIOS = "05"


class TipoContaDestino(StrEnum):
    """G031 — 2 últimos dígitos da Informação 2 em pagamentos Pix."""

    CORRENTE = "01"
    PAGAMENTO = "02"
    POUPANCA = "03"


class AvisoFavorecido(StrEnum):
    """P006."""

    NAO_EMITE = "0"
    SO_REMETENTE = "2"
    SO_FAVORECIDO = "5"
    REMETENTE_E_FAVORECIDO = "6"
    FAVORECIDO_E_2_VIAS_REMETENTE = "7"


class TipoIdentificacaoContribuinte(StrEnum):
    """N003."""

    CNPJ = "1"
    CPF = "2"
    NIT_PIS_PASEP = "3"
    CEI = "4"
    NB = "6"
    NUMERO_TITULO = "7"
    DEBCAD = "8"
    REFERENCIA = "9"


def valores(codigo: str) -> dict[str, str]:
    """Domínio bruto de um código da seção 13 (ex.: ``G029``)."""
    bloco = _dominios().get(codigo)
    if bloco is None:
        raise KeyError(f"domínio {codigo!r} não está em spec/dominios.json")
    return bloco.get("valores", {})


def valido(codigo: str, valor: str) -> bool:
    return str(valor) in valores(codigo)


def descrever(codigo: str, valor: str) -> str:
    return valores(codigo).get(str(valor), f"<desconhecido: {valor!r}>")


# --- Ocorrências (G059) ----------------------------------------------------

#: Ocorrências que indicam sucesso ou agendamento, não rejeição.
OCORRENCIAS_SUCESSO = frozenset({"00", "BD", "68"})

#: Ocorrências que indicam pendência de ação do usuário.
OCORRENCIAS_PENDENTES = frozenset({"PD"})


def _tabela_ocorrencias() -> dict[str, str]:
    g059 = _dominios()["G059"]
    tabela: dict[str, str] = {}
    # A ordem importa: os domínios específicos refinam a descrição do geral.
    for chave in ("dominio_geral", "dominio_pix", "dominio_folha_pagamento"):
        for codigo, descricao in g059.get(chave, {}).items():
            tabela.setdefault(codigo, descricao)
    return tabela


def separar_ocorrencias(campo: str) -> list[str]:
    """Quebra as 10 posições de ocorrência em até 5 códigos de 2 caracteres."""
    bruto = campo or ""
    if not bruto.strip():
        return []
    codigos = [bruto[i : i + 2].strip() for i in range(0, len(bruto), 2)]
    codigos = [c for c in codigos if c]
    # Campo preenchido inteiramente com zeros = uma única ocorrência '00'.
    if codigos and all(c == "00" for c in codigos):
        return ["00"]
    return codigos


def decodificar_ocorrencias(campo: str) -> list[tuple[str, str]]:
    """Devolve ``[(codigo, descrição)]`` a partir das posições 231-240."""
    tabela = _tabela_ocorrencias()
    return [(c, tabela.get(c, "<código não catalogado no manual>")) for c in separar_ocorrencias(campo)]


def sucesso(campo: str) -> bool:
    codigos = separar_ocorrencias(campo)
    return bool(codigos) and all(c in OCORRENCIAS_SUCESSO for c in codigos)
