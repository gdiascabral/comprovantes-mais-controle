# -*- coding: utf-8 -*-
from decimal import Decimal

import pytest
from falsos_leitura_manha import Relogio, Resp, SessaoFalsa

from leitura_manha.transporte import ErroLeitura, Ritmo, TokenOAuth, pedir_json


def _pedir(sessao, ritmo=None, **k):
    return pedir_json(sessao, "GET", "https://banco/x", ritmo=ritmo or Ritmo(0),
                      headers={}, **k)


def test_ritmo_espera_o_que_falta_do_intervalo():
    rel = Relogio()
    r = Ritmo(0.5, relogio=rel, esperar=rel.esperar)
    r.vez()
    rel.t += 0.2
    r.vez()
    r.vez()
    assert rel.esperas == [0.3, 0.5]


def test_numero_vem_em_decimal_nunca_float():
    corpo = _pedir(SessaoFalsa(Resp(200, '{"saldo": 1234.56}')))
    assert corpo["saldo"] == Decimal("1234.56") and isinstance(corpo["saldo"], Decimal)


def test_html_com_200_do_firewall_e_erro():
    with pytest.raises(ErroLeitura, match="não é JSON"):
        _pedir(SessaoFalsa(Resp(200, "<html><title>Request Rejected</title></html>")))


def test_json_que_nao_e_objeto_e_erro():
    with pytest.raises(ErroLeitura, match="objeto"):
        _pedir(SessaoFalsa(Resp(200, "[1, 2]")))


def test_fora_de_2xx_e_erro_com_status():
    with pytest.raises(ErroLeitura) as e:
        _pedir(SessaoFalsa(Resp(500, "pane")))
    assert e.value.status == 500


def test_rede_caida_vira_erro_sem_a_url():
    with pytest.raises(ErroLeitura) as e:
        _pedir(SessaoFalsa(ConnectionError("https://banco/x?numeroContaCorrente=99")))
    assert e.value.status is None and "99" not in str(e.value)


def test_429_espera_e_tenta_uma_vez_so():
    rel = Relogio()
    ritmo = Ritmo(0, relogio=rel, esperar=rel.esperar)
    s = SessaoFalsa(Resp(429, "devagar"), Resp(200, {"ok": 1}))
    assert _pedir(s, ritmo, espera_429=2.0) == {"ok": 1}
    assert rel.esperas == [2.0] and len(s.pedidos) == 2


def test_429_duas_vezes_desiste_sem_terceira_chamada():
    s = SessaoFalsa(Resp(429, "devagar"), Resp(429, "devagar"))
    with pytest.raises(ErroLeitura) as e:
        _pedir(s, Ritmo(0, esperar=lambda _s: None))
    assert e.value.status == 429 and len(s.pedidos) == 2


def _token(sessao, rel=None):
    rel = rel or Relogio()
    return TokenOAuth(sessao, "https://auth/token", {"client_id": "c", "client_secret": "SEGREDO"},
                      user_agent="ua", relogio=rel), rel


def test_token_guardado_ate_60s_antes_de_vencer():
    s = SessaoFalsa(Resp(200, {"access_token": "T1", "expires_in": 3600}),
                    Resp(200, {"access_token": "T2", "expires_in": 3600}))
    tok, rel = _token(s)
    assert tok() == "T1"
    rel.t = 3539
    assert tok() == "T1"
    rel.t = 3541
    assert tok() == "T2"
    metodo, _url, k = s.pedidos[0]
    assert metodo == "POST" and k["data"]["client_secret"] == "SEGREDO"


def test_token_recusado_nao_repete_pedido_nem_mostra_o_segredo():
    s = SessaoFalsa(Resp(401, '{"erro": "client_secret SEGREDO invalido"}'))
    tok, _rel = _token(s)
    for _ in range(3):
        with pytest.raises(ErroLeitura) as e:
            tok()
        assert "SEGREDO" not in str(e.value)
    assert len(s.pedidos) == 1


def test_token_sem_access_token_e_erro():
    tok, _rel = _token(SessaoFalsa(Resp(200, {"token_type": "Bearer"})))
    with pytest.raises(ErroLeitura):
        tok()
