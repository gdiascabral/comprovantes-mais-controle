# -*- coding: utf-8 -*-
"""A janela que pergunta o que fazer com a conta nova do ERP.

Separada da regra (`nuvem/conferencia.py`) pelo motivo de sempre neste
projeto: a regra tem teste, a tela não. Aqui só mora o que precisa de Tk.

Ela não é um sim/não. O ERP diz o nome, o banco, a agência e o número; o nosso
cadastro exige EMPRESA e PASTA, que o ERP não tem como saber. Então cada conta
marcada precisa dessas duas respostas — e marcada sem elas não é gravada, com
o motivo dito, em vez de virar erro de SQL cru na cara de quem só queria
responder "sim".

**A lista ROLA, e o rodapé fica fora dela.** A primeira versão empilhava as
contas direto na moldura: com 21 contas novas de uma vez (11/09/2026) a janela
passou da altura da tela e o "Cadastrar" ficou abaixo da borda — não havia
como confirmar nem ver o resto. Hoje o cabeçalho e o rodapé são empacotados
ANTES da lista (no `pack`, quem entra por último é quem encolhe), a lista mora
num Canvas com barra, e a janela nasce no máximo com `FRACAO_DA_TELA` da
altura da tela.

**A roda do mouse nunca escolhe empresa.** O Tk liga a roda ao `TCombobox`
(`ttk::bindMouseWheel TCombobox`): rolando com o ponteiro sobre um menu, a
empresa daquela conta trocava em silêncio — foi assim que uma conta de pessoa
física apareceu escolhida para uma SPE. Cada menu desvia a roda para a lista
e devolve "break", que impede a ligação da classe de rodar.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import widgets

import util

log = util.log(__name__)

#: A janela nunca passa desta fração da altura da tela.
FRACAO_DA_TELA = 0.85


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


def perguntar(pai, novas, empresas) -> list[dict]:
    """Mostra as contas novas e devolve as escolhas.

    `novas` são `conferencia.ContaNova`; `empresas` é `[(id, nome)]`.
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
    linhas = []

    cabeca = ttk.Frame(top, padding=(14, 14, 14, 6))
    cabeca.pack(side="top", fill="x")
    ttk.Label(cabeca, style="Secao.TLabel",
              text=f"{len(novas)} conta(s) nova(s) no Mais Controle").pack(anchor="w")
    ttk.Label(cabeca, style="Apoio.TLabel", wraplength=640, justify="left",
              text="Elas existem no ERP e não estão no cadastro do app. Marque "
                   "as que devem entrar nas automações e diga a empresa e a "
                   "pasta de cada uma. As que já vêm com a empresa sugerida "
                   "chegam marcadas — confira antes de cadastrar. O que ficar "
                   "desmarcado não é gravado, e volta a aparecer na próxima "
                   "abertura."
              ).pack(anchor="w", pady=(0, 6))

    todas = tk.BooleanVar(value=False)

    def marcar_todas():
        for _conta, marcada, _empresa, _pasta in linhas:
            marcada.set(todas.get())

    ttk.Checkbutton(cabeca, variable=todas, text="Marcar todas",
                    command=marcar_todas).pack(anchor="w")

    # O rodapé entra no `pack` ANTES da lista: é ela que encolhe quando a
    # tela não dá, e os botões ficam sempre à vista.
    rodape = ttk.Frame(top, padding=(14, 8, 14, 14))
    rodape.pack(side="bottom", fill="x")

    corpo = ttk.Frame(top)
    corpo.pack(side="top", fill="both", expand=True, padx=(14, 4))
    canvas = tk.Canvas(corpo, highlightthickness=0, borderwidth=0)
    try:
        widgets.estilo_canvas(canvas)
    except Exception:
        log.warning("pintando o fundo da lista de contas novas", exc_info=True)
    barra = ttk.Scrollbar(corpo, orient="vertical", command=canvas.yview)
    lista = ttk.Frame(canvas)
    janela = canvas.create_window((0, 0), window=lista, anchor="nw")
    lista.bind("<Configure>", lambda _e: canvas.configure(
        scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(
        janela, width=e.width))
    canvas.configure(yscrollcommand=barra.set)
    barra.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)

    def rolar(evento):
        canvas.yview_scroll(_passos_da_roda(evento.delta), "units")
        return "break"

    # A marca da janela está nas bindtags de todo widget dentro dela: a roda
    # sobre um rótulo, uma caixa ou o fundo chega aqui.
    top.bind("<MouseWheel>", rolar)

    for conta in novas:
        bloco = ttk.Frame(lista)
        bloco.pack(fill="x", pady=(6, 0))

        sugerida = ""
        if hasattr(conta, "empresa_sugerida"):
            sugerida = conta.empresa_sugerida(nomes_empresa)
        marcada = tk.BooleanVar(value=bool(sugerida))
        ttk.Checkbutton(bloco, variable=marcada, text=conta.nome
                        ).pack(anchor="w")
        if conta.resumo:
            ttk.Label(bloco, style="Apoio.TLabel",
                      text=f"        {conta.resumo}   (vindos do ERP)"
                      ).pack(anchor="w")

        campos = ttk.Frame(bloco)
        campos.pack(anchor="w", padx=(24, 0), pady=(2, 0))
        ttk.Label(campos, text="empresa:").pack(side="left")
        empresa = ttk.Combobox(campos, values=nomes_empresa, width=28,
                               state="readonly")
        empresa.pack(side="left", padx=(4, 12))
        if sugerida:
            empresa.set(sugerida)
        # Antes da ligação da CLASSE, que trocaria a empresa (ver docstring).
        empresa.bind("<MouseWheel>", rolar)
        ttk.Label(campos, text="pasta:").pack(side="left")
        pasta = ttk.Entry(campos, width=34)
        pasta.pack(side="left", padx=(4, 0))
        # Nasce preenchida com a sugestão, para ser corrigida e não digitada.
        pasta.insert(0, getattr(conta, "pasta_sugerida", ""))

        linhas.append((conta, marcada, empresa, pasta))

    escolhas: list[dict] = []

    def confirmar():
        for conta, marcada, empresa, pasta in linhas:
            if not marcada.get():
                continue
            escolhas.append({
                "nome_erp": conta.nome,
                "empresa_id": por_nome.get(empresa.get()),
                "pasta": pasta.get(),
                "banco": conta.banco,
                "agencia": conta.agencia,
                "numero": conta.numero,
            })
        top.destroy()

    ttk.Button(rodape, text="Agora não", command=top.destroy).pack(side="right")
    botao = ttk.Button(rodape, text="Cadastrar", command=confirmar)
    botao.pack(side="right", padx=(0, 8))
    try:
        botao.configure(style="Accent.TButton")
    except tk.TclError:
        pass

    # A lista inteira quando cabe; senão, o que a tela deixar — e a barra
    # de rolagem faz o resto.
    top.update_idletasks()
    tela = top.winfo_screenheight()
    fixo = cabeca.winfo_reqheight() + rodape.winfo_reqheight()
    altura = min(lista.winfo_reqheight(),
                 max(120, int(tela * FRACAO_DA_TELA) - fixo))
    canvas.configure(width=lista.winfo_reqwidth(), height=altura)
    top.update_idletasks()
    x = max(0, (top.winfo_screenwidth() - top.winfo_reqwidth()) // 2)
    y = max(0, (tela - top.winfo_reqheight()) // 2 - 20)
    top.geometry(f"+{x}+{y}")
    top.deiconify()

    top.protocol("WM_DELETE_WINDOW", top.destroy)
    top.bind("<Escape>", lambda _e: top.destroy())
    try:
        top.grab_set()
        top.focus_set()
    except tk.TclError:
        pass
    pai.wait_window(top)
    return escolhas
