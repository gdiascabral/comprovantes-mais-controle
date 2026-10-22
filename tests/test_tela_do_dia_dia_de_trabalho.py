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
    # chave = destino|aportador; o valor é o que foi mandado (Decimal).
    dia.enviados_aportes["Conta Alfa - Banco|Socio Ficticio"] = D("199.50")
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


@pytest.mark.parametrize("valor", ["2026-10-21T10:00", "NaN", "0", "-5.00"])
def test_enviado_sem_valor_em_decimal_levanta_em_vez_de_esquecer_o_envio(tmp_path, valor):
    caminho = tmp_path / "velho.json"
    caminho.write_text(json.dumps({"data": "2026-10-21",
                                   "enviados_aportes": {"A|B": valor}}), encoding="utf-8")
    with pytest.raises(ValueError, match="velho.json"):
        ddt.ler(caminho, HOJE)


# ------------------------------------------- movimentos «À MÃO» (Tarefa 12)
def test_movimentos_a_mao_ida_e_volta_em_decimal_com_origem_de_fora(tmp_path):
    dia = ddt.DiaDeTrabalho(HOJE)
    dia.a_mao = [(None, "Mae - Banco", D("1000.10")),
                 ("Mae - Banco", "Conta Alfa - Banco", D("250.00"))]
    volta = ddt.ler(ddt.gravar(dia, tmp_path / "d.json"), HOJE)
    assert volta.a_mao == dia.a_mao
    assert all(isinstance(v, D) for _o, _d, v in volta.a_mao)


def test_arquivo_sem_movimentos_a_mao_continua_legivel(tmp_path):
    caminho = tmp_path / "antigo.json"
    caminho.write_text(json.dumps({"data": "2026-10-21"}), encoding="utf-8")
    assert ddt.ler(caminho, HOJE).a_mao == []


@pytest.mark.parametrize("item", [
    {"origem": None, "destino": "Mae - Banco", "valor": "abc"},
    {"origem": None, "destino": "Mae - Banco", "valor": "NaN"},
    {"origem": None, "destino": "", "valor": "10.00"},
    {"origem": 5, "destino": "Mae - Banco", "valor": "10.00"},
    {"origem": None, "valor": "10.00"},
])
def test_movimento_a_mao_estragado_levanta_em_vez_de_sumir(tmp_path, item):
    caminho = tmp_path / "mao.json"
    caminho.write_text(json.dumps({"data": "2026-10-21", "a_mao": [item]}), encoding="utf-8")
    with pytest.raises(ValueError, match="mao.json"):
        ddt.ler(caminho, HOJE)
