"""`ler_regras` guarda a linha de cada regra: é por ela que o Excel do dia acha
a linha da aba «Movimentações». Modelo fictício."""
from decimal import Decimal

import openpyxl

from conciliacao.aportadores import Regra, ler_regras


def test_ler_regras_guarda_a_linha_mesmo_com_buraco(tmp_path):
    wb = openpyxl.Workbook()
    wb.active.title = "Painel"
    reg = wb.create_sheet("Regras")
    reg["B5"], reg["C5"], reg["E5"], reg["F5"] = "Conta Alfa - Banco", "Conta Beta - Banco", "Aporte", "sim"
    reg["B7"], reg["C7"], reg["D7"], reg["E7"] = "Conta Alfa - Banco", "Socio Ficticio", 2, "Aporte"
    caminho = tmp_path / "MODELO.xlsx"
    wb.save(caminho)
    regras = ler_regras(caminho)
    assert [(r.linha, r.aportador) for r in regras] == [(5, "Conta Beta - Banco"), (7, "Socio Ficticio")]
    assert regras[1].peso == Decimal("2")


def test_regra_construida_a_mao_continua_valendo():
    assert Regra("A", "B", None, "Aporte", True).linha == 0
