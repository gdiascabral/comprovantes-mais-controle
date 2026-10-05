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
    linhas = [(a, True, "EMPRESA MODELO", "SICOOB", "ROTULO", False),
              (b, False, "EMPRESA MODELO", "X", "ROTULO", True),
              (c, True, "", "Y", "ROTULO", False)]
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


def _perguntar(raiz, monkeypatch, novas, roteiro=None, conferir_painel=None):
    """Abre a janela RETIRADA, deixa o `roteiro(top, tabela)` agir e devolve
    (as respostas, quantos widgets a janela tinha)."""
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
        return (dialogo.perguntar(pai, novas, EMPRESAS,
                                  conferir_painel=conferir_painel),
                visto["widgets"])
    finally:
        pai.destroy()


def _entradas(top):
    """Os `TEntry` na ordem do editor: o primeiro é a pasta, o segundo a linha
    do painel."""
    return [w for w in _todos(top) if w.winfo_class() == "TEntry"]


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
        visto["pasta_no_editor"] = _entradas(top)[0].get()
        _um(top, "TCombobox").set("OUTRA EMPRESA MODELO")
        campo = _entradas(top)[0]
        campo.delete(0, "end")
        campo.insert(0, "SUBCONTA NOVA")
        tabela.event_generate("<<AlternarMarca>>")
        visto["celulas"] = (tabela.set("1", "empresa"), tabela.set("1", "pasta"))
        # Voltar à primeira não pode escrever nela o que estava no editor.
        _selecionar(raiz, tabela, "0")
        visto["editor_da_primeira"] = _um(top, "TCombobox").get()
        next(w for w in _todos(top) if w.winfo_class() == "TButton"
             and str(w.cget("text")) == "Incluir").invoke()

    respostas, _w = _perguntar(raiz, monkeypatch, novas, roteiro)
    escolhas = respostas.cadastro
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

    respostas, _w = _perguntar(raiz, monkeypatch,
                               [_conta(1, sugerida="EMPRESA MODELO")], roteiro)
    assert not respostas
    assert respostas.cadastro == [] and respostas.painel == []


# ------------------------------------------- cadastro + painel na mesma janela

def _pend(i, *, cadastro=True, painel=False, sugerida=""):
    c = _conta(i, sugerida)
    c.falta_cadastro, c.falta_painel = cadastro, painel
    c.rotulo = f"LINHA {i:02d}"
    c.falta_em = ("painel" if not cadastro
                  else ("cadastro e painel" if painel else "cadastro"))
    return c


def test_painel_marcadas_so_quem_falta_no_painel_e_tem_a_marca_do_painel():
    a, b, c = (_pend(1, painel=True), _pend(2, painel=False),
               _pend(3, painel=True))
    # A marca do cadastro (2º campo) não vale para o painel: só o 6º campo.
    linhas = [(a, False, "EMPRESA MODELO", "P", " LINHA 01 ", True),
              (b, True, "EMPRESA MODELO", "P", "LINHA 02", True),
              (c, True, "EMPRESA MODELO", "P", "LINHA 03", False)]
    assert dialogo.painel_marcadas(linhas) == [(a, "LINHA 01")]


def test_quem_ja_tem_cadastro_nao_volta_para_o_cadastro():
    a = _pend(1, cadastro=False, painel=True)
    linhas = [(a, True, "", "", "LINHA 01", True)]
    assert dialogo.escolhas_marcadas(linhas, {}) == []
    assert dialogo.painel_marcadas(linhas) == [(a, "LINHA 01")]


def _botao(top, texto):
    return next(w for w in _todos(top) if w.winfo_class() == "TButton"
                and str(w.cget("text")) == texto)


def test_sugerida_marca_so_o_cadastro_e_o_painel_nasce_desmarcado(raiz,
                                                                   monkeypatch):
    """Revisão final: a marca que nasce com a empresa sugerida incluía a conta
    também no painel do Saldo, sem ninguém ter marcado."""
    novas = [_pend(1, painel=True, sugerida="EMPRESA MODELO"),
             _pend(2, cadastro=False, painel=True, sugerida="EMPRESA MODELO")]
    visto = {}

    def roteiro(top, tabela):
        visto["0"] = (tabela.set("0", "marca"), tabela.set("0", "painel"))
        visto["1"] = (tabela.set("1", "marca"), tabela.set("1", "painel"))
        _botao(top, "Incluir").invoke()

    respostas, _w = _perguntar(raiz, monkeypatch, novas, roteiro)
    assert visto["0"] == (dialogo.MARCADA, dialogo.DESMARCADA)
    # Só falta no painel: não tem marca de cadastro e não nasce marcada.
    assert visto["1"] == ("—", dialogo.DESMARCADA)
    assert [e["nome_erp"] for e in respostas.cadastro] == [novas[0].nome]
    assert respostas.painel == []


