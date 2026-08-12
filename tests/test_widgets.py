# -*- coding: utf-8 -*-
"""O campo de data — o widget que TODAS as abas com data usam.

Em 11/08/2026 ele quebrou em todas de uma vez: não dava para digitar nem para
abrir o calendário. Duas causas, e as duas estão cobertas aqui.

Os testes abrem uma janela Tk de verdade (escondida). Se o ambiente não tiver
display, eles pulam em vez de falhar.
"""
import tkinter as tk

import pytest

import widgets


# A janela `raiz` mora no conftest e é UMA para a sessão inteira — ver lá o
# porquê: dois módulos abrindo e destruindo o próprio Tk fazem o segundo pular
# com "sem display" num ambiente que tem display.


@pytest.fixture
def campo(raiz):
    var = tk.StringVar(master=raiz, value="01/08/2026")
    c = widgets.CampoData(raiz, var)
    c.pack()
    raiz.update()
    yield c, var, raiz
    # Popup vazando de um teste contamina o próximo: o registro de qual
    # calendário está aberto é do MÓDULO, não da instância.
    try:
        c._fechar_popup()
        c.destroy()
    except tk.TclError:
        pass
    raiz.update()


def _digitar(campo, root, texto, no_fim=True):
    # `focus_force` é obrigatório: evento de tecla gerado por `event_generate`
    # só chega ao widget que tem o foco, e sem ele o teste passaria por não
    # exercitar nada.
    campo.ent.focus_force()
    if no_fim:
        campo.ent.icursor("end")
    for ch in texto:
        campo.ent.insert("insert", ch)
        campo.ent.event_generate("<KeyRelease>", keysym=ch)
        root.update()


# ------------------------------------------------------------------ máscara
def test_digitar_do_zero_ganha_as_barras(campo):
    c, var, root = campo
    var.set("")
    _digitar(c, root, "05082026")
    assert var.get() == "05/08/2026"


def test_editar_no_meio_nao_destroi_a_data(campo):
    """O defeito de 11/08/2026: com "01/08/2026" e o cursor no começo,
    digitar "0" virava "00/10/8202" — a máscara remontava o campo inteiro."""
    c, var, root = campo
    c.ent.focus_force()
    c.ent.icursor(0)
    c.ent.insert(0, "0")
    c.ent.event_generate("<KeyRelease>", keysym="0")
    root.update()
    assert var.get() == "001/08/2026", (
        "a máscara mexeu no texto com o cursor no meio: " + var.get())
    assert "8202" not in var.get()


def test_apagar_no_meio_nao_remonta(campo):
    c, var, root = campo
    c.ent.focus_force()
    c.ent.icursor(3)
    c.ent.event_generate("<KeyRelease>", keysym="BackSpace")
    root.update()
    assert var.get() == "01/08/2026"


def test_completar_ano_ao_sair_do_campo(campo):
    c, var, root = campo
    var.set("05/08")
    c._completar_ano()
    assert var.get().startswith("05/08/") and len(var.get()) == 10
    var.set("05/08/26")
    c._completar_ano()
    assert var.get() == "05/08/2026"


# --------------------------------------------------------------- calendário
def _popups(w):
    achados = []
    for c in w.winfo_children():
        if isinstance(c, tk.Toplevel):
            achados.append(c)
        achados += _popups(c)
    return achados


def test_o_botao_abre_o_calendario(campo):
    c, var, root = campo
    c.bt.invoke()
    root.update()
    assert c._popup is not None
    assert len(_popups(root)) == 1


def test_o_calendario_nao_fecha_sozinho_ao_perder_foco(campo):
    """A versão sem borda nunca ganhava foco de verdade, então o `<FocusOut>`
    disparava na hora e o calendário sumia antes de aparecer."""
    c, var, root = campo
    c.bt.invoke()
    root.update()
    c._popup.event_generate("<FocusOut>")
    root.update()
    assert c._popup is not None, "o calendário fechou sozinho ao perder o foco"


def test_o_calendario_nao_prende_o_app(campo):
    """O defeito de 12/08/2026: com `grab_set`, o Tk entregava todo clique e
    toda tecla ao calendário. Só se saía dele escolhendo uma data ou fechando
    a janelinha — nem o X do app respondia.

    `grab_current()` é a prova mecânica: com alguém segurando o grab, ele
    devolve essa janela; sem ninguém, devolve None."""
    c, var, root = campo
    c.bt.invoke()
    root.update()
    assert c._popup is not None, "o calendário nem abriu"
    assert root.grab_current() is None, (
        "o calendário está modal: o resto do app fica surdo e nem dá para "
        "fechar o programa")


def test_so_um_calendario_por_vez(campo, raiz):
    """Sem o modal, nada impede clicar no 📅 de outro campo — e dois
    calendários iguais na tela não dizem qual preenche qual."""
    c, var, root = campo
    outro_var = tk.StringVar(master=raiz, value="02/08/2026")
    outro = widgets.CampoData(raiz, outro_var)
    outro.pack()
    root.update()
    try:
        c.bt.invoke()
        root.update()
        outro.bt.invoke()
        root.update()
        assert c._popup is None, "o calendário do primeiro campo ficou aberto"
        assert outro._popup is not None
        assert len(_popups(root)) == 1
    finally:
        outro._fechar_popup()
        outro.destroy()
        root.update()


def test_fechar_o_calendario_libera_o_registro_do_modulo(campo):
    """Registro de módulo que não é limpo trava o próximo: o campo seguinte
    tentaria fechar um popup que já não existe."""
    c, var, root = campo
    c.bt.invoke()
    root.update()
    assert widgets._calendario_aberto is c
    c._fechar_popup()
    root.update()
    assert widgets._calendario_aberto is None


def test_clique_simples_no_campo_nao_abre_calendario(campo):
    """Clique simples é para pôr o cursor e digitar. Abrindo o popup ali, ele
    roubava o clique e o campo ficava impossível de editar."""
    c, var, root = campo
    c.ent.event_generate("<Button-1>")
    root.update()
    assert c._popup is None


def test_escolher_um_dia_preenche_e_fecha(campo):
    from tkinter import ttk
    c, var, root = campo
    c.bt.invoke()
    root.update()

    def achar(w, texto):
        for filho in w.winfo_children():
            if isinstance(filho, ttk.Button) and filho.cget("text") == texto:
                return filho
            achado = achar(filho, texto)
            if achado:
                return achado

    dia = achar(c._popup, "15")
    assert dia is not None, "o calendário não desenhou os dias"
    dia.invoke()
    root.update()
    assert var.get() == "15/08/2026"
    assert c._popup is None


def test_botao_hoje(campo):
    from datetime import date
    from tkinter import ttk
    c, var, root = campo
    c.bt.invoke()
    root.update()

    def achar(w, texto):
        for filho in w.winfo_children():
            if isinstance(filho, ttk.Button) and filho.cget("text") == texto:
                return filho
            achado = achar(filho, texto)
            if achado:
                return achado

    achar(c._popup, "Hoje").invoke()
    root.update()
    assert var.get() == f"{date.today():%d/%m/%Y}"
