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

**Desde 05/10/2026 a mesma janela também inclui contas no painel do Saldo de
pagamentos**, que tinha uma janela só dela: o ERP é a fonte das duas listas, e
duas janelas na abertura perguntavam a mesma coisa em dobro. Cada conta
(`contas_central.Pendencia`) diz onde falta — cadastro, painel ou os dois — e
a janela só deixa editar o que falta: empresa e pasta valem para o cadastro, a
"linha no painel" vale para o painel. Devolve `Respostas(cadastro, painel)`,
duas listas, porque quem grava cada uma é um código diferente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass
class Respostas:
    """O que a janela devolve: o que vai para o cadastro e o que vai para o
    painel do Saldo. `painel` é `[(conta, rotulo)]`."""
    cadastro: list = field(default_factory=list)
    painel: list = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.cadastro or self.painel)


def _falta_cadastro(conta) -> bool:
    # Leitura tolerante: objetos antigos (sem os campos novos) são só cadastro.
    return getattr(conta, "falta_cadastro", True)


def _falta_painel(conta) -> bool:
    return getattr(conta, "falta_painel", False)


def _rotulo(conta) -> str:
    return getattr(conta, "rotulo", conta.nome)


def escolhas_marcadas(linhas, por_nome) -> list[dict]:
    """O que vai para o cadastro: só as contas MARCADAS que faltam nele.

    `linhas` é `[(conta, marcada, nome da empresa, pasta, rotulo)]`, o estado
    da janela; `por_nome` é `{nome da empresa: id}`. Marcada sem empresa sai
    com `empresa_id` None — quem grava recusa com o motivo dito (ver o
    docstring do módulo), e não este dicionário. Conta que já está no cadastro
    e só falta no painel não volta para cá: gravaria em duplicidade."""
    return [{"nome_erp": conta.nome,
             "empresa_id": por_nome.get(empresa),
             "pasta": pasta,
             "banco": conta.banco,
             "agencia": conta.agencia,
             "numero": conta.numero}
            for conta, marcada, empresa, pasta, _rot in linhas
            if marcada and _falta_cadastro(conta)]


def painel_marcadas(linhas) -> list[tuple]:
    """O que vai para o painel: `(conta, rotulo)` das MARCADAS que faltam
    nele. O rótulo é o nome da linha como o dono quer vê-la na planilha."""
    return [(conta, rotulo.strip())
            for conta, marcada, _empresa, _pasta, rotulo in linhas
            if marcada and _falta_painel(conta)]


