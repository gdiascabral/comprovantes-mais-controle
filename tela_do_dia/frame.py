# -*- coding: utf-8 -*-
"""Aba "Pagamentos do dia": a tela fina por cima de `tela_do_dia/`.

Tudo o que decide número mora nos módulos puros ao lado e tem teste sem
janela (`decisoes.py` reúne o que antes seria `if` desta tela). Aqui só se lê
o ERP na thread do navegador (`anx.submeter`, `dona=self`), mostra, pergunta e
grava o dia de trabalho. Nada escreve no Mais Controle: o único caminho até o
ERP é a aba Aportes, depois que a pessoa confere e confirma lá. As abas
antigas continuam no menu até esta estar provada.
"""
from __future__ import annotations

import datetime
import os
import queue
import subprocess
import time
import tkinter as tk
from threading import Event
from tkinter import messagebox, ttk

import util
import widgets
from conciliacao.aportadores import ler_regras
from conciliacao.config import load_config
from conciliacao.frame import RAIZ_SAIDA
from conciliacao.mapping import AccountMapping
from conciliacao.models import sugerir_periodo
from conciliacao.workbook import WorkbookError, output_name
from pagamentos_dia import confirmacao, html_pagamentos, leitura_do_dia
from pagamentos_dia import reembolso, relatorio
from pagamentos_dia import regras_pagamento as regras_pag
from pagamentos_dia.pagamentos_frame import _carregar_mapas, _historico

from . import aportes as ap
from . import decisoes as dc
from . import dia_de_trabalho as ddt
from . import erp_do_dia, excel_do_dia, para_aportes
from . import pagamentos as pg
from . import saldos as sd
from .valores import brl, ler_valor_editado

px = widgets.px
REMOVER = "remover"


