# -*- coding: utf-8 -*-
"""Clicar no cabeçalho ordena a tabela — e a zebra continua alternando.

O caso que dá o motivo inteiro: ordenado como TEXTO, "R$ 987,00" vem depois de
"R$ 1.234,56", porque "9" > "1". E é justamente a coluna de dinheiro que se
ordena, para achar o maior pagamento do dia.

Precisa de janela (é `ttk.Treeview` de verdade), então usa a fixture `raiz` do
conftest — UM Tk para a sessão inteira. Ver o porquê lá.
"""
import tkinter as tk
from tkinter import ttk

import pytest

import widgets


@pytest.fixture
def tabela(raiz):
    tv = ttk.Treeview(raiz, columns=("valor", "data", "quem"),
                      show="headings", height=5)
    for col, titulo in (("valor", "Valor"), ("data", "Data"),
                        ("quem", "Favorecido")):
        tv.heading(col, text=titulo)
    widgets.estilo_tabela(tv)
    tv.pack()
    raiz.update()
    yield tv
    tv.destroy()
    raiz.update()


def _preencher(tv, linhas):
    for i, valores in enumerate(linhas):
        tv.insert("", "end", values=valores, tags=widgets.linha_zebrada(i))


def _coluna(tv, col):
    return [str(tv.set(i, col)) for i in tv.get_children("")]


# --------------------------------------------------------------- o inverso do brl
@pytest.mark.parametrize("texto, esperado", [
    ("R$ 1.234,56", 1234.56),
    ("R$ 987,00", 987.0),
    ("1.234,56", 1234.56),               # a tabela do retorno grava sem o R$
    ("0,00", 0.0),
    ("R$ 1.000.000,00", 1000000.0),
    ("(1.234,56)", -1234.56),            # saída de caixa, como em planilha
    ("-99,90", -99.9),
])
def test_valor_de_brl_desfaz_o_brl(texto, esperado):
    assert widgets.valor_de_brl(texto) == pytest.approx(esperado)


@pytest.mark.parametrize("texto", ["", "—", "R$ —", "12/08/2026", "55696-3",
                                   "PAGO", None])
def test_o_que_nao_e_valor_devolve_none(texto):
    assert widgets.valor_de_brl(texto) is None


def test_o_brl_e_o_valor_de_brl_fecham_a_volta():
    for v in (0, 1, 987, 1234.56, 1000000, 0.05):
        assert widgets.valor_de_brl(widgets.brl(v)) == pytest.approx(float(v))


# ------------------------------------------------------------------ dinheiro
def test_dinheiro_ordena_como_numero_e_nao_como_texto(tabela):
    """O caso do enunciado: 987 antes de 1.234,56."""
    _preencher(tabela, [("R$ 1.234,56", "01/01/2026", "A"),
                        ("R$ 987,00", "02/01/2026", "B"),
                        ("R$ 45,00", "03/01/2026", "C")])
    widgets.ordenar_tabela(tabela, "valor")
    assert _coluna(tabela, "valor") == ["R$ 45,00", "R$ 987,00", "R$ 1.234,56"]


def test_o_segundo_clique_inverte(tabela):
    _preencher(tabela, [("R$ 1.234,56", "01/01/2026", "A"),
                        ("R$ 987,00", "02/01/2026", "B")])
    widgets.ordenar_tabela(tabela, "valor")
    widgets.ordenar_tabela(tabela, "valor")
    assert _coluna(tabela, "valor") == ["R$ 1.234,56", "R$ 987,00"]


def test_celula_sem_valor_nao_vira_zero(tabela):
    """"—" não é R$ 0,00. Ela vale menos que qualquer número — abre a lista no
    ▲ e fecha no ▼ —, e nunca se mistura com o zero de verdade."""
    _preencher(tabela, [("R$ 10,00", "01/01/2026", "A"),
                        ("—", "02/01/2026", "B"),
                        ("R$ 0,00", "03/01/2026", "C")])
    widgets.ordenar_tabela(tabela, "valor")
    assert _coluna(tabela, "valor") == ["—", "R$ 0,00", "R$ 10,00"]
    widgets.ordenar_tabela(tabela, "valor")
    assert _coluna(tabela, "valor")[-1] == "—"


# ---------------------------------------------------------------------- data
def test_data_ordena_como_data(tabela):
    """Como texto, 01/12/2025 viria antes de 02/01/2026 — o dia manda, e o ano
    não conta para nada."""
    _preencher(tabela, [("R$ 1,00", "02/01/2026", "A"),
                        ("R$ 2,00", "01/12/2025", "B"),
                        ("R$ 3,00", "31/12/2025", "C")])
    widgets.ordenar_tabela(tabela, "data")
    assert _coluna(tabela, "data") == ["01/12/2025", "31/12/2025", "02/01/2026"]


