# -*- coding: utf-8 -*-
"""Dinheiro digitado e mostrado na aba Pagamentos do dia. Sem tela.

Saldo pode ser negativo e pode ser zero, ao contrário do valor de aporte. Por
isso `aportes.regras.ler_valor_brl` (que recusa os dois) é usado só para a
MAGNITUDE: o sinal e o zero se resolvem aqui, e a recusa do ambíguo ("1500.50")
continua sendo a dela, sem uma segunda régua.
"""
from __future__ import annotations

import re
from decimal import ROUND_HALF_UP, Decimal

from aportes.regras import ler_valor_brl
from conciliacao.parsing import format_brl

CENTAVO = Decimal("0.01")
_ZERO = re.compile(r"0+(,0{1,2})?")


def ler_valor_editado(texto) -> Decimal:
    t = str(texto or "").replace("\xa0", " ").strip()
    negativo = t.startswith("-")
    if negativo:
        t = t[1:].strip()
    t = re.sub(r"^r\$", "", t, flags=re.IGNORECASE).strip()
    if not negativo and t.startswith("-"):          # "R$ -10,00"
        negativo, t = True, t[1:].strip()
    if _ZERO.fullmatch(t):
        return Decimal("0.00")
    valor = ler_valor_brl(t)
    return -valor if negativo else valor


def de_float(valor) -> Decimal:
    """O `valor` float da apuração da Remessa, em Decimal. Passa por `str`."""
    return Decimal(str(valor or 0)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def brl(valor) -> str:
    return format_brl(valor)
