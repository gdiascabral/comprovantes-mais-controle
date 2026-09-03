# -*- coding: utf-8 -*-
"""A tecla que o teste gera chega ao widget, mesmo com o foco noutra janela.

O Tk entrega tecla gerada a quem tem o foco, e "quem tem o foco" fica vazio
sempre que o Windows o leva para outra janela — outra suíte rodando ao lado,
um clique de quem usa a máquina. Aí o `event_generate` de tecla é descartado
em silêncio, e o teste que dependia dele falha sem nada ter mudado no código
(02/09/2026, com três `pytest` ao mesmo tempo). O conserto é `teclar`, no
conftest, que confere (ou toma) o foco no instante de gerar; o porquê de
cada escolha está no bloco "teclas e foco" de lá.

Aqui o roubo é REENCENADO, sem outra janela nem outro processo:
`SetFocus(NULL)` tira o foco de teclado da thread, e o Windows manda
`WM_KILLFOCUS` à janela que o tinha — o mesmo caminho de quando outra janela
vai para o primeiro plano —, que o Tk traduz em FocusOut e, no `update`,
esquece quem tinha o foco. As duas metades importam: a primeira prova que a
reencenação reproduz o defeito nesta máquina (a tecla crua some), a segunda
é a garantia (a de `teclar` chega). Sem a primeira, a segunda poderia estar
passando à toa.

Só no Windows: a reencenação é uma chamada do Windows, e é lá que a suíte
roda (aqui e no CI)."""
import ctypes
import sys
import tkinter as tk

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform != "win32",
    reason="o roubo do foco é reencenado com SetFocus(NULL), do Windows")


def _foco(raiz) -> str:
    return str(raiz.tk.call("focus"))


@pytest.fixture
def campo(raiz):
    ent = tk.Entry(raiz)
    ent.pack()
    raiz.update()
    chegou = []
    ent.bind("<Return>", lambda _e: chegou.append("Return"))
    yield ent, chegou
    ent.destroy()
    raiz.update()


def _o_windows_leva_o_foco(raiz):
    ctypes.WinDLL("user32", use_last_error=True).SetFocus(None)
    raiz.update()


def test_sem_o_foco_do_sistema_a_tecla_gerada_some(raiz, campo, teclar):
    """A metade que prova que o defeito existe."""
    ent, chegou = campo
    teclar(ent, "<Return>")
    raiz.update()
    assert chegou == ["Return"], "nem com o foco a tecla chegou"

    _o_windows_leva_o_foco(raiz)
    assert _foco(raiz) == "", (
        "o Windows não levou o foco: a reencenação não vale nesta máquina")
    ent.event_generate("<Return>")        # o jeito cru
    raiz.update()
    assert chegou == ["Return"], (
        "a tecla crua chegou sem foco: o Tk mudou de contrato, e o `teclar` "
        "do conftest deixou de ser necessário — atualize os dois")


def test_focus_set_nao_devolve_o_foco_ao_tk(raiz, campo):
    """O caminho de `focar_busca()`: `focus_set` só ANOTA para quando o app
    recuperar o foco (é o que `focus -lastfor` responde), e a tecla gerada em
    seguida some do mesmo jeito."""
    ent, chegou = campo
    ent.focus_force()
    _o_windows_leva_o_foco(raiz)

    ent.focus_set()
    assert _foco(raiz) == ""
    assert str(raiz.focus_lastfor()) == str(ent)
    ent.event_generate("<Return>")
    raiz.update()
    assert chegou == []


def test_teclar_entrega_depois_do_roubo(raiz, campo, teclar):
    """A garantia."""
    ent, chegou = campo
    ent.focus_force()
    _o_windows_leva_o_foco(raiz)
    assert _foco(raiz) == ""

    teclar(ent, "<Return>")
    raiz.update()
    assert chegou == ["Return"]


def test_teclar_entrega_sem_update_entre_o_roubo_e_a_tecla(raiz, campo,
                                                             teclar):
    """O roubo acontece e o teste NÃO dá `update` antes da tecla — o caso
    de quem digita várias teclas seguidas. O Tk pode já ter processado o
    FocusOut dentro da própria chamada do Windows (`TkWinChildProc` termina
    com `Tcl_ServiceAll`) ou tê-lo deixado na fila; `teclar` tem de enxergar
    os dois sem que o teste volte ao laço de eventos."""
    ent, chegou = campo
    ent.focus_force()
    ctypes.WinDLL("user32", use_last_error=True).SetFocus(None)   # sem update

    teclar(ent, "<Return>")
    raiz.update()
    assert chegou == ["Return"]


def test_focar_recusa_widget_que_o_tk_nao_focaliza(raiz, focar):
    """Falhar com nome, e não passar à toa: um widget que o Tk não aceita
    como foco (aqui, um que nunca foi empacotado) deixaria a tecla gerada
    sumir e o teste passar sem exercitar nada."""
    solto = tk.Entry(raiz)                # sem `pack`: não mapeado
    try:
        with pytest.raises(AssertionError, match="mapeado"):
            focar(solto)
    finally:
        solto.destroy()
        raiz.update()
