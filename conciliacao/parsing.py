"""Parsers para os formatos brutos que o ERP entrega.

Trata as pegadinhas documentadas no brainstorm:
- numero BR com ponto de milhar e virgula decimal;
- negativo escrito como "R$ - 1.179,29" (traco depois do R$, separado por espaco);
- valor com pagamento parcial: "R$ 4.000,00 Pago: R$ 3.230,00" -> vale o PRIMEIRO;
- saldo mascarado ("******") -> None, nunca zero.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

# Valor precedido de "R$". `pre` captura sinal antes da moeda ("-R$ 10,00"),
# `sign` captura o sinal depois dela ("R$ - 10,00"), que e o formato do ERP.
_MONEY_CURRENCY = re.compile(
    r"(?P<pre>-\s*)?R\$\s*(?P<sign>-\s*)?(?P<num>\d[\d.]*(?:,\d{1,2})?)"
)

# Fallback para celulas sem "R$". Exige virgula decimal para nao confundir
# com quantidades, dias ou numeros de conta soltos no mesmo texto.
_MONEY_BARE = re.compile(r"(?P<sign>-\s*)?(?P<num>\d[\d.]*,\d{1,2})")

_DATE_BR = re.compile(r"(?P<d>\d{1,2})/(?P<m>\d{1,2})(?:/(?P<y>\d{2,4}))?")

# "55.694-7", "55694-7", "10730-1" -> digitos normalizados ("556947").
_ACCOUNT_NUMBER = re.compile(r"(?<![\d-])(?P<base>\d[\d.]{2,})-(?P<check>\d)(?!\d)")

# Prefixos da celula "Condicao e Conta" da grade de pagamentos.
_CONDITION_PREFIXES = ("a vista", "recorrente", "parcelado", "entrada")


def is_masked(text: str | None) -> bool:
    """True quando o ERP devolveu o valor escondido atras do olho ("******")."""
    return bool(text) and "*" in text


def parse_brl(text: str | None) -> Decimal | None:
    """Converte texto monetario BR em Decimal. None quando nao ha valor legivel.

    Devolve o PRIMEIRO valor do texto, que na grade de pagamentos e o valor
    em aberto (o segundo, quando existe, e o "Pago: R$ x" de pagamento parcial).
    """
    if not text:
        return None
    if is_masked(text):
        return None

    match = _MONEY_CURRENCY.search(text) or _MONEY_BARE.search(text)
    if not match:
        return None

    groups = match.groupdict()
    negative = bool(groups.get("pre")) or bool(groups.get("sign"))
    try:
        value = Decimal(groups["num"].replace(".", "").replace(",", "."))
    except InvalidOperation:
        return None
    return -value if negative else value


def parse_date_br(text: str | None, *, reference: date | None = None) -> date | None:
    """Converte "29/07/2026" (ou "29/07", herdando o ano de `reference`) em date."""
    if not text:
        return None
    match = _DATE_BR.search(text)
    if not match:
        return None

    day, month = int(match.group("d")), int(match.group("m"))
    raw_year = match.group("y")
    if raw_year:
        year = int(raw_year)
        if year < 100:  # "26" -> 2026
            year += 2000
    elif reference:
        year = reference.year
    else:
        return None

    try:
        return date(year, month, day)
    except ValueError:
        return None


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_name(text: str | None) -> str:
    """Normaliza nome de conta para comparacao: sem acento, maiusculo, sem pontuacao.

    "Morais Participações - MÃE - 55.694-7" -> "MORAIS PARTICIPACOES MAE 55 694 7"
    """
    if not text:
        return ""
    cleaned = strip_accents(text).upper()
    cleaned = re.sub(r"[^A-Z0-9]+", " ", cleaned)
    return " ".join(cleaned.split())


def normalize_account_number(text: str | None) -> str | None:
    """Reduz um numero de conta a digitos puros: "55.694-7" -> "556947"."""
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    return digits or None


def extract_account_numbers(text: str | None) -> list[str]:
    """Extrai numeros de conta normalizados de um nome livre do ERP.

    "Morais Participações - SUBCONTA 55696-3 - TB 21 QD 51 LT 40" -> ["556963"]
    """
    if not text:
        return []
    found: list[str] = []
    for match in _ACCOUNT_NUMBER.finditer(text):
        digits = re.sub(r"\D", "", match.group("base")) + match.group("check")
        if digits not in found:
            found.append(digits)
    return found


def strip_condition_prefix(text: str | None) -> str:
    """Remove "A Vista"/"Recorrente"/... do inicio da celula "Condicao e Conta"."""
    if not text:
        return ""
    cleaned = " ".join(text.replace("\n", " ").split())
    lowered = strip_accents(cleaned).lower()
    for prefix in _CONDITION_PREFIXES:
        if lowered.startswith(prefix):
            return cleaned[len(prefix) :].strip(" -–:").strip()
    return cleaned


def to_float(value: Decimal | None) -> float | None:
    """Converte para float apenas na fronteira com o openpyxl."""
    return None if value is None else float(value)


def format_brl(value: Decimal | None) -> str:
    """Formata para leitura humana: Decimal("1536956.24") -> "R$ 1.536.956,24"."""
    if value is None:
        return "—"
    quantizado = value.quantize(Decimal("0.01"))
    inteiro, _, centavos = f"{abs(quantizado):.2f}".partition(".")
    grupos = f"{int(inteiro):,}".replace(",", ".")
    sinal = "-" if quantizado < 0 else ""
    return f"{sinal}R$ {grupos},{centavos}"
