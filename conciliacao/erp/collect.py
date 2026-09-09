"""Coleta completa: ERP -> Snapshot em disco.

DOIS CAMINHOS, UMA CHAVE
------------------------
Desde 08/09/2026 a coleta inteira — saldos E pagamentos — vai pela API REST,
sem abrir navegador nenhum (`coletar_pela_api`). A raspagem da grade de
pagamentos continua existindo, intacta, como plano B (`coletar_pela_tela` e
`coletar_com_pagina`), atras da chave `pagamentos_via_api: false` no
`config.yaml`. Quem escolhe e `coletar()`.

Ate 10/08/2026 os dois vinham da tela. A leitura de saldos migrou para a API
quando o redesenho da tela de contas quebrou a raspagem pela segunda vez
(`accounts.py`). A grade de pagamentos migrou em 08/09/2026, pela lista
`payable-installments/paginated-result` que a propria tela consome
(`payments_api.py`, com a tabela coluna -> campo no cabecalho).

O que muda entre os dois caminhos, alem do navegador:

  - o "agregado em aberto" que `validate.py` usa como teto do total do dia
    vinha do rodape da grade (o MES inteiro); pela API e a SOMA da propria
    lista do periodo (`payments_api.agregado_em_aberto`);
  - um login so: a mesma `SessaoApi` le os saldos (`prod-erp-api`) e as
    parcelas (`legacy-api`), com o token escolhido pelo host. O login por
    HTTP continua derrubando a sessao do navegador do app, se houver um
    aberto — quem usar outra aba passa pelo `garantir_sessao`, que refaz.

Antes de confiar no caminho novo com dinheiro, `conciliacao comparar-coleta`
roda os dois para o mesmo periodo e imprime, por conta, o total e a
quantidade de cada um (`comparar_coletas`).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from ..config import Config
from ..errors import ErpError
from ..models import ErpPayment, Periodo, Snapshot, sugerir_periodo
from ..parsing import format_brl
from ..rules import conta_como_a_pagar
from .accounts import coletar_contas
from .api import SessaoApi
from .auth import entrar, garantir_login
from .browser import abrir_erp, aguardar_sistema, ir_para, salvar_screenshot
from .payments import coletar_pagamentos
from .payments_api import agregado_em_aberto, coletar_pagamentos_api

#: Linhas da grade de pagamentos (MUI DataGrid).
SEL_LINHAS_PAGAMENTOS = '[role="row"]'


def _periodo_de(data_referencia: date | None, periodo: Periodo | None) -> Periodo:
    if periodo is not None:
        return periodo
    if data_referencia:
        return Periodo.de_um_dia(data_referencia)
    return sugerir_periodo(date.today())


def usa_api(config) -> bool:
    """A chave, com o padrao True para quem nao a tem (config de teste,
    `_ConfigMinimo`)."""
    return bool(getattr(config, "pagamentos_via_api", True))


def coletar(
    config: Config,
    *,
    data_referencia: date | None = None,
    periodo: Periodo | None = None,
    visivel: bool = True,
    log=print,
) -> Snapshot:
    """Le saldos e pagamentos e devolve o snapshot do periodo.

    Pela API quando `config.pagamentos_via_api` (o padrao); pela tela, com
    navegador proprio, quando a chave esta desligada. `visivel` so importa no
    segundo caso — e ali tem de ser True, porque o WAF recusa headless.
    """
    periodo = _periodo_de(data_referencia, periodo)
    if usa_api(config):
        return coletar_pela_api(config, periodo=periodo, log=log)
    return coletar_pela_tela(config, periodo=periodo, visivel=visivel, log=log)


# ------------------------------------------------------------ pela API (padrao)


def coletar_pela_api(config: Config, *, periodo: Periodo, log=print) -> Snapshot:
    """Saldos e pagamentos pela API REST. Nenhum navegador.

    Um login, duas listas. A ordem — saldos primeiro — e a de sempre: se a
    credencial estiver errada, o erro aparece na chamada mais barata.
    """
    referencia = periodo.fim
    log(f"Periodo: {periodo.descrever()}")

    sessao = SessaoApi.logar(config, log=log)

    log("Lendo saldos das contas (API do Mais Controle)...")
    contas = sessao.contas(ativas=True)
    if not contas:
        raise ErpError("a API nao devolveu nenhuma conta bancaria.")
    log(f"  {len(contas)} conta(s) lida(s)")

    pagamentos = coletar_pagamentos_api(sessao, periodo, log=log)
    agregado = agregado_em_aberto(pagamentos)
    log(f"  {len(pagamentos)} linha(s) a pagar no periodo, somando "
        f"{format_brl(agregado)}")

    return _montar_snapshot(referencia, contas, pagamentos, agregado, periodo)


# --------------------------------------------------- pela tela (plano B)


def coletar_pela_tela(
    config: Config,
    *,
    periodo: Periodo,
    visivel: bool = True,
    log=print,
) -> Snapshot:
    """A coleta de antes de 08/09/2026: saldos pela API, grade pelo navegador.

    Abre um Chrome proprio (`abrir_erp`), entra pela tela de login e raspa a
    grade (`payments.py`). E o plano B: fica atras de
    `pagamentos_via_api: false` e serve de referencia para o
    `comparar-coleta`.
    """
    referencia = periodo.fim
    log(f"Periodo: {periodo.descrever()}")

    # Saldos primeiro, de proposito: sao rapidos e nao abrem janela. Se a
    # credencial estiver errada, o erro aparece aqui — antes de o navegador
    # subir e o usuario ficar olhando para uma janela que vai morrer.
    log("Lendo saldos das contas (API do Mais Controle)...")
    contas = coletar_contas(config, log=log)
    log(f"  {len(contas)} conta(s) lida(s)")

    with abrir_erp(config, visivel=visivel) as pagina:
        try:
            # Entrar ANTES de pedir tela interna: navegar direto para uma rota
            # sem sessao faz o ERP mostrar "sem permissao".
            log("Entrando no Mais Controle...")
            entrar(pagina, config, visivel=visivel, log=log)

            log("Abrindo pagamentos...")
            ir_para(pagina, config, config.erp["rota_pagamentos"])
            garantir_login(
                pagina,
                config,
                seletor_sucesso=SEL_LINHAS_PAGAMENTOS,
                visivel=visivel,
                log=log,
            )
            pagamentos, agregado = _ler_pagamentos(pagina, config, periodo, log=log)

        except Exception:
            caminho = salvar_screenshot(pagina, config, f"falha-{referencia:%Y-%m-%d}")
            log(f"Screenshot do erro: {caminho}")
            raise

    return _montar_snapshot(referencia, contas, pagamentos, agregado, periodo)


def coletar_com_pagina(
    pagina,
    config: Config,
    *,
    data_referencia: date | None = None,
    periodo: Periodo | None = None,
    revalidar_sessao=None,
    log=print,
) -> Snapshot:
    """Mesma coleta pela tela, sobre uma pagina JA LOGADA — a do app.

    E o caminho da aba quando `pagamentos_via_api` esta desligada. O ERP
    aceita uma sessao por usuario: se a aba abrisse o proprio navegador,
    derrubaria a sessao do Anexar, e vice-versa. Aqui a sessao e emprestada.

    ORDEM OBRIGATORIA: pagamentos (navegador) primeiro, saldos (API) por
    ultimo. Guardada por `tests/test_ordem_da_coleta.py`.

    A leitura de saldos faz `POST /users/login` com o MESMO usuario. Como o
    ERP admite uma sessao por usuario, esse login DERRUBA a sessao do
    navegador, que ate ali estava boa. O sintoma engana: o app diz "Login OK",
    le as 36 contas, e so entao a grade volta vazia — recarregando, aparece
    "Insira suas credenciais para entrar novamente no sistema".

    Ate 18/08/2026 a ordem era a inversa, com um `revalidar_sessao` no meio
    para consertar o estrago. Funcionava e custava um LOGIN INTEIRO por
    rodada, visivel no Registro como "entra, sai, entra de novo" — foi o que o
    dono estranhou. Lendo a grade antes, a sessao emprestada e usada enquanto
    ainda esta boa e a API roda quando ninguem mais precisa do Chrome.

    A sessao do navegador cai depois disso, e isso e inofensivo: quem for usar
    outra aba passa pelo `garantir_sessao`, que refaz o login sozinho. O
    `revalidar_sessao` continua sendo chamado no fim, mas agora como cortesia
    para a proxima aba — e por isso falhar ali nao derruba uma coleta que ja
    terminou.
    """
    periodo = _periodo_de(data_referencia, periodo)
    referencia = periodo.fim
    log(f"Periodo: {periodo.descrever()}")

    # NAVEGADOR PRIMEIRO, API DEPOIS. A ordem inversa custava um login inteiro
    # a cada rodada: o ERP aceita UMA sessao por usuario, a API de saldos abre
    # a dela e derruba a do navegador, e o app tinha de entrar de novo para
    # ler a grade. Era o "entra, sai, entra" que aparecia no Registro.
    #
    # Invertendo, o navegador usa a sessao que ja veio pronta de fora e a API
    # roda por ultimo, quando ninguem mais precisa do Chrome. A sessao dele
    # cai depois disso, e isso e inofensivo: quem for usar outra aba passa
    # pelo `garantir_sessao`, que refaz o login sozinho.
    try:
        log("Abrindo pagamentos...")
        ir_para(pagina, config, config.erp["rota_pagamentos"])
        pagamentos, agregado = _ler_pagamentos(pagina, config, periodo, log=log)
    except Exception:
        caminho = salvar_screenshot(pagina, config, f"falha-{referencia:%Y-%m-%d}")
        log(f"Screenshot do erro: {caminho}")
        raise

    log("Lendo saldos das contas (API do Mais Controle)...")
    contas = coletar_contas(config, log=log)
    log(f"  {len(contas)} conta(s) lida(s)")
    if revalidar_sessao is not None:
        # A API acabou de derrubar a sessao do navegador. Refazer aqui e
        # cortesia para a PROXIMA aba, nao necessidade desta coleta -- por
        # isso falhar aqui nao pode derrubar um trabalho que ja terminou.
        try:
            revalidar_sessao()
        except Exception as e:                                    # noqa: BLE001
            log(f"  (o login do navegador nao foi refeito: {e})")

    return _montar_snapshot(referencia, contas, pagamentos, agregado, periodo)


def _ler_pagamentos(pagina, config: Config, periodo: Periodo, *, log=print):
    aguardar_sistema(pagina, SEL_LINHAS_PAGAMENTOS)
    log("Lendo a grade de pagamentos (todas as paginas do mes)...")
    pagamentos, agregado = coletar_pagamentos(pagina, config, periodo, log=log)
    log(f"  {len(pagamentos)} linha(s) lida(s) no mes")
    return pagamentos, agregado


def _montar_snapshot(referencia, contas, pagamentos, agregado, periodo) -> Snapshot:
    return Snapshot(
        reference_date=referencia,
        collected_at=datetime.now().isoformat(timespec="seconds"),
        accounts=contas,
        payments=pagamentos,
        page_aggregate_open=agregado,
        periodo=periodo,
    )


def testar_login(config: Config, log=print) -> bool:
    """Confere os acessos que a coleta usa, sem coletar nada.

    Serve para validar a senha recem-guardada: se a API responde (e, no plano
    B, a grade de pagamentos carrega), a conciliacao do dia vai passar. Com a
    chave ligada nao abre navegador: a segunda prova e a propria lista de
    parcelas, num periodo de um dia.
    """
    log("1/2 — API de saldos...")
    if usa_api(config):
        sessao = SessaoApi.logar(config, log=log)
        contas = sessao.contas(ativas=True)
        log(f"  OK: {len(contas)} conta(s) ativa(s) com saldo.")

        log("2/2 — API de pagamentos (a lista de hoje)...")
        hoje = date.today()
        linhas = coletar_pagamentos_api(sessao, Periodo.de_um_dia(hoje), log=log,
                                        somente_em_aberto=False)
        log(f"  OK: a lista de pagamentos respondeu com {len(linhas)} linha(s) "
            f"para {hoje:%d/%m/%Y}.")
        return True

    contas = coletar_contas(config, log=log)
    log(f"  OK: {len(contas)} conta(s) ativa(s) com saldo.")

    log("2/2 — navegador (grade de pagamentos)...")
    with abrir_erp(config, visivel=True) as pagina:
        entrar(pagina, config, visivel=True, log=log)
        ir_para(pagina, config, config.erp["rota_pagamentos"])
        aguardar_sistema(pagina, SEL_LINHAS_PAGAMENTOS)
        linhas = pagina.locator(SEL_LINHAS_PAGAMENTOS).count()
        log(f"  OK: a grade de pagamentos carregou com {linhas} linha(s).")
    return True


# ------------------------------------------------ a tela contra a API


@dataclass(frozen=True)
class LinhaComparacao:
    """Uma conta: quantidade e total em cada caminho."""

    conta: str
    qtd_tela: int
    total_tela: Decimal
    qtd_api: int
    total_api: Decimal

    @property
    def diferenca(self) -> Decimal:
        return self.total_api - self.total_tela

    @property
    def bate(self) -> bool:
        return self.qtd_tela == self.qtd_api and self.total_tela == self.total_api


@dataclass(frozen=True)
class ParcialEmOutraConta:
    """Titulo pago em parte cuja grade mostra outra conta que a API."""

    id: str
    conta_tela: str
    conta_api: str
    valor: Decimal | None


@dataclass
class Comparacao:
    """O resultado de `comparar_coletas`, e o texto que o dono vai ler."""

    periodo: Periodo
    linhas: list[LinhaComparacao] = field(default_factory=list)
    #: ids (o `data-id` da grade, o `id` da parcela) presentes so de um lado.
    so_na_tela: list[str] = field(default_factory=list)
    so_na_api: list[str] = field(default_factory=list)
    agregado_tela: Decimal | None = None
    agregado_api: Decimal | None = None
    #: Linhas da API em que `plannedDate` e `dueDate` diferem — e o que
    #: decide se a coluna "Vencimento" da grade e a data prevista ou a de
    #: vencimento, e so a comparacao ao vivo responde.
    datas_divergentes: int = 0
    #: Titulos pagos em PARTE em que a grade mostra a conta do pagamento ja
    #: feito e a API a conta cadastrada no titulo. Vale a cadastrada, entao
    #: a linha da tela e somada na conta da API e o caso fica listado aqui,
    #: em vez de acusar diferenca (ver `_conta_cadastrada_nos_parciais`).
    parciais_em_outra_conta: list[ParcialEmOutraConta] = field(default_factory=list)

    @property
    def qtd_tela(self) -> int:
        return sum(linha.qtd_tela for linha in self.linhas)

    @property
    def qtd_api(self) -> int:
        return sum(linha.qtd_api for linha in self.linhas)

    @property
    def total_tela(self) -> Decimal:
        return sum((linha.total_tela for linha in self.linhas), Decimal("0"))

    @property
    def total_api(self) -> Decimal:
        return sum((linha.total_api for linha in self.linhas), Decimal("0"))

    @property
    def bate(self) -> bool:
        return all(linha.bate for linha in self.linhas)

    def relatorio(self) -> str:
        largura = max([len("CONTA")] + [len(linha.conta) for linha in self.linhas])
        cab = (f"{'CONTA':<{largura}}  {'TELA':>16}  {'QTD':>4}  "
               f"{'API':>16}  {'QTD':>4}  {'DIFERENCA':>16}")
        saida = [f"Periodo: {self.periodo.descrever()}", "", cab, "-" * len(cab)]
        # As que diferem primeiro: sao as que o dono vai olhar.
        for linha in sorted(self.linhas, key=lambda x: (x.bate, x.conta)):
            marca = "" if linha.bate else "  <-- difere"
            saida.append(
                f"{linha.conta:<{largura}}  {format_brl(linha.total_tela):>16}  "
                f"{linha.qtd_tela:>4}  {format_brl(linha.total_api):>16}  "
                f"{linha.qtd_api:>4}  {format_brl(linha.diferenca):>16}{marca}"
            )
        saida.append("-" * len(cab))
        saida.append(
            f"{'TOTAL':<{largura}}  {format_brl(self.total_tela):>16}  "
            f"{self.qtd_tela:>4}  {format_brl(self.total_api):>16}  "
            f"{self.qtd_api:>4}  {format_brl(self.total_api - self.total_tela):>16}"
        )
        saida.append("")
        saida.append(f"Agregado 'Em aberto' — tela (rodape do mes): "
                     f"{format_brl(self.agregado_tela)}; "
                     f"API (soma do periodo): {format_brl(self.agregado_api)}")
        if self.so_na_tela or self.so_na_api:
            saida.append(f"Ids so na tela: {len(self.so_na_tela)} "
                         f"{self.so_na_tela[:8]}")
            saida.append(f"Ids so na API:  {len(self.so_na_api)} "
                         f"{self.so_na_api[:8]}")
        if self.datas_divergentes:
            saida.append(f"{self.datas_divergentes} linha(s) da API com plannedDate "
                         "diferente de dueDate — se a tela e a API divergirem, "
                         "comece por elas")
        if self.parciais_em_outra_conta:
            saida.append(
                f"{len(self.parciais_em_outra_conta)} titulo(s) pago(s) em parte "
                "somado(s) na conta CADASTRADA (a da API): a grade mostra a "
                "conta do pagamento ja feito, e e a cadastrada que vale")
            for parcial in self.parciais_em_outra_conta[:8]:
                saida.append(f"  {format_brl(parcial.valor)}  tela: {parcial.conta_tela}"
                             f"  ->  API: {parcial.conta_api}  (id {parcial.id})")
        saida.append("")
        saida.append("RESULTADO: os dois caminhos BATEM." if self.bate
                     else "RESULTADO: os dois caminhos DIFEREM — nao ligue a "
                          "chave sem entender por que.")
        return "\n".join(saida)


def _a_pagar_no_periodo(snapshot: Snapshot) -> list[ErpPayment]:
    """O mesmo recorte que `rules.classify_payments` faz: data e status."""
    intervalo = snapshot.intervalo
    return [p for p in snapshot.payments
            if intervalo.contem(p.due_date) and conta_como_a_pagar(p.status)]


def _pago_em_parte(p: ErpPayment) -> bool:
    """`sumOfPaidValues` > 0 na parcela da API: uma parte ja saiu."""
    try:
        return Decimal(str(p.raw.get("sumOfPaidValues") or 0)) > 0
    except (InvalidOperation, ValueError):
        return False


def _conta_cadastrada_nos_parciais(
    da_tela: list[ErpPayment], da_api: list[ErpPayment],
) -> tuple[list[ErpPayment], list[ParcialEmOutraConta]]:
    """Titulo pago em parte: a grade mostra a conta do pagamento ja feito, a
    API a conta cadastrada no titulo, e e a cadastrada que vale (dono,
    09/09/2026: em conta pessoa fisica cada parte pode sair de uma conta
    diferente, e o que falta pagar ainda nao saiu de nenhuma). A linha da
    tela passa a somar na conta da API, e o caso fica listado no relatorio.

    So o titulo presente nos DOIS lados, com o mesmo id, pago em parte e com
    conta diferente: conta diferente SEM pagamento parcial continua sendo
    diferenca de verdade.
    """
    da_api_por_id = {str(p.raw.get("id")): p for p in da_api if p.raw.get("id")}
    ajustadas: list[ErpPayment] = []
    parciais: list[ParcialEmOutraConta] = []
    for p in da_tela:
        par = da_api_por_id.get(str(p.raw.get("id"))) if p.raw.get("id") else None
        if (par is not None and par.account_label
                and p.account_label != par.account_label and _pago_em_parte(par)):
            parciais.append(ParcialEmOutraConta(
                id=str(p.raw["id"]), conta_tela=p.account_label,
                conta_api=par.account_label, valor=p.amount))
            p = replace(p, account_label=par.account_label)
        ajustadas.append(p)
    return ajustadas, parciais


def comparar_coletas(tela: Snapshot, api: Snapshot) -> Comparacao:
    """Poe lado a lado o que a grade leu e o que a API leu, por conta.

    Os dois snapshots passam pelo MESMO recorte de `rules.py` antes de somar
    (vencimento no periodo, status a pagar), porque a grade vem com o filtro
    da tela e a API vem com `type=ALL`: comparar as listas cruas acusaria
    diferenca onde so ha filtro. Valor `None` (ilegivel) conta na quantidade
    e nao no total, dos dois lados.
    """
    periodo = api.intervalo
    contas: dict[str, list] = {}

    def somar(pagamentos: list[ErpPayment], indice: int):
        for p in pagamentos:
            acumulado = contas.setdefault(p.account_label or "(sem conta)",
                                          [0, Decimal("0"), 0, Decimal("0")])
            acumulado[indice] += 1
            if p.amount is not None:
                acumulado[indice + 1] += p.amount

    da_tela = _a_pagar_no_periodo(tela)
    da_api = _a_pagar_no_periodo(api)
    da_tela, parciais = _conta_cadastrada_nos_parciais(da_tela, da_api)
    somar(da_tela, 0)
    somar(da_api, 2)

    linhas = [LinhaComparacao(conta, q1, t1, q2, t2)
              for conta, (q1, t1, q2, t2) in contas.items()]

    ids_tela = {str(p.raw.get("id")) for p in da_tela if p.raw.get("id")}
    ids_api = {str(p.raw.get("id")) for p in da_api if p.raw.get("id")}
    divergentes = sum(
        1 for p in da_api
        if p.raw.get("plannedDate") and p.raw.get("dueDate")
        and str(p.raw["plannedDate"])[:10] != str(p.raw["dueDate"])[:10]
    )
    return Comparacao(
        periodo=periodo,
        linhas=linhas,
        so_na_tela=sorted(ids_tela - ids_api),
        so_na_api=sorted(ids_api - ids_tela),
        agregado_tela=tela.page_aggregate_open,
        agregado_api=api.page_aggregate_open,
        datas_divergentes=divergentes,
        parciais_em_outra_conta=parciais,
    )
