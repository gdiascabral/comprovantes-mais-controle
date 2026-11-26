# -*- coding: utf-8 -*-
"""O cliente monta o pedido que a documentação do Sicoob pede. Sessão falsa: nenhuma rede."""
import json
from decimal import Decimal

import pytest

from pagamento_api import sicoob as sc


class Resposta:
    def __init__(self, status, corpo):
        self.status_code, self.text = status, json.dumps(corpo)


class Sessao:
    def __init__(self, status=200, corpo=None, erro=None):
        self.status, self.corpo, self.erro = status, corpo or {}, erro
        self.pedidos = []

    def request(self, metodo, url, **k):
        self.pedidos.append((metodo, url, k))
        if self.erro:
            raise self.erro
        return Resposta(self.status, self.corpo)


CONTA = sc.ContaApi(4342, 1234569, 1)


def _cliente(sessao):
    return sc.Sicoob(sessao, sc.SANDBOX, "cid", lambda: "tok", cert=("c.pem", "k.pem"))


def test_cabecalhos_certificado_e_endereco():
    s = Sessao(corpo={"endToEndId": "E1"})
    _cliente(s).pix_iniciar("a@b.com")
    metodo, url, k = s.pedidos[0]
    assert (metodo, url) == ("POST", sc.SANDBOX.pix + "/pagamentos")
    assert k["headers"]["Authorization"] == "Bearer tok" and k["headers"]["client_id"] == "cid"
    assert k["cert"] == ("c.pem", "k.pem")
    assert json.loads(k["data"]) == {"chave": "a@b.com"}


def test_confirmar_pix_leva_valor_com_virgula_e_descricao():
    s = Sessao(corpo={"estado": "REALIZADO"})
    _cliente(s).pix_confirmar("E1", Decimal("1234.5"), "OBRA X NF 1")
    corpo = json.loads(s.pedidos[0][2]["data"])
    assert corpo["valor"] == "1234,50" and corpo["descricao"] == "OBRA X NF 1"


def test_pagar_boleto_leva_a_chave_de_idempotencia_e_a_conta():
    s = Sessao(corpo={"resultado": {"idPagamento": 9}})
    chave = sc.chave_de_idempotencia(CONTA, "u-1")
    r = _cliente(s).boleto_pagar("3" * 44, CONTA, {"identificadorConsulta": "h"},
                                 Decimal("152.30"), "DESC", chave, "2026-11-27")
    _, url, k = s.pedidos[0]
    assert url == sc.SANDBOX.boleto + "/boletos/pagamentos/" + "3" * 44
    assert k["headers"]["x-idempotency-key"] == "4342-1234569-u-1"
    corpo = json.loads(k["data"])
    assert corpo["valorBoleto"] == 152.3 and corpo["identificadorConsulta"] == "h"
    assert corpo["debtorAccount"] == {"issuer": 4342, "number": 1234569, "accountType": 0, "personType": 1}
    assert r == {"idPagamento": 9}


def test_consultar_boleto_manda_a_conta():
    s = Sessao(corpo={"resultado": {"valorPagamento": 1.0}})
    assert _cliente(s).boleto_consultar("3" * 44, CONTA) == {"valorPagamento": 1.0}
    assert s.pedidos[0][2]["params"] == {"numeroConta": 1234569}


def test_fora_de_2xx_e_sem_rede_viram_erro():
    with pytest.raises(sc.ErroSicoob) as e:
        _cliente(Sessao(status=400, corpo={"mensagens": []})).pix_consultar("E1")
    assert e.value.status == 400
    with pytest.raises(sc.ErroSicoob) as e:
        _cliente(Sessao(erro=TimeoutError("x"))).pix_consultar("E1")
    assert e.value.status is None


def test_producao_usa_os_enderecos_de_producao():
    assert sc.PRODUCAO.boleto == "https://api.sicoob.com.br/pagamentos/v3"
    assert sc.PRODUCAO.pix == "https://api.sicoob.com.br/pix-pagamentos/v2"


class RespostaCrua:
    def __init__(self, status, texto):
        self.status_code, self.text = status, texto


def test_200_com_html_do_firewall_e_erro_e_nao_sucesso():
    class S(Sessao):
        def request(self, metodo, url, **k):
            self.pedidos.append((metodo, url, k))
            return RespostaCrua(200, "<html><head><title>Request Rejected</title></head></html>")
    with pytest.raises(sc.ErroSicoob) as e:
        _cliente(S()).pix_iniciar("a@b.com")
    assert e.value.status == 200 and "não é JSON" in str(e.value)


@pytest.mark.parametrize("chamar", [
    lambda c: c.pix_confirmar("E1", Decimal("1"), "D"),
    lambda c: c.pix_qrcode("000201", Decimal("1"), ""),
    lambda c: c.boleto_pagar("3" * 44, CONTA, {}, Decimal("1"), "D", "k", "2026-11-27"),
    lambda c: c.convenio_pagar("8" * 44, CONTA, Decimal("1"), "2026-11-27", 1),
])
def test_pagamento_com_2xx_vazio_e_erro_e_nao_sucesso(chamar):
    with pytest.raises(sc.ErroSicoob) as e:
        chamar(_cliente(Sessao(corpo={})))
    assert e.value.status == 200


def test_json_que_nao_e_objeto_e_erro():
    class S(Sessao):
        def request(self, metodo, url, **k):
            return RespostaCrua(200, "[1, 2]")
    with pytest.raises(sc.ErroSicoob):
        _cliente(S()).pix_consultar("E1")


def test_valores_do_banco_chegam_em_decimal():
    r = _cliente(Sessao(corpo={"resultado": {"valorPagamento": 152.3}})).boleto_consultar("3" * 44, CONTA)
    assert r["valorPagamento"] == Decimal("152.3") and isinstance(r["valorPagamento"], Decimal)


def test_qrcode_e_convenio_montam_o_pedido_da_documentacao():
    s = Sessao(corpo={"estado": "REALIZADO"})
    _cliente(s).pix_qrcode("000201X", Decimal("10"), "11222333000181")
    corpo = json.loads(s.pedidos[0][2]["data"])
    assert corpo["valor"] == "10.00" and corpo["destino"] == {"cpfCnpj": "11222333000181"}
    s = Sessao(corpo={"resultado": {"valorTotal": 1.0}})
    _cliente(s).convenio_consultar("8" * 44, "2026-11-27")
    assert s.pedidos[0][2]["params"] == {"dataPagamento": "2026-11-27"}


def test_identificacao_fixa_do_cliente():
    s = Sessao(corpo={})
    _cliente(s).pix_consultar("E1")
    assert s.pedidos[0][2]["headers"]["User-Agent"] == sc.USER_AGENT
