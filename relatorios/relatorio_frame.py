# -*- coding: utf-8 -*-
"""
Aba "Relatório Mensal": baixa em PDF o extrato de cada conta bancária.

Compartilha o navegador e a thread do AnexarFrame — o Playwright síncrono só
aceita uma thread, e abrir um segundo Chrome significaria um segundo login.
É o mesmo arranjo da Conferência e dos Aportes.
"""
from __future__ import annotations

import calendar
import datetime
import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from threading import Event
from tkinter import messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

import contas_mc                                             # noqa: E402
import extrato_mc                                            # noqa: E402

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def _pasta_base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _fmt_dur(seg: float) -> str:
    seg = int(seg)
    return f"{seg // 60}min {seg % 60}s" if seg >= 60 else f"{seg}s"


class RelatorioFrame(ttk.Frame):
    def __init__(self, master, anexar_frame):
        super().__init__(master)
        self.anx = anexar_frame          # dono do navegador e da thread
        self.q = queue.Queue()
        self.worker = None
        self._parar = Event()
        self.contas: list[dict] = []
        self.vars_contas: dict[str, tk.BooleanVar] = {}
        self.ultima_pasta: Path | None = None
        self.mapa: contas_mc.Mapa | None = None
        self.sem_destino: set[str] = set()

        hoje = datetime.date.today()
        anterior = hoje.replace(day=1) - datetime.timedelta(days=1)
        self.v_mes = tk.StringVar(value=MESES[anterior.month - 1])
        self.v_ano = tk.StringVar(value=str(anterior.year))
        self.v_personalizado = tk.BooleanVar(value=False)
        self.v_ini = tk.StringVar(value=f"{anterior.replace(day=1):%d/%m/%Y}")
        self.v_fim = tk.StringVar(value=f"{anterior:%d/%m/%Y}")
        self.v_pasta = tk.StringVar(value="(definido em contas_mc.json)")

        self._build()
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = 14

        cab = ttk.Frame(self)
        cab.pack(fill="x", padx=PADX, pady=(12, 4))
        ttk.Label(cab, text="Relatório Mensal",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(cab, foreground="#6b6b6b",
                  text="Baixa o extrato de cada conta bancária do período, "
                       "com todos os lançamentos, num PDF por conta."
                  ).pack(anchor="w")

        # ---- card 1: período
        f1 = ttk.LabelFrame(self, text=" 1. Período ", padding=(12, 8, 12, 10))
        f1.pack(fill="x", padx=PADX, pady=6)

        linha = ttk.Frame(f1); linha.pack(fill="x")
        ttk.Label(linha, text="Mês:").pack(side="left")
        self.cb_mes = ttk.Combobox(linha, textvariable=self.v_mes, values=MESES,
                                   state="readonly", width=12)
        self.cb_mes.pack(side="left", padx=(6, 14))
        ttk.Label(linha, text="Ano:").pack(side="left")
        anos = [str(a) for a in range(datetime.date.today().year + 1, 2019, -1)]
        self.cb_ano = ttk.Combobox(linha, textvariable=self.v_ano, values=anos,
                                   state="readonly", width=7)
        self.cb_ano.pack(side="left", padx=(6, 14))
        self.lbl_periodo = ttk.Label(linha, foreground="#6b6b6b")
        self.lbl_periodo.pack(side="left")

        pers = ttk.Frame(f1); pers.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(pers, text="Usar um intervalo de datas em vez do mês inteiro",
                        variable=self.v_personalizado,
                        command=self._alternar_periodo).pack(anchor="w")
        self.f_datas = ttk.Frame(f1)
        ttk.Label(self.f_datas, text="De:").pack(side="left")
        ttk.Entry(self.f_datas, textvariable=self.v_ini, width=12).pack(side="left", padx=(6, 14))
        ttk.Label(self.f_datas, text="até:").pack(side="left")
        ttk.Entry(self.f_datas, textvariable=self.v_fim, width=12).pack(side="left", padx=(6, 8))
        ttk.Label(self.f_datas, text="(dd/mm/aaaa)", foreground="#6b6b6b").pack(side="left")

        for var in (self.v_mes, self.v_ano):
            var.trace_add("write", lambda *_: self._atualizar_rotulo())
        self._atualizar_rotulo()

        # ---- card 2: contas
        f2 = ttk.LabelFrame(self, text=" 2. Contas bancárias (marque as desejadas) ",
                            padding=(12, 8, 12, 10))
        f2.pack(fill="both", expand=True, padx=PADX, pady=6)

        # Lista rolável: são ~34 contas, com nomes longos.
        self.canvas = tk.Canvas(f2, height=150, highlightthickness=0, borderwidth=0)
        barra = ttk.Scrollbar(f2, orient="vertical", command=self.canvas.yview)
        self.contas_box = ttk.Frame(self.canvas)
        self.contas_box.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.janela_lista = self.canvas.create_window((0, 0), window=self.contas_box,
                                                      anchor="nw")
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self.janela_lista, width=e.width))
        self.canvas.configure(yscrollcommand=barra.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        self.lbl_vazio = ttk.Label(
            self.contas_box, text='Clique em "1. Carregar contas" para listar as contas.')
        self.lbl_vazio.pack(anchor="w")

        # ---- card 3: destino
        # O destino não é mais escolhido à mão: cada conta tem o seu, definido
        # em contas_mc.json. O campo virou informação, não decisão.
        f3 = ttk.LabelFrame(self, text=" 3. Onde salva ", padding=(12, 8, 12, 10))
        f3.pack(fill="x", padx=PADX, pady=6)
        ttk.Entry(f3, textvariable=self.v_pasta, state="readonly"
                  ).pack(side="left", fill="x", expand=True)
        ttk.Label(f3, foreground="#6b6b6b",
                  text="  cada conta vai para a pasta da sua empresa"
                  ).pack(side="left")

        # ---- barra de ação
        acao = ttk.Frame(self)
        acao.pack(side="bottom", fill="x", padx=PADX, pady=(6, 12))
        prog = ttk.Frame(acao); prog.pack(side="bottom", fill="x", pady=(8, 0))
        self.lbl = ttk.Label(prog, text="Pronto.")
        self.lbl.pack(side="left")
        self.pb = ttk.Progressbar(prog, mode="determinate")
        self.pb.pack(side="left", fill="x", expand=True, padx=12)

        btns = ttk.Frame(acao); btns.pack(fill="x")
        self.b1 = ttk.Button(btns, text="▶ 1. Carregar contas", command=self.carregar)
        self.b1.pack(side="left")
        self.b2 = ttk.Button(btns, text="▶ 2. Gerar os extratos", command=self.gerar,
                             state="disabled")
        self.b2.pack(side="left", padx=10)
        self.b_stop = ttk.Button(btns, text="⏹ Parar", command=self._parar_click,
                                 state="disabled")
        self.b_stop.pack(side="left")
        self.b_abrir = ttk.Button(btns, text="📂 Abrir pasta", command=self._abrir_pasta,
                                  state="disabled")
        self.b_abrir.pack(side="left", padx=(10, 0))
        for b in (self.b1, self.b2):
            try:
                b.configure(style="Accent.TButton")
            except tk.TclError:
                pass

        # ---- registro
        reg = ttk.LabelFrame(self, text=" Registro ", padding=(10, 6, 10, 10))
        reg.pack(fill="both", expand=True, padx=PADX, pady=6)
        self.log = tk.Text(reg, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0, height=8, font=("Consolas", 10))
        self.log.pack(fill="both", expand=True)

    def _alternar_periodo(self):
        if self.v_personalizado.get():
            self.f_datas.pack(fill="x", pady=(6, 0))
        else:
            self.f_datas.pack_forget()
        self._atualizar_rotulo()

    def _atualizar_rotulo(self):
        try:
            ini, fim = self._periodo()
        except ValueError:
            self.lbl_periodo.configure(text="")
            return
        self.lbl_periodo.configure(text=f"→ {ini:%d/%m/%Y} a {fim:%d/%m/%Y}")

    def _periodo(self) -> tuple[datetime.date, datetime.date]:
        """Datas escolhidas. Levanta ValueError se o que foi digitado não serve."""
        if self.v_personalizado.get():
            ini = datetime.datetime.strptime(self.v_ini.get().strip(), "%d/%m/%Y").date()
            fim = datetime.datetime.strptime(self.v_fim.get().strip(), "%d/%m/%Y").date()
            if ini > fim:
                ini, fim = fim, ini
            return ini, fim
        mes = MESES.index(self.v_mes.get()) + 1
        ano = int(self.v_ano.get())
        return (datetime.date(ano, mes, 1),
                datetime.date(ano, mes, calendar.monthrange(ano, mes)[1]))

    def _nome_do_periodo(self, ini: datetime.date, fim: datetime.date) -> str:
        """Nome da subpasta: o mês por extenso ("Julho 2026").

        Com o ano junto para não misturar julhos de anos diferentes. Só quando
        o período não é um mês fechado é que caem as duas datas no nome.
        """
        mes_fechado = (ini.day == 1
                       and fim.day == calendar.monthrange(fim.year, fim.month)[1]
                       and (ini.year, ini.month) == (fim.year, fim.month))
        if mes_fechado:
            return f"{MESES[ini.month - 1]} {ini.year}"
        return f"{ini:%d-%m-%Y} a {fim:%d-%m-%Y}"

    def _garantir_mapa(self) -> bool:
        """Carrega o mapa conta→pasta, avisando de forma legível quando falta."""
        if self.mapa is not None:
            return True
        try:
            self.mapa = contas_mc.carregar()
        except contas_mc.MapaInvalido as e:
            self._log(f"[!] {e}")
            return False
        self.v_pasta.set(str(self.mapa.raiz).replace("\\", "/"))
        return True

    def _abrir_pasta(self):
        if self.ultima_pasta and self.ultima_pasta.exists():
            try:
                os.startfile(self.ultima_pasta)          # noqa: S606 (Windows)
            except Exception:
                subprocess.Popen(["explorer", str(self.ultima_pasta)])

    def _parar_click(self):
        self._parar.set()
        self.lbl.configure(text="Parando após a conta atual...")
        self.b_stop.configure(state="disabled")

    def aplicar_cores(self, escuro: bool):
        fundo = "#1c1c1c" if escuro else "#ffffff"
        frente = "#e8e8e8" if escuro else "#000000"
        try:
            self.log.configure(background=fundo, foreground=frente,
                               insertbackground=frente)
            self.canvas.configure(background=fundo)
        except tk.TclError:
            pass

    # ------------------------------------------------------------- mensagens
    def _log(self, msg=""):
        self.q.put(("log", msg))

    def _drain(self):
        try:
            while True:
                tipo, valor = self.q.get_nowait()
                if tipo == "log":
                    self.log.insert("end", f"{valor}\n")
                    self.log.see("end")
                elif tipo == "status":
                    self.lbl.configure(text=valor)
                elif tipo == "progresso":
                    feitos, total = valor
                    self.pb.configure(maximum=max(total, 1), value=feitos)
                elif tipo == "contas":
                    self._montar_contas(valor)
                elif tipo == "botoes":
                    self.b1.configure(state=valor)
                    self.b2.configure(
                        state="normal" if valor == "normal" and self.contas else "disabled")
                    self.b_stop.configure(
                        state="disabled" if valor == "normal" else "normal")
                elif tipo == "pasta_pronta":
                    self.ultima_pasta = valor
                    self.b_abrir.configure(state="normal")
        except queue.Empty:
            pass
        self.after(150, self._drain)

    # ------------------------------------------------------------- etapa 1
    def carregar(self):
        if self.worker and not self.worker.done():
            return
        self.q.put(("botoes", "disabled"))
        self.b_stop.configure(state="disabled")
        self.q.put(("status", "Abrindo o Mais Controle e lendo as contas..."))
        self.worker = self.anx.exec.submit(self._t_carregar)

    def _t_carregar(self):
        try:
            if not self._garantir_mapa():
                self.q.put(("status", "Falta o mapa contas_mc.json."))
                return
            self.anx.garantir_sessao(self._log)
            self._log("Lendo as contas bancárias...")
            contas = extrato_mc.listar_contas(self.anx.mc.page)
            self.contas = contas
            self._log(f"{len(contas)} conta(s) encontradas.")
            self.q.put(("contas", contas))
            self.q.put(("status", "Contas carregadas. Marque as desejadas e clique em 2."))
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui carregar as contas."))
        finally:
            self.q.put(("botoes", "normal"))

    def _montar_contas(self, contas):
        for w in self.contas_box.winfo_children():
            w.destroy()
        self.vars_contas = {}
        self.sem_destino = set()
        for conta in contas:
            # A lista vem do ERP; o mapa só diz onde salvar. Conta que o mapa
            # não conhece nasce DESMARCADA e avisando — melhor não baixar do
            # que baixar sem saber o destino.
            destino = self.mapa.de(conta["nome"]) if self.mapa else None
            if destino is None:
                self.sem_destino.add(conta["id"])
            v = tk.BooleanVar(value=destino is not None)
            self.vars_contas[conta["id"]] = v
            rotulo = (f'{conta["nome"]}   →   {destino.empresa} / {destino.pasta}'
                      if destino else f'{conta["nome"]}   (sem pasta no mapa)')
            ttk.Checkbutton(self.contas_box, text=rotulo, variable=v).pack(anchor="w")
        rodape = ttk.Frame(self.contas_box)
        rodape.pack(anchor="w", pady=(6, 0))
        ttk.Button(rodape, text="Marcar todas",
                   command=lambda: [v.set(True) for v in self.vars_contas.values()]
                   ).pack(side="left")
        ttk.Button(rodape, text="Desmarcar todas",
                   command=lambda: [v.set(False) for v in self.vars_contas.values()]
                   ).pack(side="left", padx=6)
        self.b2.configure(state="normal")

    # ------------------------------------------------------------- etapa 2
    def gerar(self):
        if self.worker and not self.worker.done():
            return
        try:
            ini, fim = self._periodo()
        except ValueError:
            messagebox.showwarning("Período", "Use datas no formato dd/mm/aaaa.")
            return
        escolhidas = [c for c in self.contas if self.vars_contas.get(c["id"]) and
                      self.vars_contas[c["id"]].get()]
        if not escolhidas:
            messagebox.showinfo("Relatório Mensal", "Marque ao menos uma conta.")
            return
        # Conta sem destino trava ANTES do primeiro download: com o lote no
        # meio do caminho, decidir onde salvar vira improviso.
        orfas = [c["nome"] for c in escolhidas if c["id"] in self.sem_destino]
        if orfas:
            messagebox.showwarning(
                "Contas sem pasta",
                "Estas contas não estão no contas_mc.json e eu não sei onde "
                "salvá-las:\n\n" + "\n".join(f"  {n}" for n in orfas[:10])
                + ("\n  ..." if len(orfas) > 10 else "")
                + "\n\nDesmarque-as ou acrescente-as ao mapa.")
            return

        self._parar.clear()
        self.q.put(("botoes", "disabled"))
        self.q.put(("progresso", (0, len(escolhidas))))
        self.worker = self.anx.exec.submit(self._t_gerar, escolhidas, ini, fim)

    def _t_gerar(self, contas, ini, fim):
        comeco = time.time()
        ini_txt, fim_txt = f"{ini:%d/%m/%Y}", f"{fim:%d/%m/%Y}"
        ano, mes = ini.year, ini.month          # o nome do arquivo segue o início
        pasta_mes = contas_mc.caminho_do_mes(self.mapa, ano, mes)
        pagina = None
        try:
            self.anx.garantir_sessao(self._log)
            pagina = self.anx.mc.page
            self._log(f"\nExtratos de {ini_txt} a {fim_txt} — {len(contas)} conta(s)")
            self._log(f"Pasta do mês: {str(pasta_mes).replace(chr(92), '/')}")

            feitos, vazios, falhas = [], [], []
            for i, conta in enumerate(contas, 1):
                if self._parar.is_set():
                    self._log("\nInterrompido a pedido.")
                    break
                nome = conta["nome"]
                self.q.put(("status", f"{i}/{len(contas)} — {nome[:45]}"))
                marca = time.time()
                try:
                    destino = self.mapa.de(nome)
                    if destino is None:         # a interface já barra, mas o
                        raise RuntimeError("conta sem pasta no mapa")  # mapa manda
                    arquivo = contas_mc.caminho_do_arquivo(self.mapa, destino, ano, mes)

                    extrato_mc.abrir_extrato(pagina, conta["id"], ini_txt, fim_txt)
                    n = extrato_mc.carregar_tudo(pagina, parar=self._parar.is_set)

                    # Confere ANTES de gravar: conta certa e paginação encerrada.
                    # Se o usuário interrompeu, o extrato está pela metade de
                    # propósito — aí não se grava nada.
                    if self._parar.is_set():
                        self._log(f"  {i}/{len(contas)} {nome[:50]} — interrompido, não salvei")
                        break
                    problemas = extrato_mc.conferir_antes_de_salvar(
                        extrato_mc.estado(pagina), nome)
                    if problemas:
                        raise RuntimeError("; ".join(problemas))

                    extrato_mc.salvar_pdf(pagina, arquivo)
                    kb = arquivo.stat().st_size // 1024
                    self._log(f"  {i}/{len(contas)} {nome[:44]} — {n} lançamento(s), "
                              f"{kb} KB, {_fmt_dur(time.time() - marca)}")
                    self._log(f"      → {destino.empresa} / {destino.pasta} / {arquivo.name}")
                    feitos.append(arquivo)
                    if not n:
                        vazios.append(nome)
                except Exception as e:
                    self._log(f"  {i}/{len(contas)} {nome[:50]} — FALHOU: {e}")
                    falhas.append(nome)
                self.q.put(("progresso", (i, len(contas))))

            self._log(f"\n{len(feitos)} extrato(s) gerados em "
                      f"{_fmt_dur(time.time() - comeco)}.")
            if vazios:
                self._log(f"{len(vazios)} sem lançamentos no período: "
                          + ", ".join(vazios[:5]) + (" ..." if len(vazios) > 5 else ""))
            if falhas:
                self._log(f"{len(falhas)} com problema: " + ", ".join(falhas[:5]))
            if feitos:
                self.q.put(("pasta_pronta", pasta_mes))
            self.q.put(("status", f"{len(feitos)} PDF(s) em "
                                  f"{str(pasta_mes).replace(chr(92), '/')}"))
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui gerar os extratos."))
        finally:
            # A impressão deixa a página só com o modal: sem restaurar, as
            # outras abas encontrariam um navegador sem app nenhum.
            if pagina is not None:
                extrato_mc.restaurar_pagina(pagina)
            self.q.put(("botoes", "normal"))
