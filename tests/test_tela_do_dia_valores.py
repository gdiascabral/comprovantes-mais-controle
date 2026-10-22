"""O dinheiro digitado na aba Pagamentos do dia. Fictício, sem tela."""
from decimal import Decimal

import pytest

from tela_do_dia.valores import brl, de_float, ler_valor_editado


@pytest.mark.parametrize("texto, esperado", [
    ("1.234,56", "1234.56"), ("-1.234,56", "-1234.56"), ("R$ -10,00", "-10.00"),
    ("- R$ 10,00", "-10.00"), ("0", "0.00"), ("0,00", "0.00"), ("1500", "1500.00"),
])
def test_le_o_valor_editado(texto, esperado):
    assert ler_valor_editado(texto) == Decimal(esperado)


@pytest.mark.parametrize("texto", ["1500.50", "", "abc", "1,234", "--5"])
def test_recusa_o_ambiguo_e_o_que_nao_e_valor(texto):
    with pytest.raises(ValueError):
        ler_valor_editado(texto)


def test_de_float_nao_herda_lixo_binario():
    assert de_float(0.1 + 0.2) == Decimal("0.30")
    assert de_float(None) == Decimal("0.00")


def test_brl_mostra_negativo_e_vazio():
    assert brl(Decimal("-1234.5")) == "-R$ 1.234,50"
    assert brl(None) == "—"
