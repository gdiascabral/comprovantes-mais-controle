# -*- coding: utf-8 -*-
"""`MCApi.anexos_da_venda`: venda -> recebimento -> anexos do lançamento.

Falha de leitura sobe como erro: "vazio" quer dizer que a venda não tem anexo,
e o pipeline diz coisas diferentes nos dois casos. Nenhuma rede aqui.
"""
import pytest

pytest.importorskip("playwright")
from anexar.mc_api import MCApi  # noqa: E402

LEGACY = "https://legado.invalid/maiscontrole/services/payable-installments/paginated-result?x=1"
NOVA = "https://nova.invalid/attachments/v2"


def _api(respostas):
    api = object.__new__(MCApi)
    api._req_pagos = (LEGACY, {"h": "legado"})
    api._req_anexos = (NOVA, {"h": "nova"})
    api.pedidos = []

    def fetch(url, headers):
        api.pedidos.append((url, headers))
        return respostas[len(api.pedidos) - 1]

    api._fetch_json = fetch
    return api


def test_le_a_venda_e_depois_os_anexos_do_recebimento():
    anexos = [{"id": "a1", "filename": "CONTRATO"}]
    api = _api([{"tradeReceivable": {"id": "tr-1"}}, anexos])
    assert api.anexos_da_venda("venda-1") == anexos
    assert api.pedidos == [
        ("https://legado.invalid/maiscontrole/services/sales/venda-1", {"h": "legado"}),
        (f"{NOVA}?entityIds=tr-1&entityOrigin=TRADE_RECEIVABLE_READJUSTED", {"h": "nova"}),
    ]


def test_lancamento_sem_anexo_devolve_lista_vazia():
    assert _api([{"tradeReceivable": {"id": "tr-1"}}, []]).anexos_da_venda("v") == []


@pytest.mark.parametrize("respostas", [
    [{"__erro": 500}],
    [{"tradeReceivable": {}}],
    [{"tradeReceivable": {"id": "tr-1"}}, {"__erro": 403}],
    [{"tradeReceivable": {"id": "tr-1"}}, None],
])
def test_falha_na_leitura_sobe_como_erro_e_nao_como_vazio(respostas):
    with pytest.raises(RuntimeError):
        _api(respostas).anexos_da_venda("v")
