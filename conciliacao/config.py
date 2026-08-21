"""Carga do config.yaml em objetos tipados."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml

from openpyxl.utils import column_index_from_string


@dataclass(frozen=True)
class PlanilhaConfig:
    aba: str
    primeira_linha: int
    ultima_linha: int
    linha_totais: int
    ultima_coluna: str
    celula_data: str
    celula_total_pagamentos: str
    formato_data: str
    col_saldo: str
    col_pagamento: str
    col_qtd_sistema: str
    col_qtd_banco: str
    colunas_formula: tuple[str, ...]

    @property
    def linhas(self) -> range:
        return range(self.primeira_linha, self.ultima_linha + 1)

    @property
    def colunas_escritas(self) -> tuple[str, ...]:
        return (self.col_saldo, self.col_pagamento, self.col_qtd_sistema, self.col_qtd_banco)

    @property
    def area_conferida(self) -> tuple[tuple[int, int], tuple[int, int]]:
        """((linha_ini, linha_fim), (col_ini, col_fim)) da conferencia pos-save.

        Vai ate a linha de TOTAIS, e nao ate a ultima conta: a versao anterior
        deste numero era fixa (33) e ficou para tras quando o modelo cresceu, o
        que deixou as formulas de total fora do guarda-corpo sem ninguem notar.
        """
        return ((1, self.linha_totais), (1, column_index_from_string(self.ultima_coluna)))


@dataclass(frozen=True)
class Config:
    erp: dict
    caminhos: dict
    planilha: PlanilhaConfig
    excluir_valor_exato: Decimal
    status_considerados: tuple[str, ...]
    status_ignorados: tuple[str, ...]
    exigir_todos_os_saldos: bool
    tolerancia_agregado: Decimal
    raiz: Path

    def caminho(self, chave: str) -> Path:
        """Resolve um caminho do config relativo a raiz do projeto."""
        return self.raiz / str(self.caminhos[chave])


def load_config(path: str | Path) -> Config:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    pl = raw["planilha"]
    cols = pl["colunas_escritas"]

    planilha = PlanilhaConfig(
        aba=str(pl["aba"]),
        primeira_linha=int(pl["primeira_linha"]),
        ultima_linha=int(pl["ultima_linha"]),
        linha_totais=int(pl["linha_totais"]),
        ultima_coluna=str(pl["ultima_coluna"]),
        celula_data=str(pl["celula_data"]),
        celula_total_pagamentos=str(pl["celula_total_pagamentos"]),
        formato_data=str(pl["formato_data"]),
        col_saldo=str(cols["saldo"]),
        col_pagamento=str(cols["pagamento"]),
        col_qtd_sistema=str(cols["qtd_sistema"]),
        col_qtd_banco=str(cols["qtd_banco"]),
        colunas_formula=tuple(pl["colunas_formula"]),
    )

    regras = raw.get("regras", {})
    validacao = raw.get("validacao", {})

    return Config(
        erp=raw.get("erp", {}),
        caminhos=raw.get("caminhos", {}),
        planilha=planilha,
        excluir_valor_exato=Decimal(str(regras.get("excluir_valor_exato", "1.00"))),
        status_considerados=tuple(
            regras.get("status_considerados") or ["Em aberto", "Vencido"]
        ),
        status_ignorados=tuple(regras.get("status_ignorados") or ["Pago"]),
        exigir_todos_os_saldos=bool(validacao.get("exigir_todos_os_saldos", True)),
        tolerancia_agregado=Decimal(str(validacao.get("tolerancia_agregado", "0.01"))),
        raiz=path.resolve().parent,
    )
