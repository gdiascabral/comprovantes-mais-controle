# -*- coding: utf-8 -*-
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from falsos_leitura_manha import Resp, SessaoFalsa
from test_leitura_manha_leitura import _cfg, _tudo_bom

from conciliacao.errors import ErpError
from conciliacao.models import ErpAccount
from leitura_manha import config as cf
from leitura_manha import rodar

HORA = datetime(2026, 11, 27, 10, 30, tzinfo=timezone.utc)


def test_erp_desligado_nao_chama_ler_saldos():
    chamou = []
    with pytest.raises(ErpError, match="porteiro"):
        rodar.ler_erp_pelo_porteiro(central=lambda: False,
                                    ler_saldos=lambda *a, **k: chamou.append(1))
    assert chamou == []


def test_erp_ligado_passa_um_central_que_nunca_diz_desligado():
    vistos = []

    def ler_saldos(config, api, *, central_ligado, log):
        vistos.append((api, config.erp["api_base"].startswith("https://"), central_ligado()))
        return [ErpAccount("1", "A1 - SICOOB", balance=Decimal("1.00"))]
    estado = iter([True, False])
    with pytest.raises(ErpError):   # o porteiro caiu entre a 1ª pergunta e a de dentro
        rodar.ler_erp_pelo_porteiro(central=lambda: next(estado), ler_saldos=ler_saldos)
    contas = rodar.ler_erp_pelo_porteiro(central=lambda: True, ler_saldos=ler_saldos)
    assert contas[0].name == "A1 - SICOOB" and vistos == [(None, True, True)]


class NuvemFalsa:
    def __init__(self, em_aberto=(), cair=None):
        self._em_aberto, self.cair, self.gravou = list(em_aberto), cair, None

    def em_aberto(self, token):
        assert token == "TOK"
        return self._em_aberto

    def gravar(self, token, rodada, ontem, saldos, extratos, marcas):
        if self.cair:
            raise self.cair
        self.gravou = (rodada, ontem, saldos, extratos, marcas)
        return {"saldo_lido": len(saldos)}


def _entrar(email, senha):
    assert (email, senha) == ("r@e.com", "s")
    return {"access_token": "TOK"}


def test_rodada_grava_bancos_erp_e_pre_marcas():
    nuvem = NuvemFalsa([{"id": 1, "dia": "2026-11-26", "conta": "A1 - SICOOB", "valor": "150.00",
                         "descricao": "OBRA X LT 10", "foto": {}}])
    log = []
    r = rodar.rodada(_cfg(), fabrica=_tudo_bom(), entrar=_entrar, nuvem=nuvem,
                     ler_erp=lambda: [ErpAccount("1", "A1 - SICOOB", balance=Decimal("90.00"))],
                     agora=lambda: HORA, log=log.append)
    assert r == 0
    _rodada, ontem, saldos, _extratos, marcas = nuvem.gravou
    assert ontem == date(2026, 11, 26)
    assert {(s.fonte, s.conta) for s in saldos} >= {("erp", "A1 - SICOOB"), ("sicoob", "A1 - SICOOB")}
    assert [m.agendado_id for m in marcas if m.prova] == [1]
    assert any(linha.startswith("gravado:") for linha in log)


def test_nuvem_fora_devolve_1_e_o_log_ainda_tem_os_saldos():
    log = []
    r = rodar.rodada(_cfg(), fabrica=_tudo_bom(), entrar=_entrar,
                     nuvem=NuvemFalsa(cair=RuntimeError("caiu")), ler_erp=lambda: [],
                     agora=lambda: HORA, log=log.append)
    assert r == 1 and any("NÃO GRAVOU" in linha for linha in log)
    assert any("saldo sicoob A1 - SICOOB: 100.00" in linha for linha in log)


def test_rodada_de_verdade_recusa_sandbox():
    cfg = cf.de_dict({"ambiente": "sandbox", "pasta": "p", "empresas": [
        {"nome": "E", "sicoob": {"client_id": "C", "token_fixo": "T"},
         "contas": [{"banco": "sicoob", "numero": 1, "conta_erp": "X"}]}]})
    with pytest.raises(SystemExit, match="producao"):
        rodar.rodada(cfg)


def test_ensaio_sandbox_le_o_sandbox_e_nao_grava():
    lorem = {"transacoes": [{"tipo": "elit magna", "valor": "ullamco", "data": "commodo"}]}
    s = SessaoFalsa(Resp(200, '{"saldo": 436196.58701458573}'), Resp(200, lorem))
    le = rodar.ensaio_sandbox({"client_id": "C", "token_fixo": "T"}, sessao=s,
                              agora=lambda: HORA, log=lambda _m: None)
    (_m1, u1, k1), (_m2, u2, _k2) = s.pedidos
    assert u1.startswith("https://sandbox.sicoob.com.br/") and u2.endswith("/extrato/11/2026")
    assert k1["headers"]["Authorization"] == "Bearer T"
    assert le.saldos[0].valor is None and le.extratos[0].ilegiveis == 1 and le.lidas == set()


