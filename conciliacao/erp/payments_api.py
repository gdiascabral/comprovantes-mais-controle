"""Pagamentos a vencer pela API REST — a mesma lista da grade, sem a grade.

POR QUE ESTE MODULO EXISTE
--------------------------
`payments.py` le a grade de #/payable-installments raspando o MUI DataGrid:
abre Chrome com janela (o WAF recusa headless), entra pela tela de login,
aplica o filtro "Em aberto", o seletor de periodo e o tamanho de pagina, e
confere a cobertura contra o rodape. Sao 16 esperas fixas, e cada uma e um
lugar onde a tela pode mudar por baixo. A tela de contas ja quebrou a
raspagem duas vezes (`accounts.py`), e a de pagamentos e a proxima da fila.

A MESMA lista tem endpoint REST, e dois clientes ja o consomem
(`anexar/mc_api.py:listar_a_pagar` pela pagina logada e
`fontes/vigia-boletos/mc_sessao.py:listar_parcelas` por HTTP puro):

    GET {legacy}/payable-installments/paginated-result
        ?page=0&size=3000&type=ALL&dateField=PLANNED
        &startDate=AAAA-MM-DD&endDate=AAAA-MM-DD
        &onlyWork=false&costCentreType=ALL&conciliationType=ALL
        &tradePayableType=ALL&batchOperationType=NONE

Contrato verificado em producao em 04/09/2026 (varredura de 2.576 parcelas):
`size=3000` funciona (nao ha teto de 200, ao contrario do que o vigia supoe),
a paginacao e estavel, a resposta traz `content[]`, `hasNextPage`,
`numberOfElements` e `pageNumber`. Janela de 15 dias e o mais barato: ~20 s
por semana, 60-100 s por quinzena. Quem fala e `erp.Sessao` (`accessToken`
do legado + os quatro cabecalhos), e o 401 de token vencido — rotina no
legado, o token vive segundos — e relogado uma vez por ela.

MAPEAMENTO: coluna da grade -> campo da API
-------------------------------------------
Copiado de `pagamentos_dia/relatorio.py`, que le estes campos em producao
desde agosto/2026, e de `anexar/mc_api.py`.

    Vencimento              plannedDate (a janela e por `dateField=PLANNED`;
                            `dueDate` fica no `raw` para a conferencia)
    Status                  DERIVADO: `paid` -> "Pago"; senao, vencimento
                            antes de hoje -> "Vencido"; senao "Em aberto".
                            A lista nao traz status por escrito; `rules.py`
                            aceita os dois primeiros como "a pagar"
    Valor                   remainingValue — o que FALTA pagar. `value` vem
                            NULL na lista; o total ja pago esta em
                            `sumOfPaidValues` e em `paids[]`. E o que a grade
                            mostra em primeiro ("R$ 4.000,00 Pago: R$ 3.230,00"
                            -> R$ 4.000,00 e o que ainda vai sair)
    Favorecido              paidTo
    Descricao e Categoria   description + category (string, ou dict com name)
    N Doc                   documentNumber
    Condicao e Conta        tradePayableAccount.name — a grade prefixa a
                            condicao ("A Vista - CONTA") e o raspador a
                            descartava com `strip_condition_prefix`; a API
                            entrega a conta ja separada. Espaco duplo do
                            cadastro cai aqui como cai na grade. Em titulo
                            pago em PARTE a grade mostra a conta do
                            pagamento ja feito, e a API a CADASTRADA no
                            titulo — e a cadastrada que vale (dono,
                            09/09/2026: em conta pessoa fisica cada parte
                            pode sair de uma conta diferente);
                            `collect.comparar_coletas` sabe disso
    Centro de Custo         costCentreDetails[].workName (worksNames de reserva)
    Pago                    paid, sumOfPaidValues, paids[] (so a contagem)
    Anexo                   hasAnyFile

DEDUPLICACAO
------------
Pela chave `id` da parcela (installment id), NUNCA pelo texto: o ERP tem
lancamentos legitimos identicos (duas tarifas PIX de R$ 0,90 no mesmo dia e
conta), e deduplicar por texto subtrairia dinheiro do painel sem aviso. E a
mesma regra do `data-id` da grade, que e este mesmo id.

O QUE CONTINUA VALENDO DEPOIS DAQUI
-----------------------------------
`rules.py` REFILTRA por status e por data, como sempre fez: se a API ignorar
o filtro de data (ja aconteceu na lista de recebimentos, `anexar/mc_api.py`),
o painel continua certo — so mais lento. E o "agregado em aberto" que a grade
entregava pelo rodape passa a ser a SOMA desta lista (`agregado_em_aberto`):
`validate.py` continua comparando o total do dia contra ele.
"""

