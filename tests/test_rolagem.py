# -*- coding: utf-8 -*-
"""A aba que rola: `widgets.AreaRolavel`, a doca e os controles do Registro.

O defeito de 11/09/2026, na máquina do dono (1920x1080, escala do Windows a
125%, janela maximizada): no Anexar, com as contas carregadas, os três
cartões numerados ocupavam a janela inteira — a barra de ação saía cortada no
pé e o Registro não aparecia. Aqui o conserto é medido numa aba de mentira de
tamanho travado (o motivo do tamanho travado está em
`tests/test_registro_visivel.py`); as onze abas de verdade são medidas lá.
"""
import time
import tkinter as tk
from tkinter import ttk

import pytest

import widgets

LARGURA, ALTURA = 800, 520


def _assentar(tela):
    """Geometria em dia. Três voltas porque a área mede em duas etapas: o
    Canvas ganha tamanho, e só depois o interior acompanha."""
    for _ in range(3):
        tela.update_idletasks()
        tela.update()


def _esperar(condicao, tela, segundos: float = 2.0) -> bool:
    """Espera `condicao()` virar verdade, servindo o laço do Tk. É para o que
    só a conferência periódica da área pega (`AreaRolavel.VIGIA_MS`)."""
    fim = time.monotonic() + segundos
    while time.monotonic() < fim:
        _assentar(tela)
        if condicao():
            return True
        time.sleep(0.03)
    return condicao()


@pytest.fixture
def tela(raiz):
    widgets.aplicar_estilos(False)
    quadro = tk.Frame(raiz, width=LARGURA, height=ALTURA)
    quadro.pack_propagate(False)
    quadro.place(x=0, y=0, width=LARGURA, height=ALTURA)
    yield quadro
    quadro.destroy()
    raiz.update()


def _aba(tela, cartoes: int = 3, campos: int = 6) -> dict:
    """Cabeçalho, cartões com campos, barra de ação e Registro — o esqueleto
    das onze abas, montado na mesma ordem em que elas montam."""
    cab = widgets.Cabecalho(tela, "Aba de teste", "Linha de apoio.")
    cab.pack(fill="x", padx=20, pady=(16, 12))
    corpo = widgets.AreaRolavel(tela)
    lista, entradas = [], []
    for n in range(cartoes):
        cartao = widgets.Cartao(corpo, f"Passo {n + 1}", n + 1)
        cartao.pack(fill="x", padx=20, pady=(0, 12))
        lista.append(cartao)
        for _ in range(campos):
            e = ttk.Entry(cartao)
            e.pack(fill="x", pady=2)
            entradas.append(e)
    acao = ttk.Frame(tela, style="Fundo.TFrame")
    acao.pack(fill="x", padx=20, pady=(0, 10))
    ttk.Label(acao, text="Pronto.", style="FundoApoio.TLabel").pack(anchor="w")
    reg = widgets.Cartao(tela, "Registro", padding=(12, 10))
    reg.pack(fill="x", padx=20, pady=(0, 12))
    texto = tk.Text(reg, wrap="word", relief="flat", borderwidth=0,
                    highlightthickness=0)
    texto.pack(fill="both", expand=True)
    widgets.estilo_log(texto, False)
    widgets.registro_elastico(reg, texto)
    corpo.encaixar(acao, reg)
    _assentar(tela)
    return {"cab": cab, "corpo": corpo, "acao": acao, "reg": reg,
            "texto": texto, "cartoes": lista, "entradas": entradas}


def _pe(w) -> int:
    return w.winfo_rooty() + w.winfo_height()


def _a_vista(area, w) -> bool:
    return (w.winfo_rooty() >= area.canvas.winfo_rooty()
            and _pe(w) <= _pe(area.canvas))


