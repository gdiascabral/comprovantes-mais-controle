# -*- coding: utf-8 -*-
"""Pedidos ao ERP pela aba do Chrome central. Sem navegador: a aba é dublê."""
import threading

import pytest

from erp import hosts
from erp.sessao import ErpErro, SessaoRecusada
from erp.sessao_pagina import SessaoPelaPagina

LEG = f"https://{hosts.HOST_LEGACY}"
PROD = f"https://{hosts.HOST_ERP_API}"


class _Req:
    def __init__(self, url, headers):
        self.url, self.headers = url, headers


class _PaginaFalsa:
    """Dispara os requests da tela quando navega/recarrega; responde fetch."""
    def __init__(self, respostas=None, logada=True):
        self.ouvintes, self.respostas = [], list(respostas or [])
        self.logada, self.recargas, self.threads = logada, 0, set()
        self.token = 1

    def on(self, evento, fn):
        assert evento == "request"
        self.ouvintes.append(fn)

    def _tela(self):
        if not self.logada:
            return
        for fn in self.ouvintes:
            fn(_Req(f"{LEG}/maiscontrole/services/x", {
                "authorization": f"Bearer acc{self.token}", "company-id": "emp",
                "user-id": "u1", "organization-unit-id": "o1", "accept": "x"}))
            fn(_Req(f"{PROD}/y", {"authorization": f"Bearer jwt{self.token}",
                                  "company-id": "emp"}))
            fn(_Req("https://api-data-event.exemplo/z", {"authorization": "Bearer tele"}))

    def goto(self, url, **kw):
        self.threads.add(threading.get_ident())
        self._tela()

    def reload(self, **kw):
        self.recargas += 1
        self.token += 1
        self._tela()

    def wait_for_timeout(self, ms):
        self.threads.add(threading.get_ident())

    def evaluate(self, js, args):
        self.threads.add(threading.get_ident())
        r = self.respostas.pop(0) if self.respostas else {"ok": True}
        return r(args) if callable(r) else r


class _AbaFalsa:
    def __init__(self, pagina):
        self.page, self.fechou = pagina, False
    def __enter__(self): return self
    def __exit__(self, *e):
        self.fechou = True
        return False


def _sessao(pagina, **kw):
    aba = _AbaFalsa(pagina)
    s = SessaoPelaPagina.do_acesso("principal", fabrica_aba=lambda: aba,
                                   espera_captura=kw.pop("espera", 2.0))
    return s, aba


def test_captura_os_dois_hosts_e_ignora_telemetria():
    s, _ = _sessao(_PaginaFalsa())
    try:
        assert s.access_token == "acc1" and s.jwt_token == "jwt1"
        assert s.company_id == "emp" and s.user_id == "u1"
        assert s.cabecalhos_para(f"{LEG}/a")["authorization"] == "Bearer acc1"
        assert s.cabecalhos_para(f"{PROD}/a")["authorization"] == "Bearer jwt1"
        assert "accept" not in s.cabecalhos_para(f"{LEG}/a")
        assert s.token_para(f"{PROD}/a") == "jwt1"
    finally:
        s.fechar()


def test_get_passa_os_cabecalhos_do_host():
    vistos = []
    pag = _PaginaFalsa([lambda a: vistos.append(a) or {"itens": [1]}])
    s, _ = _sessao(pag)
    try:
        assert s.pedir(f"{LEG}/lista") == {"itens": [1]}
        assert vistos[0]["headers"]["authorization"] == "Bearer acc1"
    finally:
        s.fechar()


def test_401_recaptura_e_repete_uma_vez():
    pag = _PaginaFalsa([{"__erro": 401}, {"ok": 2}])
    s, _ = _sessao(pag)
    try:
        assert s.pedir(f"{LEG}/lista") == {"ok": 2}
        assert pag.recargas == 1
        assert s.access_token == "acc2"
    finally:
        s.fechar()


def test_dois_401_viram_sessao_recusada():
    pag = _PaginaFalsa([{"__erro": 401}, {"__erro": 401}])
    s, _ = _sessao(pag)
    try:
        with pytest.raises(SessaoRecusada, match="401"):
            s.pedir(f"{LEG}/lista")
    finally:
        s.fechar()


def test_outro_erro_vira_erperro_sem_a_url_inteira():
    pag = _PaginaFalsa([{"__erro": 500}])
    s, _ = _sessao(pag)
    try:
        with pytest.raises(ErpErro) as e:
            s.pedir(f"{LEG}/lista?id=segredo")
        assert e.value.codigo == 500 and "segredo" not in str(e.value)
    finally:
        s.fechar()


def test_post_e_put_usam_o_transporte_certo():
    vistos = []
    pag = _PaginaFalsa([lambda a: vistos.append(a) or {"criado": 1},
                        lambda a: vistos.append(a) or {"trocado": 1}])
    s, _ = _sessao(pag)
    try:
        assert s.pedir(f"{LEG}/p", metodo="POST", corpo={"x": 1}) == {"criado": 1}
        assert s.pedir(f"{LEG}/p", metodo="PUT", corpo={"x": 2}) == {"trocado": 1}
        assert vistos[0]["corpo"] == {"x": 1} and vistos[1]["corpo"] == {"x": 2}
    finally:
        s.fechar()


