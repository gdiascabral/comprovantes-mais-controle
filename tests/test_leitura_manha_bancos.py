# -*- coding: utf-8 -*-
from datetime import date

import pytest

from falsos_leitura_manha import Relogio, Resp, SessaoFalsa

from leitura_manha import bancos as bc
from leitura_manha.transporte import Ritmo
from pagamento_api.sicoob import USER_AGENT


def _sicoob(*resps):
    s = SessaoFalsa(*resps)
    return s, bc.ContaCorrenteSicoob(s, bc.SICOOB_SANDBOX, "CID", lambda: "TOK", ritmo=Ritmo(0))


def test_saldo_sicoob_pede_a_conta_com_o_user_agent_proprio():
    s, c = _sicoob(Resp(200, {"saldo": 10}))
    assert c.saldo(1234) == {"saldo": 10}
    metodo, url, k = s.pedidos[0]
    assert (metodo, url) == ("GET", bc.SICOOB_SANDBOX + "/saldo")
    assert k["params"] == {"numeroContaCorrente": 1234}
    assert k["headers"]["User-Agent"] == USER_AGENT
    assert k["headers"]["client_id"] == "CID" and k["headers"]["Authorization"] == "Bearer TOK"


def test_extrato_sicoob_de_uma_faixa_do_mes():
    s, c = _sicoob(Resp(200, {"transacoes": []}))
    c.extrato(1234, date(2026, 1, 5), date(2026, 1, 11))
    _m, url, k = s.pedidos[0]
    assert url == bc.SICOOB_SANDBOX + "/extrato/1/2026"
    assert k["params"] == {"numeroContaCorrente": 1234, "diaInicial": 5, "diaFinal": 11}


def test_extrato_sicoob_recusa_faixa_que_cruza_o_mes_sem_pedir():
    s, c = _sicoob()
    with pytest.raises(ValueError):
        c.extrato(1234, date(2026, 11, 28), date(2026, 12, 2))
    with pytest.raises(ValueError):
        c.extrato(1234, date(2026, 11, 28), date(2026, 11, 27))
    assert s.pedidos == []


def test_sicoob_respeita_2_por_segundo_entre_empresas():
    rel = Relogio()
    ritmo = Ritmo(bc.INTERVALO_SICOOB, relogio=rel, esperar=rel.esperar)
    s = SessaoFalsa(Resp(200, {}), Resp(200, {}), Resp(200, {}))
    a = bc.ContaCorrenteSicoob(s, bc.SICOOB_SANDBOX, "A", lambda: "x", ritmo=ritmo)
    b = bc.ContaCorrenteSicoob(s, bc.SICOOB_SANDBOX, "B", lambda: "y", ritmo=ritmo)
    a.saldo(1)
    b.saldo(2)
    a.saldo(3)
    assert rel.esperas == [bc.INTERVALO_SICOOB, bc.INTERVALO_SICOOB]
    assert bc.INTERVALO_SICOOB >= 0.5


def test_inter_extrato_e_saldo_com_conta_corrente_so_quando_configurada():
    s = SessaoFalsa(Resp(200, {"disponivel": 1}), Resp(200, {"transacoes": []}))
    i = bc.BankingInter(s, bc.INTER_PRODUCAO, lambda: "T", ritmo=Ritmo(0), conta_corrente="123")
    i.saldo()
    i.extrato(date(2026, 11, 20), date(2026, 11, 26))
    (_m1, u1, k1), (_m2, u2, k2) = s.pedidos
    assert u1 == bc.INTER_PRODUCAO + "/banking/v2/saldo" and k1["headers"]["x-conta-corrente"] == "123"
    assert u2 == bc.INTER_PRODUCAO + "/banking/v2/extrato"
    assert k2["params"] == {"dataInicio": "2026-11-20", "dataFim": "2026-11-26"}
    s2 = SessaoFalsa(Resp(200, {}))
    bc.BankingInter(s2, bc.INTER_PRODUCAO, lambda: "T", ritmo=Ritmo(0)).saldo()
    assert "x-conta-corrente" not in s2.pedidos[0][2]["headers"]


def test_inter_no_maximo_10_por_minuto():
    assert 60 / bc.INTERVALO_INTER <= 10 and 60 / bc.INTERVALO_TOKEN_INTER <= 5


def test_tokens_pedem_so_leitura():
    s = SessaoFalsa(Resp(200, {"access_token": "A"}), Resp(200, {"access_token": "B"}))
    bc.token_sicoob(s, "CID", ("c.pem", "k.pem"))()
    bc.token_inter(s, bc.INTER_PRODUCAO, "CI", "CS", ("c.pem", "k.pem"), Ritmo(0))()
    (_m, u1, k1), (_m2, u2, k2) = s.pedidos
    assert u1 == bc.SICOOB_TOKEN and k1["data"]["scope"] == "cco_consulta"
    assert k1["cert"] == ("c.pem", "k.pem")
    assert u2 == bc.INTER_PRODUCAO + "/oauth/v2/token" and k2["data"]["scope"] == "extrato.read"
    assert k2["data"]["grant_type"] == "client_credentials"


def test_429_no_token_inter_dorme_61s_antes_da_segunda_tentativa():
    rel = Relogio()
    ritmo = Ritmo(0, relogio=rel, esperar=rel.esperar)
    s = SessaoFalsa(Resp(429, "devagar"), Resp(200, {"access_token": "T"}))
    tok = bc.token_inter(s, bc.INTER_PRODUCAO, "CI", "CS", ("c.pem", "k.pem"), ritmo)
    assert tok() == "T"
    assert rel.esperas == [61.0] and len(s.pedidos) == 2
