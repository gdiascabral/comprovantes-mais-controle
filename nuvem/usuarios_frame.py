# -*- coding: utf-8 -*-
"""A tela "Usuários": a fila de quem pediu acesso, e o que cada um alcança.

Só o administrador chega aqui — o item nem aparece no menu para os outros. Mas
o que impede alguém de mexer não é o item escondido: é a RLS, que só aceita
escrita em `perfil` de quem tem perfil de admin ativo. Esta tela é o lugar
onde a decisão é TOMADA, não onde ela é imposta.

A regra fica no `nuvem/usuarios.py`, e aqui só o que precisa de Tk — a mesma
divisão do `contas_novas_dialogo.py`, e pelo mesmo motivo: a regra tem teste,
a tela tem o que der para exercitar.

Tudo que fala com o servidor roda fora da thread da tela. Uma lista de oito
pessoas é rápida, mas o timeout do `rest` é de 20 segundos, e uma janela
congelada por 20 segundos é indistinguível de um app travado.
"""
from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

try:
    from . import rest, usuarios
except ImportError:                      # rodando este módulo isoladamente
    import rest
    import usuarios

try:                                     # widgets compartilhados (raiz)
    import widgets
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import widgets


#: Como cada situação aparece na tabela. O SÍMBOLO vem junto do texto porque a
#: tag do Treeview só pinta duas das situações (ver `widgets.estilo_tabela`) —
#: e porque quem não vê cor precisa da mesma informação.
COMO_MOSTRAR = {
    "pendente": ("⚠  esperando liberação", "atencao"),
    "ativo": ("✓  ativo", "ok"),
    "desativado": ("✖  desativado", "erro"),
}

#: Os rótulos do combo, na ordem do `usuarios.PAPEIS`.
ROTULO_DO_PAPEL = {chave: rotulo for chave, rotulo, _ in usuarios.PAPEIS}
PAPEL_DO_ROTULO = {rotulo: chave for chave, rotulo, _ in usuarios.PAPEIS}


def _dia(quando: str) -> str:
    """"2026-08-30T14:02:11.7+00:00" -> "30/08/2026". "" quando não dá."""
    try:
        ano, mes, dia = quando[:10].split("-")
        return f"{dia}/{mes}/{ano}"
    except (AttributeError, ValueError):
        return ""