def perguntar(pai, novas, empresas) -> Respostas:
    """Mostra as contas que faltam e devolve as respostas.

    `novas` são `contas_central.Pendencia`; `empresas` é `[(id, nome)]`.
    `Respostas.cadastro` é `[{nome_erp, empresa_id, pasta, banco, agencia,
    numero}]` e `Respostas.painel` é `[(conta, rotulo)]` — só as marcadas.
    Fechar ou cancelar devolve as duas vazias.
    """
    top = tk.Toplevel(pai)
    top.withdraw()                  # monta escondida; aparece já no tamanho
    top.title("Contas novas no Mais Controle")
    top.transient(pai)
    _barra(top)

    nomes_empresa = [nome for _id, nome in empresas]
    por_nome = {nome: ident for ident, nome in empresas}
    #: O estado da janela, uma entrada por conta: [conta, marcada, empresa,
    #: pasta, rotulo]. A tabela só o MOSTRA; é daqui que `escolhas_marcadas`
    #: e `painel_marcadas` leem.
    linhas = []
    for conta in novas:
        sugerida = ""
        if hasattr(conta, "empresa_sugerida"):
            sugerida = conta.empresa_sugerida(nomes_empresa)
        # A pasta nasce com a sugestão, para ser corrigida e não digitada; e
        # quem já vem com empresa sugerida chega marcada.
        linhas.append([conta, bool(sugerida), sugerida,
                       getattr(conta, "pasta_sugerida", ""), _rotulo(conta)])

    cabeca = ttk.Frame(top, padding=(14, 14, 14, 6))
    cabeca.pack(side="top", fill="x")
    ttk.Label(cabeca, style="Secao.TLabel",
              text=f"{len(novas)} conta(s) do Mais Controle faltando no app"
              ).pack(anchor="w")
    ttk.Label(cabeca, style="Apoio.TLabel", wraplength=640, justify="left",
              text="Elas existem no ERP e faltam no cadastro do app, no painel "
                   "do Saldo de pagamentos ou nos dois. Marque "
                   f"as que devem entrar nas automações (clique na marca "
                   f"{DESMARCADA}, ou tecle Espaço) e diga a empresa e a pasta "
                   "de cada uma, embaixo da lista. Quem falta no painel do Saldo "
                   "de pagamentos entra com o nome da linha que está embaixo da "
                   "lista. As que já vêm com a empresa "
                   "sugerida chegam marcadas — confira antes de incluir. O "
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
    tabela = ttk.Treeview(corpo, columns=("marca", "conta", "falta", "erp",
                                          "empresa", "pasta", "linha"),
                          show="headings", selectmode="browse",
                          height=max(1, min(len(linhas), 12)))
    for col, titulo, largura, ancora in (("marca", "", 34, "center"),
                                         ("conta", "CONTA NO ERP", 300, "w"),
                                         ("falta", "FALTA EM", 120, "w"),
                                         ("erp", "VINDOS DO ERP", 210, "w"),
                                         ("empresa", "EMPRESA", 210, "w"),
                                         ("pasta", "PASTA", 230, "w"),
                                         ("linha", "LINHA NO PAINEL", 190,
                                          "w")):
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
    def celulas(ln):
        """O que a tabela mostra de uma linha do estado."""
        conta, marcada, empresa, pasta, rotulo = ln
        cadastrada = not _falta_cadastro(conta)
        return (MARCADA if marcada else DESMARCADA, conta.nome,
                getattr(conta, "falta_em", "cadastro"),
                getattr(conta, "resumo", "") or "—",
                "já cadastrada" if cadastrada else (empresa or "—"),
                "já cadastrada" if cadastrada else pasta,
                rotulo if _falta_painel(conta) else "—")

    for k, ln in enumerate(linhas):
        tabela.insert("", "end", iid=str(k), tags=widgets.linha_zebrada(k),
                      values=celulas(ln))

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
    e_pasta = ttk.Entry(campos, textvariable=v_pasta, width=34)
    e_pasta.pack(side="left", padx=(4, 12))
    ttk.Label(campos, text="linha no painel:").pack(side="left")
    v_rotulo = tk.StringVar(top)
    e_rotulo = ttk.Entry(campos, textvariable=v_rotulo, width=34)
    e_rotulo.pack(side="left", padx=(4, 0))

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
        conta, _marcada, emp, pas, rot = linhas[k]
        selecionada.configure(text=conta.nome)
        v_empresa.set(emp)
        v_pasta.set(pas)
        v_rotulo.set(rot)
        # Só se edita o que falta: o que já existe no cadastro ou no painel
        # não é gravado de novo, e deixar digitar enganaria.
        no_cadastro = _falta_cadastro(conta)
        empresa.configure(state="readonly" if no_cadastro else "disabled")
        e_pasta.configure(state="normal" if no_cadastro else "disabled")
        e_rotulo.configure(state="normal" if _falta_painel(conta)
                           else "disabled")
        atual["k"] = k

    def escreveu(*_a):
        k = atual["k"]
        if k is None:
            return
        linhas[k][2] = v_empresa.get()
        linhas[k][3] = v_pasta.get()
        linhas[k][4] = v_rotulo.get()
        valores = celulas(linhas[k])
        for coluna, valor in (("empresa", valores[4]), ("pasta", valores[5]),
                              ("linha", valores[6])):
            tabela.set(str(k), coluna, valor)

    v_empresa.trace_add("write", escreveu)
    v_pasta.trace_add("write", escreveu)
    v_rotulo.trace_add("write", escreveu)
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

    respostas = Respostas()

    def confirmar():
        respostas.cadastro.extend(escolhas_marcadas(linhas, por_nome))
        respostas.painel.extend(painel_marcadas(linhas))
        top.destroy()

    ttk.Button(rodape, text="Agora não", command=top.destroy).pack(side="right")
    botao = ttk.Button(rodape, text="Incluir", command=confirmar)
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
    return respostas