def test_data_invertida(tabela):
    _preencher(tabela, [("R$ 1,00", "02/01/2026", "A"),
                        ("R$ 2,00", "01/12/2025", "B")])
    widgets.ordenar_tabela(tabela, "data", descendente=True)
    assert _coluna(tabela, "data") == ["02/01/2026", "01/12/2025"]


def test_data_invalida_nao_derruba_a_ordenacao(tabela):
    """31/02 é digitação, não data: a coluna inteira volta a ser texto em vez
    de estourar no meio do `sorted`."""
    _preencher(tabela, [("R$ 1,00", "31/02/2026", "A"),
                        ("R$ 2,00", "01/12/2025", "B")])
    widgets.ordenar_tabela(tabela, "data")
    assert len(_coluna(tabela, "data")) == 2


# ---------------------------------------------------------------------- texto
def test_texto_ordena_sem_acento_e_sem_caixa(tabela):
    """Sem normalizar, "Ática" cai depois de "Zebra": "Á" vem depois de "Z" na
    tabela de caracteres, e ninguém procura um nome ali."""
    _preencher(tabela, [("R$ 1,00", "01/01/2026", "Zebra"),
                        ("R$ 2,00", "02/01/2026", "Ática"),
                        ("R$ 3,00", "03/01/2026", "banco")])
    widgets.ordenar_tabela(tabela, "quem")
    assert _coluna(tabela, "quem") == ["Ática", "banco", "Zebra"]


# ---------------------------------------------------------------------- setas
def test_as_setas_alternam_e_so_uma_coluna_tem_seta(tabela):
    _preencher(tabela, [("R$ 1,00", "01/01/2026", "A"),
                        ("R$ 2,00", "02/01/2026", "B")])
    widgets.ordenar_tabela(tabela, "valor")
    assert str(tabela.heading("valor", "text")) == "Valor ▲"
    widgets.ordenar_tabela(tabela, "valor")
    assert str(tabela.heading("valor", "text")) == "Valor ▼"

    widgets.ordenar_tabela(tabela, "quem")
    assert str(tabela.heading("quem", "text")) == "Favorecido ▲"
    assert str(tabela.heading("valor", "text")) == "Valor", (
        "a seta ficou em duas colunas: a tabela diz estar ordenada por duas "
        "coisas ao mesmo tempo")


def test_a_seta_nao_gruda_no_titulo(tabela):
    """Ordenar dez vezes não pode virar "Valor ▲ ▲ ▲"."""
    _preencher(tabela, [("R$ 1,00", "01/01/2026", "A")])
    for _ in range(6):
        widgets.ordenar_tabela(tabela, "valor")
    assert str(tabela.heading("valor", "text")) in ("Valor ▲", "Valor ▼")


# ---------------------------------------------------------------------- zebra
def _zebra(tv):
    return [next((t for t in tv.item(i, "tags") if t in ("par", "impar")), "")
            for i in tv.get_children("")]


def test_a_zebra_e_reaplicada_depois_de_ordenar(tabela):
    """A tag "par"/"impar" viaja com o item: sem reaplicar, as listras saem
    embaralhadas e a tabela parece um erro de desenho."""
    _preencher(tabela, [("R$ 3,00", "01/01/2026", "A"),
                        ("R$ 1,00", "02/01/2026", "B"),
                        ("R$ 2,00", "03/01/2026", "C")])
    antes = _zebra(tabela)
    assert antes == ["impar", "par", "impar"]
    widgets.ordenar_tabela(tabela, "valor")
    assert _coluna(tabela, "valor") == ["R$ 1,00", "R$ 2,00", "R$ 3,00"]
    assert _zebra(tabela) == ["impar", "par", "impar"], (
        "as listras ficaram fora de ordem depois de ordenar")


def test_ordenar_nao_apaga_o_estado_da_linha(tabela):
    """A zebra é da POSIÇÃO; o estado é do DADO, e tem de sobreviver à
    mudança — senão a linha rejeitada perde a cor ao se ordenar a tabela."""
    tabela.insert("", "end", values=("R$ 3,00", "01/01/2026", "A"),
                  tags=widgets.linha_zebrada(0, "erro"))
    tabela.insert("", "end", values=("R$ 1,00", "02/01/2026", "B"),
                  tags=widgets.linha_zebrada(1, "atencao"))
    widgets.ordenar_tabela(tabela, "valor")
    primeiro = tabela.get_children("")[0]
    assert "atencao" in tabela.item(primeiro, "tags")
    assert "erro" in tabela.item(tabela.get_children("")[1], "tags")


