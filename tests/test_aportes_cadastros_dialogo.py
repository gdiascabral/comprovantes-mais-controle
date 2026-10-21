# -*- coding: utf-8 -*-
"""A janela Cadastros (`aportes/cadastros_dialogo.py`) montada de verdade, mas
sem aparecer: `_mostrar` é trocado por quem confere e fecha, e a janela fica
retirada (`withdraw`) — não rouba o foco de quem usa a máquina.

Nomes fictícios: o repositório é público."""
from __future__ import annotations

from tkinter import ttk

import pytest

from aportes import cadastros_dialogo as dlg

from test_aportes_cadastros import CONTAS, ENTIDADES, PARTICIPANTES, RATEIOS


def _todos(w):
    yield w
    for filho in w.winfo_children():
        yield from _todos(filho)


def _arvores(top):
    return [w for w in _todos(top) if isinstance(w, ttk.Treeview)]


def _botao(top, texto):
    return next(w for w in _todos(top)
                if isinstance(w, ttk.Button) and w.cget("text") == texto)


@pytest.fixture
def janela(raiz, monkeypatch):
    """Roda `abrir` com um `_mostrar` que entrega a janela ao teste."""
    def rodar(conferir, **kw):
        def mostrar(top, _pai):
            try:
                conferir(top)
            finally:
                if top.winfo_exists():
                    top.destroy()
        monkeypatch.setattr(dlg, "_mostrar", mostrar)
        args = dict(entidades=ENTIDADES, rateios=RATEIOS, contas=CONTAS,
                    participantes=PARTICIPANTES,
                    gravar=lambda *a: None, em_uso=lambda e: False)
        args.update(kw)
        return dlg.abrir(raiz, **args)
    return rodar


def test_as_duas_abas_mostram_empresas_e_subcontas(janela):
    vistos = {}

    def conferir(top):
        emp, sub = _arvores(top)
        vistos["emp"] = [emp.item(i, "values")[0] for i in emp.get_children()]
        vistos["sub"] = {emp_v[0]: emp_v for emp_v in
                         (sub.item(i, "values") for i in sub.get_children())}
        vistos["tags"] = {sub.item(i, "values")[0]: sub.item(i, "tags")
                          for i in sub.get_children()}

    assert janela(conferir) is None
    assert vistos["emp"] == ["FULANA (pessoa física)", "OBRA SPE - BANCO"]
    assert list(vistos["sub"]) == ["11111-1", "22222-2", "33333-3"]
    assert vistos["sub"]["33333-3"][4].startswith("⚠ dono diferente")
    assert "atencao" in vistos["tags"]["33333-3"]
    assert "atencao" not in vistos["tags"]["11111-1"]


def test_editar_rateio_devolve_a_conta_da_subconta(janela):
    def conferir(top):
        _, sub = _arvores(top)
        sub.selection_set(sub.get_children()[1])
        _botao(top, "Editar rateio").invoke()

    assert janela(conferir) == ("rateio", "Holding - SUBCONTA 22222-2 - BANCO")


def test_corrigir_entrega_so_a_mudanca_para_gravar(janela, monkeypatch):
    gravados = []

    def corrigir(_pai, entidade, **kw):
        assert kw["so_dono"] is False
        return {"nome_oficial": "OUTRA SPE"}

    monkeypatch.setattr(dlg, "corrigir", corrigir)

    def conferir(top):
        emp, _ = _arvores(top)
        emp.selection_set(emp.get_children()[1])          # OBRA SPE - BANCO
        _botao(top, "Corrigir").invoke()

    janela(conferir, gravar=lambda antes, mud, pronto:
           gravados.append((antes["id"], mud)))
    assert gravados == [(1, {"nome_oficial": "OUTRA SPE"})]


def test_janelinha_recusa_quem_esta_na_lista_a_lancar(raiz, monkeypatch):
    recado = {}

    def mostrar(top, _pai):
        top_vars = [w for w in _todos(top) if isinstance(w, ttk.Combobox)]
        top_vars[0].set("OUTRA SPE")                       # o contato
        _botao(top, "Salvar correção").invoke()
        recado["erro"] = next(w.cget("text") for w in _todos(top)
                              if isinstance(w, ttk.Label)
                              and w.cget("style") == "Erro.TLabel")
        top.destroy()

    monkeypatch.setattr(dlg, "_mostrar", mostrar)
    r = dlg.corrigir(raiz, ENTIDADES[0], so_dono=False, entidades=ENTIDADES,
                     rateios=RATEIOS, contas=CONTAS,
                     participantes=PARTICIPANTES, em_uso=lambda e: True)
    assert r is None
    assert "A lançar" in recado["erro"]


def test_janelinha_valida_e_devolve_a_mudanca(raiz, monkeypatch):
    def mostrar(top, _pai):
        combos = [w for w in _todos(top) if isinstance(w, ttk.Combobox)]
        combos[0].set("OUTRA SPE")
        _botao(top, "Salvar correção").invoke()

    monkeypatch.setattr(dlg, "_mostrar", mostrar)
    r = dlg.corrigir(raiz, ENTIDADES[0], so_dono=False, entidades=ENTIDADES,
                     rateios=RATEIOS, contas=CONTAS,
                     participantes=PARTICIPANTES, em_uso=lambda e: False)
    assert r == {"nome_oficial": "OUTRA SPE"}


def test_na_subconta_so_o_dono_fica_editavel(raiz, monkeypatch):
    estados = {}

    def mostrar(top, _pai):
        for w in _todos(top):
            if isinstance(w, (ttk.Entry, ttk.Combobox)):
                estados[str(w.cget("textvariable"))] = str(w.cget("state"))
        top.destroy()

    monkeypatch.setattr(dlg, "_mostrar", mostrar)
    dlg.corrigir(raiz, ENTIDADES[4], so_dono=True, entidades=ENTIDADES,
                 rateios=RATEIOS, contas=CONTAS, participantes=PARTICIPANTES,
                 em_uso=lambda e: False)
    assert sorted(estados.values()) == ["disabled", "disabled", "disabled",
                                        "normal"]