def test_sem_login_nem_tela_desiste_dizendo_o_que_viu():
    # 28/10/2026: o recado não culpa mais o porteiro (no notebook não há);
    # diz o que a aba viu. A tela de login de verdade leva ao login principal
    # (tests/test_erp_sessao_pagina_login.py).
    pag = _PaginaFalsa(logada=False)
    with pytest.raises(ErpErro, match="nem a área logada nem a tela de login"):
        _sessao(pag, espera=0.5)


def test_pedidos_de_duas_threads_rodam_na_thread_dona():
    pag = _PaginaFalsa([{"n": i} for i in range(20)])
    s, _ = _sessao(pag)
    resultados = []
    try:
        def trabalhar():
            for _ in range(10):
                resultados.append(s.pedir(f"{LEG}/x"))
        t = [threading.Thread(target=trabalhar) for _ in range(2)]
        for x in t: x.start()
        for x in t: x.join(20)
        assert sorted(r["n"] for r in resultados) == list(range(20))
        assert len(pag.threads) == 1            # só a thread dona tocou a página
        assert threading.get_ident() not in pag.threads
    finally:
        s.fechar()


def test_fechar_fecha_a_aba_e_e_idempotente():
    s, aba = _sessao(_PaginaFalsa())
    s.fechar()
    s.fechar()
    assert aba.fechou is True


def test_aceita_transporte_e_espera_atribuidos_por_fora():
    s, _ = _sessao(_PaginaFalsa())
    try:
        s.transporte, s.espera = object(), 45   # conciliacao/erp/api.py faz isso
    finally:
        s.fechar()


# ---------------------------------------------------------------- além do brief


def test_dois_401_param_no_teto_uma_recarga_e_duas_chamadas():
    chamadas = []
    pag = _PaginaFalsa([lambda a: chamadas.append(1) or {"__erro": 401}] * 3)
    s, _ = _sessao(pag)
    try:
        with pytest.raises(SessaoRecusada):
            s.pedir(f"{LEG}/lista")
        assert pag.recargas == 1 and len(chamadas) == 2
    finally:
        s.fechar()


def test_post_com_401_recaptura_mas_nao_repete():
    chamadas = []
    pag = _PaginaFalsa([lambda a: chamadas.append(1) or {"__erro": 401},
                        lambda a: chamadas.append(1) or {"criado": 1}])
    s, _ = _sessao(pag)
    try:
        with pytest.raises(SessaoRecusada) as e:
            s.pedir(f"{LEG}/p", metodo="POST", corpo={"x": 1})
        assert e.value.codigo == 401
        assert len(chamadas) == 1 and pag.recargas == 1
    finally:
        s.fechar()


def test_post_idempotente_com_401_repete():
    pag = _PaginaFalsa([{"__erro": 401}, {"trocado": 1}])
    s, _ = _sessao(pag)
    try:
        assert s.pedir(f"{LEG}/p", metodo="PUT", corpo={}, idempotente=True) == {"trocado": 1}
    finally:
        s.fechar()


def test_aba_que_nao_abre_vira_erperro_rapido():
    def fabrica():
        raise TimeoutError("porta fechada")
    with pytest.raises(ErpErro, match="porta fechada"):
        SessaoPelaPagina.do_acesso("principal", fabrica_aba=fabrica,
                                   espera_captura=30.0)


def test_pedir_depois_de_fechar_e_erro_e_nao_trava():
    s, _ = _sessao(_PaginaFalsa())
    s.fechar()
    with pytest.raises(ErpErro, match="fechada"):
        s.pedir(f"{LEG}/x")


def test_aba_que_morre_no_meio_solta_quem_espera():
    pag = _PaginaFalsa()
    s, _ = _sessao(pag)
    try:
        def morrer(ms):
            raise RuntimeError("Target closed")
        pag.wait_for_timeout = morrer
        s._saiu.wait(5)
        with pytest.raises(ErpErro):
            s.pedir(f"{LEG}/x")
    finally:
        s.fechar()


def test_relogar_recaptura_sem_login():
    pag = _PaginaFalsa()
    s, _ = _sessao(pag)
    try:
        s.relogar()
        assert pag.recargas == 1 and s.jwt_token == "jwt2"
    finally:
        s.fechar()


def test_thread_dona_e_daemon_com_nome():
    s, _ = _sessao(_PaginaFalsa())
    try:
        assert s._thread.daemon and s._thread.name == "erp-central-principal"
        assert s.usuario == "Chrome central (principal)" and s.empresa is None
    finally:
        s.fechar()
    assert not s._thread.is_alive()


# ------------------------------------------------- rodada de correção 1


class _PrazoPlaywright(Exception):
    """Faz o papel do TimeoutError do Playwright."""


