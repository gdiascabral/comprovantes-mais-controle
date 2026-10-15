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


def _digitar(teclar, combo, _root, texto):
    # `teclar`, e não `event_generate` cru: tecla gerada só chega a quem tem o
    # foco, e o foco do sistema vai e vem com o Windows. E nenhum `update`
    # depois da tecla: o filtro roda dentro de `teclar`, e o `update` é onde o
    # FocusOut do Windows entra e o `<FocusOut>` do combo (`_ao_sair`) devolve
    # a lista inteira antes de o teste olhar. Ver o conftest.
    combo.delete(0, "end")
    combo.insert(0, texto)
    teclar(combo, "<KeyRelease>", keysym=texto[-1] if texto else "a")


def test_digitar_filtra_a_lista_do_proprio_campo(combo, teclar):
    c, root = combo
    _digitar(teclar, c, root, "696")
    assert list(c["values"]) == ["PARTICIPAÇÕES SUBCONTA 55696-3 - SICOOB"]


def test_acha_no_meio_do_nome_e_sem_acento(combo, teclar):
    """"livia" tem de achar "LIVIAN", como o campo antigo já fazia."""
    c, root = combo
    _digitar(teclar, c, root, "livia")
    assert list(c["values"]) == ["LIVIAN (pessoa física)"]
    _digitar(teclar, c, root, "PARTICIPACOES")
    assert len(c["values"]) == 2


def test_apagar_o_que_digitou_traz_a_lista_de_volta(combo, teclar):
    """O filtro parte SEMPRE da lista completa. Filtrando sobre o resultado
    anterior, a lista só encolheria e apagar não a traria de volta."""
    c, root = combo
    _digitar(teclar, c, root, "696")
    assert len(c["values"]) == 1
    _digitar(teclar, c, root, "")
    assert list(c["values"]) == CONTAS


def test_navegar_na_lista_nao_refiltra(combo, teclar):
    """Seta e Enter não são digitação: filtrar ali embaralharia a lista
    justamente enquanto a pessoa anda por ela."""
    c, root = combo
    _digitar(teclar, c, root, "696")
    teclar(c, "<KeyRelease>", keysym="Down")
    assert len(c["values"]) == 1


def test_escolher_devolve_a_lista_inteira(combo, teclar):
    """Senão a próxima abertura ainda mostraria só o resto do filtro anterior."""
    c, root = combo
    _digitar(teclar, c, root, "696")
    c.set("PARTICIPAÇÕES SUBCONTA 55696-3 - SICOOB")
    c.event_generate("<<ComboboxSelected>>")
    root.update()
    assert list(c["values"]) == CONTAS


def test_sair_do_campo_corrige_so_a_grafia(combo, teclar):
    """Casou exatamente fora acento e caixa: vira o nome do cadastro."""
    c, root = combo
    _digitar(teclar, c, root, "livian (pessoa fisica)")
    c.event_generate("<FocusOut>")
    root.update()
    assert c.get() == "LIVIAN (pessoa física)"


def test_texto_que_nao_e_opcao_nao_vira_conta_parecida(combo, teclar):
    """A trava que importa: quem lança dinheiro tem de receber erro, e não uma
    conta escolhida em silêncio por parecer com o que se digitou."""
    c, root = combo
    _digitar(teclar, c, root, "MORAIS")           # casa com uma, mas não é o nome dela
    c.event_generate("<FocusOut>")
    root.update()
    assert c.get() == "MORAIS"
    assert c.get() not in CONTAS


def test_a_lista_completa_fica_acessivel(combo):
    c, _root = combo
    assert c.valores_completos() == CONTAS


# ---------------------------------------------------------------------------
# A lista que abre sozinha enquanto se digita (14/10/2026). É um `Toplevel`
# nosso, sem foco: o foco nunca sai do campo, e as teclas da lista (↑/↓,
# Enter, Esc) são ligadas ao próprio campo.

def _textos_visiveis(c):
    return [lin.cget("text") for lin in c._linhas if lin.winfo_manager()]


def test_digitar_abre_a_lista_com_o_que_contem_as_letras(combo, teclar):
    c, root = combo
    _digitar(teclar, c, root, "sicoob")
    assert c.lista_aberta()
    assert _textos_visiveis(c) == [
        "PARTICIPAÇÕES SUBCONTA 55696-3 - SICOOB",
        "PARTICIPAÇÕES SUBCONTA 55697-1 - SICOOB",
        "SENADOR CANEDO - SICOOB (55711-0)",
    ]


def test_a_lista_acha_pedaco_no_meio_do_nome(combo, teclar):
    """O caso da tela do dono: "jo" no Recebeu tem de mostrar quem CONTÉM
    "jo", e não só quem começa com "jo"."""
    c, root = combo
    _digitar(teclar, c, root, "anedo")
    assert _textos_visiveis(c) == ["SENADOR CANEDO - SICOOB (55711-0)"]


def test_o_foco_fica_no_campo_com_a_lista_aberta(combo, teclar):
    c, root = combo
    _digitar(teclar, c, root, "part")
    assert c.lista_aberta()
    assert str(c.focus_lastfor()) == str(c)


