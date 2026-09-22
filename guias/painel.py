# -*- coding: utf-8 -*-
"""O bloco "Guias do mês → Mais Controle" da aba Acessórias.

Treeview, e não um bloco de widgets por linha: as listas de conferência do app
caíram de 5,4 s para 0,14 s quando mudaram para Treeview, e esta lista tem
dezenas de linhas.

Nada de rede nesta thread. `varrer` e `lancar` empurram o trabalho para o
executor da aba e a tela só lê a fila — falar com o Tcl de dentro do worker
trava sem hora marcada, que é a falha que nunca aparece em teste.
"""
from __future__ import annotations

import datetime as dt
import os
import tkinter as tk
import webbrowser
from collections import Counter
from tkinter import ttk

import util
import widgets
from anexar import config as anx_config
from guias.modelos import ALTERAR, CRIAR, DECIDIR, JA_LANCADO

log = util.log(__name__)

#: Os nomes dos meses vêm de `widgets`, e não de `acessorias.frame`: a aba
#: importa ESTE módulo, e importá-la de volta fecharia o ciclo.
MESES = list(widgets.MESES)

#: A ordem do trabalho: o que vai ser gravado, o que precisa de você, o pronto.
SECOES = (ALTERAR, CRIAR, DECIDIR, JA_LANCADO)

#: As duas colunas que o duplo clique edita. Valor e vencimento saem do
#: documento e não se digitam: o que vale é o que está no PDF.
CAMPOS_EDITAVEIS = ("categoria", "obra")

TITULOS = {ALTERAR: "Alterar a recorrência",
           CRIAR: "Criar o lançamento",
           DECIDIR: "Você decide",
           JA_LANCADO: "Já lançado"}

#: Só estas duas são gravadas. "Você decide" nunca entra por distração.
LANCAVEIS = (ALTERAR, CRIAR)

COLUNAS = (("empresa", "Empresa", 170), ("documento", "Documento", 230),
           ("venc", "Vence", 90), ("valor", "Valor", 100),
           ("categoria", "Categoria", 150), ("obra", "Obra", 150),
           ("estado", "Situação", 260))