class UsuariosFrame(ttk.Frame):
    """`obter_token` é chamado a cada ida ao servidor, e não guardado: o token
    vence de hora em hora, e um guardado na abertura do app estaria velho na
    primeira aprovação da tarde."""

    def __init__(self, pai, obter_token, eu=None):
        super().__init__(pai, style="Fundo.TFrame")
        self._obter_token = obter_token
        self._eu = eu
        self._lista: list[usuarios.Usuario] = []
        self._fila: queue.Queue = queue.Queue()
        self._ocupado = False
        self._avisando_progresso = False
        self._build()
        self.ao_abrir()

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = widgets.PADX

        cab = widgets.Cabecalho(
            self, "Usuários",
            "Quem entra no app, e o que cada um alcança. Conta criada pela "
            "tela de login nasce esperando: enquanto ninguém a libera, ela "
            "entra e não vê nada.",
            trilha="Administração  ›  Usuários")
        cab.pack(fill="x", padx=PADX, pady=(16, 12))
        widgets.Botao(cab.acoes, "Atualizar", papel="neutro",
                      command=self.ao_abrir).pack(side="right")

        cartao = widgets.Cartao(self, "Contas e papéis")
        cartao.pack(fill="both", expand=True, padx=PADX, pady=(0, 18))

        colunas = ("nome", "email", "papel", "situacao", "desde")
        self.tabela = ttk.Treeview(cartao, columns=colunas, show="headings",
                                   selectmode="browse", height=12)
        for col, titulo, larg, onde in (
                ("nome", "NOME", 200, "w"),
                ("email", "E-MAIL", 250, "w"),
                ("papel", "PAPEL", 130, "w"),
                ("situacao", "SITUAÇÃO", 170, "w"),
                ("desde", "DESDE", 90, "center")):
            self.tabela.heading(col, text=titulo)
            self.tabela.column(col, width=larg, anchor=onde,
                               stretch=col in ("nome", "email"))
        widgets.estilo_tabela(self.tabela)
        self.tabela.pack(fill="both", expand=True)
        self.tabela.bind("<<TreeviewSelect>>", lambda _e: self._escolheu())

        self.rodape = widgets.RodapeTabela(cartao)
        self.rodape.pack(fill="x", pady=(8, 0))

        # ---- o que fazer com quem está selecionado
        acoes = ttk.Frame(cartao)
        acoes.pack(fill="x", pady=(12, 0))

        ttk.Label(acoes, text="PAPEL", style="MenuSecao.TLabel"
                  ).pack(side="left", padx=(0, 6))
        self.combo = ttk.Combobox(acoes, state="readonly", width=17,
                                  values=[r for _c, r, _e in usuarios.PAPEIS])
        self.combo.pack(side="left")
        self.combo.bind("<<ComboboxSelected>>", lambda _e: self._explicar())

        self.lbl_papel = ttk.Label(acoes, text="", style="Apoio.TLabel")
        self.lbl_papel.pack(side="left", padx=(10, 0))

        self.b_desativar = widgets.Botao(acoes, "Desativar", papel="neutro",
                                         command=self._desativar)
        self.b_desativar.pack(side="right")
        self.b_papel = widgets.Botao(acoes, "Trocar papel", papel="passo",
                                     command=self._trocar_papel)
        self.b_papel.pack(side="right", padx=(0, 8))
        self.b_aprovar = widgets.Botao(acoes, "Aprovar", papel="acao",
                                       command=self._aprovar)
        self.b_aprovar.pack(side="right", padx=(0, 8))

        self.aviso = ttk.Label(cartao, text=" ", style="Apoio.TLabel",
                               wraplength=820, justify="left")
        self.aviso.pack(fill="x", pady=(10, 0))
        self._escolheu()

    # ------------------------------------------------------------- a lista
    def ao_abrir(self, dizendo: bool = True):
        """Chamado pelo menu a cada vez que a tela aparece.

        Relê SEMPRE. Aprovar alguém com a lista de ontem é aprovar quem já foi
        desativado hoje — e é a única tela do app em que o dado velho vira
        decisão errada em vez de número desatualizado.

        `dizendo=False` é para a releitura que vem logo depois de uma
        aprovação: o "Carregando…" apagaria da tela o "✔ fulano agora entra
        como aprovador" antes de alguém ler."""
        self._trabalhar("Carregando", lambda t: usuarios.listar(t),
                        self._recebeu_lista, dizendo=dizendo)

    def _recebeu_lista(self, lista):
        self._lista = list(lista)
        self.tabela.delete(*self.tabela.get_children())
        for i, u in enumerate(self._lista):
            texto, estado = COMO_MOSTRAR.get(u.situacao,
                                             (u.situacao, "info"))
            self.tabela.insert(
                "", "end", iid=u.user_id,
                values=(u.como_chamar, u.email,
                        ROTULO_DO_PAPEL.get(u.papel, u.papel),
                        texto, _dia(u.criado_em)),
                tags=widgets.linha_zebrada(i, estado))
        esperando = sum(1 for u in self._lista if u.espera)
        ativos = sum(1 for u in self._lista if u.situacao == "ativo")
        fora = sum(1 for u in self._lista if u.situacao == "desativado")
        partes = [f"{esperando} esperando liberação",
                  f"{ativos} ativos"]
        if fora:
            partes.append(f"{fora} desativados")
        self.rodape.definir(texto=" · ".join(partes))
        self._escolheu()

    # ------------------------------------------------------------ a seleção
    def _selecionado(self) -> "usuarios.Usuario | None":
        escolhidos = self.tabela.selection()
        if not escolhidos:
            return None
        for u in self._lista:
            if u.user_id == escolhidos[0]:
                return u
        return None

    def _escolheu(self):
        u = self._selecionado()
        if u is None:
            for b in (self.b_aprovar, self.b_papel, self.b_desativar):
                b.configure(state="disabled")
            self.combo.set("")
            self.lbl_papel.configure(text="Escolha alguém na lista.")
            return
        self.combo.set(ROTULO_DO_PAPEL.get(u.papel, ""))
        self._explicar()
        # Aprovar é para quem espera; trocar papel e desativar, para quem já
        # entrou. O mesmo botão servindo aos dois casos deixaria "Aprovar"
        # aceso na frente de quem já trabalha há meses.
        self.b_aprovar.configure(state="normal" if u.espera else "disabled")
        self.b_papel.configure(state="disabled" if u.espera else "normal")
        self.b_desativar.configure(
            text="Reativar" if u.situacao == "desativado" else "Desativar",
            state="normal")

    def _explicar(self):
        papel = PAPEL_DO_ROTULO.get(self.combo.get(), "")
        for chave, _rotulo, explica in usuarios.PAPEIS:
            if chave == papel:
                self.lbl_papel.configure(text=explica)
                return
        self.lbl_papel.configure(text="")

    # -------------------------------------------------------------- as ações
    def _aprovar(self):
        u = self._selecionado()
        papel = PAPEL_DO_ROTULO.get(self.combo.get(), "")
        if u is None or not papel:
            return
        self._trabalhar(f"Liberando {u.como_chamar}",
                        lambda t: usuarios.aprovar(t, u.user_id, papel),
                        lambda _r: self._deu_certo(
                            f"{u.como_chamar} agora entra como "
                            f"{ROTULO_DO_PAPEL[papel].lower()}."))

    def _trocar_papel(self):
        u = self._selecionado()
        papel = PAPEL_DO_ROTULO.get(self.combo.get(), "")
        if u is None or not papel or papel == u.papel:
            self._dizer("O papel escolhido já é o que essa conta tem.")
            return
        if not usuarios.sobraria_admin(self._lista, u.user_id, papel=papel):
            self._dizer(self._sem_admin(u), erro=True)
            return
        self._trabalhar(f"Trocando o papel de {u.como_chamar}",
                        lambda t: usuarios.mudar_papel(t, u.user_id, papel),
                        lambda _r: self._deu_certo(
                            f"{u.como_chamar} agora é "
                            f"{ROTULO_DO_PAPEL[papel].lower()}."))

    def _desativar(self):
        u = self._selecionado()
        if u is None:
            return
        if u.situacao == "desativado":
            self._trabalhar(f"Reativando {u.como_chamar}",
                            lambda t: usuarios.reativar(t, u.user_id),
                            lambda _r: self._deu_certo(
                                f"{u.como_chamar} voltou a trabalhar."))
            return
        if not usuarios.sobraria_admin(self._lista, u.user_id,
                                       situacao="desativado"):
            self._dizer(self._sem_admin(u), erro=True)
            return
        self._trabalhar(f"Desativando {u.como_chamar}",
                        lambda t: usuarios.desativar(t, u.user_id),
                        lambda _r: self._deu_certo(
                            f"{u.como_chamar} não entra mais. A conta fica na "
                            "lista: é ela que diz quem era, na auditoria."))

    def _sem_admin(self, u) -> str:
        """A frase do caminho sem volta.

        Diz o que aconteceria, e não só "não pode": quem lê precisa saber que
        a saída é promover outra pessoa antes."""
        eu_mesmo = bool(self._eu and self._eu.user_id == u.user_id)
        quem = "você" if eu_mesmo else u.como_chamar
        return (f"Isso deixaria o app sem nenhum administrador ativo — "
                f"{quem} é o último. Ninguém mais aprovaria conta nem trocaria "
                "papel, e o conserto passaria a exigir SQL no painel do "
                "Supabase. Promova outra pessoa a administrador primeiro.")

    # ------------------------------------------------------- fora da thread
    def _trabalhar(self, o_que: str, tarefa, depois, dizendo: bool = True):
        if self._ocupado:
            return
        token = self._obter_token()
        if not token:
            self._dizer("Sem sessão com o servidor agora. Tente de novo em "
                        "alguns instantes.", erro=True)
            return
        self._ocupado = True
        self._travar(True)
        self._avisando_progresso = dizendo
        if dizendo:
            self._dizer(o_que + "…")

        def rodar():
            try:
                self._fila.put(("ok", tarefa(token), depois))
            except Exception as e:                        # noqa: BLE001
                self._fila.put(("erro", e, depois))
        threading.Thread(target=rodar, daemon=True).start()
        self.after(120, self._drenar)

    def _drenar(self):
        if not self.winfo_exists():
            return                       # a aba fechou enquanto se esperava
        try:
            estado, carga, depois = self._fila.get_nowait()
        except queue.Empty:
            try:
                self.after(120, self._drenar)
            except tk.TclError:
                pass
            return
        self._ocupado = False
        self._travar(False)
        # O "Carregando…" some ao terminar de carregar. Deixá-lo na tela faria
        # a próxima pessoa a olhar achar que ainda está buscando algo.
        if self._avisando_progresso:
            self._dizer(" ")
            self._avisando_progresso = False
        if estado == "ok":
            depois(carga)
            return
        self._dizer(self._frase(carga), erro=True)

    @staticmethod
    def _frase(e: Exception) -> str:
        if isinstance(e, rest.SemRede):
            return ("Sem internet: não deu para falar com o servidor. "
                    "Conecte-se e tente de novo.")
        if isinstance(e, rest.PrecisaEntrar):
            return ("O servidor recusou: a sua sessão venceu ou a sua conta "
                    "perdeu a permissão de administrador. Feche e abra o app.")
        if isinstance(e, (rest.RecusadoPeloBanco, ValueError)):
            return str(e)
        return f"Não deu certo agora: {e}"

    def _deu_certo(self, frase: str):
        self._dizer("✔  " + frase)
        # Relê do servidor em vez de remendar a linha na tela: o que vale é o
        # que ficou gravado, e a lista pode ter mudado por outra mão enquanto
        # esta tela estava aberta.
        self.ao_abrir(dizendo=False)

    def _travar(self, travando: bool):
        estado = "disabled" if travando else "normal"
        for b in (self.b_aprovar, self.b_papel, self.b_desativar):
            try:
                b.configure(state=estado)
            except tk.TclError:
                pass
        if not travando:
            self._escolheu()             # devolve cada botão ao estado certo

    def _dizer(self, frase: str, erro: bool = False):
        self.aviso.configure(text=frase,
                             style="Erro.TLabel" if erro else "Apoio.TLabel")
