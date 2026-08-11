"""Carga do config.yaml em objetos tipados."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import yaml


@dataclass(frozen=True)
class RateioRule:
    """Rateio do aporte de uma linha entre dois aportadores.

    No caso do Buritis - Inter: o deficit e dividido 2:1 entre a Morais
    Engenharia (`fator_principal`) e a Julio/Livian (`divisor_secundario`).
    """

    linha: int
    fator_principal: Decimal
    aportador_principal: str
    aportador_secundario: str
    divisor_secundario: Decimal
    celula_secundario: str


@dataclass(frozen=True)
class PlanilhaConfig:
    primeira_linha: int
    ultima_linha: int
    celula_data: str
    celula_total_pagamentos: str
    formato_data: str
    col_saldo: str
    col_pagamento: str
    col_qtd_sistema: str
    col_qtd_banco: str
    colunas_formula: tuple[str, ...]
    linhas_com_aporte_zero_fixo: frozenset[int]
    aportes_direcionados: dict[int, str]
    rateios: tuple[RateioRule, ...]

    @property
    def linhas(self) -> range:
        return range(self.primeira_linha, self.ultima_linha + 1)

    @property
    def colunas_escritas(self) -> tuple[str, ...]:
        return (self.col_saldo, self.col_pagamento, self.col_qtd_sistema, self.col_qtd_banco)

    def rateio_da_linha(self, linha: int) -> RateioRule | None:
        return next((r for r in self.rateios if r.linha == linha), None)


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
    pn = raw.get("painel", {})
    cols = pl["colunas_escritas"]

    planilha = PlanilhaConfig(
        primeira_linha=int(pl["primeira_linha"]),
        ultima_linha=int(pl["ultima_linha"]),
        celula_data=str(pl["celula_data"]),
        celula_total_pagamentos=str(pl["celula_total_pagamentos"]),
        formato_data=str(pl["formato_data"]),
        col_saldo=str(cols["saldo"]),
        col_pagamento=str(cols["pagamento"]),
        col_qtd_sistema=str(cols["qtd_sistema"]),
        col_qtd_banco=str(cols["qtd_banco"]),
        colunas_formula=tuple(pl["colunas_formula"]),
        linhas_com_aporte_zero_fixo=frozenset(
            int(r) for r in pn.get("linhas_com_aporte_zero_fixo", [])
        ),
        aportes_direcionados={
            int(k): str(v) for k, v in (pn.get("aportes_direcionados") or {}).items()
        },
        rateios=tuple(
            RateioRule(
                linha=int(r["linha"]),
                fator_principal=Decimal(str(r["fator_principal"])),
                aportador_principal=str(r["aportador_principal"]),
                aportador_secundario=str(r["aportador_secundario"]),
                divisor_secundario=Decimal(str(r["divisor_secundario"])),
                celula_secundario=str(r["celula_secundario"]),
            )
            for r in pn.get("rateios", [])
        ),
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