from __future__ import annotations

import urllib.parse
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from erp import hosts as erp_hosts

from ..errors import ErpError
from ..models import ErpPayment, Periodo
from ..rules import conta_como_a_pagar
from .api import _traduzido

import util

__all__ = [
    "JANELA_DIAS",
    "TAMANHO_PAGINA",
    "agregado_em_aberto",
    "coletar_pagamentos_api",
    "converter",
    "janelas",
    "listar_parcelas",
    "montar_url",
    "status_da_parcela",
]

#: O diagnostico do modulo. As funcoes daqui recebem um `log` PROPRIO (o
#: recado do Registro da aba) que SOMBREIA este nome; dentro delas o
#: diagnostico sai por `_diag`, o mesmo objeto com outro nome.
log = util.log(__name__)
_diag = log

#: A rota da lista, no legado. A raiz `/maiscontrole/services` ja esta em
#: `erp.hosts.LEGACY`.
ROTA = "/payable-installments/paginated-result"

#: Quinze dias por pedido: e a janela mais barata medida em producao
#: (60-100 s por quinzena). Menor que isso multiplica logins; maior, a
#: resposta cresce sem ganhar nada.
JANELA_DIAS = 15

#: `size=3000` cobre qualquer quinzena de uma vez — verificado em producao,
#: nao ha teto de 200. O laco de `hasNextPage` existe para o dia em que
#: passar disso.
TAMANHO_PAGINA = 3000

#: Trava contra `hasNextPage` preso em true. Cinquenta paginas de 3.000 sao
#: 150 mil parcelas numa quinzena: nao e um mes, e um laco.
_MAX_PAGINAS = 50

#: Os parametros que a TELA manda, copiados de `anexar/mc_api.py` e de
#: `fontes/vigia-boletos/mc_sessao.py`. `type=ALL` de proposito: pagos e a
#: pagar vem juntos e quem separa e o campo `paid` — assim a coleta consegue
#: dizer quantos ficaram de fora, em vez de sumir com eles.
_PARAMETROS_FIXOS = (
    ("type", "ALL"),
    ("dateField", "PLANNED"),
    ("onlyWork", "false"),
    ("costCentreType", "ALL"),
    ("conciliationType", "ALL"),
    ("tradePayableType", "ALL"),
    ("batchOperationType", "NONE"),
)

#: Onde a data prevista mora, na ordem de preferencia — a mesma de
#: `pagamentos_dia/relatorio.py:_CAMPOS_DATA`.
_CAMPOS_DATA = ("plannedDate", "dueDate", "dateOfPayment", "referenceDate")


# ------------------------------------------------------------------ janelas


def janelas(periodo: Periodo, dias: int = JANELA_DIAS) -> list[Periodo]:
    """Parte o periodo em janelas contiguas de no maximo `dias` dias.

    Inclusivo nas duas pontas, como o `Periodo`: um periodo de 4 dias vira
    uma janela so; 45 dias viram tres de 15. Nenhum dia fica de fora e
    nenhum entra em duas — o `startDate`/`endDate` da API tambem sao
    inclusivos.
    """
    if dias < 1:
        raise ValueError(f"janela de {dias} dia(s) nao faz sentido")
    resultado: list[Periodo] = []
    inicio = periodo.inicio
    while inicio <= periodo.fim:
        fim = min(inicio + timedelta(days=dias - 1), periodo.fim)
        resultado.append(Periodo(inicio=inicio, fim=fim))
        inicio = fim + timedelta(days=1)
    return resultado