# ------------------------------------------------------------------- a doca
def test_o_que_nao_cabe_rola_e_a_doca_fica_inteira(tela):
    a = _aba(tela, cartoes=4, campos=8)
    corpo = a["corpo"]
    assert corpo.rola(), "o conteúdo passa da tela e a área não rola"
    assert corpo.barra.winfo_ismapped(), "há o que rolar e a barra não apareceu"
    for nome in ("acao", "reg"):
        w = getattr(a[nome], "moldura", a[nome])
        assert w.winfo_height() >= w.winfo_reqheight(), f"{nome} saiu cortado"
        assert _pe(w) <= _pe(tela), f"{nome} passou do pé da janela"
    # De cima para baixo: cabeçalho, área, barra de ação, Registro.
    assert (a["cab"].winfo_rooty() < corpo.moldura.winfo_rooty()
            < a["acao"].winfo_rooty() < a["reg"].moldura.winfo_rooty())


def test_com_trabalho_dentro_o_registro_guarda_o_piso(tela):
    a = _aba(tela, cartoes=4, campos=8)
    texto = a["texto"]
    texto.insert("end", "14:02 — conta 1 ok\n" * 12)
    _assentar(tela)
    linha = widgets._altura_da_linha(texto)
    assert texto.winfo_height() >= 6 * linha, (
        f"o Registro tem {texto.winfo_height()} px, menos que seis linhas "
        f"de {linha} px")
    assert _pe(a["reg"].moldura) <= _pe(tela)


def test_o_que_cabe_nao_ganha_barra(tela):
    a = _aba(tela, cartoes=1, campos=1)
    assert not a["corpo"].rola()
    assert not a["corpo"].barra.winfo_ismapped()


def test_a_area_percebe_quando_um_cartao_cresce(tela):
    """"Carregar contas" enche o cartão 3 depois que a aba já está na tela."""
    a = _aba(tela, cartoes=1, campos=1)
    assert not a["corpo"].rola()
    for _ in range(30):
        ttk.Entry(a["cartoes"][0]).pack(fill="x", pady=2)
    assert _esperar(a["corpo"].rola, tela), "o cartão cresceu e a área não rola"


def test_a_area_percebe_um_cartao_novo(tela):
    """O "Lista pronta" do Anexar entra e sai da tela conforme o modo."""
    a = _aba(tela, cartoes=1, campos=1)
    novo = widgets.Cartao(a["corpo"], "Lista pronta")
    for _ in range(30):
        ttk.Entry(novo).pack(fill="x", pady=2)
    novo.pack(fill="x", padx=20, pady=(0, 12))
    assert _esperar(a["corpo"].rola, tela), "um cartão novo entrou e a área não rola"


# ----------------------------------------------------------------- a roda
def _rodar(teclar, widget, delta: int = -120):
    """Um dente da roda sobre `widget`, com o ponteiro no meio dele.

    Por `teclar` porque o evento da roda é do mesmo tipo que a tecla e, gerado,
    pode precisar do foco para ser entregue (ver o bloco "teclas e foco" do
    conftest). Com `rootx`/`rooty` porque a área decide pelo widget sob o
    PONTEIRO, como faz com a roda de verdade."""
    widget.update_idletasks()
    meio_x, meio_y = widget.winfo_width() // 2, widget.winfo_height() // 2
    teclar(widget, "<MouseWheel>", delta=delta, x=meio_x, y=meio_y,
           rootx=widget.winfo_rootx() + meio_x,
           rooty=widget.winfo_rooty() + meio_y)


def _focado(focar, tela, area, widget) -> float:
    """Dá o foco a `widget` ANTES da roda e devolve onde a página ficou.

    O `teclar` da roda dá o foco a quem recebe o evento, e foco pelo teclado
    traz o widget à vista (`_foco_na_area`): medido depois da roda, esse
    salto passaria por rolagem da roda. Foi o que fez a primeira versão do
    teste da tabela acusar a página de rolar junto."""
    focar(widget)
    _assentar(tela)
    return area.canvas.canvasy(0)