def test_seta_e_enter_escolhem_a_linha_realcada(combo, teclar):
    c, root = combo
    escolhidos = []
    c.bind("<<ComboboxSelected>>", lambda _e: escolhidos.append(c.get()), add="+")
    _digitar(teclar, c, root, "subconta")
    teclar(c, "<Down>")                      # da 1ª para a 2ª
    teclar(c, "<Return>")
    assert c.get() == "PARTICIPAÇÕES SUBCONTA 55697-1 - SICOOB"
    assert not c.lista_aberta()
    assert escolhidos == [c.get()]
    assert list(c["values"]) == CONTAS       # a lista nativa volta inteira


def test_enter_com_a_lista_aberta_nao_aciona_a_aba(combo):
    """Com a lista aberta, Enter é escolha: devolve "break" para o `bind_all`
    do app não começar o passo principal da aba no meio dela. Fechada, o Enter
    segue o caminho de sempre."""
    c, _root = combo
    assert c._confirmar() is None
    c.insert(0, "inter")
    c.abrir_lista()
    assert c._confirmar() == "break"
    assert c.get() == "MORAIS ENGENHARIA - INTER"


def test_clique_na_linha_escolhe(combo, teclar):
    c, root = combo
    _digitar(teclar, c, root, "livian")
    c._clicou_linha(0)
    assert c.get() == "LIVIAN (pessoa física)"
    assert not c.lista_aberta()


def test_esc_fecha_e_deixa_o_texto(combo, teclar):
    c, root = combo
    _digitar(teclar, c, root, "mor")
    teclar(c, "<Escape>")
    assert not c.lista_aberta()
    assert c.get() == "mor"


def test_apagar_tudo_fecha_a_lista(combo, teclar):
    c, root = combo
    _digitar(teclar, c, root, "mor")
    assert c.lista_aberta()
    _digitar(teclar, c, root, "")
    assert not c.lista_aberta()


def test_sem_nada_parecido_a_lista_diz_que_nao_achou(combo, teclar):
    c, root = combo
    _digitar(teclar, c, root, "xyzw")
    assert c.lista_aberta()
    assert _textos_visiveis(c) == []
    assert "xyzw" in c._rodape.cget("text")


def test_seta_para_baixo_com_opcao_escolhida_abre_tudo_com_ela_realcada(combo, teclar):
    """Quem abre a lista com algo escolhido quer trocar: filtrar pelo nome
    inteiro deixaria uma linha só."""
    c, root = combo
    c.set("SENADOR CANEDO - SICOOB (55711-0)")
    teclar(c, "<Down>")
    assert c.lista_aberta()
    assert c._achados == CONTAS
    assert c._achados[c._realce] == "SENADOR CANEDO - SICOOB (55711-0)"


def test_lista_longa_mostra_uma_janela_e_rola(raiz, teclar):
    contas = [f"CONTA {i:02d} - SICOOB" for i in range(30)]
    c = widgets.ComboBusca(raiz, width=30)
    c.pack()
    c.definir_valores(contas)
    raiz.update()
    try:
        _digitar(teclar, c, raiz, "conta")
        assert len(_textos_visiveis(c)) == c.VISIVEIS
        assert "30" in c._rodape.cget("text")
        for _ in range(c.VISIVEIS):          # passa da última linha visível
            teclar(c, "<Down>")
        assert c._realce == c.VISIVEIS
        assert _textos_visiveis(c)[-1] == contas[c.VISIVEIS]
        teclar(c, "<Return>")
        assert c.get() == contas[c.VISIVEIS]
    finally:
        c.destroy()
        raiz.update()


def test_fechar_a_lista_nao_desliga_o_clique_de_outros(combo, teclar):
    """O `unbind` do tkinter apaga TODOS os scripts da sequência; fechar a
    lista não pode levar junto o clique-fora de outro widget da janela."""
    c, root = combo
    janela = c.winfo_toplevel()
    cliques = []
    fid = janela.bind("<Button-1>", lambda _e: cliques.append(1), add="+")
    try:
        _digitar(teclar, c, root, "mor")
        c.fechar_lista()
        assert fid in janela.tk.call("bind", str(janela), "<Button-1>")
    finally:
        widgets._desligar(janela, "<Button-1>", fid)


def test_destruir_o_campo_leva_a_lista(raiz, teclar):
    c = widgets.ComboBusca(raiz, width=30)
    c.pack()
    c.definir_valores(CONTAS)
    raiz.update()
    _digitar(teclar, c, raiz, "mor")
    popup = c._popup
    c.destroy()
    raiz.update()
    assert not popup.winfo_exists()


def test_enter_de_quem_usa_o_combo_nao_apaga_o_da_lista(combo, teclar):
    """O "Novo cadastro" e as Guias ligam o próprio `<Return>` no combo, sem
    `add`. Com a lista aberta o Enter escolhe e para ali; fechada, chega a
    quem usa."""
    c, root = combo
    chamadas = []
    c.bind("<Return>", lambda _e: chamadas.append(c.get()))
    _digitar(teclar, c, root, "inter")
    teclar(c, "<Return>")
    assert c.get() == "MORAIS ENGENHARIA - INTER"
    assert chamadas == []
    teclar(c, "<Return>")
    assert chamadas == ["MORAIS ENGENHARIA - INTER"]