def _pasta_inter(tmp_path):
    for nome, texto in (("client_id.txt", "﻿CID-FALSO\n"), ("client_secret.txt", "SEGREDO-FALSO"),
                        ("Sandbox_InterAPI_Certificado.crt", "x"), ("Sandbox_InterAPI_Chave.key", "y")):
        (tmp_path / nome).write_text(texto, encoding="utf-8")
    return tmp_path


def test_credencial_do_inter_lida_da_pasta_sem_bom(tmp_path):
    c = rodar.credencial_inter_da_pasta(_pasta_inter(tmp_path))
    assert c["client_id"] == "CID-FALSO" and c["client_secret"] == "SEGREDO-FALSO"
    assert c["cert"][0].endswith(".crt") and c["cert"][1].endswith(".key")


def test_ensaio_inter_le_token_saldo_e_extrato_e_nao_mostra_o_token(tmp_path, monkeypatch):
    monkeypatch.setattr(rodar.bc, "INTERVALO_INTER", 0)    # o teste não espera 6,5 s de verdade
    s = SessaoFalsa(Resp(200, {"access_token": "TOKEN-SECRETO", "expires_in": 3600}),
                    Resp(200, '{"disponivel": 100.5, "limite": 0}'),
                    Resp(200, {"transacoes": [{"dataEntrada": "2023-01-26", "tipoTransacao": None,
                                               "tipoOperacao": "D", "valor": "33.33"}]}))
    log = []
    le = rodar.ensaio_sandbox({"inter_chaves": str(_pasta_inter(tmp_path))}, sessao=s,
                              agora=lambda: HORA, log=log.append)
    (_m0, u0, k0), (_m1, u1, k1), (_m2, u2, k2) = s.pedidos
    assert u0 == "https://cdpj-sandbox.partners.uatinter.co/oauth/v2/token"
    assert k0["cert"][0].endswith(".crt") and k0["data"]["client_secret"] == "SEGREDO-FALSO"
    assert u1.endswith("/banking/v2/saldo") and k1["headers"]["Authorization"] == "Bearer TOKEN-SECRETO"
    assert le.saldos[0].valor == Decimal("100.50") and le.extratos[0].fora_do_dia == 1
    assert le.lidas == {"ENSAIO - INTER"}
    assert not any("TOKEN-SECRETO" in linha or "SEGREDO" in linha for linha in log)


def test_ensaio_sem_banco_nenhum_e_config_invalida():
    with pytest.raises(cf.ConfigInvalida):
        rodar.ensaio_sandbox({}, log=lambda _m: None)


def test_argumentos():
    assert rodar._argumentos(["--config", "a.json"]) == ("a.json", False)
    assert rodar._argumentos(["--config=a.json", "--ensaio-sandbox"]) == ("a.json", True)
    with pytest.raises(SystemExit):
        rodar._argumentos(["--pagar"])
    assert rodar.main([]) == 2


def test_main_com_arquivo_ruim_sai_2_sem_rodar(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"ambiente": "producao"}', encoding="utf-8")
    assert rodar.main(["--config", str(p)]) == 2


class NuvemSemEmAberto(NuvemFalsa):
    def em_aberto(self, token):
        raise RuntimeError("PostgREST fora")


def test_falha_ao_ler_em_aberto_nao_perde_saldos_e_sai_1():
    nuvem, log = NuvemSemEmAberto(), []
    r = rodar.rodada(_cfg(), fabrica=_tudo_bom(), entrar=_entrar, nuvem=nuvem,
                     ler_erp=lambda: [], agora=lambda: HORA, log=log.append)
    assert r == 1
    _rodada, _ontem, saldos, extratos, marcas = nuvem.gravou
    assert saldos and extratos and marcas == []
    assert any("pré-marcas puladas" in linha and "RuntimeError" in linha for linha in log)
    assert not any("PostgREST fora" in linha for linha in log if "puladas" in linha)


def test_gravacao_parcial_aparece_no_log():
    from leitura_manha import nuvem_leitura as nl
    log = []
    cai = nl.GravacaoParcial({"saldo_lido": 12}, "extrato_lido", RuntimeError("x"))
    r = rodar.rodada(_cfg(), fabrica=_tudo_bom(), entrar=_entrar,
                     nuvem=NuvemFalsa(cair=cai), ler_erp=lambda: [],
                     agora=lambda: HORA, log=log.append)
    assert r == 1 and any("gravou saldo_lido 12" in linha for linha in log)
