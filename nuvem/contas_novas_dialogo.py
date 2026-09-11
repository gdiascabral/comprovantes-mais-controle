# -*- coding: utf-8 -*-
"""A janela que pergunta o que fazer com a conta nova do ERP.

Separada da regra (`nuvem/contas_novas.py`) pelo motivo de sempre neste
projeto: a regra tem teste, a tela não. Aqui só mora o que precisa de Tk — e
o que a janela devolve sai de `escolhas_marcadas`, que é função e tem teste.

Ela não é um sim/não. O ERP diz o nome, o banco, a agência e o número; o nosso
cadastro exige EMPRESA e PASTA, que o ERP não tem como saber. Então cada conta
marcada precisa dessas duas respostas — e marcada sem elas não é gravada, com
o motivo dito, em vez de virar erro de SQL cru na cara de quem só queria
responder "sim".

**É LISTA + DETALHE, e o rodapé fica fora da lista** (11/09/2026). A primeira
versão empilhava as contas direto na moldura: com 21 contas novas de uma vez a
janela passou da altura da tela e o "Cadastrar" ficou abaixo da borda. A
segunda pôs cada conta num bloco de widgets (caixa, rótulo, menu da empresa,
campo da pasta) dentro de um Canvas rolável — e o Canvas recalcula a
geometria de todos os blocos a cada um que entra: medido com a janela fora da
tela, os blocos das mesmas 21 contas custavam 0,15 s num frame comum e 1,45 s
dentro do Canvas, e a janela levava 2,2 s para aparecer na abertura do app.
Hoje é UMA tabela (marca, conta, o que veio do ERP, empresa, pasta) e,
embaixo, a empresa e a pasta da conta SELECIONADA — os mesmos widgets com 3
contas ou com 300. Cabeçalho, editor e rodapé entram no `pack` ANTES da
tabela (no `pack`, quem entra por último é quem encolhe), e ela nasce com as
linhas que cabem em `FRACAO_DA_TELA` da altura da tela.

**A roda do mouse nunca escolhe empresa.** O Tk liga a roda ao `TCombobox`
(`ttk::bindMouseWheel TCombobox`): rolando com o ponteiro sobre um menu, a
empresa daquela conta trocava em silêncio — foi assim que uma conta de pessoa
física apareceu escolhida para uma SPE. O menu do editor desvia a roda para a
lista e devolve "break", que impede a ligação da classe de rodar.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import widgets

import util

log = util.log(__name__)

#: A janela nunca passa desta fração da altura da tela.
FRACAO_DA_TELA = 0.85

#: A marca da primeira coluna — os mesmos símbolos do Baixar Comprovantes.
#: Símbolo, e não caixa de marcar: o Treeview não aceita widget na célula.
MARCADA = "☑"
DESMARCADA = "☐"


def _barra(top) -> None:
    if widgets is not None and hasattr(widgets, "barra_de_titulo"):
        try:
            widgets.barra_de_titulo(top)
        except Exception:
            log.warning("aplicando a barra de título na janela de contas "
                        "novas", exc_info=True)


def _passos_da_roda(delta: int) -> int:
    """Quantas linhas rolar num `<MouseWheel>`.

    O Windows manda múltiplos de 120 por dente da roda; o touchpad manda
    menos, e `delta // 120` daria 0 para cima e -1 para baixo — a lista
    andaria num sentido só."""
    passos = -int(delta / 120)
    if passos == 0 and delta:
        passos = -1 if delta > 0 else 1
    return passos


def escolhas_marcadas(linhas, por_nome) -> list[dict]:
    """O que vai para o cadastro: só as contas MARCADAS.

    `linhas` é `[(conta, marcada, nome da empresa, pasta)]`, o estado da
    janela; `por_nome` é `{nome da empresa: id}`. Marcada sem empresa sai com
    `empresa_id` None — quem grava recusa com o motivo dito (ver o docstring
    do módulo), e não este dicionário."""
    return [{"nome_erp": conta.nome,
             "empresa_id": por_nome.get(empresa),
             "pasta": pasta,
             "banco": conta.banco,
             "agencia": conta.agencia,
             "numero": conta.numero}
            for conta, marcada, empresa, pasta in linhas if marcada]


def perguntar(pai, novas, empresas) -> list[dict]:
    """Mostra as contas novas e devolve as escolhas.

    `novas` são `contas_novas.ContaNova`; `empresas` é `[(id, nome)]`.
    Devolve `[{nome_erp, empresa_id, pasta, banco, agencia, numero}]` — só as
    marcadas. Fechar ou cancelar devolve `[]`.
    """
    top = tk.Toplevel(pai)
    top.withdraw()                  # monta escondida; aparece já no tamanho
    top.title("Contas novas no Mais Controle")
    top.transient(pai)
    _barra(top)

    nomes_empresa = [nome for _id, nome in empresas]
    por_nome = {nome: ident for ident, nome in empresas}
    #: O estado da janela, uma entrada por conta: [conta, marcada, empresa,
    #: pasta]. A tabela só o MOSTRA; é daqui que `escolhas_marcadas` lê.
    linhas = []
    for conta in novas:
        sugerida = ""
        if hasattr(conta, "empresa_sugerida"):
            sugerida = conta.empresa_sugerida(nomes_empresa)
        # A pasta nasce com a sugestão, para ser corrigida e não digitada; e
        # quem já vem com empresa sugerida chega marcada.
        linhas.append([conta, bool(sugerida), sugerida,
                       getattr(conta, "pasta_sugerida", "")])

    cabeca = ttk.Frame(top, padding=(14, 14, 14, 6))
    cabeca.pack(side="top", fill="x")
    ttk.Label(cabeca, style="Secao.TLabel",
              text=f"{len(novas)} conta(s) nova(s) no Mais Controle").pack(anchor="w")
    ttk.Label(cabeca, style="Apoio.TLabel", wraplength=640, justify="left",
              text="Elas existem no ERP e não estão no cadastro do app. Marque "
                   f"as que devem entrar nas automações (clique na marca "
                   f"{DESMARCADA}, ou tecle Espaço) e diga a empresa e a pasta "
                   "de cada uma, embaixo da lista. As que já vêm com a empresa "
                   "sugerida chegam marcadas — confira antes de cadastrar. O "
                   "que ficar desmarcado não é gravado, e volta a aparecer na "
                   "próxima abertura."
              ).pack(anchor="w", pady=(0, 6))

    todas = tk.BooleanVar(value=False)
    ttk.Checkbutton(cabeca, variable=todas, text="Marcar todas",
                    command=lambda: marcar(range(len(linhas)), todas.get())
                    ).pack(anchor="w")

    # O rodapé e o editor entram no `pack` ANTES da lista: é ela que encolhe
    # quando a tela não dá, e os botões ficam sempre à vista.
    rodape = ttk.Frame(top, padding=(14, 8, 14, 14))
    rodape.pack(side="bottom", fill="x")
    editor = ttk.Frame(top, padding=(14, 10, 14, 0))
    editor.pack(side="bottom", fill="x")

    corpo = ttk.Frame(top)
    corpo.pack(side="top", fill="both", expand=True, padx=14)
    tabela = ttk.Treeview(corpo, columns=("marca", "conta", "erp", "empresa",
                                          "pasta"),
                          show="headings", selectmode="browse",
                          height=max(1, min(len(linhas), 12)))
    for col, titulo, largura, ancora in (("marca", "", 34, "center"),
                                         ("conta", "CONTA NO ERP", 300, "w"),
                                         ("erp", "VINDOS DO ERP", 210, "w"),
                                         ("empresa", "EMPRESA", 210, "w"),
                                         ("pasta", "PASTA", 230, "w")):
        tabela.heading(col, text=titulo)
        tabela.column(col, width=largura, anchor=ancora, stretch=col == "conta")
    # O cabeçalho da marca é o "todas", como no Baixar Comprovantes: coluna
    # que já tem comando o `estilo_tabela` não troca por uma ordenação.
    tabela.heading("marca", text=MARCADA,
                   command=lambda: marcar(range(len(linhas)),
                                          not all(ln[1] for ln in linhas)))
    widgets.estilo_tabela(tabela)
    barra = ttk.Scrollbar(corpo, orient="vertical", command=tabela.yview)
    tabela.configure(yscrollcommand=barra.set)
    barra.pack(side="right", fill="y")
    tabela.pack(side="left", fill="both", expand=True)
    for k, (conta, marcada, empresa, pasta) in enumerate(linhas):
        tabela.insert("", "end", iid=str(k), tags=widgets.linha_zebrada(k),
                      values=(MARCADA if marcada else DESMARCADA, conta.nome,
                              getattr(conta, "resumo", "") or "—",
                              empresa or "—", pasta))

    # ---- o editor: empresa e pasta da conta SELECIONADA
    selecionada = ttk.Label(editor, style="Forte.TLabel")
    selecionada.pack(anchor="w")
    campos = ttk.Frame(editor)
    campos.pack(anchor="w", pady=(4, 0))
    ttk.Label(campos, text="empresa:").pack(side="left")
    v_empresa = tk.StringVar(top)
    empresa = ttk.Combobox(campos, textvariable=v_empresa, values=nomes_empresa,
                           width=28, state="readonly")
    empresa.pack(side="left", padx=(4, 12))
    ttk.Label(campos, text="pasta:").pack(side="left")
    v_pasta = tk.StringVar(top)
    ttk.Entry(campos, textvariable=v_pasta, width=34).pack(side="left",
                                                          padx=(4, 0))

    def rolar(evento):
        tabela.yview_scroll(_passos_da_roda(evento.delta), "units")
        return "break"

    # Antes da ligação da CLASSE, que trocaria a empresa da conta selecionada
    # (ver docstring). Sobre a tabela a roda já rola sozinha.
    empresa.bind("<MouseWheel>", rolar)

    #: A conta que está no editor. Fica None enquanto ele é recarregado: sem
    #: a trava, pôr nos campos os dados da conta nova escreveria na anterior.
    atual = {"k": None}

    def mostrar(_e=None):
        foco = tabela.focus()
        if not foco:
            return
        k = int(foco)
        atual["k"] = None
        conta, _marcada, emp, pas = linhas[k]
        selecionada.configure(text=conta.nome)
        v_empresa.set(emp)
        v_pasta.set(pas)
        atual["k"] = k

    def escreveu(*_a):
        k = atual["k"]
        if k is None:
            return
        linhas[k][2] = v_empresa.get()
        linhas[k][3] = v_pasta.get()
        tabela.set(str(k), "empresa", linhas[k][2] or "—")
        tabela.set(str(k), "pasta", linhas[k][3])

    v_empresa.trace_add("write", escreveu)
    v_pasta.trace_add("write", escreveu)
    tabela.bind("<<TreeviewSelect>>", mostrar)

    def marcar(ks, valor):
        for k in ks:
            linhas[k][1] = bool(valor)
            tabela.set(str(k), "marca", MARCADA if valor else DESMARCADA)

    def clicou(evento):
        """Só a coluna da marca alterna; clique no resto seleciona a conta e
        a leva para o editor."""
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
    # O mesmo caminho do Espaço, por evento virtual: é por ele que o teste
    # marca, com a janela retirada e sem foco para receber tecla.
    tabela.bind("<<AlternarMarca>>", espaco)

    escolhas: list[dict] = []

    def confirmar():
        escolhas.extend(escolhas_marcadas(linhas, por_nome))
        top.destroy()

    ttk.Button(rodape, text="Agora não", command=top.destroy).pack(side="right")
    botao = ttk.Button(rodape, text="Cadastrar", command=confirmar)
    botao.pack(side="right", padx=(0, 8))
    try:
        botao.configure(style="Accent.TButton")
    except tk.TclError:
        pass

    if linhas:
        tabela.selection_set("0")
        tabela.focus("0")
        mostrar()

    # A lista inteira quando cabe; senão, o que a tela deixar — e a barra
    # de rolagem faz o resto.
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
    # Uma linha a menos: é a altura do cabeçalho da tabela.
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