def montar_url(base: str, janela: Periodo, pagina: int,
               tamanho: int = TAMANHO_PAGINA) -> str:
    """A URL de uma pagina de uma janela. `page` e base 0 (Spring)."""
    consulta = urllib.parse.urlencode([
        ("page", str(pagina)),
        ("size", str(tamanho)),
        *_PARAMETROS_FIXOS,
        ("startDate", f"{janela.inicio:%Y-%m-%d}"),
        ("endDate", f"{janela.fim:%Y-%m-%d}"),
    ])
    return f"{base.rstrip('/')}{ROTA}?{consulta}"


def _base_de(sessao, base: str | None) -> str:
    """O legado. `SessaoApi` sabe o do `config.yaml`; o resto usa `erp.hosts`."""
    if base:
        return base
    return getattr(sessao, "base_legado", None) or erp_hosts.LEGACY


# --------------------------------------------------------------------- lista


def listar_parcelas(sessao, periodo: Periodo, *, base: str | None = None,
                    log=print) -> list[dict]:
    """As parcelas cruas do periodo, janela a janela, pagina a pagina.

    `sessao` e qualquer coisa com `.pedir(url) -> dict` — o `SessaoApi` da
    Conciliacao ou a `erp.Sessao` por baixo dele. Deduplica pelo `id` ao
    juntar as janelas: uma parcela nao deveria aparecer em duas, mas uma
    lista que deixa isso ao acaso e uma lista que um dia soma em dobro.
    """
    raiz = _base_de(sessao, base)
    todas: list[dict] = []
    vistos: set[str] = set()
    sem_id = 0

    for janela in janelas(periodo):
        lidas = 0
        for pagina in range(_MAX_PAGINAS + 1):
            if pagina == _MAX_PAGINAS:
                raise ErpError(
                    f"a lista de parcelas de {janela.descrever()} nao terminou em "
                    f"{_MAX_PAGINAS} paginas de {TAMANHO_PAGINA} — parei para nao "
                    "devolver uma lista pela metade com cara de inteira."
                )
            with _traduzido():
                corpo = sessao.pedir(montar_url(raiz, janela, pagina)) or {}
            if not isinstance(corpo, dict):
                raise ErpError("a lista de parcelas veio num formato que nao "
                               "conheco — o contrato da API mudou.")
            lote = corpo.get("content") or []
            for item in lote:
                if not isinstance(item, dict):
                    continue
                chave = item.get("id")
                if chave is None:
                    sem_id += 1
                else:
                    chave = str(chave)
                    if chave in vistos:
                        continue
                    vistos.add(chave)
                todas.append(item)
            lidas += len(lote)
            if not corpo.get("hasNextPage") or not lote:
                break
        log(f"  {janela.descrever()}: {lidas} parcela(s) em {pagina + 1} pagina(s)")

    if sem_id:
        # Parcela sem `id` nao deduplica e nao casa com nada depois. Nao e
        # erro (a linha continua entrando no painel), mas e contrato mudando.
        log(f"  [aviso] {sem_id} parcela(s) vieram sem 'id' — o contrato da "
            "API pode ter mudado")
        _diag.warning("%d parcela(s) sem 'id' na lista de %s", sem_id,
                      periodo.descrever())
    return todas


# ---------------------------------------------------------------- conversao


def _para_data(valor) -> date | None:
    """ISO ("2026-07-27" ou com hora), dd/mm/aaaa ou epoch em ms -> date."""
    if valor in (None, ""):
        return None
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        try:
            return datetime.fromtimestamp(valor / 1000).date()
        except (OverflowError, OSError, ValueError):
            return None
    texto = str(valor).strip()
    for padrao in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(texto[:10], padrao).date()
        except ValueError:
            continue
    return None


