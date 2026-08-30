# -*- coding: utf-8 -*-
"""
Aba "Início": os números do dia, a situação de cada rotina e o que aconteceu
por último.

Por que ela NÃO abre o navegador
--------------------------------
Esta é a primeira tela do app, e o app abre em cima de UMA sessão do ERP —
que só aceita uma por usuário. Uma tela de resumo que buscasse os pagamentos
do dia na abertura consumiria essa sessão antes de a pessoa clicar em coisa
alguma, e a aba que ela abrisse em seguida teria de refazer o login.

Então o Início não coleta nada: ele LÊ o que as rotinas já contaram. Cada
tela, ao terminar, grava um evento em `atividade.jsonl` com os números que
acabou de apurar (`widgets.registrar_atividade`). O Início soma esses eventos.

A consequência aparece na tela, e é de propósito: número que ninguém apurou
hoje aparece como "—", com a frase "rode a rotina para atualizar" embaixo.
Um zero seria pior que um traço — zero é uma afirmação sobre o dia, e o app
não tem como fazê-la sem falar com o ERP.
"""
from __future__ import annotations

import datetime as dt
import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

try:                                     # widgets compartilhados (raiz)
    import widgets
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import widgets


#: As rotinas, na ordem do menu. `ritmo` é o que decide quando a situação
#: vira aviso: uma rotina DIÁRIA que não rodou hoje é uma pendência; uma
#: mensal que não rodou hoje é só o dia 3 do mês.
ROTINAS = (
    ("sep", "Separar e Renomear", "diario"),
    ("anx", "Anexar comprovantes", "diario"),
    ("conf", "Conferência", "diario"),
    ("apt", "Aportes", "avulso"),
    ("pag", "Remessa/Retorno", "diario"),
    ("con", "Saldo de pagamentos", "diario"),
    ("rel", "Relatório Mensal", "mensal"),
    ("ext", "Extratos Sicoob", "mensal"),
    ("ctr", "Contratos", "mensal"),
    ("acs", "Acessorias", "mensal"),
)

#: Os três atalhos do canto. São as três telas que se abrem todo dia, na
#: ordem em que o dia acontece — e não as três primeiras do menu.
ATALHOS = (("pag", "🗓  Remessa do dia"),
           ("anx", "📎  Anexar comprovantes"),
           ("conf", "✅  Conferir o que foi anexado"))


def _quando(ev) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat((ev or {}).get("quando") or "")
    except (TypeError, ValueError):
        return None


def _de_hoje(ev) -> bool:
    q = _quando(ev)
    return bool(q and q.date() == dt.date.today())


def _do_mes(ev) -> bool:
    q = _quando(ev)
    hoje = dt.date.today()
    return bool(q and (q.year, q.month) == (hoje.year, hoje.month))


class CartaoKPI(widgets.Cartao):
    """Um número grande, o que ele é, e a linha que o qualifica.

    Três alturas e não duas: sem a terceira linha, "12" e "R$ 41.380,20"
    disputavam o mesmo lugar, e o cartão passava a ter dois números do mesmo
    tamanho sem dizer qual é o principal.
    """

    def __init__(self, pai, rotulo: str):
        super().__init__(pai, padding=(16, 14))
        ttk.Label(self, text=rotulo.upper(), style="Rotulo.TLabel"
                  ).pack(anchor="w")
        self.lbl_valor = ttk.Label(self, text="—", style="KPI.TLabel")
        self.lbl_valor.pack(anchor="w", pady=(4, 0))
        self.lbl_apoio = ttk.Label(self, text="", style="Tenue.TLabel",
                                   wraplength=210, justify="left")
        self.lbl_apoio.pack(anchor="w", pady=(3, 0))

    def definir(self, valor: str, apoio: str = "", marca: bool = False):
        self.lbl_valor.configure(
            text=valor, style="KPIMarca.TLabel" if marca else "KPI.TLabel")
        self.lbl_apoio.configure(text=apoio)


