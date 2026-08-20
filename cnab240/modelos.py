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


def dinheiro_exato(valor: Any, rotulo: str) -> Decimal:
    """Dinheiro com no máximo 2 casas — mais que isso é recusado, não arredondado.

    O arquivo grava centavos: ``fmt_num`` arredonda CADA registro na gravação,
    enquanto o trailer soma os valores como vieram. Três parcelas de
    ``Decimal("33.3333")`` viram três registros de 33,33 (99,99) debaixo de um
    trailer que declara 100,00 — e divergência de somatória faz o Sicoob
    rejeitar o ARQUIVO inteiro, não a linha. Arredondar aqui esconderia o
    problema e mudaria, calado, quanto sai da conta de outra pessoa: com
    dinheiro alheio, recusar é a única saída honesta.

    O critério é o EXPOENTE do Decimal, não o texto. Comparar strings
    tropeçaria em "33.3", em "3.333E+1" e no float que virou
    "33.330000000000005"; menos de duas casas é legítimo e passa.
    """
    d = dinheiro(valor)
    if not d.is_finite():
        raise ValueError(f"{rotulo}: {valor!r} não é um valor monetário (NaN ou infinito)")
    if d.as_tuple().exponent < -2:
        raise ValueError(
            f"{rotulo}: {d} tem mais de 2 casas decimais. O CNAB 240 grava centavos, "
            "e arredondar por conta própria faria a somatória do trailer divergir da "
            "soma dos registros — o banco recusa o arquivo inteiro. Informe o valor "
            "já arredondado (ex.: 33.33), decidindo você para onde vai o centavo."
        )
    return d


def so_digitos(valor: Any) -> str:
    return "".join(c for c in str(valor or "") if c.isdigit())


#: Tamanhos do layout (header de arquivo 08.0/10.0 e segmento A 10.3A/12.3A):
#: agência 5 posições, conta 12, e cada dígito verificador 1.
TAMANHO_AGENCIA = 5
TAMANHO_CONTA = 12

#: Pontuação que o cadastro escreve e o arquivo não tem: "45.678-1", "4321 / 0".
_RUIDO_DE_MASCARA = frozenset(" ./-")


def _texto(valor: Any) -> str:
    """``str`` limpo, tratando None como vazio (e sem confundir 0 com vazio)."""
    return "" if valor is None else str(valor).strip()


def _dv(valor: Any, rotulo: str) -> str:
    """Um dígito verificador, ou erro — nunca um branco silencioso."""
    texto = _texto(valor)
    if not texto:
        return ""
    if not texto.isdigit():
        raise ValueError(
            f"{rotulo}: {valor!r} não é um dígito. O campo do CNAB 240 tem 1 posição "
            "e o Sicoob só usa dígitos ali; deixar isso virar branco trocaria a conta "
            "de destino sem nada denunciar."
        )
    if len(texto) > 1:
        raise ValueError(f"{rotulo}: {valor!r} tem {len(texto)} dígitos e o campo tem 1")
    return texto