class TelaDoDiaFrame(ttk.Frame):
    COLS_SALDOS = (("conta", "CONTA", 300, "w"), ("sistema", "SISTEMA (ERP)", 230, "e"),
                   ("banco", "BANCO", 230, "e"), ("dif", "DIFERENÇA", 130, "e"),
                   ("situacao", "SITUAÇÃO", 320, "w"))
    # Passo 2 do desenho aprovado: quantos vão sair e quanto, quantos estão
    # bloqueados (o valor deles não soma no a pagar).
    COLS_PAG = (("vao", "VÃO SAIR", 110, "e"), ("a_pagar", "A PAGAR", 150, "e"),
                ("bloq", "BLOQUEADOS", 180, "e"), ("situacao", "SITUAÇÃO", 400, "w"))
    COLS_APT = (("minimo", "MÍNIMO", 120, "e"), ("sugerido", "SUGERIDO", 120, "e"),
                ("definido", "DEFINIDO", 120, "e"), ("falta", "FALTA RATEAR", 120, "e"),
                ("final", "SALDO FINAL", 130, "e"))
    COLS_MAO = (("origem", "DE", 300, "w"), ("destino", "PARA", 300, "w"),
                ("valor", "VALOR", 140, "e"))

    def __init__(self, master, anexar_frame):
        super().__init__(master)
        self.anx = anexar_frame
        self.q = queue.Queue()
        self.worker = None
        self._parar = Event()
        self._erro_drain = None
        self.aba_aportes = None
        self.aba_remessa = None
        # Ligados pelo app; devolvem True se a aba foi mostrada (o papel de
        # quem entrou pode não a ter).
        self.abrir_aportes = lambda: False
        self.abrir_remessa = lambda: False
        self.cfg = self.mapping = self.leitura = self.modelo = self.periodo = None
        self.contas_erp, self.regras = [], []
        self.dia = None
        self._dia_bloqueado = ""
        self.saldos, self.fora = [], []
        self.pagamentos = {}
        self.aportes = None
        self._iid_aporte = {}
        self.ultimo_arquivo = None
        self._build()
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = px(widgets.PADX)
        cab = widgets.Cabecalho(
            self, "Pagamentos do dia",
            "Saldos, o que vai sair, os aportes e o Excel do dia — numa tela só. "
            "Nada aqui escreve no Mais Controle.",
            trilha="Diário  ›  Pagamentos do dia")
        cab.pack(fill="x", padx=PADX, pady=px((16, 12)))
        # O meio rola quando não cabe (ver `widgets.AreaRolavel`).
        corpo = widgets.AreaRolavel(self)
        self.b1 = widgets.Botao(cab.acoes, "Buscar pagamentos e saldos", papel="acao",
                                command=self.buscar)
        self.b1.pack(side="left")

        c1 = widgets.Cartao(corpo, "Saldos", 1)
        c1.pack(fill="x", padx=PADX, pady=px((0, 12)))
        ttk.Label(c1, style="Tenue.TLabel",
                  text="As que não batem sobem para o topo. Clique no valor do sistema ou "
                       "do banco para editar (Enter edita o do banco): o original fica ao "
                       "lado, o motivo é opcional, e o ajuste vale só para o dia."
                  ).pack(anchor="w")
        self.t_saldos = self._tabela(c1, self.COLS_SALDOS, arvore=False, altura=8)
        self.t_saldos.bind("<ButtonRelease-1>", self._clique_saldo)
        self.t_saldos.bind("<Return>", self._enter_saldo)

        c2 = widgets.Cartao(corpo, "Pagamentos por conta", 2)
        c2.pack(fill="x", padx=PADX, pady=px((0, 12)))
        ttk.Label(c2, style="Tenue.TLabel",
                  text="A pagar = o que vai sair (os aptos). Bloqueados não somam: não "
                       "aptos e o que já saiu em remessa. Abra a conta para ver as linhas."
                  ).pack(anchor="w")
        self.t_pag = self._tabela(c2, self.COLS_PAG, arvore=True, altura=10)

        c3 = widgets.Cartao(corpo, "Aportes", 3)
        c3.pack(fill="x", padx=PADX, pady=px((0, 12)))
        # Erro em cima, em vermelho, e atenção à parte: a conta-mãe negativa
        # não pode se perder no meio de "falta ratear".
        self.lbl_alerta = ttk.Label(c3, style="Erro.TLabel", wraplength=px(900),
                                    justify="left", text="")
        self.lbl_alerta.pack(anchor="w")
        self.lbl_avisos = ttk.Label(c3, style="Atencao.TLabel", wraplength=px(900),
                                    justify="left", text="")
        self.lbl_avisos.pack(anchor="w")
        ttk.Label(c3, style="Tenue.TLabel",
                  text="Para cada conta que precisa: o mínimo, quem põe e quanto, e o que "
                       "ainda falta ratear. A conta-mãe vem primeiro, com o que entra e o "
                       "que sai para as filhas. A regra sugere; dois cliques (ou Enter) no "
                       "aportador para digitar o valor dele."
                  ).pack(anchor="w", pady=px((6, 0)))
        self.t_apt = self._tabela(c3, self.COLS_APT, arvore=True, altura=10)
        self.t_apt.bind("<Double-1>", self._duplo_aporte)
        self.t_apt.bind("<Return>", self._enter_aporte)

        ttk.Label(c3, text="Movimentos à mão", style="Secao.TLabel"
                  ).pack(anchor="w", pady=px((12, 0)))
        ttk.Label(c3, style="Tenue.TLabel",
                  text="Dinheiro que entra numa conta sem ser aporte da aba Regras: o "
                       "sócio que aporta na mãe, a transferência entre contas. Entram no "
                       "mínimo e no saldo final, e na seção «À MÃO» do Excel."
                  ).pack(anchor="w")
        self.t_mao = self._tabela(c3, self.COLS_MAO, arvore=False, altura=4)
        self.t_mao.bind("<Delete>", lambda _e: self._remover_movimento())
        linha_mao = ttk.Frame(c3)
        linha_mao.pack(fill="x", pady=px((8, 0)))
        self.b_mao_mae = widgets.Botao(linha_mao, "+ Aporte que entra na mãe", papel="neutro",
                                       state="disabled",
                                       command=lambda: self._novo_movimento(de_fora=True))
        self.b_mao_transf = widgets.Botao(linha_mao, "+ Transferência entre contas",
                                          papel="neutro", state="disabled",
                                          command=lambda: self._novo_movimento(de_fora=False))
        self.b_mao_tirar = widgets.Botao(linha_mao, "Remover o selecionado", papel="link",
                                         state="disabled", command=self._remover_movimento)
        for i, b in enumerate((self.b_mao_mae, self.b_mao_transf, self.b_mao_tirar)):
            b.pack(side="left", padx=px((0 if i == 0 else 8, 0)))

        linha = ttk.Frame(c3)
        linha.pack(fill="x", pady=px((12, 0)))
        self.b_sugestao = widgets.Botao(linha, "Preencher com a sugestão da regra",
                                        papel="neutro", state="disabled",
                                        command=self._usar_sugestoes)
        self.b_sugestao.pack(side="left")
        self.b_mandar = widgets.Botao(linha, "Mandar para a aba Aportes", papel="passo",
                                      state="disabled", command=self._mandar_aportes)
        self.b_mandar.pack(side="left", padx=px((8, 0)))

        c4 = widgets.Cartao(corpo, "Gerar", 4)
        c4.pack(fill="x", padx=PADX, pady=px((0, 12)))
        ttk.Label(c4, style="Tenue.TLabel",
                  text="Sai o mesmo de hoje — e o Excel do painel do dia, cópia com os "
                       "números da tela (ajustes e aportes)."
                  ).pack(anchor="w", pady=px((0, 8)))
        botoes = ttk.Frame(c4)
        botoes.pack(fill="x")
        self.b_excel = widgets.Botao(botoes, "Excel do painel do dia", papel="passo",
                                     state="disabled", command=self._gerar_excel)
        self.b_planilha = widgets.Botao(botoes, "Planilha por conta", papel="neutro",
                                        state="disabled", command=self._gerar_planilha)
        self.b_html = widgets.Botao(botoes, "HTML dos pagamentos", papel="neutro",
                                    state="disabled", command=self._gerar_html)
        self.b_remessa = widgets.Botao(botoes, "Remessa do Sicoob…", papel="neutro",
                                       state="disabled", command=self._ir_para_remessa)
        # Na ordem do desenho aprovado: o de hoje primeiro, a cópia do dia por último.
        for i, b in enumerate((self.b_html, self.b_planilha, self.b_remessa, self.b_excel)):
            b.pack(side="left", padx=px((0 if i == 0 else 8, 0)))

        acao = ttk.Frame(self, style="Fundo.TFrame")
        acao.pack(fill="x", padx=PADX, pady=px((0, 10)))
        btns = ttk.Frame(acao, style="Fundo.TFrame")
        btns.pack(side="right", padx=px((16, 0)))
        self.b_stop = widgets.Botao(btns, "⏹  Parar", papel="perigo", state="disabled",
                                    command=self._parar_click)
        self.b_stop.pack(side="left")
        self.b_pasta = widgets.Botao(btns, "📂  Abrir a pasta", papel="neutro",
                                     state="disabled",
                                     command=lambda: self._abrir(self.ultimo_arquivo.parent
                                                                 if self.ultimo_arquivo else None))
        self.b_pasta.pack(side="left", padx=px((8, 0)))
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

    @property
    def _botoes_do_dia(self):
        """Os que só fazem sentido com uma leitura inteira na tela."""
        return (self.b_excel, self.b_planilha, self.b_html, self.b_remessa, self.b_mandar,
                self.b_sugestao, self.b_mao_mae, self.b_mao_transf, self.b_mao_tirar)

    def _tabela(self, pai, colunas, *, arvore: bool, altura: int):
        grade = ttk.Frame(pai)
        grade.pack(fill="both", expand=True, pady=px((8, 0)))
        t = ttk.Treeview(grade, columns=[c[0] for c in colunas],
                         show="tree headings" if arvore else "headings", height=altura)
        if arvore:
            t.heading("#0", text="CONTA", anchor="w")
            t.column("#0", width=px(320), anchor="w")
        for chave, titulo, largura, ancora in colunas:
            t.heading(chave, text=titulo, anchor=ancora)
            # Sem `px`: o `estilo_tabela` escala as colunas de dados (e só
            # elas, guardando a largura de origem); a #0 é escalada acima.
            t.column(chave, width=largura, anchor=ancora)
        widgets.estilo_tabela(t, ordenavel=False)
        t.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(grade, orient="vertical", command=t.yview).pack(side="right", fill="y")
        return t

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
                    self.b_stop.configure(state="disabled" if valor == "normal" else "normal")
                elif tipo == "leitura":
                    self._receber_leitura(valor)
        except queue.Empty:
            pass
        except Exception as e:                              # noqa: BLE001
            # A bomba de UI nunca morre (ver o `_drain` da Conciliação).
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

    @staticmethod
    def _abrir(alvo):
        if alvo and alvo.exists():
            try:
                os.startfile(alvo)                          # noqa: S606 (Windows)
            except Exception:                               # noqa: BLE001
                subprocess.Popen(["explorer", str(alvo)])

    # ---------------------------------------------------------------- leitura
    def buscar(self):
        if self.worker and not self.worker.done():
            return
        # Recusar ANTES de apagar os botões (ver "Um navegador, seis abas").
        if self.anx.avisar_se_ocupado("os Pagamentos do dia", aba=self):
            return
        periodo = sugerir_periodo(datetime.date.today())
        self._limpar()
        self._parar.clear()
        self.q.put(("botoes", "disabled"))
        self.q.put(("ocupado", True))
        self.q.put(("status", f"Lendo {periodo.descrever()}..."))
        self.worker = self.anx.submeter("Pagamentos do dia — ler", self._t_ler,
                                        periodo, dona=self)

    def _limpar(self):
        """A leitura de antes sai da tela ANTES da nova começar: busca que cai
        ou é parada no meio não pode deixar os números de ontem com os botões
        de gerar e de mandar acesos."""
        self.leitura = None
        self.aportes = None
        self.dia = None                  # sem dia, nenhuma edição grava nada
        self.saldos, self.fora, self.pagamentos = [], [], {}
        self._iid_aporte = {}
        for t in (self.t_saldos, self.t_pag, self.t_apt, self.t_mao):
            t.delete(*t.get_children())
        self.lbl_alerta.configure(text="")
        self.lbl_avisos.configure(text="")
        for b in self._botoes_do_dia:
            b.configure(state="disabled")

    def _t_ler(self, periodo):
        comeco = time.time()
        try:
            base = util.pasta_base()
            cfg = load_config(base / "config.yaml")
            mapping = AccountMapping.load(base / "mapping.yaml")
            api = self.anx.garantir_sessao(self._log)
            self.q.put(("status", "Lendo os pagamentos e os anexos..."))
            try:
                leitura = leitura_do_dia.ler_pagamentos(
                    api, periodo.inicio, periodo.fim,
                    abrir_historico=lambda: _historico(self._log),
                    carregar_mapas=_carregar_mapas,
                    cadastro_reembolso=reembolso.carregar(base),
                    regras_fornecedor=regras_pag.carregar_fornecedores(),
                    destacar=regras_pag.carregar_confirmar(),
                    log=self._log,
                    progresso=lambda f, t: self.q.put(("status", f"Lendo... {f}/{t}")),
                    cancelar=self._parar.is_set)
            except Exception as e:                          # noqa: BLE001
                # Credenciais que a tela de Pagamentos não deu, lista que não
                # carregou: o recado de sempre, e nada na tela.
                self._log("\n" + widgets.recado_de_erro(e, "Não consegui ler os pagamentos."))
                self.q.put(("status", "Não consegui ler os pagamentos — veja o Registro."))
                return
            if leitura.interrompida:
                self._log("\nLeitura interrompida — nada foi mostrado nem calculado. "
                          "Busque de novo.")
                self.q.put(("status", "Leitura interrompida — busque de novo."))
                return
            self.q.put(("status", "Lendo os saldos..."))
            contas = erp_do_dia.ler_saldos(cfg, api, log=self._log)
            # Como a Conciliação (`conciliacao/frame.py`): relativo à pasta base.
            modelo = base / cfg.caminhos.get("modelo", "MODELO.xlsx")
            self.q.put(("leitura", (cfg, mapping, leitura, contas, ler_regras(modelo),
                                    periodo, modelo)))
            self.q.put(("status", f"Leitura pronta em {util.fmt_dur(time.time() - comeco)}."))
        except Exception as e:                              # noqa: BLE001
            self._log("\n" + widgets.recado_de_erro(e, "Não consegui ler o dia."))
            self.q.put(("status", "Não consegui ler o dia — veja o Registro."))
        finally:
            self.q.put(("ocupado", False))
            self.q.put(("botoes", "normal"))

    def _receber_leitura(self, pacote):
        (self.cfg, self.mapping, self.leitura, self.contas_erp, self.regras,
         self.periodo, self.modelo) = pacote
        caminho = ddt.caminho_do_dia(RAIZ_SAIDA, self.periodo.fim)
        try:
            self.dia, self._dia_bloqueado = ddt.ler(caminho, self.periodo.fim), ""
        except ValueError as e:
            self.dia, self._dia_bloqueado = ddt.DiaDeTrabalho(self.periodo.fim), str(e)
            self._log(f"[!] {e}\n    Os ajustes de hoje NÃO serão gravados e nada vai "
                      "para a aba Aportes até esse arquivo ser conferido (ele não é "
                      "sobrescrito).")
        for aviso in self.leitura.avisos:
            self._log(f"[!] {aviso}")
        self._recalcular()
        for b in self._botoes_do_dia:
            b.configure(state="normal")
        motivo = dc.motivo_sem_geradores(self.leitura)
        if motivo:
            # Sem apuração (nenhum lançamento a pagar), planilha, HTML e
            # Remessa não têm de onde sair; o Excel do dia sai (a pagar zero).
            for b in (self.b_planilha, self.b_html, self.b_remessa):
                b.configure(state="disabled")
            self._log(motivo)

    def _gravar_dia(self):
        if self._dia_bloqueado:
            self._log("[!] dia de trabalho NÃO gravado (o arquivo do dia está ilegível).")
            return
        try:
            ddt.gravar(self.dia, ddt.caminho_do_dia(RAIZ_SAIDA, self.periodo.fim))
        except OSError as e:
            self._log(f"[!] não consegui gravar o dia de trabalho: {e}")

    # -------------------------------------------------------------- recálculo
    def _recalcular(self):
        """Só com leitura inteira: `_t_ler` nunca entrega a interrompida."""
        base = sd.montar_saldos(self.contas_erp, self.mapping)
        self.saldos = sd.ordenar(sd.aplicar_ajustes(base, self.dia.ajustes))
        self.pagamentos, self.fora = pg.por_conta(self.leitura.grupos, self.mapping)
        em_ordem = sorted(self.saldos, key=lambda ln: ln.linha)
        self.aportes = ap.montar_aportes(
            {ln.rotulo: ln.saldo_do_dia for ln in em_ordem},
            {c.rotulo: c.a_pagar for c in self.pagamentos.values()},
            self.regras, self.dia.aportes, a_mao=self.dia.a_mao)
        self._encher_saldos()
        self._encher_pagamentos()
        self._encher_aportes()
        self._encher_movimentos()

    @property
    def _rotulos_do_painel(self) -> list[str]:
        return [ln.rotulo for ln in sorted(self.saldos, key=lambda ln: ln.linha)]

    @staticmethod
    def _celula(lido, ajuste):
        if ajuste is None:
            return brl(lido)
        motivo = f" · {ajuste.motivo}" if ajuste.motivo else ""
        return f"{brl(ajuste.valor)}  (era {brl(ajuste.original)}{motivo})"

    def _encher_saldos(self):
        t = self.t_saldos
        t.delete(*t.get_children())
        for i, ln in enumerate(self.saldos):
            tag, frase = ln.situacao()
            t.insert("", "end", iid=ln.rotulo, tags=widgets.linha_zebrada(i, tag), values=(
                ln.rotulo, self._celula(ln.sistema, ln.ajuste_sistema),
                self._celula(ln.banco, ln.ajuste_banco), brl(ln.diferenca),
                f"{widgets.MARCAS_ESTADO[tag]} {frase}"))

    def _encher_pagamentos(self):
        t = self.t_pag
        t.delete(*t.get_children())
        contas = sorted(self.pagamentos.values(), key=lambda c: c.linha) + list(self.fora)
        for i, c in enumerate(contas):
            estado = "erro" if c.motivo_fora else ("atencao" if c.bloqueados else "")
            pai = t.insert("", "end", text=c.rotulo, open=False,
                           tags=widgets.linha_zebrada(i, estado),
                           values=dc.celulas_da_conta(c))
            for p in c.vao_sair:
                t.insert(pai, "end", text=f"   {p.favorecido}",
                         values=("vai sair", brl(p.valor), "", p.situacao))
            for p in c.bloqueados:
                t.insert(pai, "end", text=f"   {p.favorecido}", tags=("erro",),
                         values=("", "", f"bloqueado · {brl(p.valor)}", p.situacao))

    def _encher_aportes(self):
        t = self.t_apt
        t.delete(*t.get_children())
        self._iid_aporte = {}
        alertas = self.aportes.alertas
        self.lbl_alerta.configure(text="\n".join(f"{widgets.MARCAS_ESTADO['erro']} {f}"
                                                 for tag, f in alertas if tag == "erro"))
        self.lbl_avisos.configure(text="\n".join(f"{widgets.MARCAS_ESTADO['atencao']} {f}"
                                                 for tag, f in alertas if tag != "erro"))
        for i, c in enumerate(self.aportes.contas):
            if c.sem_saldo or (c.saldo_final < 0 and c.e_mae):
                estado = "erro"
            elif c.saldo_final < 0 or c.falta_ratear > 0:
                estado = "atencao"
            else:
                estado = ""
            minimo, definido, falta, final = dc.celulas_do_aporte(c)
            pai = t.insert("", "end", open=True, tags=widgets.linha_zebrada(i, estado),
                           text=("★ CONTA-MÃE · " if c.e_mae else "") + c.rotulo,
                           values=(minimo, "", definido, falta, final))
            sugestao = c.sugestao
            for p in c.participantes:
                peso = f"  (peso {p.peso})" if p.peso is not None else ""
                iid = t.insert(pai, "end", text=f"   {p.aportador}{peso}", values=(
                    "", brl(sugestao.get(p.aportador)), brl(c.definidos.get(p.aportador)), "", ""))
                self._iid_aporte[iid] = (c.rotulo, p.aportador)
            if c.entra_a_mao:
                t.insert(pai, "end", text="   entra à mão",
                         values=("", "", brl(c.entra_a_mao), "", ""))
            if c.sai:
                t.insert(pai, "end", text=("   sai para as filhas" if c.e_mae
                                           else "   sai para outras contas"),
                         values=("", "", brl(-c.sai), "", ""))

    def _encher_movimentos(self):
        t = self.t_mao
        t.delete(*t.get_children())
        for i, (origem, destino, valor) in enumerate(self.dia.a_mao):
            t.insert("", "end", iid=str(i), tags=widgets.linha_zebrada(i),
                     values=(origem or "de fora", destino, brl(valor)))

    # ---------------------------------------------------------------- edição
    def _janela(self, titulo):
        """Modal filha da JANELA, e não desta aba: o Enter global do app
        (`_enter_aciona`) aciona o `b1` de quem tem o foco dentro da aba, e um
        diálogo filho dela faria o Enter do "Aplicar" também buscar de novo."""
        jan = tk.Toplevel(self.winfo_toplevel())
        jan.title(titulo)
        jan.transient(self.winfo_toplevel())
        widgets.barra_de_titulo(jan)
        corpo = ttk.Frame(jan, padding=px(14))
        corpo.pack(fill="both", expand=True)
        return jan, corpo

    @staticmethod
    def _rodape(jan, corpo, botoes, aplicar):
        linha = ttk.Frame(corpo)
        linha.pack(anchor="e", pady=px((14, 0)))
        for i, (texto, papel, comando) in enumerate(botoes):
            widgets.Botao(linha, texto, papel=papel, command=comando
                          ).pack(side="left", padx=px((0 if i == 0 else 8, 0)))
        jan.bind("<Return>", aplicar)
        jan.bind("<Escape>", lambda _e: jan.destroy())
        jan.grab_set()
        # `after_idle`: o foco depende da geometria, que a janela ainda não tem
        # (o mesmo motivo do `mostrar` do app).
        jan.after_idle(lambda: TelaDoDiaFrame._focar(corpo))
        jan.wait_window()

    @staticmethod
    def _focar(corpo):
        try:
            widgets.focar_primeiro_campo(corpo)
        except tk.TclError:
            pass                         # janela fechada antes do idle

    def _pedir_valor(self, titulo, explicacao, atual="", com_motivo=True):
        """(Decimal, motivo), REMOVER ou None. Modal: é pergunta que exige resposta."""
        jan, corpo = self._janela(titulo)
        ttk.Label(corpo, text=explicacao, wraplength=px(440), justify="left").pack(anchor="w")
        v_valor, v_motivo = tk.StringVar(value=atual), tk.StringVar()
        widgets.Campo(corpo, "Valor R$", lambda p: ttk.Entry(p, textvariable=v_valor, width=18)
                      ).pack(anchor="w", pady=px((10, 0)))
        if com_motivo:
            widgets.Campo(corpo, "Motivo (opcional — ex.: simulação, aporte ainda não caiu)",
                          lambda p: ttk.Entry(p, textvariable=v_motivo, width=48)
                          ).pack(anchor="w", pady=px((10, 0)))
        resposta = {}

        def aplicar(_e=None):
            try:
                resposta["v"] = (ler_valor_editado(v_valor.get()), v_motivo.get().strip())
            except ValueError as e:
                messagebox.showwarning(titulo, str(e), parent=jan)
                return "break"
            jan.destroy()
            return "break"

        def remover():
            resposta["v"] = REMOVER
            jan.destroy()

        self._rodape(jan, corpo, (("Voltar ao original", "neutro", remover),
                                  ("Cancelar", "neutro", jan.destroy),
                                  ("Aplicar", "acao", aplicar)), aplicar)
        return resposta.get("v")

    def _clique_saldo(self, evento):
        if self.t_saldos.identify_region(evento.x, evento.y) != "cell":
            return
        iid = self.t_saldos.identify_row(evento.y)
        campo = {"#2": sd.SISTEMA, "#3": sd.BANCO}.get(self.t_saldos.identify_column(evento.x))
        self._editar_saldo(iid, campo)

    def _enter_saldo(self, _evento):
        self._editar_saldo(self.t_saldos.focus(), sd.BANCO)
        return "break"

    def _editar_saldo(self, iid, campo):
        if not iid or not campo or self.dia is None:
            return
        linha = next((ln for ln in self.saldos if ln.rotulo == iid), None)
        if linha is None:
            return
        lido = linha.sistema if campo == sd.SISTEMA else linha.banco
        resposta = self._pedir_valor(f"{iid} — saldo do {campo}",
                                     f"Lido agora: {brl(lido)}. O ajuste vale só hoje e o "
                                     "original continua visível.")
        if resposta is None:
            return
        ajustes = self.dia.ajustes.setdefault(iid, {})
        if resposta == REMOVER:
            ajustes.pop(campo, None)
        else:
            valor, motivo = resposta
            ajustes[campo] = sd.novo_ajuste(linha, campo, valor, motivo,
                                            quando=datetime.datetime.now().isoformat(timespec="minutes"))
        if not ajustes:
            self.dia.ajustes.pop(iid, None)
        self._gravar_dia()
        self._recalcular()

    def _duplo_aporte(self, evento):
        self._editar_aporte(self.t_apt.identify_row(evento.y))

    def _enter_aporte(self, _evento):
        self._editar_aporte(self.t_apt.focus())
        return "break"

    def _editar_aporte(self, iid):
        par = self._iid_aporte.get(iid)
        if not par or self.dia is None:
            return
        destino, aportador = par
        conta = next((c for c in self.aportes.contas if c.rotulo == destino), None)
        if conta is None:                # a tabela mudou embaixo do clique
            return
        sugerido = conta.sugestao.get(aportador)
        minimo, _definido, falta, _final = dc.celulas_do_aporte(conta)
        resposta = self._pedir_valor(
            f"Aporte · {aportador} → {destino}",
            f"Mínimo da conta: {minimo} · falta ratear: {falta}"
            + (f" · a regra sugere {brl(sugerido)}" if sugerido is not None else ""),
            com_motivo=False)
        if resposta is None:
            return
        if resposta == REMOVER or resposta[0] == 0:
            self.dia.aportes.pop((destino, aportador), None)
        elif resposta[0] < 0:
            messagebox.showwarning("Aporte", "Aporte não pode ser negativo.")
            return
        else:
            self.dia.aportes[(destino, aportador)] = resposta[0]
        self._gravar_dia()
        self._recalcular()

    def _usar_sugestoes(self):
        if self.aportes is None:
            return
        for c in self.aportes.contas:
            for aportador, valor in c.sugestao.items():
                self.dia.aportes.setdefault((c.rotulo, aportador), valor)
        self._gravar_dia()
        self._recalcular()

    def _novo_movimento(self, *, de_fora: bool):
        if self.dia is None:
            return
        rotulos = self._rotulos_do_painel
        titulo = "Aporte que entra na mãe" if de_fora else "Transferência entre contas"
        jan, corpo = self._janela(titulo)
        ttk.Label(corpo, wraplength=px(440), justify="left",
                  text=("Dinheiro de fora do painel (sócio ou investidor) que entra numa "
                        "conta hoje." if de_fora else
                        "Dinheiro que sai de uma conta do painel e entra em outra hoje.")
                  ).pack(anchor="w")
        v_origem = tk.StringVar(value=dc.DE_FORA if de_fora else "")
        v_destino = tk.StringVar(value=(self.aportes.mae or "") if de_fora and self.aportes else "")
        v_valor = tk.StringVar()
        if not de_fora:
            widgets.Campo(corpo, "Sai de", lambda p: ttk.Combobox(
                p, textvariable=v_origem, values=rotulos, state="readonly", width=46)
                          ).pack(anchor="w", pady=px((10, 0)))
        widgets.Campo(corpo, "Entra em", lambda p: ttk.Combobox(
            p, textvariable=v_destino, values=rotulos, state="readonly", width=46)
                      ).pack(anchor="w", pady=px((10, 0)))
        widgets.Campo(corpo, "Valor R$", lambda p: ttk.Entry(p, textvariable=v_valor, width=18)
                      ).pack(anchor="w", pady=px((10, 0)))
        resposta = {}

        def aplicar(_e=None):
            try:
                resposta["v"] = dc.novo_movimento(v_origem.get(), v_destino.get(),
                                                  v_valor.get(), rotulos)
            except ValueError as e:
                messagebox.showwarning(titulo, str(e), parent=jan)
                return "break"
            jan.destroy()
            return "break"

        self._rodape(jan, corpo, (("Cancelar", "neutro", jan.destroy),
                                  ("Incluir", "acao", aplicar)), aplicar)
        if "v" not in resposta:
            return
        self.dia.a_mao.append(resposta["v"])
        self._log(f"Movimento à mão incluído: {dc.descrever_movimento(resposta['v'])}")
        self._gravar_dia()
        self._recalcular()

    def _remover_movimento(self):
        if self.dia is None:
            return
        sel = self.t_mao.selection()
        if not sel:
            messagebox.showinfo("Movimentos à mão", "Selecione o movimento a remover.")
            return
        i = int(sel[0])
        mov = self.dia.a_mao[i]
        if not messagebox.askyesno("Movimentos à mão",
                                   f"Remover {dc.descrever_movimento(mov)}?", default="no"):
            return
        del self.dia.a_mao[i]
        self._log(f"Movimento à mão removido: {dc.descrever_movimento(mov)}")
        self._gravar_dia()
        self._recalcular()

    # ----------------------------------------------------------------- gerar
    def _ocupado(self, titulo) -> bool:
        if self.worker and not self.worker.done():
            messagebox.showinfo(titulo, "Espere a leitura em andamento terminar.")
            return True
        return False

    def _pode_gerar(self, titulo) -> bool:
        """Planilha, HTML e Remessa: só com a apuração inteira (M2)."""
        if self._ocupado(titulo):
            return False
        motivo = dc.motivo_sem_geradores(self.leitura)
        if motivo:
            messagebox.showinfo(titulo, motivo)
            return False
        return True

    def _resultado_que_sai(self):
        return confirmacao.remontar(self.leitura.entradas, pg.ids_que_nao_saem(self.leitura.grupos))

    def _pasta_pagamentos(self):
        pasta = util.pasta_base() / "Pagamentos do dia"
        pasta.mkdir(parents=True, exist_ok=True)
        return pasta

    def _gerar_excel(self):
        titulo = "Excel do dia"
        if self._ocupado(titulo):
            return
        exigir = bool(self.cfg and self.cfg.exigir_todos_os_saldos)
        motivo = dc.motivo_sem_excel(self.leitura, self.saldos, exigir)
        if motivo:
            self._log(f"\nO EXCEL DO DIA NÃO FOI GERADO\n{motivo}")
            messagebox.showwarning(titulo, motivo)
            return
        sem_saldo = sorted(dc.contas_sem_saldo(self.saldos))
        if sem_saldo and not messagebox.askyesno(
                titulo, "Sem o saldo do sistema: " + ", ".join(sem_saldo)
                        + ".\n\nGerar o Excel assim mesmo? A célula do saldo fica vazia.",
                default="no"):
            return
        mae = next((c for c in self.aportes.contas if c.e_mae), None)
        if mae and not mae.sem_saldo and mae.saldo_final < 0 and not messagebox.askyesno(
                titulo, f"A conta-mãe fecha NEGATIVA ({brl(mae.saldo_final)}). "
                        "Gerar o Excel assim mesmo?", default="no"):
            return
        fim = self.periodo.fim
        destino = ddt.pasta_do_dia(RAIZ_SAIDA, fim) / output_name(fim)
        pergunta = dc.pergunta_sobrescrever(destino)
        if pergunta and not messagebox.askyesno(titulo, pergunta, default="no"):
            return
        try:
            r = excel_do_dia.gerar(
                modelo=self.modelo, destino=destino, data=fim, mapping=self.mapping,
                planilha=self.cfg.planilha,
                saldos={ln.linha: ln.saldo_do_dia for ln in self.saldos},
                a_pagar=pg.totais_para_o_painel(self.pagamentos),
                regras=self.regras, definidos=self.aportes.definidos_validos,
                a_mao=dc.movimentos_validos(self.dia.a_mao, self._rotulos_do_painel),
                leitura_interrompida=self.leitura.interrompida)
        except (WorkbookError, OSError) as e:
            self._log(f"\nO EXCEL DO DIA NÃO FOI GERADO\n{e}")
            messagebox.showwarning(titulo, widgets.recado_de_erro(e, "Não gerei o Excel do dia."))
            return
        self.ultimo_arquivo = r.path
        self.b_pasta.configure(state="normal")
        self._log(f"\nExcel do dia: {str(r.path).replace(chr(92), '/')} "
                  f"({r.celulas_conferidas} células conferidas)")
        widgets.registrar_atividade("dia", "Excel do dia", "ok", r.path.name)
        self._abrir(r.path)

    def _gerar_planilha(self):
        if not self._pode_gerar("Planilha por conta"):
            return
        ini, fim = self.leitura.periodo
        nome = f"pagamentos_{ini:%Y-%m-%d}{'' if ini == fim else f'_a_{fim:%Y-%m-%d}'}.xlsx"
        try:
            arquivo = relatorio.gerar_excel(self._resultado_que_sai(),
                                            self._pasta_pagamentos() / nome, log=self._log)
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] planilha por conta: {e}")
            messagebox.showwarning("Planilha por conta",
                                   widgets.recado_de_erro(e, "Não gerei a planilha."))
            return
        self._log(f"Planilha por conta: {str(arquivo).replace(chr(92), '/')}")
        self._abrir(arquivo)

    def _gerar_html(self):
        if not self._pode_gerar("HTML dos pagamentos"):
            return
        resultado, lancamentos = self._resultado_que_sai(), self.leitura.lancamentos
        pessoas = regras_pag.carregar_confirmar()
        if pessoas:
            nomes = " e ".join(pessoas) if len(pessoas) <= 2 else ", ".join(pessoas)
            if not messagebox.askyesno("HTML dos pagamentos",
                                       f"Incluir reembolso para {nomes}?\n\n"
                                       "Sim = os reembolsos deles entram no HTML.\n"
                                       "Não = ficam fora dos dois HTMLs."):
                resultado, lancamentos, tirados = html_pagamentos.tirar_reembolsos(
                    resultado, lancamentos, pessoas, self.leitura.overviews)
                for linha in tirados:
                    self._log(f"  - fora do HTML: {linha}")
        ini, fim = self.leitura.periodo
        pasta = self._pasta_pagamentos()
        try:
            gerados = html_pagamentos.gravar(resultado, lancamentos, self.leitura.anexos,
                                             pasta, ini, fim, pastas_extras=(pasta, util.pasta_base()))
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] HTML dos pagamentos: {e}")
            messagebox.showwarning("HTML dos pagamentos",
                                   widgets.recado_de_erro(e, "Não gerei o HTML."))
            return
        for linha in gerados.registro():
            self._log(linha)
        self._abrir(gerados.geral)

    def _ir_para_remessa(self):
        if self.aba_remessa is None or not self._pode_gerar("Remessa do Sicoob"):
            return
        if not self.abrir_remessa():
            self._log("[!] a aba Remessa/Retorno não está disponível para quem entrou.")
            return
        self.aba_remessa.receber_apuracao(self.leitura, pg.ids_que_nao_saem(self.leitura.grupos))

    # --------------------------------------------------- aba Aportes
    def _mandar_aportes(self):
        titulo = "Aportes"
        if self.aba_aportes is None or self.aportes is None or self._ocupado(titulo):
            return
        if self._dia_bloqueado:
            # Sem o arquivo do dia, não se sabe o que já foi mandado hoje: mandar
            # agora pode ser o segundo aporte (o ERP somaria os dois).
            messagebox.showwarning(titulo, "O arquivo do dia está ilegível, e é nele que "
                                           "fica o que já foi mandado hoje. Confira o "
                                           "arquivo (veja o Registro) antes de mandar.")
            return
        envio = para_aportes.operacoes(
            self.aportes.definidos_validos, self.regras, self.aba_aportes.entidades,
            self.aba_aportes.subcontas, dc.data_das_operacoes(self.periodo),
            enviados=dict(self.dia.enviados_aportes),
            sem_saldo=dc.contas_sem_saldo(self.saldos))
        # Pendência NÃO foi (bloqueia); aviso foi, mas pede conferência. "Já
        # mandado" se resolve na aba Aportes: mandar de novo daqui seria um
        # segundo aporte por cima do primeiro.
        pendentes, avisos = dc.linhas_do_envio(envio)
        if pendentes:
            self._log("\nNÃO foram para a aba Aportes:")
            for linha in pendentes:
                self._log(f"  [!] {linha}")
        if avisos:
            self._log("\nForam, mas confira:")
            for linha in avisos:
                self._log(f"  [!] {linha}")
        mandar_sem_saldo = True
        if envio.sem_saldo:
            mandar_sem_saldo = messagebox.askyesno(
                titulo, f"{len(envio.sem_saldo)} operação(ões) envolvem conta sem saldo do "
                        "sistema — o mínimo dela não foi calculado.\n\n"
                        "Mandar assim mesmo?", default="no")
        mandadas, seguradas = dc.separar_envio(envio, mandar_sem_saldo)
        for op in seguradas:
            self._log(f"  segurada (conta sem saldo): {op.resumo()}")
        if not mandadas:
            messagebox.showinfo(titulo, "Nada foi para a aba Aportes — veja o Registro.")
            return
        recusas = self.aba_aportes.receber_operacoes(mandadas)
        recusadas = para_aportes.operacoes_recusadas(mandadas, recusas)
        for (_i, motivo), op in zip(recusas, recusadas):
            self._log(f"  [!] a aba Aportes recusou {op.resumo()}: {motivo}")
        para_aportes.marcar_enviados(envio, mandadas, recusadas, self.dia.enviados_aportes)
        self._gravar_dia()
        aceitas = len(mandadas) - len(recusadas)
        self._log(f"\n{aceitas} operação(ões) na lista da aba Aportes — confira lá e "
                  "clique em Lançar no Mais Controle.")
        if aceitas:
            self.abrir_aportes()
