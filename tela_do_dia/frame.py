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
import threading
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
from nuvem import registro, sessao
from nuvem.pagamentos_do_dia import DiaNaNuvem
from pagamentos_dia import html_pagamentos, leitura_do_dia
from pagamentos_dia import reembolso, relatorio
from pagamentos_dia import regras_pagamento as regras_pag
from pagamentos_dia.pagamentos_frame import _carregar_mapas, _historico

from . import aportes as ap
from . import conferencia as cf
from . import decisoes as dc
from . import dia_de_trabalho as ddt
from . import erp_do_dia, excel_do_dia, geracao, janelas, lancamento_do_erp
from . import agendados as agd
from . import lista_diretor as ldr
from . import nuvem_do_dia, para_aportes, passo2, passo67
from . import pagamentos as pg
from . import saldos as sd
from .valores import brl, de_float, ler_valor_editado

px = widgets.px
REMOVER = "remover"


class TelaDoDiaFrame(ttk.Frame):
    # Larguras a 100% (o `estilo_tabela` escala). A soma de cada tabela cabe
    # no cartão a 1280x800 com o menu aberto e o Windows a 125%: o Treeview
    # não encolhe coluna para caber, ele CORTA as da direita (era o BANCO, a
    # DIFERENÇA e a SITUAÇÃO sumindo). Só a coluna de texto estica (a #0,
    # "CONTA", nas tabelas em árvore), e é ela que ganha a sobra da tela larga.
    COLS_SALDOS = (("conta", "CONTA", 200, "w"), ("sistema", "SISTEMA (ERP)", 125, "e"),
                   ("banco", "BANCO", 125, "e"), ("dif", "DIFERENÇA", 100, "e"),
                   ("situacao", "SITUAÇÃO", 130, "w"))
    # Passo 2 do desenho aprovado: quantos saem da conta e quanto (o já
    # enviado em remessa soma), quantos estão bloqueados (não somam).
    COLS_PAG = (("vao", "VÃO SAIR", 75, "e"), ("a_pagar", "A PAGAR", 115, "e"),
                ("bloq", "BLOQUEADOS", 130, "e"), ("situacao", "SITUAÇÃO", 150, "w"))
    COLS_APT = (("minimo", "MÍNIMO", 95, "e"), ("sugerido", "SUGERIDO", 95, "e"),
                ("definido", "DEFINIDO", 95, "e"), ("falta", "FALTA RATEAR", 100, "e"),
                ("final", "SALDO FINAL", 95, "e"))
    COLS_MAO = (("origem", "DE", 260, "w"), ("destino", "PARA", 260, "w"),
                ("valor", "VALOR", 120, "e"))
    #: Largura da #0 ("CONTA") das tabelas em árvore, a 100%.
    LARGURA_CONTA = 200
    #: Tabela vazia fica baixa (não empurra os passos de baixo para longe);
    #: cheia, cresce até o teto de cada uma e rola dali em diante.
    LINHAS_VAZIA = 3

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
        # Entrega 2: o passo 2 editável, gravado na nuvem. Sem a nuvem lida
        # (`_nuvem_travada`), nada desta parte grava — falha fechada.
        self.lido = None
        self.conferencia = cf.Conferencia()
        self._nuvem_travada = passo2.SEM_NUVEM
        self._gravando = False
        self._iid_pag = {}               # iid da tabela do passo 2 → passo2.LinhaDaTabela
        self._ao_ler_link = None
        self._geracao = 0                # muda a cada _limpar: gravação velha não pinta tela nova
        # "Agendados a confirmar" e passos 6/7: as regras moram em `passo67`.
        self.marcas_agd = {}             # agendado_id → marcado (pré-marca só da prova)
        self.para_marcar_itens = None    # None = "Montar a lista" ainda não foi clicado
        self.lista = []                  # [lista_diretor.LinhaDaLista]
        self._lista_ligada = False
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

        self._padx = PADX
        # No topo, e só quando há pendentes (`_encher_agendados`): empacotado
        # antes do cartão 1.
        self.c0 = widgets.Cartao(corpo, "Agendados a confirmar")
        self._ajuda(self.c0, "Agendados esperando a sua resposta, de hoje e de dias anteriores. "
                             "O app marca (☑) só o que ele prova pago — baixa no ERP ou "
                             "retorno do banco; título que sumiu ou mudou de valor espera "
                             "você. Clique na 1ª coluna (ou Espaço) para marcar ou desmarcar.")
        self.t_agd = self._tabela(self.c0, passo67.COLS_AGD, arvore=False, altura=8)
        self.t_agd.configure(selectmode="browse")
        self.t_agd.bind("<ButtonRelease-1>", self._clique_agd)
        self.t_agd.bind("<space>", lambda _e: self._alternar_agd(self.t_agd.focus()) or "break")
        linha_agd = ttk.Frame(self.c0)
        linha_agd.pack(fill="x", pady=px((8, 0)))
        self.b_agd_pago = widgets.Botao(linha_agd, "Pago (os marcados)", papel="passo",
                                        state="disabled", command=lambda: self._responder("pago"))
        self.b_agd_nao = widgets.Botao(linha_agd, "Não saiu…", papel="neutro", state="disabled",
                                       command=lambda: self._responder("nao_saiu"))
        self.b_agd_reag = widgets.Botao(linha_agd, "Reagendado…", papel="neutro",
                                        state="disabled",
                                        command=lambda: self._responder("reagendado"))
        for i, b in enumerate((self.b_agd_pago, self.b_agd_nao, self.b_agd_reag)):
            b.pack(side="left", padx=px((0 if i == 0 else 8, 0)))

        c1 = self.c1 = widgets.Cartao(corpo, "Saldos", 1)
        c1.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self._ajuda(c1, "As que não batem sobem para o topo. Clique no valor do sistema ou "
                        "do banco para editar (Enter edita o do banco): o original fica ao "
                        "lado, o motivo é opcional, e o ajuste vale só para o dia.")
        self.t_saldos = self._tabela(c1, self.COLS_SALDOS, arvore=False, altura=8)
        self.t_saldos.bind("<ButtonRelease-1>", self._clique_saldo)
        self.t_saldos.bind("<Return>", self._enter_saldo)

        c2 = widgets.Cartao(corpo, "Pagamentos por conta", 2)
        c2.pack(fill="x", padx=PADX, pady=px((0, 12)))
        # Sem campo de data (decisão do dono): o período lido fica à vista,
        # mas só DEPOIS de buscar — vazio, o rótulo era uma linha em branco
        # em cima da ajuda (`mostrar_periodo`).
        self.lbl_periodo = ttk.Label(c2, style="Secao.TLabel", text="")
        # A nuvem que não respondeu: em vermelho, fora do layout quando vazio.
        self.lbl_nuvem = self._ajuda(c2, "", estilo="Erro.TLabel")
        self.lbl_nuvem.pack_forget()
        self._ajuda_pag = self._ajuda(
            c2, "A pagar = o que sai da conta: os aptos de hoje e o que já foi "
                "enviado em remessa e ainda não está pago (esse não é gerado de "
                "novo). Bloqueados (não aptos) não somam. Abra a conta para ver. "
                "Selecione uma linha e use os botões abaixo.")
        self.t_pag = self._tabela(c2, self.COLS_PAG, arvore=True, altura=10)
        self.t_pag.configure(selectmode="browse")    # uma linha por ação
        linha_pag = ttk.Frame(c2)
        linha_pag.pack(fill="x", pady=px((8, 0)))
        self.b_liberar = widgets.Botao(linha_pag, "Incluir mesmo assim…", papel="neutro",
                                       state="disabled", command=self._liberar)
        self.b_desmarcar = widgets.Botao(linha_pag, "Desmarcar", papel="neutro",
                                         state="disabled", command=self._desmarcar)
        self.b_editar = widgets.Botao(linha_pag, "Editar…", papel="neutro",
                                      state="disabled", command=self._editar)
        self.b_desfazer = widgets.Botao(linha_pag, "Desfazer", papel="neutro",
                                        state="disabled", command=self._desfazer)
        # À mão só se remove (decisão do coordenador): nunca "desmarcar".
        self.b_remover = widgets.Botao(linha_pag, "Remover à mão", papel="neutro",
                                       state="disabled", command=self._remover_a_mao)
        self.b_a_mao = widgets.Botao(linha_pag, "+ Pagamento à mão…", papel="neutro",
                                     state="disabled", command=self._novo_a_mao)
        for i, b in enumerate(self._botoes_do_passo2):
            b.pack(side="left", padx=px((0 if i == 0 else 8, 0)))

        c3 = widgets.Cartao(corpo, "Aportes", 3)
        c3.pack(fill="x", padx=PADX, pady=px((0, 12)))
        # Erro em cima, em vermelho, e atenção à parte: a conta-mãe negativa
        # não pode se perder no meio de "falta ratear".
        # Vazios saem do layout (`_mostrar_alertas`): rótulo vazio empacotado
        # é uma linha em branco embaixo do título do cartão.
        alertas = ttk.Frame(c3)
        alertas.pack(fill="x")
        self.lbl_alerta = self._ajuda(alertas, "", estilo="Erro.TLabel")
        self.lbl_avisos = self._ajuda(alertas, "", estilo="Atencao.TLabel")
        self._mostrar_alertas("", "")
        self._ajuda(c3, "Para cada conta que precisa: o mínimo, quem põe e quanto, e o que "
                        "ainda falta ratear. A conta-mãe vem primeiro, com o que entra e o "
                        "que sai para as filhas. A regra sugere; dois cliques (ou Enter) no "
                        "aportador para digitar o valor dele.", pady=px((6, 0)))
        self.t_apt = self._tabela(c3, self.COLS_APT, arvore=True, altura=10)
        self.t_apt.bind("<Double-1>", self._duplo_aporte)
        self.t_apt.bind("<Return>", self._enter_aporte)

        ttk.Label(c3, text="Movimentos à mão", style="Secao.TLabel"
                  ).pack(anchor="w", pady=px((12, 0)))
        self._ajuda(c3, "Dinheiro que entra numa conta sem ser aporte da aba Regras: o "
                        "sócio que aporta na mãe, a transferência entre contas. Entram no "
                        "mínimo e no saldo final, e na seção «À MÃO» do Excel.")
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
        self._ajuda(c4, "Sai o mesmo de hoje — e o Excel do painel do dia, cópia com os "
                        "números da tela (ajustes e aportes).", pady=px((0, 8)))
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

        c5 = widgets.Cartao(corpo, "Agendar (no banco)", 5)
        c5.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self._ajuda(c5, "Agende no banco como sempre — isto fica fora do app. Depois, marque "
                        "aqui embaixo o que agendou.")

        c6 = widgets.Cartao(corpo, "Marcar agendados", 6)
        c6.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self._ajuda(c6, "«Montar a lista» traz o que sai hoje, tudo marcado: desmarque o que "
                        "não agendou e grave. O já marcado hoje aparece apagado e não vai de "
                        "novo. Clique na 1ª coluna (ou Espaço) para marcar ou desmarcar.")
        self.t_marcar = self._tabela(c6, passo67.COLS_MARCAR, arvore=False, altura=10)
        self.t_marcar.configure(selectmode="browse")
        self.t_marcar.bind("<ButtonRelease-1>", self._clique_marcar)
        self.t_marcar.bind("<space>",
                           lambda _e: self._alternar_marcar(self.t_marcar.focus()) or "break")
        linha6 = ttk.Frame(c6)
        linha6.pack(fill="x", pady=px((8, 0)))
        self.b_montar = widgets.Botao(linha6, "Montar a lista", papel="neutro", state="disabled",
                                      command=self._montar_para_marcar)
        self.b_gravar_agd = widgets.Botao(linha6, "Gravar agendados", papel="passo",
                                          state="disabled", command=self._gravar_agendados)
        self.b_montar.pack(side="left")
        self.b_gravar_agd.pack(side="left", padx=px((8, 0)))

        c7 = widgets.Cartao(corpo, "Lista do diretor", 7)
        c7.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self._ajuda(c7, "Só o que foi agendado hoje, uma linha por conta. ↑/↓ mudam a ordem "
                        "(dentro dos numerados ou dentro dos demais); «Ordinal» liga ou "
                        "desliga o 1º, 2º…; o nome curto fica gravado para os próximos dias.")
        self.t_lista = self._tabela(c7, passo67.COLS_LISTA, arvore=False, altura=10)
        self.t_lista.configure(selectmode="browse")
        self.t_lista.bind("<<TreeviewSelect>>", lambda _e: self._ligar_lista())
        linha7 = ttk.Frame(c7)
        linha7.pack(fill="x", pady=px((8, 0)))
        self.b_subir = widgets.Botao(linha7, "↑", papel="neutro", state="disabled",
                                     command=lambda: self._lista_mover(-1))
        self.b_descer = widgets.Botao(linha7, "↓", papel="neutro", state="disabled",
                                      command=lambda: self._lista_mover(1))
        self.b_ordinal = widgets.Botao(linha7, "Ordinal sim/não", papel="neutro",
                                       state="disabled", command=self._lista_ordinal)
        self.b_nome = widgets.Botao(linha7, "Nome curto…", papel="neutro", state="disabled",
                                    command=self._nome_curto)
        self.b_copiar = widgets.Botao(linha7, "Copiar para o WhatsApp", papel="passo",
                                      state="disabled", command=self._copiar_lista)
        for i, b in enumerate(self._botoes_da_lista):
            b.pack(side="left", padx=px((0 if i == 0 else 8, 0)))

        acao =ttk.Frame(self, style="Fundo.TFrame")
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
                self.b_sugestao, self.b_mao_mae, self.b_mao_transf, self.b_mao_tirar,
                *self._botoes_do_passo2, *self._botoes_67, *self._botoes_da_lista)

    @property
    def _botoes_do_passo2(self):
        """Os que GRAVAM na nuvem: apagados sem a nuvem lida e durante uma
        gravação (`passo2.botoes_ligados`)."""
        return (self.b_liberar, self.b_desmarcar, self.b_editar, self.b_desfazer,
                self.b_remover, self.b_a_mao)

    @property
    def _botoes_67(self):
        """"Agendados a confirmar" e passo 6: a mesma regra do passo 2 (nuvem
        lida, sem gravação em andamento)."""
        return (self.b_agd_pago, self.b_agd_nao, self.b_agd_reag, self.b_montar,
                self.b_gravar_agd)

    @property
    def _botoes_da_lista(self):
        return (self.b_subir, self.b_descer, self.b_ordinal, self.b_nome, self.b_copiar)

    def _ligar_botoes(self):
        """O que fica ligado vem de `passo2.botoes`: gravando na nuvem, nada
        (nem gerar, nem mandar aportes, nem buscar); sem leitura, só buscar;
        sem apuração, sem os geradores; nuvem travada, sem o passo 2."""
        b = passo2.botoes(tem_leitura=self.leitura is not None, gravando=self._gravando,
                          travada=self._nuvem_travada,
                          sem_geradores=(self.leitura is not None
                                         and bool(dc.motivo_sem_geradores(self.leitura))))

        def estado(ligado):
            return "normal" if ligado else "disabled"
        for w in (self.b_excel, self.b_mandar, self.b_sugestao, self.b_mao_mae,
                  self.b_mao_transf, self.b_mao_tirar):
            w.configure(state=estado(b.dia))
        for w in (self.b_planilha, self.b_html, self.b_remessa):
            w.configure(state=estado(b.geradores))
        for w in (*self._botoes_do_passo2, *self._botoes_67):
            w.configure(state=estado(b.passo2))
        self._lista_ligada = b.passo2
        self._ligar_lista()
        # Durante a leitura quem manda no Buscar é a mensagem "botoes" do `_t_ler`.
        if not (self.worker and not self.worker.done()):
            self.b1.configure(state=estado(b.buscar))

    def _ligar_lista(self):
        """↑/↓ só dentro do mesmo lado (numerados × demais), pela seleção."""
        estados = passo67.botoes_da_lista(self.lista, self._indice_lista(),
                                          ligado=self._lista_ligada)
        for chave, w in zip(("subir", "descer", "ordinal", "nome", "copiar"),
                            self._botoes_da_lista):
            w.configure(state="normal" if estados[chave] else "disabled")

    @staticmethod
    def _ajuda(pai, texto, *, estilo="Tenue.TLabel", pady=0):
        """Texto que quebra a linha na largura do cartão. `wraplength` fixo
        cortava a frase à direita na janela estreita ("o motivo é o..."): a
        largura certa só se sabe depois do layout, e muda com a janela."""
        lbl = ttk.Label(pai, style=estilo, text=texto, justify="left")
        lbl.pack(fill="x", anchor="w", pady=pady)

        def _quebrar(e):
            if e.width > 1 and str(lbl.cget("wraplength")) != str(e.width):
                lbl.configure(wraplength=e.width)
        lbl.bind("<Configure>", _quebrar, add="+")
        return lbl

    def _tabela(self, pai, colunas, *, arvore: bool, altura: int):
        grade = ttk.Frame(pai)
        grade.pack(fill="both", expand=True, pady=px((8, 0)))
        t = ttk.Treeview(grade, columns=[c[0] for c in colunas],
                         show="tree headings" if arvore else "headings",
                         height=self.LINHAS_VAZIA)
        t._altura_maxima = altura
        if arvore:
            t.heading("#0", text="CONTA", anchor="w")
            t.column("#0", width=px(self.LARGURA_CONTA), anchor="w", stretch=True)
        for chave, titulo, largura, ancora in colunas:
            t.heading(chave, text=titulo, anchor=ancora)
            # Sem `px`: o `estilo_tabela` escala as colunas de dados (e só
            # elas, guardando a largura de origem); a #0 é escalada acima.
            # Valor não estica (fica colado no título); texto ganha a sobra.
            t.column(chave, width=largura, anchor=ancora, stretch=ancora == "w")
        widgets.estilo_tabela(t, ordenavel=False)
        # A barra ANTES da tabela: empacotada depois, ela só ganhava o que a
        # tabela deixasse — nada, quando as colunas passavam da largura.
        ttk.Scrollbar(grade, orient="vertical", command=t.yview).pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        if arvore:
            for ev in ("<<TreeviewOpen>>", "<<TreeviewClose>>"):
                t.bind(ev, lambda _e, t=t: t.after_idle(self._ajustar_altura, t), add="+")
        return t

    def _ajustar_altura(self, t):
        """Linhas à vista (filhos só de conta aberta), entre o mínimo da
        tabela vazia e o teto dela."""
        def visiveis(pai):
            n = 0
            for iid in t.get_children(pai):
                n += 1
                if t.item(iid, "open"):
                    n += visiveis(iid)
            return n
        try:
            t.configure(height=max(self.LINHAS_VAZIA,
                                   min(visiveis(""), t._altura_maxima)))
        except tk.TclError:
            pass                         # aba fechada antes do idle

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
                elif tipo == "gravou":
                    self._receber_gravacao(*valor)
                elif tipo == "link_lido":
                    if self._ao_ler_link is not None:
                        self._ao_ler_link(*valor)
                elif tipo == "aviso":
                    messagebox.showwarning(*valor)
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
            # As cores das linhas (zebra, atenção, erro) são tags gravadas na
            # tabela quando ela nasce: sem repassar, trocar o tema deixava as
            # linhas claras dentro do app escuro. As larguras não mudam (o
            # `estilo_tabela` guarda as de origem).
            for t in (self.t_saldos, self.t_pag, self.t_apt, self.t_mao, self.t_agd,
                      self.t_marcar, self.t_lista):
                widgets.estilo_tabela(t, ordenavel=False)
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
        if self._gravando:
            messagebox.showinfo("Pagamentos do dia", "Espere a gravação na nuvem terminar.")
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
        self.lido = None
        self.conferencia = cf.Conferencia()
        self._nuvem_travada = passo2.SEM_NUVEM
        self._iid_pag = {}
        self._geracao += 1
        self._mostrar_nuvem("")
        self.saldos, self.fora, self.pagamentos = [], [], {}
        self._iid_aporte = {}
        self.marcas_agd, self.para_marcar_itens, self.lista = {}, None, []
        for t in self._tabelas:
            t.delete(*t.get_children())
        self.c0.pack_forget()
        self._mostrar_alertas("", "")
        self.mostrar_periodo("")
        for t in self._tabelas:
            self._ajustar_altura(t)
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
            self.q.put(("status", "Lendo a nuvem (liberações, à mão, agendados)..."))
            # Nuvem que falha não derruba a leitura: volta `erro`, a tela fica
            # como na entrega 1 e o passo 2 trava (falha fechada).
            lido = nuvem_do_dia.ler(self._cliente_nuvem(), periodo.fim, datetime.date.today(),
                                    api=api, registro=self._registro_nuvem(), log=self._log)
            # Como a Conciliação (`conciliacao/frame.py`): relativo à pasta base.
            modelo = base / cfg.caminhos.get("modelo", "MODELO.xlsx")
            self.q.put(("leitura", (cfg, mapping, leitura, contas, ler_regras(modelo),
                                    periodo, modelo, lido)))
            self.q.put(("status", f"Leitura pronta em {util.fmt_dur(time.time() - comeco)}."))
        except Exception as e:                              # noqa: BLE001
            self._log("\n" + widgets.recado_de_erro(e, "Não consegui ler o dia."))
            self.q.put(("status", "Não consegui ler o dia — veja o Registro."))
        finally:
            self.q.put(("ocupado", False))
            self.q.put(("botoes", "normal"))

    def _receber_leitura(self, pacote):
        (self.cfg, self.mapping, self.leitura, self.contas_erp, self.regras,
         self.periodo, self.modelo, lido) = pacote
        self.lido, self.conferencia, self._nuvem_travada = lido, lido.conferencia, lido.erro
        self.marcas_agd = passo67.marcas_iniciais(lido.pendentes)
        if lido.erro:
            self._log(f"[!] {lido.erro} — liberar, editar, à mão e agendados ficam "
                      "travados até buscar de novo")
        self._mostrar_nuvem(lido.erro)
        for aviso in lido.avisos:
            self._log(f"[!] {aviso}")
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
        self.mostrar_periodo(dc.periodo_na_tela(self.periodo))
        self._montar_lista()
        self._recalcular()
        # Sem apuração (nenhum lançamento a pagar), planilha, HTML e Remessa
        # não têm de onde sair; o Excel do dia sai (a pagar zero).
        self._ligar_botoes()
        motivo = dc.motivo_sem_geradores(self.leitura)
        if motivo:
            self._log(motivo)

    def _mostrar_alertas(self, erro: str, atencao: str):
        """Erro em cima, atenção embaixo; o vazio não ocupa linha."""
        for lbl, texto in ((self.lbl_alerta, erro), (self.lbl_avisos, atencao)):
            lbl.configure(text=texto)
            lbl.pack_forget()
        for lbl, texto in ((self.lbl_alerta, erro), (self.lbl_avisos, atencao)):
            if texto:
                lbl.pack(fill="x", anchor="w")

    def _mostrar_nuvem(self, erro: str):
        """O recado da nuvem que não respondeu; vazio sai do layout."""
        texto = (f"{widgets.MARCAS_ESTADO['erro']} Nuvem: {erro} — liberar, editar, "
                 "pagamento à mão, agendados e lista do diretor travados até buscar de "
                 "novo." if erro else "")
        self.lbl_nuvem.configure(text=texto)
        if texto:
            self.lbl_nuvem.pack(fill="x", anchor="w", before=self._ajuda_pag)
        else:
            self.lbl_nuvem.pack_forget()

    def mostrar_periodo(self, texto: str):
        """Sem texto, o rótulo sai do layout (não deixa linha em branco)."""
        self.lbl_periodo.configure(text=texto)
        if texto:
            self.lbl_periodo.pack(anchor="w", before=self._ajuda_pag)
        else:
            self.lbl_periodo.pack_forget()

    def _gravar_dia(self) -> bool:
        """True = gravou. Quem depende da gravação (o envio à aba Aportes)
        tem de olhar a resposta: falha calada era o próximo Buscar esquecendo
        o que foi mandado."""
        if self._dia_bloqueado:
            self._log(f"[!] dia de trabalho NÃO gravado: {self._dia_bloqueado}")
            return False
        try:
            ddt.gravar(self.dia, ddt.caminho_do_dia(RAIZ_SAIDA, self.periodo.fim))
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] não consegui gravar o dia de trabalho: {e}")
            return False
        return True

    # -------------------------------------------------------------- recálculo
    def _recalcular(self):
        """Só com leitura inteira: `_t_ler` nunca entrega a interrompida."""
        base = sd.montar_saldos(self.contas_erp, self.mapping)
        self.saldos = sd.ordenar(sd.aplicar_ajustes(base, self.dia.ajustes))
        self.pagamentos, self.fora = pg.por_conta(self.leitura.grupos, self.mapping,
                                                  self.conferencia)
        em_ordem = sorted(self.saldos, key=lambda ln: ln.linha)
        self.aportes = ap.montar_aportes(
            {ln.rotulo: ln.saldo_do_dia for ln in em_ordem},
            {c.rotulo: c.a_pagar for c in self.pagamentos.values()},
            self.regras, self.dia.aportes, a_mao=self.dia.a_mao)
        self.mostrar_numeros()

    def mostrar_numeros(self):
        """Põe na tela o que já está em `saldos`, `pagamentos`, `fora`,
        `aportes` e `dia`. Pública porque a `ferramentas/galeria.py` monta
        esse estado com dados fictícios para fotografar a aba preenchida."""
        self._encher_saldos()
        self._encher_pagamentos()
        self._encher_aportes()
        self._encher_movimentos()
        # Sem a nuvem (a galeria monta a aba sem ela), as três ficam vazias.
        self._encher_agendados()
        self._encher_para_marcar()
        self._encher_lista()
        for t in self._tabelas:
            self._ajustar_altura(t)

    @property
    def _tabelas(self):
        return (self.t_saldos, self.t_pag, self.t_apt, self.t_mao, self.t_agd, self.t_marcar,
                self.t_lista)

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
        # A conta aberta continua aberta depois de gravar e reler.
        abertas = {t.item(i, "text") for i in t.get_children() if t.item(i, "open")}
        t.delete(*t.get_children())
        self._iid_pag = {}
        contas = sorted(self.pagamentos.values(), key=lambda c: c.linha) + list(self.fora)
        for i, c in enumerate(contas):
            estado = ("erro" if c.motivo_fora else
                      ("atencao" if (c.bloqueados or c.ja_enviados or c.liberados or c.a_mao
                                     or getattr(c, "desmarcados", ())) else ""))
            pai = t.insert("", "end", text=c.rotulo, open=c.rotulo in abertas,
                           tags=widgets.linha_zebrada(i, estado),
                           values=dc.celulas_da_conta(c))
            # iid por POSIÇÃO (`passo2.linhas_da_conta`): o id do lançamento
            # pode repetir (partes) e o Treeview recusa iid repetido.
            for ln in passo2.linhas_da_conta(c, i):
                t.insert(pai, "end", iid=ln.iid, text=ln.texto, tags=ln.tags, values=ln.valores)
                self._iid_pag[ln.iid] = ln

    def _encher_aportes(self):
        t = self.t_apt
        t.delete(*t.get_children())
        self._iid_aporte = {}
        alertas = self.aportes.alertas
        self._mostrar_alertas(
            "\n".join(f"{widgets.MARCAS_ESTADO['erro']} {f}"
                      for tag, f in alertas if tag == "erro"),
            "\n".join(f"{widgets.MARCAS_ESTADO['atencao']} {f}"
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

    # ------------------------------------------------ passo 2 editável (nuvem)
    # Regra nenhuma mora aqui: quem decide é `passo2` / `conferencia` (puros,
    # com teste). Toda gravação e toda releitura correm FORA da thread do Tk
    # (`_na_nuvem`), e a tela só muda com o que a nuvem devolveu ao reler.
    def _cliente_nuvem(self):
        try:
            return DiaNaNuvem(sessao.token(util.pasta_base()))
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] nuvem: {e}")
            return None

    def _registro_nuvem(self):
        try:
            return registro.Registro(sessao.token(util.pasta_base()))
        except Exception:                                   # noqa: BLE001
            return None

    def _selecionada(self):
        """A `passo2.LinhaDaTabela` selecionada no passo 2, ou None."""
        sel = self.t_pag.selection()
        return self._iid_pag.get(sel[0]) if sel else None

    def _linha_erp(self, ld):
        return passo2.linha_do_id(self.leitura.grupos, ld.pagamento.id, ld.pagamento.conta_erp)

    def _selecao_para(self, acao, titulo, recado):
        """A linha selecionada, se ela aceita `acao` e a nuvem deixa gravar."""
        recusa = passo2.recusa_de_gravar(self._nuvem_travada, self._gravando)
        if recusa:
            messagebox.showwarning(titulo, recusa)
            return None
        if self.leitura is None or self.periodo is None:
            return None
        ld = self._selecionada()
        tem_decisao = ld is not None and ld.pagamento.id in self.conferencia.decisoes
        recusa = passo2.recusa_da_selecao(ld, acao, tem_decisao, recado)
        if recusa:
            messagebox.showinfo(titulo, recusa)
            return None
        return ld

    def _na_nuvem(self, titulo, fazer, tipo="decisao", *, depois=""):
        """Grava e RELÊ fora da thread da tela (o rest espera até 20 s) e
        devolve pelo `q` ("gravou"). Nada muda na tela antes da releitura;
        enquanto grava, os botões de gravar ficam apagados (`_gravando`).
        A releitura traz TUDO da nuvem (`passo67.reler_tudo`: decisões, à
        mão, agendados, pendentes, nomes curtos, lista de ontem); o ERP não é
        relido aqui (fora da thread do navegador)."""
        recusa = passo2.recusa_de_gravar(self._nuvem_travada, self._gravando)
        if recusa:
            messagebox.showwarning(titulo, recusa)
            return
        self._gravando = True
        self._ligar_botoes()
        self.lbl.configure(text=f"{titulo}: gravando na nuvem...")
        dia, geracao_da_tela = self.periodo.fim, self._geracao
        anterior = self.lido
        lancamentos = list(self.leitura.lancamentos or ()) if self.leitura is not None else []

        def recado(e):
            base = widgets.recado_de_erro(getattr(e, "causa", None) or e, "Não gravei na nuvem.")
            return passo67.recado_do_erro(e, base, depois=depois)

        def correr():
            try:
                g = passo2.gravar_e_reler(
                    self._cliente_nuvem(), dia, fazer, recado=recado,
                    reler=lambda c, d: passo67.reler_tudo(c, d, anterior, lancamentos))
            except Exception as e:                          # noqa: BLE001
                g = passo2.Gravacao(erro=widgets.recado_de_erro(e, "Não gravei na nuvem."),
                                    travar=f"falha inesperada ao gravar ({e!r}) — busque de novo")
            self.q.put(("gravou", (titulo, tipo, geracao_da_tela, g)))
        threading.Thread(target=correr, daemon=True).start()

    def _receber_gravacao(self, titulo, tipo, geracao_da_tela, g):
        self._gravando = False
        self.lbl.configure(text="")
        if geracao_da_tela != self._geracao or self.leitura is None:
            self._log(f"[!] {titulo}: a gravação terminou depois de outra busca — "
                      "busque de novo para ver o estado da nuvem.")
            self._ligar_botoes()
            return
        if g.travar:
            # Sem reler, o que está na tela pode estar velho: limpa e pede busca.
            self._log(f"[!] {titulo}: {g.travar}")
            self._limpar()
            self._ligar_botoes()         # sem leitura: só o Buscar volta
            self.lbl.configure(text="Busque de novo — a nuvem não foi relida.")
            messagebox.showwarning(titulo, "\n\n".join(filter(None, [
                g.erro, ("A gravação foi aceita pela nuvem." if g.gravado is not None
                         and not g.erro else ""),
                f"{g.travar}.\nA tela foi limpa para não mostrar número velho."])))
            return
        # Decisão (a): a releitura é a da nuvem INTEIRA (`passo67.reler_tudo`).
        lido = g.conferencia
        self.lido, self.conferencia = lido, lido.conferencia
        self.marcas_agd = passo67.marcas_iniciais(lido.pendentes, self.marcas_agd)
        self._montar_lista()
        self._recalcular()               # passo 2, aportes e (mostrar_numeros) agendados/lista
        self._remontar_para_marcar()
        self._encher_para_marcar()
        self._ligar_botoes()
        if g.erro:
            self._log(f"[!] {titulo}: {g.erro}")
            messagebox.showwarning(titulo, g.erro)
            return
        self._log(f"{titulo}: gravado na nuvem.")
        if tipo == "agendados":
            resumo = passo67.resumo_da_marcacao(g.gravado)
            for linha in resumo:
                self._log(f"  {linha}")
            if len(resumo) > 1:          # as repetidas (já marcadas): recado, não erro
                messagebox.showinfo(titulo, resumo[1])
        elif tipo == "respondido":
            n = len(g.gravado) if isinstance(g.gravado, list) else 1
            self._log(f"  {n} resposta(s) gravada(s).")

    def _liberar(self):
        titulo = "Incluir mesmo assim"
        ld = self._selecao_para(passo2.A_LIBERAR, titulo,
                                "Selecione um bloqueado ou um já enviado.")
        if ld is None:
            return
        linha = self._linha_erp(ld)
        if not passo2.pode_liberar(linha):
            messagebox.showinfo(titulo, "Esta linha não se libera aqui (lançamento dividido "
                                        "em partes, ou já vai sair): resolva no ERP ou na "
                                        "Remessa.")
            return
        motivo = janelas.pedir_motivo(self, titulo, f"{passo2.descricao_de(ld.pagamento)}\n"
                                                    f"Bloqueado por: {linha.situacao}")
        if motivo is None:
            return
        # Decisão (a): DEPOIS do motivo, o "tem certeza?" do já enviado e do
        # favorecido fora dos Contatos — a única trava contra pagar em dobro
        # pelo HTML.
        certeza = passo2.certeza_ao_liberar(linha)
        if certeza and not messagebox.askyesno(titulo, certeza, default="no"):
            return
        dia = self.periodo.fim
        self._na_nuvem(titulo, lambda c: c.registrar_decisao(
            dia, alvo=linha.id, conta=linha.conta, acao=cf.LIBERAR, motivo=motivo))

    def _desmarcar(self):
        titulo = "Desmarcar"
        ld = self._selecionada()
        if ld is not None and ld.tipo == passo2.MAO:
            messagebox.showinfo(titulo, "Pagamento à mão não se desmarca: use «Remover à mão».")
            return
        ld = self._selecao_para(passo2.A_DESMARCAR, titulo,
                                "Selecione um pagamento que vai sair.")
        if ld is None:
            return
        motivo = janelas.pedir_motivo(self, titulo, f"{passo2.descricao_de(ld.pagamento)}\n"
                                                    "Sai da planilha, do HTML e da remessa.",
                                      obrigatorio=False)
        if motivo is None:
            return
        p, dia = ld.pagamento, self.periodo.fim
        self._na_nuvem(titulo, lambda c: c.registrar_decisao(
            dia, alvo=p.id, conta=p.conta_erp, acao=cf.DESMARCAR, motivo=motivo))

    def _remover_a_mao(self):
        titulo = "Remover à mão"
        ld = self._selecao_para(passo2.A_REMOVER, titulo, "Selecione um pagamento à mão.")
        if ld is None:
            return
        motivo = janelas.pedir_motivo(self, titulo, f"{passo2.descricao_de(ld.pagamento)}\n"
                                                    "Sai da tela e do HTML.")
        if motivo is None:
            return
        p, dia = ld.pagamento, self.periodo.fim
        self._na_nuvem(titulo, lambda c: c.registrar_decisao(
            dia, alvo=p.id, conta=p.conta_erp, acao=cf.REMOVER_A_MAO, motivo=motivo))

    def _desfazer(self):
        titulo = "Desfazer"
        ld = self._selecao_para(passo2.A_DESFAZER, titulo,
                                "Selecione uma linha liberada, desmarcada ou editada.")
        if ld is None:
            return
        p = ld.pagamento
        if not messagebox.askyesno(titulo, f"Desfazer o que foi decidido para "
                                           f"{passo2.descricao_de(p)}?\n\nLiberação, "
                                           "desmarcação e edições saem: volta a ser o que "
                                           "o ERP diz.", default="no"):
            return
        dia = self.periodo.fim
        self._na_nuvem(titulo, lambda c: c.registrar_decisao(
            dia, alvo=p.id, conta=p.conta_erp, acao=cf.DESFAZER))

    def _editar(self):
        titulo = "Editar o pagamento"
        ld = self._selecao_para(passo2.A_EDITAR, titulo,
                                "Selecione um pagamento que vai sair, liberado ou bloqueado. "
                                "(À mão não se edita: remova e lance de novo.)")
        if ld is None:
            return
        ident, conta = ld.pagamento.id, ld.pagamento.conta_erp
        registro_erp = (geracao.registro_atual(self.leitura.resultado, ident)
                        if self.leitura.resultado is not None else None)
        if registro_erp is None:
            messagebox.showinfo(titulo, "Não achei este lançamento na apuração — busque de novo.")
            return
        # O diálogo abre com o que VALE hoje (o ERP + as edições já gravadas);
        # o `antes` continua o do ERP. Digitar o valor do ERP de volta é uma
        # mudança como outra qualquer.
        iniciais = passo2.valores_iniciais(registro_erp, conta)
        mostrados = passo2.valores_para_editar(registro_erp, conta,
                                               self.conferencia.decisoes.get(ident))
        escolhido = {}

        def validar(r):
            campos = passo2.campos_da_edicao(mostrados, r["campos"])
            erro = passo2.validar_edicao_da_tela(registro_erp, campos, r["motivo"])
            if not erro:
                escolhido["campos"] = campos
            return erro

        r = janelas.pedir_edicao(self, mostrados, explicacao=passo2.descricao_de(ld.pagamento),
                                 validar=validar)
        if r is None or "campos" not in escolhido:
            return
        campos = escolhido["campos"]
        if "descricao" in campos:
            aviso = cf.aviso_de_casamento({**registro_erp, "descricao_editada": campos["descricao"]},
                                          conta)
            if aviso and not messagebox.askyesno(titulo, aviso + "\n\nGravar assim mesmo?",
                                                 default="no"):
                return
        antes, dia = passo2.antes_da_edicao(iniciais, campos), self.periodo.fim
        self._na_nuvem(titulo, lambda c: c.registrar_decisao(
            dia, alvo=ident, conta=conta, acao=cf.EDITAR, motivo=r["motivo"], campos=campos,
            antes=antes, corrigir_no_erp=r["corrigir_no_erp"]))

    def _novo_a_mao(self):
        titulo = "Pagamento à mão"
        recusa = passo2.recusa_de_gravar(self._nuvem_travada, self._gravando)
        if recusa:
            messagebox.showwarning(titulo, recusa)
            return
        if self.leitura is None or self.periodo is None:
            return
        contas = passo2.contas_para_a_mao(self.contas_erp, self.mapping, self.leitura.grupos)
        ids, existentes = passo2.ids_do_dia(self.leitura.grupos), self.conferencia.a_mao

        def montar(r):
            link = r.get("link") or ""
            erro = passo2.recado_do_link(link, r.get("lido"), lancamento_do_erp.id_do_link(link))
            if erro:
                return None, erro
            return cf.nova_a_mao(conta=r["conta"], valor_texto=r["valor"],
                                 descricao=r["descricao"], motivo=r["motivo"],
                                 contas=set(contas), lido=r["lido"] if link.strip() else None,
                                 tipo=r["tipo"], dados=r["dados"], favorecido=r["favorecido"],
                                 ids_do_dia=ids, a_mao_existentes=existentes)

        try:
            dados = janelas.pedir_a_mao(self, contas, self._ler_link,
                                        validar=lambda r: montar(r)[1])
        finally:
            self._ao_ler_link = None
        if dados is None:
            return
        linha, erro = montar(dados)
        if erro:
            messagebox.showwarning(titulo, erro)
            return
        # Lançamento que já está no dia, ou em aberto desconhecido: pergunta.
        pergunta = linha.pop("pergunta", "")
        if pergunta and not messagebox.askyesno(titulo, pergunta, default="no"):
            return
        if not linha.get("lancamento_id") and not messagebox.askyesno(
                titulo, "Sem o link do lançamento, o Anexar não tem o que casar depois. "
                        "Gravar assim mesmo?", default="no"):
            return
        dia = self.periodo.fim
        self._na_nuvem(titulo, lambda c: c.registrar_a_mao(dia, linha), "a_mao")

    def _ler_link(self, texto, ao_ler):
        ident = lancamento_do_erp.id_do_link(texto)
        if not ident:
            ao_ler(None, "Isto não parece o link de um lançamento do Mais Controle.")
            return
        if self.anx.avisar_se_ocupado("ler o lançamento", aba=self):
            ao_ler(None, "O navegador está ocupado — tente de novo daqui a pouco.")
            return
        self._ao_ler_link = ao_ler
        self.anx.submeter("Pagamentos do dia — ler lançamento", self._t_ler_link, ident, dona=self)

    def _t_ler_link(self, ident):
        try:
            api = self.anx.garantir_sessao(self._log)
            conhecidos = self.leitura.lancamentos if self.leitura is not None else ()
            lido = lancamento_do_erp.ler(api, ident, conhecidos, log=self._log)
            self.q.put(("link_lido", (lido, "")))
        except Exception as e:                              # noqa: BLE001
            self.q.put(("link_lido", (None, widgets.recado_de_erro(e, "Não li o lançamento."))))

    # ------------------------------- agendados a confirmar, passos 6 e 7 (nuvem)
    # Regra nenhuma mora aqui: quem decide é `passo67` / `agendados` /
    # `lista_diretor` (puros, com teste). Gravar passa por `_na_nuvem`.
    def _pode_gravar(self, titulo) -> bool:
        recusa = passo2.recusa_de_gravar(self._nuvem_travada, self._gravando)
        if recusa:
            messagebox.showwarning(titulo, recusa)
            return False
        return self.leitura is not None and self.lido is not None and self.periodo is not None

    def _encher_agendados(self):
        t = self.t_agd
        t.delete(*t.get_children())
        pendentes = self.lido.pendentes if self.lido is not None else []
        for i, ln in enumerate(passo67.linhas_agendados(pendentes, self.marcas_agd)):
            t.insert("", "end", iid=ln.iid, values=ln.valores,
                     tags=widgets.linha_zebrada(i, ln.tags[0] if ln.tags else ""))
        if pendentes:
            self.c0.pack(fill="x", padx=self._padx, pady=px((0, 12)), before=self.c1)
        else:
            self.c0.pack_forget()

    def _clique_agd(self, evento):
        t = self.t_agd
        if t.identify_region(evento.x, evento.y) == "cell" and t.identify_column(evento.x) == "#1":
            self._alternar_agd(t.identify_row(evento.y))

    def _alternar_agd(self, iid):
        if not iid or self.lido is None:
            return
        self.marcas_agd = passo67.alternar(self.marcas_agd, int(iid))
        self._encher_agendados()
        if self.t_agd.exists(iid):
            self.t_agd.selection_set(iid)
            self.t_agd.focus(iid)

    def _responder(self, resposta):
        nomes = {"pago": "Pago", "nao_saiu": "Não saiu", "reagendado": "Reagendado"}
        titulo = f"Agendados a confirmar — {nomes[resposta]}"
        if not self._pode_gravar(titulo):
            return
        pend = self.lido.pendentes
        if resposta == "pago":
            itens = passo67.pagos_marcados(pend, self.marcas_agd)
            recusa = passo67.recusa_de_pagar(itens)
            if recusa:
                messagebox.showinfo(titulo, recusa)
                return
            # Marcado sem prova (sumiu, mudou, aguardando): o dono confirma.
            pergunta = passo67.pergunta_ao_pagar(pend, self.marcas_agd)
            if pergunta and not messagebox.askyesno(titulo, pergunta, default="no"):
                return
            self._na_nuvem(titulo, lambda c: passo67.responder_pagos(c, itens), "respondido")
            return
        sel = self.t_agd.selection()
        ident = int(sel[0]) if sel else None
        if ident is None:
            messagebox.showinfo(titulo, "Selecione um agendado da lista.")
            return
        r = janelas.pedir_resposta(self, titulo, com_data=resposta == "reagendado")
        if r is None:
            return
        motivo, nova_data = r
        recusa = passo67.recusa_da_resposta(pend, ident, resposta, motivo, nova_data,
                                            datetime.date.today())
        if recusa:
            messagebox.showwarning(titulo, recusa)
            return
        self._na_nuvem(titulo, lambda c: c.responder(ident, resposta, motivo=motivo,
                                                     nova_data=nova_data), "respondido")

    # passo 6
    def _novos_para_marcar(self):
        return agd.para_marcar(self.pagamentos, self.fora, self.leitura.lancamentos,
                               self.conferencia, {a.alvo for a in self.lido.agendados_hoje})

    def _montar_para_marcar(self):
        if not self._pode_gravar("Marcar agendados"):
            return
        self.para_marcar_itens = self._novos_para_marcar()
        self._encher_para_marcar()
        self._ajustar_altura(self.t_marcar)
        if not self.para_marcar_itens:
            self._log("Marcar agendados: nada sai hoje.")

    def _remontar_para_marcar(self):
        """Depois de reler: a lista nova, com o desmarcado pelo dono guardado."""
        if self.para_marcar_itens is None or self.leitura is None or self.lido is None:
            return
        self.para_marcar_itens = passo67.remontar_para_marcar(self._novos_para_marcar(),
                                                              self.para_marcar_itens)

    def _encher_para_marcar(self):
        t = self.t_marcar
        t.delete(*t.get_children())
        for i, ln in enumerate(passo67.linhas_para_marcar(self.para_marcar_itens or ())):
            t.insert("", "end", iid=ln.iid, values=ln.valores,
                     tags=widgets.linha_zebrada(i, ln.tags[0] if ln.tags else ""))

    def _clique_marcar(self, evento):
        t = self.t_marcar
        if t.identify_region(evento.x, evento.y) == "cell" and t.identify_column(evento.x) == "#1":
            self._alternar_marcar(t.identify_row(evento.y))

    def _alternar_marcar(self, iid):
        if not iid or self.para_marcar_itens is None:
            return
        self.para_marcar_itens, recado = passo67.alternar_para_marcar(self.para_marcar_itens,
                                                                      int(iid))
        if recado:
            messagebox.showinfo("Marcar agendados", recado)
            return
        self._encher_para_marcar()
        if self.t_marcar.exists(iid):
            self.t_marcar.selection_set(iid)
            self.t_marcar.focus(iid)

    def _gravar_agendados(self):
        titulo = "Gravar agendados"
        if not self._pode_gravar(titulo):
            return
        recusa = passo67.recusa_de_marcar(self.para_marcar_itens)
        if recusa:
            messagebox.showinfo(titulo, recusa)
            return
        linhas, dia = agd.linhas_para_nuvem(self.para_marcar_itens), self.periodo.fim
        self._na_nuvem(titulo, lambda c: c.marcar_agendados(dia, linhas), "agendados")

    # passo 7
    def _montar_lista(self):
        """A lista de HOJE; a ordem que o dono já arrumou vale sobre a de ontem."""
        if self.lido is None or self.mapping is None:
            self.lista = []
            return

        def rotulo(conta):
            achado = self.mapping.resolve_label(conta)
            return achado.label if achado else conta
        try:
            self.lista = passo67.montar_lista(self.lido.agendados_hoje, rotulo,
                                              self.lido.nomes_curtos, self.lido.lista_anterior,
                                              atual=self.lista)
        except ValueError as e:
            self.lista = []
            self._log(f"[!] lista do diretor: {e}")

    def _indice_lista(self):
        sel = self.t_lista.selection()
        try:
            i = int(sel[0]) if sel else None
        except ValueError:
            return None
        return i if i is not None and 0 <= i < len(self.lista) else None

    def _encher_lista(self, selecionar=None):
        t = self.t_lista
        t.delete(*t.get_children())
        for i, ln in enumerate(self.lista):
            t.insert("", "end", iid=str(i), tags=widgets.linha_zebrada(
                         i, "atencao" if ln.sem_nome_curto else ""),
                     values=(f"{ln.ordinal}º" if ln.ordinal else "", ln.nome, brl(ln.valor)))
        if selecionar is not None:
            i = next((n for n, ln in enumerate(self.lista) if ln.rotulo == selecionar), None)
            if i is not None:
                t.selection_set(str(i))
                t.focus(str(i))
        self._ligar_lista()

    def _lista_mover(self, delta):
        i = self._indice_lista()
        if not passo67.pode_mover(self.lista, i, delta):
            return
        rotulo = self.lista[i].rotulo
        self.lista = ldr.mover(self.lista, i, delta)
        self._encher_lista(selecionar=rotulo)

    def _lista_ordinal(self):
        i = self._indice_lista()
        if i is None:
            return
        rotulo = self.lista[i].rotulo
        self.lista = ldr.alternar_ordinal(self.lista, i)
        self._encher_lista(selecionar=rotulo)

    def _nome_curto(self):
        titulo = "Nome curto da conta"
        if not self._pode_gravar(titulo):
            return
        i = self._indice_lista()
        if i is None:
            messagebox.showinfo(titulo, "Selecione uma linha da lista do diretor.")
            return
        rotulo, nomes = self.lista[i].rotulo, self.lido.nomes_curtos
        atual = nomes.get(rotulo, "")
        while True:
            nome = janelas.pedir_nome_curto(self, rotulo, atual)
            if nome is None:
                return
            erro = passo67.validar_nome_curto(nome, rotulo, nomes, self.lista)
            if not erro:
                break
            messagebox.showwarning(titulo, erro)
            atual = nome
        nome = nome.strip()
        if nome == nomes.get(rotulo):
            return
        self._na_nuvem(titulo, lambda c: c.gravar_nome_curto(rotulo, nome), "nome_curto")

    def _copiar_lista(self):
        titulo = "Lista do diretor"
        if not self._pode_gravar(titulo):
            return
        recusa = passo67.recusa_de_copiar(self.lista)
        if recusa:
            messagebox.showinfo(titulo, recusa)
            return
        texto = ldr.texto_whatsapp(self.lista)
        # Clipboard só na thread da tela; a gravação vai depois, para a
        # sugestão de amanhã — falhar nela não desfaz a cópia.
        self.clipboard_clear()
        self.clipboard_append(texto)
        self._log("Lista copiada — cole no WhatsApp.")
        ordem, dia = ldr.para_nuvem(self.lista), self.periodo.fim
        self._na_nuvem(titulo, lambda c: c.gravar_lista(dia, ordem, texto), "lista",
                       depois="A lista JÁ foi copiada; o que se perdeu é só a sugestão de "
                              "ordem de amanhã.")

    # ----------------------------------------------------------------- gerar
    def _ocupado(self, titulo) -> bool:
        if self.worker and not self.worker.done():
            messagebox.showinfo(titulo, "Espere a leitura em andamento terminar.")
            return True
        if self._gravando:
            # Gerar no meio da gravação sairia com a decisão de antes.
            messagebox.showinfo(titulo, "Espere a gravação na nuvem terminar.")
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
        # Nuvem que FALHOU: as decisões do dono não estão aplicadas.
        pergunta = passo2.pergunta_ao_gerar(self._nuvem_travada)
        if pergunta and not messagebox.askyesno(titulo, pergunta, default="no"):
            return False
        return True

    def _resultado_que_sai(self):
        """Planilha, HTML e (sem os à mão) remessa: o da Remessa com as
        decisões do dono. Conferência vazia (nuvem fora) = entrega 1."""
        return geracao.resultado_da_tela(self.leitura.entradas, self.leitura.grupos,
                                         self.conferencia)

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
        except Exception as e:                              # noqa: BLE001
            # Como os outros geradores: erro inesperado vira recado, nunca a
            # exceção crua no callback do Tk (a pessoa acharia que gerou).
            self._log(f"\nO EXCEL DO DIA NÃO FOI GERADO\n[!] {e!r}")
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
        resultado = self._resultado_que_sai()
        for r in (r for regs in resultado.contas.values() for r in regs if r.get("a_mao")):
            self._log(f"  à mão não vai na remessa — pague pelo HTML: "
                      f"{r['favorecido']} {brl(de_float(r['valor']))}")
        self.aba_remessa.receber_apuracao(self.leitura, pg.ids_que_nao_saem(self.leitura.grupos),
                                          resultado=geracao.para_a_remessa(resultado))

    # --------------------------------------------------- aba Aportes
    def _mandar_aportes(self):
        titulo = "Aportes"
        if self.aba_aportes is None or self.aportes is None or self._ocupado(titulo):
            return
        if self._dia_bloqueado:
            # Sem o arquivo do dia, não se sabe o que já foi mandado hoje: mandar
            # agora pode ser o segundo aporte (o ERP somaria os dois).
            messagebox.showwarning(titulo, f"{self._dia_bloqueado}\n\nÉ no arquivo do dia "
                                           "que fica o que já foi mandado hoje. Confira a "
                                           "aba Aportes e o arquivo (veja o Registro) "
                                           "antes de mandar.")
            return
        envio = para_aportes.operacoes(
            self.aportes.definidos_validos, self.regras, self.aba_aportes.entidades,
            self.aba_aportes.subcontas, dc.data_das_operacoes(self.periodo),
            enviados=dict(self.dia.enviados_aportes),
            sem_saldo=dc.contas_sem_saldo(self.saldos),
            na_aba_aportes=list(self.aba_aportes.operacoes))
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
        # O registro do que foi mandado é gravado ANTES de entregar: gravação
        # que falha não manda nada. Ao contrário (mandar e depois não conseguir
        # anotar), o próximo Buscar esqueceria o envio e o aporte iria em dobro.
        antes = dict(self.dia.enviados_aportes)
        self.dia.enviados_aportes = para_aportes.enviados_apos(antes, envio, mandadas, [])
        if not self._gravar_dia():
            self.dia.enviados_aportes = antes
            self._dia_bloqueado = self._dia_bloqueado or (
                "não consegui gravar o arquivo do dia (veja o Registro)")
            self._log("\nNADA foi para a aba Aportes: o registro do que é mandado não "
                      "foi gravado.")
            messagebox.showerror(titulo, "Não consegui gravar o arquivo do dia, onde fica o "
                                         "registro do que foi mandado — por isso NADA foi "
                                         "para a aba Aportes. Veja o Registro.")
            return
        recusas = self.aba_aportes.receber_operacoes(mandadas)
        recusadas = para_aportes.operacoes_recusadas(mandadas, recusas)
        for (_i, motivo), op in zip(recusas, recusadas):
            self._log(f"  [!] a aba Aportes recusou {op.resumo()}: {motivo}")
        if recusadas:
            # As recusadas não estão na aba: desmarcá-las. Se esta segunda
            # gravação falhar, o arquivo fica com elas como mandadas — o lado
            # seguro (seguram um envio, nunca liberam um segundo).
            self.dia.enviados_aportes = para_aportes.enviados_apos(antes, envio, mandadas,
                                                                   recusadas)
            if not self._gravar_dia():
                self._dia_bloqueado = self._dia_bloqueado or (
                    "não consegui gravar o arquivo do dia (veja o Registro)")
                messagebox.showerror(titulo, "O registro do que foi mandado NÃO foi salvo "
                                             "— não mande de novo antes de conferir a aba "
                                             "Aportes.")
        aceitas = len(mandadas) - len(recusadas)
        self._log(f"\n{aceitas} operação(ões) na lista da aba Aportes — confira lá e "
                  "clique em Lançar no Mais Controle.")
        if aceitas:
            self.abrir_aportes()
