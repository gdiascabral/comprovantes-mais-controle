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


def _frase(e: Exception) -> str:
    """Traduz a falha em UMA frase: o que houve, de quem é, e o próximo passo.

    Nunca o traceback, nunca o nome da classe. O que aparecia na PRIMEIRA tela
    do app era `HTTPSConnectionPool(host=...): Max retries exceeded` — texto da
    biblioteca de rede, que não diz nem que a internet caiu nem o que fazer a
    respeito. As três famílias que o `nuvem/rest.py` nomeia pedem coisas
    diferentes de quem está na frente da tela: conectar, esperar, ou digitar de
    novo — e é essa diferença que a frase tem de carregar."""
    if isinstance(e, rest.SemRede):
        return ("Sem internet: não consegui falar com o servidor para conferir "
                "o seu acesso. Conecte-se à rede e tente de novo.")
    if isinstance(e, rest.RecusadoPeloBanco):
        return ("O servidor respondeu com erro — não é a sua senha. Tente de "
                "novo em alguns minutos; se continuar, avise quem cuida do "
                "cadastro.")
    if isinstance(e, rest.PrecisaEntrar):
        # Quem monta a explicação exata é o `nuvem/sessao.py`: só ele sabe
        # separar "sem internet e a sessão salva venceu" de "a sessão não vale
        # mais". Aqui a frase é consumida como está — reescrevê-la criaria uma
        # segunda versão da mesma verdade.
        recado = str(e).strip()
        if not recado:
            return "A sua sessão venceu. Entre de novo."
        return recado[:1].upper() + recado[1:]
    return "Não deu para entrar agora. Tente de novo em alguns minutos."


def entrar_sozinho(pasta=None) -> tuple[bool, str]:
    """Tenta entrar com a sessão salva, sem perguntar nada.

    Devolve (entrou, recado). O recado é a frase que explica por que NÃO deu —
    ela era descartada aqui, e o diálogo abria mudo: quem estava sem internet
    com a sessão vencida via só um campo de senha, sem uma palavra sobre o
    motivo nem sobre o que fazer.

    Sem sessão salva não há recado: é a primeira vez nesta máquina, e aí
    explicar seria ruído em cima do óbvio."""
    try:
        sessao.token(pasta)
        return True, ""
    except rest.ErroDaNuvem as e:
        # `ErroDaNuvem`, e não só `PrecisaEntrar`: uma recusa do servidor
        # (`RecusadoPeloBanco`) subia daqui até o `main()` e o app não abria —
        # com o traceback indo para um console que o exe não tem.
        return False, (_frase(e) if sessao.tem_sessao(pasta) else "")


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

    entrou, recado = entrar_sozinho(pasta)
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
    # O recado vem ANTES da explicação de sempre: ele é a resposta para "por
    # que estou vendo esta tela?", e é a única coisa nesta janela que muda de
    # uma abertura para a outra. Sem ele, a queda da internet e a sessão
    # revogada eram indistinguíveis — as duas mostravam só o campo de senha.
    if recado:
        ttk.Label(quadro, text="⚠  " + recado, style="Erro.TLabel",
                  wraplength=380, justify="left").pack(anchor="w", pady=(8, 0))
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
            # e-mail existe já sabe metade. Aqui a frase NÃO vem do `_frase`:
            # neste ponto a senha acabou de ser digitada, e o recado do
            # `rest.entrar` ("e-mail ou senha incorretos") já é o certo — o do
            # `_frase` fala de sessão, que é o outro caminho.
            aviso.configure(text="E-mail ou senha incorretos. Confira e tente "
                                 "de novo.")
            campo_senha.delete(0, "end")
            campo_senha.focus_set()
            try:
                dlg.bell()
            except tk.TclError:
                pass
            return
        except rest.ErroDaNuvem as e:
            # Sem rede, servidor fora do ar e recusa do banco chegavam aqui
            # juntos e saíam com o texto CRU da biblioteca de rede na tela.
            aviso.configure(text=_frase(e))
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