class GuiasPainel(ttk.Frame):
    def __init__(self, master, aba=None, anx=None):
        super().__init__(master)
        self.aba = aba                   # AcessoriasFrame: fila, log, executor
        self.anx = anx                   # AnexarFrame: a sessão do ERP
        self.decisoes = {}               # iid -> Decisao
        self.marcado = {}                # iid -> bool
        self.secoes = {}                 # ação -> iid do nó da seção
        self._tarefa = ""
        #: Nomes vindos do cadastro do ERP, para os combos de correção.
        #: Preenchidos pela varredura; vazios antes dela.
        self.categorias: list[str] = []
        self.obras: list[dict] = []

        # O mês é o ATUAL, e não o anterior: o bloco de cima manda o
        # fechamento do mês passado ao escritório; este traz o que vence
        # agora. Mesma aba, dois calendários — e trocar os dois seria o
        # tipo de erro que ninguém percebe até faltar guia no mês.
        hoje = dt.date.today()
        self.v_mes = tk.StringVar(value=MESES[hoje.month - 1])
        self.v_ano = tk.StringVar(value=str(hoje.year))

        self._build()

    @property
    def periodo(self) -> tuple[int, int]:
        """(ano, mês) escolhidos. SÓ na thread da interface: ler `StringVar` é
        falar com o Tcl, e o Tcl é de quem criou a janela."""
        return int(self.v_ano.get()), MESES.index(self.v_mes.get()) + 1

    # ---------------------------------------------------------------- layout

    def _build(self):
        topo = ttk.Frame(self)
        topo.pack(fill="x", pady=(widgets.px(8), widgets.px(4)))
        ttk.Label(topo, text="Guias do mês → Mais Controle",
                  style="Titulo.TLabel").pack(side="left")

        ttk.Combobox(topo, textvariable=self.v_mes, values=MESES, width=12,
                     state="readonly").pack(side="left", padx=(widgets.px(12), 0))
        ttk.Entry(topo, textvariable=self.v_ano, width=6).pack(
            side="left", padx=widgets.px(4))

        ttk.Button(topo, text="Varrer o portal",
                   command=self.varrer).pack(side="right")
        ttk.Button(topo, text="Lançar o marcado",
                   command=self.lancar).pack(side="right", padx=widgets.px(6))
        ttk.Button(topo, text="Parar", command=self.parar).pack(side="right")

        self.lista = ttk.Treeview(self, columns=[c[0] for c in COLUNAS],
                                  show="tree headings", height=14)
        self.lista.heading("#0", text="")
        self.lista.column("#0", width=widgets.px(30), stretch=False)
        for chave, titulo, largura in COLUNAS:
            self.lista.heading(chave, text=titulo)
            self.lista.column(chave, width=widgets.px(largura), stretch=True)
        self.lista.pack(fill="both", expand=True)
        self.lista.bind("<space>", self._tecla_marcar)
        self.lista.bind("<Button-1>", self._clique)
        self.lista.bind("<Double-1>", self._duplo_clique)

        pe = ttk.Frame(self)
        pe.pack(fill="x", pady=widgets.px(4))
        ttk.Button(pe, text="Abrir o PDF",
                   command=lambda: self._na_selecionada(self.abrir_pdf)).pack(
                       side="left")
        ttk.Button(pe, text="Abrir no ERP",
                   command=lambda: self._na_selecionada(self.abrir_no_erp)).pack(
                       side="left", padx=widgets.px(6))

        for acao in SECOES:
            self.secoes[acao] = self.lista.insert(
                "", "end", text="", values=(TITULOS[acao], "", "", "", "", "", ""),
                open=True, tags=("secao",))

    def _na_selecionada(self, funcao):
        for iid in self.lista.selection():
            if iid in self.decisoes:
                funcao(iid)
                return

    # ------------------------------------------------------------- conteúdo

    def mostrar(self, decisoes) -> None:
        """Repõe a lista inteira. SÓ na thread da interface."""
        for iid in list(self.decisoes):
            self.lista.delete(iid)
        self.decisoes.clear()
        self.marcado.clear()
        for decisao in decisoes:
            self._inserir(decisao)

    def _nome_da_obra(self, obra_id: str) -> str:
        for obra in self.obras:
            if str(obra.get("id")) == str(obra_id):
                return str(obra.get("name") or obra_id)
        return str(obra_id or "")

    def _valores(self, decisao) -> tuple:
        guia = decisao.guia
        obra = self._nome_da_obra(decisao.obra_id)
        if obra and decisao.obra_sugerida:
            # Palpite sobre o texto do documento, e não regra confirmada: a
            # linha diz isso, senão o "?" some junto com a diferença.
            obra += "  ?"
        return (guia.empresa, guia.documento or guia.desc[:40],
                guia.vencimento.strftime("%d/%m") if guia.vencimento else "",
                util.fmt_val(int((guia.valor or 0) * 100)) if guia.valor else "",
                decisao.categoria, obra,
                decisao.motivo or decisao.aviso or "")

    def _inserir(self, decisao) -> str:
        marca = decisao.acao in LANCAVEIS
        iid = self.lista.insert(self.secoes[decisao.acao], "end",
                                text="[x]" if marca else "[ ]",
                                values=self._valores(decisao))
        self.decisoes[iid] = decisao
        self.marcado[iid] = marca
        return iid

    # --------------------------------------------------------------- edição

    def editar(self, iid: str, campo: str, valor: str) -> None:
        """Troca categoria ou obra de UMA linha. O que o dono escolhe aqui é o
        que a Tarefa 9 grava na regra — por isso a decisão muda, e não só a
        aparência da linha."""
        decisao = self.decisoes.get(iid)
        if decisao is None or campo not in CAMPOS_EDITAVEIS or not valor:
            return
        if campo == "categoria":
            decisao.categoria = valor
        else:
            decisao.obra_id = valor
            decisao.obra_sugerida = False   # agora é escolha, não palpite
        self.lista.item(iid, values=self._valores(decisao))

    def _duplo_clique(self, evento):
        iid = self.lista.identify_row(evento.y)
        if iid not in self.decisoes:
            return None
        coluna = self.lista.identify_column(evento.x)
        indice = int(coluna[1:]) - 1 if coluna.startswith("#") else -1
        if not 0 <= indice < len(COLUNAS):
            return None
        campo = COLUNAS[indice][0]
        if campo not in CAMPOS_EDITAVEIS:
            return None
        self._pedir_valor(iid, campo)
        return "break"

    def _opcoes_de(self, campo: str) -> dict[str, str]:
        """Rótulo -> valor gravável, para o `ComboBusca` de correção.

        Duas obras com o MESMO nome no cadastro do ERP fariam o dicionário
        guardar só a última, e a escolha do dono apontaria para a outra em
        silêncio — e é a obra que decide a conta que paga. Nome que repete
        ganha desempate visível; nome único fica limpo."""
        if campo == "categoria":
            return {nome: nome for nome in self.categorias}
        vezes = Counter(str(o.get("name") or "") for o in self.obras)
        opcoes = {}
        for obra in self.obras:
            nome = str(obra.get("name") or "")
            ident = str(obra.get("id") or "")
            if not nome or not ident:
                continue
            rotulo = nome if vezes[nome] == 1 else f"{nome} [{ident[:8]}]"
            opcoes[rotulo] = ident
        return opcoes

    def _pedir_valor(self, iid: str, campo: str) -> None:
        """Abre um `ComboBusca` com os nomes do cadastro do ERP.

        Digita-se para procurar, e nada é escolhido por adivinhação: texto que
        não é uma opção não vira nada (é a regra do próprio widget)."""
        opcoes = self._opcoes_de(campo)
        if not opcoes:
            if self.aba is not None:
                self.aba._log("[!] Varra o portal primeiro: os nomes de "
                              "categoria e obra vêm do cadastro do ERP.")
            return

        janela = tk.Toplevel(self)
        janela.title("Escolher " + campo)
        widgets.barra_de_titulo(janela)
        combo = widgets.ComboBusca(janela, width=44)
        combo.definir_valores(sorted(opcoes))
        combo.pack(padx=widgets.px(12), pady=widgets.px(12))
        combo.focus_set()

        def confirmar(_ev=None):
            escolhido = opcoes.get(combo.get().strip())
            janela.destroy()
            if escolhido:
                self.editar(iid, campo, escolhido)
            elif self.aba is not None:
                self.aba._log(f"Nada gravado: o texto digitado não é uma opção "
                              f"de {campo}.")

        combo.bind("<Return>", confirmar)
        ttk.Button(janela, text="Usar este", command=confirmar).pack(
            pady=(0, widgets.px(10)))

    # --------------------------------------------------------------- atalhos

    def abrir_pdf(self, iid: str) -> None:
        decisao = self.decisoes.get(iid)
        caminho = getattr(getattr(decisao, "guia", None), "pdf", None)
        if not caminho:
            if self.aba is not None:
                self.aba._log("Esta linha não tem PDF.")
            return
        try:
            os.startfile(str(caminho))          # noqa: S606  (Windows)
        except OSError:
            log.warning("não deu para abrir o PDF da guia", exc_info=True)

    def abrir_no_erp(self, iid: str) -> None:
        """Abre a PARCELA no ERP. A rota do ERP é por parcela (`launchId`), e
        não por título: mandar o id do título para lá abre uma tela vazia."""
        decisao = self.decisoes.get(iid)
        if decisao is None or not decisao.parcela_id:
            if self.aba is not None:
                self.aba._log("Esta linha ainda não tem parcela no ERP "
                              "(criação só ganha id depois de lançada).")
            return
        webbrowser.open(anx_config.MC_URL_LANCAMENTO + decisao.parcela_id)

    def parar(self) -> None:
        """Pede a parada da rodada. Quem observa é o worker, entre itens."""
        if self.aba is not None:
            self.aba._parar.set()

    def linhas_de(self, acao) -> list[str]:
        return list(self.lista.get_children(self.secoes[acao]))

    def quantas(self, acao) -> int:
        return len(self.linhas_de(acao))

    def texto_da_linha(self, iid: str) -> str:
        return " ".join(str(v) for v in self.lista.item(iid, "values"))

    def marcadas(self) -> list:
        return [d for iid, d in self.decisoes.items()
                if self.marcado.get(iid) and d.acao in LANCAVEIS]

    def alternar(self, iid: str) -> None:
        if iid not in self.decisoes:
            return
        if self.decisoes[iid].acao not in LANCAVEIS:
            return                        # "você decide" não se marca
        self.marcado[iid] = not self.marcado[iid]
        self.lista.item(iid, text="[x]" if self.marcado[iid] else "[ ]")

    def _clique(self, evento):
        if self.lista.identify_column(evento.x) == "#0":
            self.alternar(self.lista.identify_row(evento.y))
            return "break"
        return None

    def _tecla_marcar(self, _evento=None):
        for iid in self.lista.selection():
            self.alternar(iid)
        return "break"

    # ---------------------------------------------------------------- ações

    def ocupado(self) -> str | None:
        """O que está rodando aqui, para a aba não deixar sair no meio."""
        if self.aba is None:
            return None
        return getattr(self, "_tarefa", "") or None

    def fechar(self) -> None:
        self._tarefa = ""

    def _executar(self, funcao, *args) -> None:
        """Manda para o executor da aba. Trocado por dublê no teste."""
        if self.aba is None:
            return
        self.aba.worker = self.aba.exec.submit(funcao, *args)

    def varrer(self) -> None:
        if self.ocupado():
            return
        ano, mes = self.periodo        # lido AQUI: o worker não fala com o Tcl
        if self.aba is not None:
            self.aba._parar.clear()
        self._tarefa = "varrendo o portal"
        self._executar(self._t_varrer, ano, mes)

    def lancar(self) -> None:
        alvo = self.marcadas()
        if not alvo or self.ocupado():
            return
        ano, mes = self.periodo
        if self.aba is not None:
            self.aba._parar.clear()
        self._tarefa = "lançando no Mais Controle"
        self._executar(self._t_lancar, alvo, ano, mes)

    # Os dois corpos de thread ficam em `_t_varrer`/`_t_lancar`, ligados na
    # Tarefa 9, quando o painel passa a ter a aba e a sessão do ERP.
    def _t_varrer(self, ano, mes):                        # pragma: no cover
        raise NotImplementedError

    def _t_lancar(self, decisoes, ano, mes):              # pragma: no cover
        raise NotImplementedError
