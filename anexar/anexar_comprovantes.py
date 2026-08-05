# -*- coding: utf-8 -*-
"""
Anexar Comprovantes — Mais Controle

Fluxo da janela:
  1) Informe o PERÍODO (data de pagamento dos comprovantes) e a PASTA dos
     PDFs renomeados (padrão "VALOR - DESCRIÇÃO - DATA") e clique em
     "Carregar contas" — o app abre o Chrome, ENTRA SOZINHO no Mais Controle
     (com a senha guardada no 🔑 Login) e busca os títulos PAGOS do período.
  2) Marque as CONTAS BANCÁRIAS desejadas (caixas de seleção).
  3) "Casar e anexar": verifica quem já tem comprovante (pula), casa os
     pendentes com os PDFs e anexa. No fim, gera um relatório Excel.

O botão "Abrir o Mais Controle" não é mais um passo: serve para o primeiro
acesso (quando ainda não há senha guardada) e para destravar sessão caída.

Modo alternativo "Por lista": anexa a partir de um CSV (launchId,valor,arquivo_pdf)
ou de um Excel com aba CERTEZA (coluna link + PDF(s)).
"""
import os
import queue
import re
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from datetime import date, datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

try:
    from . import config, matcher, mc_api, planilha, credenciais
    from .mc_client import MCClient, SemRede
except ImportError:
    import config, matcher, mc_api, planilha, credenciais
    from mc_client import MCClient, SemRede

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

LINK = config.MC_URL_LANCAMENTO
_fmt_dur = util.fmt_dur
_norm = util.norm


