# -*- coding: utf-8 -*-
"""A janela do botão "Cadastros" da aba Aportes: ver e corrigir.

Duas abas, como o dono aprovou em 21/10/2026: "Empresas e pessoas" (toda a
lista de Pagou/Recebeu, com busca) e "Subcontas de investidor" (rateio, obras
e dono, com aviso quando algo destoa). Corrigir abre uma janelinha com os
quatro campos; não existe apagar.

Só Tk. A regra está em `cadastros.py`, que tem teste; quem grava é a aba, por
`gravar(antes, mudancas, pronto)`, porque é ela que tem a thread de fundo e o
recado de erro. Devolve `("rateio", conta)` quando a pessoa pede para editar
o rateio de uma subconta (a aba abre o Novo cadastro nela) ou None.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import util
import widgets

from . import cadastros as cad

log = util.log(__name__)


def _tabela(pai, colunas, altura=12):
    t = ttk.Treeview(pai, columns=[c for c, _, _ in colunas], show="headings",
                     height=altura, selectmode="browse")
    for chave, titulo, largura in colunas:
        t.heading(chave, text=titulo)
        t.column(chave, width=largura, anchor="w", stretch=True)
    widgets.estilo_tabela(t)
    return t


def _janela(pai, titulo):
    top = tk.Toplevel(pai)
    top.withdraw()
    top.title(titulo)
    top.transient(pai)
    try:
        widgets.barra_de_titulo(top)
    except Exception:
        log.warning("barra de título de %s", titulo, exc_info=True)
    return top


def _mostrar(top, pai):
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


def corrigir(pai, entidade, *, so_dono, entidades, rateios, contas,
             participantes, em_uso):
    """A janelinha de correção. Devolve as mudanças (dict) ou None."""
    top = _janela(pai, "Corrigir cadastro")
    corpo = ttk.Frame(top, padding=16)
    corpo.pack(fill="both", expand=True)
    ttk.Label(corpo, style="Secao.TLabel",
              text="Corrigir subconta" if so_dono else "Corrigir cadastro"
              ).pack(anchor="w")
    ttk.Label(corpo, style="Apoio.TLabel", wraplength=560, justify="left",
              text=("Na subconta só o dono muda: o nome segue o padrão e a "
                    "conta é a própria subconta." if so_dono else
                    "Conta vazia = pessoa física que só aparece como contato.")
              ).pack(anchor="w", pady=(2, 10))

    vs = {c: tk.StringVar(value=str(entidade.get(c) or "")) for c in cad.COLUNAS}
    campos = {}
    for coluna, rotulo, fabrica in (
            ("nome_exibicao", "Nome na lista de Pagou / Recebeu",
             lambda p: ttk.Entry(p, textvariable=vs["nome_exibicao"], width=66)),
            ("nome_oficial", "Nome no ERP (contato)",
             lambda p: widgets.ComboBusca(p, width=64,
                                          textvariable=vs["nome_oficial"])),
            ("conta", "Conta no Mais Controle",
             lambda p: widgets.ComboBusca(p, width=64,
                                          textvariable=vs["conta"])),
            ("nome_descricao", "Apelido na descrição (opcional)",
             lambda p: ttk.Entry(p, textvariable=vs["nome_descricao"],
                                 width=66))):
        campo = widgets.Campo(corpo, rotulo, fabrica)
        campo.pack(anchor="w", fill="x", pady=(0, 10))
        campos[coluna] = campo.widget
    campos["nome_oficial"].definir_valores(
        sorted({str(p).strip() for p in participantes or []} - {""},
               key=util.norm_espaco)
        or sorted({str(e.get("nome_oficial") or "").strip()
                   for e in entidades} - {""}, key=util.norm_espaco))
    campos["conta"].definir_valores(
        sorted({str(c.get("nome_erp") or "").strip() for c in contas} - {""},
               key=util.norm_espaco))
    if so_dono:
        for coluna in ("nome_exibicao", "conta", "nome_descricao"):
            campos[coluna].configure(state="disabled")

    ttk.Label(corpo, style="Apoio.TLabel", wraplength=560, justify="left",
              text="Fica registrado quem corrigiu, quando, o antes e o depois. "
                   "Não existe apagar aqui.").pack(anchor="w", pady=(4, 0))
    erro = ttk.Label(corpo, style="Erro.TLabel", wraplength=560,
                     justify="left", text="")
    erro.pack(anchor="w", pady=(6, 0))
    resultado: list = []

    def salvar(_e=None):
        depois = {c: v.get() for c, v in vs.items()}
        problema = cad.validar(entidade, depois, entidades, rateios,
                               contas=contas, participantes=participantes)
        if problema:
            erro.configure(text=problema)
            return
        if em_uso(entidade):
            erro.configure(
                text=f"\"{entidade['nome_exibicao']}\" está na lista \"A "
                     "lançar\". Lance ou tire da lista antes de corrigir — "
                     "corrigir no meio pode lançar o aporte em dobro ou no "
                     "lugar errado.")
            return
        resultado.append(cad.mudancas(entidade, depois))
        top.destroy()

    rodape = ttk.Frame(corpo)
    rodape.pack(fill="x", pady=(14, 0))
    ttk.Button(rodape, text="Cancelar", command=top.destroy).pack(side="right")
    botao = ttk.Button(rodape, text="Salvar correção", command=salvar)
    botao.pack(side="right", padx=(0, 8))
    try:
        botao.configure(style="Accent.TButton")
    except tk.TclError:
        pass
    _mostrar(top, pai)
    if isinstance(pai, tk.Toplevel) and pai.winfo_exists():
        try:
            pai.grab_set()    # a janela Cadastros volta a ser a modal
        except tk.TclError:
            pass
    return resultado[0] if resultado else None


def abrir(pai, *, entidades, rateios, contas, participantes, gravar, em_uso):
    """A janela Cadastros. `gravar(antes, mudancas, pronto)` grava em fundo e
    chama `pronto(entidades_novas)` quando o banco aceitou."""
    top = _janela(pai, "Cadastros — Aportes")
    estado = {"entidades": list(entidades)}
    resultado: list = []

    corpo = ttk.Frame(top, padding=16)
    corpo.pack(fill="both", expand=True)
    ttk.Label(corpo, style="Secao.TLabel",
              text="Quem paga ou recebe aportes").pack(anchor="w")
    ttk.Label(corpo, style="Apoio.TLabel", wraplength=860, justify="left",
              text="Como está no banco agora, em todos os computadores. "
                   "Dois cliques numa linha para corrigir."
              ).pack(anchor="w", pady=(2, 10))

    abas = ttk.Notebook(corpo)
    abas.pack(fill="both", expand=True)

    # ------------------------------------------------- empresas e pessoas
    f_emp = ttk.Frame(abas, padding=(0, 8, 0, 0))
    v_busca = tk.StringVar()
    widgets.Campo(f_emp, "Procurar por nome, contato ou conta",
                  lambda p: ttk.Entry(p, textvariable=v_busca, width=60)
                  ).pack(anchor="w", pady=(0, 8))
    t_emp = _tabela(f_emp, [("n", "NOME NA LISTA", 250),
                            ("o", "NOME NO ERP (CONTATO)", 250),
                            ("c", "CONTA", 280), ("a", "APELIDO", 110)])
    t_emp.pack(fill="both", expand=True)

    # -------------------------------------------- subcontas de investidor
    f_sub = ttk.Frame(abas, padding=(0, 8, 0, 0))
    t_sub = _tabela(f_sub, [("n", "SUBCONTA", 90),
                            ("a", "APORTADORES", 260),
                            ("o", "OBRAS (DIVIDE IGUAL)", 230),
                            ("d", "DONO NO ERP", 200),
                            ("v", "AVISO", 150)])
    t_sub.pack(fill="both", expand=True)
    ttk.Label(f_sub, style="Apoio.TLabel", wraplength=860, justify="left",
              text="⚠ quando o dono destoa das outras subcontas, a obra está "
                   "\"A CLASSIFICAR\" ou a subconta não tem conta em "
                   "Pagou/Recebeu.").pack(anchor="w", pady=(6, 0))

    abas.add(f_emp, text="Empresas e pessoas")
    abas.add(f_sub, text="Subcontas de investidor")

    linhas_emp: dict = {}
    linhas_sub: dict = {}

    def preencher(*_a):
        ents = estado["entidades"]
        lista = cad.empresas(ents, rateios)
        busca = v_busca.get().strip()
        if busca:
            lista = util.filtrar(lista, busca, chave=lambda e: " ".join(
                str(e.get(c) or "") for c in cad.COLUNAS))
        t_emp.delete(*t_emp.get_children())
        linhas_emp.clear()
        for i, e in enumerate(lista):
            item = t_emp.insert("", "end", tags=widgets.linha_zebrada(i), values=(
                e["nome_exibicao"], e.get("nome_oficial") or "",
                e.get("conta") or "— sem conta —", e.get("nome_descricao") or ""))
            linhas_emp[item] = e
        t_sub.delete(*t_sub.get_children())
        linhas_sub.clear()
        subs = cad.subcontas(ents, rateios)
        for i, s in enumerate(subs):
            aviso = "; ".join(s.avisos)
            item = t_sub.insert(
                "", "end",
                tags=widgets.linha_zebrada(i, "atencao" if aviso else ""),
                values=(s.numero, ", ".join(s.aportadores),
                        ", ".join(s.obras), s.dono or "—",
                        f"⚠ {aviso}" if aviso else ""))
            linhas_sub[item] = s
        abas.tab(f_emp, text=f"Empresas e pessoas ({len(cad.empresas(ents, rateios))})")
        abas.tab(f_sub, text=f"Subcontas de investidor ({len(subs)})")

    v_busca.trace_add("write", preencher)

    def depois_de_gravar(novas):
        estado["entidades"] = list(novas)
        if top.winfo_exists():          # pode ter sido fechada no meio
            preencher()

    def abrir_correcao(entidade, so_dono):
        mud = corrigir(top, entidade, so_dono=so_dono,
                       entidades=estado["entidades"], rateios=rateios,
                       contas=contas, participantes=participantes,
                       em_uso=em_uso)
        if mud:
            gravar(entidade, mud, depois_de_gravar)

    def corrigir_empresa(_e=None):
        sel = t_emp.selection()
        if not sel:
            messagebox.showinfo("Cadastros", "Escolha uma linha da lista.",
                                parent=top)
            return
        abrir_correcao(linhas_emp[sel[0]], so_dono=False)

    def subconta_escolhida():
        sel = t_sub.selection()
        if not sel:
            messagebox.showinfo("Cadastros", "Escolha uma subconta da lista.",
                                parent=top)
            return None
        return linhas_sub[sel[0]]

    def corrigir_dono(_e=None):
        s = subconta_escolhida()
        if s is None:
            return
        if s.entidade is None:
            messagebox.showinfo(
                "Cadastros", f"A subconta {s.numero} não tem conta em "
                "Pagou/Recebeu. Use Editar rateio para criá-la.", parent=top)
            return
        abrir_correcao(s.entidade, so_dono=True)

    def editar_rateio():
        s = subconta_escolhida()
        if s is None:
            return
        resultado.append(("rateio", (s.entidade or {}).get("conta") or ""))
        top.destroy()

    t_emp.bind("<Double-1>", corrigir_empresa)
    t_sub.bind("<Double-1>", corrigir_dono)

    rodape = ttk.Frame(corpo)
    rodape.pack(fill="x", pady=(14, 0))
    ttk.Button(rodape, text="Fechar", command=top.destroy).pack(side="right")
    b_corrigir = ttk.Button(rodape, text="Corrigir", command=corrigir_empresa)
    b_dono = ttk.Button(rodape, text="Corrigir dono", command=corrigir_dono)
    b_rateio = ttk.Button(rodape, text="Editar rateio", command=editar_rateio)
    try:
        b_corrigir.configure(style="Accent.TButton")
        b_rateio.configure(style="Accent.TButton")
    except tk.TclError:
        pass

    def trocou_aba(_e=None):
        for b in (b_corrigir, b_dono, b_rateio):
            b.pack_forget()
        if abas.index(abas.select()) == 0:
            b_corrigir.pack(side="right", padx=(0, 8))
        else:
            b_rateio.pack(side="right", padx=(0, 8))
            b_dono.pack(side="right", padx=(0, 8))

    abas.bind("<<NotebookTabChanged>>", trocou_aba)
    preencher()
    trocou_aba()
    _mostrar(top, pai)
    return resultado[0] if resultado else None
