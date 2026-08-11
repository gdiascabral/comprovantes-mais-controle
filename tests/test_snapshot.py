from datetime import date
from decimal import Decimal

from conciliacao import snapshot as snapshot_io
from conciliacao.models import ErpAccount, ErpPayment, Snapshot


def test_round_trip_preserva_centavos_e_negativos(tmp_path):
    original = Snapshot(
        reference_date=date(2026, 7, 30),
        collected_at="2026-07-30T08:15:00",
        page_aggregate_open=Decimal("123456.78"),
        accounts=[
            ErpAccount(
                id="uuid-1",
                name="MORAIS ENGENHARIA - INTER",
                account_number="55.694-7",
                raw_balance="R$ 1.536.956,24",
                balance=Decimal("1536956.24"),
            ),
            ErpAccount(id="uuid-2", name="TERRA BELA - SICOOB", balance=Decimal("-1179.29")),
            # Saldo mascarado: precisa voltar como None, nunca zero.
            ErpAccount(id="uuid-3", name="VXZ CONSTRUTORA - INTER", raw_balance="******"),
        ],
        payments=[
            ErpPayment(
                due_date=date(2026, 7, 30),
                status="Em aberto",
                amount=Decimal("40608.17"),
                payee="FORNECEDOR X",
                account_label="MORAIS ENGENHARIA - INTER",
                raw={"venc": "30/07/2026"},
            ),
            ErpPayment(due_date=None, status="Em aberto", amount=None, payee="SEM DATA"),
        ],
    )

    caminho = snapshot_io.save(original, tmp_path)
    assert caminho.name == "2026-07-30.json"

    lido = snapshot_io.load(caminho)
    assert lido == original


def test_dinheiro_vai_para_json_como_string(tmp_path):
    """Float perderia centavos; o snapshot e a fonte de verdade do dia."""
    snap = Snapshot(
        reference_date=date(2026, 7, 30),
        collected_at="",
        accounts=[ErpAccount(id="a", name="X", balance=Decimal("0.10"))],
    )
    dados = snapshot_io.to_dict(snap)
    assert dados["accounts"][0]["balance"] == "0.10"


def test_salvar_duas_vezes_no_mesmo_dia_sobrescreve(tmp_path):
    snap = Snapshot(reference_date=date(2026, 7, 30), collected_at="")
    primeiro = snapshot_io.save(snap, tmp_path)
    segundo = snapshot_io.save(snap, tmp_path)
    assert primeiro == segundo
    assert len(list(tmp_path.glob("*.json"))) == 1
