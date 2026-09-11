# -*- coding: utf-8 -*-
"""A janela "Contas do ERP fora do painel", da aba Saldo de pagamentos.

Separada da regra (`conciliacao/painel_novas.py`) pelo motivo de sempre neste
projeto: a regra tem teste, a tela não. O que a janela devolve sai de
`inclusoes_marcadas`, que é função e tem teste.

É LISTA + DETALHE, como a janela de contas novas da abertura
(`nuvem/contas_novas_dialogo.py`): uma tabela com a marca, a conta do ERP, o
saldo e o nome que a linha terá, e embaixo o nome da conta SELECIONADA num
campo editável — os mesmos widgets com 3 contas ou com 30. Cabeçalho, editor
e rodapé entram no `pack` ANTES da tabela, para ela ser quem encolhe.

**Nada nasce marcado.** A lista mistura as contas que o dono quer no painel
com contas de pessoa física que ele não quer, e incluir é mexer no modelo:
quem decide é o clique, não uma sugestão.

**"Incluir" confere antes de fechar.** Os problemas (nome repetido, curinga
que o SUMIF leria, conta já no painel) aparecem de uma vez e a janela
continua aberta com o que já foi marcado e digitado — fechar para mostrar o
erro faria perder tudo isso.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import util
import widgets

from .painel_novas import Inclusao, rotulo_sugerido
from .parsing import format_brl

log = util.log(__name__)

px = widgets.px

#: A janela nunca passa desta fração da altura da tela.
FRACAO_DA_TELA = 0.85

MARCADA = "☑"
DESMARCADA = "☐"


def inclusoes_marcadas(linhas) -> list[Inclusao]:
    """O que vai para o painel: só as linhas MARCADAS, com o nome digitado.

    `linhas` é `[[conta, marcada, rotulo]]`, o estado da janela."""
    return [Inclusao(conta, (rotulo or "").strip())
            for conta, marcada, rotulo in linhas if marcada]


def perguntar(pai, fora, conferir, *, primeira_linha: int) -> list[Inclusao]:
    """Mostra as contas fora do painel e devolve as que devem entrar.

    `fora` são `ErpAccount`; `conferir(inclusoes) -> list[str]` devolve os
    problemas (vazio = pode); `primeira_linha` é onde a primeira nova entra,
    só para a frase do rodapé. Fechar ou cancelar devolve `[]`."""
    top = tk.Toplevel(pai)
    top.withdraw()                  # monta escondida; aparece já no tamanho
    top.title("Contas do Mais Controle fora do painel")
    top.transient(pai)
    try:
        widgets.barra_de_titulo(top)
    except Exception:
        log.warning("aplicando a barra de título na janela de contas fora do "
                    "painel", exc_info=True)

    #: Estado da janela, uma entrada por conta: [conta, marcada, rotulo].
    linhas = [[conta, False, rotulo_sugerido(conta)] for conta in fora]

    cabeca = ttk.Frame(top, padding=(14, 14, 14, 6))
    cabeca.pack(side="top", fill="x")
    ttk.Label(cabeca, style="Secao.TLabel",
              text=f"{len(fora)} conta(s) do Mais Controle fora do painel"
              ).pack(anchor="w")
    ttk.Label(cabeca, style="Apoio.TLabel", wraplength=px(700), justify="left",
              text="Elas existem no ERP e não têm linha no MODELO.xlsx, então "
                   "os pagamentos delas ficam fora do painel do dia. Marque as "
                   f"que devem entrar (clique na marca {DESMARCADA}, ou tecle "
                   "Espaço) e confira o nome que a linha terá na coluna B — "
                   "é por ele que a aba Regras diz quem aporta. As linhas novas "
                   "entram no fim do painel, e o app guarda uma cópia dos "
                   "arquivos de antes. As desmarcadas continuam fora, e "
                   "continuam no aviso do resumo."
              ).pack(anchor="w", pady=(0, 6))

    rodape = ttk.Frame(top, padding=(14, 8, 14, 14))
    rodape.pack(side="bottom", fill="x")
    editor = ttk.Frame(top, padding=(14, 10, 14, 0))
    editor.pack(side="bottom", fill="x")

    corpo = ttk.Frame(top)
    corpo.pack(side="top", fill="both", expand=True, padx=14)
    tabela = ttk.Treeview(corpo, columns=("marca", "conta", "saldo", "rotulo"),
                          show="headings", selectmode="browse",
                          height=max(1, min(len(linhas), 12)))
    for col, titulo, largura, ancora in (("marca", "", 34, "center"),
                                         ("conta", "CONTA NO ERP", 360, "w"),
                                         ("saldo", "SALDO", 120, "e"),
                                         ("rotulo", "NOME NA LINHA DO PAINEL",
                                          360, "w")):
        tabela.heading(col, text=titulo)
        tabela.column(col, width=largura, anchor=ancora,
                      stretch=col in ("conta", "rotulo"))
    tabela.heading("marca", text=MARCADA,
                   command=lambda: marcar(range(len(linhas)),
                                          not all(ln[1] for ln in linhas)))
    widgets.estilo_tabela(tabela)
    barra = ttk.Scrollbar(corpo, orient="vertical", command=tabela.yview)
    tabela.configure(yscrollcommand=barra.set)
    barra.pack(side="right", fill="y")
    tabela.pack(side="left", fill="both", expand=True)
    for k, (conta, marcada, rotulo) in enumerate(linhas):
        tabela.insert("", "end", iid=str(k), tags=widgets.linha_zebrada(k),
                      values=(DESMARCADA, conta.name, format_brl(conta.balance),
                              rotulo))

    # ---- o editor: o nome da linha da conta SELECIONADA
    selecionada = ttk.Label(editor, style="Forte.TLabel")
    selecionada.pack(anchor="w")
    campos = ttk.Frame(editor)
    campos.pack(anchor="w", fill="x", pady=(4, 0))
    ttk.Label(campos, text="nome na linha do painel (coluna B):").pack(side="left")
    v_rotulo = tk.StringVar(top)
    ttk.Entry(campos, textvariable=v_rotulo, width=60).pack(
        side="left", padx=(6, 0), fill="x", expand=True)

    resumo = ttk.Label(rodape, style="Apoio.TLabel")
    resumo.pack(side="left")

    #: A conta que está no editor. None enquanto ele é recarregado: sem a
    #: trava, pôr no campo o nome da conta nova escreveria na anterior.
    atual = {"k": None}

    def contar():
        marcadas = sum(1 for ln in linhas if ln[1])
        if not marcadas:
            resumo.configure(text="nenhuma marcada")
        elif marcadas == 1:
            resumo.configure(text=f"1 marcada → linha {primeira_linha}")
        else:
            resumo.configure(text=f"{marcadas} marcadas → linhas {primeira_linha} "
                                  f"a {primeira_linha + marcadas - 1}")

    def mostrar(_e=None):
        foco = tabela.focus()
        if not foco:
            return
        k = int(foco)
        atual["k"] = None
        selecionada.configure(text=linhas[k][0].name)
        v_rotulo.set(linhas[k][2])
        atual["k"] = k

    def escreveu(*_a):
        k = atual["k"]
        if k is None:
            return
        linhas[k][2] = v_rotulo.get()
        tabela.set(str(k), "rotulo", linhas[k][2])

    v_rotulo.trace_add("write", escreveu)
    tabela.bind("<<TreeviewSelect>>", mostrar)

    def marcar(ks, valor):
        for k in ks:
            linhas[k][1] = bool(valor)
            tabela.set(str(k), "marca", MARCADA if valor else DESMARCADA)
        contar()

    def clicou(evento):
        """Só a coluna da marca alterna; clique no resto seleciona a conta."""
        if (tabela.identify_region(evento.x, evento.y) == "cell"
                and tabela.identify_column(evento.x) == "#1"):
            linha = tabela.identify_row(evento.y)
            if linha:
                marcar([int(linha)], not linhas[int(linha)][1])

    def espaco(_e=None):
        for linha in tabela.selection():
            marcar([int(linha)], not linhas[int(linha)][1])
        return "break"

    tabela.bind("<Button-1>", clicou)
    tabela.bind("<space>", espaco)
    tabela.bind("<<AlternarMarca>>", espaco)

    escolhas: list[Inclusao] = []

    def confirmar():
        marcadas = inclusoes_marcadas(linhas)
        problemas = conferir(marcadas)
        if problemas:
            messagebox.showwarning(
                "Ainda não dá para incluir",
                "Corrija antes de incluir:\n\n" + "\n".join(
                    f"• {p}" for p in problemas),
                parent=top)
            return
        escolhas.extend(marcadas)
        top.destroy()

    ttk.Button(rodape, text="Fechar", command=top.destroy).pack(side="right")
    botao = ttk.Button(rodape, text="Incluir no painel", command=confirmar)
    botao.pack(side="right", padx=(0, 8))
    try:
        botao.configure(style="Accent.TButton")
    except tk.TclError:
        pass

    contar()
    if linhas:
        tabela.selection_set("0")
        tabela.focus("0")
        mostrar()

    top.update_idletasks()
    tela = top.winfo_screenheight()
    fixo = (cabeca.winfo_reqheight() + editor.winfo_reqheight()
            + rodape.winfo_reqheight())
    try:
        altura_linha = int(ttk.Style().lookup(str(tabela.cget("style")),
                                              "rowheight") or 0)
    except (tk.TclError, ValueError):
        altura_linha = 0
    altura_linha = altura_linha or 24
    cabem = max(3, (int(tela * FRACAO_DA_TELA) - fixo) // altura_linha - 1)
    tabela.configure(height=max(1, min(len(linhas), cabem)))
    top.update_idletasks()
    x = max(0, (top.winfo_screenwidth() - top.winfo_reqwidth()) // 2)
    y = max(0, (tela - top.winfo_reqheight()) // 2 - 20)
    top.geometry(f"+{x}+{y}")
    top.deiconify()

    top.protocol("WM_DELETE_WINDOW", top.destroy)
    top.bind("<Escape>", lambda _e: top.destroy())
    try:
        top.grab_set()
        tabela.focus_set()
    except tk.TclError:
        pass
    pai.wait_window(top)
    return escolhas
