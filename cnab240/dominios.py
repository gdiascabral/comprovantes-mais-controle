"""Acesso aos domínios da seção 13 do manual e decodificação de ocorrências."""

from __future__ import annotations

import re
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
        # Conta CARACTERES, não dígitos: desde a v4.0 do guia (01/07/2026) o
        # CNPJ pode ter letras, e contar só dígitos devolveria "não sei" para
        # um CNPJ legítimo. O CPF continua sendo só dígitos.
        caracteres = so_inscricao(documento)
        if len(caracteres) == 11 and caracteres.isdigit():
            return cls.CPF
        if len(caracteres) == 14:
            return cls.CNPJ
        raise ValueError(
            f"não dá para inferir o tipo de inscrição de {documento!r} "
            "(esperado 11 dígitos para CPF ou 14 para CNPJ)"
        )


#: O alfabeto do número de inscrição (G006) desde a v4.0 do guia: dígitos e
#: letras MAIÚSCULAS. É o alfabeto do CNPJ alfanumérico da Receita (IN RFB
#: 2.229/2024): raiz e ordem podem ter letras, os dois DVs continuam dígitos.
CARACTERES_INSCRICAO = frozenset("0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ")


def so_inscricao(valor) -> str:
    """Só o que um CPF/CNPJ pode conter: dígitos e letras A-Z, em maiúsculas.

    É o `so_digitos` de quem já sabe que o CNPJ pode ter letra. Serve para
    VALOR que se espera que seja um documento ("12.ABC.345/01DE-35"); para
    achar um documento dentro de TEXTO livre é `documento_valido`, que confere
    o dígito verificador — aqui, "PIX CNPJ 12..." viraria "PIXCNPJ12...".
    """
    return "".join(c for c in str(valor or "").upper() if c in CARACTERES_INSCRICAO)


#: Pesos do DV do CNPJ, do 2º dígito para trás. O 1º DV usa os 12 últimos;
#: o 2º, os 13. Escritos por extenso de propósito: a versão calculada saía
#: deslocada em uma posição e reprovava CNPJ legítimo em silêncio.
_PESOS_CNPJ = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def dv_cpf(d: str) -> bool:
    """Os onze dígitos fecham como CPF?"""
    if len(d) != 11 or len(set(d)) == 1 or not d.isdigit():
        return False
    for tamanho in (9, 10):
        soma = sum(int(d[i]) * (tamanho + 1 - i) for i in range(tamanho))
        resto = (soma * 10) % 11 % 10
        if resto != int(d[tamanho]):
            return False
    return True


def dv_cnpj(d: str) -> bool:
    """Os catorze caracteres fecham como CNPJ?

    Desde 01/07/2026 (guia v4.0, campo G006) o CNPJ pode ter letras nas doze
    primeiras posições — raiz e ordem —, e os dois dígitos verificadores
    continuam numéricos. A conta é a MESMA da Receita para o CNPJ de sempre,
    com cada caractere valendo o seu código ASCII menos 48: os dígitos
    continuam valendo 0 a 9 (nada muda para quem só tem dígito) e A..Z valem
    17 a 42. O exemplo oficial da Receita, ``12.ABC.345/01DE-35``, fecha.

    Minúscula não passa de propósito: quem normaliza é `so_inscricao`, e um
    "a" chegando aqui é sinal de que alguém pulou a normalização.
    """
    if len(d) != 14 or len(set(d)) == 1:
        return False
    if not all(c in CARACTERES_INSCRICAO for c in d[:12]) or not d[12:].isdigit():
        return False
    for tamanho in (12, 13):
        pesos = _PESOS_CNPJ[-tamanho:]
        soma = sum((ord(d[i]) - 48) * pesos[i] for i in range(tamanho))
        resto = soma % 11
        if (0 if resto < 2 else 11 - resto) != int(d[tamanho]):
            return False
    return True


#: Um CNPJ alfanumérico dentro de um texto, com ou sem a máscara
#: "12.ABC.345/01DE-35" — catorze caracteres delimitados por algo que não é
#: dígito nem letra. `[0-9]` no lugar de `\d` e lookarounds no lugar de
#: `\b` de propósito: `\b` trata "_" como letra, e aqui "_" é delimitador.
_CNPJ_ALFANUMERICO = re.compile(
    r"(?<![0-9A-Z])([0-9A-Z]{2})[.]?([0-9A-Z]{3})[.]?([0-9A-Z]{3})/?([0-9A-Z]{4})-?([0-9]{2})(?![0-9A-Z])"
)


def cnpj_alfanumerico_em(texto) -> str:
    """O primeiro CNPJ COM LETRAS que fecha o DV dentro de ``texto``, ou "".

    Exige pelo menos uma letra: sem letra, o caminho dos dígitos de
    `documento_valido` já respondeu, e este não pode mudar a resposta dele —
    é o que mantém intacto tudo o que já funcionava com CNPJ numérico. O DV
    é o filtro contra palavra de catorze caracteres terminada em dois dígitos
    (fecha por acaso ~1 vez em 100, a mesma exposição que o CPF numérico
    sempre teve).
    """
    for m in _CNPJ_ALFANUMERICO.finditer(str(texto or "").upper()):
        candidato = "".join(m.groups())
        if not candidato.isdigit() and dv_cnpj(candidato):
            return candidato
    return ""


