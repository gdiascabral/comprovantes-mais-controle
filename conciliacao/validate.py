"""Validacoes do dia. Um painel silenciosamente errado e pior que uma falha.

Erro interrompe a execucao; aviso apenas aparece no resumo e no log.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from .config import Config
from .models import Snapshot
from .panel import PanelComputation
from .parsing import format_brl
from .rules import BalanceResolution, Classification


class Nivel(str, Enum):
    ERRO = "erro"
    AVISO = "aviso"


@dataclass(frozen=True)
class Issue:
    nivel: Nivel
    mensagem: str

    def __str__(self) -> str:
        marca = "ERRO " if self.nivel is Nivel.ERRO else "AVISO"
        return f"[{marca}] {self.mensagem}"


class ValidationError(Exception):
    """Ha erros que impedem confiar no painel do dia."""

    def __init__(self, issues: list[Issue]):
        self.issues = issues
        super().__init__("\n".join(str(i) for i in issues))


def validate(
    snapshot: Snapshot,
    balances: BalanceResolution,
    classification: Classification,
    computation: PanelComputation,
    config: Config,
) -> list[Issue]:
    """Roda todas as checagens e devolve a lista de problemas encontrados."""
    issues: list[Issue] = []

    # --- ERROS ---------------------------------------------------------------

    for row in balances.linhas_nao_encontradas:
        issues.append(
            Issue(
                Nivel.ERRO,
                f"linha {row.row} ({row.label}) esta mapeada mas nao foi encontrada no ERP",
            )
        )

    if config.exigir_todos_os_saldos:
        for linha in computation.saldos_nao_lidos:
            issues.append(
                Issue(
                    Nivel.ERRO,
                    f"linha {linha.row} ({linha.label}) ficou sem saldo; o painel "
                    f"calcularia aporte sobre saldo zero",
                )
            )

    for pagamento in classification.invalid_amount:
        issues.append(
            Issue(
                Nivel.ERRO,
                f"pagamento com valor ilegivel: {pagamento.payee!r} "
                f"em {pagamento.account_label!r}",
            )
        )

    # Status novo no ERP: pode ser algo a pagar que ficaria fora do painel.
    if classification.status_desconhecido:
        vistos = sorted({p.status for p in classification.status_desconhecido})
        total = sum(
            (p.amount for p in classification.status_desconhecido if p.amount is not None),
            Decimal("0"),
        )
        issues.append(
            Issue(
                Nivel.ERRO,
                f"status desconhecido no ERP: {vistos} "
                f"({len(classification.status_desconhecido)} lancamento(s), "
                f"{format_brl(total)} com vencimento no periodo).\n"
                "         Se conta como a pagar, adicione em 'status_considerados' "
                "no config.yaml; se nao, em 'status_ignorados'.",
            )
        )

    # O rodape da grade agrega o MES inteiro, nao o dia. Logo a unica relacao
    # valida e: total do dia nunca pode passar do "Em aberto" do mes.
    agregado = snapshot.page_aggregate_open
    if agregado is not None:
        total_dia = classification.total_eligible + classification.total_out_of_panel
        if total_dia > agregado + config.tolerancia_agregado:
            # Quando o periodo cruza a virada do mes, o agregado lido e de UM
            # mes so, enquanto o total do dia soma os dois — e a comparacao
            # acusa duplicacao que nao existe. Justamente na segunda-feira dia
            # 1o, que ja e o dia mais dificil. Vira aviso.
            periodo = snapshot.intervalo
            cruza_mes = (periodo.inicio.year, periodo.inicio.month) != (
                periodo.fim.year, periodo.fim.month)
            if cruza_mes:
                issues.append(
                    Issue(
                        Nivel.AVISO,
                        f"total do periodo ({format_brl(total_dia)}) passou do "
                        f"'Em aberto' lido no rodape ({format_brl(agregado)}), mas o "
                        f"periodo cruza a virada do mes ({periodo.descrever()}) e o "
                        "rodape so cobre um mes — a comparacao nao vale aqui.",
                    )
                )
            else:
                issues.append(
                    Issue(
                        Nivel.ERRO,
                        f"total de hoje ({format_brl(total_dia)}) passou do 'Em aberto' do mes "
                        f"({format_brl(agregado)}) — a coleta provavelmente duplicou linhas",
                    )
                )

    # --- AVISOS --------------------------------------------------------------

    for account in balances.contas_desconhecidas:
        issues.append(
            Issue(
                Nivel.AVISO,
                f"conta nova no ERP fora do painel: {account.name!r} "
                f"(saldo {format_brl(account.balance)})",
            )
        )

    for pagamento in classification.unmapped:
        issues.append(
            Issue(
                Nivel.AVISO,
                f"pagamento de {format_brl(pagamento.amount)} em conta fora do painel: "
                f"{pagamento.account_label!r} ({pagamento.payee})",
            )
        )

    for linha in computation.saldos_negativos:
        issues.append(
            Issue(
                Nivel.AVISO,
                f"saldo negativo na linha {linha.row} ({linha.label}): "
                f"{format_brl(linha.saldo)}",
            )
        )

    if not classification.eligible:
        issues.append(
            Issue(
                Nivel.AVISO,
                f"nenhum pagamento vence em {snapshot.intervalo.descrever()} — "
                "o painel sai com E=0 em tudo",
            )
        )

    return issues


def erros(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.nivel is Nivel.ERRO]


def avisos(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.nivel is Nivel.AVISO]


def raise_if_errors(issues: list[Issue]) -> None:
    encontrados = erros(issues)
    if encontrados:
        raise ValidationError(encontrados)


def total_conferido(classification: Classification) -> Decimal:
    return classification.total_eligible