def test_a_roda_rola_a_area(tela, teclar, focar):
    a = _aba(tela, cartoes=4, campos=8)
    alvo = a["entradas"][0]
    antes = _focado(focar, tela, a["corpo"], alvo)
    _rodar(teclar, alvo)
    _assentar(tela)
    assert a["corpo"].canvas.canvasy(0) > antes


def test_a_roda_sobre_o_combobox_nao_troca_o_valor(tela, teclar, focar):
    """Com a página rolando, passar o ponteiro por "Tipo" ou "Forma" trocava o
    valor em silêncio (`ttk::bindMouseWheel TCombobox`)."""
    a = _aba(tela, cartoes=4, campos=8)
    cb = ttk.Combobox(a["cartoes"][0], state="readonly",
                      values=("Pagamento", "Recebimento", "Transferência"))
    cb.current(0)
    cb.pack(fill="x", before=a["entradas"][0])
    _assentar(tela)
    antes = _focado(focar, tela, a["corpo"], cb)
    _rodar(teclar, cb)
    _assentar(tela)
    assert cb.get() == "Pagamento", "a roda trocou o valor do combobox"
    assert a["corpo"].canvas.canvasy(0) > antes, "a roda não rolou a página"


def test_a_lista_que_rola_sozinha_fica_com_a_roda(tela, teclar, focar):
    """Uma tabela com o que rolar rola ELA, e a página fica parada — senão as
    duas andariam juntas a cada dente da roda."""
    a = _aba(tela, cartoes=4, campos=8)
    tabela = ttk.Treeview(a["cartoes"][0], columns=("a",), show="headings",
                          height=4)
    for n in range(40):
        tabela.insert("", "end", values=(f"linha {n}",))
    tabela.pack(fill="x", before=a["entradas"][0])
    _assentar(tela)
    antes = _focado(focar, tela, a["corpo"], tabela)
    _rodar(teclar, tabela)
    _assentar(tela)
    assert tabela.yview()[0] > 0.0, "a tabela não rolou"
    assert a["corpo"].canvas.canvasy(0) == antes, "a página rolou junto"


# ------------------------------------------------------------------ o foco
def test_o_foco_traz_o_campo_para_a_vista(tela, focar):
    a = _aba(tela, cartoes=4, campos=8)
    ultimo = a["entradas"][-1]
    assert not _a_vista(a["corpo"], ultimo), "a aba de teste cabe inteira"
    focar(ultimo)
    _assentar(tela)
    assert _a_vista(a["corpo"], ultimo), "o campo recebeu o foco e ficou escondido"


def test_foco_que_vem_de_clique_nao_rola_a_pagina(tela):
    """O que se clica já está sob o ponteiro: a página saltar debaixo do mouse
    no meio do clique (numa tabela, por exemplo) é pior do que meia caixa à
    vista. Só o foco pelo teclado traz o campo à vista."""
    a = _aba(tela, cartoes=4, campos=8)
    ultimo = a["entradas"][-1]
    antes = a["corpo"].canvas.canvasy(0)
    widgets._clique_global(None)
    ultimo.focus_force()
    _assentar(tela)
    assert a["corpo"].canvas.canvasy(0) == antes


def test_janela_aberta_de_dentro_da_area_nao_mexe_na_aba(tela):
    """No tkinter o `master` de uma janela é quem a criou: o calendário do
    `CampoData` tem um cartão da área como pai lógico. A roda e o foco dentro
    dessa janela não podem rolar a aba que ficou atrás dela."""
    a = _aba(tela, cartoes=4, campos=8)
    corpo = a["corpo"]
    top = tk.Toplevel(a["cartoes"][0])
    top.withdraw()
    try:
        rotulo = ttk.Label(top, text="calendário")
        rotulo.pack()
        assert widgets._area_de(rotulo) is None
        antes = corpo.canvas.canvasy(0)
        evento = type("Ev", (), {"widget": rotulo, "delta": -120,
                                 "x_root": -1, "y_root": -1})()
        widgets._roda_na_area(evento)
        widgets._foco_anterior["clique"] = 0.0
        widgets._foco_na_area(type("Ev", (), {"widget": rotulo})())
        _assentar(tela)
        assert corpo.canvas.canvasy(0) == antes
    finally:
        top.destroy()


