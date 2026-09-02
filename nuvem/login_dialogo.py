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

Desde 30/08/2026 a janela tem duas abas. A segunda, "Criar conta", existe
porque o chefe vai entrar aqui para aprovar a remessa do dia, e criar conta à
mão no painel do Supabase não escala nem para três pessoas — além de obrigar
quem cria a escolher a senha de outro. Aqui a senha é digitada pela própria
pessoa e vai direto para o servidor: o app não a vê, não a guarda e não a
escolhe.

Quem se cadastra NÃO entra por isso. Confirma o e-mail (recurso do Supabase,
não construído aqui), e depois espera um administrador liberar — é a terceira
tela deste arquivo, `avisar_que_espera`. Enquanto isso a conta existe, loga, e
não alcança dado nenhum: quem garante isso é a RLS, não a interface.
"""
from __future__ import annotations

try:
    from . import rest, sessao
except ImportError:
    import rest
    import sessao

#: O mínimo que o servidor aceita, para não fazer a pessoa viajar até ele
#: para ouvir um não. Vale como CÓPIA, não como regra: quem manda é o painel
#: (Authentication → Sign In / Providers → Minimum password length), e quando
#: os dois discordarem é o servidor que decide — a recusa dele chega
#: traduzida pelo `nuvem/rest.py`, com o número que ele exige.
#:
#: Ficou em 8 por um tempo, mais apertado que o servidor de propósito. Voltou
#: para 6 em 30/08/2026: uma trava local mais dura que a do servidor recusa
#: senha que o servidor aceitaria, e quem lê não tem como saber que foi o app,
#: e não o banco, que disse não.
MINIMO_DA_SENHA = 6


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

    ttk.Label(quadro, text="🔒  Comprovantes Mais Controle",
              style="Titulo.TLabel").pack(anchor="w")
    # O recado vem ANTES de tudo: ele é a resposta para "por que estou vendo
    # esta tela?", e é a única coisa nesta janela que muda de uma abertura para
    # a outra. Sem ele, a queda da internet e a sessão revogada eram
    # indistinguíveis — as duas mostravam só o campo de senha.
    #
    # Fica FORA das abas de propósito: ele fala da sessão, não de qual das
    # duas coisas a pessoa veio fazer.
    if recado:
        ttk.Label(quadro, text="⚠  " + recado, style="Erro.TLabel",
                  wraplength=380, justify="left").pack(anchor="w", pady=(8, 0))

    abas = ttk.Notebook(quadro)
    abas.pack(fill="both", expand=True, pady=(10, 12))
    entrada = ttk.Frame(abas, padding=(2, 14, 2, 4))
    criacao = ttk.Frame(abas, padding=(2, 14, 2, 4))
    abas.add(entrada, text="   Entrar   ")
    abas.add(criacao, text="   Criar conta   ")

    # ---------------------------------------------------------- aba Entrar
    ttk.Label(entrada, wraplength=380, justify="left", style="Apoio.TLabel",
              text="Use o seu e-mail e senha. O app lembra deste computador — "
                   "só vai perguntar de novo se você sair ou trocar de "
                   "máquina.").pack(anchor="w", pady=(0, 12))

    ttk.Label(entrada, text="E-mail", style="Apoio.TLabel").pack(anchor="w")
    campo_email = ttk.Entry(entrada, width=34, font=widgets.FONTE_SECAO)
    campo_email.pack(fill="x", pady=(0, 8))
    campo_email.insert(0, sessao.quem(pasta).email)

    ttk.Label(entrada, text="Senha", style="Apoio.TLabel").pack(anchor="w")
    campo_senha = ttk.Entry(entrada, show="•", width=34,
                            font=widgets.FONTE_SECAO)
    campo_senha.pack(fill="x")

    aviso = ttk.Label(entrada, text=" ", style="Erro.TLabel", wraplength=380,
                      justify="left")
    aviso.pack(anchor="w", pady=(6, 10))

    # ----------------------------------------------------- aba Criar conta
    ttk.Label(criacao, wraplength=380, justify="left", style="Apoio.TLabel",
              text="Crie a sua conta com a SUA senha — ninguém aqui a vê. "
                   "Você recebe um e-mail para confirmar o endereço; depois "
                   "disso, um administrador libera o acesso."
              ).pack(anchor="w", pady=(0, 12))

    campos_novos = {}
    for chave, rotulo, oculto in (("nome", "Nome completo", False),
                                  ("email", "E-mail", False),
                                  ("senha", "Senha (mínimo 6 caracteres)", True),
                                  ("repete", "Repita a senha", True)):
        ttk.Label(criacao, text=rotulo, style="Apoio.TLabel").pack(anchor="w")
        campo = ttk.Entry(criacao, width=34, font=widgets.FONTE_SECAO,
                          show="•" if oculto else "")
        campo.pack(fill="x", pady=(0, 8))
        campos_novos[chave] = campo

    # Dois avisos, e não um: o verde precisa continuar na tela enquanto a
    # pessoa vai abrir o e-mail, e o vermelho de um erro seguinte não pode
    # apagar a instrução que ela ainda não cumpriu.
    aviso_novo = ttk.Label(criacao, text=" ", style="Erro.TLabel",
                           wraplength=380, justify="left")
    aviso_novo.pack(anchor="w", pady=(2, 0))
    feito_novo = ttk.Label(criacao, text="", style="Ok.TLabel",
                           wraplength=380, justify="left")
    feito_novo.pack(anchor="w", pady=(2, 8))

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

    def _criar(_=None):
        nome = campos_novos["nome"].get().strip()
        email = campos_novos["email"].get().strip()
        senha = campos_novos["senha"].get()
        # A conferência daqui é a que evita uma viagem à toa e, no caso da
        # senha repetida, algo que o servidor NÃO tem como pegar: senha
        # digitada errada em campo escondido vira conta que ninguém abre.
        if not nome or not email or not senha:
            aviso_novo.configure(text="Preencha nome, e-mail e senha.")
            return
        if " " not in nome:
            aviso_novo.configure(
                text="Escreva o nome completo — é o que o administrador vê "
                     "para saber quem está pedindo acesso.")
            return
        if "@" not in email or "." not in email.split("@")[-1]:
            aviso_novo.configure(text="Esse e-mail não parece completo.")
            return
        if len(senha) < MINIMO_DA_SENHA:
            aviso_novo.configure(
                text=f"A senha precisa de ao menos {MINIMO_DA_SENHA} "
                     "caracteres.")
            return
        if senha != campos_novos["repete"].get():
            aviso_novo.configure(text="As duas senhas não são iguais.")
            campos_novos["repete"].delete(0, "end")
            campos_novos["repete"].focus_set()
            return

        aviso_novo.configure(text="Criando a conta…")
        dlg.update_idletasks()
        try:
            confirmar = rest.criar_conta(nome, email, senha)
        except rest.RecusadoPeloBanco as e:
            # A frase vem PRONTA do `rest`: é lá que se sabe o que o GoTrue
            # respondeu, e traduzir de novo aqui criaria duas versões da mesma
            # verdade. O `_frase` é para o outro caminho, o da sessão.
            aviso_novo.configure(text=str(e))
            return
        except rest.ErroDaNuvem as e:
            aviso_novo.configure(text=_frase(e))
            return

        aviso_novo.configure(text=" ")
        for chave in ("senha", "repete"):
            campos_novos[chave].delete(0, "end")
        feito_novo.configure(
            text=("✔  Conta criada. Abra o e-mail em " + email + " e clique "
                  "no link para confirmar o endereço. Depois entre pela aba "
                  "“Entrar” — o acesso ainda precisa ser liberado por um "
                  "administrador.\n\n"
                  "Se o link disser que expirou, tente entrar mesmo assim: "
                  "alguns provedores abrem os links da mensagem antes de "
                  "você, e nesse caso a confirmação já aconteceu.")
            if confirmar else
            ("✔  Conta criada e já confirmada. Entre pela aba “Entrar” — o "
             "acesso ainda precisa ser liberado por um administrador."))
        # O e-mail já vai para a outra aba: quando a confirmação chegar, falta
        # só a senha.
        if not campo_email.get().strip():
            campo_email.insert(0, email)

    def _sair():
        resultado["ok"] = False
        dlg.destroy()

    ttk.Button(botoes, text="Sair do app", command=_sair, width=14
               ).pack(side="right")

    def _principal(pai, texto, comando):
        try:
            return ttk.Button(pai, text=texto, style="Accent.TButton",
                              command=comando, width=14)
        except tk.TclError:  # sem o sv-ttk não existe Accent.TButton
            return ttk.Button(pai, text=texto, command=comando, width=14)

    # Um botão por aba, e não um só que muda de nome: o botão de uma aba
    # escondida não pode ser acionado sem querer, e "Entrar" e "Criar conta"
    # fazem coisas irreversivelmente diferentes.
    _principal(entrada, "Entrar", _entrar).pack(anchor="e")
    _principal(criacao, "Criar conta", _criar).pack(anchor="e", pady=(4, 0))

    campo_email.bind("<Return>", lambda _e: campo_senha.focus_set())
    campo_senha.bind("<Return>", _entrar)
    campos_novos["nome"].bind("<Return>",
                              lambda _e: campos_novos["email"].focus_set())
    campos_novos["email"].bind("<Return>",
                               lambda _e: campos_novos["senha"].focus_set())
    campos_novos["senha"].bind("<Return>",
                               lambda _e: campos_novos["repete"].focus_set())
    campos_novos["repete"].bind("<Return>", _criar)
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


def avisar_que_espera(root, pasta=None) -> bool:
    """A tela de quem entrou mas ainda não pode trabalhar. True = pode agora.

    Quem chega aqui acertou a senha: a conta existe e a sessão é válida. O que
    falta é um administrador dizer que essa pessoa trabalha aqui — e é o único
    passo do cadastro que uma máquina não tem como decidir sozinha.

    Esconder as abas não é o que protege nada; quem protege é a RLS, que nega
    tudo a quem não tem perfil ativo. Esta tela existe para a pessoa entender
    por que o app está vazio, em vez de achar que ele quebrou.
    """
    import tkinter as tk
    from tkinter import ttk

    import widgets

    eu = sessao.quem(pasta)
    resultado = {"liberado": False}

    dlg = tk.Toplevel(root)
    dlg.title("Aguardando liberação — Comprovantes Mais Controle")
    dlg.resizable(False, False)
    widgets.barra_de_titulo(dlg)
    try:
        ico = root.wm_iconbitmap()
        if ico:
            dlg.iconbitmap(ico)
    except tk.TclError:
        pass

    quadro = ttk.Frame(dlg, padding=20)
    quadro.pack(fill="both", expand=True)

    desativado = eu.situacao == "desativado"
    ttk.Label(quadro, style="Titulo.TLabel",
              text=("🚫  Acesso desativado" if desativado
                    else "⏳  Aguardando liberação")).pack(anchor="w")
    ttk.Label(quadro, wraplength=420, justify="left", style="Apoio.TLabel",
              text=("A sua conta foi desativada por um administrador. Se isso "
                    "não era esperado, fale com quem cuida do app."
                    if desativado else
                    "A sua conta está criada e o e-mail, confirmado. Falta um "
                    "administrador liberar o acesso — assim que ele fizer "
                    "isso, clique em “Conferir de novo” aqui embaixo, sem "
                    "precisar fechar o app.")
              ).pack(anchor="w", pady=(8, 12))

    ttk.Label(quadro, text="ENTROU COMO", style="MenuSecao.TLabel"
              ).pack(anchor="w")
    ttk.Label(quadro, text=eu.email or "—", style="Forte.TLabel"
              ).pack(anchor="w", pady=(0, 12))

    aviso = ttk.Label(quadro, text=" ", style="Erro.TLabel", wraplength=420,
                      justify="left")
    aviso.pack(anchor="w", pady=(0, 10))

    def _conferir():
        aviso.configure(text="Perguntando ao servidor…")
        dlg.update_idletasks()
        agora = sessao.reconferir(pasta)
        if agora.ativo:
            resultado["liberado"] = True
            dlg.destroy()
            return
        aviso.configure(
            text=("A conta continua desativada." if agora.situacao == "desativado"
                  else "Ainda não. A liberação não saiu até agora."))

    def _trocar():
        # Entrou com a conta errada, ou a conta certa foi desligada: apagar a
        # sessão faz a próxima abertura perguntar de novo. Não fala com o
        # servidor — o token vence sozinho.
        sessao.esquecer(pasta)
        resultado["liberado"] = False
        dlg.destroy()

    def _sair():
        resultado["liberado"] = False
        dlg.destroy()

    botoes = ttk.Frame(quadro)
    botoes.pack(fill="x")
    ttk.Button(botoes, text="Sair do app", command=_sair, width=14
               ).pack(side="right")
    ttk.Button(botoes, text="Entrar com outra conta", command=_trocar, width=20
               ).pack(side="right", padx=(0, 8))
    if not desativado:
        try:
            conferir = ttk.Button(botoes, text="Conferir de novo",
                                  style="Accent.TButton", command=_conferir,
                                  width=16)
        except tk.TclError:
            conferir = ttk.Button(botoes, text="Conferir de novo",
                                  command=_conferir, width=16)
        conferir.pack(side="right", padx=(0, 8))

    dlg.bind("<Escape>", lambda _e: _sair())
    dlg.protocol("WM_DELETE_WINDOW", _sair)

    dlg.update_idletasks()
    larg, alt = dlg.winfo_width(), dlg.winfo_height()
    dlg.geometry("+%d+%d" % ((dlg.winfo_screenwidth() - larg) // 2,
                             (dlg.winfo_screenheight() - alt) // 3))
    try:
        dlg.grab_set()
        dlg.lift()
        dlg.focus_force()
    except tk.TclError:
        pass
    root.wait_window(dlg)
    return resultado["liberado"]