def _data_api(txt: str) -> str | None:
    """'dd/mm/aaaa' -> 'aaaa-mm-dd' (aceita também dd-mm-aaaa)."""
    m = re.match(r"^\s*(\d{2})[/-](\d{2})[/-](\d{4})\s*$", txt or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _fmt_val(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d}"


def _texto_do_erro(e: Exception) -> str:
    """O que vai para o Registro. Falta de internet é recado, não defeito do
    app: mostra só a orientação, sem despejar traceback de Playwright."""
    if isinstance(e, SemRede):
        return "⚠ " + str(e)
    return "ERRO: " + str(e) + "\n" + traceback.format_exc()


def _resumo_cands(pe: dict) -> str:
    """Candidatos que sobraram para um pagamento em dúvida, do mais provável
    para o menos, com o que bateu em cada um — mesmo detalhe que a janela."""
    partes = []
    for c in sorted((c for c in pe["cands"] if c["pdf"]["used_by"] is None),
                    key=lambda c: -c["score"]):
        sinais = " + ".join(s for s in ("OC/NF" if c["ocnf"] else "",
                                        "centro de custo" if c["cc"] else "",
                                        "data" if c["date"] else "") if s)
        partes.append(f"{c['pdf']['fn']}  [{sinais or 'só o valor'}]")
    return " || ".join(partes) or "(sem candidatos livres)"


def _abrir_url(url: str):
    """Abre uma URL no navegador padrão. Usa os.startfile (sempre presente no
    executável); só recorre ao módulo webbrowser se aquele falhar — assim o
    app não depende do webbrowser estar embutido no motor."""
    try:
        os.startfile(url)                # Windows: abre no navegador padrão
    except Exception:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            pass


class CampoData(ttk.Frame):
    """Campo de data dd/mm/aaaa: completa as barras sozinho ao digitar e tem
    um botão que abre um calendário para escolher a data com o mouse."""

    MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
             "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

    def __init__(self, master, textvariable, width=11):
        super().__init__(master)
        self.var = textvariable
        self.ent = ttk.Entry(self, textvariable=self.var, width=width)
        self.ent.pack(side="left")
        ttk.Button(self, text="📅", width=3, command=self._abrir_cal
                   ).pack(side="left", padx=(2, 0))
        self.ent.bind("<KeyRelease>", self._auto_barra)

    def _auto_barra(self, ev):
        if ev.keysym in ("BackSpace", "Delete", "Left", "Right",
                         "Home", "End", "Tab", "Shift_L", "Shift_R"):
            return
        t = self.var.get()
        d = "".join(c for c in t if c.isdigit())[:8]
        if len(d) > 4:
            novo = d[:2] + "/" + d[2:4] + "/" + d[4:]
        elif len(d) > 2:
            novo = d[:2] + "/" + d[2:]
        else:
            novo = d
        if novo != t:
            self.var.set(novo)
            self.ent.icursor("end")

    def _abrir_cal(self):
        try:
            import calendar
        except ImportError:              # módulo pode não estar no motor antigo
            messagebox.showinfo("Calendário indisponível",
                                "Digite a data manualmente no formato dd/mm/aaaa.")
            return
        top = tk.Toplevel(self)
        top.title("Escolher data")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.geometry(f"+{self.winfo_rootx()}+{self.winfo_rooty() + self.winfo_height() + 2}")
        hoje = date.today()
        m = re.match(r"(\d{2})/(\d{2})/(\d{4})$", (self.var.get() or "").strip())
        mes = [int(m.group(2))] if m and 1 <= int(m.group(2)) <= 12 else [hoje.month]
        ano = [int(m.group(3))] if m else [hoje.year]

        cab = ttk.Frame(top); cab.pack(fill="x", padx=6, pady=4)
        lbl = ttk.Label(cab, text="", width=16, anchor="center")
        grade = ttk.Frame(top); grade.pack(padx=6, pady=(0, 6))

        def escolher(dia):
            self.var.set(f"{dia:02d}/{mes[0]:02d}/{ano[0]}")
            top.destroy()

        def desenhar():
            for w in grade.winfo_children():
                w.destroy()
            lbl.config(text=f"{self.MESES[mes[0] - 1]} {ano[0]}")
            for i, dsem in enumerate(["S", "T", "Q", "Q", "S", "S", "D"]):
                ttk.Label(grade, text=dsem, width=3, anchor="center"
                          ).grid(row=0, column=i)
            for r, semana in enumerate(
                    calendar.Calendar().monthdayscalendar(ano[0], mes[0]), 1):
                for c, dia in enumerate(semana):
                    if dia:
                        ttk.Button(grade, text=str(dia), width=3,
                                   command=lambda d=dia: escolher(d)
                                   ).grid(row=r, column=c, padx=1, pady=1)

        def mudar(delta):
            m2 = mes[0] + delta
            if m2 < 1:
                mes[0], ano[0] = 12, ano[0] - 1
            elif m2 > 12:
                mes[0], ano[0] = 1, ano[0] + 1
            else:
                mes[0] = m2
            desenhar()

        ttk.Button(cab, text="◀", width=3, command=lambda: mudar(-1)).pack(side="left")
        lbl.pack(side="left", expand=True)
        ttk.Button(cab, text="▶", width=3, command=lambda: mudar(1)).pack(side="right")
        desenhar()
        top.grab_set()


class AnexarFrame(ttk.Frame):
    """Conteúdo do app Anexar Comprovantes (usável sozinho ou como aba)."""

    def __init__(self, master):
        super().__init__(master)
        self.q = queue.Queue()
        self.worker = None
        # TODO o trabalho com o navegador roda nesta ÚNICA thread (exigência
        # do Playwright: os objetos só podem ser usados na thread que os criou).
        self.exec = ThreadPoolExecutor(max_workers=1)
        self._pausa = Event()   # ⏸ pausado enquanto setado
        self._parar = Event()   # ⏹ interrompe o processo em andamento
        self.mc = None                       # MCClient aberto entre as etapas
        self.api = None
        self.ultimo_relatorio = None
        self.pagos = []                      # registros de montar_pagos()
        self.vars_contas: dict[str, tk.BooleanVar] = {}

        hoje = date.today()
        self.v_ini = tk.StringVar(value=hoje.replace(day=1).strftime("%d/%m/%Y"))
        self.v_fim = tk.StringVar(value=hoje.strftime("%d/%m/%Y"))
        self.v_pasta = tk.StringVar()
        self.v_lista = tk.StringVar()
        self.v_modo = tk.StringVar(value="auto")
        self.v_dry = tk.BooleanVar(value=False)
        self.v_ign = tk.BooleanVar(value=True)
        self.v_ign_ap = tk.BooleanVar(value=True)
        self._build()
        try:                             # já nasce na cor do tema (sem flash)
            self.aplicar_cores(util.cor_escura(ttk.Style().lookup("TFrame", "background")))
        except Exception:
            pass
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = 14

        # ---- cabeçalho
        cab = ttk.Frame(self)
        cab.pack(fill="x", padx=PADX, pady=(12, 4))
        ttk.Label(cab, text="Anexar Comprovantes",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.lbl_sub = ttk.Label(
            cab, foreground="#6b6b6b",
            text="Busca os pagos do período, descobre quem está sem comprovante "
                 "e anexa o PDF certo em cada um.")
        self.lbl_sub.pack(anchor="w")

        # ---- card 1: período e pasta
        self.f_auto = ttk.LabelFrame(self, text=" 1. Período e pasta dos comprovantes ",
                                     padding=(12, 8, 12, 10))
        self.f_auto.pack(fill="x", padx=PADX, pady=6)
        fa = self.f_auto
        ttk.Label(fa, text="Data de pagamento — de:").grid(row=0, column=0, sticky="w", pady=4)
        CampoData(fa, self.v_ini).grid(row=0, column=1, sticky="w", padx=(6, 14))
        ttk.Label(fa, text="até:").grid(row=0, column=2, sticky="e")
        CampoData(fa, self.v_fim).grid(row=0, column=3, sticky="w", padx=(6, 14))
        ttk.Label(fa, text="(dd/mm/aaaa)").grid(row=0, column=4, sticky="w")
        ttk.Label(fa, text="Pasta dos PDFs renomeados:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(fa, textvariable=self.v_pasta).grid(row=1, column=1, columnspan=3, sticky="we", pady=(6, 0))
        ttk.Button(fa, text="Selecionar…",
                   command=lambda: self.v_pasta.set(
                       (filedialog.askdirectory() or self.v_pasta.get()).replace("\\", "/"))
                   ).grid(row=1, column=4, padx=(6, 0), sticky="w", pady=(6, 0))
        ttk.Checkbutton(fa, text="Ignorar tarifas bancárias, IOF, cesta e pacote de serviços",
                        variable=self.v_ign).grid(row=2, column=0, columnspan=5, sticky="w", pady=(8, 0))
        ttk.Checkbutton(fa, text="Ignorar aportes de capital e distribuição de lucros",
                        variable=self.v_ign_ap).grid(row=3, column=0, columnspan=5, sticky="w")
        fa.columnconfigure(3, weight=1)

        # ---- escolha do modo (entre os blocos 1 e 2)
        self.topo = ttk.Frame(self)
        self.topo.pack(fill="x", padx=PADX, pady=(2, 0))
        ttk.Label(self.topo, text="Modo:").pack(side="left", padx=(0, 10))
        ttk.Radiobutton(self.topo, text="Automático (casar pelos nomes dos PDFs)",
                        variable=self.v_modo, value="auto",
                        command=self._alternar_modo).pack(side="left", padx=(0, 18))
        ttk.Radiobutton(self.topo, text="Por lista pronta (.csv / .xlsx)",
                        variable=self.v_modo, value="lista",
                        command=self._alternar_modo).pack(side="left")

        # ---- card 2: contas
        self.f_contas = ttk.LabelFrame(self, text=" 2. Contas bancárias (marque as desejadas) ",
                                       padding=(12, 8, 12, 10))
        self.f_contas.pack(fill="x", padx=PADX, pady=6)
        self.contas_box = ttk.Frame(self.f_contas)
        self.contas_box.pack(fill="x")
        ttk.Label(self.contas_box,
                  text="Clique em \"1. Carregar contas\" para listar as contas."
                  ).pack(anchor="w")

        # ---- card: modo lista (mostrado só no modo "Por lista")
        self.f_lista = ttk.LabelFrame(self, text=" Lista pronta ", padding=(12, 8, 12, 10))
        fl = self.f_lista
        ttk.Label(fl, text="Arquivo (.csv ou .xlsx):").grid(row=0, column=0, sticky="w")
        ttk.Entry(fl, textvariable=self.v_lista).grid(row=0, column=1, sticky="we", padx=6)
        ttk.Button(fl, text="Selecionar…", command=self._sel_lista
                   ).grid(row=0, column=2, sticky="w")
        fl.columnconfigure(1, weight=1)

        # ---- barra de ação (fixa no rodapé): botões + status/progresso
        acao = ttk.Frame(self)
        acao.pack(side="bottom", fill="x", padx=PADX, pady=(6, 12))
        prog = ttk.Frame(acao)
        prog.pack(side="bottom", fill="x", pady=(8, 0))
        self.lbl = ttk.Label(prog, text="Pronto.")
        self.lbl.pack(side="left")
        self.pb = ttk.Progressbar(prog, mode="determinate")
        self.pb.pack(side="left", fill="x", expand=True, padx=12)

        btns = ttk.Frame(acao)
        btns.pack(fill="x")
        ttk.Checkbutton(btns, text="Simular (não anexa de verdade)",
                        variable=self.v_dry).pack(side="left")
        # "Abrir e acessar" deixou de ser passo: com o login salvo o app entra
        # sozinho. O botão continua aqui, sem número, para o primeiro acesso
        # (quando ainda não há senha guardada) e para destravar sessão caída.
        self.b1 = ttk.Button(btns, text="▶ 1. Carregar contas", command=self.conectar)
        self.b1.pack(side="left", padx=(10, 0))
        self.b2 = ttk.Button(btns, text="▶ 2. Casar e anexar", command=self.executar,
                             state="disabled")
        self.b2.pack(side="left", padx=10)
        self.b0 = ttk.Button(btns, text="Abrir o Mais Controle", command=self.abrir_mc)
        self.b0.pack(side="left")
        self.b_pause = ttk.Button(btns, text="⏸ Pausar", command=self._pausar_toggle,
                                  state="disabled")
        self.b_pause.pack(side="left")
        self.b_stop = ttk.Button(btns, text="⏹ Parar", command=self._parar_click,
                                 state="disabled")
        self.b_stop.pack(side="left", padx=6)
        self.b_rel = ttk.Button(btns, text="📄 Abrir relatório",
                                command=self._abrir_relatorio, state="disabled")
        self.b_rel.pack(side="left", padx=(10, 0))
        self.b_login = ttk.Button(btns, text="🔑 Login",
                                  command=self._gerenciar_login)
        self.b_login.pack(side="right")
        for _b in (self.b1, self.b2):
            try:
                _b.configure(style="Accent.TButton")   # botões azuis (tema sv-ttk)
            except tk.TclError:
                pass

        # ---- card: registro (ocupa o espaço restante)
        reg = ttk.LabelFrame(self, text=" Registro ", padding=(10, 6, 10, 10))
        reg.pack(fill="both", expand=True, padx=PADX, pady=6)
        self.log = tk.Text(reg, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0, background="#ffffff",
                           font=("Consolas", 10))
        self.log.pack(fill="both", expand=True)
        self.log.tag_configure("ph", justify="center", foreground="#8a8a8a",
                               spacing1=6, font=("Segoe UI", 11))
        self._mostrar_placeholder()
        self._alternar_modo()

    def _mostrar_placeholder(self):
        self.log.delete("1.0", "end")
        self.log.insert("end", "\n\n", "ph")
        self.log.insert("end", "O andamento e os resultados aparecerão aqui.\n", "ph")
        self.log.insert("end", "\nSiga os passos 1 → 2 na barra abaixo — o app "
                               "abre o Mais Controle e entra sozinho.\n", "ph")
        self._ph = True

    def _alternar_modo(self):
        if self.v_modo.get() == "auto":
            self.f_lista.pack_forget()
            self.b1.config(state="normal")
        else:
            self.f_lista.pack(fill="x", padx=14, pady=6, after=self.topo)
            self.b2.config(state="normal")

    def _sel_lista(self):
        f = filedialog.askopenfilename(filetypes=[("Lista", "*.csv *.xlsx")])
        if f:
            self.v_lista.set(f.replace("\\", "/"))

    def _log(self, msg):
        self.q.put(("log", msg))

    # ---------------------------------------------------------------- etapa 1
    def abrir_mc(self):
        if self.worker and not self.worker.done():
            return
        self.b0.config(state="disabled")
        self.worker = self.exec.submit(self._t_abrir)

    def garantir_sessao(self, log=None):
        """Abre o Chrome e prepara a API, se ainda não estiverem prontos.
        Deve rodar na thread self.exec (a dona do navegador)."""
        log = log or self._log
        if self.mc is None:
            log("Abrindo o Chrome e entrando no Mais Controle...")
            self.mc = MCClient(log=log).__enter__()
            self.api = mc_api.MCApi(self.mc.page)
            self.mc.garantir_login()
        return self.api

    def _gerenciar_login(self):
        """Botão 🔑 Login: cadastrar/trocar/remover o login salvo."""
        def done(creds):
            if creds and creds[2]:
                try:
                    credenciais.salvar(creds[0], creds[1])
                    self.lbl.config(text="Login salvo neste computador.")
                except Exception as e:
                    messagebox.showerror("Erro", f"Não consegui salvar o login:\n{e}")
        self._mostrar_dialogo_login(done)

    def _mostrar_dialogo_login(self, on_done):
        """Diálogo de login (thread principal). Chama on_done((email, senha,
        salvar)) ao confirmar, ou on_done(None) ao cancelar."""
        top = tk.Toplevel(self)
        top.title("Login do Mais Controle")
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.attributes("-topmost", True)     # fica à frente da janela do Chrome
        top.lift()
        top.after(50, top.focus_force)
        salvos = credenciais.carregar()
        ttk.Label(top, wraplength=380, justify="left",
                  text="Entre com seu login do Mais Controle. Ele é salvo cifrado "
                       "neste computador (login automático nas próximas vezes)."
                  ).grid(row=0, column=0, columnspan=2, padx=14, pady=(14, 10), sticky="w")
        v_email = tk.StringVar(value=(salvos[0] if salvos else ""))
        v_senha = tk.StringVar(value=(salvos[1] if salvos else ""))
        v_salvar = tk.BooleanVar(value=True)
        ttk.Label(top, text="E-mail").grid(row=1, column=0, sticky="w", padx=14)
        ttk.Entry(top, textvariable=v_email, width=42
                  ).grid(row=2, column=0, columnspan=2, padx=14, sticky="we")
        ttk.Label(top, text="Senha").grid(row=3, column=0, sticky="w", padx=14, pady=(8, 0))
        e_senha = ttk.Entry(top, textvariable=v_senha, width=42, show="•")
        e_senha.grid(row=4, column=0, columnspan=2, padx=14, sticky="we")
        ttk.Checkbutton(top, text="Salvar neste computador (entrar automaticamente)",
                        variable=v_salvar).grid(row=5, column=0, columnspan=2,
                                                sticky="w", padx=14, pady=10)
        bar = ttk.Frame(top)
        bar.grid(row=6, column=0, columnspan=2, sticky="we", padx=14, pady=(0, 14))

        def concluir(creds):
            top.destroy()
            on_done(creds)

        def confirmar():
            email, senha = v_email.get().strip(), v_senha.get()
            if not email or not senha:
                messagebox.showwarning("Login", "Preencha e-mail e senha.")
                return
            concluir((email, senha, v_salvar.get()))

        b_ok = ttk.Button(bar, text="Entrar", command=confirmar)
        b_ok.pack(side="right")
        try:
            b_ok.configure(style="Accent.TButton")
        except tk.TclError:
            pass
        ttk.Button(bar, text="Cancelar", command=lambda: concluir(None)
                   ).pack(side="right", padx=(0, 8))
        if salvos:
            ttk.Button(bar, text="Remover login salvo",
                       command=lambda: (credenciais.apagar(), concluir(None))
                       ).pack(side="left")
        top.protocol("WM_DELETE_WINDOW", lambda: concluir(None))
        e_senha.focus_set()
        top.grab_set()

    def _t_abrir(self):
        inicio = time.time()
        self._log(f"⏱ Etapa 1 — início: {time.strftime('%H:%M:%S')}")
        try:
            self.garantir_sessao()
            self._log("Mais Controle aberto. Agora confira o período e a pasta dos "
                      "PDFs e clique em \"1. Carregar contas\".")
            self._log(f"⏱ Etapa 1 — fim: {time.strftime('%H:%M:%S')} "
                      f"({_fmt_dur(time.time() - inicio)})")
        except Exception as e:
            self._log(_texto_do_erro(e))
            self.mc = None
        self.q.put(("reabilitar0", None))

    def aplicar_cores(self, escuro: bool):
        """Ajusta as cores dos widgets clássicos ao tema claro/escuro."""
        if escuro:
            self.log.configure(background="#252525", foreground="#e6e6e6",
                               insertbackground="#e6e6e6")
            muted = "#9a9a9a"
        else:
            self.log.configure(background="#ffffff", foreground="#000000",
                               insertbackground="#000000")
            muted = "#5f5f5f"
        self.log.tag_configure("ph", foreground="#8a8a8a")
        try:
            self.lbl_sub.configure(foreground=muted)
        except Exception:
            pass

    # -------------------------------------------------------- pausar / parar
    def _pausar_toggle(self):
        if self._pausa.is_set():
            self._pausa.clear()
            self.b_pause.config(text="⏸ Pausar")
            self.lbl.config(text="Retomando...")
        else:
            self._pausa.set()
            self.b_pause.config(text="▶ Continuar")
            self.lbl.config(text="⏸ Pausado.")

    def _parar_click(self):
        self._parar.set()
        self._pausa.clear()
        self.b_pause.config(text="⏸ Pausar")
        self.lbl.config(text="Parando...")

    def _checar_pausa(self) -> bool:
        """Bloqueia enquanto pausado; retorna True se o usuário mandou parar."""
        while self._pausa.is_set() and not self._parar.is_set():
            time.sleep(0.3)
        return self._parar.is_set()

    # ------------------------------------------------------------ relatório
    def _abrir_relatorio(self):
        if self.ultimo_relatorio and Path(self.ultimo_relatorio).exists():
            try:
                os.startfile(self.ultimo_relatorio)
            except OSError as e:
                messagebox.showerror("Erro", f"Não consegui abrir o relatório:\n{e}")
        else:
            messagebox.showinfo("Relatório", "Nenhum relatório gerado ainda.")

    # ------------------------------------------------------ resolver dúvidas
    def _janela_duvidas(self, duvidas, ev):
        """Janela para o usuário escolher o PDF certo dos casamentos em dúvida.

        Mostra o pagamento INTEIRO (descrição sem cortar, centro de custo, nº
        doc, categoria, conta) e, para cada PDF candidato, o que bateu e o que
        não bateu — é isso que permite decidir sem abrir o Mais Controle. Dá
        também para abrir o PDF na hora, para conferir o comprovante."""
        pasta = Path(self.v_pasta.get() or ".")
        top = tk.Toplevel(self)
        top.title(f"Resolver dúvidas ({len(duvidas)})")
        top.transient(self.winfo_toplevel())
        try:
            top.geometry(f"{min(1180, self.winfo_screenwidth() - 80)}"
                         f"x{min(780, self.winfo_screenheight() - 120)}")
        except tk.TclError:
            pass
        ttk.Label(top, wraplength=1120, justify="left",
                  text=f"O app não teve certeza em {len(duvidas)} pagamento(s): "
                       "havia mais de um PDF com o mesmo valor, ou nenhum sinal "
                       "forte (OC/NF, centro de custo, data) para decidir. "
                       "Escolha o PDF certo em cada um — ou deixe em dúvida "
                       "para decidir depois pelo relatório.\n"
                       "Dica: dê dois cliques na linha para abrir o PDF."
                  ).pack(anchor="w", padx=12, pady=(10, 6))

        rodape = ttk.Frame(top)
        rodape.pack(side="bottom", fill="x", padx=12, pady=10)

        canvas = tk.Canvas(top, highlightthickness=0)
        barra = ttk.Scrollbar(top, orient="vertical", command=canvas.yview)
        quadro = ttk.Frame(canvas)
        janela = canvas.create_window((0, 0), window=quadro, anchor="nw")
        quadro.bind("<Configure>",
                    lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfigure(janela, width=e.width))
        canvas.configure(yscrollcommand=barra.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=4)
        barra.pack(side="right", fill="y")
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(-(e.delta // 120), "units"))

        def _abrir_pdf(tv, mapa):
            pd = mapa.get((tv.selection() or [None])[0])
            if pd is None:
                messagebox.showinfo("Abrir PDF",
                                    "Selecione um dos arquivos da lista.")
                return
            alvo = pasta / pd["fn"]
            try:
                os.startfile(str(alvo))
            except OSError as e:
                messagebox.showerror("Erro", f"Não consegui abrir:\n{alvo}\n\n{e}")

        escolhas = []
        for pe in duvidas:
            cands = sorted((c for c in pe["cands"] if c["pdf"]["used_by"] is None),
                           key=lambda c: -c["score"])
            vals = sorted(set(pe.get("valores") or [pe["valor"]]))
            titulo = f" R$ {_fmt_val(pe['valor'])}"
            outros = [v for v in vals if v != pe["valor"]]
            if outros:
                titulo += " (pago; nominal " + ", ".join(_fmt_val(v) for v in outros) + ")"
            titulo += f" — {pe['dataFull']} — {pe['conta']} "
            bloco = ttk.LabelFrame(quadro, text=titulo)
            bloco.pack(fill="x", padx=4, pady=6)

            for rotulo, texto in (("Descrição", pe["desc"] or "(sem descrição)"),
                                  ("Centro de custo", "; ".join(pe["works"]) or "—"),
                                  ("Nº doc", pe["doc"] or "—"),
                                  ("Categoria", pe.get("categoria") or "—")):
                ttk.Label(bloco, text=f"{rotulo}: {texto}", wraplength=1080,
                          justify="left").pack(anchor="w", padx=8)

            ttk.Label(bloco, text=f"{len(cands)} PDF(s) livre(s) com esse valor:"
                      ).pack(anchor="w", padx=8, pady=(8, 2))
            tv = ttk.Treeview(bloco, columns=("sinais", "arquivo", "data", "desc"),
                              show="headings", selectmode="browse",
                              height=min(max(len(cands) + 1, 2), 7))
            for col, cab, larg, estica in (("sinais", "O que bateu", 190, False),
                                           ("arquivo", "Arquivo", 470, False),
                                           ("data", "Data do PDF", 85, False),
                                           ("desc", "Descrição do PDF", 290, True)):
                tv.heading(col, text=cab)
                tv.column(col, width=larg, anchor="w", stretch=estica)
            tv.insert("", "end", iid="_nada",
                      values=("—", "(deixar em dúvida)", "", ""))
            mapa = {}
            for k, c in enumerate(cands):
                pd = c["pdf"]
                sinais = " ".join(s for s in ("✔ OC/NF" if c["ocnf"] else "",
                                              "✔ centro de custo" if c["cc"] else "",
                                              "✔ data" if c["date"] else "") if s)
                dt = pd["data"]
                tv.insert("", "end", iid=f"c{k}",
                          values=(sinais or "só o valor bate", pd["fn"],
                                  f"{dt[:2]}/{dt[2:]}" if dt else "—", pd["desc"]))
                mapa[f"c{k}"] = pd
            tv.selection_set("_nada")
            tv.pack(fill="x", padx=8, pady=(0, 4))
            tv.bind("<Double-1>", lambda e, t=tv, m=mapa: _abrir_pdf(t, m))

            botoes = ttk.Frame(bloco)
            botoes.pack(fill="x", padx=8, pady=(0, 6))
            ttk.Button(botoes, text="Abrir lançamento no navegador",
                       command=lambda i=pe["launchId"]: _abrir_url(LINK + str(i))
                       ).pack(side="right")
            ttk.Button(botoes, text="📄  Abrir PDF selecionado",
                       command=lambda t=tv, m=mapa: _abrir_pdf(t, m)
                       ).pack(side="right", padx=(0, 8))
            escolhas.append((pe, tv, mapa))

        def concluir(confirmar):
            canvas.unbind_all("<MouseWheel>")
            if confirmar:
                usados = set()
                for pe, tv, mapa in escolhas:
                    pd = mapa.get((tv.selection() or [None])[0])
                    if pd is None or id(pd) in usados or pd["used_by"] is not None:
                        continue        # mesmo PDF escolhido 2x: vale a 1ª escolha
                    usados.add(id(pd))
                    pd["used_by"] = pe["paidId"]
                    pe["match"] = {"pdf": pd, "ocnf": False, "cc": False,
                                   "date": False, "score": 0}
                    pe["pdf"] = pd["fn"]
                    pe["motivo"] = "escolhido por você"
                    pe["status"] = "CERTEZA"
            top.destroy()
            ev.set()

        b_ok = ttk.Button(rodape, text="✔ Confirmar escolhas",
                          command=lambda: concluir(True))
        b_ok.pack(side="left")
        try:
            b_ok.configure(style="Accent.TButton")
        except tk.TclError:
            pass
        ttk.Button(rodape, text="Deixar todas em dúvida",
                   command=lambda: concluir(False)).pack(side="left", padx=10)
        top.protocol("WM_DELETE_WINDOW", lambda: concluir(False))
        top.grab_set()

    # ---------------------------------------------------------------- etapa 2
    def conectar(self):
        ini, fim = _data_api(self.v_ini.get()), _data_api(self.v_fim.get())
        if not ini or not fim:
            messagebox.showerror("Erro", "Datas inválidas. Use dd/mm/aaaa."); return
        if self.v_modo.get() == "auto" and not Path(self.v_pasta.get() or "").is_dir():
            messagebox.showerror("Erro", "Selecione a pasta dos PDFs renomeados."); return
        self.b1.config(state="disabled")
        self.log.delete("1.0", "end"); self._ph = False
        self.lbl.config(text="Conectando...")
        self.pb.config(mode="indeterminate")
        self.pb.start(12)
        self.worker = self.exec.submit(self._t_conectar, ini, fim)

    def _t_conectar(self, ini, fim):
        inicio = time.time()
        self._log(f"⏱ Etapa 2 — início: {time.strftime('%H:%M:%S')}")

        def st(msg):                      # atualiza o texto de status da janela
            self.q.put(("status", msg))
        try:
            if self.mc is None:
                st("Abrindo o Chrome — faça o login se for pedido...")
            self.garantir_sessao()
            st("Capturando credenciais da tela de Pagamentos...")
            if not self.api.capturar_credenciais(self._log):
                raise RuntimeError("Não capturei a lista de pagamentos.")
            st("Buscando títulos pagos do período no servidor...")
            self._log(f"Buscando títulos PAGOS de {ini} a {fim} (todas as contas)...")

            def log_pg(m):
                self._log(m)
                st("Buscando títulos pagos — " + m.strip(" .") + "...")
            lanc = self.api.listar_pagos(ini, fim, log_pg)
            st("Organizando as contas bancárias...")
            self.pagos = mc_api.montar_pagos(lanc)
            contas = sorted({p["conta"] for p in self.pagos if p["conta"]})
            self._log(f"{len(lanc)} lançamento(s), {len(self.pagos)} pagamento(s), "
                      f"{len(contas)} conta(s) encontradas.")
            self._log(f"⏱ Etapa 2 — fim: {time.strftime('%H:%M:%S')} "
                      f"({_fmt_dur(time.time() - inicio)})")
            self.q.put(("contas", contas))
        except Exception as e:
            self._log(_texto_do_erro(e))
            self.q.put(("reabilitar", None))

    def _montar_contas(self, contas):
        for w in self.contas_box.winfo_children():
            w.destroy()
        self.vars_contas = {}
        cont = {c: 0 for c in contas}
        for p in self.pagos:
            if p["conta"] in cont:
                cont[p["conta"]] += 1
        colunas = 3
        for i, c in enumerate(contas):
            v = tk.BooleanVar(value=True)
            self.vars_contas[c] = v
            ttk.Checkbutton(self.contas_box, text=f"{c}  ({cont[c]})", variable=v
                            ).grid(row=i // colunas, column=i % colunas, sticky="w", padx=4)
        linha = len(contas) // colunas + 1
        ttk.Button(self.contas_box, text="Marcar todas",
                   command=lambda: [v.set(True) for v in self.vars_contas.values()]
                   ).grid(row=linha, column=0, sticky="w", pady=4)
        ttk.Button(self.contas_box, text="Desmarcar todas",
                   command=lambda: [v.set(False) for v in self.vars_contas.values()]
                   ).grid(row=linha, column=1, sticky="w")

    # ---------------------------------------------------------------- etapa 2
    def executar(self):
        if self.worker and not self.worker.done():
            return
        if self.v_modo.get() == "lista":
            if not Path(self.v_lista.get() or "").exists():
                messagebox.showerror("Erro", "Selecione a lista (.csv/.xlsx)."); return
            alvo = self._t_lista
        else:
            if not self.pagos:
                messagebox.showerror("Erro", "Primeiro clique em \"1. Carregar contas\"."); return
            alvo = self._t_auto
        self._parar.clear()
        self._pausa.clear()
        self.b_pause.config(text="⏸ Pausar", state="normal")
        self.b_stop.config(state="normal")
        self.b2.config(state="disabled")
        self.worker = self.exec.submit(alvo)

    def _t_auto(self):
        inicio = time.time()
        self._log(f"⏱ Etapa 3 — início: {time.strftime('%H:%M:%S')}")
        try:
            contas_sel = {c for c, v in self.vars_contas.items() if v.get()}
            if not contas_sel:
                self._log("[!] Nenhuma conta marcada."); self.q.put(("reabilitar2", None)); return
            pagos = [p for p in self.pagos if p["conta"] in contas_sel]
            termos = []
            if self.v_ign.get():
                termos += config.IGNORAR_TARIFAS
            if self.v_ign_ap.get():
                termos += config.IGNORAR_APORTES
            if termos:
                antes = len(pagos)
                pagos = [p for p in pagos
                         if not any(t in (_norm(p["desc"]) + " | " + _norm(p["categoria"]))
                                    for t in termos)]
                self._log(f"Ignorados por tipo: {antes - len(pagos)}")
            self._log(f"{len(pagos)} pagamento(s) nas contas marcadas. Verificando anexos...")

            if pagos and not self.api.capturar_credenciais_anexos(pagos[0]["launchId"]):
                raise RuntimeError("Não capturei as credenciais de anexos.")
            self.q.put(("max", len(pagos)))
            att = self.api.verificar_anexos([p["paidId"] for p in pagos], self._log,
                                            progresso=lambda i, n: self.q.put(("prog_verif", (i, n))),
                                            cancelar=self._checar_pausa)
            if self._parar.is_set():
                self._log("⏹ Interrompido pelo usuário durante a verificação.")
                self.q.put(("reabilitar2", None))
                return
            pendentes = [p for p in pagos if att.get(p["paidId"], 0) == 0]
            com = len(pagos) - len(pendentes)
            self._log(f"Com comprovante: {com} | SEM comprovante: {len(pendentes)}")
            self._log(f"⏱ Verificação de anexos: {_fmt_dur(time.time() - inicio)}")
            ini_anexar = time.time()

            pdfs = matcher.carregar_pdfs(Path(self.v_pasta.get()), self._log)
            self._log(f"{len(pdfs)} PDF(s) válidos na pasta.")
            certezas, duvidas, sem_par = matcher.casar(pendentes, pdfs)
            self._log(f"Casamentos com certeza: {len(certezas)} | dúvida: {len(duvidas)} "
                      f"| sem par: {len(sem_par)}\n")

            if duvidas and not self._parar.is_set():
                self._log("Abrindo a janela para você resolver as dúvidas...")
                ev = Event()
                self.q.put(("duvidas", (duvidas, ev)))
                while not ev.wait(timeout=0.5):
                    if self._parar.is_set():
                        break
                resolvidas = [p for p in duvidas if p["status"] == "CERTEZA"]
                if resolvidas:
                    self._log(f"{len(resolvidas)} dúvida(s) resolvida(s) por você.\n")
                    certezas += resolvidas
                    duvidas = [p for p in duvidas if p["status"] == "DUVIDA"]

            resultados = []
            self.q.put(("max", len(certezas)))
            pasta = Path(self.v_pasta.get())
            for i, pe in enumerate(certezas, 1):
                if self._checar_pausa():
                    self._log("⏹ Interrompido pelo usuário — gerando relatório "
                              "com o que já foi feito.")
                    break
                arq = pasta / pe["pdf"]
                vals = [_fmt_val(v) for v in pe.get("valores", [pe["valor"]])]
                r = self.mc.anexar(pe["launchId"], _fmt_val(pe["valor"]), arq,
                                   doc=pe["doc"] or None, dry_run=self.v_dry.get(),
                                   valores=vals)
                if r.startswith("erro:"):
                    self._log(f"   ({r}) — recarregando o sistema e tentando de novo...")
                    self.mc.resetar()
                    r = self.mc.anexar(pe["launchId"], _fmt_val(pe["valor"]), arq,
                                       doc=pe["doc"] or None, dry_run=self.v_dry.get(),
                                       valores=vals)
                pe["resultado"] = r
                resultados.append(pe)
                self.q.put(("prog", (i, sum(1 for x in resultados if not x["resultado"].startswith("erro")), 0)))
                self._log(f"[{i}/{len(certezas)}] {_fmt_val(pe['valor'])}  {pe['pdf']}  -> {r}")

            saida = self._relatorio(resultados, duvidas, sem_par)
            ok = sum(1 for x in resultados
                     if x["resultado"] in ("anexado", "anexado_sem_tag", "ja_tinha", "dry_run"))
            self._log(f"⏱ Anexos: {_fmt_dur(time.time() - ini_anexar)}")
            self._log(f"\nConcluído. Anexados/ok: {ok} de {len(certezas)}. Relatório: {saida}")
            self._log(f"⏱ Etapa 3 — fim: {time.strftime('%H:%M:%S')} "
                      f"(total: {_fmt_dur(time.time() - inicio)})")
            self.q.put(("fim", (ok, len(certezas), len(duvidas), len(sem_par), saida)))
        except Exception as e:
            self._log(_texto_do_erro(e))
            self.q.put(("reabilitar2", None))

    def _t_lista(self):
        inicio = time.time()
        self._log(f"⏱ Início: {time.strftime('%H:%M:%S')}")
        try:
            pasta_pdfs = self.v_pasta.get().strip() or None
            tarefas = planilha.carregar_tarefas(Path(self.v_lista.get()),
                                                pasta_pdfs=pasta_pdfs)
            self._log(f"{len(tarefas)} linha(s) na lista. Simular={self.v_dry.get()}")
            self.garantir_sessao()
            self.q.put(("max", len(tarefas)))
            ok = 0
            for i, t in enumerate(tarefas, 1):
                if self._checar_pausa():
                    self._log("⏹ Interrompido pelo usuário.")
                    break
                if not t["launchId"]:
                    r = "erro:sem_link_do_lancamento"
                elif not t["valor"]:
                    r = "erro:sem_valor"
                elif t["arquivo"] is None:
                    r = "erro:pdf_nao_encontrado_na_pasta"
                else:
                    r = self.mc.anexar(t["launchId"], t["valor"], t["arquivo"],
                                       doc=t.get("doc") or None, dry_run=self.v_dry.get())
                    if r.startswith("erro:"):
                        self._log(f"   ({r}) — recarregando o sistema e tentando de novo...")
                        self.mc.resetar()
                        r = self.mc.anexar(t["launchId"], t["valor"], t["arquivo"],
                                           doc=t.get("doc") or None,
                                           dry_run=self.v_dry.get())
                if r in ("anexado", "anexado_sem_tag", "ja_tinha", "dry_run"):
                    ok += 1
                self.q.put(("prog", (i, ok, i - ok)))
                self._log(f"[{i}/{len(tarefas)}] {t['valor']}  {t['arquivo_bruto']}  -> {r}")
            self._log(f"\nConcluído: {ok}/{len(tarefas)} ok.")
            self._log(f"⏱ Fim: {time.strftime('%H:%M:%S')} — tempo total: "
                      f"{_fmt_dur(time.time() - inicio)}")
            self.q.put(("fim", (ok, len(tarefas), 0, 0, "")))
        except Exception as e:
            self._log(_texto_do_erro(e))
            self.q.put(("reabilitar2", None))

    # ---------------------------------------------------------------- saída
    def _relatorio(self, anexados, duvidas, sem_par) -> str:
        wb = Workbook(); wb.remove(wb.active)
        verde = PatternFill("solid", fgColor="1B7837")
        branco = Font(bold=True, color="FFFFFF")
        H = ["Valor", "Data", "Centro de custo", "Conta", "Descrição", "Nº doc",
             "PDF", "Motivo/Candidatos", "Resultado", "Link"]

        def aba(nome, linhas):
            ws = wb.create_sheet(nome)
            for j, h in enumerate(H, 1):
                c = ws.cell(1, j, h); c.font = branco; c.fill = verde
            for i, r in enumerate(linhas, 2):
                for j, v in enumerate(r, 1):
                    ws.cell(i, j, v)
            for col, w in zip("ABCDEFGHIJ", [11, 9, 32, 26, 38, 16, 45, 30, 16, 58]):
                ws.column_dimensions[col].width = w
            ws.freeze_panes = "A2"

        aba("ANEXADOS", [[_fmt_val(p["valor"]), p["dataFull"], "; ".join(p["works"]),
                          p["conta"], p["desc"], p["doc"], p["pdf"], p["motivo"],
                          p.get("resultado", ""), LINK + p["launchId"]] for p in anexados])
        aba("DUVIDA", [[_fmt_val(p["valor"]), p["dataFull"], "; ".join(p["works"]),
                        p["conta"], p["desc"], p["doc"], "", _resumo_cands(p),
                        "", LINK + p["launchId"]] for p in duvidas])
        aba("SEM PAR", [[_fmt_val(p["valor"]), p["dataFull"], "; ".join(p["works"]),
                         p["conta"], p["desc"], p["doc"], "", "", "",
                         LINK + p["launchId"]] for p in sem_par])
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(self.v_pasta.get() or ".") / f"relatorio_anexos_{stamp}.xlsx"
        wb.save(out)
        return str(out).replace("\\", "/")

    # ---------------------------------------------------------------- UI pump
    def _drain(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    if getattr(self, "_ph", False):    # limpa o estado inicial
                        self.log.delete("1.0", "end"); self._ph = False
                    self.log.insert("end", val + "\n"); self.log.see("end")
                elif kind == "status":
                    self.lbl.config(text=val)
                elif kind == "max":
                    self.pb.stop()
                    self.pb.config(mode="determinate", maximum=max(val, 1), value=0)
                elif kind == "prog":
                    i, ok, err = val
                    self.pb.config(value=i)
                    self.lbl.config(text=f"{i} processados — {ok} ok" + (f", {err} erros" if err else ""))
                elif kind == "prog_verif":
                    i, n = val
                    self.pb.config(value=i)
                    self.lbl.config(text=f"Verificando comprovantes já anexados: {i}/{n}")
                elif kind == "contas":
                    self.pb.stop()
                    self.pb.config(mode="determinate", value=0)
                    self._montar_contas(val)
                    self.b1.config(state="normal")
                    self.b2.config(state="normal")
                    self.lbl.config(text="Contas carregadas. Marque as desejadas e clique em 3.")
                elif kind == "reabilitar0":
                    self.b0.config(state="normal")
                elif kind == "reabilitar":
                    self.pb.stop()
                    self.pb.config(mode="determinate", value=0)
                    self.b1.config(state="normal")
                    self.lbl.config(text="Erro ao carregar — veja o Registro.")
                elif kind == "reabilitar2":
                    self.b2.config(state="normal")
                    self.b_pause.config(text="⏸ Pausar", state="disabled")
                    self.b_stop.config(state="disabled")
                elif kind == "duvidas":
                    self._janela_duvidas(*val)
                elif kind == "fim":
                    ok, tot, duv, sp, saida = val
                    self.b2.config(state="normal")
                    self.b_pause.config(text="⏸ Pausar", state="disabled")
                    self.b_stop.config(state="disabled")
                    if saida:
                        self.ultimo_relatorio = saida
                        self.b_rel.config(state="normal")
                    self.lbl.config(text=f"Concluído: {ok}/{tot} ok"
                                    + (f" | {duv} dúvidas, {sp} sem par" if duv or sp else ""))
                    msg = f"Anexados/ok: {ok} de {tot}"
                    if duv or sp:
                        msg += f"\nDúvidas: {duv}\nSem par: {sp}"
                    if saida:
                        msg += f"\n\nRelatório:\n{saida}"
                    messagebox.showinfo("Concluído", msg)
        except queue.Empty:
            pass
        self.after(150, self._drain)

    def fechar(self):
        """Fecha o navegador e a thread de trabalho (chamar ao sair do app)."""
        try:
            if self.mc:
                # fecha o navegador na thread dele (exigência do Playwright)
                self.exec.submit(self.mc.__exit__, None, None, None).result(timeout=8)
        except Exception:
            pass
        try:
            self.exec.shutdown(wait=False)
        except Exception:
            pass


def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)   # texto nítido em telas HiDPI
    except Exception:
        pass
    root = tk.Tk()
    root.title("Anexar Comprovantes — Mais Controle")
    try:
        root.state("zoomed")            # janela ocupando a tela (Windows)
    except tk.TclError:
        root.geometry("1100x720")
    try:
        import sv_ttk                   # tema moderno (visual Windows 11)
        sv_ttk.set_theme("light")
    except Exception:
        pass
    app = AnexarFrame(root)
    app.pack(fill="both", expand=True)

    def _sair():
        app.fechar()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", _sair)
    root.mainloop()


if __name__ == "__main__":
    main()