def data_prevista(item: dict) -> date | None:
    """`plannedDate` — a data pela qual a janela foi pedida. Reservas na
    ordem do `pagamentos_dia/relatorio.py`."""
    for campo in _CAMPOS_DATA:
        lida = _para_data(item.get(campo))
        if lida is not None:
            return lida
    return None


def _decimal(valor) -> Decimal | None:
    """Numero da API -> Decimal, por `str` para nao herdar lixo binario.
    `None` continua `None`: e o `invalid_amount` de `rules.py`, nunca zero."""
    if valor is None or valor == "":
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None


def valor_em_aberto(item: dict) -> Decimal | None:
    """O que FALTA pagar desta parcela: `remainingValue`.

    `value` vem NULL na lista (medido em producao), entao nao serve nem de
    reserva. Em titulo quitado o `remainingValue` e 0.0 e o dinheiro esta em
    `sumOfPaidValues` — para o painel do DIA isso e o certo: quitado nao sai
    mais da conta.
    """
    return _decimal(item.get("remainingValue"))


def status_da_parcela(item: dict, vencimento: date | None, hoje: date) -> str:
    """O status como a grade escreve, derivado dos campos que a lista traz.

    A lista nao tem o status por escrito: tem `paid`. A grade troca "Em
    aberto" por "Vencido" quando o vencimento passa, e `rules.STATUS_A_PAGAR`
    aceita os dois — a distincao existe para o log contar os vencidos, como
    `payments.filtrar_em_aberto` fazia, e para quem abrir o snapshot ler a
    mesma palavra que le na tela.
    """
    if item.get("paid"):
        return "Pago"
    if vencimento is not None and vencimento < hoje:
        return "Vencido"
    return "Em aberto"


def _texto(valor) -> str:
    """Nome legivel de um campo que pode vir string, dict ou lista."""
    if not valor:
        return ""
    if isinstance(valor, str):
        return valor.strip()
    if isinstance(valor, list):
        return " | ".join(t for t in (_texto(v) for v in valor) if t)
    if isinstance(valor, dict):
        for chave in ("name", "description", "workName", "tradeName"):
            texto = valor.get(chave)
            if isinstance(texto, str) and texto.strip():
                return texto.strip()
    return ""


def conta_da_parcela(item: dict) -> str:
    """`tradePayableAccount.name` — a conta que a grade mostra em "Condicao
    e Conta", ja sem o prefixo da condicao.

    Espaco repetido do cadastro ("LTDA  - Conta corrente") cai, como cai na
    grade (`strip_condition_prefix`): os dois caminhos tem de entregar o
    MESMO rotulo, senao a comparacao ve duas contas onde ha uma (09/09/2026).
    """
    return " ".join(_texto(item.get("tradePayableAccount")).split())


def centro_de_custo(item: dict) -> str:
    """`costCentreDetails[].workName`, sem repetir (rateio repete o imovel)."""
    nomes = [_texto(c) for c in (item.get("costCentreDetails") or [])]
    unicos = list(dict.fromkeys(n for n in nomes if n))
    if not unicos:
        unicos = [_texto(item.get("worksNames"))] if item.get("worksNames") else []
    return " | ".join(n for n in unicos if n)


def converter(item: dict, *, hoje: date | None = None) -> ErpPayment:
    """Uma parcela crua -> o mesmo `ErpPayment` que o raspador devolve.

    O `raw` guarda os campos mapeados, com os nomes da API, para o snapshot
    contar de onde cada numero saiu — e so eles: a parcela inteira carrega o
    texto livre da conta do favorecido, que pode ser uma chave Pix, e o
    snapshot e arquivo comum no disco.
    """
    hoje = hoje or date.today()
    vencimento = data_prevista(item)
    return ErpPayment(
        due_date=vencimento,
        status=status_da_parcela(item, vencimento, hoje),
        amount=valor_em_aberto(item),
        payee=_texto(item.get("paidTo")),
        account_label=conta_da_parcela(item),
        raw={
            "fonte": "api",
            "id": None if item.get("id") is None else str(item.get("id")),
            "tradePayableId": (None if item.get("tradePayableId") is None
                               else str(item.get("tradePayableId"))),
            "plannedDate": item.get("plannedDate"),
            "dueDate": item.get("dueDate"),
            "paid": bool(item.get("paid")),
            "remainingValue": item.get("remainingValue"),
            "sumOfPaidValues": item.get("sumOfPaidValues"),
            "value": item.get("value"),
            "description": _texto(item.get("description")),
            "category": _texto(item.get("category")),
            "documentNumber": _texto(item.get("documentNumber")),
            "costCentre": centro_de_custo(item),
            "paids": len(item.get("paids") or []),
            "hasAnyFile": bool(item.get("hasAnyFile")),
        },
    )


