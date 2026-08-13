"""Modelos de entrada do gerador — o que o sistema chamador preenche.

Nenhuma classe aqui conhece posições do arquivo; a tradução para o layout fica
em ``remessa.py``.
"""

from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from .dominios import (
    AvisoFavorecido,
    BANCO_SICOOB,
    FormaIniciacaoPix,
    TipoContaDestino,
    TipoIdentificacaoContribuinte,
    TipoInscricao,
)


def dinheiro(valor: Any) -> Decimal:
    """Converte para ``Decimal`` sem passar por ``float`` quando evitável."""
    if isinstance(valor, Decimal):
        return valor
    if valor is None:
        return Decimal("0")
    return Decimal(str(valor))


def so_digitos(valor: Any) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


@dataclass
class Endereco:
    logradouro: str = ""
    numero: str = ""
    complemento: str = ""
    bairro: str = ""
    cidade: str = ""
    cep: str = ""
    estado: str = ""

    @property
    def cep_prefixo(self) -> str:
        return so_digitos(self.cep).zfill(8)[:5] if self.cep else ""

    @property
    def cep_sufixo(self) -> str:
        return so_digitos(self.cep).zfill(8)[5:8] if self.cep else ""


@dataclass
class Empresa:
    """Dados do pagador — vão no header do arquivo e no header de cada lote."""

    nome: str
    documento: str
    convenio: str
    agencia: str
    conta: str
    dv_conta: str
    dv_agencia: str = ""
    dv_ag_conta: str = ""
    tipo_inscricao: TipoInscricao | None = None
    endereco: Endereco = field(default_factory=Endereco)

    def __post_init__(self) -> None:
        self.documento = so_digitos(self.documento)
        if self.tipo_inscricao is None:
            self.tipo_inscricao = TipoInscricao.por_documento(self.documento)


@dataclass
class Favorecido:
    nome: str
    documento: str
    banco: str = BANCO_SICOOB
    agencia: str = ""
    conta: str = ""
    dv_conta: str = ""
    dv_agencia: str = ""
    dv_ag_conta: str = ""
    tipo_inscricao: TipoInscricao | None = None
    endereco: Endereco = field(default_factory=Endereco)

    def __post_init__(self) -> None:
        self.documento = so_digitos(self.documento)
        if self.tipo_inscricao is None:
            self.tipo_inscricao = TipoInscricao.por_documento(self.documento)


# --------------------------------------------------------------------------
# Pagamentos por produto
# --------------------------------------------------------------------------


@dataclass(kw_only=True)
class _PagamentoBase:
    valor: Decimal
    data_pagamento: _dt.date
    seu_numero: str = ""
    nosso_numero: str = ""

    def __post_init__(self) -> None:
        self.valor = dinheiro(self.valor)


@dataclass(kw_only=True)
class TransferenciaConta(_PagamentoBase):
    """Crédito em conta (Sicoob) ou TED. Formas de lançamento 01, 05, 41 e 43."""

    favorecido: Favorecido
    mensagem: str = ""
    aviso: AvisoFavorecido = AvisoFavorecido.NAO_EMITE
    finalidade_ted: str = ""
    finalidade_complementar: str = ""
    # Dados de documento opcionais gravados no segmento B.
    vencimento: _dt.date | None = None
    valor_documento: Decimal | None = None
    abatimento: Decimal | None = None
    desconto: Decimal | None = None
    mora: Decimal | None = None
    multa: Decimal | None = None
    codigo_documento_favorecido: str = ""


@dataclass(kw_only=True)
class PixTransferencia(_PagamentoBase):
    """Pix Transferência — forma de lançamento 45."""

    favorecido: Favorecido
    forma_iniciacao: FormaIniciacaoPix = FormaIniciacaoPix.CHAVE_ALEATORIA
    chave: str = ""
    tipo_conta_destino: TipoContaDestino = TipoContaDestino.CORRENTE
    aviso: AvisoFavorecido = AvisoFavorecido.NAO_EMITE

    def __post_init__(self) -> None:
        super().__post_init__()
        precisa_chave = self.forma_iniciacao in (
            FormaIniciacaoPix.CHAVE_TELEFONE,
            FormaIniciacaoPix.CHAVE_EMAIL,
            FormaIniciacaoPix.CHAVE_ALEATORIA,
        )
        if precisa_chave and not self.chave:
            raise ValueError(
                f"forma de iniciação {self.forma_iniciacao.name} exige a chave Pix"
            )
        if self.forma_iniciacao is FormaIniciacaoPix.DADOS_BANCARIOS and not self.favorecido.conta:
            raise ValueError("forma de iniciação DADOS_BANCARIOS exige conta do favorecido")


@dataclass
class DadosJ52:
    """Entes envolvidos no pagamento de título (registro opcional 52)."""

    sacado_nome: str = ""
    sacado_documento: str = ""
    cedente_nome: str = ""
    cedente_documento: str = ""
    sacador_nome: str = ""
    sacador_documento: str = ""


