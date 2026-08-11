"""Orquestracao do dia a partir de um snapshot. Nenhum browser aqui.

Ordem deliberada: valida ANTES de escrever a planilha. Um arquivo gerado a
partir de dados suspeitos e pior que nenhum arquivo, porque parece confiavel.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config
from .mapping import AccountMapping
from .models import Snapshot
from .panel import PanelComputation, compute_panel
from .report import build_report, write_out_of_panel_log
from .rules import (
    BalanceResolution,
    Classification,
    aggregate_by_row,
    build_row_fills,
    classify_payments,
    resolve_balances,
)
from .validate import Issue, raise_if_errors, validate
from .workbook import build, output_name


@dataclass
class DailyResult:
    snapshot: Snapshot
    balances: BalanceResolution
    classification: Classification
    computation: PanelComputation
    issues: list[Issue]
    resumo: str
    arquivo: Path | None = None
    log_fora_do_painel: Path | None = None


def analyze(snapshot: Snapshot, config: Config, mapping: AccountMapping) -> DailyResult:
    """Roda regras, espelho das formulas e validacoes. Nao escreve nada."""
    balances = resolve_balances(snapshot.accounts, mapping)
    # `intervalo` respeita o periodo pedido na coleta (ex.: sabado a segunda).
    classification = classify_payments(
        snapshot.payments,
        mapping,
        snapshot.intervalo,
        status_a_pagar=config.status_considerados,
        status_fora=config.status_ignorados,
    )
    aggregates = aggregate_by_row(classification)
    fills = build_row_fills(mapping, balances.balances, aggregates)
    computation = compute_panel(fills, mapping, config.planilha)
    issues = validate(snapshot, balances, classification, computation, config)

    resumo = build_report(
        snapshot.intervalo, classification, computation, balances, issues
    )
    return DailyResult(
        snapshot=snapshot,
        balances=balances,
        classification=classification,
        computation=computation,
        issues=issues,
        resumo=resumo,
    )


def run_offline(
    snapshot: Snapshot,
    config: Config,
    mapping: AccountMapping,
    *,
    forcar: bool = False,
) -> DailyResult:
    """Analisa, valida e (se passar) gera a planilha do dia + resumo + log."""
    resultado = analyze(snapshot, config, mapping)

    if not forcar:
        raise_if_errors(resultado.issues)

    aggregates = aggregate_by_row(resultado.classification)
    fills = build_row_fills(mapping, resultado.balances.balances, aggregates)


    destino = config.caminho("saida") / output_name(snapshot.reference_date)
    build_result = build(
        modelo=config.caminho("modelo"),
        destino=destino,
        reference_date=snapshot.reference_date,
        fills=fills,
        mapping=mapping,
        planilha=config.planilha,
    )
    resultado.arquivo = build_result.path

    resultado.log_fora_do_painel = write_out_of_panel_log(
        snapshot.intervalo, resultado.classification, config.caminho("logs")
    )

    resultado.resumo = build_report(
        snapshot.intervalo,
        resultado.classification,
        resultado.computation,
        resultado.balances,
        resultado.issues,
        arquivo=resultado.arquivo,
    )
    return resultado
