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
from . import regras

log = util.log(__name__)


def _lista_editavel(pai, rotulo: str, opcoes: list[str], com_pct=False):
    """Combo de busca + "Adicionar" + lista com "Remover".

    `com_pct` (centros de custo) põe um campo "%" ao lado: adicionar de novo
    um nome que já está na lista só troca o % dele. Devolve o quadro, quem lê
    os nomes, quem troca o conteúdo e quem lê os % (`{nome: "70"}`)."""
    quadro = ttk.Frame(pai)
    ttk.Label(quadro, text=rotulo.upper(), style="Rotulo.TLabel"
              ).pack(anchor="w", pady=(0, 3))
    linha = ttk.Frame(quadro)
    linha.pack(fill="x")
    combo = widgets.ComboBusca(linha, width=48)
    combo.definir_valores(opcoes)
    combo.pack(side="left", fill="x", expand=True)
    v_pct = tk.StringVar()
    if com_pct:
        ttk.Label(linha, text="%").pack(side="left", padx=(8, 2))
        ttk.Entry(linha, textvariable=v_pct, width=7).pack(side="left")
    # Treeview e não Listbox: é ela que a paleta já pinta nos dois temas.
    colunas = ("n", "p") if com_pct else ("n",)
    lista = ttk.Treeview(quadro, columns=colunas,
                         show="headings" if com_pct else "", height=5,
                         selectmode="extended")
    lista.column("n", anchor="w")
    if com_pct:
        lista.heading("n", text="CENTRO DE CUSTO")
        lista.heading("p", text="%")
        lista.column("p", width=70, anchor="e", stretch=False)
    widgets.estilo_tabela(lista, zebra=False, ordenavel=False)
    total = ttk.Label(quadro, style="Apoio.TLabel", text="")

    def linhas():
        return [(i, lista.item(i, "values")) for i in lista.get_children()]

    def nomes():
        return [v[0] for _, v in linhas()]

    def pcts():
        return {v[0]: v[1] for _, v in linhas() if len(v) > 1 and str(v[1]).strip()}

    def somar():
        if not com_pct:
            return
        try:
            soma = sum(regras.Decimal(str(p).replace(",", "."))
                       for p in pcts().values())
        except Exception:
            total.configure(text="Há um % que não é número.")
            return
        total.configure(text=("Sem %: o valor se divide em partes iguais."
                              if not pcts() else f"Total: {soma:g}% "
                              "(precisa fechar 100)"))

    def adicionar(_e=None):
        nome = combo.get().strip()
        if not nome:
            return "break"
        pct = v_pct.get().strip().replace("%", "")
        for i, v in linhas():
            if util.norm_espaco(v[0]) == util.norm_espaco(nome):
                if com_pct:
                    lista.item(i, values=(v[0], pct))
                break
        else:
            lista.insert("", "end", values=(nome, pct) if com_pct else (nome,))
        combo.set("")
        v_pct.set("")
        somar()
        return "break"

    def remover():
        for i in lista.selection():
            lista.delete(i)
        somar()

    def escolheu_linha(_e=None):
        # Clicar numa linha traz o nome e o % para cima: é assim que se troca
        # o % de um CC (Adicionar de novo com o % novo).
        sel = lista.selection()
        if com_pct and len(sel) == 1:
            v = lista.item(sel[0], "values")
            combo.set(v[0])
            v_pct.set(v[1] if len(v) > 1 else "")

    ttk.Button(linha, text="Adicionar", command=adicionar
               ).pack(side="left", padx=(8, 0))
    combo.bind("<Return>", adicionar)
    lista.bind("<<TreeviewSelect>>", escolheu_linha)
    lista.pack(fill="x", pady=(6, 0))
    rodape = ttk.Frame(quadro)
    rodape.pack(fill="x", pady=(4, 0))
    total.pack(in_=rodape, side="left")
    ttk.Button(rodape, text="Remover selecionado", command=remover
               ).pack(side="right")

    def trocar(novos, percentuais=None):
        lista.delete(*lista.get_children())
        for n in novos:
            if com_pct:
                pct = regras.percentual_de(percentuais or {}, n)
                lista.insert("", "end", values=(n, "" if pct is None
                                                else format(pct, "f")))
            else:
                lista.insert("", "end", values=(n,))
        somar()

    somar()
    return quadro, nomes, trocar, pcts


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
                   "recebimento para cada. Com % em TODOS os CCs (somando 100), "
                   "cada CC leva o seu %; sem %, partes iguais. Os nomes vêm "
                   "das listas do Mais Controle."
              ).pack(anchor="w", pady=(2, 12))

    v_numero = tk.StringVar()
    campo = widgets.Campo(corpo, "Subconta",
                          lambda p: ttk.Combobox(p, state="readonly", width=20,
                                                 values=numeros,
                                                 textvariable=v_numero))
    campo.pack(anchor="w", pady=(0, 10))

    q_inv, ler_inv, trocar_inv, _ = _lista_editavel(
        corpo, "Investidores (contatos do Mais Controle)", participantes)
    q_inv.pack(fill="x", pady=(0, 10))
    q_cc, ler_cc, trocar_cc, ler_pct = _lista_editavel(
        corpo, "Centros de custo (obras do Mais Controle) e % de cada um",
        centros, com_pct=True)
    q_cc.pack(fill="x", pady=(0, 10))

    erro = ttk.Label(corpo, style="Erro.TLabel", wraplength=600,
                     justify="left", text="")
    erro.pack(anchor="w")

    def escolheu(*_a):
        cfg = subcontas.get(v_numero.get()) or {}
        trocar_inv(cfg.get("investidores") or [])
        trocar_cc(cfg.get("obras") or [], cfg.get("percentuais"))
        erro.configure(text="" if cfg else "Subconta sem rateio ainda: "
                                            "adicione investidores e CCs.")

    v_numero.trace_add("write", escolheu)

    def gravar():
        numero, invs, ccs = v_numero.get(), ler_inv(), ler_cc()
        try:
            pcts = {n: str(regras.Decimal(p.replace(",", ".")))
                    for n, p in ler_pct().items()}
        except Exception:
            erro.configure(text="Há um % que não é número (use 70 ou 33,5).")
            return
        problema = rs.validar(numero, invs, ccs, participantes=participantes,
                              centros=centros, percentuais=pcts)
        if problema:
            erro.configure(text=problema)
            return
        resultado.append((numero, invs, ccs, pcts))
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