def test_sem_zebra_a_ordenacao_nao_inventa_tags(raiz):
    tv = ttk.Treeview(raiz, columns=("valor",), show="headings")
    tv.heading("valor", text="Valor")
    widgets.estilo_tabela(tv, zebra=False)
    for v in ("R$ 3,00", "R$ 1,00"):
        tv.insert("", "end", values=(v,))
    try:
        widgets.ordenar_tabela(tv, "valor")
        assert all(not tv.item(i, "tags") for i in tv.get_children(""))
    finally:
        tv.destroy()
        raiz.update()


# -------------------------------------------------------------- ligar/desligar
def test_o_clique_no_cabecalho_esta_ligado_por_padrao(tabela):
    """Cabeçalho que não responde ao clique é lido como tabela quebrada."""
    for col in ("valor", "data", "quem"):
        assert str(tabela.heading(col, "command")), (
            f"a coluna {col} não ordena ao ser clicada")


def test_da_para_desligar(raiz):
    tv = ttk.Treeview(raiz, columns=("passo",), show="headings")
    tv.heading("passo", text="Passo")
    widgets.estilo_tabela(tv, ordenavel=False)
    try:
        assert not str(tv.heading("passo", "command"))
    finally:
        tv.destroy()
        raiz.update()


def test_coluna_que_ja_tem_dono_nao_e_sequestrada(raiz):
    """O cabeçalho da coluna de marcação do Baixar Comprovantes é o "marcar
    todas" — um botão disfarçado de cabeçalho. Trocá-lo por uma ordenação
    tiraria da tela o único lugar onde se marca tudo de uma vez."""
    tv = ttk.Treeview(raiz, columns=("marca", "nome"), show="headings")
    chamou = []
    tv.heading("marca", text="☑", command=lambda: chamou.append(1))
    tv.heading("nome", text="Nome")
    widgets.estilo_tabela(tv)
    try:
        tv.event_generate("<Expose>")
        raiz.update()
        tv.tk.call(tv._w, "heading", "marca", "-command")   # existe
        # O comando continua sendo o da tela: invocá-lo marca todas.
        tv.tk.call(str(tv.heading("marca", "command")))
        assert chamou == [1]
        assert str(tv.heading("nome", "command")), (
            "as outras colunas deviam continuar ordenando")
    finally:
        tv.destroy()
        raiz.update()


# ------------------------------------------------------------------- fixos
def test_a_linha_fixa_nao_se_move(raiz):
    """A "(deixar em dúvida)" do Anexar é uma OPÇÃO, não um candidato: ordenar
    a lista não pode enterrá-la no meio dos arquivos."""
    tv = ttk.Treeview(raiz, columns=("arquivo",), show="headings")
    tv.heading("arquivo", text="Arquivo")
    widgets.estilo_tabela(tv, fixos=("_nada",))
    tv.insert("", "end", iid="_nada", values=("(deixar em dúvida)",))
    for k, nome in enumerate(("zulu.pdf", "alfa.pdf", "mike.pdf")):
        tv.insert("", "end", iid=f"c{k}", values=(nome,),
                  tags=widgets.linha_zebrada(k))
    try:
        widgets.ordenar_tabela(tv, "arquivo")
        assert tv.get_children("")[0] == "_nada"
        assert _coluna(tv, "arquivo")[1:] == ["alfa.pdf", "mike.pdf",
                                              "zulu.pdf"]
        widgets.ordenar_tabela(tv, "arquivo")            # e no inverso também
        assert tv.get_children("")[0] == "_nada"
    finally:
        tv.destroy()
        raiz.update()


# ------------------------------------------------------------------- limites
def test_tabela_vazia_nao_estoura(tabela):
    widgets.ordenar_tabela(tabela, "valor")
    assert tabela.get_children("") == ()


def test_tabela_destruida_nao_estoura(raiz):
    tv = ttk.Treeview(raiz, columns=("a",), show="headings")
    widgets.estilo_tabela(tv)
    tv.destroy()
    raiz.update()
    with pytest.raises(tk.TclError):
        tv.get_children("")              # confirma que ela morreu mesmo
    widgets.ordenar_tabela(tv, "a")      # e a ordenação engole isso
