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

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

#: Duração e pasta-base vinham em cópias byte a byte por aba. Uma cópia de
#: regra de CAMINHO é como um app passa a procurar o mesmo arquivo em dois
#: lugares; uma de FORMATO é como a mesma duração aparece de dois jeitos.
_fmt_dur = util.fmt_dur
_pasta_base = util.pasta_base

try:                                     # widgets compartilhados (raiz)
    import widgets
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import widgets

#: A medida de layout que segue a fonte. `px(14)` são "os 14 px de quem
#: desenhou esta tela a 100%", ditos na escala de hoje — a 150% saem 21, e
#: a 100% saem os mesmos 14. Ver o bloco do `px` no `widgets.py`.
px = widgets.px

CampoData = widgets.CampoData

#: Erros que já explicam a si mesmos: a mensagem vai inteira para o log, sem
#: "[!]" na frente, porque ela É a entrega quando a planilha não sai.
ERROS_ESPERADOS = (ValidationError, WorkbookError, MappingError, ErpError)

#: A tabela de pasta mora em `util.MESES_PASTA`: as três cópias que
#: existiam aqui produzem NOME DE PASTA no disco, e uma divergir entre
#: elas parte o mês ao meio. O nome local continua porque é por ele que
#: o resto do módulo chama.
MESES = util.MESES_PASTA

#: Onde a planilha do dia é arquivada, junto do resto do fechamento.
RAIZ_SAIDA = Path("C:/Arquivos Morais/CONCILIACAO DIARIA")






class ConciliacaoFrame(ttk.Frame):
    def __init__(self, master, anexar_frame):
        super().__init__(master)
        self.anx = anexar_frame          # dono do navegador e da thread
        self.q = queue.Queue()
        self.worker = None
        self._parar = Event()
        self.ultimo_arquivo: Path | None = None
        # Último motivo de falha do `_drain`, para não repetir a mesma linha a
        # cada 150 ms (ver o `except` de lá).
        self._erro_drain = None

        sugerido = sugerir_periodo(datetime.date.today())
        self.v_ini = tk.StringVar(value=f"{sugerido.inicio:%d/%m/%Y}")
        self.v_fim = tk.StringVar(value=f"{sugerido.fim:%d/%m/%Y}")

        self._build()
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = px(widgets.PADX)

        cab = widgets.Cabecalho(
            self, "Saldo de pagamentos",
            "Lê os saldos e os pagamentos a vencer e gera o painel do dia, "
            "com o aporte mínimo de cada conta.",
            trilha="Diário  ›  Saldo de pagamentos")
        cab.pack(fill="x", padx=PADX, pady=px((16, 12)))
        # Ação única: o verde é o único botão do cabeçalho. O cartão "Gerar",
        # que existia só para segurá-lo, deixa de existir.
        self.b1 = widgets.Botao(cab.acoes, "Coletar e gerar o painel",
                                papel="acao", command=self.gerar)
        self.b1.pack(side="left")

        f1 = widgets.Cartao(self, "Vencimentos que entram", 1)
        f1.pack(fill="x", padx=PADX, pady=px((0, 12)))
        linha = ttk.Frame(f1)
        linha.pack(fill="x")
        widgets.Campo(linha, "De", lambda p: CampoData(p, self.v_ini)
                      ).pack(side="left", padx=px((0, 16)))
        widgets.Campo(linha, "Até", lambda p: CampoData(p, self.v_fim)
                      ).pack(side="left", padx=px((0, 16)))
        ttk.Label(linha, style="Tenue.TLabel",
                  text="na segunda já vem sábado + domingo + segunda"
                  ).pack(side="left", pady=px((15, 0)))

        acao = ttk.Frame(self, style="Fundo.TFrame")
        acao.pack(fill="x", padx=PADX, pady=px((0, 10)))
        btns = ttk.Frame(acao, style="Fundo.TFrame")
        btns.pack(side="right", padx=px((16, 0)))
        self.b_stop = widgets.Botao(btns, "⏹  Parar", papel="perigo",
                                    state="disabled", command=self._parar_click)
        self.b_stop.pack(side="left")
        self.b_abrir = widgets.Botao(btns, "📄  Abrir a planilha", papel="neutro",
                                     state="disabled",
                                     command=self._abrir_arquivo)
        self.b_abrir.pack(side="left", padx=px((8, 0)))
        self.b_pasta = widgets.Botao(btns, "📂  Abrir a pasta", papel="neutro",
                                     state="disabled", command=self._abrir_pasta)
        self.b_pasta.pack(side="left", padx=px((8, 0)))
        self.barra_exec = widgets.BarraExecucao(acao)
        self.barra_exec.pack(side="left", fill="x", expand=True)
        self.lbl = self.barra_exec.lbl
        self.pb = self.barra_exec.pb

        self.reg = widgets.Cartao(self, "Registro", padding=(12, 10))
        self.reg.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.log = tk.Text(self.reg, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0)
        self.log.pack(fill="both", expand=True)
        widgets.estilo_log(self.log)
        widgets.registro_elastico(self.reg, self.log)

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
                    widgets.registrar_atividade(
                        "con", "Painel de saldo", "ok",
                        str(self.lbl.cget("text"))[:120])
        except queue.Empty:
            pass
        except Exception as e:                              # noqa: BLE001
            # A bomba de UI NUNCA pode morrer, e por isso o reagendamento está
            # no `finally`. Um `tk.TclError` aqui (mexer num widget recém
            # destruído, por exemplo) parava o ciclo para sempre: o registro
            # congelava, os botões nunca voltavam e a coleta seguia rodando na
            # thread do Anexar — sem ninguém saber sequer se dava para fechar o
            # app. É o modelo do `_drain` do Anexar.
            #
            # O motivo vai para o próprio Registro, e não para o
            # `diagnostico.log`: esta aba não importa o `config` do Anexar, e
            # criar essa dependência só para registrar uma linha custaria mais
            # do que resolve. Só quando MUDA — repetido a cada 150 ms, ele
            # afogaria o que a pessoa precisa ler.
            motivo = repr(e)
            if motivo != self._erro_drain:
                self._erro_drain = motivo
                self.q.put(("log", f"[!] falha ao atualizar a tela: {motivo}"))
        finally:
            self.after(150, self._drain)

    def aplicar_cores(self, escuro: bool):
        try:
            widgets.estilo_log(self.log, escuro)
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
        # Recusar ANTES de desabilitar os botões: quem sai por aqui não passa
        # mais pelo `_drain`, e a aba ficava travada — botões apagados, nada
        # rodando — até reiniciar o app.
        if self.anx.avisar_se_ocupado("a Conciliação Diária"):
            return
        self._parar.clear()
        self.q.put(("botoes", "disabled"))
        self.q.put(("ocupado", True))
        self.worker = self.anx.submeter("Controle de saldo pgtos", self._t_gerar,
                                        periodo, dona=self)

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
