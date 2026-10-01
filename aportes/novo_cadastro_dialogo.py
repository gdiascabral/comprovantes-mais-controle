# -*- coding: utf-8 -*-
"""A janela do botão "Novo cadastro" da aba Aportes.

Só Tk. A regra (o que sugerir, o que recusar) está em `novo_cadastro.py`, que
tem teste; aqui a janela mostra, pergunta e devolve um `Novo` — ou None, se a
pessoa desistiu. Quem grava é a aba.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import util
import widgets

from . import novo_cadastro as nc

log = util.log(__name__)

CONTA = "conta"
PESSOA = "pessoa"


def perguntar(pai, contas: list[dict], entidades: list[dict]) -> nc.Novo | None:
    top = tk.Toplevel(pai)
    top.withdraw()
    top.title("Novo cadastro — Aportes")
    top.transient(pai)
    try:
        widgets.barra_de_titulo(top)
    except Exception:
        log.warning("barra de título do Novo cadastro", exc_info=True)

    livres = nc.contas_livres(contas, entidades)
    resultado: list[nc.Novo] = []

    corpo = ttk.Frame(top, padding=16)
    corpo.pack(fill="both", expand=True)
    ttk.Label(corpo, style="Secao.TLabel",
              text="Quem paga ou recebe aportes").pack(anchor="w")
    ttk.Label(corpo, style="Apoio.TLabel", wraplength=560, justify="left",
              text="Entra na lista de Pagou e Recebeu desta aba, em todos os "
                   "computadores. Corrigir ou apagar depois continua sendo "
                   "pelo painel do Supabase — confira antes de cadastrar."
              ).pack(anchor="w", pady=(2, 12))

    tipo = tk.StringVar(value=CONTA if livres else PESSOA)
    linha_tipo = ttk.Frame(corpo)
    linha_tipo.pack(anchor="w", pady=(0, 10))
    ttk.Radiobutton(linha_tipo, text="Conta bancária de empresa/obra",
                    variable=tipo, value=CONTA,
                    command=lambda: trocou_tipo()).pack(side="left")
    ttk.Radiobutton(linha_tipo, text="Pessoa física (sem conta no app)",
                    variable=tipo, value=PESSOA,
                    command=lambda: trocou_tipo()).pack(side="left",
                                                        padx=(16, 0))

    v_conta = tk.StringVar()
    v_oficial = tk.StringVar()
    v_exibicao = tk.StringVar()
    v_apelido = tk.StringVar()

    campo_conta = widgets.Campo(
        corpo, "Conta no Mais Controle (as que ainda não estão na lista)",
        lambda p: widgets.ComboBusca(p, width=64, textvariable=v_conta))
    campo_conta.pack(anchor="w", fill="x", pady=(0, 10))
    cb_conta = campo_conta.widget
    cb_conta.definir_valores(livres)

    for rotulo, var in (
            ("Nome do contato no Mais Controle (Favorecido / Cliente)",
             v_oficial),
            ("Nome na lista de Pagou / Recebeu", v_exibicao),
            ("Apelido na descrição (opcional)", v_apelido)):
        widgets.Campo(corpo, rotulo,
                      lambda p, v=var: ttk.Entry(p, textvariable=v, width=66)
                      ).pack(anchor="w", fill="x", pady=(0, 10))

    erro = ttk.Label(corpo, style="Erro.TLabel",
                     wraplength=560, justify="left", text="")
    erro.pack(anchor="w")
    if not livres:
        erro.configure(text="Todas as contas do cadastro já estão na lista. "
                            "Conta que nasceu hoje no Mais Controle entra "
                            "primeiro pela janela de contas novas, na "
                            "abertura do app.")

    # O que a janela preencheu sozinha. Só se sobrescreve o que ainda é
    # sugestão: o que a pessoa digitou por cima é dela.
    sugerido = {"oficial": "", "exibicao": ""}

    def escolheu_conta(*_a):
        conta = v_conta.get().strip()
        if conta not in livres:
            return
        oficial = nc.nome_oficial_sugerido(conta, contas, entidades)
        if v_oficial.get().strip() in ("", sugerido["oficial"]):
            v_oficial.set(oficial)
            sugerido["oficial"] = oficial
        if v_exibicao.get().strip() in ("", sugerido["exibicao"]):
            v_exibicao.set(conta)
            sugerido["exibicao"] = conta

    v_conta.trace_add("write", escolheu_conta)

    def trocou_tipo():
        if tipo.get() == CONTA:
            cb_conta.configure(state="normal")
        else:
            v_conta.set("")
            cb_conta.configure(state="disabled")

    def cadastrar(_e=None):
        conta = v_conta.get().strip() if tipo.get() == CONTA else ""
        if tipo.get() == CONTA and conta not in livres:
            erro.configure(text="Escolha a conta na lista — ela precisa ter o "
                                "nome exato do Mais Controle.")
            return
        novo = nc.Novo(v_exibicao.get(), v_oficial.get(), conta,
                       v_apelido.get())
        problema = nc.validar(novo, entidades)
        if problema:
            erro.configure(text=problema)
            return
        resultado.append(novo)
        top.destroy()

    rodape = ttk.Frame(corpo)
    rodape.pack(fill="x", pady=(14, 0))
    ttk.Button(rodape, text="Cancelar", command=top.destroy).pack(side="right")
    botao = ttk.Button(rodape, text="Cadastrar", command=cadastrar)
    botao.pack(side="right", padx=(0, 8))
    try:
        botao.configure(style="Accent.TButton")
    except tk.TclError:
        pass

    trocou_tipo()
    top.update_idletasks()
    x = max(0, (top.winfo_screenwidth() - top.winfo_reqwidth()) // 2)
    y = max(0, (top.winfo_screenheight() - top.winfo_reqheight()) // 2 - 20)
    top.geometry(f"+{x}+{y}")
    top.deiconify()
    top.protocol("WM_DELETE_WINDOW", top.destroy)
    top.bind("<Escape>", lambda _e: top.destroy())
    top.bind("<Return>", cadastrar)
    try:
        top.grab_set()
        (cb_conta if tipo.get() == CONTA else top).focus_set()
    except tk.TclError:
        pass
    pai.wait_window(top)
    return resultado[0] if resultado else None
