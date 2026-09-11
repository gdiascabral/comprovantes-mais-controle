# -*- coding: utf-8 -*-
"""Janela "Resolver dúvidas" do Anexar: o que ela grava e quanto ela custa.

A regra de dinheiro — um PDF vai para UM pagamento, e só o que a pessoa
escolheu vira CERTEZA — mora em funções puras e é testada sem Tk.

A janela em si é montada de verdade, mas RETIRADA (`withdraw` antes do
primeiro `update`): o Windows nunca a mostra e ela não toma o foco de quem
está usando a máquina. Os cliques são `selection_set` + `update`, que é o
caminho do <<TreeviewSelect>> de verdade — ele entra na fila do Tk, e é
justamente a fila que o código precisa aguentar.

O teste que importa mais é o do TAMANHO: até 11/09/2026 a janela tinha um
bloco de widgets por dúvida num Canvas rolável, e 184 dúvidas davam 2.032
widgets e 86 s só de geometria. A lista com 3 ou com 300 dúvidas tem de ter
os mesmos widgets.
"""
import tkinter as tk
from threading import Event
from tkinter import ttk

import pytest

from anexar import anexar_comprovantes as ac


def _pdf(fn, used_by=None):
    return {"fn": fn, "data": "0109", "desc": "FORNECEDOR", "used_by": used_by}


def _cand(pdf, score=0, cc=False, date=False):
    return {"pdf": pdf, "ocnf": False, "cc": cc, "date": date,
            "docnum": False, "score": score}


def _duvida(i, cands):
    return {"paidId": f"p{i}", "launchId": str(100 + i), "valor": 600000,
            "valores": [600000], "dataFull": "2026-09-01", "conta": "CONTA A",
            "favorecido": "FAVORECIDO", "desc": "DESCRIÇÃO", "works": ["OBRA"],
            "doc": "", "ocs": [], "categoria": "Categoria", "cands": cands,
            "status": "DUVIDA"}


def _duvidas_com_os_mesmos_pdfs(n):
    """`n` pagamentos de mesmo valor disputando os MESMOS dois PDFs — é como
    o `matcher.casar` os entrega: candidatos por pagamento, PDF partilhado."""
    a, b = _pdf("a.pdf"), _pdf("b.pdf")
    return [_duvida(i, [_cand(a, score=10, cc=True), _cand(b, score=1, date=True)])
            for i in range(n)], (a, b)


# ------------------------------------------------------------ regras puras

def test_candidatos_livres_sem_dono_do_mais_provavel_para_o_menos():
    a, b, c = _pdf("a.pdf"), _pdf("b.pdf"), _pdf("c.pdf", used_by="outro")
    pe = _duvida(0, [_cand(a, 1), _cand(b, 10), _cand(c, 100)])
    assert [x["pdf"]["fn"] for x in ac._candidatos_livres(pe)] == ["b.pdf", "a.pdf"]


def test_resumo_do_relatorio_segue_a_mesma_ordem():
    a, b = _pdf("a.pdf"), _pdf("b.pdf")
    pe = _duvida(0, [_cand(a, 1, date=True), _cand(b, 10, cc=True)])
    assert ac._resumo_cands(pe) == "b.pdf  [centro de custo] || a.pdf  [data]"


def test_so_o_escolhido_vira_certeza():
    duvidas, (a, b) = _duvidas_com_os_mesmos_pdfs(2)
    assert ac._aplicar_escolhas(duvidas, {1: b}) == 1
    assert duvidas[0]["status"] == "DUVIDA" and "pdf" not in duvidas[0]
    assert duvidas[1]["status"] == "CERTEZA"
    assert duvidas[1]["pdf"] == "b.pdf"
    assert duvidas[1]["motivo"] == "escolhido por você"
    assert b["used_by"] == "p1" and a["used_by"] is None


def test_o_mesmo_pdf_nao_vai_para_dois_pagamentos():
    duvidas, (a, _b) = _duvidas_com_os_mesmos_pdfs(2)
    assert ac._aplicar_escolhas(duvidas, {0: a, 1: a}) == 1
    assert duvidas[0]["status"] == "CERTEZA"
    assert duvidas[1]["status"] == "DUVIDA"
    assert a["used_by"] == "p0"


def test_pdf_que_ja_tem_dono_nao_e_regravado():
    duvidas, (a, _b) = _duvidas_com_os_mesmos_pdfs(1)
    a["used_by"] = "p9"
    assert ac._aplicar_escolhas(duvidas, {0: a}) == 0
    assert duvidas[0]["status"] == "DUVIDA" and a["used_by"] == "p9"


def test_data_curta():
    assert ac._data_curta("2026-09-01") == "01/09/2026"
    assert ac._data_curta("01/09/2026") == "01/09/2026"
    assert ac._data_curta("") == "—"


# ----------------------------------------------------------------- a janela

def _todos(pai):
    for filho in pai.winfo_children():
        yield filho
        yield from _todos(filho)


def _tabelas(top):
    """[lista de pagamentos, tabela de PDFs], na ordem em que nascem."""
    return [w for w in _todos(top) if w.winfo_class() == "Treeview"]


def _botao(top, texto):
    for w in _todos(top):
        if w.winfo_class() in ("Button", "TButton") and texto in str(w.cget("text")):
            return w
    raise AssertionError(f"não achei o botão {texto!r}")


