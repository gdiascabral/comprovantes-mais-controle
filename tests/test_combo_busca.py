# -*- coding: utf-8 -*-
"""O combo que também é campo de busca (aba Aportes).

Substituiu um campo "Buscar" separado, que filtrava os DOIS combos de uma vez:
para escolher a conta do "Recebeu" era preciso sair para outro campo, digitar,
voltar e abrir a lista — e o filtro mexia no "Pagou" junto.

Abrem uma janela Tk de verdade (escondida). Sem display, pulam.
"""
import tkinter as tk

import pytest

import widgets

CONTAS = [
    "MORAIS ENGENHARIA - INTER",
    "PARTICIPAÇÕES SUBCONTA 55696-3 - SICOOB",
    "PARTICIPAÇÕES SUBCONTA 55697-1 - SICOOB",
    "SENADOR CANEDO - SICOOB (55711-0)",
    "LIVIAN (pessoa física)",
]


@pytest.fixture
def combo(raiz):
    c = widgets.ComboBusca(raiz, width=30)
    c.pack()
    c.definir_valores(CONTAS)
    raiz.update()
    yield c, raiz
    try:
        c.destroy()
    except tk.TclError:
        pass
    raiz.update()


def _digitar(combo, root, texto):
    combo.focus_force()
    combo.delete(0, "end")
    combo.insert(0, texto)
    combo.event_generate("<KeyRelease>", keysym=texto[-1] if texto else "a")
    root.update()


def test_digitar_filtra_a_lista_do_proprio_campo(combo):
    c, root = combo
    _digitar(c, root, "696")
    assert list(c["values"]) == ["PARTICIPAÇÕES SUBCONTA 55696-3 - SICOOB"]


def test_acha_no_meio_do_nome_e_sem_acento(combo):
    """"livia" tem de achar "LIVIAN", como o campo antigo já fazia."""
    c, root = combo
    _digitar(c, root, "livia")
    assert list(c["values"]) == ["LIVIAN (pessoa física)"]
    _digitar(c, root, "PARTICIPACOES")
    assert len(c["values"]) == 2


def test_apagar_o_que_digitou_traz_a_lista_de_volta(combo):
    """O filtro parte SEMPRE da lista completa. Filtrando sobre o resultado
    anterior, a lista só encolheria e apagar não a traria de volta."""
    c, root = combo
    _digitar(c, root, "696")
    assert len(c["values"]) == 1
    _digitar(c, root, "")
    assert list(c["values"]) == CONTAS


def test_navegar_na_lista_nao_refiltra(combo):
    """Seta e Enter não são digitação: filtrar ali embaralharia a lista
    justamente enquanto a pessoa anda por ela."""
    c, root = combo
    _digitar(c, root, "696")
    c.event_generate("<KeyRelease>", keysym="Down")
    root.update()
    assert len(c["values"]) == 1


def test_escolher_devolve_a_lista_inteira(combo):
    """Senão a próxima abertura ainda mostraria só o resto do filtro anterior."""
    c, root = combo
    _digitar(c, root, "696")
    c.set("PARTICIPAÇÕES SUBCONTA 55696-3 - SICOOB")
    c.event_generate("<<ComboboxSelected>>")
    root.update()
    assert list(c["values"]) == CONTAS


def test_sair_do_campo_corrige_so_a_grafia(combo):
    """Casou exatamente fora acento e caixa: vira o nome do cadastro."""
    c, root = combo
    _digitar(c, root, "livian (pessoa fisica)")
    c.event_generate("<FocusOut>")
    root.update()
    assert c.get() == "LIVIAN (pessoa física)"


def test_texto_que_nao_e_opcao_nao_vira_conta_parecida(combo):
    """A trava que importa: quem lança dinheiro tem de receber erro, e não uma
    conta escolhida em silêncio por parecer com o que se digitou."""
    c, root = combo
    _digitar(c, root, "MORAIS")           # casa com uma, mas não é o nome dela
    c.event_generate("<FocusOut>")
    root.update()
    assert c.get() == "MORAIS"
    assert c.get() not in CONTAS


def test_a_lista_completa_fica_acessivel(combo):
    c, _root = combo
    assert c.valores_completos() == CONTAS