def documento_valido(valor) -> str:
    """Os dígitos, se forem um CPF ou CNPJ que fecha. Senão, "".

    Mora aqui, e não na camada de pagamentos, porque é o `cnab240` que escreve
    os campos de inscrição e é ele quem tem de saber recusá-los. O
    `TipoInscricao.por_documento` logo acima mede o TAMANHO para escolher entre
    CPF e CNPJ — nunca conferiu o dígito verificador, e não é trabalho dele. Foi
    por essa fresta que um CPF de preenchimento (onze dígitos, DV que não fecha)
    chegou ao campo 08.3B e fez o Sicoob devolver a remessa de 20/08/2026.

    Os dígitos verificadores não são preciosismo: sem eles, todo telefone de
    onze dígitos viraria "CPF encontrado".

    Dois caminhos, nesta ordem: os DÍGITOS do texto inteiro (o de sempre, que
    resolve CPF e CNPJ numérico) e, só quando eles não fecham, um CNPJ com
    letras achado no texto (`cnpj_alfanumerico_em`, desde a v4.0 do guia).
    Devolve o documento como o arquivo o grava: maiúsculas, sem pontuação.
    """
    if isinstance(valor, bool) or not isinstance(valor, (str, int)):
        return ""
    digitos = "".join(c for c in str(valor) if c.isdigit())
    if dv_cpf(digitos) or dv_cnpj(digitos):
        return digitos
    return cnpj_alfanumerico_em(valor) if isinstance(valor, str) else ""


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


DDDS = frozenset((
    11, 12, 13, 14, 15, 16, 17, 18, 19,
    21, 22, 24, 27, 28,
    31, 32, 33, 34, 35, 37, 38,
    41, 42, 43, 44, 45, 46, 47, 48, 49,
    51, 53, 54, 55,
    61, 62, 63, 64, 65, 66, 67, 68, 69,
    71, 73, 74, 75, 77, 79,
    81, 82, 83, 84, 85, 86, 87, 88, 89,
    91, 92, 93, 94, 95, 96, 97, 98, 99,
))


def chave_telefone_pix(chave: str) -> str:
    """A chave Pix de celular como o Pix a guarda: "+55" + DDD + 9 + 8 dígitos.

    O cadastro do ERP escreve a chave do jeito de cada um ("62 9XXXX-XXXX",
    onze dígitos crus, "+55 (62) …"), e até 27/11/2026 ela ia assim para a
    Informação 12 do segmento B (G100 = 01; o G101 não diz o formato). O
    formato da chave telefone no Pix é "+55…", e o próprio Guia o exige no
    J-52 (G102); nenhuma das 39 remessas com chave telefone tinha retorno do
    banco. Conferido antes de sair, porque um número bem formado de OUTRA
    pessoa é o pior erro aqui (revisão de dinheiro, 27/11/2026):
    - DDD do Brasil e o 9 do celular (11 dígitos); fixo e celular sem o 9 não
      são chave Pix e não vão;
    - o primeiro grupo de dígitos tem de ser o DDD, o "55" ou o número
      inteiro (o DDD escrito depois do número não se adivinha);
    - "55" só sai da frente com 13 dígitos ("+55" + DDD + número). Onze
      dígitos que começam por 55 podem ser "+55 9XXXX-XXXX" sem o DDD (a
      extração perde o "+"): o DDD 55 escrito sozinho é recusado, e o do RS
      só passa com o "+55" na frente ("+55 55 9XXXX-XXXX").
    Fora disso, ValueError: chave de telefone que não se lê não vai ao banco."""
    grupos = re.findall(r"\d+", str(chave or ""))
    d = "".join(grupos)
    com_pais = len(d) == 13 and d.startswith("55")
    # O primeiro grupo de dígitos é o começo da chave: o DDD ("62 9…",
    # "(62) 9…"), o "55" do país, ou o número inteiro colado. "999991234 62"
    # (o DDD escrito DEPOIS) daria outro número bem formado.
    if not grupos or len(grupos[0]) not in (2, 4, 11, 13) or (
            len(grupos[0]) == 4 and not com_pais):
        raise ValueError(f"chave Pix de telefone ilegível: {chave!r}")
    if com_pais and grupos[0] == "55" and (len(grupos) < 2 or len(grupos[1]) not in (2, 11)):
        # "+55 999991234 62": o país separado tem de vir seguido do DDD ou do
        # número inteiro, senão é o DDD escrito depois (revisão de dinheiro).
        raise ValueError(f"chave Pix de telefone ilegível: {chave!r}")
    if com_pais:
        d = d[2:]
    if len(d) != 11 or d[2] != "9" or int(d[:2]) not in DDDS:
        raise ValueError(f"chave Pix de telefone ilegível: {chave!r}")
    if d.startswith("55") and not com_pais:
        raise ValueError(f"chave Pix de telefone ilegível (DDD 55 ou +55 sem DDD?): {chave!r}")
    return "+55" + d


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

#: Ocorrências em que o banco SEGUROU a transação para análise de segurança.
#: `BS` existe desde 29/04/2026 (guia v3.5) e tem uma propriedade que nenhum
#: outro código tem: o retorno NÃO é atualizado quando a análise termina —
#: o Sicoob avisou isso aos cooperados por escrito. Quem diz se o dinheiro saiu
#: é o extrato da conta, e por isso `BS` não pode ser lido nem como pago, nem
#: como pendente de assinatura, nem como rejeitado. Não vale para Pix.
OCORRENCIAS_EM_ANALISE = frozenset({"BS"})


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
