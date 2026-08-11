# -*- coding: utf-8 -*-
"""Senha de primeira utilização.

Na primeira vez que o app abre numa máquina, pede a senha de ativação. Acertou,
grava o marcador `ativacao.dat` ao lado do executável (mesma pasta do
`preferencias.json`) e nunca mais pergunta ali.

**A senha NÃO está aqui, e não pode estar**: o repositório é público
(github.com/gdiascabral/comprovantes-mais-controle), então quem clonar leria o
arquivo. O que fica gravado é o SHA-256 de (sal + senha) — irreversível. O sal
está à vista de propósito: ele não é segredo, só existe para que o hash não
case com tabelas prontas de "sha256 de senhas comuns"; o segredo é a senha, que
mora fora do código (com o dono do app).

Este módulo é importável sem GUI: o `tkinter` só é carregado dentro de
`pedir_ativacao()`, para os testes rodarem no CI sem abrir janela.
"""
import hashlib
import hmac
from datetime import datetime
from pathlib import Path

# Sal fixo e público (ver o cabeçalho). Mudar isto invalida as ativações já
# feitas — todo mundo seria perguntado de novo.
SAL = "comprovantes-mais-controle:ativacao:v1"

# SHA-256 de (SAL + senha). Trocar a senha = trocar esta linha pelo hash novo.
_HASH_SENHA = "a7f754d285649cb639737aca4f168470be6b40fad756f9c454f0026cfb65138b"

ARQUIVO = "ativacao.dat"


def _hash(senha: str) -> str:
    """SHA-256 de (SAL + senha), em hexadecimal."""
    return hashlib.sha256((SAL + (senha or "")).encode("utf-8")).hexdigest()


def senha_confere(senha: str) -> bool:
    """True se a senha digitada bate com o hash gravado.

    O `.strip()` existe porque a senha costuma ser colada de um e-mail ou de uma
    conversa, e um espaço invisível no fim viraria "senha incorreta" sem que a
    pessoa tivesse como perceber o motivo. `compare_digest` compara em tempo
    constante — aqui é pouco mais que higiene, mas não custa nada.
    """
    return hmac.compare_digest(_hash((senha or "").strip()), _HASH_SENHA)


def caminho_marcador(pasta) -> Path:
    return Path(pasta) / ARQUIVO


def ja_ativado(pasta) -> bool:
    """True se esta máquina já foi ativada.

    Confere o CONTEÚDO, não só a existência do arquivo: um `ativacao.dat` vazio
    ou truncado (disco cheio, OneDrive que sincronizou só o nome) passaria por
    ativação válida se bastasse existir. De quebra, trocar a senha invalida os
    marcadores antigos sozinho, porque o hash gravado deixa de bater.
    """
    try:
        primeira = caminho_marcador(pasta).read_text(
            encoding="utf-8").splitlines()[0].strip()
    except (OSError, IndexError):
        return False
    return hmac.compare_digest(primeira, _HASH_SENHA)


def marcar_ativado(pasta) -> bool:
    """Grava o marcador. Devolve False se não deu para escrever.

    Guarda o hash (que já está no código, então não vaza nada) e a data, só para
    quem for olhar o arquivo entender o que ele é.
    """
    try:
        caminho_marcador(pasta).write_text(
            f"{_HASH_SENHA}\n"
            f"ativado em {datetime.now():%d/%m/%Y %H:%M}\n", encoding="utf-8")
        return True
    except OSError:
        return False


def pedir_ativacao(root, pasta) -> bool:
    """Diálogo modal da ativação. True = liberado; False = o app não deve abrir.

    Recebe a janela principal já criada e com o tema aplicado (sv-ttk), porque
    montar um segundo `Tk()` só para isto deixaria o diálogo com o visual
    padrão do tkinter, destoando do resto do app.
    """
    import tkinter as tk
    from tkinter import ttk

    if ja_ativado(pasta):
        return True

    resultado = {"ok": False}
    dlg = tk.Toplevel(root)
    dlg.title("Ativação — Comprovantes Mais Controle")
    dlg.resizable(False, False)
    # Sem `transient()` de propósito: a janela principal está escondida enquanto
    # isto aparece, e uma janela transiente não ganha botão na barra de tarefas
    # — quem clicasse fora não teria como voltar para o diálogo.
    try:
        ico = root.wm_iconbitmap()
        if ico:
            dlg.iconbitmap(ico)
    except tk.TclError:
        pass

    quadro = ttk.Frame(dlg, padding=20)
    quadro.pack(fill="both", expand=True)

    ttk.Label(quadro, text="🔒  Primeira utilização",
              font=("Segoe UI", 13, "bold")).pack(anchor="w")
    ttk.Label(quadro, wraplength=380, justify="left",
              text="Digite a senha de ativação para liberar o app nesta "
                   "máquina.\nEla é pedida uma única vez.").pack(
        anchor="w", pady=(6, 12))

    campo = ttk.Entry(quadro, show="•", width=34, font=("Segoe UI", 11))
    campo.pack(fill="x")

    aviso = ttk.Label(quadro, text=" ", foreground="#d13438", wraplength=380,
                      justify="left")
    aviso.pack(anchor="w", pady=(6, 12))

    def _ativar(_=None):
        if not senha_confere(campo.get()):
            aviso.configure(text="Senha incorreta. Confira e tente de novo.")
            campo.delete(0, "end")
            campo.focus_set()
            try:
                dlg.bell()
            except tk.TclError:
                pass
            return
        # Marcador que não gravou (pasta somente-leitura, antivírus) não pode
        # barrar quem acertou a senha: abre assim mesmo e no próximo dia
        # pergunta de novo — pior é ficar de fora com a senha certa na mão.
        if not marcar_ativado(pasta):
            aviso.configure(
                text="Ativado, mas não deu para gravar o marcador nesta pasta:"
                     " a senha será pedida de novo na próxima vez.")
        resultado["ok"] = True
        dlg.destroy()

    def _sair():
        resultado["ok"] = False
        dlg.destroy()

    botoes = ttk.Frame(quadro)
    botoes.pack(fill="x")
    ttk.Button(botoes, text="Sair do app", command=_sair, width=14
               ).pack(side="right")
    try:
        ok = ttk.Button(botoes, text="Ativar", style="Accent.TButton",
                        command=_ativar, width=14)
    except tk.TclError:      # sem o sv-ttk instalado não existe Accent.TButton
        ok = ttk.Button(botoes, text="Ativar", command=_ativar, width=14)
    ok.pack(side="right", padx=(0, 8))

    campo.bind("<Return>", _ativar)
    dlg.bind("<Escape>", lambda _e: _sair())
    # Fechar no X é o mesmo que desistir: sem ativar, o app não abre.
    dlg.protocol("WM_DELETE_WINDOW", _sair)

    dlg.update_idletasks()
    larg, alt = dlg.winfo_width(), dlg.winfo_height()
    dlg.geometry("+%d+%d" % ((dlg.winfo_screenwidth() - larg) // 2,
                             (dlg.winfo_screenheight() - alt) // 3))
    try:
        dlg.grab_set()                   # modal
        dlg.lift()
        campo.focus_force()
    except tk.TclError:
        pass
    root.wait_window(dlg)
    return resultado["ok"]
