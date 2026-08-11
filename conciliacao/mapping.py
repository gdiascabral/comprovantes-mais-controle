"""Resolve conta do ERP -> linha do painel.

Ordem de match, da mais estavel para a mais fragil:
  1. UUID (`account.id`) — imune a renomeacao;
  2. numero da conta — sobrevive a divergencia de rotulo (caso da linha 16);
  3. nome normalizado — igualdade primeiro, depois "contido em", e SO se
     houver um unico candidato. Ambiguidade nunca chuta: devolve None.

Conflito no proprio mapping.yaml (dois rows com mesmo UUID/numero) e erro de
configuracao e falha na carga — melhor explodir agora que escrever painel errado.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .models import ErpAccount, ModelRow
from .parsing import extract_account_numbers, normalize_account_number, normalize_name


class MappingError(Exception):
    """Problema de configuracao no mapping.yaml."""


@dataclass
class AccountMapping:
    rows: list[ModelRow]
    ignored_names: list[str]

    # ------------------------------------------------------------------ carga

    @classmethod
    def load(cls, path: str | Path) -> AccountMapping:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        rows: list[ModelRow] = []

        for entry in raw.get("model_rows", []):
            if "row" not in entry or "label" not in entry:
                raise MappingError(f"entrada sem 'row'/'label': {entry!r}")
            rows.append(
                ModelRow(
                    row=int(entry["row"]),
                    label=str(entry["label"]),
                    uuid=entry.get("uuid") or None,
                    account_number=normalize_account_number(entry.get("account_number")),
                    erp_name=entry.get("erp_name") or None,
                    exists_in_erp=bool(entry.get("exists_in_erp", True)),
                )
            )

        mapping = cls(rows=rows, ignored_names=list(raw.get("ignored_erp_accounts", [])))
        mapping._validate()
        mapping._build_indexes()
        return mapping

    def _validate(self) -> None:
        for field in ("row", "uuid", "account_number"):
            seen: dict[object, int] = {}
            for row in self.rows:
                key = getattr(row, field)
                if key is None:
                    continue
                if key in seen:
                    raise MappingError(
                        f"{field} duplicado ({key!r}) nas linhas {seen[key]} e {row.row}"
                    )
                seen[key] = row.row

        for row in self.rows:
            if row.exists_in_erp and not (row.uuid or row.account_number or row.erp_name):
                raise MappingError(
                    f"linha {row.row} ({row.label}) existe no ERP mas nao tem "
                    "nenhuma chave de match (uuid/account_number/erp_name)"
                )

    def _build_indexes(self) -> None:
        self._by_uuid = {r.uuid: r for r in self.rows if r.uuid}
        self._by_number = {r.account_number: r for r in self.rows if r.account_number}
        self._by_name = {normalize_name(r.erp_name): r for r in self.rows if r.erp_name}
        self._ignored_normalized = [normalize_name(n) for n in self.ignored_names if n]

    # --------------------------------------------------------------- consulta

    @property
    def live_rows(self) -> list[ModelRow]:
        """Linhas que tem conta correspondente no ERP."""
        return [r for r in self.rows if r.exists_in_erp]

    @property
    def dead_rows(self) -> list[ModelRow]:
        """Linhas do painel cuja conta nao existe mais no ERP (28, 30, 31)."""
        return [r for r in self.rows if not r.exists_in_erp]

    def by_row(self, row: int) -> ModelRow | None:
        return next((r for r in self.rows if r.row == row), None)

    def resolve_account(self, account: ErpAccount) -> ModelRow | None:
        """Casa uma conta lida em #/accounts (tem UUID) com uma linha do painel."""
        if account.id and account.id in self._by_uuid:
            return self._by_uuid[account.id]

        number = normalize_account_number(account.account_number)
        if number and number in self._by_number:
            return self._by_number[number]

        return self.resolve_label(account.name)

    def resolve_label(self, label: str | None) -> ModelRow | None:
        """Casa um nome livre de conta (grade de pagamentos nao expoe UUID)."""
        if not label:
            return None

        for number in extract_account_numbers(label):
            if number in self._by_number:
                return self._by_number[number]

        normalized = normalize_name(label)
        if not normalized:
            return None
        if normalized in self._by_name:
            return self._by_name[normalized]

        # Fallback por continencia — aceito somente se for inequivoco.
        candidates = [
            row
            for name, row in self._by_name.items()
            if name and (name in normalized or normalized in name)
        ]
        return candidates[0] if len(candidates) == 1 else None

    def is_ignored(self, label: str | None) -> bool:
        """True para conta do ERP que sabidamente nao pertence ao painel."""
        normalized = normalize_name(label)
        if not normalized:
            return False
        return any(ign in normalized for ign in self._ignored_normalized if ign)
