# -*- coding: utf-8 -*-
"""Rateio de subconta pela aba Aportes (`aportes/rateio_subconta.py`).

Nomes fictícios: o repositório é público."""
from __future__ import annotations

import json

import pytest

from aportes import dados as cadastro
from aportes import rateio_subconta as rs


@pytest.mark.parametrize("texto, numero", [
    ("Holding - SUBCONTA 11111-1 - INVESTIDOR X - BANCO", "11111-1"),
    ("Holding - MÃE - 22.222-2 - BANCO", "22222-2"),
    ("conta 33333 - 3", "33333-3"),
    ("sem número", ""),
])
def test_numero_da_conta(texto, numero):
    assert rs.numero_da_conta(texto) == numero


def test_subcontas_possiveis_junta_as_do_rateio_e_as_contas_novas():
    entidades = {
        "SUB 11111": {"conta": "Holding - SUBCONTA 11111-1 - BANCO"},
        "MAE": {"conta": "Holding - MÃE - 22.222-2 - BANCO"},   # não é subconta
        "PF": {"conta": None},
    }
    subcontas = {"_obra_padrao": "X", "44444-4": {}}
    assert rs.subcontas_possiveis(entidades, subcontas) == ["11111-1", "44444-4"]


def test_validar():
    ok = dict(participantes=["INVESTIDOR A LTDA"], centros=["LOTE 1", "LOTE 2"])
    assert rs.validar("11111-1", ["investidor a ltda"], ["LOTE 1"], **ok) == ""
    assert "número" in rs.validar("1111", ["A"], ["B"])
    assert "investidor" in rs.validar("11111-1", [" "], ["B"])
    assert "centro de custo" in rs.validar("11111-1", ["A"], [])
    assert "não existe" in rs.validar("11111-1", ["OUTRO"], ["LOTE 1"], **ok)
    assert "não existe" in rs.validar("11111-1", ["INVESTIDOR A LTDA"],
                                      ["LOTE 9"], **ok)


def test_diferenca_so_mexe_no_que_mudou():
    antes = [{"id": 1, "nome": "LOTE 1"}, {"id": 2, "nome": "LOTE 2"}]
    assert rs.diferenca(antes, ["lote 1", "LOTE 3", "LOTE 3"]) == (["LOTE 3"], [2])
    assert rs.diferenca(antes, ["LOTE 1", "LOTE 2"]) == ([], [])


class _Banco:
    """Dublê do `nuvem.rest` com as três tabelas."""

    def __init__(self):
        self.tabelas = {"subconta": [], "subconta_obra": [],
                        "subconta_investidor": []}
        self.ordem: list[str] = []
        self._id = 100

    def ler(self, tabela, _token, colunas="*", filtro=""):
        campo, _, valor = filtro.partition("=eq.")
        return [dict(l) for l in self.tabelas[tabela]
                if not filtro or str(l.get(campo)) == valor]

    def inserir(self, tabela, _token, linhas, devolver=True):
        self.ordem.append(f"inserir {tabela}")
        saida = []
        for l in linhas:
            self._id += 1
            nova = dict(l, id=self._id)
            self.tabelas[tabela].append(nova)
            saida.append(nova)
        return saida

    def alterar(self, tabela, _token, filtro, mudancas):
        self.ordem.append(f"alterar {tabela}")
        ident = int(filtro.split("=eq.")[1])
        for l in self.tabelas[tabela]:
            if l["id"] == ident:
                l.update(mudancas)
        return []

    def apagar(self, tabela, _token, filtro):
        self.ordem.append(f"apagar {tabela}")
        ids = {int(i) for i in filtro[len("id=in.("):-1].split(",")}
        self.tabelas[tabela] = [l for l in self.tabelas[tabela]
                                if l["id"] not in ids]


@pytest.fixture
def banco(monkeypatch, tmp_path):
    from nuvem import rest
    b = _Banco()
    for nome in ("ler", "inserir", "apagar", "alterar"):
        monkeypatch.setattr(rest, nome, getattr(b, nome))
    arquivo = tmp_path / "subcontas.json"
    arquivo.write_text(json.dumps({"_obra_padrao": "PADRAO"}), encoding="utf-8")
    monkeypatch.setattr(cadastro, "ARQUIVO_SUBCONTAS", arquivo)
    return b


def test_gravar_cria_a_subconta_e_o_cache(banco):
    rs.gravar("tok", "11111-1", ["INV A"], ["LOTE 1", "LOTE 2"])
    assert [s["nome"] for s in banco.tabelas["subconta"]] == ["11111-1"]
    assert {o["nome"] for o in banco.tabelas["subconta_obra"]} == {"LOTE 1", "LOTE 2"}
    cache = cadastro.carregar_subcontas()
    assert cache["_obra_padrao"] == "PADRAO"
    assert cache["11111-1"] == {"obras": ["LOTE 1", "LOTE 2"],
                                "investidores": ["INV A"]}


