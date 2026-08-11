# -*- coding: utf-8 -*-
"""
Aba "Conciliação Diária": lê saldos e pagamentos do dia e gera o painel.

Compartilha o navegador e a thread do AnexarFrame, como a Conferência e os
Aportes. Aqui isso não é só conveniência: **o ERP aceita uma sessão por
usuário**, então uma janela própria derrubaria a sessão do Anexar e vice-versa.

A regra de negócio inteira vive em `conciliacao/` e não sabe que existe
interface — esta aba só escolhe o período, empresta a página e mostra o que
voltou.
"""
from __future__ import annotations

import datetime
import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from threading import Event
from tkinter import messagebox, ttk

from conciliacao.config import load_config
from conciliacao.errors import ErpError
from conciliacao.mapping import AccountMapping, MappingError
from conciliacao.models import Periodo, sugerir_periodo
from conciliacao.pipeline import run_offline
from conciliacao.snapshot import save as salvar_snapshot
from conciliacao.validate import ValidationError
from conciliacao.workbook import WorkbookError

#: Erros que já explicam a si mesmos: a mensagem vai inteira para o log, sem
#: "[!]" na frente, porque ela É a entrega quando a planilha não sai.
ERROS_ESPERADOS = (ValidationError, WorkbookError, MappingError, ErpError)

MESES = ("JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO",
         "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO")

#: Onde a planilha do dia é arquivada, junto do resto do fechamento.
RAIZ_SAIDA = Path("C:/Arquivos Morais/CONCILIACAO DIARIA")


def _pasta_base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _fmt_dur(seg: float) -> str:
    seg = int(seg)
    return f"{seg // 60}min {seg % 60}s" if seg >= 60 else f"{seg}s"


