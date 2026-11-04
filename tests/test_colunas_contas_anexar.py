"""Grade de contas do Anexar: colunas acompanham a largura (dono, 04/11/2026).

Com 3 colunas fixas, nome longo de conta empurrava a 3ª coluna para fora do
cartão e ela sumia cortada, sem barra para rolar.
"""
import tkinter as tk
from tkinter import ttk

from anexar.anexar_comprovantes import colunas_que_cabem


def test_tudo_curto_usa_o_teto():
    assert colunas_que_cabem([100] * 20, 1500, 8) == 4


def test_nome_longo_reduz_colunas_ate_caber():
    # parecido com a tela do dono: uma conta de ~600 px na 1ª coluna
    larguras = [600, 450, 300] * 7
    assert colunas_que_cabem(larguras, 1450, 8) == 3   # 608+458+308 = 1374
    assert colunas_que_cabem(larguras, 1300, 8) == 2   # 3 colunas não cabem


def test_nunca_corta_coluna_inteira():
    larguras = [700, 700, 700]
    assert colunas_que_cabem(larguras, 1500, 8) == 2
    assert colunas_que_cabem(larguras, 1000, 8) == 1


def test_nada_cabe_devolve_uma():
    assert colunas_que_cabem([2000], 500, 8) == 1
    assert colunas_que_cabem([900, 900], 500, 8) == 1


def test_nao_passa_do_numero_de_contas():
    assert colunas_que_cabem([100, 100], 1500, 8) == 2


def test_grade_real_cabe_na_largura(raiz):
    """Monta checkbuttons de verdade e confere que nenhum passa da borda."""
    caixa = ttk.Frame(raiz, width=900)
    caixa.pack(fill="x")
    nomes = ["MORAIS EMPREENDIMENTOS GOIANIA SPE I LTDA - Conta corrente: "
             "00000-0 - SICOOB  (4)"] + [f"CONTA {i} - SICOOB  (1)" for i in range(19)]
    v = tk.BooleanVar(master=raiz, value=True)
    caixas = [ttk.Checkbutton(caixa, text=t, variable=v) for t in nomes]
    larg = 900
    n = colunas_que_cabem([w.winfo_reqwidth() for w in caixas], larg, 8)
    for i, w in enumerate(caixas):
        w.grid(row=i // n, column=i % n, sticky="w", padx=4)
    raiz.update_idletasks()
    if n > 1:
        assert caixa.winfo_reqwidth() <= larg
    caixa.destroy()
