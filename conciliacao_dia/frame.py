# -*- coding: utf-8 -*-
"""Aba "Conciliação" (grupo DIÁRIO): dois ambientes, "Baixar OFX" e
"Provar saldos" (spec de 29/10/2026).

Só desenha e chama: a regra mora em `ofx_regras`, a rodada em `rodada`, os
motores em `extratos_sicoob.ofx_periodo`, `baixar_comprovantes.inter_ofx` e
`importar_erp`. Três threads, como no resto do app: a do ERP é a vaga do
Anexar (`anx.submeter(..., dona=self)`, avisando antes com
`avisar_se_ocupado`); a dos bancos é a `ofx-bancos` (o `SicoobClient` e o
Chrome de cada conta do Inter nascem e morrem nela); a tela só lê a fila.

**"Ler as contas do ERP"** é o primeiro passo dos DOIS ambientes: a lista do
OFX e a Prova de saldos precisam saber quais contas do ERP são do Sicoob e
do Inter (antes a prova usava a leitura do "Buscar" de Pagamentos do dia).
A Prova de saldos mora em `tela_do_dia/prova_*`; esta aba é o hospedeiro
dela (`anx`, `cfg`, `mapping`, `contas_erp`, `_log`, `_abrir`,
`_pasta_pagamentos`).
"""
from __future__ import annotations

import datetime
import os
import queue
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import util
import widgets
from tela_do_dia.prova_na_tela import ProvaNaTela

from . import ofx_regras as r

TITULO = "Conciliação"
OCUPADO = "Conciliação — Baixar OFX"
MARCADA, DESMARCADA = "☑", "☐"
GRUPO_DIA, GRUPO_OUTRAS = "dia", "outras"
SEM_LEITURA = "Leia as contas do ERP para montar a lista."
px = widgets.px


def _ajuda(pai, texto, *, pady=0):
    """Texto que quebra na largura do cartão (o `_ajuda` da tela do dia)."""
    lbl = ttk.Label(pai, style="Tenue.TLabel", text=texto, justify="left")
    lbl.pack(fill="x", anchor="w", pady=pady)

    def _quebrar(e):
        if e.width > 1 and str(lbl.cget("wraplength")) != str(e.width):
            lbl.configure(wraplength=e.width)
    lbl.bind("<Configure>", _quebrar, add="+")
    return lbl


