"""Montagem da planilha final.

Escreve apenas E4 (data) e D/E/I/J nas linhas 8 a 31. Todas as formulas do
modelo (F, G, H, K, L, M, N, F32, E33) sao preservadas — o programa nunca poe
valor onde havia formula, e confere isso celula por celula depois de salvar.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

import openpyxl
from openpyxl.worksheet.worksheet import Worksheet

from .config import PlanilhaConfig
from .mapping import AccountMapping
from .models import RowFill
from .parsing import to_float

#: Area do modelo conferida contra o original apos salvar.
_AREA_CONFERIDA = ((1, 33), (1, 16))  # linhas 1-33, colunas A-P


class WorkbookError(Exception):
    """Falha ao montar ou validar a planilha."""


@dataclass(frozen=True)
class BuildResult:
    path: Path
    linhas_escritas: int
    celulas_conferidas: int


def output_name(reference_date: date) -> str:
    """Nome idempotente do dia: "30 07 - completa.xlsx" (sobrescreve o do dia)."""
    return f"{reference_date:%d %m} - completa.xlsx"


def _comparavel(value: object) -> object:
    """Normaliza para comparar celulas relidas.

    O Excel guarda data como numero de serie e o openpyxl devolve `datetime`,
    mesmo quando gravamos um `date`.
    """
    if isinstance(value, datetime):
        return value.date()
    return value


def _sheet(wb) -> Worksheet:
    if len(wb.worksheets) != 1:
        raise WorkbookError(
            f"esperava 1 aba no modelo, encontrei {len(wb.worksheets)}: {wb.sheetnames}"
        )
    return wb.worksheets[0]


def check_labels(ws: Worksheet, mapping: AccountMapping) -> None:
    """Confere que o mapping.yaml casa com a coluna B do modelo.

    Critico: a coluna F usa SUMIF(N, B, M). Se o label do mapping divergir de B,
    o encadeamento de aportes devolve zero sem erro nenhum no Excel.
    """
    divergencias = []
    for row in mapping.rows:
        no_modelo = ws[f"B{row.row}"].value
        if (no_modelo or "") != row.label:
            divergencias.append(f"  linha {row.row}: modelo={no_modelo!r} mapping={row.label!r}")

    if divergencias:
        raise WorkbookError(
            "label do mapping.yaml diverge da coluna B do modelo:\n" + "\n".join(divergencias)
        )


def build(
    modelo: str | Path,
    destino: str | Path,
    reference_date: date,
    fills: list[RowFill],
    mapping: AccountMapping,
    planilha: PlanilhaConfig,
) -> BuildResult:
    """Copia o modelo, preenche o dia e valida o resultado."""
    modelo, destino = Path(modelo), Path(destino)
    if not modelo.is_file():
        raise WorkbookError(f"modelo nao encontrado: {modelo}")

    destino.parent.mkdir(parents=True, exist_ok=True)
    # Copia antes de abrir para nunca correr risco de salvar sobre o original.
    shutil.copy2(modelo, destino)

    wb = openpyxl.load_workbook(destino)
    ws = _sheet(wb)
    check_labels(ws, mapping)

    # E4: data de referencia. O modelo vem com formato americano (m/d/yyyy);
    # forcamos DD/MM/YYYY para ler certo em portugues.
    celula_data = ws[planilha.celula_data]
    celula_data.value = reference_date
    celula_data.number_format = planilha.formato_data

    escritas = 0
    for fill in fills:
        if fill.row not in planilha.linhas:
            raise WorkbookError(f"linha {fill.row} fora da faixa do painel")
        ws[f"{planilha.col_saldo}{fill.row}"] = to_float(fill.balance)
        ws[f"{planilha.col_pagamento}{fill.row}"] = to_float(fill.total)
        ws[f"{planilha.col_qtd_sistema}{fill.row}"] = fill.count
        ws[f"{planilha.col_qtd_banco}{fill.row}"] = fill.bank_count
        escritas += 1

    wb.save(destino)
    wb.close()

    conferidas = assert_untouched(modelo, destino, reference_date, fills, planilha)
    return BuildResult(path=destino, linhas_escritas=escritas, celulas_conferidas=conferidas)


def assert_untouched(
    modelo: str | Path,
    destino: str | Path,
    reference_date: date,
    fills: list[RowFill],
    planilha: PlanilhaConfig,
) -> int:
    """Reabre os dois arquivos e prova que so as celulas previstas mudaram.

    Devolve a quantidade de celulas conferidas. Qualquer formula perdida no
    round-trip do openpyxl aparece aqui como divergencia.
    """
    esperado = _celulas_escritas(reference_date, fills, planilha)

    wb_orig = openpyxl.load_workbook(Path(modelo))
    wb_novo = openpyxl.load_workbook(Path(destino))
    try:
        ws_orig, ws_novo = _sheet(wb_orig), _sheet(wb_novo)
        (r1, r2), (c1, c2) = _AREA_CONFERIDA

        problemas: list[str] = []
        conferidas = 0
        for row in range(r1, r2 + 1):
            for col in range(c1, c2 + 1):
                original = ws_orig.cell(row=row, column=col)
                novo = ws_novo.cell(row=row, column=col)
                coord = original.coordinate

                if coord in esperado:
                    if _comparavel(novo.value) != _comparavel(esperado[coord]):
                        problemas.append(
                            f"  {coord}: gravado={novo.value!r} esperado={esperado[coord]!r}"
                        )
                    continue

                conferidas += 1
                if original.value != novo.value:
                    problemas.append(
                        f"  {coord}: modelo={original.value!r} virou {novo.value!r}"
                    )

        if problemas:
            raise WorkbookError("planilha final divergiu do modelo:\n" + "\n".join(problemas))
        return conferidas
    finally:
        wb_orig.close()
        wb_novo.close()


def _celulas_escritas(
    reference_date: date,
    fills: list[RowFill],
    planilha: PlanilhaConfig,
) -> dict[str, object]:
    """Mapa coordenada -> valor esperado, para as celulas que o programa escreve."""
    esperado: dict[str, object] = {planilha.celula_data: reference_date}
    for fill in fills:
        esperado[f"{planilha.col_saldo}{fill.row}"] = to_float(fill.balance)
        esperado[f"{planilha.col_pagamento}{fill.row}"] = to_float(fill.total)
        esperado[f"{planilha.col_qtd_sistema}{fill.row}"] = fill.count
        esperado[f"{planilha.col_qtd_banco}{fill.row}"] = fill.bank_count
    return esperado
