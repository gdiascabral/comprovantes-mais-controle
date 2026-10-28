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


def test_central_some_entre_as_leituras_nao_faz_login_http(monkeypatch):
    """Janela de corrida: ligado na 1a leitura, desligado na 2a."""
    from erp import sessao as erp_sessao
    leituras = iter([True, False, False])
    monkeypatch.setattr(erp_sessao, "central_ligado", lambda nome="principal": next(leituras))
    monkeypatch.setattr(erp_sessao, "_pedir", _nao_loga)
    monkeypatch.setattr(erp_sessao.Sessao, "de_login", _nao_loga)
    api = ApiDaAba({})
    with pytest.raises(ErpError):
        erp_do_dia.ler_saldos(Cfg(), api)
    assert api.urls == []


def test_excecao_do_fetch_vira_erperror():
    class Quebra(ApiDaAba):
        def _fetch_json(self, url, headers):
            raise RuntimeError("aba fechada")
    with pytest.raises(ErpError) as e:
        erp_do_dia.ler_saldos(Cfg(), Quebra({}), central_ligado=lambda: False,
                              logar=_nao_loga)
    assert isinstance(e.value.__cause__, RuntimeError)


def test_acessos_estragado_propaga_sem_tocar_api_nem_login():
    from erp.sessao import ErpErro

    def estragado():
        raise ErpErro("acessos.json estragado")
    api = ApiDaAba({})
    with pytest.raises(ErpErro):
        erp_do_dia.ler_saldos(Cfg(), api, central_ligado=estragado, logar=_nao_loga)
    assert api.urls == [] and not api.garantiu


def test_conta_sem_saldo_no_lote_sai_none_nunca_zero():
    api = ApiDaAba({"bank-accounts?": CONTAS, "balances?": {}})
    contas = erp_do_dia.ler_saldos(Cfg(), api, central_ligado=lambda: False, logar=_nao_loga)
    assert contas[0].balance is None


# ------------------------------- prova ao vivo 22/10: login na mesma rodada
class _SessaoQue:
    def __init__(self, erro=None):
        self.erro = erro
        self._sessao = object()          # a SessaoPelaPagina por baixo

    def contas(self, *, ativas=True):
        if self.erro:
            raise self.erro
        return ["conta"]


def test_sessao_central_velha_e_esquecida_e_le_de_novo_uma_vez():
    """Quando o Chrome do app precisou logar na mesma rodada, a sessão central
    guardada estava velha e o "Não consegui ler o dia" aparecia (22/10)."""
    from erp.sessao import ErpErro
    velha = _SessaoQue(ErpErro("401 do prod-erp-api"))
    sessoes = iter([velha, _SessaoQue()])
    esquecidas, registro, diagnostico = [], [], []
    contas = erp_do_dia.ler_saldos(
        Cfg(), ApiDaAba({}), central_ligado=lambda: True,
        logar=lambda cfg, log=print: next(sessoes),
        esquecer=lambda nome, sessao: esquecidas.append((nome, sessao)), log=registro.append,
        diag=diagnostico.append)
    assert contas == ["conta"] and esquecidas == [("principal", velha._sessao)]
    # 28/10: o Registro diz o que houve em português; o erro cru vai ao diagnóstico.
    assert registro == ["  Saldos do ERP: a sessão do ERP tinha caído; entrei de "
                        "novo e li os saldos."]
    assert any("401 do prod-erp-api" in d for d in diagnostico)


def test_relogin_dentro_da_sessao_central_e_avisado_no_registro():
    """A `SessaoPelaPagina` entrou sozinha (a página estava no login): a
    leitura passa de primeira e o Registro conta que a sessão tinha caído."""
    class _Pagina:
        def __init__(self):
            self.vezes = [True]

        def reentrou(self):
            return self.vezes.pop(0) if self.vezes else False

    sessao = _SessaoQue()
    sessao._sessao = _Pagina()
    registro = []
    contas = erp_do_dia.ler_saldos(
        Cfg(), ApiDaAba({}), central_ligado=lambda: True,
        logar=lambda cfg, log=print: sessao,
        esquecer=lambda n, s: None, log=registro.append, diag=lambda m: None)
    assert contas == ["conta"]
    assert registro == ["  Saldos do ERP: a sessão do ERP tinha caído; entrei de "
                        "novo e li os saldos."]


def test_sem_relogin_o_registro_fica_quieto():
    registro = []
    erp_do_dia.ler_saldos(Cfg(), ApiDaAba({}), central_ligado=lambda: True,
                          logar=lambda cfg, log=print: _SessaoQue(),
                          esquecer=lambda n, s: None, log=registro.append,
                          diag=lambda m: None)
    assert registro == []


def test_sessao_central_que_falha_duas_vezes_sobe_o_motivo_real():
    sessoes = iter([_SessaoQue(ErpError("primeira")), _SessaoQue(ErpError("token recusado"))])
    esquecidas = []
    with pytest.raises(ErpError, match="token recusado"):
        erp_do_dia.ler_saldos(Cfg(), ApiDaAba({}), central_ligado=lambda: True,
                              logar=lambda cfg, log=print: next(sessoes),
                              esquecer=lambda n, s: esquecidas.append(n), log=lambda m: None,
                              diag=lambda m: None)
    assert esquecidas == ["principal"]           # só UMA nova tentativa


def test_erro_que_nao_e_do_erp_nao_tenta_de_novo():
    sessoes = iter([_SessaoQue(ValueError("bug")), _SessaoQue()])
    esquecidas = []
    with pytest.raises(ValueError):
        erp_do_dia.ler_saldos(Cfg(), ApiDaAba({}), central_ligado=lambda: True,
                              logar=lambda cfg, log=print: next(sessoes),
                              esquecer=lambda n, s: esquecidas.append(n), log=lambda m: None,
                              diag=lambda m: None)
    assert esquecidas == []


def test_porteiro_sem_token_leva_a_sessao_na_excecao(monkeypatch):
    """O `_logar_pela_pagina` que recusa diz QUAL sessão guardada falhou."""
    from erp import sessao as erp_sessao
    sem_token = type("S", (), {"jwt_token": "", "company_id": "", "usuario": "",
                               "empresa": None})()
    monkeypatch.setattr(erp_sessao.Sessao, "logar", classmethod(lambda cls, e, s: sem_token))
    with pytest.raises(ErpError) as e:
        erp_do_dia._logar_pela_pagina(Cfg())
    assert e.value.sessao is sem_token


def test_esquecer_central_fecha_so_a_que_falhou(monkeypatch):
    from erp import sessao as erp_sessao
    fechadas = []

    def nova():
        return type("S", (), {"fechar": lambda self: fechadas.append(self)})()
    velha, recriada = nova(), nova()
    # Outra aba (Conciliação) já recriou a sessão: a que falhou não está mais
    # guardada, e a nova NÃO pode cair.
    monkeypatch.setattr(erp_sessao, "_CENTRAIS", {"principal": recriada})
    erp_sessao.esquecer_central("principal", velha)
    assert erp_sessao._CENTRAIS == {"principal": recriada} and fechadas == []
    erp_sessao.esquecer_central("principal", None)       # sem saber qual: nada
    assert erp_sessao._CENTRAIS == {"principal": recriada}
    erp_sessao.esquecer_central("principal", recriada)
    assert erp_sessao._CENTRAIS == {} and fechadas == [recriada]
