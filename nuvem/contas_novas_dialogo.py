# -*- coding: utf-8 -*-
"""A janela que pergunta o que fazer com a conta nova do ERP.

Separada da regra (`nuvem/conferencia.py`) pelo motivo de sempre neste
projeto: a regra tem teste, a tela não. Aqui só mora o que precisa de Tk.

Ela não é um sim/não. O ERP diz o nome, o banco, a agência e o número; o nosso
cadastro exige EMPRESA e PASTA, que o ERP não tem como saber. Então cada conta
marcada precisa dessas duas respostas — e marcada sem elas não é gravada, com
o motivo dito, em vez de virar erro de SQL cru na cara de quem só queria
responder "sim".
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import widgets

import util

log = util.log(__name__)


def _barra(top) -> None:
    if widgets is not None and hasattr(widgets, "barra_de_titulo"):
        try:
            widgets.barra_de_titulo(top)
        except Exception:
            log.warning("aplicando a barra de título na janela de contas "
                        "novas", exc_info=True)


def perguntar(pai, novas, empresas) -> list[dict]:
    """Mostra as contas novas e devolve as escolhas.

    `novas` são `conferencia.ContaNova`; `empresas` é `[(id, nome)]`.
    Devolve `[{nome_erp, empresa_id, pasta, banco, agencia, numero}]` — só as
    marcadas. Fechar ou cancelar devolve `[]`.
    """
    top = tk.Toplevel(pai)
    top.title("Contas novas no Mais Controle")
    top.transient(pai)
    _barra(top)

    moldura = ttk.Frame(top, padding=14)
    moldura.pack(fill="both", expand=True)

    ttk.Label(moldura, style="Secao.TLabel",
              text=f"{len(novas)} conta(s) nova(s) no Mais Controle").pack(anchor="w")
    ttk.Label(moldura, style="Apoio.TLabel", wraplength=640, justify="left",
              text="Elas existem no ERP e não estão no cadastro do app. Marque "
                   "as que devem entrar nas automações e diga a empresa e a "
                   "pasta de cada uma. O que ficar desmarcado não é gravado — "
                   "e volta a aparecer na próxima abertura."
              ).pack(anchor="w", pady=(0, 10))

    nomes_empresa = [nome for _id, nome in empresas]
    por_nome = {nome: ident for ident, nome in empresas}

    linhas = []
    for conta in novas:
        bloco = ttk.Frame(moldura)
        bloco.pack(fill="x", pady=(6, 0))

        marcada = tk.BooleanVar(value=False)
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

    rodape = ttk.Frame(moldura)
    rodape.pack(fill="x", pady=(14, 0))
    ttk.Button(rodape, text="Agora não", command=top.destroy).pack(side="right")
    botao = ttk.Button(rodape, text="Cadastrar", command=confirmar)
    botao.pack(side="right", padx=(0, 8))
    try:
        botao.configure(style="Accent.TButton")
    except tk.TclError:
        pass

    top.protocol("WM_DELETE_WINDOW", top.destroy)
    top.bind("<Escape>", lambda _e: top.destroy())
    try:
        top.grab_set()
        top.focus_set()
    except tk.TclError:
        pass
    pai.wait_window(top)
    return escolhas
