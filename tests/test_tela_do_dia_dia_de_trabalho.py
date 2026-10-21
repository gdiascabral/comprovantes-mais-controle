"""O JSON do dia de trabalho. Valores e contas fictícios."""
import json
from datetime import date
from decimal import Decimal as D
from pathlib import Path

import pytest

from tela_do_dia import dia_de_trabalho as ddt
from tela_do_dia.saldos import BANCO, SISTEMA, Ajuste

HOJE = date(2026, 10, 21)


def test_caminho_ao_lado_do_excel_do_dia():
    assert ddt.pasta_do_dia(Path("C:/X"), HOJE) == Path("C:/X/2026/OUTUBRO")
    assert ddt.caminho_do_dia(Path("C:/X"), HOJE).name == "21 10 - dia de trabalho.json"


def test_ida_e_volta_preserva_decimal(tmp_path):
    dia = ddt.DiaDeTrabalho(HOJE)
    dia.ajustes["Conta Alfa - Banco"] = {SISTEMA: Ajuste(D("-5.10"), D("100.00"), "simulação", "2026-10-21T09:00"),
                                          BANCO: Ajuste(D("98.00"), None)}
    dia.aportes[("Conta Alfa - Banco", "Socio Ficticio")] = D("199.50")
    dia.enviados_aportes["Conta Alfa - Banco|Socio Ficticio|199.50"] = "2026-10-21T10:00"
    caminho = ddt.gravar(dia, tmp_path / "x" / "dia.json")
    volta = ddt.ler(caminho, HOJE)
    assert volta == dia
    assert not list(caminho.parent.glob("*.tmp"))


def test_arquivo_ausente_e_dia_vazio(tmp_path):
    assert ddt.ler(tmp_path / "nada.json", HOJE) == ddt.DiaDeTrabalho(HOJE)


def test_arquivo_de_outra_data_levanta_em_vez_de_dia_vazio(tmp_path):
    caminho = ddt.gravar(ddt.DiaDeTrabalho(date(2026, 10, 20), aportes={("A", "B"): D("1")}), tmp_path / "d.json")
    with pytest.raises(ValueError, match="2026-10-20") as e:
        ddt.ler(caminho, HOJE)
    assert "2026-10-21" in str(e.value)


@pytest.mark.parametrize("conteudo", ["{", json.dumps({"data": "2026-10-21", "ajustes": [{"conta": "A"}]})])
def test_arquivo_ilegivel_levanta_com_o_caminho(tmp_path, conteudo):
    caminho = tmp_path / "ruim.json"
    caminho.write_text(conteudo, encoding="utf-8")
    with pytest.raises(ValueError, match="ruim.json"):
        ddt.ler(caminho, HOJE)
