"""Regras de negocio do painel. Zero dependencia de browser ou de Excel.

Decisoes travadas com o Gustavo:
- pagamento entra se vencimento == data de referencia E status "Em aberto";
- exclui lancamento de EXATAMENTE R$ 1,00 (recorrentes Sanesc/Equatorial);
- NAO exclui reembolso (nao ha regra por favorecido — reembolso e pagamento normal);
- conta fora do painel: ignorada na planilha, registrada em log;
- regra do zero: E == 0 -> E, I e J recebem 0; E > 0 -> J fica vazio;
- linhas sem conta no ERP (28, 30, 31): D, E, I e J todos VAZIOS.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

from .mapping import AccountMapping
from .models import ErpAccount, ErpPayment, ModelRow, Periodo, RowFill
from .parsing import normalize_name

#: Lancamentos de exatamente este valor sao recorrencias tecnicas, nao pagamentos.
EXCLUDED_EXACT_AMOUNT = Decimal("1.00")

#: Status que contam como "a pagar".
#:
#: "Vencido" e obrigatorio aqui: o Mais Controle troca "Em aberto" por "Vencido"
#: assim que o vencimento passa. Sem isso, um titulo de sabado ficaria fora do
#: painel de segunda-feira.
STATUS_A_PAGAR = ("EM ABERTO", "VENCIDO")

#: Status conhecidos que ficam fora de proposito.
STATUS_FORA = ("PAGO",)


def _casa_status(status: str | None, alvos) -> bool:
    normalizado = normalize_name(status)
    return any(normalize_name(alvo) in normalizado for alvo in alvos)


def conta_como_a_pagar(status: str | None, alvos=STATUS_A_PAGAR) -> bool:
    return _casa_status(status, alvos)


def is_open_status(status: str | None) -> bool:
    """Mantido por compatibilidade; prefira `conta_como_a_pagar`."""
    return conta_como_a_pagar(status)


@dataclass
class Classification:
    """Resultado da triagem dos pagamentos do dia."""

    #: Pagamentos que entram no painel, com a linha resolvida.
    eligible: list[tuple[ErpPayment, ModelRow]] = field(default_factory=list)
    #: Excluidos pela regra do R$ 1,00.
    excluded_one_real: list[ErpPayment] = field(default_factory=list)
    #: Conta reconhecida como fora do painel (lista `ignored_erp_accounts`).
    ignored_by_config: list[ErpPayment] = field(default_factory=list)
    #: Conta que nao casou com nenhuma linha nem com a lista de ignoradas.
    #: Isto e um alerta: pode ser conta nova que deveria estar no painel.
    unmapped: list[ErpPayment] = field(default_factory=list)
    #: Linha da grade sem valor legivel — sempre um alerta.
    invalid_amount: list[ErpPayment] = field(default_factory=list)
    #: Status que nao esta nem na lista de "a pagar" nem na de ignorados.
    #: Pode ser um pagamento que deveria entrar: nunca descartar em silencio.
    status_desconhecido: list[ErpPayment] = field(default_factory=list)
    #: Descartados por data/status (contagem apenas, nao interessam individualmente).
    skipped_other_date: int = 0
    skipped_not_open: int = 0

    @property
    def total_eligible(self) -> Decimal:
        return sum((p.amount for p, _ in self.eligible), Decimal("0"))

    @property
    def total_out_of_panel(self) -> Decimal:
        """Soma do que vence hoje mas fica fora do painel — vai para o log."""
        out = self.ignored_by_config + self.unmapped
        return sum((p.amount for p in out if p.amount is not None), Decimal("0"))


def classify_payments(
    payments: list[ErpPayment],
    mapping: AccountMapping,
    periodo: Periodo | date,
    *,
    status_a_pagar=STATUS_A_PAGAR,
    status_fora=STATUS_FORA,
) -> Classification:
    """Triagem completa: data, status, exclusoes e resolucao de conta.

    `periodo` aceita um intervalo ou uma data solta (tratada como um dia). O
    intervalo existe para o caso da segunda-feira, quando os vencimentos de
    sabado e domingo continuam em aberto e precisam ser somados.
    """
    intervalo = Periodo.normalizar(periodo)
    result = Classification()

    for payment in payments:
        if not intervalo.contem(payment.due_date):
            result.skipped_other_date += 1
            continue
        if not conta_como_a_pagar(payment.status, status_a_pagar):
            # Status conhecido e fora de proposito (ex.: "Pago") apenas conta;
            # status desconhecido vira alerta, porque pode ser algo a pagar.
            if _casa_status(payment.status, status_fora):
                result.skipped_not_open += 1
            else:
                result.status_desconhecido.append(payment)
            continue
        if payment.amount is None:
            result.invalid_amount.append(payment)
            continue
        if payment.amount == EXCLUDED_EXACT_AMOUNT:
            result.excluded_one_real.append(payment)
            continue

        # Ignoradas primeiro, pelo mesmo motivo explicado em `resolve_balances`:
        # o match por nome aceita continencia e uma conta ignorada pode conter
        # o nome de uma conta do painel, levando o pagamento para a linha errada.
        if mapping.is_ignored(payment.account_label):
            result.ignored_by_config.append(payment)
            continue

        row = mapping.resolve_label(payment.account_label)
        if row is not None and row.exists_in_erp:
            result.eligible.append((payment, row))
        else:
            result.unmapped.append(payment)

    return result


@dataclass
class BalanceResolution:
    """Resultado do casamento entre as contas lidas no ERP e as linhas do painel."""

    #: linha -> saldo. Valor None significa conta encontrada com saldo ilegivel.
    balances: dict[int, Decimal | None] = field(default_factory=dict)
    #: Linhas vivas do painel que nao apareceram no ERP.
    linhas_nao_encontradas: list[ModelRow] = field(default_factory=list)
    #: Contas do ERP fora do painel e fora da lista de ignoradas — possiveis
    #: contas novas que talvez devessem entrar no modelo.
    contas_desconhecidas: list[ErpAccount] = field(default_factory=list)


def resolve_balances(accounts: list[ErpAccount], mapping: AccountMapping) -> BalanceResolution:
    """Casa as contas lidas no ERP com as linhas do painel.

    A LISTA DE IGNORADAS VEM PRIMEIRO, E ISSO IMPORTA. O match por nome aceita
    continencia, entao "APLICACAO FUNDO INVESTIMENTOS - MORAIS EMPREENDIMENTOS
    BURITIS - CAIXA ECONOMICA FEDERAL" CONTEM o erp_name da linha 27 e casava
    com ela. As duas contas casavam com a mesma linha e quem vencia era a
    ultima lida — ou seja, o painel dependia da ordem em que o ERP devolvia as
    contas. Consultar `is_ignored` antes de tentar casar remove esse azar: a
    lista existe justamente para dizer "esta conta NUNCA entra no painel".
    """
    resultado = BalanceResolution()
    vistas: set[int] = set()

    for account in accounts:
        if mapping.is_ignored(account.name):
            continue

        row = mapping.resolve_account(account)
        if row is not None and row.exists_in_erp:
            resultado.balances[row.row] = account.balance
            vistas.add(row.row)
        else:
            resultado.contas_desconhecidas.append(account)

    resultado.linhas_nao_encontradas = [r for r in mapping.live_rows if r.row not in vistas]
    return resultado


def aggregate_by_row(classification: Classification) -> dict[int, tuple[Decimal, int]]:
    """Agrupa os elegiveis: linha -> (soma para E, contagem para I)."""
    totals: dict[int, tuple[Decimal, int]] = {}
    for payment, row in classification.eligible:
        total, count = totals.get(row.row, (Decimal("0"), 0))
        totals[row.row] = (total + payment.amount, count + 1)
    return totals


def build_row_fills(
    mapping: AccountMapping,
    balances: dict[int, Decimal | None],
    aggregates: dict[int, tuple[Decimal, int]],
) -> list[RowFill]:
    """Monta o que sera escrito em cada linha do painel (D, E, I, J).

    `balances` mapeia linha -> saldo lido. Linha ausente ou com None significa
    saldo nao lido: a celula fica vazia e o resumo alerta.
    """
    fills: list[RowFill] = []

    for row in sorted(mapping.rows, key=lambda r: r.row):
        # Conta que nao existe mais no ERP: a linha inteira fica em branco.
        if not row.exists_in_erp:
            fills.append(RowFill(row=row.row, balance=None, total=None, count=None, bank_count=None))
            continue

        total, count = aggregates.get(row.row, (Decimal("0"), 0))
        # Regra do zero: sem pagamento hoje, J tambem vai a zero; com pagamento,
        # J fica vazio porque so e preenchido na conferencia manual com o extrato.
        bank_count = 0 if total == 0 else None

        fills.append(
            RowFill(
                row=row.row,
                balance=balances.get(row.row),
                total=total,
                count=count,
                bank_count=bank_count,
            )
        )

    return fills
