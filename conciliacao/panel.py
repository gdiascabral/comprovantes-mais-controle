"""Espelho em memoria das formulas do painel — usado SO para o resumo em texto.

O programa nunca escreve nas colunas de formula: elas continuam vivas no xlsx e
o Gustavo decide o aporte final olhando o Excel. Este modulo existe porque o
openpyxl nao recalcula formulas, e sem recalcular o resumo nao teria como dizer
"a conta X precisa de no minimo R$ Y".

Formulas espelhadas (linha n do modelo de tres abas):
    E = SUMIF(Movimentações!origem,  Bn, Movimentações!valor)   -> o que SAI
    F = SUMIF(Movimentações!destino, Bn, Movimentações!valor)   -> o que ENTRA
    G = IF(Cn>=Dn+En, "—", Dn+En-Cn)                            -> aporte minimo
    I = Cn - Dn - En + Fn                                       -> saldo final

NO ARQUIVO RECEM-GERADO, E E F VALEM ZERO. As duas somam a aba «Movimentações»,
que por sua vez rateia o APORTE DEFINIDO (coluna H) — e H so e preenchido
depois, pelo Gustavo. Foi isto que sumiu com o modelo velho: la a coluna N
direcionava o aporte de UMA linha automaticamente, e o espelho tinha que
refazer a cadeia de SUMIF em Python. Aqui nao ha cadeia: minimo = o que falta.

`tests/test_modelo_consistencia.py` compara este espelho com as formulas reais
do arquivo e falha se alguem editar o modelo sem atualizar aqui.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .aportadores import Regra, saidas_estimadas
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
    saldo: Decimal | None  # C — None = nao lido (celula vazia)
    pagamento: Decimal | None  # D
    aporte_minimo: Decimal | None  # G — None espelha o "—" do Excel
    saldo_final: Decimal  # I
    #: Quem entra nesta conta, em texto ("Morais (2) · Livian/Julio (1)").
    #: Vem da aba «Regras» do modelo; "" quando a conta nao tem aportador.
    aportadores: str = ""

    @property
    def precisa_aporte(self) -> bool:
        return self.aporte_minimo is not None and self.aporte_minimo > ZERO

    @property
    def saldo_nao_lido(self) -> bool:
        return self.saldo is None


@dataclass(frozen=True)
class PanelComputation:
    rows: list[RowComputation] = field(default_factory=list)
    #: Quanto cada aportador teria de mandar se o aporte fosse o MINIMO de cada
    #: conta. So entra quem tem peso na aba «Regras».
    saidas_minimas: dict[str, Decimal] = field(default_factory=dict)
    #: Contas cujo rateio nao tem peso: o valor total e seu, a divisao e sua.
    a_dividir: list[tuple[str, Decimal, tuple[str, ...]]] = field(default_factory=list)

    def by_row(self, row: int) -> RowComputation | None:
        return next((r for r in self.rows if r.row == row), None)

    @property
    def total_pagamentos(self) -> Decimal:
        """Espelha a celula de total dos pagamentos do dia."""
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

    @property
    def total_aporte_minimo(self) -> Decimal:
        return sum((r.aporte_minimo for r in self.precisam_aporte), ZERO)


def _aporte_minimo(saldo: Decimal | None, pagamento: Decimal | None) -> Decimal | None:
    """Espelha G. Devolve None onde o Excel mostra "—" (nao precisa de aporte).

    `E` (o que sai) nao entra na conta porque vale zero no arquivo recem-gerado
    — ver o cabecalho do modulo. No Excel a formula continua somando E, e e por
    isso que o numero se corrige sozinho assim que voce preenche um aporte.
    """
    if pagamento is None:  # linha sem conta no ERP: celula vazia
        return None
    if _num(saldo) >= pagamento:
        return None
    return pagamento - _num(saldo)


def compute_panel(
    fills: list[RowFill],
    mapping: AccountMapping,
    planilha: PlanilhaConfig,
    regras: list[Regra] | None = None,
) -> PanelComputation:
    """Calcula o aporte minimo e o saldo final de cada linha."""
    label_by_row = {r.row: r.label for r in mapping.rows}
    regras = regras or []
    texto_por_conta: dict[str, str] = {}
    for regra in regras:
        parte = regra.aportador if regra.peso is None else f"{regra.aportador} ({regra.peso})"
        anterior = texto_por_conta.get(regra.destino)
        texto_por_conta[regra.destino] = f"{anterior} · {parte}" if anterior else parte

    rows: list[RowComputation] = []
    for row in planilha.linhas:
        fill = next((f for f in fills if f.row == row), None)
        if fill is None:
            continue
        label = label_by_row.get(row, "")
        rows.append(
            RowComputation(
                row=row,
                label=label,
                saldo=fill.balance,
                pagamento=fill.total,
                aporte_minimo=_aporte_minimo(fill.balance, fill.total),
                saldo_final=_num(fill.balance) - _num(fill.total),
                aportadores=texto_por_conta.get(label, ""),
            )
        )

    minimos = {r.label: r.aporte_minimo for r in rows if r.precisa_aporte}
    saidas, a_dividir = saidas_estimadas(minimos, regras)
    return PanelComputation(rows=rows, saidas_minimas=saidas, a_dividir=a_dividir)
