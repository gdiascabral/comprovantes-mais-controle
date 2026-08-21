"""Orquestracao do dia a partir de um snapshot. Nenhum browser aqui.

Ordem deliberada: valida ANTES de escrever a planilha. Um arquivo gerado a
partir de dados suspeitos e pior que nenhum arquivo, porque parece confiavel.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .aportadores import ler_regras
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
    #: Linhas ja calculadas do painel. Ficam aqui para o `run_offline` nao
    #: refazer a conta: recalcular abre a porta para os dois caminhos
    #: divergirem, e ai a planilha sairia diferente do resumo que a validou.
    fills: list = field(default_factory=list)
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
    # As regras de aporte moram na aba «Regras» do modelo, e nao no config: elas
    # citam pessoa fisica e o repositorio e publico (ver `aportadores.py`). Sem
    # o modelo a lista volta vazia e o resumo apenas nao diz quem entra.
    regras = ler_regras(config.caminho("modelo"))
    computation = compute_panel(fills, mapping, config.planilha, regras)
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
        fills=fills,
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

    # Vem do analyze: era recalculado aqui, com o risco de divergir do que foi
    # validado logo acima.
    fills = resultado.fills

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