class ConciliacaoDiaFrame(ttk.Frame):
    COLS_LISTA = (("banco", "BANCO", 80, "w"), ("aviso", "AVISO", 260, "w"))
    COLS_RESULTADO = (("periodo", "PERÍODO", 110, "w"), ("lanc", "LANÇAMENTOS", 100, "e"),
                      ("situacao", "SITUAÇÃO", 330, "w"))

    def __init__(self, master, anexar_frame):
        super().__init__(master)
        self.anx = anexar_frame
        self.q = queue.Queue()
        self.worker = None
        self._thread = None
        self._parar = threading.Event()
        self._erro_drain = None
        self.cfg = self.mapping = None
        self.contas_erp: list = []
        self.contas_ofx: list = []
        self._cadastros = (None, [], [])
        self.marcadas: set = set()
        hoje = datetime.date.today()
        ini, fim = r.periodo_padrao(hoje)
        self.v_ini = tk.StringVar(value=f"{ini:%d/%m/%Y}")
        self.v_fim = tk.StringVar(value=f"{fim:%d/%m/%Y}")
        #: Ligado pelo app: quem mais está com o Chrome do Sicoob ou com os
        #: perfis do Inter (Extratos, Baixar comprovantes, a tela do dia).
        self.outros_no_sicoob = lambda: None
        self._build()
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = px(widgets.PADX)
        cab = widgets.Cabecalho(
            self, TITULO,
            "Baixa o OFX das contas marcadas (Sicoob e Inter) e importa no Mais "
            "Controle; e tira a prova dos saldos. Comece lendo as contas do ERP.",
            trilha="Diário  ›  Conciliação")
        cab.lbl_apoio.configure(wraplength=px(600))
        cab.pack(fill="x", padx=PADX, pady=px((16, 12)))
        self.b_ler = widgets.Botao(cab.acoes, "Ler as contas do ERP", papel="acao",
                                   command=self.ler)
        self.b_ler.pack(side="left")
        corpo = widgets.AreaRolavel(self)

        c1 = self.c1 = widgets.Cartao(corpo, "Baixar OFX", 1)
        c1.pack(fill="x", padx=PADX, pady=px((0, 12)))
        datas = ttk.Frame(c1)
        datas.pack(fill="x", pady=px((0, 8)))
        widgets.Campo(datas, "De", lambda p: widgets.CampoData(p, self.v_ini)
                      ).pack(side="left", padx=px((0, 16)))
        widgets.Campo(datas, "Até", lambda p: widgets.CampoData(p, self.v_fim)
                      ).pack(side="left", padx=px((0, 16)))
        self.lbl_lista = _ajuda(c1, SEM_LEITURA, pady=px((0, 6)))
        self.t_lista = self._tabela(c1, self.COLS_LISTA, "CONTA", altura=12)
        self.t_lista.bind("<Button-1>", self._clique_na_lista, add="+")
        self.t_lista.bind("<space>", self._espaco_na_lista, add="+")
        linha = ttk.Frame(c1)
        linha.pack(fill="x", pady=px((8, 0)))
        self.b_dia = widgets.Botao(linha, "Marcar as do pagamento do dia", papel="neutro",
                                   state="disabled", command=lambda: self._marcar_grupo(True))
        self.b_nenhuma = widgets.Botao(linha, "Desmarcar todas", papel="neutro",
                                       state="disabled", command=self._desmarcar)
        self.b_baixar = widgets.Botao(linha, "Baixar e importar", papel="acao",
                                      state="disabled", command=self.baixar)
        self.b_parar = widgets.Botao(linha, "Parar", papel="neutro", state="disabled",
                                     command=self.parar)
        for i, b in enumerate((self.b_dia, self.b_nenhuma)):
            b.pack(side="left", padx=px((0 if i == 0 else 8, 0)))
        self.b_parar.pack(side="right")
        self.b_baixar.pack(side="right", padx=px((0, 8)))
        ttk.Label(c1, text="Resultado", style="Secao.TLabel").pack(anchor="w",
                                                                   pady=px((12, 0)))
        self.t_resultado = self._tabela(c1, self.COLS_RESULTADO, "CONTA", altura=12)

        c2 = self.c2 = widgets.Cartao(corpo, "Provar saldos", 2)
        c2.pack(fill="x", padx=PADX, pady=px((0, 12)))
        _ajuda(c2, "O saldo atual de cada conta Sicoob e Inter do painel no ERP e no "
                   "banco, com um print de cada tela, num PDF para o grupo.")
        self.prova = ProvaNaTela(c2, tela=self)
        self.prova.barra.pack(fill="x", pady=px((6, 0)))

        acao = ttk.Frame(self, style="Fundo.TFrame")
        acao.pack(fill="x", padx=PADX, pady=px((0, 10)))
        self.barra_exec = widgets.BarraExecucao(acao)
        self.barra_exec.pack(side="left", fill="x", expand=True)
        self.lbl, self.pb = self.barra_exec.lbl, self.barra_exec.pb
        self.reg = widgets.Cartao(self, "Registro", padding=(12, 10))
        self.reg.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.log = tk.Text(self.reg, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0)
        self.log.pack(fill="both", expand=True)
        widgets.estilo_log(self.log)
        widgets.registro_elastico(self.reg, self.log)
        corpo.encaixar(acao, self.reg)

    def _tabela(self, pai, colunas, titulo_arvore, *, altura: int):
        grade = ttk.Frame(pai)
        grade.pack(fill="x", pady=px((6, 0)))
        t = ttk.Treeview(grade, columns=[c[0] for c in colunas], show="tree headings",
                         height=altura)
        t.heading("#0", text=titulo_arvore, anchor="w")
        t.column("#0", width=px(300), anchor="w", stretch=True)
        for chave, titulo, largura, ancora in colunas:
            t.heading(chave, text=titulo, anchor=ancora)
            t.column(chave, width=largura, anchor=ancora, stretch=ancora == "w")
        widgets.estilo_tabela(t, ordenavel=False)
        ttk.Scrollbar(grade, orient="vertical", command=t.yview).pack(side="right", fill="y")
        t.pack(side="left", fill="x", expand=True)
        return t

    # -------------------------------------- o que a Prova de saldos usa daqui
    def _log(self, msg=""):
        self.q.put(("log", msg))

    @staticmethod
    def _abrir(alvo):
        if alvo and alvo.exists():
            try:
                os.startfile(alvo)                          # noqa: S606 (Windows)
            except Exception:                               # noqa: BLE001
                subprocess.Popen(["explorer", str(alvo)])

    def _pasta_pagamentos(self):
        pasta = util.pasta_base() / "Pagamentos do dia"
        pasta.mkdir(parents=True, exist_ok=True)
        return pasta

    # --------------------------------------------------------------- perguntas
    def ocupado(self) -> str | None:
        t = self._thread
        return OCUPADO if t is not None and t.is_alive() else None

    def sicoob_ocupado(self) -> str | None:
        """Esta aba com o Chrome do Sicoob ou de um Inter aberto."""
        return self.ocupado() or self.prova.ocupado()

    def fechar(self):
        self._parar.set()
        self.prova.fechar()

    # -------------------------------------------------------------- leitura
    def ler(self) -> bool:
        if self.worker and not self.worker.done():
            return False
        if self.anx.avisar_se_ocupado("a Conciliação", aba=self):
            return False
        self._ligar(False)
        self.q.put(("ocupado", True))
        self.q.put(("status", "Lendo as contas do Mais Controle..."))
        try:
            self.worker = self.anx.submeter("Conciliação — ler as contas", self._t_ler,
                                            dona=self)
        except Exception as e:                              # noqa: BLE001
            self.q.put(("ocupado", False))
            self.q.put(("status", "Não consegui começar a leitura — veja o Registro."))
            self._log("\n" + widgets.recado_de_erro(e, "Não consegui começar a leitura."))
            self.b_ler.configure(state="normal")
            return False
        return True

    def _t_ler(self):
        from conciliacao.config import load_config
        from conciliacao.mapping import AccountMapping
        from tela_do_dia import erp_do_dia
        from tela_do_dia.prova_na_tela import _carregar_cadastros
        try:
            base = util.pasta_base()
            cfg = load_config(base / "config.yaml")
            mapping = AccountMapping.load(base / "mapping.yaml")
            api = self.anx.garantir_sessao(self._log)
            contas = erp_do_dia.ler_saldos(cfg, api, log=self._log)
            cadastros = _carregar_cadastros()
            self.q.put(("leitura", (cfg, mapping, contas, cadastros)))
            self.q.put(("status", f"{len(contas)} contas lidas do Mais Controle."))
        except Exception as e:                              # noqa: BLE001
            self._log("\n" + widgets.recado_de_erro(e, "Não consegui ler as contas do ERP."))
            self.q.put(("status", "Não consegui ler as contas — veja o Registro."))
            self.q.put(("leitura", None))
        finally:
            self.q.put(("ocupado", False))

    def _receber(self, valor):
        self.b_ler.configure(state="normal")
        if valor is None:
            self._ligar(False)
            return
        from tela_do_dia import saldos as sd
        self.cfg, self.mapping, self.contas_erp, self._cadastros = valor
        mapa_mc, empresas, inter = self._cadastros
        linhas = sd.montar_saldos(self.contas_erp, self.mapping)
        self.contas_ofx = r.contas_para_ofx(self.contas_erp, self.mapping, mapa_mc, empresas,
                                            inter, {ln.linha for ln in linhas})
        self.marcadas = set()                # spec: nenhuma marcada de início
        self._desenhar_lista()
        self._ligar(True)

    # ----------------------------------------------------------------- lista
    def _desenhar_lista(self):
        t = self.t_lista
        t.delete(*t.get_children())
        n_dia = sum(1 for c in self.contas_ofx if c.do_dia)
        for grupo, titulo, do_dia in ((GRUPO_DIA, "Do pagamento do dia", True),
                                      (GRUPO_OUTRAS, "Outras", False)):
            contas = [c for c in self.contas_ofx if c.do_dia == do_dia]
            if not contas:
                continue
            t.insert("", "end", iid=grupo, text=f"{titulo} ({len(contas)})", open=True)
            for c in contas:
                marca = DESMARCADA if not c.motivo else "  "
                t.insert(grupo, "end", iid=c.erp_id, text=f"{marca}  {c.nome}",
                         values=(c.banco.title(), c.motivo))
        self.lbl_lista.configure(text=(
            f"{len(self.contas_ofx)} contas Sicoob e Inter ({n_dia} do pagamento do dia). "
            "Clique na conta para marcar." if self.contas_ofx else
            "Nenhuma conta do Sicoob ou do Inter no cadastro."))

    def _conta(self, erp_id):
        return next((c for c in self.contas_ofx if c.erp_id == erp_id), None)

    def _alternar(self, erp_id):
        c = self._conta(erp_id)
        if c is None or c.motivo or self.ocupado():
            return
        if erp_id in self.marcadas:
            self.marcadas.discard(erp_id)
        else:
            self.marcadas.add(erp_id)
        marca = MARCADA if erp_id in self.marcadas else DESMARCADA
        self.t_lista.item(erp_id, text=f"{marca}  {c.nome}")
        self._ligar(True)

    def _clique_na_lista(self, ev):
        iid = self.t_lista.identify_row(ev.y)
        if iid and iid not in (GRUPO_DIA, GRUPO_OUTRAS):
            self._alternar(iid)

    def _espaco_na_lista(self, _ev):
        for iid in self.t_lista.selection():
            self._alternar(iid)
        return "break"

    def _marcar_grupo(self, do_dia: bool):
        for c in self.contas_ofx:
            if c.do_dia == do_dia and not c.motivo:
                self.marcadas.add(c.erp_id)
                self.t_lista.item(c.erp_id, text=f"{MARCADA}  {c.nome}")
        self._ligar(True)

    def _desmarcar(self):
        for erp_id in list(self.marcadas):
            c = self._conta(erp_id)
            if c is not None:
                self.t_lista.item(erp_id, text=f"{DESMARCADA}  {c.nome}")
        self.marcadas = set()
        self._ligar(True)

    def _ligar(self, leu: bool):
        rodando = bool(self.ocupado())
        lido = leu and self.mapping is not None
        self.b_ler.configure(state="disabled" if rodando else "normal")
        for b in (self.b_dia, self.b_nenhuma):
            b.configure(state="normal" if lido and not rodando else "disabled")
        self.b_baixar.configure(state="normal" if lido and self.marcadas and not rodando
                                else "disabled")
        self.b_parar.configure(state="normal" if rodando else "disabled")
        self.prova.ligar(lido)

    # ---------------------------------------------------------------- baixar
    def baixar(self):
        if self.ocupado():
            return
        try:
            ini, fim = r.ler_data(self.v_ini.get()), r.ler_data(self.v_fim.get())
        except ValueError as e:
            messagebox.showinfo(TITULO, f"{str(e)[:1].upper()}{str(e)[1:]}.")
            return
        porque = r.validar_periodo(ini, fim, datetime.date.today())
        if porque:
            messagebox.showinfo(TITULO, f"Não dá para pedir este período: {porque}.")
            return
        contas = [c for c in self.contas_ofx if c.erp_id in self.marcadas and not c.motivo]
        if not contas:
            return
        quem = self.outros_no_sicoob() or self.prova.ocupado()
        if quem:
            messagebox.showinfo(TITULO, f"O Chrome do banco está em uso ({quem}). Espere "
                                        "terminar: os dois usariam o mesmo perfil.")
            return
        if self.anx.avisar_se_ocupado("a Conciliação", aba=self):
            return
        inter = [c.apelido for c in contas if c.banco == r.INTER]
        partes = [f"Vou baixar o OFX de {len(contas)} conta(s), de {ini:%d/%m/%Y} a "
                  f"{fim:%d/%m/%Y}, e importar no Mais Controle (só importa, não concilia)."]
        if any(c.banco == r.SICOOB for c in contas):
            partes.append("Sicoob: faça o login quando o Chrome do Sicoob abrir.")
        if inter:
            partes.append("Inter: um QR por conta, nesta ordem: " + ", ".join(inter)
                          + ". Confira a empresa escolhida no app do celular antes de ler.")
        if not messagebox.askokcancel(TITULO, "\n\n".join(partes)):
            return
        # A pergunta esperou a pessoa: outra aba pode ter aberto o banco nesse
        # meio tempo (a Prova confere duas vezes pelo mesmo motivo).
        quem = self.outros_no_sicoob() or self.prova.ocupado()
        if quem:
            messagebox.showinfo(TITULO, f"O Chrome do banco está em uso ({quem}). Espere "
                                        "terminar: os dois usariam o mesmo perfil.")
            return
        from . import importados
        try:
            self._ja = importados.ler(self._pasta_ofx())
        except importados.RegistroIlegivel as e:
            messagebox.showwarning(TITULO, f"{str(e)[:1].upper()}{str(e)[1:]}.")
            return
        self.t_resultado.delete(*self.t_resultado.get_children())
        self._parar.clear()
        pasta = self._pasta_ofx() / f"{datetime.datetime.now():%Y-%m-%d %Hh%M}"
        self._thread = threading.Thread(target=self._t_baixar, args=(contas, ini, fim, pasta),
                                        name="ofx-bancos", daemon=True)
        self._thread.start()
        self._ligar(True)
        self.q.put(("ocupado", True))

    def _pasta_ofx(self):
        """Onde ficam os OFX baixados e o registro do que já foi importado."""
        return self._pasta_pagamentos() / "OFX"

    def _registrar(self, erp_id, chaves, incerto):
        """Da thread dos bancos, logo depois do ERP: anota o que foi enviado.
        Falha ao gravar vai ao Registro com destaque (o próximo envio não
        saberia destes lançamentos)."""
        from . import importados
        try:
            importados.registrar(self._pasta_ofx(), erp_id, chaves, incerto=incerto)
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] não gravei o registro do que foi importado ({e}) — antes "
                      "de importar esta conta de novo, confira o extrato dela no ERP.")

    def parar(self):
        self._parar.set()
        self.q.put(("status", "Parando antes da próxima etapa..."))

    def _t_baixar(self, contas, ini, fim, pasta):
        from . import rodada
        try:
            resultados = rodada.rodar(
                contas, ini, fim, pasta,
                sicoob=lambda cs, p: self._sicoob(cs, ini, fim, p),
                inter=lambda c, arq: self._inter(c, ini, fim, arq),
                erp=self._erp, perguntar_outro_acesso=self._perguntar_outro_acesso,
                ja_importados=getattr(self, "_ja", {}), registrar=self._registrar,
                avisar=lambda s: self.q.put(("status", s)), parar=self._parar.is_set,
                log=self._log)
            self.q.put(("resultado", (resultados, ini, fim, pasta)))
        except Exception as e:                              # noqa: BLE001
            self._log("\n" + widgets.recado_de_erro(e, "O Baixar OFX parou no meio."))
            self.q.put(("status", "O Baixar OFX parou — veja o Registro."))
        finally:
            self.q.put(("ocupado", False))
            self.q.put(("fim", None))

    def _sicoob(self, contas, ini, fim, pasta):
        from extratos_sicoob import ofx_periodo
        from extratos_sicoob.sicoob_client import SicoobClient
        with SicoobClient(log=self._log) as cli:
            cli.aguardar_login()
            return ofx_periodo.baixar(cli, [c.numero for c in contas], ini, fim, pasta,
                                      lista={}, parar=self._parar.is_set, log=self._log,
                                      progresso=lambda f, t: self.q.put(
                                          ("status", f"Sicoob: conta {f + 1} de {t}")))

    def _inter(self, conta, ini, fim, arquivo):
        from baixar_comprovantes import inter_ofx
        mapa_mc, empresas, inter = self._cadastros
        nomes, razoes = r.nomes_da_conta(conta, mapa_mc, empresas, inter)
        return inter_ofx.baixar_conta(
            conta.apelido, conta.numero, nomes, razoes, ini, fim, arquivo,
            log=lambda s, a=conta.apelido: self._log(f"  Inter {a}: {s}"),
            avisar_qr=lambda a: self.q.put(("status", f"Leia o QR da {a} no Chrome do "
                                                      "Inter — confira a empresa no celular")),
            parar=self._parar.is_set)

    def _erp(self, pedidos):
        from . import importar_erp

        def importar():
            self.anx.garantir_sessao(self._log)
            return importar_erp.importar(self.anx.mc, pedidos, log=self._log,
                                         parar=self._parar.is_set)
        fut = self.anx.submeter("Conciliação — importar OFX", importar, dona=self)
        return fut.result()

    def _perguntar_outro_acesso(self, faltam) -> bool:
        """Da thread dos bancos: a pergunta vai pela fila e a thread espera.
        Parar (ou fechar o app) responde "não"."""
        caixa = {"ev": threading.Event(), "sim": False}
        texto = (f"{len(faltam)} conta(s) não aparecem neste login do Sicoob "
                 f"({', '.join(faltam)}). Entrar com o outro acesso agora?")
        self.q.put(("perguntar", (texto, caixa)))
        while not caixa["ev"].wait(0.2):
            if self._parar.is_set():
                return False
        return bool(caixa["sim"]) and not self._parar.is_set()

    def _mostrar_resultado(self, resultados, ini, fim, pasta):
        # O que foi importado (ou ficou sem confirmação, ou não tinha nada novo)
        # sai da marca: um segundo clique não manda de novo (revisão de 16/11).
        for res in resultados:
            if res.situacao != r.NAO_IMPORTADO and res.conta.erp_id in self.marcadas:
                self.marcadas.discard(res.conta.erp_id)
                if self.t_lista.exists(res.conta.erp_id):
                    self.t_lista.item(res.conta.erp_id,
                                      text=f"{DESMARCADA}  {res.conta.nome}")
        t = self.t_resultado
        t.delete(*t.get_children())
        for i, res in enumerate(resultados):
            conta, periodo, lanc, situacao = r.linha_do_resultado(res, ini, fim)
            t.insert("", "end", iid=str(i), text=conta, values=(periodo, lanc, situacao))
        n = sum(1 for x in resultados if x.situacao == r.IMPORTADO)
        incertos = sum(1 for x in resultados if x.situacao == r.NAO_VERIFICADO)
        aviso = (f" {incertos} sem confirmação do ERP: confira o extrato delas."
                 if incertos else "")
        self.q.put(("status", f"{n} de {len(resultados)} OFX importados.{aviso} Os arquivos "
                              f"estão em {str(pasta).replace(os.sep, '/')}."))

    # ----------------------------------------------------------------- fila
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
                elif tipo == "leitura":
                    self._receber(valor)
                elif tipo == "resultado":
                    self._mostrar_resultado(*valor)
                elif tipo == "fim":
                    self._ligar(self.mapping is not None)
                elif tipo == "perguntar":
                    texto, caixa = valor
                    caixa["sim"] = messagebox.askyesno(TITULO, texto)
                    caixa["ev"].set()
        except queue.Empty:
            pass
        except Exception as e:                              # noqa: BLE001
            # A bomba de UI nunca morre (ver o `_drain` da tela do dia).
            motivo = repr(e)
            if motivo != self._erro_drain:
                self._erro_drain = motivo
                self.q.put(("log", f"[!] falha ao atualizar a tela: {motivo}"))
        finally:
            self.after(150, self._drain)
