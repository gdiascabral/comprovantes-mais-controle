# -*- coding: utf-8 -*-
"""Regra da janela "Cadastros" da aba Aportes (`aportes/cadastros.py`).

Nomes fictícios: o repositório é público."""
from __future__ import annotations

import pytest

from aportes import cadastros as cad

CONTAS = [
    {"nome_erp": "Holding - SUBCONTA 11111-1 - BANCO", "empresa_id": 7},
    {"nome_erp": "Holding - SUBCONTA 22222-2 - BANCO", "empresa_id": 7},
    {"nome_erp": "Holding - SUBCONTA 33333-3 - BANCO", "empresa_id": 7},
    {"nome_erp": "OBRA SPE - BANCO", "empresa_id": 9},
    {"nome_erp": "OBRA SPE - OUTRO BANCO", "empresa_id": 9},
]
ENTIDADES = [
    {"id": 1, "nome_exibicao": "OBRA SPE - BANCO", "nome_oficial": "OBRA SPE",
     "conta": "OBRA SPE - BANCO", "nome_descricao": None},
    {"id": 2, "nome_exibicao": "FULANA (pessoa física)",
     "nome_oficial": "FULANA DE TAL", "conta": None, "nome_descricao": "FULANA/BELTRANO"},
    {"id": 3, "nome_exibicao": "SUBCONTA 11111-1 - BANCO - INVESTIDOR",
     "nome_oficial": "HOLDING SPE", "conta": "Holding - SUBCONTA 11111-1 - BANCO",
     "nome_descricao": None},
    {"id": 4, "nome_exibicao": "SUBCONTA 22222-2 - BANCO - INVESTIDOR",
     "nome_oficial": "HOLDING SPE", "conta": "Holding - SUBCONTA 22222-2 - BANCO",
     "nome_descricao": None},
    {"id": 5, "nome_exibicao": "SUBCONTA 33333-3 - BANCO - INVESTIDOR",
     "nome_oficial": "INVESTIDORA LTDA", "conta": "Holding - SUBCONTA 33333-3 - BANCO",
     "nome_descricao": None},
]
RATEIOS = {
    "11111-1": {"investidores": ["INV A", "INV B"], "obras": ["LOTE 1"],
                "pesos": {"INV A": "2", "INV B": "1"}},
    "22222-2": {"investidores": ["INV C"], "obras": ["LOTE 2", "LOTE 3"],
                "pesos": {}},
    "33333-3": {"investidores": ["INVESTIDORA LTDA"],
                "obras": ["A CLASSIFICAR - OBRA PENDENTE"], "pesos": {}},
}
PARTICIPANTES = ["OBRA SPE", "FULANA DE TAL", "HOLDING SPE",
                 "INVESTIDORA LTDA", "OUTRA SPE"]


def _ent(i):
    return next(e for e in ENTIDADES if e["id"] == i)


# ------------------------------------------------------------------ listas
def test_empresas_tira_as_linhas_de_subconta_e_ordena_pelo_nome():
    assert [e["nome_exibicao"] for e in cad.empresas(ENTIDADES, RATEIOS)] == [
        "FULANA (pessoa física)", "OBRA SPE - BANCO"]


def test_subcontas_traz_rateio_percentuais_e_dono():
    linhas = {s.numero: s for s in cad.subcontas(ENTIDADES, RATEIOS)}
    assert list(linhas) == ["11111-1", "22222-2", "33333-3"]
    s = linhas["11111-1"]
    assert s.dono == "HOLDING SPE"
    assert s.entidade["id"] == 3
    assert s.aportadores == ["INV A 66,67%", "INV B 33,33%"]
    assert linhas["22222-2"].aportadores == ["INV C 100%"]
    assert linhas["22222-2"].obras == ["LOTE 2", "LOTE 3"]


def test_subconta_avisa_dono_diferente_dos_outros_e_obra_a_classificar():
    linhas = {s.numero: s for s in cad.subcontas(ENTIDADES, RATEIOS)}
    assert linhas["11111-1"].avisos == []
    assert linhas["33333-3"].avisos == [
        "dono diferente das outras subcontas (HOLDING SPE)",
        "obra a classificar"]


def test_subconta_sem_linha_em_pagou_recebeu_avisa():
    rateios = dict(RATEIOS, **{"44444-4": {"investidores": ["X"],
                                           "obras": ["L"], "pesos": {}}})
    s = {s.numero: s for s in cad.subcontas(ENTIDADES, rateios)}["44444-4"]
    assert s.entidade is None and s.dono == ""
    assert "sem conta em Pagou/Recebeu" in s.avisos


# ---------------------------------------------------------------- mudanças
def test_mudancas_so_o_que_mudou_e_vazio_vira_none():
    depois = {"nome_exibicao": " OBRA SPE - BANCO ", "nome_oficial": "OUTRA SPE",
              "conta": "OBRA SPE - BANCO", "nome_descricao": "  "}
    assert cad.mudancas(_ent(1), depois) == {"nome_oficial": "OUTRA SPE"}
    assert cad.mudancas(_ent(2), {**_ent(2), "nome_descricao": ""}) == {
        "nome_descricao": None}
    assert cad.mudancas(_ent(1), dict(_ent(1))) == {}


