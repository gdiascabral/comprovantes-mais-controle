# -*- coding: utf-8 -*-
"""O `ComboBusca` nunca mostra a lista NATIVA do ttk (22/10/2026).

O dono mandou print da aba Aportes: ao escolher o banco em "Recebeu", às vezes
abria a lista nova (o `Toplevel` nosso) e às vezes a antiga, a listbox do
`ttk.Combobox`. A causa estava na diferença entre as duas perguntas:

- o nosso `_clique` só tomava o clique quando ele caía na SETA (`identify`
  com "arrow", ou os últimos 26 px);
- o `ttk::combobox::Press` da classe posta a nativa em TODO clique que não cai
  no `textarea` — a borda, o enchimento de cima e de baixo, o canto esquerdo
  do campo; e, com o campo `readonly`, em qualquer lugar.

Entre as duas sobrava uma faixa (a moldura do campo) em que nenhum dos dois
dizia "é meu" para o nosso lado e a classe postava a dela.

Aqui, só o que roda SEM janela: a decisão do clique é função pura, e a trava
do `-postcommand` é um script Tcl, provado num interpretador Tcl sem Tk. Os
testes que constroem o combo de verdade estão em `test_combo_busca.py`
(fixture `raiz`).
"""
import tkinter

import widgets


# ------------------------------------------------------- decisão do clique
def _destino(elemento, *, x=10, largura=300, desabilitado=False,
             so_leitura=False):
    return widgets.destino_do_clique(
        elemento, x=x, largura=largura, faixa_seta=26,
        desabilitado=desabilitado, so_leitura=so_leitura)


def test_clique_no_texto_fica_com_o_campo():
    """Clicar no texto posiciona o cursor: não abre lista nenhuma."""
    assert _destino("Combobox.textarea") == "texto"
    assert _destino("textarea") == "texto"


def test_clique_na_seta_abre_a_nossa_lista():
    assert _destino("Combobox.downarrow", x=290) == "lista"


def test_clique_na_moldura_do_campo_abre_a_nossa_e_nao_a_nativa():
    """Era o furo: a classe posta a nativa em tudo o que não é `textarea`."""
    for elemento in ("Combobox.field", "Combobox.padding", "Combobox.border",
                     "Combobox.focus", "", "algum.elemento.do.tema"):
        assert _destino(elemento, x=3) == "lista", elemento


def test_os_ultimos_pixels_continuam_sendo_a_seta_mesmo_no_texto():
    """Em escala alta o `identify` pode devolver o texto encostado na seta."""
    assert _destino("Combobox.textarea", x=280) == "lista"
    assert _destino("Combobox.textarea", x=273) == "texto"


def test_readonly_qualquer_clique_abre_a_nossa():
    """Campo só de leitura: a classe postaria a nativa em QUALQUER clique."""
    assert _destino("Combobox.textarea", so_leitura=True) == "lista"
    assert _destino("Combobox.field", so_leitura=True) == "lista"


def test_desabilitado_nao_abre_nada():
    assert _destino("Combobox.textarea", desabilitado=True) == "nada"
    assert _destino("Combobox.downarrow", x=290, desabilitado=True) == "nada"


# ------------------------------------------------- trava do -postcommand
def test_o_script_do_postcommand_faz_o_post_nativo_desistir():
    """`ttk::combobox::Post` roda `uplevel #0 [$cb cget -postcommand]` ANTES
    de criar a listbox. Um `return` no fim do script faz o `uplevel` devolver
    TCL_RETURN, e o `Post` sai ali — a lista nativa nem chega a existir. Quem
    chamou o `Post` (o `Press` da classe) segue normalmente, sem erro.

    Reencenado com um `Post` de mentira, no MESMO formato do Tk 8.6, num Tcl
    sem Tk (sem janela)."""
    tcl = tkinter.Tcl()
    tcl.eval("set chamou 0")
    tcl.eval("proc avisar {} { incr ::chamou }")
    tcl.eval("proc Post {script} { uplevel #0 $script; return postou }")
    tcl.eval("proc Press {script} { Post $script; return seguiu }")

    script = widgets._script_sem_lista_nativa("avisar")
    assert tcl.eval(f"Post {{{script}}}") == ""        # não postou
    assert tcl.eval("set chamou") == "1"                 # o nosso rodou
    assert tcl.eval(f"Press {{{script}}}") == "seguiu"   # quem chamou segue
    # Sem a trava, o mesmo Post posta: o teste mede o que diz medir.
    assert tcl.eval("Post {avisar}") == "postou"