class InicioFrame(ttk.Frame):
    """A tela de abertura. Não tem navegador, não tem thread e não tem passo:
    ela só lê arquivo local e mostra."""

    def __init__(self, pai):
        super().__init__(pai, style="Fundo.TFrame")
        self._navegar = None
        self._build()
        self.ao_abrir()

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = widgets.PADX

        cab = widgets.Cabecalho(
            self, "Início",
            "O que já foi apurado hoje, em que pé está cada rotina e o que "
            "aconteceu por último. Esta tela não fala com o ERP: ela lê o que "
            "as rotinas contaram quando rodaram.",
            trilha="Visão geral  ›  Início")
        cab.pack(fill="x", padx=PADX, pady=(16, 12))
        widgets.Botao(cab.acoes, "Atualizar", papel="neutro",
                      command=self.ao_abrir).pack(side="right")

        # ---- os quatro números
        kpis = ttk.Frame(self, style="Fundo.TFrame")
        kpis.pack(fill="x", padx=PADX)
        self.kpis = {}
        for col, (chave, rotulo) in enumerate((
                ("hoje", "Pagamentos de hoje"),
                ("sem_remessa", "Contas sem remessa"),
                ("anexados", "Anexados no mês"),
                ("pendencias", "Pendências"))):
            cartao = CartaoKPI(kpis, rotulo)
            cartao.grid(row=0, column=col, sticky="nsew",
                        padx=(0 if col == 0 else 12, 0))
            kpis.columnconfigure(col, weight=1, uniform="kpi")
            self.kpis[chave] = cartao

        # ---- rotinas à esquerda, atividade e atalhos à direita
        meio = ttk.Frame(self, style="Fundo.TFrame")
        meio.pack(fill="both", expand=True, padx=PADX, pady=(14, 18))
        meio.columnconfigure(0, weight=1)
        meio.rowconfigure(0, weight=1)

        c_rot = widgets.Cartao(meio, "Rotinas — situação de agora")
        c_rot.grid(row=0, column=0, sticky="nsew")
        colunas = ("rotina", "quando", "resultado", "situacao")
        self.tabela = ttk.Treeview(c_rot, columns=colunas, show="headings",
                                   height=10, selectmode="browse")
        for chave, titulo, larg, ancora in (
                ("rotina", "ROTINA", 200, "w"),
                ("quando", "ÚLTIMA EXECUÇÃO", 130, "w"),
                ("resultado", "RESULTADO", 250, "w"),
                ("situacao", "SITUAÇÃO", 175, "w")):
            self.tabela.heading(chave, text=titulo)
            self.tabela.column(chave, width=larg, anchor=ancora,
                               stretch=chave == "resultado")
        widgets.estilo_tabela(self.tabela)
        self.tabela.pack(fill="both", expand=True)
        # Duplo clique abre a rotina. O botão "Abrir" do mockup viraria um
        # widget por linha dentro do Treeview, e o Treeview do Tk não aceita
        # widget dentro de célula — então quem abre é a LINHA, e o rodapé diz
        # isso em vez de deixar a pessoa descobrir.
        self.tabela.bind("<Double-Button-1>", self._abrir_selecionada)
        self.tabela.bind("<Return>", self._abrir_selecionada)
        rodape = widgets.RodapeTabela(c_rot)
        rodape.pack(fill="x", pady=(10, 0))
        rodape.definir(texto="Dois cliques na linha abrem a rotina")
        self.btn_abrir = rodape.link("Abrir a selecionada",
                                     self._abrir_selecionada)

        direita = ttk.Frame(meio, style="Fundo.TFrame", width=330)
        direita.grid(row=0, column=1, sticky="nsew", padx=(14, 0))
        direita.grid_propagate(False)

        c_atv = widgets.Cartao(direita, "Atividade recente")
        c_atv.pack(fill="both", expand=True)
        self.lista_atividade = ttk.Frame(c_atv)
        self.lista_atividade.pack(fill="both", expand=True)

        c_ata = widgets.Cartao(direita, "Atalhos")
        c_ata.pack(fill="x", pady=(14, 0))
        for chave, texto in ATALHOS:
            widgets.Botao(c_ata, texto, papel="neutro",
                          command=lambda c=chave: self._ir(c),
                          anchor="w").pack(fill="x", pady=(0, 6))

    # ------------------------------------------------------------- navegação
    def definir_navegacao(self, ir_para):
        """Quem sabe trocar de aba é a janela, e ela só existe depois desta
        tela ser construída — daí o ajuste em dois tempos."""
        self._navegar = ir_para

    def _ir(self, chave: str):
        if self._navegar:
            self._navegar(chave)

    def _abrir_selecionada(self, _ev=None):
        sel = self.tabela.selection()
        if sel:
            self._ir(sel[0])
        return "break"

    # ---------------------------------------------------------------- dados
    def ao_abrir(self):
        """Relê o arquivo de atividade e redesenha. Chamada pela janela toda
        vez que esta aba volta à frente — o que as outras telas fizeram muda
        enquanto esta fica escondida."""
        try:
            eventos = widgets.atividades(widgets.MAX_ATIVIDADE)
        except Exception:                                     # noqa: BLE001
            eventos = []
        ultimos, numeros = {}, {}
        for ev in eventos:                # já vêm do mais novo para o mais velho
            ultimos.setdefault(ev.get("aba"), ev)
            # Os NÚMEROS de uma aba se juntam; o EVENTO não. Uma rotina de
            # três passos escreve três eventos, e cada um sabe uma coisa
            # diferente: buscar conta os lançamentos, gerar a remessa conta as
            # contas que ficaram sem arquivo. Olhando só o último, "Pagamentos
            # de hoje" ficava em "—" justamente nos dias em que o dia inteiro
            # tinha rodado.
            #
            # `setdefault` por CHAVE, varrendo do mais novo para o mais velho:
            # o número mais recente ganha, e os que só o passo anterior sabe
            # continuam valendo.
            alvo = numeros.setdefault(ev.get("aba"), {})
            for chave, valor in (ev.get("numeros") or {}).items():
                alvo.setdefault(chave, valor)
                # De onde veio o número decide se ele conta como "de hoje".
                alvo.setdefault("_quando_" + chave, ev.get("quando"))
        self._pintar_kpis(numeros)
        self._pintar_rotinas(ultimos)
        self._pintar_atividade(eventos[:9])

    def _pintar_kpis(self, juntos: dict):
        def numeros(aba, chave, so_hoje=True, so_mes=False):
            """O valor de `chave` para `aba`, se ele for recente o bastante.

            A janela é por NÚMERO, e não pela aba inteira: no mesmo dicionário
            convivem o "87 lançamentos" de hoje e o "38 anexados" da semana
            passada, e cada KPI pergunta o que faz sentido para ele."""
            dados = juntos.get(aba) or {}
            if chave not in dados:
                return None
            quando = {"quando": dados.get("_quando_" + chave)}
            if so_hoje and not _de_hoje(quando):
                return None
            if so_mes and not _do_mes(quando):
                return None
            return dados[chave]

        sem_dado = "rode a rotina para atualizar"

        lancamentos = numeros("pag", "lancamentos")
        if lancamentos is not None:
            self.kpis["hoje"].definir(
                str(lancamentos),
                widgets.brl(numeros("pag", "total") or 0) + " a pagar",
                marca=True)
        else:
            self.kpis["hoje"].definir("—", sem_dado)

        # "Contas sem remessa" só existe depois de a remessa do dia ser
        # montada: é a diferença entre as contas que têm pagamento hoje e as
        # que viraram arquivo. Antes disso não há resposta — e inventar zero
        # aqui diria "está tudo enviado" num dia em que nada foi.
        faltam = numeros("pag", "contas_sem_remessa")
        if faltam is not None:
            self.kpis["sem_remessa"].definir(
                str(int(faltam)),
                "todas as contas do dia foram para o banco" if not faltam
                else "ainda não viraram arquivo de remessa")
        else:
            self.kpis["sem_remessa"].definir("—", sem_dado)

        anexados = numeros("anx", "anexados", so_hoje=False, so_mes=True)
        if anexados is not None:
            pagos = int(numeros("anx", "pagos", so_hoje=False, so_mes=True) or 0)
            pct = f"{int(anexados) * 100 // pagos}% dos pagos" if pagos else ""
            self.kpis["anexados"].definir(str(int(anexados)), pct)
        else:
            self.kpis["anexados"].definir("—", sem_dado)

        # Pendências junta as duas coisas que exigem alguém: o que ficou em
        # dúvida na conferência e o que foi pago sem comprovante anexado.
        duvidas = numeros("conf", "duvidas", so_hoje=False, so_mes=True)
        sem_anexo = numeros("pag", "sem_anexo")
        if duvidas is None and sem_anexo is None:
            self.kpis["pendencias"].definir("—", sem_dado)
        else:
            total = int(duvidas or 0) + int(sem_anexo or 0)
            partes = []
            if duvidas is not None:
                partes.append(f"{int(duvidas)} em dúvida")
            if sem_anexo is not None:
                partes.append(f"{int(sem_anexo)} sem anexo")
            self.kpis["pendencias"].definir(str(total), " · ".join(partes))

    def _situacao(self, ev, ritmo: str) -> tuple[str, str]:
        """(o que dizer, qual cor). A cor sai do RITMO da rotina: a mensal que
        não rodou hoje está em dia; a diária, não."""
        if ev is None:
            return "nunca rodou", "info"
        resultado = (ev.get("resultado") or "ok").strip().lower()
        # "atencao" NÃO é falha: é a rotina que terminou e achou coisa para
        # alguém olhar. Tratá-la como erro apagava a diferença entre "não
        # rodou" e "rodou e encontrou três pendências" — que é justamente a
        # informação pela qual se abre esta tela.
        if resultado in ("atencao", "aviso", "parcial"):
            return "rodou com avisos", "atencao"
        if resultado not in ("ok", ""):
            return "falhou", "erro"
        if ritmo == "diario":
            return ("feita hoje", "ok") if _de_hoje(ev) else ("não rodou hoje",
                                                              "atencao")
        if ritmo == "mensal":
            return ("feita neste mês", "ok") if _do_mes(ev) else (
                "não rodou neste mês", "atencao")
        return ("feita hoje", "ok") if _de_hoje(ev) else ("em dia", "info")

    def _pintar_rotinas(self, ultimos: dict):
        self.tabela.delete(*self.tabela.get_children())
        for i, (chave, nome, ritmo) in enumerate(ROTINAS):
            ev = ultimos.get(chave)
            texto, estado = self._situacao(ev, ritmo)
            quando = widgets.quando_humano((ev or {}).get("quando") or "")
            resultado = ((ev or {}).get("detalhe")
                         or (ev or {}).get("evento") or "—")
            self.tabela.insert(
                "", "end", iid=chave,
                values=(nome, quando, resultado[:64],
                        f"{widgets.MARCAS_ESTADO[estado]}  {texto}"),
                tags=widgets.linha_zebrada(i, estado))

    def _pintar_atividade(self, eventos):
        for w in self.lista_atividade.winfo_children():
            w.destroy()
        if not eventos:
            ttk.Label(self.lista_atividade, style="Tenue.TLabel",
                      wraplength=280, justify="left",
                      text="Ainda não há nada anotado. Cada rotina escreve "
                           "aqui quando termina."
                      ).pack(anchor="w")
            return
        nomes = {c: n for c, n, _ in ROTINAS}
        for ev in eventos:
            estado = widgets.estado_de(ev.get("resultado") or "ok")
            linha = ttk.Frame(self.lista_atividade)
            linha.pack(fill="x", pady=(0, 9))
            topo = ttk.Frame(linha)
            topo.pack(fill="x")
            ttk.Label(topo, text=widgets.MARCAS_ESTADO[estado],
                      style={"ok": "Ok", "atencao": "Atencao",
                             "erro": "Erro"}.get(estado, "Tenue") + ".TLabel"
                      ).pack(side="left", padx=(0, 6))
            ttk.Label(topo, text=nomes.get(ev.get("aba"), ev.get("aba") or "—"),
                      style="Forte.TLabel").pack(side="left")
            ttk.Label(topo, text=widgets.quando_humano(ev.get("quando") or ""),
                      style="Mini.TLabel").pack(side="right")
            texto = ev.get("detalhe") or ev.get("evento") or ""
            if texto:
                ttk.Label(linha, text=texto, style="Apoio.TLabel",
                          wraplength=280, justify="left"
                          ).pack(anchor="w", padx=(20, 0))

    # ------------------------------------------------------------------ tema
    def aplicar_cores(self, escuro: bool):
        """Os cartões e os botões se repintam sozinhos (`_repintaveis`); a
        tabela precisa das tags de novo, porque `tag_configure` guarda a COR e
        não o nome do estado."""
        try:
            widgets.estilo_tabela(self.tabela)
        except tk.TclError:
            pass
