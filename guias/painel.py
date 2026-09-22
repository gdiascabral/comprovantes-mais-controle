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

import calendar
import datetime as dt
import os
import tkinter as tk
import webbrowser
from collections import Counter
from tkinter import ttk
from urllib.parse import urlencode

import util
import widgets
from acessorias import pacote
from acessorias.portal import PortalClient
from anexar import config as anx_config
from guias import calendario, casamento, lancar, regras, registro
from guias.modelos import ALTERAR, CRIAR, DECIDIR, JA_LANCADO, Resultado

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


# --------------------------------------------------------- Mais Controle

def _sessao_do_erp(painel):
    """(transporte, catalogos, id_usuario), pela página que o app já tem logada.

    Mesmo caminho da aba Aportes: passar pela LISTA de Pagamentos faz o ERP
    autenticar os dois back-ends de cadastro, e os cabeçalhos são copiados do
    tráfego da própria página. Sem login novo — o ERP aceita uma sessão por
    usuário, e um login por HTTP derrubaria a do dono.
    """
    from aportes import erp_sessao
    from aportes.mc_catalogos import Catalogos
    from erp.pagina import TransportePagina

    api = painel.anx.garantir_sessao(painel.aba._log)
    pagina = painel.anx.mc.page
    cabecalhos: dict = {}
    ao_requisitar = erp_sessao.ouvinte(cabecalhos)
    pagina.on("request", ao_requisitar)
    try:
        if erp_sessao.na_lista_de_pagamentos(pagina.url):
            pagina.reload(wait_until="domcontentloaded")
        else:
            pagina.goto(anx_config.MC_URL_PAGAMENTOS,
                        wait_until="domcontentloaded")
        for _ in range(60):
            if all(h in cabecalhos for h in erp_sessao.HOSTS_CADASTRO):
                break
            pagina.wait_for_timeout(250)
    finally:
        try:
            pagina.remove_listener("request", ao_requisitar)
        except Exception:
            pass

    faltando = [h for h in erp_sessao.HOSTS_CADASTRO if h not in cabecalhos]
    if faltando:
        raise RuntimeError(
            "não consegui a autenticação de " + ", ".join(faltando) + ".\n"
            "Abra a LISTA de Pagamentos no Chrome (ou recarregue com F5).")

    transporte = TransportePagina(pagina, cabecalhos)
    catalogos = Catalogos(pagina, cabecalhos, painel.aba._log)
    catalogos.carregar()

    # As obras NÃO vêm do `carregar()`: elas saem do REST do outro back-end,
    # pela mesma porta que a aba Contratos usa. Sem este passo `obras` fica
    # vazio e toda criação morre com "Obra não encontrada" — cadastro que
    # está lá, certo, o tempo todo (`aportes/aportes_frame._carregar_obras`).
    try:
        api.garantir_credenciais_anexos(painel.aba._log)
        catalogos.definir_obras(api.listar_obras(painel.aba._log))
    except Exception as e:                                  # noqa: BLE001
        catalogos.definir_obras([])
        painel.aba._log(f"  aviso (obras): {e}")

    return transporte, catalogos, transporte.cabecalho("user-id") or ""


