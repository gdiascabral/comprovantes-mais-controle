# -*- coding: utf-8 -*-
"""A janela do botão "Rateio de subconta" da aba Aportes.

Só Tk; a regra está em `rateio_subconta.py`. Devolve `(numero,
investidores, obras)` ou None.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import util
import widgets

from . import rateio_subconta as rs

log = util.log(__name__)


def _lista_editavel(pai, rotulo: str, opcoes: list[str]):
    """Combo de busca + "Adicionar" + lista com "Remover". Devolve a função
    que lê os nomes escolhidos e a que troca o conteúdo."""
    quadro = ttk.Frame(pai)
    ttk.Label(quadro, text=rotulo.upper(), style="Rotulo.TLabel"
              ).pack(anchor="w", pady=(0, 3))
    linha = ttk.Frame(quadro)
    linha.pack(fill="x")
    combo = widgets.ComboBusca(linha, width=48)
    combo.definir_valores(opcoes)
    combo.pack(side="left", fill="x", expand=True)
    # Treeview e não Listbox: é ela que a paleta já pinta nos dois temas.
    lista = ttk.Treeview(quadro, columns=("n",), show="", height=5,
                         selectmode="extended")
    lista.column("n", anchor="w")
    widgets.estilo_tabela(lista, zebra=False, ordenavel=False)

    def nomes():
        return [lista.item(i, "values")[0] for i in lista.get_children()]

    def adicionar(_e=None):
        nome = combo.get().strip()
        if not nome:
            return "break"
        if util.norm_espaco(nome) not in [util.norm_espaco(n) for n in nomes()]:
            lista.insert("", "end", values=(nome,))
        combo.set("")
        return "break"

    def remover():
        for i in lista.selection():
            lista.delete(i)

    ttk.Button(linha, text="Adicionar", command=adicionar
               ).pack(side="left", padx=(8, 0))
    combo.bind("<Return>", adicionar)
    lista.pack(fill="x", pady=(6, 0))
    ttk.Button(quadro, text="Remover selecionado", command=remover
               ).pack(anchor="e", pady=(4, 0))
    def ler():
        return nomes()

    def trocar(novos):
        lista.delete(*lista.get_children())
        for n in novos:
            lista.insert("", "end", values=(n,))

    return quadro, ler, trocar


def perguntar(pai, numeros: list[str], subcontas: dict,
              participantes: list[str], centros: list[str]):
    top = tk.Toplevel(pai)
    top.withdraw()
    top.title("Rateio de subconta — Aportes")
    top.transient(pai)
    try:
        widgets.barra_de_titulo(top)
    except Exception:
        log.warning("barra de título do Rateio de subconta", exc_info=True)

    resultado: list = []
    corpo = ttk.Frame(top, padding=16)
    corpo.pack(fill="both", expand=True)
    ttk.Label(corpo, style="Secao.TLabel",
              text="Investidores e centros de custo da subconta").pack(anchor="w")
    ttk.Label(corpo, style="Apoio.TLabel", wraplength=600, justify="left",
              text="Em Pagou a subconta aparece como \"Investidor conta "
                   "00000-0\". Ao lançar, o valor é dividido em partes "
                   "iguais entre cada centro de custo × investidor, um "
                   "recebimento para cada. Os nomes vêm das listas do Mais "
                   "Controle."
              ).pack(anchor="w", pady=(2, 12))

    v_numero = tk.StringVar()
    campo = widgets.Campo(corpo, "Subconta",
                          lambda p: ttk.Combobox(p, state="readonly", width=20,
                                                 values=numeros,
                                                 textvariable=v_numero))
    campo.pack(anchor="w", pady=(0, 10))

    q_inv, ler_inv, trocar_inv = _lista_editavel(
        corpo, "Investidores (contatos do Mais Controle)", participantes)
    q_inv.pack(fill="x", pady=(0, 10))
    q_cc, ler_cc, trocar_cc = _lista_editavel(
        corpo, "Centros de custo (obras do Mais Controle)", centros)
    q_cc.pack(fill="x", pady=(0, 10))

    erro = ttk.Label(corpo, style="Erro.TLabel", wraplength=600,
                     justify="left", text="")
    erro.pack(anchor="w")

    def escolheu(*_a):
        cfg = subcontas.get(v_numero.get()) or {}
        trocar_inv(cfg.get("investidores") or [])
        trocar_cc(cfg.get("obras") or [])
        erro.configure(text="" if cfg else "Subconta sem rateio ainda: "
                                            "adicione investidores e CCs.")

    v_numero.trace_add("write", escolheu)

    def gravar():
        numero, invs, ccs = v_numero.get(), ler_inv(), ler_cc()
        problema = rs.validar(numero, invs, ccs, participantes=participantes,
                              centros=centros)
        if problema:
            erro.configure(text=problema)
            return
        resultado.append((numero, invs, ccs))
        top.destroy()

    rodape = ttk.Frame(corpo)
    rodape.pack(fill="x", pady=(14, 0))
    ttk.Button(rodape, text="Cancelar", command=top.destroy).pack(side="right")
    botao = ttk.Button(rodape, text="Gravar rateio", command=gravar)
    botao.pack(side="right", padx=(0, 8))
    try:
        botao.configure(style="Accent.TButton")
    except tk.TclError:
        pass

    top.update_idletasks()
    x = max(0, (top.winfo_screenwidth() - top.winfo_reqwidth()) // 2)
    y = max(0, (top.winfo_screenheight() - top.winfo_reqheight()) // 2 - 20)
    top.geometry(f"+{x}+{y}")
    top.deiconify()
    top.protocol("WM_DELETE_WINDOW", top.destroy)
    top.bind("<Escape>", lambda _e: top.destroy())
    try:
        top.grab_set()
    except tk.TclError:
        pass
    pai.wait_window(top)
    return resultado[0] if resultado else None
