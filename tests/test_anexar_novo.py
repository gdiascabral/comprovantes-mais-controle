# -*- coding: utf-8 -*-
"""Aba "Anexar (novo)": a Anexar de sempre + somas, sem um segundo navegador.

Testes puros: sem janela Tk. O `__init__` roda com ttk/StringVar trocados por
dublês, como `tests/test_abas_em_paralelo.py` faz com `__new__`."""

import pytest


@pytest.fixture
def modulo():
    pytest.importorskip("playwright")
    from anexar import anexar_comprovantes as modulo
    return modulo


class _Var:
    def __init__(self, master=None, value=None, **_k):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


def _sem_tk(*_a, **_k):
    raise RuntimeError("sem Tk no teste")


def _construir(modulo, monkeypatch, classe, *args):
    import tkinter as tk
    from tkinter import ttk
    ch = {"executor": 0, "after": []}

    def executor(*_a, **_k):
        ch["executor"] += 1
        return object()

    monkeypatch.setattr(ttk.Frame, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(tk, "StringVar", _Var)
    monkeypatch.setattr(tk, "BooleanVar", _Var)
    monkeypatch.setattr(ttk, "Style", _sem_tk)
    monkeypatch.setattr(modulo.AnexarFrame, "_build", lambda self: None)
    monkeypatch.setattr(modulo.AnexarFrame, "after",
                        lambda self, ms, fn=None, *a: ch["after"].append(fn.__name__))
    monkeypatch.setattr(modulo, "ThreadPoolExecutor", executor)
    return classe(None, *args), ch


def test_a_anexar_de_sempre_continua_dona_do_navegador(modulo, monkeypatch):
    assert modulo.AnexarFrame.DONO_DO_NAVEGADOR is True
    assert modulo.AnexarFrame.TITULO == "Anexar Comprovantes"
    assert modulo.AnexarFrame.TRILHA == "Comprovantes  ›  Anexar"
    f, ch = _construir(modulo, monkeypatch, modulo.AnexarFrame)
    assert ch["executor"] == 1 and f.exec is not None
    assert ch["after"] == ["_drain", "_pulsar_navegador"]


def test_o_cabecalho_le_titulo_e_trilha_da_classe(modulo, monkeypatch):
    """O `_build` de sempre passa os atributos ao `Cabecalho` — com os
    padrões, os mesmos textos de antes."""
    vistos = {}

    class _Parou(Exception):
        pass

    def cabecalho(pai, titulo, sub, trilha=None, **_k):
        vistos.update(titulo=titulo, trilha=trilha)
        raise _Parou

    monkeypatch.setattr(modulo.widgets, "Cabecalho", cabecalho)
    f = modulo.AnexarFrame.__new__(modulo.AnexarFrame)
    with pytest.raises(_Parou):
        f._build()
    assert vistos == {"titulo": "Anexar Comprovantes",
                      "trilha": "Comprovantes  ›  Anexar"}