# -------------------------------------------------------- os controles do Registro
def test_ampliar_e_recolher_o_registro(tela):
    a = _aba(tela, cartoes=1, campos=1)
    reg, texto = a["reg"], a["texto"]
    assert reg.b_ampliar.cget("text") == "Ampliar"
    reg.b_ampliar.invoke()
    _assentar(tela)
    assert int(texto.cget("height")) > 6
    assert reg.b_ampliar.cget("text") == "Recolher"
    reg.b_ampliar.invoke()
    _assentar(tela)
    assert int(texto.cget("height")) == 6
    assert reg.b_ampliar.cget("text") == "Ampliar"


def test_puxar_a_alca_para_cima_aumenta_o_registro(tela):
    a = _aba(tela, cartoes=1, campos=1)
    texto, alca = a["texto"], a["reg"].alca
    linha = widgets._altura_da_linha(texto)
    antes = int(texto.cget("height"))
    alca.event_generate("<ButtonPress-1>", x=5, y=2, rootx=5, rooty=400)
    alca.event_generate("<B1-Motion>", x=5, y=2, rootx=5,
                        rooty=400 - 5 * linha)
    alca.event_generate("<ButtonRelease-1>", x=5, y=2, rootx=5,
                        rooty=400 - 5 * linha)
    _assentar(tela)
    assert int(texto.cget("height")) >= antes + 4


def test_copiar_leva_o_registro_inteiro(tela, monkeypatch):
    """Sem tocar a área de transferência de verdade: a suíte roda na máquina
    de quem está colando linha digitável no site do banco."""
    a = _aba(tela, cartoes=1, campos=1)
    reg, texto = a["reg"], a["texto"]
    pego = []
    monkeypatch.setattr(texto, "clipboard_clear", lambda: pego.clear())
    monkeypatch.setattr(texto, "clipboard_append", lambda s: pego.append(s))
    reg.b_copiar.invoke()
    assert pego == [] and reg.b_copiar.cget("text") == "Nada a copiar"
    conteudo = "14:02 — conta 1 ok\n14:03 ✖ ERRO: sem PDF\n"
    texto.insert("end", conteudo)
    _assentar(tela)
    reg.b_copiar.invoke()
    assert pego == [conteudo.rstrip("\n") + "\n"] or pego == [conteudo]
    assert reg.b_copiar.cget("text").startswith("Copiado")


# -------------------------------------------------------------- tema e menu
def test_a_area_segue_o_tema(tela):
    a = _aba(tela, cartoes=1, campos=1)
    try:
        widgets.aplicar_estilos(True)
        widgets._repintar_todos()
        assert str(a["corpo"].canvas.cget("background")).upper() == \
            widgets.PALETA["escuro"]["fundo"].upper()
    finally:
        widgets.aplicar_estilos(False)
        widgets._repintar_todos()
    assert str(a["corpo"].canvas.cget("background")).upper() == \
        widgets.PALETA["claro"]["fundo"].upper()


def test_o_menu_rola_quando_os_itens_nao_cabem(raiz):
    widgets.aplicar_estilos(False)
    quadro = tk.Frame(raiz, width=300, height=320)
    quadro.pack_propagate(False)
    quadro.place(x=0, y=0, width=300, height=320)
    try:
        menu = widgets.painel_menu(quadro)
        menu.pack(side="left", fill="y")
        for n in range(24):
            widgets.ItemMenu(menu.corpo, f"Tela {n}", icone="▦").pack(fill="x")
        assert _esperar(menu.corpo.rola, quadro), (
            "vinte e quatro itens em 320 px e o menu não rola")
    finally:
        quadro.destroy()
        raiz.update()