@dataclass(kw_only=True)
class PagamentoTitulo(_PagamentoBase):
    """Boleto — formas de lançamento 30 (Sicoob) e 31 (outros bancos)."""

    codigo_barras: str = ""
    nome_cedente: str = ""
    vencimento: _dt.date | None = None
    valor_titulo: Decimal | None = None
    desconto_abatimento: Decimal = Decimal("0")
    mora_multa: Decimal = Decimal("0")
    j52: DadosJ52 = field(default_factory=DadosJ52)

    def __post_init__(self) -> None:
        super().__post_init__()
        self.codigo_barras = so_digitos(self.codigo_barras)
        if len(self.codigo_barras) != 44:
            raise ValueError(
                f"código de barras deve ter 44 dígitos (recebido {len(self.codigo_barras)}). "
                "Use o código de barras, não a linha digitável de 47/48 dígitos."
            )
        if self.valor_titulo is None:
            self.valor_titulo = self.valor
        self.valor_titulo = dinheiro(self.valor_titulo)
        self.desconto_abatimento = dinheiro(self.desconto_abatimento)
        self.mora_multa = dinheiro(self.mora_multa)


@dataclass(kw_only=True)
class PixQRCode(_PagamentoBase):
    """Pix via QR Code — forma de lançamento 47 (segmento J + J-52-Pix)."""

    chave_pagamento: str = ""
    txid: str = ""
    favorecido: Favorecido
    devedor_nome: str = ""
    devedor_documento: str = ""
    vencimento: _dt.date | None = None
    valor_titulo: Decimal | None = None
    #: O manual mantém o campo 08.3J obrigatório mesmo sem boleto; zeros é o
    #: preenchimento adotado. Sobrescreva se a cooperativa exigir outro.
    codigo_barras: str = "0" * 44

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.chave_pagamento:
            raise ValueError("Pix QR Code exige a URL (dinâmico) ou a chave de endereçamento (estático)")
        if not self.txid:
            raise ValueError("Pix QR Code exige o TXID (obrigatório no segmento J-52-Pix)")
        if len(self.txid) > 30:
            raise ValueError(f"TXID tem {len(self.txid)} caracteres; o layout CNAB 240 permite 30")
        if self.valor_titulo is None:
            self.valor_titulo = self.valor
        self.valor_titulo = dinheiro(self.valor_titulo)


@dataclass(kw_only=True)
class PagamentoConvenio(_PagamentoBase):
    """Convênio/tributo COM código de barras — forma de lançamento 11 (segmento O)."""

    codigo_barras: str = ""
    nome_concessionaria: str = ""
    vencimento: _dt.date | None = None
    complemento: "SegmentoW | None" = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.codigo_barras = so_digitos(self.codigo_barras)
        if len(self.codigo_barras) != 44:
            raise ValueError(
                f"código de barras deve ter 44 dígitos (recebido {len(self.codigo_barras)})"
            )


@dataclass(kw_only=True)
class _TributoBase(_PagamentoBase):
    nome_contribuinte: str = ""
    codigo_receita: str = ""
    tipo_identificacao: TipoIdentificacaoContribuinte = TipoIdentificacaoContribuinte.CNPJ
    identificacao: str = ""
    complemento: "SegmentoW | None" = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.identificacao = so_digitos(self.identificacao)


@dataclass(kw_only=True)
class TributoDARF(_TributoBase):
    """DARF Normal — forma de lançamento 16."""

    periodo_apuracao: _dt.date | None = None
    numero_referencia: str = ""
    valor_principal: Decimal = Decimal("0")
    valor_multa: Decimal = Decimal("0")
    juros_encargos: Decimal = Decimal("0")
    vencimento: _dt.date | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        self.valor_principal = dinheiro(self.valor_principal or self.valor)
        self.valor_multa = dinheiro(self.valor_multa)
        self.juros_encargos = dinheiro(self.juros_encargos)


@dataclass(kw_only=True)
class TributoGPS(_TributoBase):
    """GPS — forma de lançamento 17."""

    competencia: _dt.date | str = ""
    valor_inss: Decimal = Decimal("0")
    valor_outras_entidades: Decimal = Decimal("0")
    atualizacao_monetaria: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        super().__post_init__()
        self.valor_inss = dinheiro(self.valor_inss or self.valor)
        self.valor_outras_entidades = dinheiro(self.valor_outras_entidades)
        self.atualizacao_monetaria = dinheiro(self.atualizacao_monetaria)


@dataclass(kw_only=True)
class TributoDARFSimples(_TributoBase):
    """DARF Simples — forma de lançamento 18. Código de receita fixo '6106'."""

    periodo_apuracao: _dt.date | None = None
    receita_bruta: Decimal = Decimal("0")
    percentual: Decimal = Decimal("0")
    valor_principal: Decimal = Decimal("0")
    valor_multa: Decimal = Decimal("0")
    juros_encargos: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        super().__post_init__()
        self.codigo_receita = self.codigo_receita or "6106"
        self.receita_bruta = dinheiro(self.receita_bruta)
        self.percentual = dinheiro(self.percentual)
        self.valor_principal = dinheiro(self.valor_principal or self.valor)
        self.valor_multa = dinheiro(self.valor_multa)
        self.juros_encargos = dinheiro(self.juros_encargos)


@dataclass
class SegmentoW:
    """Informações complementares (opcional; obrigatório para FGTS 0181/0182)."""

    tipo_informacao: str = "1"
    informacao_1: str = ""
    informacao_2: str = ""
    identificador_tributo: str = ""
    informacao_tributo: str = ""
    sequencial: int = 1


@dataclass(kw_only=True)
class PagamentoFolha(_PagamentoBase):
    """Crédito de folha de pagamento — serviço 30, forma 01 (segmentos A + B clássico)."""

    favorecido: Favorecido
    mensagem: str = ""
    aviso: AvisoFavorecido = AvisoFavorecido.NAO_EMITE
