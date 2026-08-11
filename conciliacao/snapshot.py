"""Leitura/escrita do snapshot bruto.

O snapshot e a fronteira do programa: a coleta (browser) so escreve, o resto
so le. Isso permite reprocessar o dia inteiro sem reabrir o ERP e da fixtures
reais para os testes.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from .models import ErpAccount, ErpPayment, Periodo, Snapshot

_ISO = "%Y-%m-%d"


def _money_out(value: Decimal | None) -> str | None:
    """Dinheiro vai para o JSON como string — nunca float, para nao perder centavo."""
    return None if value is None else str(value)


def _money_in(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def to_dict(snapshot: Snapshot) -> dict:
    return {
        "reference_date": snapshot.reference_date.strftime(_ISO),
        "collected_at": snapshot.collected_at,
        "page_aggregate_open": _money_out(snapshot.page_aggregate_open),
        "periodo": (
            None
            if snapshot.periodo is None
            else {
                "inicio": snapshot.periodo.inicio.strftime(_ISO),
                "fim": snapshot.periodo.fim.strftime(_ISO),
            }
        ),
        "accounts": [
            {
                "id": a.id,
                "name": a.name,
                "is_active": a.is_active,
                "bank_code": a.bank_code,
                "agency": a.agency,
                "account_number": a.account_number,
                "raw_balance": a.raw_balance,
                "balance": _money_out(a.balance),
            }
            for a in snapshot.accounts
        ],
        "payments": [
            {
                "due_date": p.due_date.strftime(_ISO) if p.due_date else None,
                "status": p.status,
                "amount": _money_out(p.amount),
                "payee": p.payee,
                "account_label": p.account_label,
                "raw": p.raw,
            }
            for p in snapshot.payments
        ],
    }


def from_dict(data: dict) -> Snapshot:
    bruto = data.get("periodo")
    return Snapshot(
        reference_date=date.fromisoformat(data["reference_date"]),
        collected_at=data.get("collected_at", ""),
        page_aggregate_open=_money_in(data.get("page_aggregate_open")),
        periodo=(
            Periodo(
                inicio=date.fromisoformat(bruto["inicio"]),
                fim=date.fromisoformat(bruto["fim"]),
            )
            if bruto
            else None
        ),
        accounts=[
            ErpAccount(
                id=a.get("id", ""),
                name=a.get("name", ""),
                is_active=bool(a.get("is_active", True)),
                bank_code=a.get("bank_code"),
                agency=a.get("agency"),
                account_number=a.get("account_number"),
                raw_balance=a.get("raw_balance"),
                balance=_money_in(a.get("balance")),
            )
            for a in data.get("accounts", [])
        ],
        payments=[
            ErpPayment(
                due_date=date.fromisoformat(p["due_date"]) if p.get("due_date") else None,
                status=p.get("status", ""),
                amount=_money_in(p.get("amount")),
                payee=p.get("payee", ""),
                account_label=p.get("account_label", ""),
                raw=p.get("raw", {}),
            )
            for p in data.get("payments", [])
        ],
    )


def save(snapshot: Snapshot, directory: str | Path) -> Path:
    """Grava `snapshots/AAAA-MM-DD.json` (sobrescreve o do dia — idempotente)."""
    folder = Path(directory)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{snapshot.reference_date.strftime(_ISO)}.json"
    path.write_text(
        json.dumps(to_dict(snapshot), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def load(path: str | Path) -> Snapshot:
    return from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