@pytest.fixture
def abrir(raiz, monkeypatch, tmp_path):
    """Abre a janela de dúvidas RETIRADA e devolve (janela, evento)."""
    original = tk.Toplevel

    class Retirada(original):
        def __init__(self, *a, **k):
            super().__init__(*a, **k)
            self.withdraw()

        def grab_set(self):              # grab em janela retirada estoura
            pass

    monkeypatch.setattr(tk, "Toplevel", Retirada)
    donos = []

    def _abrir(duvidas):
        dono = ttk.Frame(raiz)
        dono.v_pasta = tk.StringVar(raiz, value=str(tmp_path))
        donos.append(dono)
        ev = Event()
        ac.AnexarFrame._janela_duvidas(dono, duvidas, ev)
        top = next(w for w in dono.winfo_children() if isinstance(w, original))
        raiz.update()
        return top, ev

    yield _abrir
    for dono in donos:
        try:
            dono.destroy()
        except tk.TclError:
            pass


def test_a_janela_nao_cresce_com_o_numero_de_duvidas(abrir):
    pequena, _ = abrir(_duvidas_com_os_mesmos_pdfs(3)[0])
    grande, _ = abrir(_duvidas_com_os_mesmos_pdfs(300)[0])
    assert len(list(_todos(grande))) == len(list(_todos(pequena)))
    lista, _tv = _tabelas(grande)
    assert len(lista.get_children()) == 300


def test_escolher_e_confirmar_grava_so_o_escolhido(abrir, raiz):
    duvidas, (_a, b) = _duvidas_com_os_mesmos_pdfs(3)
    top, ev = abrir(duvidas)
    lista, tv = _tabelas(top)
    lista.selection_set("1")
    raiz.update()
    assert tv.get_children() == ("_nada", "c0", "c1")
    assert tv.selection() == ("_nada",), "sem escolha, começa em dúvida"
    tv.selection_set("c1")                   # b.pdf
    raiz.update()
    assert lista.set("1", "situacao") == "✓ escolhido"
    assert lista.set("0", "situacao") == "· em dúvida"
    _botao(top, "Confirmar").invoke()
    assert ev.is_set()
    assert duvidas[1]["status"] == "CERTEZA" and duvidas[1]["pdf"] == "b.pdf"
    assert duvidas[0]["status"] == "DUVIDA" and duvidas[2]["status"] == "DUVIDA"
    assert b["used_by"] == "p1"


def test_voltar_a_uma_duvida_mostra_o_que_foi_escolhido(abrir, raiz):
    duvidas, _ = _duvidas_com_os_mesmos_pdfs(2)
    top, _ev = abrir(duvidas)
    lista, tv = _tabelas(top)
    tv.selection_set("c1")
    raiz.update()
    lista.selection_set("1")
    raiz.update()
    lista.selection_set("0")
    raiz.update()
    assert tv.selection() == ("c1",)
    assert lista.set("0", "situacao") == "✓ escolhido"


def test_o_mesmo_pdf_escolhido_de_novo_muda_de_lugar(abrir, raiz):
    duvidas, (a, _b) = _duvidas_com_os_mesmos_pdfs(2)
    top, _ev = abrir(duvidas)
    lista, tv = _tabelas(top)
    tv.selection_set("c0")                   # a.pdf no pagamento 0
    raiz.update()
    lista.selection_set("1")
    raiz.update()
    assert tv.set("c0", "sinais").startswith("⚠"), \
        "tem de avisar que o PDF já está noutro pagamento"
    tv.selection_set("c0")                   # o mesmo a.pdf no pagamento 1
    raiz.update()
    assert lista.set("0", "situacao") == "· em dúvida"
    assert lista.set("1", "situacao") == "✓ escolhido"
    _botao(top, "Confirmar").invoke()
    assert a["used_by"] == "p1"
    assert duvidas[0]["status"] == "DUVIDA"


def test_proxima_pula_o_que_ja_foi_decidido(abrir, raiz):
    duvidas, _ = _duvidas_com_os_mesmos_pdfs(3)
    top, _ev = abrir(duvidas)
    lista, tv = _tabelas(top)
    lista.selection_set("1")
    raiz.update()
    tv.selection_set("c0")
    raiz.update()
    lista.selection_set("0")
    raiz.update()
    _botao(top, "Próxima").invoke()
    raiz.update()
    assert lista.selection() == ("2",), "a 1 já tinha PDF escolhido"


def test_sair_com_escolhas_pergunta_antes_de_descartar(abrir, raiz, monkeypatch):
    duvidas, _ = _duvidas_com_os_mesmos_pdfs(2)
    top, ev = abrir(duvidas)
    _lista, tv = _tabelas(top)
    tv.selection_set("c0")
    raiz.update()
    perguntas = []
    monkeypatch.setattr(ac.messagebox, "askyesno",
                        lambda *a, **k: perguntas.append(a) or False)
    _botao(top, "Deixar todas").invoke()
    assert perguntas, "escolha feita não pode sumir sem perguntar"
    assert top.winfo_exists() and not ev.is_set()
    monkeypatch.setattr(ac.messagebox, "askyesno", lambda *a, **k: True)
    _botao(top, "Deixar todas").invoke()
    assert ev.is_set()
    assert all(d["status"] == "DUVIDA" for d in duvidas)
