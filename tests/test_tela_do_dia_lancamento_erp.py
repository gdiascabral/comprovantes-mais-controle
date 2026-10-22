"""O link do lançamento: id, e a leitura pela sessão do Chrome do app (dublê)."""
from datetime import date
from decimal import Decimal as D

import pytest

from tela_do_dia import lancamento_do_erp as le

ITEM = {"id": "L9", "tradePayableId": "T9", "paidTo": "Fornecedor Modelo Ltda", "remainingValue": 80000.0,
        "plannedDate": "2026-09-29", "tradePayableAccount": {"name": "CONTA EXEMPLO - SICOOB"},
        "documentNumber": "1234", "description": "compra de material",
        "costCentreDetails": [{"workName": "OBRA MODELO"}], "paid": False}


def test_id_do_link_aceita_o_link_e_o_id_cru():
    assert le.id_do_link("https://acessar.maiscontroleerp.com.br/#/payable-installments/abc-123") == "abc-123"
    assert le.id_do_link("  abc-123 ") == "abc-123"
    assert le.id_do_link("https://outro.invalid/x?y=1") == ""
    assert le.id_do_link("") == ""


def test_do_item_le_as_pecas_do_lancamento():
    lido = le.do_item(ITEM, {"purchaseOrder": {"number": "55"}})
    assert (lido.favorecido, lido.centro_custo, lido.nf, lido.oc) == ("Fornecedor Modelo Ltda", "OBRA MODELO", "1234", "55")
    assert lido.em_aberto == D("80000.00") and lido.vencimento == date(2026, 9, 29)
    assert lido.conta == "CONTA EXEMPLO - SICOOB" and not lido.pago


class _Api:
    _req_pagos = ("u", {})

    def __init__(self, overview=None, lista=()):
        self.overview, self.lista, self.pedidos = overview, list(lista), []

    def listar_overviews(self, ids, log=print):
        return {ids[0]: self.overview} if self.overview else {}

    def listar_a_pagar(self, ini, fim, log=print):
        self.pedidos.append((ini, fim))
        return self.lista


def test_le_fora_do_periodo_pela_data_do_detalhe():
    api = _Api(overview={"plannedDate": "2026-09-29", "documentNumber": "1234"}, lista=[ITEM])
    lido = le.ler(api, "L9", conhecidos=[])
    assert api.pedidos == [("2026-09-29", "2026-09-29")] and lido.em_aberto == D("80000.00")
    assert lido.favorecido == "Fornecedor Modelo Ltda" and lido.centro_custo == "OBRA MODELO"


def test_conhecido_nao_pede_a_lista_do_dia():
    api = _Api(overview={"documentNumber": "1234"})
    lido = le.ler(api, "L9", conhecidos=[ITEM])
    assert api.pedidos == [] and lido.favorecido == "Fornecedor Modelo Ltda"


def test_sem_o_item_avisa_e_nao_inventa_valor():
    lido = le.ler(_Api(overview={"documentNumber": "1234"}), "L9")
    assert lido.em_aberto is None and any("confira" in a for a in lido.avisos)
    assert lido.favorecido == "" and lido.centro_custo == "" and lido.nf == "1234"


def test_so_detalhe_usa_o_pendente_e_ignora_paidto_vazio():
    # forma medida em 21/10/2026: paidTo vem {}, o valor em aberto é pendingValue
    det = {"plannedValue": 100.0, "plannedDate": "2026-09-29", "pendingValue": 40.0,
           "sumOfPaidValues": 60.0, "paid": False, "markedAsPaid": False, "paidTo": {}}
    lido = le.ler(_Api(overview=det, lista=[]), "L9")
    assert lido.em_aberto == D("40.00") and lido.favorecido == "" and not lido.pago


def test_so_detalhe_sem_pendente_calcula_pelo_previsto_menos_pago():
    det = {"plannedValue": 100.0, "sumOfPaidValues": 60.0}
    assert le.do_item({**det, "id": "L9"}, det).em_aberto == D("40.00")
    assert le.do_item({"id": "L9", "plannedValue": 100.0}, None).em_aberto is None


def test_titulo_pago_vem_marcado():
    assert le.do_item({**ITEM, "paid": True, "remainingValue": 0.0}, None).pago is True
    assert le.do_item({"id": "L9", "markedAsPaid": True}, None).pago is True


def test_lancamento_que_nao_existe_levanta():
    with pytest.raises(LookupError):
        le.ler(_Api(), "L9")
    with pytest.raises(LookupError):
        le.ler(_Api(), "")
