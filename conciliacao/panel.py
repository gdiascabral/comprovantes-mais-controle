"""Espelho em memoria das formulas do painel — usado SO para o resumo em texto.

O programa nunca escreve nas colunas de formula: elas continuam vivas no xlsx
e o Gustavo decide o aporte final olhando o Excel. Este modulo existe porque o
openpyxl nao recalcula formulas, e sem recalcular o resumo nao teria como dizer
"a conta X precisa de no minimo R$ Y".

Formulas espelhadas (linha n, extraidas do MODELO.xlsx):
    F = SUMIF($N$8:$N$31, Bn, $M$8:$M$31)      (literal 0 nas linhas 12 e 13)
    G = Dn - En - Fn
    M = IF(En="", 0, IF(Dn>(En+Fn), "-", ((En+Fn)-Dn) * fator))
    H = IF(Gn<0, Gn+Mn(+F32 na linha 9), Gn)
    F32 = IF(M9>0, M9/2, 0)

`tests/test_modelo_consistencia.py` compara este espelho com as formulas reais
do arquivo e falha se alguem editar o modelo sem atualizar aqui.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .config import PlanilhaConfig
from .mapping import AccountMapping
from .models import RowFill

ZERO = Decimal("0")


def _num(value: Decimal | None) -> Decimal:
    """Celula vazia vale zero em aritmetica de Excel."""
    return ZERO if value is None else value


@dataclass(frozen=True)
class RowComputation:
    row: int
    label: str
    saldo: Decimal | None  # D — None = nao lido (celula vazia)
    pagamento: Decimal | None  # E
    aportes_recebidos: Decimal  # F
    saldo_final: Decimal  # G
    aporte_minimo: Decimal | None  # M — None espelha o "-" do Excel
    saldo_pos_aporte: Decimal  # H
    aporte_direcionado_para: str | None  # N

    @property
    def precisa_aporte(self) -> bool:
        """Sinal real de necessidade de aporte.

        Nao usamos a coluna L do modelo porque ela depende de J
        (`IF(J="","-",...)`), e J so e preenchido na conferencia manual com o
        extrato — no arquivo recem-gerado L fica sempre "-".
        """
        return self.aporte_minimo is not None and self.aporte_minimo > ZERO

    @property
    def saldo_nao_lido(self) -> bool:
        return self.saldo is None


@dataclass(frozen=True)
class PanelComputation:
    rows: list[RowComputation] = field(default_factory=list)
    #: Aportes do rateio secundario por celula, ex. {"F32": Decimal("6692.16")}.
    rateios_secundarios: dict[str, Decimal] = field(default_factory=dict)

    def by_row(self, row: int) -> RowComputation | None:
        return next((r for r in self.rows if r.row == row), None)

    @property
    def total_pagamentos(self) -> Decimal:
        """Espelha E33 = SUM(E8:E31)."""
        return sum((_num(r.pagamento) for r in self.rows), ZERO)

    @property
    def precisam_aporte(self) -> list[RowComputation]:
        return [r for r in self.rows if r.precisa_aporte]

    @property
    def saldos_nao_lidos(self) -> list[RowComputation]:
        return [r for r in self.rows if r.saldo_nao_lido and r.pagamento is not None]

    @property
    def saldos_negativos(self) -> list[RowComputation]:
        return [r for r in self.rows if r.saldo is not None and r.saldo < ZERO]


def _aporte_minimo(
    saldo: Decimal | None,
    pagamento: Decimal | None,
    aportes: Decimal,
    fator: Decimal,
) -> Decimal | None:
    """Espelha M. Devolve None onde o Excel mostra "-" (nao precisa de aporte)."""
    if pagamento is None:  # IF(E="", 0, ...)
        return ZERO
    necessario = pagamento + aportes
    if _num(saldo) > necessario:
        return None
    return (necessario - _num(saldo)) * fator


def compute_panel(
    fills: list[RowFill],
    mapping: AccountMapping,
    planilha: PlanilhaConfig,
) -> PanelComputation:
    """Calcula F, G, M, H e o rateio secundario a partir do que sera escrito."""
    fill_by_row = {f.row: f for f in fills}
    label_by_row = {r.row: r.label for r in mapping.rows}

    fator_por_linha = {
        r.linha: r.fator_principal for r in planilha.rateios
    }

    def fator(row: int) -> Decimal:
        return fator_por_linha.get(row, Decimal("1"))

    # --- passada 1: linhas cujo F e literal 0, logo M nao depende de ninguem.
    aporte_minimo: dict[int, Decimal | None] = {}
    aportes_recebidos: dict[int, Decimal] = {}

    for row in planilha.linhas_com_aporte_zero_fixo:
        fill = fill_by_row.get(row)
        if fill is None:
            continue
        aportes_recebidos[row] = ZERO
        aporte_minimo[row] = _aporte_minimo(fill.balance, fill.total, ZERO, fator(row))

    # --- coluna F das demais linhas: SUMIF sobre os aportes direcionados a ela.
    # O SUMIF do Excel e insensivel a maiusculas, entao comparamos em casefold.
    # N so e preenchido quando M > 0, logo aporte nulo/"-" nao soma.
    for row in planilha.linhas:
        if row in aportes_recebidos:
            continue
        alvo = (label_by_row.get(row) or "").casefold()
        total = ZERO
        for origem, destino in planilha.aportes_direcionados.items():
            if destino.casefold() != alvo:
                continue
            valor = aporte_minimo.get(origem)
            if valor is not None and valor > ZERO:
                total += valor
        aportes_recebidos[row] = total

    # --- passada 2: M das demais linhas.
    for row in planilha.linhas:
        if row in aporte_minimo:
            continue
        fill = fill_by_row.get(row)
        if fill is None:
            continue
        aporte_minimo[row] = _aporte_minimo(
            fill.balance, fill.total, aportes_recebidos[row], fator(row)
        )

    # --- rateio secundario (F32 = M9/2): a parte da Julio/Livian.
    rateios_secundarios: dict[str, Decimal] = {}
    for regra in planilha.rateios:
        principal = aporte_minimo.get(regra.linha)
        valor = (
            principal / regra.divisor_secundario
            if principal is not None and principal > ZERO
            else ZERO
        )
        rateios_secundarios[regra.celula_secundario] = valor

    # --- G e H.
    rows: list[RowComputation] = []
    for row in planilha.linhas:
        fill = fill_by_row.get(row)
        if fill is None:
            continue

        aportes = aportes_recebidos[row]
        minimo = aporte_minimo[row]
        saldo_final = _num(fill.balance) - _num(fill.total) - aportes

        # H soma o aporte recebido; na linha com rateio soma tambem a parte
        # do aportador secundario (F32), fechando 100% do deficit.
        if saldo_final < ZERO:
            extra = ZERO
            regra = planilha.rateio_da_linha(row)
            if regra is not None:
                extra = rateios_secundarios.get(regra.celula_secundario, ZERO)
            saldo_pos = saldo_final + _num(minimo) + extra
        else:
            saldo_pos = saldo_final

        rows.append(
            RowComputation(
                row=row,
                label=label_by_row.get(row, ""),
                saldo=fill.balance,
                pagamento=fill.total,
                aportes_recebidos=aportes,
                saldo_final=saldo_final,
                aporte_minimo=minimo,
                saldo_pos_aporte=saldo_pos,
                aporte_direcionado_para=(
                    planilha.aportes_direcionados.get(row)
                    if minimo is not None and minimo > ZERO
                    else None
                ),
            )
        )

    return PanelComputation(rows=rows, rateios_secundarios=rateios_secundarios)