# ------------------------------------------------------------------- coleta


def coletar_pagamentos_api(
    sessao,
    periodo: Periodo,
    *,
    log=print,
    base: str | None = None,
    hoje: date | None = None,
    somente_em_aberto: bool = True,
) -> list[ErpPayment]:
    """Os pagamentos do periodo, no modelo que `rules.py` e o painel consomem.

    `somente_em_aberto` espelha o filtro "Em aberto" que o raspador marcava
    na tela: os pagos ficam de fora e o log diz quantos — sumir com eles em
    silencio e o que este pacote nunca faz. `rules.py` refiltra por status e
    por data de qualquer jeito; isto e so para o snapshot nao carregar o mes
    inteiro de titulos quitados.
    """
    hoje = hoje or date.today()
    log(f"Lendo a lista de pagamentos (API do Mais Controle, "
        f"{periodo.descrever()})...")
    crus = listar_parcelas(sessao, periodo, base=base, log=log)
    convertidos = [converter(item, hoje=hoje) for item in crus]

    pagos = [p for p in convertidos if p.raw.get("paid")]
    abertos = [p for p in convertidos if not p.raw.get("paid")]
    vencidos = sum(1 for p in abertos if p.status == "Vencido")
    log(f"  {len(convertidos)} parcela(s) lida(s): {len(abertos)} em aberto "
        f"({vencidos} vencida(s)), {len(pagos)} ja paga(s)")
    if abertos and not vencidos:
        # Mesma pista que `payments.filtrar_em_aberto` deixava: pode nao
        # haver vencido nenhum hoje, mas um titulo atrasado fora do painel e
        # o erro mais caro daqui, e esta e a unica linha que o denuncia.
        log("  (nenhuma parcela vencida na lista — se voce esperava alguma, "
            "confira na tela do ERP)")

    sem_data = sum(1 for p in convertidos if p.due_date is None)
    if sem_data:
        log(f"  [aviso] {sem_data} parcela(s) sem data prevista legivel — "
            "somem do recorte por data")

    escolhidos = abertos if somente_em_aberto else convertidos
    datas = [p.due_date for p in escolhidos if p.due_date]
    if datas:
        fora = sum(1 for d in datas if not periodo.contem(d))
        log(f"  vencimentos de {min(datas):%d/%m} a {max(datas):%d/%m}")
        if fora:
            log(f"  atencao: {fora} linha(s) fora do periodo pedido — a API nao "
                "restringiu tudo; o recorte por data no codigo cobre isso")
    return escolhidos


def agregado_em_aberto(pagamentos: list[ErpPayment]) -> Decimal:
    """A soma do que esta a pagar na lista — o que o rodape da grade dizia.

    No caminho da tela o agregado era o "Em aberto" do MES inteiro, lido do
    cartao de totais, e `validate.py` o usa como teto do total do dia. Aqui a
    lista e a do periodo, entao o teto e a propria soma dela: continua
    barrando uma classificacao que conte a mesma linha duas vezes, mas nao e
    mais um numero independente da lista — quem protege contra linha
    duplicada na COLETA e a deduplicacao por `id`.
    """
    return sum(
        (p.amount for p in pagamentos
         if p.amount is not None and conta_como_a_pagar(p.status)),
        Decimal("0"),
    )
