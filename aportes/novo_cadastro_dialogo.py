# -*- coding: utf-8 -*-
"""A janela do botão "Novo cadastro" da aba Aportes.

Uma janela, três cadastros (pedido do dono, 01/10/2026):

* **Subconta de investidor** — a conta, os aportadores (clientes no Mais
  Controle) com a proporção de cada um, e as obras entre as quais o aporte
  se divide igual. Os nomes em Pagou ("INVESTIDOR SUBCONTA 00000-0") e em
  Recebeu ("SUBCONTA 00000-0 - SICOOB - INVESTIDOR") saem sozinhos. Escolher
  uma subconta que já existe abre o rateio dela para mudar.
* **Conta de empresa/obra** e **Pessoa física** — como antes.

Só Tk. A regra está em `novo_cadastro.py` e `rateio_subconta.py`, que têm
teste; quem grava é a aba. Devolve `("investidor", Investidor)`,
`("entidade", Novo)` ou None.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import util
import widgets

from . import novo_cadastro as nc
from . import rateio_subconta as rs
from . import regras

log = util.log(__name__)

INVESTIDOR = "investidor"
CONTA = "conta"
PESSOA = "pessoa"


def _tabela(pai, colunas, alturas=5):
    """Treeview com cabeçalho, pintada pela paleta (Listbox não é)."""
    t = ttk.Treeview(pai, columns=[c for c, _, _ in colunas], show="headings",
                     height=alturas, selectmode="extended")
    for chave, titulo, largura in colunas:
        t.heading(chave, text=titulo)
        t.column(chave, width=largura, anchor="e" if largura < 120 else "w",
                 stretch=largura >= 120)
    widgets.estilo_tabela(t, zebra=False, ordenavel=False)
    return t


def _linhas(t):
    return [(i, t.item(i, "values")) for i in t.get_children()]


def perguntar(pai, contas, entidades, subcontas, participantes=None,
              centros=None):
    """`participantes`/`centros` são as listas do ERP; None quando não deu
    para lê-las — aí a opção de investidor fica desligada, com o motivo."""
    top = tk.Toplevel(pai)
    top.withdraw()
    top.title("Novo cadastro — Aportes")
    top.transient(pai)
    try:
        widgets.barra_de_titulo(top)
    except Exception:
        log.warning("barra de título do Novo cadastro", exc_info=True)

    livres = nc.contas_livres(contas, entidades)
    de_investidor = nc.contas_de_investidor(contas, entidades, subcontas)
    tem_erp = participantes is not None and centros is not None
    resultado: list = []

    corpo = ttk.Frame(top, padding=16)
    corpo.pack(fill="both", expand=True)
    ttk.Label(corpo, style="Secao.TLabel",
              text="Quem paga ou recebe aportes").pack(anchor="w")
    ttk.Label(corpo, style="Apoio.TLabel", wraplength=640, justify="left",
              text="Entra na lista de Pagou e Recebeu desta aba, em todos os "
                   "computadores."
              ).pack(anchor="w", pady=(2, 10))

    tipo = tk.StringVar(value=INVESTIDOR if tem_erp else CONTA)
    linha_tipo = ttk.Frame(corpo)
    linha_tipo.pack(anchor="w", pady=(0, 10))
    for texto, valor in (("Subconta de investidor", INVESTIDOR),
                         ("Conta de empresa/obra", CONTA),
                         ("Pessoa física", PESSOA)):
        b = ttk.Radiobutton(linha_tipo, text=texto, variable=tipo, value=valor,
                            command=lambda: trocou_tipo())
        b.pack(side="left", padx=(0, 16))
        if valor == INVESTIDOR and not tem_erp:
            b.configure(state="disabled")

    area = ttk.Frame(corpo)
    area.pack(fill="both", expand=True)

    # ---------------------------------------------------------- investidor
    f_inv = ttk.Frame(area)
    v_conta_inv = tk.StringVar()
    v_dono = tk.StringVar()
    campo = widgets.Campo(
        f_inv, "Conta no Mais Controle",
        lambda p: widgets.ComboBusca(p, width=72, textvariable=v_conta_inv))
    campo.pack(anchor="w", fill="x", pady=(0, 4))
    cb_conta_inv = campo.widget
    cb_conta_inv.definir_valores(de_investidor)
    nomes = ttk.Label(f_inv, style="Apoio.TLabel", text="", justify="left")
    nomes.pack(anchor="w", pady=(0, 8))
    campo_dono = widgets.Campo(
        f_inv, "Empresa dona da conta (nome do cliente no Mais Controle)",
        lambda p: ttk.Entry(p, textvariable=v_dono, width=74))
    campo_dono.pack(anchor="w", fill="x", pady=(0, 10))

    ttk.Label(f_inv, text="APORTADORES (CLIENTES NO MAIS CONTROLE)",
              style="Rotulo.TLabel").pack(anchor="w", pady=(0, 3))
    l_ap = ttk.Frame(f_inv)
    l_ap.pack(fill="x")
    cb_ap = widgets.ComboBusca(l_ap, width=50)
    cb_ap.definir_valores(participantes or [])
    cb_ap.pack(side="left", fill="x", expand=True)
    ttk.Label(l_ap, text="Parte").pack(side="left", padx=(8, 2))
    v_parte = tk.StringVar()
    ttk.Entry(l_ap, textvariable=v_parte, width=7).pack(side="left")
    t_ap = _tabela(f_inv, [("n", "APORTADOR", 360), ("p", "PARTE", 70),
                           ("pct", "%", 70)], 4)

    l_prop = ttk.Frame(f_inv)
    ttk.Label(l_prop, style="Apoio.TLabel",
              text="Parte vazia em todos = partes iguais. Pode ser % (60 e 40) "
                   "ou proporção (2 e 1). Ou digite a proporção inteira:"
              ).pack(side="left")
    v_prop = tk.StringVar()
    ttk.Entry(l_prop, textvariable=v_prop, width=10).pack(side="left",
                                                          padx=(6, 4))

    lbl_ob = ttk.Label(f_inv, text="OBRAS (CENTROS DE CUSTO) — CADA APORTE "
                                   "SE DIVIDE IGUAL ENTRE ELAS",
                       style="Rotulo.TLabel")
    lbl_ob.pack(anchor="w", pady=(12, 3))
    l_ob = ttk.Frame(f_inv)
    l_ob.pack(fill="x")
    cb_ob = widgets.ComboBusca(l_ob, width=60)
    cb_ob.definir_valores(centros or [])
    cb_ob.pack(side="left", fill="x", expand=True)
    t_ob = _tabela(f_inv, [("n", "OBRA", 500)], 4)

    def nomes_ap():
        return [v[0] for _, v in _linhas(t_ap)]

    def pesos_ap():
        return {v[0]: v[1] for _, v in _linhas(t_ap) if str(v[1]).strip()}

    def recalcular():
        invs = nomes_ap()
        try:
            pcts = regras.percentuais_dos_pesos(invs, pesos_ap())
        except Exception:
            pcts = [""] * len(invs)
        for (i, v), pct in zip(_linhas(t_ap), pcts):
            t_ap.item(i, values=(v[0], v[1], f"{pct}".replace(".", ",")
                                 if pct != "" else ""))

    def add_ap(_e=None):
        nome = cb_ap.get().strip()
        if not nome:
            return "break"
        try:
            parte = rs.ler_parte(v_parte.get()) or ""
        except ValueError as e:
            erro.configure(text=str(e))
            return "break"
        for i, v in _linhas(t_ap):
            if util.norm_espaco(v[0]) == util.norm_espaco(nome):
                t_ap.item(i, values=(v[0], parte, ""))
                break
        else:
            t_ap.insert("", "end", values=(nome, parte, ""))
        cb_ap.set("")
        v_parte.set("")
        erro.configure(text="")
        recalcular()
        return "break"

    def aplicar_prop(_e=None):
        try:
            partes = rs.partes_de_proporcao(v_prop.get(), len(nomes_ap()))
        except ValueError as e:
            erro.configure(text=str(e))
            return "break"
        if partes is None:
            erro.configure(text="Escreva a proporção com dois-pontos, na "
                                "ordem da lista: 2:1, 60:40, 1:1:1.")
            return "break"
        for (i, v), p in zip(_linhas(t_ap), partes):
            t_ap.item(i, values=(v[0], p or "", ""))
        v_prop.set("")
        erro.configure(text="")
        recalcular()
        return "break"

    def escolheu_ap(_e=None):
        sel = t_ap.selection()
        if len(sel) == 1:
            v = t_ap.item(sel[0], "values")
            cb_ap.set(v[0])
            v_parte.set(v[1])

    def add_ob(_e=None):
        nome = cb_ob.get().strip()
        if nome and util.norm_espaco(nome) not in [
                util.norm_espaco(v[0]) for _, v in _linhas(t_ob)]:
            t_ob.insert("", "end", values=(nome,))
        cb_ob.set("")
        return "break"

    def remover(t):
        for i in t.selection():
            t.delete(i)
        recalcular()

    ttk.Button(l_ap, text="Adicionar", command=add_ap).pack(side="left",
                                                           padx=(8, 0))
    cb_ap.bind("<Return>", add_ap)
    t_ap.bind("<<TreeviewSelect>>", escolheu_ap)
    # `before`: a lista e a proporção são dos aportadores, e o rótulo das
    # obras já está empacotado logo abaixo deles.
    t_ap.pack(fill="x", pady=(6, 0), before=lbl_ob)
    ttk.Button(l_prop, text="Aplicar", command=aplicar_prop).pack(side="left")
    ttk.Button(l_prop, text="Remover selecionado",
               command=lambda: remover(t_ap)).pack(side="right")
    l_prop.pack(fill="x", pady=(4, 0), before=lbl_ob)
    ttk.Button(l_ob, text="Adicionar", command=add_ob).pack(side="left",
                                                           padx=(8, 0))
    cb_ob.bind("<Return>", add_ob)
    t_ob.pack(fill="x", pady=(6, 0))
    ttk.Button(f_inv, text="Remover selecionado",
               command=lambda: remover(t_ob)).pack(anchor="e", pady=(4, 0))

    def escolheu_conta_inv(*_a):
        conta = v_conta_inv.get().strip()
        if conta not in de_investidor:
            nomes.configure(text="")
            return
        inv = nc.Investidor(conta, "", [], [], {},
                            nc.banco_da_conta(conta, contas))
        existente = nc.entidade_da_conta(conta, entidades)
        nomes.configure(text=f"Em Pagou:  {inv.em_pagou}\n"
                             f"Em Recebeu:  {existente['nome_exibicao'] if existente else inv.em_recebeu}")
        if existente:
            v_dono.set(existente.get("nome_oficial") or "")
            campo_dono.widget.configure(state="disabled")
        else:
            campo_dono.widget.configure(state="normal")
            v_dono.set(nc.nome_oficial_sugerido(conta, contas, entidades))
        cfg = subcontas.get(inv.numero) or {}
        t_ap.delete(*t_ap.get_children())
        for n in cfg.get("investidores") or []:
            p = regras.peso_de(cfg.get("pesos") or {}, n)
            t_ap.insert("", "end", values=(n, "" if p is None
                                           else format(p.normalize(), "f"), ""))
        t_ob.delete(*t_ob.get_children())
        for n in cfg.get("obras") or []:
            t_ob.insert("", "end", values=(n,))
        recalcular()

    v_conta_inv.trace_add("write", escolheu_conta_inv)

    # ------------------------------------------------- conta / pessoa física
    f_ent = ttk.Frame(area)
    v_conta = tk.StringVar()
    v_oficial = tk.StringVar()
    v_exibicao = tk.StringVar()
    v_apelido = tk.StringVar()
    campo_conta = widgets.Campo(
        f_ent, "Conta no Mais Controle (as que ainda não estão na lista)",
        lambda p: widgets.ComboBusca(p, width=72, textvariable=v_conta))
    campo_conta.pack(anchor="w", fill="x", pady=(0, 10))
    cb_conta = campo_conta.widget
    cb_conta.definir_valores(livres)
    for rotulo, var in (
            ("Nome do cliente no Mais Controle", v_oficial),
            ("Nome na lista de Pagou / Recebeu", v_exibicao),
            ("Apelido na descrição (opcional)", v_apelido)):
        widgets.Campo(f_ent, rotulo,
                      lambda p, v=var: ttk.Entry(p, textvariable=v, width=74)
                      ).pack(anchor="w", fill="x", pady=(0, 10))
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

    erro = ttk.Label(corpo, style="Erro.TLabel", wraplength=640,
                     justify="left", text="")
    erro.pack(anchor="w", pady=(8, 0))
    if not tem_erp:
        erro.configure(text="Não deu para ler aportadores e obras do Mais "
                            "Controle agora — a opção de subconta de "
                            "investidor fica desligada. Veja o Registro.")

    def trocou_tipo():
        f_inv.pack_forget()
        f_ent.pack_forget()
        if tipo.get() == INVESTIDOR:
            f_inv.pack(fill="both", expand=True)
        else:
            f_ent.pack(fill="both", expand=True)
            if tipo.get() == CONTA:
                campo_conta.pack(anchor="w", fill="x", pady=(0, 10),
                                 before=f_ent.winfo_children()[1])
            else:
                v_conta.set("")
                campo_conta.pack_forget()

    def cadastrar(_e=None):
        if tipo.get() == INVESTIDOR:
            conta = v_conta_inv.get().strip()
            if conta not in de_investidor:
                erro.configure(text="Escolha a conta na lista — ela precisa "
                                    "ter o nome exato do Mais Controle.")
                return
            inv = nc.Investidor(conta, v_dono.get().strip(), nomes_ap(),
                                [v[0] for _, v in _linhas(t_ob)], pesos_ap(),
                                nc.banco_da_conta(conta, contas))
            problema = nc.validar_investidor(inv, entidades,
                                             participantes=participantes,
                                             centros=centros)
            if problema:
                erro.configure(text=problema)
                return
            resultado.append((INVESTIDOR, inv))
        else:
            conta = v_conta.get().strip() if tipo.get() == CONTA else ""
            if tipo.get() == CONTA and conta not in livres:
                erro.configure(text="Escolha a conta na lista — ela precisa "
                                    "ter o nome exato do Mais Controle.")
                return
            novo = nc.Novo(v_exibicao.get(), v_oficial.get(), conta,
                           v_apelido.get())
            problema = nc.validar(novo, entidades)
            if problema:
                erro.configure(text=problema)
                return
            resultado.append(("entidade", novo))
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
    try:
        top.grab_set()
    except tk.TclError:
        pass
    pai.wait_window(top)
    return resultado[0] if resultado else None