def test_editar_insere_antes_de_apagar(banco):
    rs.gravar("tok", "11111-1", ["INV A"], ["LOTE 1", "LOTE 2"])
    banco.ordem.clear()
    rs.gravar("tok", "11111-1", ["INV A"], ["LOTE 2", "LOTE 3"])
    assert banco.ordem == ["inserir subconta_obra", "apagar subconta_obra"]
    assert len(banco.tabelas["subconta"]) == 1
    assert {o["nome"] for o in banco.tabelas["subconta_obra"]} == {"LOTE 2", "LOTE 3"}


def test_pagador_e_o_que_a_regra_reconhece():
    from aportes.regras import numero_subconta
    assert numero_subconta(rs.pagador("11111-1"), {"11111-1": {}}) == "11111-1"


def test_mudou_ignora_ordem_e_caixa():
    a = {"11111-1": {"obras": ["LOTE 1", "LOTE 2"], "investidores": ["INV"]}}
    b = {"11111-1": {"obras": ["lote 2", "LOTE 1"], "investidores": ["inv"]}}
    c = {"11111-1": {"obras": ["LOTE 1"], "investidores": ["INV"]}}
    assert not rs.mudou(a, b, "11111-1")
    assert rs.mudou(a, c, "11111-1")
    assert rs.mudou(a, {}, "11111-1")


def test_falha_no_meio_deixa_o_cache_igual_ao_banco(banco, monkeypatch):
    from nuvem import rest
    rs.gravar("tok", "11111-1", ["INV A"], ["LOTE 1", "LOTE 2"])

    def apagar_cai(*_a, **_kw):
        raise rest.SemRede("caiu")

    monkeypatch.setattr(rest, "apagar", apagar_cai)
    with pytest.raises(RuntimeError, match="parou no meio"):
        rs.gravar("tok", "11111-1", ["INV A"], ["LOTE 1", "LOTE 3"])
    # O LOTE 3 entrou, o LOTE 2 não saiu: é isso que o banco tem, e é isso
    # que o cache tem de dizer.
    obras = set(cadastro.carregar_subcontas()["11111-1"]["obras"])
    assert obras == {"LOTE 1", "LOTE 2", "LOTE 3"}


def test_aporte_lancado_pela_metade_trava_a_troca_do_rateio():
    from types import SimpleNamespace
    from aportes.aportes_frame import AportesFrame
    op = SimpleNamespace(pagador=rs.pagador("11111-1"))
    outra = SimpleNamespace(pagador="EMPRESA X")
    meio = SimpleNamespace(operacoes=[outra, op], criados=[{0}, {0}])
    nada = SimpleNamespace(operacoes=[op], criados=[set()])
    assert AportesFrame._subconta_em_andamento(meio, "11111-1")
    assert not AportesFrame._subconta_em_andamento(nada, "11111-1")
    assert not AportesFrame._subconta_em_andamento(meio, "22222-2")


def test_percentual_grava_troca_e_vai_para_o_cache(banco):
    rs.gravar("tok", "11111-1", ["INV A"], ["LOTE 1", "LOTE 2"],
              {"LOTE 1": "70", "LOTE 2": "30"})
    pct = {o["nome"]: o["percentual"] for o in banco.tabelas["subconta_obra"]}
    assert pct == {"LOTE 1": "70", "LOTE 2": "30"}
    banco.ordem.clear()
    rs.gravar("tok", "11111-1", ["INV A"], ["LOTE 1", "LOTE 2"],
              {"LOTE 1": "50", "LOTE 2": "50"})
    assert banco.ordem == ["alterar subconta_obra", "alterar subconta_obra"]
    cache = cadastro.carregar_subcontas()["11111-1"]
    assert cache["percentuais"] == {"LOTE 1": "50", "LOTE 2": "50"}
    # tirar os % volta a partes iguais
    rs.gravar("tok", "11111-1", ["INV A"], ["LOTE 1", "LOTE 2"], {})
    assert "percentuais" not in cadastro.carregar_subcontas()["11111-1"]


def test_validar_percentual_na_janela():
    assert "somam" in rs.validar("11111-1", ["A"], ["L1", "L2"],
                                 percentuais={"L1": "70", "L2": "20"})
    assert rs.validar("11111-1", ["A"], ["L1", "L2"],
                      percentuais={"L1": "70", "L2": "30"}) == ""


def test_mudou_enxerga_troca_de_percentual():
    a = {"1": {"obras": ["L"], "investidores": ["I"], "percentuais": {"L": "100"}}}
    b = {"1": {"obras": ["L"], "investidores": ["I"]}}
    assert rs.mudou(a, b, "1")