# ---------------------------------------------------------------- validar
def _validar(i, **mudou):
    return cad.validar(_ent(i), {**_ent(i), **mudou}, ENTIDADES, RATEIOS,
                       contas=CONTAS, participantes=PARTICIPANTES)


def test_correcao_valida_passa():
    assert _validar(1, nome_oficial="OUTRA SPE",
                    conta="OBRA SPE - OUTRO BANCO") == ""
    assert _validar(2, nome_descricao="") == ""


def test_nada_mudou_e_recusado():
    assert _validar(1) == "Nada mudou."


@pytest.mark.parametrize("campo,valor,trecho", [
    ("nome_exibicao", "  ", "Falta o nome"),
    ("nome_oficial", "", "Falta o nome do contato"),
    ("nome_exibicao", "fulana (PESSOA FÍSICA)", "Já existe"),
    ("nome_oficial", "NAO EXISTE SA", "não existe no Mais Controle"),
    ("conta", "CONTA QUE NAO EXISTE", "não está no cadastro de contas"),
    ("conta", "Holding - SUBCONTA 22222-2 - BANCO", "já está na lista"),
    ("nome_exibicao", "A;B", "ponto e vírgula"),
    ("nome_exibicao", "INVESTIDOR SUBCONTA 1", "rateios de subconta"),
])
def test_correcao_recusada_com_motivo(campo, valor, trecho):
    assert trecho in _validar(1, **{campo: valor})


def test_o_proprio_nome_com_outra_caixa_nao_conta_como_repetido():
    assert _validar(1, nome_exibicao="obra spe - banco") == ""


def test_subconta_so_deixa_corrigir_o_dono():
    assert _validar(5, nome_oficial="HOLDING SPE") == ""
    assert "segue o padrão" in _validar(5, nome_exibicao="OUTRO NOME")
    assert "não muda" in _validar(5, conta="OBRA SPE - OUTRO BANCO")


def test_sem_listas_do_erp_nao_confere_contato_nem_conta():
    assert cad.validar(_ent(1), {**_ent(1), "nome_oficial": "QUALQUER"},
                       ENTIDADES, RATEIOS) == ""


# ----------------------------------------------------- em uso na lista
def test_em_uso_por_nome_em_pagou_ou_recebeu():
    pares = [("OUTRO", "obra spe - banco")]
    assert cad.em_uso(_ent(1), pares)
    assert not cad.em_uso(_ent(2), pares)


def test_subconta_em_uso_pelo_pagador_investidor():
    assert cad.em_uso(_ent(3), [("INVESTIDOR SUBCONTA 11111-1", "X")])
    assert not cad.em_uso(_ent(4), [("INVESTIDOR SUBCONTA 11111-1", "X")])


# ------------------------------------------------------------------ banco
class _Rest:
    def __init__(self, devolve):
        self.devolve = devolve
        self.chamadas = []

    def alterar(self, tabela, token, filtro, mudancas):
        self.chamadas.append((tabela, filtro, mudancas))
        return self.devolve

    def ler(self, tabela, token, colunas="*", filtro=""):
        return ENTIDADES


def test_gravar_altera_so_a_linha_pelo_id(monkeypatch):
    falso = _Rest([{"id": 1}])
    monkeypatch.setattr(cad, "_rest", lambda: falso)
    regravou = []
    monkeypatch.setattr(cad, "_regravar_cache", lambda e: regravou.append(e))
    cad.gravar("tok", 1, {"nome_oficial": "OUTRA SPE"})
    assert falso.chamadas == [("entidade", "id=eq.1",
                               {"nome_oficial": "OUTRA SPE"})]
    assert regravou == [ENTIDADES]


def test_banco_que_nao_altera_nada_e_erro_e_nao_mexe_no_cache(monkeypatch):
    # PATCH barrado pela RLS não dá erro: devolve ZERO linhas. Tratar isso
    # como sucesso diria "corrigido" sem ter corrigido.
    falso = _Rest([])
    monkeypatch.setattr(cad, "_rest", lambda: falso)
    regravou = []
    monkeypatch.setattr(cad, "_regravar_cache", lambda e: regravou.append(e))
    with pytest.raises(RuntimeError, match="não aceitou"):
        cad.gravar("tok", 1, {"nome_oficial": "OUTRA SPE"})
    assert regravou == []


def test_gravar_sem_mudanca_ou_sem_id_recusa(monkeypatch):
    monkeypatch.setattr(cad, "_rest", lambda: _Rest([{"id": 1}]))
    with pytest.raises(ValueError):
        cad.gravar("tok", 1, {})
    with pytest.raises(ValueError):
        cad.gravar("tok", None, {"nome_oficial": "X"})