def test_goto_com_prazo_vencido_depois_da_captura_nao_mata_a_sessao():
    pag = _PaginaFalsa([{"ok": 1}])
    original = pag.goto

    def goto_lento(url, **kw):
        original(url, **kw)                 # a tela já chamou os dois hosts
        raise _PrazoPlaywright("Timeout 30000ms exceeded (load)")
    pag.goto = goto_lento
    s, _ = _sessao(pag)
    try:
        assert s.pedir(f"{LEG}/x") == {"ok": 1}
    finally:
        s.fechar()


def test_reload_que_levanta_vira_erperro_e_a_sessao_segue(monkeypatch):
    import erp.sessao_pagina as sp
    monkeypatch.setattr(sp, "_PRAZO_RECAPTURA", 0.4)
    pag = _PaginaFalsa([{"__erro": 401}, {"ok": 2}])

    def reload_quebrado(**kw):
        raise _PrazoPlaywright("Timeout 30000ms exceeded (reload)")
    pag.reload = reload_quebrado
    s, _ = _sessao(pag)
    try:
        with pytest.raises(ErpErro) as e:
            s.pedir(f"{LEG}/lista")
        assert not isinstance(e.value, _PrazoPlaywright)
        assert s.pedir(f"{LEG}/y") == {"ok": 2}     # a dona continua viva
    finally:
        s.fechar()


def test_evaluate_pendurado_quebra_a_sessao_e_o_seguinte_falha_na_hora():
    import time
    solta = threading.Event()
    pag = _PaginaFalsa([lambda a: solta.wait(10) and {"tarde": 1}])
    aba = _AbaFalsa(pag)
    s = SessaoPelaPagina.do_acesso("principal", fabrica_aba=lambda: aba,
                                   espera_captura=2.0, prazo_pedido=0.3)
    try:
        with pytest.raises(ErpErro, match="parou de responder"):
            s.pedir(f"{LEG}/x")
        t0 = time.monotonic()
        with pytest.raises(ErpErro, match="parou de responder"):
            s.pedir(f"{LEG}/x")
        assert time.monotonic() - t0 < 0.2
        t0 = time.monotonic()
        s.fechar()                                  # não espera a dona presa
        assert time.monotonic() - t0 < 1.0
    finally:
        solta.set()
        s.fechar()
    assert s._saiu.wait(5) and aba.fechou


def test_contrato_viva_do_acesso_ao_fechar_e_quebrada():
    s, _ = _sessao(_PaginaFalsa())
    assert s.viva is True
    s.fechar()
    assert s.viva is False

    solta = threading.Event()
    pag = _PaginaFalsa([lambda a: solta.wait(10) and {"tarde": 1}])
    q = SessaoPelaPagina.do_acesso("principal", fabrica_aba=lambda: _AbaFalsa(pag),
                                   espera_captura=2.0, prazo_pedido=0.3)
    try:
        assert q.viva is True
        with pytest.raises(ErpErro, match="parou de responder"):
            q.pedir(f"{LEG}/x")
        assert q.viva is False
    finally:
        solta.set()
        q.fechar()


# ------------------------------------------------- rodada de correção 2


def _devagar(segundos, resposta):
    import time
    return lambda a: time.sleep(segundos) or resposta


def _sessao_prazo(pagina, prazo):
    aba = _AbaFalsa(pagina)
    return SessaoPelaPagina.do_acesso("principal", fabrica_aba=lambda: aba,
                                      espera_captura=2.0, prazo_pedido=prazo)


def test_dois_pedidos_concorrentes_dentro_do_prazo_nao_quebram_a_sessao():
    pag = _PaginaFalsa([_devagar(0.6, {"n": 1}), _devagar(0.6, {"n": 2}), {"n": 3}])
    s = _sessao_prazo(pag, 1.0)
    resultados, erros = [], []
    try:
        def trabalhar():
            try:
                resultados.append(s.pedir(f"{LEG}/x")["n"])
            except Exception as e:          # pragma: no cover - é a falha
                erros.append(e)
        t = [threading.Thread(target=trabalhar) for _ in range(2)]
        for x in t: x.start()
        for x in t: x.join(10)
        assert erros == [] and sorted(resultados) == [1, 2]
        assert s.pedir(f"{LEG}/x") == {"n": 3}
    finally:
        s.fechar()


def test_pedido_parado_na_fila_estoura_como_ocupado_sem_quebrar():
    import time
    pag = _PaginaFalsa([_devagar(0.7, {"n": 1}), _devagar(0.7, {"n": 2}), {"n": 3}])
    s = _sessao_prazo(pag, 1.0)
    resultados = []
    try:
        t = []
        for _ in range(2):                  # A e B, cada um 0,7 s em execução
            t.append(threading.Thread(
                target=lambda: resultados.append(s.pedir(f"{LEG}/x")["n"])))
            t[-1].start()
            time.sleep(0.05)
        with pytest.raises(ErpErro, match="ocupado"):   # C: 1 s parado na fila
            s.pedir(f"{LEG}/x")
        for x in t: x.join(10)
        assert sorted(resultados) == [1, 2]
        assert s.pedir(f"{LEG}/x") == {"n": 3}          # não ficou quebrada
    finally:
        s.fechar()