def _numero_e_dv(numero: Any, dv: Any, *, rotulo: str, tamanho: int) -> tuple[str, str]:
    """Separa "0910-5" em agência 0910 e DV 5 — sem colar um no outro.

    Quem cadastra escreve como o extrato mostra: "0910-5", "45.678-1". Isso
    chegava cru ao ``fmt_num``, que remove a pontuação e trata o resto como
    número já pronto: a agência virava 09105 e a conta, 000000456781 com o DV
    grudado no fim. São números plausíveis, o validador os aprova, e o dinheiro
    vai para outra conta — que não volta.

    Hífen seguido de UM dígito é a máscara "número-DV" do sistema bancário
    brasileiro, e é a única pontuação com significado aqui; ponto, barra e
    espaço são ruído e caem fora. Letra não passa: DV "X" existe em outros
    bancos, mas o campo do CNAB é numérico, e transformá-lo em branco seria o
    mesmo erro silencioso de novo. Máscara e campo ``dv_*`` discordando é
    contradição, não preferência — escolher um dos dois seria adivinhar.
    """
    original = _texto(numero)
    estranhos = sorted({c for c in original if not c.isdigit() and c not in _RUIDO_DE_MASCARA})
    if estranhos:
        raise ValueError(
            f"{rotulo}: {numero!r} tem caractere que não é dígito ({' '.join(estranhos)}). "
            "O campo do CNAB 240 é numérico; informe só os dígitos, com o DV no campo "
            "próprio ou na máscara 'número-DV'."
        )

    texto, dv_da_mascara = original, ""
    cabeca, separador, cauda = original.rpartition("-")
    if separador and len(cauda) == 1 and cauda.isdigit():
        texto, dv_da_mascara = cabeca, cauda

    digitos = so_digitos(texto)
    if original and not digitos:
        raise ValueError(f"{rotulo}: {numero!r} não tem dígito nenhum")
    if len(digitos) > tamanho:
        raise ValueError(
            f"{rotulo}: {numero!r} dá {len(digitos)} dígitos e o campo do CNAB 240 tem "
            f"{tamanho}. Confira se o DV não entrou junto do número."
        )

    dv_informado = _dv(dv, f"DV da {rotulo}")
    if dv_da_mascara and dv_informado and dv_da_mascara != dv_informado:
        raise ValueError(
            f"{rotulo}: a máscara {numero!r} termina no DV {dv_da_mascara} e o campo "
            f"informa {dv_informado}. Um dos dois está errado."
        )
    return digitos, dv_informado or dv_da_mascara


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
        # Antes daqui só o documento era normalizado; agência e conta iam cruas
        # e o DV da máscara acabava colado no número (ver ``_numero_e_dv``).
        self.agencia, self.dv_agencia = _numero_e_dv(
            self.agencia, self.dv_agencia, rotulo="agência da empresa", tamanho=TAMANHO_AGENCIA
        )
        self.conta, self.dv_conta = _numero_e_dv(
            self.conta, self.dv_conta, rotulo="conta da empresa", tamanho=TAMANHO_CONTA
        )
        self.dv_ag_conta = _dv(self.dv_ag_conta, "DV agência/conta da empresa")


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
        self.agencia, self.dv_agencia = _numero_e_dv(
            self.agencia, self.dv_agencia, rotulo="agência do favorecido", tamanho=TAMANHO_AGENCIA
        )
        self.conta, self.dv_conta = _numero_e_dv(
            self.conta, self.dv_conta, rotulo="conta do favorecido", tamanho=TAMANHO_CONTA
        )
        self.dv_ag_conta = _dv(self.dv_ag_conta, "DV agência/conta do favorecido")


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
        self.valor = dinheiro_exato(self.valor, "valor do pagamento")


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

    #: Os cinco campos monetários do segmento B. ``None`` é "não informado" e
    #: continua sendo — o layout grava zeros —, mas o que vier preenchido passa
    #: pela mesma régua do valor do pagamento.
    _MONETARIOS = ("valor_documento", "abatimento", "desconto", "mora", "multa")

    def __post_init__(self) -> None:
        super().__post_init__()
        # Estes cinco não passavam por ``dinheiro()`` nenhum: iam crus para o
        # ``fmt_num``, que arredondava em silêncio na hora de gravar.
        for campo in self._MONETARIOS:
            bruto = getattr(self, campo)
            if bruto is not None:
                setattr(self, campo, dinheiro_exato(bruto, campo))


@dataclass(kw_only=True)
class PixTransferencia(_PagamentoBase):
    """Pix Transferência — forma de lançamento 45."""

    favorecido: Favorecido
    forma_iniciacao: FormaIniciacaoPix = FormaIniciacaoPix.CHAVE_ALEATORIA
    chave: str = ""
    #: Texto livre por pagamento — vai nas 38 primeiras posições do campo
    #: `24.3A`, que no Pix eram brancos (as 2 últimas são o tipo da conta de
    #: destino). É o único lugar onde a tela de pendências do banco mostra
    #: algo NOSSO sobre um Pix; vazio, a coluna "Detalhes" fica em branco.
    mensagem: str = ""
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
