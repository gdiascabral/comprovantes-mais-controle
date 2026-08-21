"""Resumo do dia em portugues, direto ao ponto.

Os numeros de aporte vem do `panel.py` (espelho das formulas), nao do arquivo:
o openpyxl nao recalcula, e no arquivo recem-gerado as colunas de aporte ainda
estao zeradas — elas so ganham valor quando o Gustavo preenche o APORTE
DEFINIDO e a aba «Movimentações» rateia.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import Periodo
from .panel import PanelComputation
from .parsing import format_brl
from .rules import BalanceResolution, Classification
from .validate import Issue, avisos, erros


def _linha_conta(label: str, valor: str, largura: int = 46) -> str:
    return f"  {label[:largura]:<{largura}} {valor:>16}"


def build_report(
    periodo: Periodo | date,
    classification: Classification,
    computation: PanelComputation,
    balances: BalanceResolution,
    issues: list[Issue],
    arquivo: Path | None = None,
) -> str:
    intervalo = Periodo.normalizar(periodo)
    partes: list[str] = []
    add = partes.append

    add(f"CONCILIACAO DE {intervalo.descrever()}")
    add("=" * 64)

    # --- total do periodo ----------------------------------------------------
    total = classification.total_eligible
    qtd = len(classification.eligible)
    add("")
    if intervalo.um_dia_so:
        add(f"Total a pagar hoje: {format_brl(total)} em {qtd} lancamento(s)")
    else:
        dias = len(intervalo.dias)
        add(
            f"Total a pagar no periodo ({dias} dias, vencimentos de "
            f"{intervalo.inicio:%d/%m} a {intervalo.fim:%d/%m}): "
            f"{format_brl(total)} em {qtd} lancamento(s)"
        )

    if classification.excluded_one_real:
        add(f"  ({len(classification.excluded_one_real)} lancamento(s) de R$ 1,00 excluido(s))")

    fora = classification.ignored_by_config + classification.unmapped
    if fora:
        add(
            f"  ({len(fora)} lancamento(s) em contas fora do painel, "
            f"{format_brl(classification.total_out_of_panel)} — ver log)"
        )

    # --- contas que precisam de aporte --------------------------------------
    precisam = computation.precisam_aporte
    add("")
    if precisam:
        add(f"CONTAS QUE PRECISAM DE APORTE ({len(precisam)})")
        add("-" * 64)
        for linha in precisam:
            add(_linha_conta(linha.label, format_brl(linha.aporte_minimo)))
            if linha.aportadores:
                add(f"      quem entra: {linha.aportadores}")
            else:
                add("      (sem aportador na aba Regras)")
        add("")
        add(_linha_conta("TOTAL DE APORTE MINIMO", format_brl(computation.total_aporte_minimo)))
        add("")
        add("  Estes sao os valores MINIMOS — o valor final do aporte e sua decisao.")

        # --- quanto sairia de cada aportador, se o aporte fosse o minimo -----
        if computation.saidas_minimas or computation.a_dividir:
            add("")
            add("SE VOCE APORTAR O MINIMO EM TODAS")
            add("-" * 64)
            for quem, quanto in sorted(
                computation.saidas_minimas.items(), key=lambda kv: -kv[1]
            ):
                add(_linha_conta(quem, format_brl(quanto)))
            for destino, valor, participantes in computation.a_dividir:
                add(_linha_conta(f"{destino} (a dividir)", format_brl(valor)))
                add(f"      entre: {' · '.join(participantes)}")
    else:
        add("Nenhuma conta precisa de aporte hoje.")

    # --- saldos atipicos -----------------------------------------------------
    negativos = computation.saldos_negativos
    zerados = [
        r for r in computation.rows if r.saldo is not None and r.saldo == Decimal("0")
    ]
    if negativos or zerados:
        add("")
        add("SALDOS ATIPICOS")
        add("-" * 64)
        for linha in negativos:
            add(_linha_conta(f"{linha.label} (negativo)", format_brl(linha.saldo)))
        for linha in zerados:
            add(_linha_conta(f"{linha.label} (zerado)", format_brl(linha.saldo)))

    # --- problemas -----------------------------------------------------------
    lista_erros, lista_avisos = erros(issues), avisos(issues)
    if lista_erros:
        add("")
        add(f"ERROS ({len(lista_erros)})")
        add("-" * 64)
        for issue in lista_erros:
            add(f"  {issue.mensagem}")

    if lista_avisos:
        add("")
        add(f"AVISOS ({len(lista_avisos)})")
        add("-" * 64)
        for issue in lista_avisos:
            add(f"  {issue.mensagem}")

    # --- arquivo -------------------------------------------------------------
    add("")
    add("-" * 64)
    add(f"Contas lidas no ERP: {len(balances.balances)} de {len(balances.balances) + len(balances.linhas_nao_encontradas)} mapeadas")
    if arquivo is not None:
        add(f"Arquivo: {arquivo}")

    return "\n".join(partes)


def write_out_of_panel_log(
    periodo: Periodo | date,
    classification: Classification,
    directory: str | Path,
) -> Path | None:
    """Grava o log das contas fora do painel. Devolve None quando nao ha nada."""
    intervalo = Periodo.normalizar(periodo)
    fora = classification.ignored_by_config + classification.unmapped
    if not fora:
        return None

    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"fora-do-painel-{intervalo.fim:%Y-%m-%d}.txt"

    linhas = [
        f"Pagamentos com vencimento em {intervalo.descrever()} "
        "em contas fora do painel",
        "",
    ]
    for pagamento in classification.ignored_by_config:
        linhas.append(
            f"[ignorada]    {format_brl(pagamento.amount):>18}  "
            f"{pagamento.account_label}  |  {pagamento.payee}"
        )
    for pagamento in classification.unmapped:
        linhas.append(
            f"[desconhecida]{format_brl(pagamento.amount):>18}  "
            f"{pagamento.account_label}  |  {pagamento.payee}"
        )
    linhas.append("")
    linhas.append(f"Total fora do painel: {format_brl(classification.total_out_of_panel)}")

    path.write_text("\n".join(linhas), encoding="utf-8")
    return path
