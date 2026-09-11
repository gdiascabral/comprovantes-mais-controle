# -*- coding: utf-8 -*-
"""A janela de contas novas do ERP: o que ela devolve e quanto ela custa.

O que vai para o cadastro sai de `escolhas_marcadas`, função pura, testada
sem Tk. A janela é montada de verdade, mas RETIRADA (`withdraw` antes do
primeiro `update`, e o `deiconify` do fim anulado): o Windows nunca a mostra
e ela não toma o foco de quem está usando a máquina. Marcar é o evento
virtual `<<AlternarMarca>>`, o mesmo caminho do Espaço.

Até 11/09/2026 cada conta era um bloco de widgets num Canvas rolável: 21
contas custavam 1,45 s de geometria (0,15 s num frame comum), e a janela
levava 2,2 s para aparecer na abertura do app.
"""
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

from nuvem import contas_novas_dialogo as dialogo

EMPRESAS = [(1, "EMPRESA MODELO"), (2, "OUTRA EMPRESA MODELO")]


def _conta(i, sugerida=""):
    return SimpleNamespace(
        nome=f"CONTA NOVA FICTICIA {i:02d}", banco="756", agencia="1234",
        numero=f"{90000 + i}-1", resumo=f"banco 756 · ag 1234 · conta {90000 + i}-1",
        pasta_sugerida=f"SUBCONTA {i:02d}",
        empresa_sugerida=lambda _nomes, s=sugerida: s)


# ------------------------------------------------------------- regra pura

def test_so_as_marcadas_vao_e_a_empresa_vira_id():
    a, b, c = _conta(1), _conta(2), _conta(3)
    linhas = [(a, True, "EMPRESA MODELO", "SICOOB"),
              (b, False, "EMPRESA MODELO", "X"),
              (c, True, "", "Y")]
    escolhas = dialogo.escolhas_marcadas(linhas, {"EMPRESA MODELO": 7})
    assert [e["nome_erp"] for e in escolhas] == [a.nome, c.nome]
    assert escolhas[0] == {"nome_erp": a.nome, "empresa_id": 7,
                           "pasta": "SICOOB", "banco": "756",
                           "agencia": "1234", "numero": "90001-1"}
    assert escolhas[1]["empresa_id"] is None, \
        "marcada sem empresa segue — quem grava recusa com o motivo"


def test_a_roda_anda_nos_dois_sentidos_mesmo_no_touchpad():
    assert dialogo._passos_da_roda(120) == -1
    assert dialogo._passos_da_roda(-240) == 2
    assert dialogo._passos_da_roda(30) == -1
    assert dialogo._passos_da_roda(-30) == 1


# ----------------------------------------------------------------- a janela

def _todos(pai):
    for filho in pai.winfo_children():
        yield filho
        yield from _todos(filho)


def _um(top, classe):
    return next(w for w in _todos(top) if w.winfo_class() == classe)


def _perguntar(raiz, monkeypatch, novas, roteiro=None):
    """Abre a janela RETIRADA, deixa o `roteiro(top, tabela)` agir e devolve
    (as escolhas, quantos widgets a janela tinha)."""
    original = tk.Toplevel

    class Retirada(original):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.withdraw()

        def deiconify(self):             # a janela nunca vai para a tela
            pass

        def grab_set(self):              # grab em janela retirada estoura
            pass

    monkeypatch.setattr(tk, "Toplevel", Retirada)
    pai = ttk.Frame(raiz)
    visto = {}

    def esperar(top):
        raiz.update()
        visto["widgets"] = len(list(_todos(top)))
        if roteiro:
            roteiro(top, _um(top, "Treeview"))

    pai.wait_window = esperar
    try:
        return dialogo.perguntar(pai, novas, EMPRESAS), visto["widgets"]
    finally:
        pai.destroy()


def _selecionar(raiz, tabela, iid):
    tabela.selection_set(iid)
    tabela.focus(iid)
    raiz.update()


def test_a_janela_nao_cresce_com_o_numero_de_contas(raiz, monkeypatch):
    _e, pequena = _perguntar(raiz, monkeypatch, [_conta(i) for i in range(3)])
    _e, grande = _perguntar(raiz, monkeypatch, [_conta(i) for i in range(300)])
    assert grande == pequena


def test_sugerida_chega_marcada_e_o_editor_preenche_a_conta_certa(raiz,
                                                                  monkeypatch):
    novas = [_conta(1, sugerida="EMPRESA MODELO"), _conta(2)]
    visto = {}

    def roteiro(top, tabela):
        visto["marcas"] = (tabela.set("0", "marca"), tabela.set("1", "marca"))
        _selecionar(raiz, tabela, "1")
        visto["pasta_no_editor"] = _um(top, "TEntry").get()
        _um(top, "TCombobox").set("OUTRA EMPRESA MODELO")
        campo = _um(top, "TEntry")
        campo.delete(0, "end")
        campo.insert(0, "SUBCONTA NOVA")
        tabela.event_generate("<<AlternarMarca>>")
        visto["celulas"] = (tabela.set("1", "empresa"), tabela.set("1", "pasta"))
        # Voltar à primeira não pode escrever nela o que estava no editor.
        _selecionar(raiz, tabela, "0")
        visto["editor_da_primeira"] = _um(top, "TCombobox").get()
        next(w for w in _todos(top) if w.winfo_class() == "TButton"
             and str(w.cget("text")) == "Cadastrar").invoke()

    escolhas, _w = _perguntar(raiz, monkeypatch, novas, roteiro)
    assert visto["marcas"] == (dialogo.MARCADA, dialogo.DESMARCADA)
    assert visto["pasta_no_editor"] == "SUBCONTA 02"
    assert visto["celulas"] == ("OUTRA EMPRESA MODELO", "SUBCONTA NOVA")
    assert visto["editor_da_primeira"] == "EMPRESA MODELO"
    assert [(e["nome_erp"], e["empresa_id"], e["pasta"]) for e in escolhas] == [
        (novas[0].nome, 1, "SUBCONTA 01"),
        (novas[1].nome, 2, "SUBCONTA NOVA")]


def test_agora_nao_nao_grava_nada(raiz, monkeypatch):
    def roteiro(top, _tabela):
        next(w for w in _todos(top) if w.winfo_class() == "TButton"
             and str(w.cget("text")) == "Agora não").invoke()

    escolhas, _w = _perguntar(raiz, monkeypatch,
                              [_conta(1, sugerida="EMPRESA MODELO")], roteiro)
    assert escolhas == []