def test_marcar_o_painel_pelo_evento_inclui_no_painel(raiz, monkeypatch):
    novas = [_pend(1, painel=True, sugerida="EMPRESA MODELO")]
    visto = {}

    def roteiro(top, tabela):
        tabela.event_generate("<<AlternarPainel>>")
        visto["celula"] = tabela.set("0", "painel")
        _botao(top, "Incluir").invoke()

    respostas, _w = _perguntar(raiz, monkeypatch, novas, roteiro)
    assert visto["celula"] == dialogo.MARCADA
    assert [e["nome_erp"] for e in respostas.cadastro] == [novas[0].nome]
    assert respostas.painel == [(novas[0], "LINHA 01")]


def test_marca_do_cadastro_nao_mexe_em_quem_so_falta_no_painel(raiz,
                                                               monkeypatch):
    novas = [_pend(1, cadastro=False, painel=True)]

    def roteiro(top, tabela):
        tabela.event_generate("<<AlternarMarca>>")
        _botao(top, "Incluir").invoke()

    respostas, _w = _perguntar(raiz, monkeypatch, novas, roteiro)
    assert not respostas


def test_problema_do_painel_mostra_a_lista_e_nao_fecha(raiz, monkeypatch):
    """Como a janela antiga do painel: conferir antes, e quem errou o nome
    corrige sem redigitar tudo."""
    novas = [_pend(1, painel=True, sugerida="EMPRESA MODELO")]
    avisos, conferidos = [], []
    monkeypatch.setattr(dialogo.messagebox, "showwarning",
                        lambda titulo, texto, **k: avisos.append(texto))

    def conferir(painel):
        conferidos.append([(c.nome, r) for c, r in painel])
        return [] if painel[0][1] == "LINHA BOA" else ["LINHA 01: nome ruim."]

    visto = {}

    def roteiro(top, tabela):
        tabela.event_generate("<<AlternarPainel>>")
        _botao(top, "Incluir").invoke()
        visto["aberta"] = bool(top.winfo_exists())
        visto["pasta"] = _entradas(top)[0].get()
        rotulo = _entradas(top)[1]
        rotulo.delete(0, "end")
        rotulo.insert(0, "LINHA BOA")
        _botao(top, "Incluir").invoke()

    respostas, _w = _perguntar(raiz, monkeypatch, novas, roteiro,
                               conferir_painel=conferir)
    assert avisos and "LINHA 01: nome ruim." in avisos[0]
    assert visto == {"aberta": True, "pasta": "SUBCONTA 01"}
    assert conferidos == [[(novas[0].nome, "LINHA 01")],
                          [(novas[0].nome, "LINHA BOA")]]
    assert respostas.painel == [(novas[0], "LINHA BOA")]
    assert [e["nome_erp"] for e in respostas.cadastro] == [novas[0].nome]


def test_sem_nada_no_painel_nao_confere(raiz, monkeypatch):
    novas = [_pend(1, painel=True, sugerida="EMPRESA MODELO")]
    chamadas = []

    def roteiro(top, _tabela):
        _botao(top, "Incluir").invoke()

    respostas, _w = _perguntar(raiz, monkeypatch, novas, roteiro,
                               conferir_painel=lambda p: chamadas.append(p)
                               or ["nunca"])
    assert chamadas == []
    assert len(respostas.cadastro) == 1


def test_so_painel_trava_empresa_e_pasta_e_grava_a_linha(raiz, monkeypatch):
    novas = [_pend(1, cadastro=False, painel=True)]
    visto = {}

    def roteiro(top, tabela):
        visto["falta"] = tabela.set("0", "falta")
        visto["empresa"] = str(_um(top, "TCombobox").cget("state"))
        entradas = _entradas(top)
        visto["pasta"] = str(entradas[0].cget("state"))
        entradas[1].delete(0, "end")
        entradas[1].insert(0, "LINHA NOVA")
        tabela.event_generate("<<AlternarPainel>>")
        next(w for w in _todos(top) if w.winfo_class() == "TButton"
             and str(w.cget("text")) == "Incluir").invoke()

    respostas, _w = _perguntar(raiz, monkeypatch, novas, roteiro)
    assert visto["falta"] == "painel"
    assert visto["empresa"] == "disabled" and visto["pasta"] == "disabled"
    assert respostas.cadastro == []
    assert respostas.painel == [(novas[0], "LINHA NOVA")]
