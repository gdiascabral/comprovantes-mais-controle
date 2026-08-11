"""Casos reais colhidos do ERP durante o prototipo manual."""

from datetime import date
from decimal import Decimal

import pytest

from conciliacao.parsing import (
    extract_account_numbers,
    is_masked,
    normalize_account_number,
    normalize_name,
    parse_brl,
    parse_date_br,
    strip_condition_prefix,
)


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("R$ 1.234.567,89", Decimal("1234567.89")),
        ("R$ 724,84", Decimal("724.84")),
        # Negativo do ERP: traco DEPOIS do R$, separado por espaco.
        ("R$ - 1.500,75", Decimal("-1500.75")),
        ("-R$ 1.500,75", Decimal("-1500.75")),
        # Pagamento parcial: vale o primeiro valor (o que esta em aberto).
        ("R$ 4.000,00 Pago: R$ 3.230,00", Decimal("4000.00")),
        ("R$ 4.000,00\nPago: R$ 3.230,00", Decimal("4000.00")),
        ("R$ 1,00", Decimal("1.00")),
        ("R$ 0,00", Decimal("0")),
        # Milhar sem centavos.
        ("R$ 1.000", Decimal("1000")),
        # Sem simbolo de moeda, ainda parseavel.
        ("45.678,90", Decimal("45678.90")),
    ],
)
def test_parse_brl(texto, esperado):
    assert parse_brl(texto) == esperado


@pytest.mark.parametrize("texto", ["******", "R$ ******", None, "", "   ", "sem numero"])
def test_parse_brl_sem_valor_legivel_e_none(texto):
    """Mascarado ou vazio NUNCA pode virar zero — zero e um saldo valido."""
    assert parse_brl(texto) is None


def test_is_masked():
    assert is_masked("******")
    assert not is_masked("R$ 724,84")
    assert not is_masked(None)


def test_parse_date_br():
    assert parse_date_br("29/07/2026") == date(2026, 7, 29)
    assert parse_date_br("01/08/26") == date(2026, 8, 1)
    assert parse_date_br("29/07", reference=date(2026, 7, 1)) == date(2026, 7, 29)
    assert parse_date_br("31/02/2026") is None  # data inexistente
    assert parse_date_br("") is None


def test_normalize_name_remove_acento_e_pontuacao():
    assert normalize_name("Morais Participações - MÃE - 11.111-1 - SICOOB") == (
        "MORAIS PARTICIPACOES MAE 11 111 1 SICOOB"
    )
    assert normalize_name("MORAIS EMPREENDIMENTOS BURITIS - CAIXA ECONÔMICA FEDERAL") == (
        "MORAIS EMPREENDIMENTOS BURITIS CAIXA ECONOMICA FEDERAL"
    )


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("Morais Participações - MÃE - 11.111-1 - SICOOB", ["111111"]),
        ("Morais Participações - SUBCONTA 22222-2 - TB 21 QD 51 LT 40 - SICOOB", ["222222"]),
        ("MOURA DANTAS EMPREENDIMENTOS BRADESCO - 33333-3", ["333333"]),
        ("JOAO V PARTICIPACOES - 44.444-4 - SICOOB", ["444444"]),
        ("MORAIS ENGENHARIA - INTER", []),
    ],
)
def test_extract_account_numbers(texto, esperado):
    assert extract_account_numbers(texto) == esperado


def test_normalize_account_number():
    # Com e sem pontuação têm de chegar na mesma forma comparável.
    assert normalize_account_number("11.111-1") == "111111"
    assert normalize_account_number("11111-1") == "111111"
    assert normalize_account_number(None) is None


@pytest.mark.parametrize(
    "texto, esperado",
    [
        ("À Vista MORAIS ENGENHARIA - INTER", "MORAIS ENGENHARIA - INTER"),
        ("Recorrente TERRA BELA - SICOOB", "TERRA BELA - SICOOB"),
        ("À Vista\nMORAIS ENGENHARIA - INTER", "MORAIS ENGENHARIA - INTER"),
        ("MORAIS ENGENHARIA - INTER", "MORAIS ENGENHARIA - INTER"),
    ],
)
def test_strip_condition_prefix(texto, esperado):
    assert strip_condition_prefix(texto) == esperado
