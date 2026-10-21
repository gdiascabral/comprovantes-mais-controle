"""Saldos do ERP sem login HTTP. Dublês; contas fictícias."""
from decimal import Decimal

import pytest

from conciliacao.errors import ErpError
from tela_do_dia import erp_do_dia

CAPTURA = ("https://prod-erp-api.maiscontroleerp.com.br/attachments/v2",
           {"authorization": "Bearer ficticio", "company-id": "c"})
CONTAS = {"items": [{"id": "uuid-alfa", "name": "ALFA LTDA - BANCO", "isActive": True}],
          "hasNextPage": False}
SALDOS = {"uuid-alfa": 1234.56}


class Cfg:
    erp = {}


class ApiDaAba:
    def __init__(self, respostas, capturado=True, garante=True):
        self._req_anexos = CAPTURA if capturado else None
        self.respostas, self.urls, self.garantiu, self._garante = respostas, [], False, garante

    def _fetch_json(self, url, headers):
        self.urls.append((url, headers))
        for pedaco, corpo in self.respostas.items():
            if pedaco in url:
                return corpo
        return {"__erro": 404}

    def garantir_credenciais_anexos(self, log=print):
        self.garantiu = True
        if self._garante:
            self._req_anexos = CAPTURA
        return self._garante


def _nao_loga(*_a, **_k):
    raise AssertionError("login HTTP não pode acontecer")


def test_central_desligado_le_pela_aba_do_app_sem_login():
    api = ApiDaAba({"bank-accounts?": CONTAS, "balances?": SALDOS})
    contas = erp_do_dia.ler_saldos(Cfg(), api, central_ligado=lambda: False, logar=_nao_loga)
    assert [(c.id, c.balance) for c in contas] == [("uuid-alfa", Decimal("1234.56"))]
    assert api.urls and all(h["authorization"] for _u, h in api.urls)


def test_resposta_de_erro_vira_erperror_e_nunca_saldo_zero():
    api = ApiDaAba({"bank-accounts?": {"__erro": 401}})
    with pytest.raises(ErpError, match="401"):
        erp_do_dia.ler_saldos(Cfg(), api, central_ligado=lambda: False, logar=_nao_loga)


def test_sem_captura_pede_a_isca_e_sem_ela_para():
    api = ApiDaAba({"bank-accounts?": CONTAS, "balances?": SALDOS}, capturado=False)
    erp_do_dia.ler_saldos(Cfg(), api, central_ligado=lambda: False, logar=_nao_loga)
    assert api.garantiu
    with pytest.raises(ErpError):
        erp_do_dia.ler_saldos(Cfg(), ApiDaAba({}, capturado=False, garante=False),
                              central_ligado=lambda: False, logar=_nao_loga)


def test_central_ligado_usa_a_sessao_do_porteiro():
    class Sessao:
        def contas(self, *, ativas=True):
            assert ativas
            return ["conta"]
    api = ApiDaAba({})
    assert erp_do_dia.ler_saldos(Cfg(), api, central_ligado=lambda: True,
                                 logar=lambda cfg, log=print: Sessao()) == ["conta"]
    assert api.urls == []


def test_nenhuma_conta_e_erro():
    api = ApiDaAba({"bank-accounts?": {"items": [], "hasNextPage": False}})
    with pytest.raises(ErpError, match="nenhuma conta"):
        erp_do_dia.ler_saldos(Cfg(), api, central_ligado=lambda: False, logar=_nao_loga)
