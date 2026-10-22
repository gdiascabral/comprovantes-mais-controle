# tests/test_tela_do_dia_controle.py
# -*- coding: utf-8 -*-
"""Controle de aportes (`tela_do_dia/controle_aportes.py`). Sem tela, sem rede.

Nomes fictícios: o repositório é público. Os dois aportadores têm o MESMO
primeiro nome de propósito — são pessoas diferentes e nunca se misturam."""
import datetime
from dataclasses import replace
from decimal import Decimal

import pytest

from tela_do_dia import controle_aportes as ca

D = Decimal
ZERO = D("0.00")
ABRE = datetime.date(2026, 10, 21)
HOJE = datetime.date(2026, 10, 23)
ALFA, BETA = "FULANO ALFA DA SILVA", "FULANO BETA SOUZA"


def _conta(alfa_abertura="50000.00", beta_abertura="0.00", pesos=("1", "1")):
    return ca.ContaControlada(
        conta_erp="CONTA MAE - BANCO", abertura=ABRE, id=1, aportadores=(
            ca.Aportador(ALFA, D(pesos[0]), D(alfa_abertura), id=10),
            ca.Aportador(BETA, D(pesos[1]), D(beta_abertura), id=11)))


def _rec(ident, valor, cliente, data=HOJE):
    return ca.Recebimento(id=ident, data=data, valor=D(valor), cliente=cliente)


def test_recebimento_do_erp_le_os_campos_que_a_aba_contratos_ja_le():
    r = ca.recebimento_do_erp(
        {"id": "r1", "dateOfReceipt": "2026-10-22T00:00:00", "sumOfReceivedValues": 1500.5,
         "customerName": f" {ALFA} ", "description": "APORTE CAPITAL - X PARA Y",
         "workName": "CENTRO FICTICIO"}, "Aporte de Capital")
    assert r == ca.Recebimento(id="r1", data=datetime.date(2026, 10, 22), valor=D("1500.50"),
                               cliente=ALFA, natureza="Aporte de Capital",
                               descricao="APORTE CAPITAL - X PARA Y", centro="CENTRO FICTICIO")


@pytest.mark.parametrize("item", [
    {"dateOfReceipt": "2026-10-22", "sumOfReceivedValues": 1},
    {"id": "r", "sumOfReceivedValues": 1},
    {"id": "r", "dateOfReceipt": "2026-10-22"},
    {"id": "r", "dateOfReceipt": "2026-10-22", "sumOfReceivedValues": "abc"},
    {"id": "r", "dateOfReceipt": "2026-10-22", "sumOfReceivedValues": float("nan")},
    {"id": "r", "dateOfReceipt": "2026-10-22", "sumOfReceivedValues": True},
])
def test_recebimento_ilegivel_levanta_e_nunca_vira_zero(item):
    with pytest.raises(ValueError):
        ca.recebimento_do_erp(item)


def test_problemas_da_conta():
    assert ca.problemas_da_conta(_conta(), HOJE) == []
    assert ca.problemas_da_conta(_conta(), HOJE, [_conta()]) == []   # ela mesma não é outra
    texto = lambda c, outras=(): " ".join(ca.problemas_da_conta(c, HOJE, outras))  # noqa: E731
    assert "depois de hoje" in texto(replace(_conta(), abertura=HOJE + datetime.timedelta(days=1)))
    assert "repetido" in texto(replace(_conta(), aportadores=(
        ca.Aportador(ALFA, D(1)), ca.Aportador("fulano álfa da  silva", D(1)))))
    assert "Falta aportador" in texto(replace(_conta(), aportadores=()))
    assert "Proporção" in texto(replace(_conta(), aportadores=(
        ca.Aportador(ALFA, D(0)), ca.Aportador(BETA, D(1)))))
    assert "Proporção" in texto(replace(_conta(), aportadores=(
        ca.Aportador(ALFA, None), ca.Aportador(BETA, D(1)))))
    assert "inválido" in texto(_conta(alfa_abertura="-1.00"))
    assert "já está no controle" in texto(replace(_conta(), id=2), [_conta()])
    assert "nome da conta" in texto(replace(_conta(), conta_erp="  "))


def test_aberturas_para_divida_meio_a_meio():
    assert ca.aberturas_para_divida(_conta().aportadores, "Fulano Beta  Souza", D("50000")) \
        == {ALFA: D("50000.00"), BETA: ZERO}


def test_aberturas_para_divida_recusa_primeiro_nome_e_negativo():
    with pytest.raises(ValueError):
        ca.aberturas_para_divida(_conta().aportadores, "FULANO", D("1"))
    with pytest.raises(ValueError):
        ca.aberturas_para_divida(_conta().aportadores, BETA, D("-1"))