class ConciliacaoFrame(ttk.Frame):
    def __init__(self, master, anexar_frame):
        super().__init__(master)
        self.anx = anexar_frame          # dono do navegador e da thread
        self.q = queue.Queue()
        self.worker = None
        self._parar = Event()
        self.ultimo_arquivo: Path | None = None

        sugerido = sugerir_periodo(datetime.date.today())
        self.v_ini = tk.StringVar(value=f"{sugerido.inicio:%d/%m/%Y}")
        self.v_fim = tk.StringVar(value=f"{sugerido.fim:%d/%m/%Y}")

        self._build()
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = 14

        cab = ttk.Frame(self)
        cab.pack(fill="x", padx=PADX, pady=(12, 4))
        ttk.Label(cab, text="Conciliação Diária",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(cab, foreground="#6b6b6b",
                  text="Lê os saldos e os pagamentos a vencer e gera o painel "
                       "do dia, com o aporte mínimo de cada conta."
                  ).pack(anchor="w")

        f1 = ttk.LabelFrame(self, text=" 1. Vencimentos que entram ",
                            padding=(12, 8, 12, 10))
        f1.pack(fill="x", padx=PADX, pady=6)
        linha = ttk.Frame(f1); linha.pack(fill="x")
        ttk.Label(linha, text="De:").pack(side="left")
        ttk.Entry(linha, textvariable=self.v_ini, width=12).pack(side="left", padx=(6, 12))
        ttk.Label(linha, text="até:").pack(side="left")
        ttk.Entry(linha, textvariable=self.v_fim, width=12).pack(side="left", padx=(6, 12))
        ttk.Label(linha, foreground="#6b6b6b",
                  text="(dd/mm/aaaa — na segunda já vem sábado + domingo + segunda)"
                  ).pack(side="left")

        f2 = ttk.LabelFrame(self, text=" 2. Gerar ", padding=(12, 8, 12, 10))
        f2.pack(fill="x", padx=PADX, pady=6)
        self.b1 = ttk.Button(f2, text="▶ Coletar e gerar o painel",
                             command=self.gerar)
        self.b1.pack(side="left")
        self.b_stop = ttk.Button(f2, text="⏹ Parar", state="disabled",
                                 command=self._parar_click)
        self.b_stop.pack(side="left", padx=(8, 0))
        self.b_abrir = ttk.Button(f2, text="📄 Abrir a planilha", state="disabled",
                                  command=self._abrir_arquivo)
        self.b_abrir.pack(side="left", padx=(8, 0))
        self.b_pasta = ttk.Button(f2, text="📂 Abrir a pasta", state="disabled",
                                  command=self._abrir_pasta)
        self.b_pasta.pack(side="left", padx=(8, 0))
        try:
            self.b1.configure(style="Accent.TButton")
        except tk.TclError:
            pass

        prog = ttk.Frame(self); prog.pack(fill="x", padx=PADX)
        self.pb = ttk.Progressbar(prog, mode="indeterminate")
        self.pb.pack(fill="x")
        self.lbl = ttk.Label(prog, text="Pronto.", foreground="#6b6b6b")
        self.lbl.pack(anchor="w", pady=(4, 0))

        reg = ttk.LabelFrame(self, text=" Registro ", padding=(10, 6, 10, 10))
        reg.pack(fill="both", expand=True, padx=PADX, pady=6)
        self.log = tk.Text(reg, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0, height=14, font=("Consolas", 10))
        self.log.pack(fill="both", expand=True)

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
                elif tipo == "ocupado":
                    (self.pb.start(12) if valor else self.pb.stop())
                elif tipo == "botoes":
                    self.b1.configure(state=valor)
                    self.b_stop.configure(
                        state="disabled" if valor == "normal" else "normal")
                elif tipo == "pronto":
                    self.ultimo_arquivo = valor
                    self.b_abrir.configure(state="normal")
                    self.b_pasta.configure(state="normal")
        except queue.Empty:
            pass
        self.after(150, self._drain)

    def aplicar_cores(self, escuro: bool):
        fundo = "#1c1c1c" if escuro else "#ffffff"
        frente = "#e8e8e8" if escuro else "#000000"
        try:
            self.log.configure(background=fundo, foreground=frente,
                               insertbackground=frente)
        except tk.TclError:
            pass

    def _parar_click(self):
        self._parar.set()
        self.lbl.configure(text="Parando...")
        self.b_stop.configure(state="disabled")

    def _abrir_arquivo(self):
        self._abrir(self.ultimo_arquivo)

    def _abrir_pasta(self):
        self._abrir(self.ultimo_arquivo.parent if self.ultimo_arquivo else None)

    @staticmethod
    def _abrir(alvo: Path | None):
        if alvo and alvo.exists():
            try:
                os.startfile(alvo)                      # noqa: S606 (Windows)
            except Exception:
                subprocess.Popen(["explorer", str(alvo)])

    # ------------------------------------------------------------- execução
    def _periodo(self) -> Periodo:
        ini = datetime.datetime.strptime(self.v_ini.get().strip(), "%d/%m/%Y").date()
        fim = datetime.datetime.strptime(self.v_fim.get().strip(), "%d/%m/%Y").date()
        if ini > fim:
            ini, fim = fim, ini
        return Periodo(inicio=ini, fim=fim)

    def _config_do_dia(self, periodo: Periodo):
        """Config com a saída apontada para a árvore do fechamento.

        A planilha do dia vai para <raiz>/<ANO>/<MÊS>; logs e snapshots ficam
        fora da divisão por mês, porque são diagnóstico e não entrega. Como
        `Config.caminho()` faz `raiz / valor` e Path respeita caminho absoluto,
        basta trocar os valores — o config.yaml não muda."""
        base = _pasta_base()
        cfg = load_config(base / "config.yaml")
        mes = RAIZ_SAIDA / str(periodo.fim.year) / MESES[periodo.fim.month - 1]
        return replace(cfg, caminhos={
            **cfg.caminhos,
            "modelo": str(base / cfg.caminhos.get("modelo", "MODELO.xlsx")),
            "saida": str(mes),
            "logs": str(RAIZ_SAIDA / "logs"),
            "snapshots": str(RAIZ_SAIDA / "snapshots"),
            "screenshots": str(RAIZ_SAIDA / "screenshots"),
        })

    #: Quanto esperamos você entrar na janela do Chrome, antes de desistir.
    ESPERA_LOGIN_S = 240

    def _esperar_sessao(self):
        """Não coleta sem sessão confirmada no navegador.

        `garantir_login()` devolve False quando não confirma a sessão, mas
        `garantir_sessao()` ignora esse retorno — e a coleta seguia às cegas.
        Sem sessão, o ERP abre a tela de pagamentos e responde SEM DADOS: a
        grade mostra "Nenhum registro encontrado" e o erro que chega ao
        usuário é "a grade não carregou nenhuma linha", que aponta para o
        lugar errado (parece layout mudado, é sessão faltando).

        A leitura de saldos não denuncia o problema porque vai por uma API
        com login próprio, sem navegador — ela funciona mesmo sem sessão.
        """
        cli = self.anx.mc
        if cli._esta_logado():
            return
        self._log("")
        self._log("Preciso que você entre na janela do Chrome que abriu.")
        self._log("Assim que o Mais Controle carregar, eu sigo sozinho.")
        self.q.put(("status", "Aguardando seu login na janela do Chrome..."))
        for _ in range(self.ESPERA_LOGIN_S):
            if self._parar.is_set():
                raise RuntimeError("interrompido antes de entrar no Mais Controle.")
            if cli._esta_logado():
                self._log("Login confirmado — seguindo.")
                return
            time.sleep(1)
        raise RuntimeError(
            "não confirmei o login no Mais Controle.\n"
            "Sem a sessão do navegador a tela de pagamentos vem vazia, e o "
            "painel sairia errado — por isso parei aqui.\n"
            "Entre na janela do Chrome e rode de novo."
        )

    def gerar(self):
        if self.worker and not self.worker.done():
            return
        try:
            periodo = self._periodo()
        except ValueError:
            messagebox.showwarning("Período", "Use datas no formato dd/mm/aaaa.")
            return
        self._parar.clear()
        self.q.put(("botoes", "disabled"))
        self.q.put(("ocupado", True))
        self.worker = self.anx.exec.submit(self._t_gerar, periodo)

    def _t_gerar(self, periodo: Periodo):
        from conciliacao.erp.collect import coletar_com_pagina

        comeco = time.time()
        try:
            cfg = self._config_do_dia(periodo)
            mapping = AccountMapping.load(_pasta_base() / "mapping.yaml")

            self.q.put(("status", "Entrando no Mais Controle..."))
            self.anx.garantir_sessao(self._log)
            self._esperar_sessao()

            self.q.put(("status", "Coletando saldos e pagamentos..."))

            def revalidar():
                """Refaz o login do navegador depois da API de saldos.

                A API loga com o mesmo usuário, e o ERP só admite uma sessão —
                a do navegador cai. Sem isto, a grade de pagamentos vem vazia
                e o log fica sem sentido: "Login OK", 36 contas lidas, e
                nenhuma linha."""
                self.anx.mc.garantir_login()
                self._esperar_sessao()

            snapshot = coletar_com_pagina(
                self.anx.mc.page, cfg, periodo=periodo,
                revalidar_sessao=revalidar, log=self._log)

            caminho_snap = salvar_snapshot(snapshot, cfg.caminho("snapshots"))
            self._log(f"Snapshot: {str(caminho_snap).replace(chr(92), '/')}")

            if self._parar.is_set():
                self._log("\nInterrompido — nada foi gerado.")
                self.q.put(("status", "Interrompido."))
                return

            self.q.put(("status", "Conferindo e gerando a planilha..."))
            resultado = run_offline(snapshot, cfg, mapping)

            self._log("")
            self._log(resultado.resumo)
            if resultado.arquivo:
                self._log(f"\nPlanilha: {str(resultado.arquivo).replace(chr(92), '/')}")
                self.q.put(("pronto", resultado.arquivo))
            self.q.put(("status",
                        f"Painel gerado em {_fmt_dur(time.time() - comeco)}."))

        except ERROS_ESPERADOS as e:
            # Erro de regra: a mensagem já explica o que houve e por que a
            # planilha NÃO foi gerada. Gerar um painel com número errado é pior
            # do que não gerar — o texto do erro é a entrega aqui.
            self._log("")
            self._log("A PLANILHA NÃO FOI GERADA")
            self._log(str(e))
            self.q.put(("status", "Não gerei a planilha — veja o motivo acima."))
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] {e}")
            self.q.put(("status", "A conciliação parou por um erro."))
        finally:
            self.q.put(("ocupado", False))
            self.q.put(("botoes", "normal"))
