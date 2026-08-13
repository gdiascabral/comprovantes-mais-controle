# -*- coding: utf-8 -*-
"""A janela de entrada do app. Substitui a senha de ativação.

O que mudou, e por quê: a senha de ativação era UMA, compartilhada, e liberava
a máquina para sempre. Quem saía da equipe continuava sabendo dela, e trocá-la
obrigava a publicar release nova e perguntar de novo a todo mundo. Agora cada
pessoa tem a sua conta, revogável sozinha, e o app sabe quem está usando — o
que a Fase 3 vai gravar junto de cada aporte lançado.

Modal de propósito: isto EXIGE resposta, como o antigo diálogo de ativação e
o confirmar dos sócios. (O calendário do `CampoData` não é, e a diferença está
explicada no `widgets.py`.)
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from . import rest, sessao
except ImportError:
    import rest
    import sessao

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util


def entrar_sozinho(pasta=None) -> tuple[bool, str]:
    """Tenta entrar com a sessão salva, sem perguntar nada.

    Devolve (entrou, recado). O recado só é preenchido quando vale dizer algo
    — hoje, quando se entrou pelo prazo do token, sem falar com o servidor."""
    try:
        sessao.token(pasta)
        return True, ""
    except rest.PrecisaEntrar:
        return False, ""


def pedir_login(root, pasta=None) -> bool:
    """Pede e-mail e senha. True = pode abrir o app.

    Recebe a janela principal já criada e com o tema aplicado, pelo mesmo
    motivo do antigo `pedir_ativacao`: montar um segundo `Tk()` deixaria o
    diálogo com o visual padrão do tkinter, destoando do resto.
    """
    import tkinter as tk
    from tkinter import ttk

    import widgets                       # dentro da função, como o tkinter:
                                         # este módulo roda no CI sem tela

    entrou, _ = entrar_sozinho(pasta)
    if entrou:
        return True

    resultado = {"ok": False}
    dlg = tk.Toplevel(root)
    dlg.title("Entrar — Comprovantes Mais Controle")
    dlg.resizable(False, False)
    widgets.barra_de_titulo(dlg)
    # Sem `transient()`, como o diálogo de ativação: a janela principal está
    # escondida, e uma janela transiente não ganha botão na barra de tarefas —
    # quem clicasse fora não teria como voltar.
    try:
        ico = root.wm_iconbitmap()
        if ico:
            dlg.iconbitmap(ico)
    except tk.TclError:
        pass

    quadro = ttk.Frame(dlg, padding=20)
    quadro.pack(fill="both", expand=True)

    ttk.Label(quadro, text="🔒  Entrar", style="Titulo.TLabel").pack(anchor="w")
    ttk.Label(quadro, wraplength=380, justify="left", style="Apoio.TLabel",
              text="Use o seu e-mail e senha. O app lembra deste computador — "
                   "só vai perguntar de novo se você sair ou trocar de "
                   "máquina.").pack(anchor="w", pady=(6, 12))

    ttk.Label(quadro, text="E-mail", style="Apoio.TLabel").pack(anchor="w")
    campo_email = ttk.Entry(quadro, width=34, font=widgets.FONTE_SECAO)
    campo_email.pack(fill="x", pady=(0, 8))
    campo_email.insert(0, sessao.quem(pasta))

    ttk.Label(quadro, text="Senha", style="Apoio.TLabel").pack(anchor="w")
    campo_senha = ttk.Entry(quadro, show="•", width=34, font=widgets.FONTE_SECAO)
    campo_senha.pack(fill="x")

    aviso = ttk.Label(quadro, text=" ", style="Erro.TLabel", wraplength=380,
                      justify="left")
    aviso.pack(anchor="w", pady=(6, 12))

    botoes = ttk.Frame(quadro)
    botoes.pack(fill="x")

    def _entrar(_=None):
        email = campo_email.get().strip()
        senha = campo_senha.get()
        if not email or not senha:
            aviso.configure(text="Preencha o e-mail e a senha.")
            return
        aviso.configure(text="Entrando…")
        dlg.update_idletasks()
        try:
            sessao.entrar(email, senha, pasta)
        except rest.PrecisaEntrar:
            # Nunca dizer QUAL dos dois está errado: quem descobre que o
            # e-mail existe já sabe metade.
            aviso.configure(text="E-mail ou senha incorretos.")
            campo_senha.delete(0, "end")
            campo_senha.focus_set()
            try:
                dlg.bell()
            except tk.TclError:
                pass
            return
        except rest.ErroDaNuvem as e:
            aviso.configure(text=f"Não deu para entrar agora: {e}")
            return
        resultado["ok"] = True
        dlg.destroy()

    def _sair():
        resultado["ok"] = False
        dlg.destroy()

    ttk.Button(botoes, text="Sair do app", command=_sair, width=14
               ).pack(side="right")
    try:
        ok = ttk.Button(botoes, text="Entrar", style="Accent.TButton",
                        command=_entrar, width=14)
    except tk.TclError:      # sem o sv-ttk não existe Accent.TButton
        ok = ttk.Button(botoes, text="Entrar", command=_entrar, width=14)
    ok.pack(side="right", padx=(0, 8))

    campo_email.bind("<Return>", lambda _e: campo_senha.focus_set())
    campo_senha.bind("<Return>", _entrar)
    dlg.bind("<Escape>", lambda _e: _sair())
    dlg.protocol("WM_DELETE_WINDOW", _sair)

    dlg.update_idletasks()
    larg, alt = dlg.winfo_width(), dlg.winfo_height()
    dlg.geometry("+%d+%d" % ((dlg.winfo_screenwidth() - larg) // 2,
                             (dlg.winfo_screenheight() - alt) // 3))
    try:
        dlg.grab_set()                   # modal
        dlg.lift()
        (campo_senha if campo_email.get() else campo_email).focus_force()
    except tk.TclError:
        pass
    root.wait_window(dlg)
    return resultado["ok"]
