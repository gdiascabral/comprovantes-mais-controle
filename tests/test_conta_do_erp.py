# -*- coding: utf-8 -*-
"""Extrair conta crua do ERP num lugar só."""

from decimal import Decimal

from conciliacao.erp.api import conta_do_erp

CRU = {"id": "u-1", "name": "CONTA NOVA FICTICIA 01", "isActive": True,
       "bankCode": "756", "agency": "1234", "account": "90001",
       "accountDigit": "1"}


def test_conta_crua_vira_erp_account_sem_saldo():
    c = conta_do_erp(CRU)
    assert (c.id, c.name, c.is_active, c.bank_code, c.agency,
            c.account_number) == ("u-1", "CONTA NOVA FICTICIA 01", True,
                                  "756", "1234", "90001-1")
    assert c.balance is None and c.raw_balance is None


def test_com_saldo_usa_o_mapa_pelo_id():
    c = conta_do_erp(CRU, {"u-1": Decimal("10.50")})
    assert c.balance == Decimal("10.50")
    assert c.raw_balance == "10.50"