def _nomes_de(indice) -> list[str]:
    """Os `name` de um índice do `Catalogos` (que é {chave: item})."""
    return sorted({str(item.get("name") or "") for item in (indice or {}).values()
                   if item.get("name")})


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
        if guia.vencimento:
            vence = guia.vencimento.strftime("%d/%m")
        elif guia.vencimento_portal:
            # Mesma razão da obra sugerida: o `prz` do portal é palpite (o
            # PDF não trouxe vencimento), e palpite tem de aparecer como
            # palpite.
            vence = guia.vencimento_portal.strftime("%d/%m") + "  ?"
        else:
            vence = ""
        return (guia.empresa, guia.documento or guia.desc[:40], vence,
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
        descartadas = 0
        for obra in self.obras:
            nome = str(obra.get("name") or "")
            ident = str(obra.get("id") or "")
            if not nome or not ident:
                # Obra com cadastro incompleto no ERP: some da lista em vez de
                # aparecer em branco ou apontar para um id vazio — mas sumir
                # calado faz o dono achar que a obra não existe.
                descartadas += 1
                continue
            rotulo = nome if vezes[nome] == 1 else f"{nome} [{ident[:8]}]"
            opcoes[rotulo] = ident
        if descartadas and self.aba is not None:
            self.aba._log(f"{descartadas} obra(s) com cadastro incompleto "
                          f"ficaram fora da lista.")
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
        if self.anx is None:
            return
        if self.anx.avisar_se_ocupado("as Guias do mês"):
            return
        ano, mes = self.periodo
        if self.aba is not None:
            self.aba._parar.clear()
        self._tarefa = "lançando no Mais Controle"
        self.anx.submeter("Guias — lançar", self._t_lancar, alvo, ano, mes,
                          dona=self.aba)

    def _t_varrer(self, ano: int, mes: int):
        """Roda na thread do executor DESTA aba (o portal, Chrome próprio).

        `ano` e `mes` chegam como argumento porque foram lidos na thread da
        interface: ler `StringVar` daqui trava sem hora marcada.

        Só a FASE 1 (portal) mora aqui. O caminho feliz entrega o que baixou
        à fase 2 (`casar`, na thread da tela) pela fila e NÃO limpa
        `self._tarefa` — a rodada continua, e quem limpa é `_t_casar`. Só os
        ramos de saída antecipada (mapa ausente, erro) limpam aqui, porque
        para eles não há fase 2 nenhuma vindo depois."""
        try:
            if not self.aba._garantir_mapa():
                self.aba._log("[!] Preencha o arquivo de contas antes: é dele "
                              "que saem o endereço do portal e as empresas.")
                self._tarefa = ""
                return
            mapa = self.aba.mapa
            scfg, _ = self.aba._sicoob_mods()

            def pasta_de(empresa):
                return (pacote.pasta_do_mes(mapa.raiz, ano, mes, scfg.nome_do_mes)
                        / scfg.nome_pasta_empresa(ano, mes, empresa.nome))

            with PortalClient(mapa.vip_url, log=self.aba._log,
                              headless=True) as cliente:
                cliente.aguardar_login()
                guias = calendario.varrer(cliente, mapa, ano, mes,
                                          pasta_de=pasta_de, log=self.aba._log,
                                          parar=self.aba._parar.is_set)
            self.aba.q.put(("guias_baixadas", (guias, ano, mes)))
        except Exception as e:
            self.aba._log(f"[!] {e}")
            log.warning("a varredura de guias parou", exc_info=True)
            self._tarefa = ""

    def casar(self, guias, ano: int, mes: int) -> None:
        """Fase 2 da rodada: lê o ERP e decide. THREAD DA TELA.

        O ERP é falado pelo executor do Anexar, e não pelo desta aba: os
        objetos do Playwright síncrono pertencem à thread que os criou, e
        tocá-los de outra dá erro de greenlet. É o mesmo caminho que Aportes,
        Contratos, Conciliação e Conferência usam.
        """
        if self.aba is not None and self.aba._parar.is_set():
            # Quem aperta Parar na fase do portal normalmente quer o ERP
            # LIVRE — e o ERP aceita uma sessão por usuário. `calendario.varrer`
            # só observa o `parar` ENTRE empresas e devolve o que já baixou;
            # sem esta guarda, essa saída antecipada ainda abriria a sessão do
            # Mais Controle para casar o que sobrou.
            self.aba._log("Parado a pedido: não vou abrir o Mais Controle.")
            self._tarefa = ""
            return
        if self.anx is None:
            self._tarefa = ""
            return
        if self.anx.avisar_se_ocupado("as Guias do mês"):
            # Recusar ANTES de mexer em botão ou fila: quem sai por aqui não
            # passa mais pelo `_drain`.
            self._tarefa = ""
            return
        self._tarefa = "casando no Mais Controle"
        self.anx.submeter("Guias — casar no ERP", self._t_casar,
                          guias, ano, mes, dona=self.aba)

    def _t_casar(self, guias, ano: int, mes: int):
        """Roda na thread do NAVEGADOR (executor do Anexar). Nada de Tcl."""
        try:
            transporte, catalogos, _uid = _sessao_do_erp(self)
            parcelas = self._parcelas_do_mes(transporte, ano, mes)
            obras = list(getattr(catalogos, "obras", {}).values())
            regras_ = regras.Regras.carregar()
            registro_ = registro.Registro.carregar()
            decisoes = casamento.decidir(guias, parcelas, regras_, registro_,
                                         f"{ano:04d}-{mes:02d}", obras=obras)
            # Os nomes do cadastro vão junto: é deles que os combos de
            # correção da tela se servem, e sem eles o duplo clique não abre.
            self.aba.q.put(("guias_cadastro",
                            (_nomes_de(catalogos.categorias), obras)))
            self.aba.q.put(("guias", decisoes))
        except Exception as e:
            self.aba._log(f"[!] {e}")
            log.warning("o casamento das guias parou", exc_info=True)
        finally:
            self._tarefa = ""

    def _parcelas_do_mes(self, transporte, ano: int, mes: int) -> list[dict]:
        """As parcelas do mês inteiro, numa leitura só (`size=3000`)."""
        from erp import hosts
        ultimo = calendar.monthrange(ano, mes)[1]
        parametros = urlencode({
            "page": 0, "size": 3000, "type": "ALL", "onlyWork": "false",
            "dateField": "PLANNED", "costCentreType": "ALL",
            "conciliationType": "ALL", "tradePayableType": "ALL",
            "batchOperationType": "NONE",
            "startDate": f"{ano:04d}-{mes:02d}-01",
            "endDate": f"{ano:04d}-{mes:02d}-{ultimo:02d}"})
        resposta = transporte.buscar(
            f"{hosts.LEGACY}/payable-installments/paginated-result?{parametros}")
        if isinstance(resposta, dict) and resposta.get("__erro"):
            raise RuntimeError(f"o ERP recusou a lista de parcelas "
                               f"(HTTP {resposta['__erro']})")
        return list((resposta or {}).get("content") or [])

    def _t_lancar(self, decisoes, ano: int, mes: int):
        try:
            transporte, catalogos, id_usuario = _sessao_do_erp(self)
            parcelas = self._parcelas_do_mes(transporte, ano, mes)
            self._gravar(decisoes, transporte=transporte, catalogos=catalogos,
                         id_usuario=id_usuario,
                         registro=registro.Registro.carregar(),
                         parcelas=parcelas, regras=regras.Regras.carregar(),
                         pasta_backup=util.pasta_base() / "guias_backup")
        except Exception as e:
            self.aba._log(f"[!] {e}")
            log.warning("o lançamento de guias parou", exc_info=True)
        finally:
            self._tarefa = ""

    def _gravar(self, decisoes, *, transporte, catalogos, id_usuario, registro,
                parcelas, regras, pasta_backup) -> None:
        """Grava uma decisão por vez, anotando SEMPRE — inclusive o erro.

        `regras.gravar()` mora num `finally` que envolve o laço inteiro: o
        `return` do "Parar" (e qualquer exceção) não pode pular a gravação da
        recorrência aprendida nas linhas que JÁ saíram certas antes da parada
        — senão o mês seguinte não acha a recorrência e nasce um SEGUNDO
        título parcelado, com as parcelas do primeiro ainda abertas (I5).
        """
        try:
            for decisao in decisoes:
                if self.aba is not None and self.aba._parar.is_set():
                    self.aba._log("Parado a pedido; o que já foi gravado "
                                  "está no registro.")
                    return
                guia = decisao.guia
                # A decisão foi tomada minutos atrás, na fase 2. Reconferir
                # aqui é o que impede o segundo clique em "Lançar" de gravar
                # tudo de novo: a tela continua com as linhas marcadas depois
                # da rodada.
                feito = registro.ja_feito(guia.vip_id, guia.anx_id,
                                          guia.competencia)
                if feito:
                    if self.aba is not None:
                        self.aba.q.put(("guia_feita", (decisao, Resultado(
                            JA_LANCADO, tpid=str(feito.get("tpid") or ""),
                            motivo="já lançado nesta competência (" +
                                   str(feito.get("estado") or "") + ")"))))
                    continue
                if decisao.acao == CRIAR:
                    igual = casamento.titulo_igual(parcelas, guia.documento,
                                                   guia.valor, guia.vencimento)
                    if igual is not None and str(guia.documento or "").strip():
                        if self.aba is not None:
                            self.aba.q.put(("guia_feita", (decisao, Resultado(
                                JA_LANCADO,
                                tpid=str(igual.get("tradePayableId") or ""),
                                motivo="o ERP já tem título com este "
                                       "documento"))))
                        continue
                if decisao.acao == ALTERAR:
                    resultado = lancar.alterar(transporte, decisao, catalogos,
                                               pasta_backup=pasta_backup)
                else:
                    referencia = lancar.referencia_da_obra(
                        transporte, decisao.obra_id, parcelas)
                    obra = self._obra_do_erp(catalogos, decisao.obra_id)
                    resultado = lancar.criar(transporte, decisao, catalogos,
                                             id_usuario=id_usuario,
                                             referencia=referencia, obra=obra)
                registro.anotar(vip_id=decisao.guia.vip_id,
                                anx_id=decisao.guia.anx_id,
                                competencia=decisao.guia.competencia,
                                acao=decisao.acao, estado=resultado.estado,
                                tpid=resultado.tpid, motivo=resultado.motivo,
                                anexos=resultado.anexos)
                if resultado.tpid and regras is not None and decisao.tipo:
                    # O mês seguinte casa exato porque o id ficou guardado —
                    # e é isto que impede o parcelado de nascer duas vezes.
                    regras.aprender_recorrencia(decisao.tipo, decisao.guia.vip_id,
                                                resultado.tpid, decisao.obra_id)
                    if decisao.obra_id:
                        # A obra que o dono deixou passar vale como confirmada.
                        regras.aprender_obra(decisao.tipo, decisao.guia.vip_id,
                                             decisao.obra_id)
                if self.aba is not None:
                    self.aba.q.put(("guia_feita", (decisao, resultado)))
        finally:
            if regras is not None:
                regras.gravar()

    @staticmethod
    def _obra_do_erp(catalogos, obra_id: str) -> dict:
        """A obra inteira, como o ERP a devolve. O POST quer `name` e `status`
        junto do `id` — mandar só o id cria o título sem centro de custo."""
        for obra in (getattr(catalogos, "obras", {}) or {}).values():
            if str(obra.get("id")) == str(obra_id):
                return {k: obra.get(k) for k in ("id", "name", "status",
                                                 "customer", "planning", "cei")
                        if obra.get(k) is not None}
        return {"id": obra_id}
