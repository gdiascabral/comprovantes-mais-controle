# -*- coding: utf-8 -*-
"""A aba de leitura do Chrome central e o LOGIN PRINCIPAL (28/10/2026).

diagnostico.log do dono, 22 a 28/10: "o Chrome central 'principal' não está
logado no ERP — o porteiro precisa entrar" em TODA abertura do app e no
"Buscar pagamentos e saldos": a aba de leitura nascia na tela de login, em
corrida com o login da aba do Anexar. Decisão do dono: um login principal só,
sempre primeiro (`erp.login_principal`); a leitura espera por ele, recarrega
enquanto estiver no login e nunca entra sozinha. Sem navegador: página, aba,
credencial e travas são dublês.
"""
import contextlib
import threading
import time

import pytest

from erp import hosts, login_principal, login_tela
from erp import sessao as erp_sessao
from erp.central import Acesso
from erp.sessao import ErpErro
from erp.sessao_pagina import SessaoPelaPagina

LEG = f"https://{hosts.HOST_LEGACY}"
PROD = f"https://{hosts.HOST_ERP_API}"


@pytest.fixture(autouse=True)
def _rapido(monkeypatch):
    import erp.sessao_pagina as sp
    monkeypatch.setattr(sp, "_CARENCIA_LOGIN", 0.0)
    monkeypatch.setattr(sp, "_RECARGA_NO_LOGIN", 0.2)    # 1 passo
    monkeypatch.setattr(sp, "_SO_RECARGA", 1.0)          # 5 passos
    monkeypatch.setattr(login_principal, "CARENCIA", 0.0)
    login_principal.esquecer()
    yield
    login_principal.esquecer()


@pytest.fixture(autouse=True)
def _login_http_proibido(monkeypatch):
    def proibido(*a, **k):
        raise AssertionError("login HTTP por fora derruba a sessão do Chrome")
    monkeypatch.setattr(erp_sessao, "_pedir", proibido)


class _Req:
    def __init__(self, url, headers):
        self.url, self.headers = url, headers


class _Visivel:
    def __init__(self, sim):
        self.first, self._sim = self, sim

    def is_visible(self, timeout=None):
        return self._sim


class _Erp:
    """A sessão do ERP, dividida por todas as abas do MESMO Chrome."""

    def __init__(self, logado=False):
        self.logado, self.logins, self.ordem = logado, [], []


class _Pagina:
    """Uma aba: dispara os requests da área logada ao navegar, mostra a tela
    de login quando a sessão está fora e entra quando o controller é chamado."""

    def __init__(self, erp, respostas=None, controller_ok=True, nome="leitura"):
        self.erp, self.nome = erp, nome
        self.ouvintes, self.respostas = [], list(respostas or [])
        self.controller_ok = controller_ok
        self.recargas, self.gotos, self.token = 0, [], 1
        self.ao_recarregar = None          # outra aba entrou: muda a sessão

    def on(self, evento, fn):
        self.ouvintes.append(fn)

    def _tela(self):
        if not self.erp.logado:
            return
        for fn in self.ouvintes:
            fn(_Req(f"{LEG}/maiscontrole/x", {
                "authorization": f"Bearer acc{self.token}", "company-id": "emp",
                "user-id": "u1", "organization-unit-id": "o1"}))
            fn(_Req(f"{PROD}/y", {"authorization": f"Bearer jwt{self.token}",
                                  "company-id": "emp"}))

    def goto(self, url, **kw):
        self.gotos.append(url)
        self.erp.ordem.append(f"{self.nome} goto")
        self._tela()

    def reload(self, **kw):
        self.recargas += 1
        self.token += 1
        if self.ao_recarregar:
            self.ao_recarregar(self)
        self._tela()

    def wait_for_timeout(self, ms):
        pass

    def locator(self, seletor):
        return _Visivel(not self.erp.logado and seletor in login_tela.SINAIS_DE_LOGIN)

    def fill(self, seletor, valor, **kw):
        pass

    def evaluate(self, js, args=None):
        if js is login_tela.JS_LOGIN_ANGULAR:
            self.erp.logins.append(args["email"])     # nunca a senha no teste
            self.erp.ordem.append("login")
            if not self.controller_ok:
                return {"ok": False, "motivo": "controller de login não encontrado"}
            self.erp.logado = True
            return {"ok": True}
        r = self.respostas.pop(0) if self.respostas else {"ok": True}
        if isinstance(r, dict) and r.get("__deslogar"):
            self.erp.logado = False
            return {"__erro": 401}
        return r


class _Aba:
    def __init__(self, pagina):
        self.page, self.fechou = pagina, False

    def __enter__(self):
        return self

    def __exit__(self, *e):
        self.fechou = True
        return False


class _Trava:
    def __init__(self, ao_entrar=None):
        self.entradas, self.dentro, self._ao_entrar = 0, 0, ao_entrar
        self.maximo = 0

    @contextlib.contextmanager
    def __call__(self):
        self.entradas += 1
        self.dentro += 1
        self.maximo = max(self.maximo, self.dentro)
        if self._ao_entrar:
            self._ao_entrar()
        try:
            yield
        finally:
            self.dentro -= 1


ACESSO = Acesso("principal", __import__("pathlib").Path("perfis/principal"), 9230)


def _principal(erp, *, credencial=lambda: ("dono@exemplo", "x"), trava=None,
               controller_ok=True):
    """O login principal de verdade, com a aba e as travas de dublê."""
    trava = trava or _Trava()

    @contextlib.contextmanager
    def abrir():
        yield _Pagina(erp, controller_ok=controller_ok, nome="principal")

    def pedir(caiu=False):
        return login_principal.garantir_logado(
            ACESSO, caiu=caiu, abrir_pagina=abrir, credencial=credencial,
            trava_arquivo=trava, dormir=lambda s: None)
    return pedir, trava


def _leitura(pagina, principal, espera=1.0):
    return SessaoPelaPagina.do_acesso(
        "principal", fabrica_aba=lambda: _Aba(pagina), espera_captura=espera,
        login_principal=principal)


# ------------------------------------------------- a leitura e o principal


def test_porteiro_de_pe_ninguem_loga_nem_pega_a_trava():
    erp = _Erp(logado=True)
    principal, trava = _principal(erp)
    pag = _Pagina(erp)
    s = _leitura(pag, principal)
    try:
        assert s.jwt_token == "jwt1" and erp.logins == [] and trava.entradas == 0
        assert pag.recargas == 0 and s.reentrou() is False
    finally:
        s.fechar()


def test_leitura_nao_navega_antes_do_login_principal():
    erp = _Erp(logado=False)
    principal, trava = _principal(erp)
    pag = _Pagina(erp)
    s = _leitura(pag, principal)
    try:
        assert erp.logins == ["dono@exemplo"] and trava.entradas == 1
        assert erp.ordem.index("login") < erp.ordem.index("leitura goto")
        assert s.access_token and s.jwt_token
        assert s.reentrou() is True and s.reentrou() is False
    finally:
        s.fechar()


def test_corrida_leitura_no_login_recarrega_ate_outra_aba_entrar():
    """A corrida do dono: a leitura cai em #/login enquanto a aba do Anexar
    ainda está entrando; recarregando, pega o login dela sem entrar sozinha."""
    erp = _Erp(logado=False)
    pedidos = []
    pag = _Pagina(erp)

    def outra_aba_entra(p):
        if p.recargas >= 3:
            erp.logado = True
    pag.ao_recarregar = outra_aba_entra
    s = _leitura(pag, lambda caiu=False: pedidos.append(caiu) or False)
    try:
        assert s.jwt_token and erp.logins == []
        assert pedidos == [False]                # só o pedido de antes de navegar
        assert pag.recargas == 3
    finally:
        s.fechar()


def test_ninguem_entra_a_leitura_pede_o_principal_de_novo_e_le():
    erp = _Erp(logado=False)
    pedidos = []

    def principal(caiu=False):
        pedidos.append(caiu)
        if caiu:                                  # 2º pedido: agora entra
            erp.logado = True
            return True
        return False
    pag = _Pagina(erp)
    s = _leitura(pag, principal)
    try:
        assert pedidos == [False, True] and s.jwt_token
        assert pag.recargas >= 2                 # recarregou antes de pedir
        assert s.reentrou() is True
    finally:
        s.fechar()


def test_sem_credencial_guardada_o_erro_diz_o_que_fazer():
    erp = _Erp(logado=False)
    principal, _ = _principal(erp, credencial=lambda: None)
    with pytest.raises(ErpErro, match="Minha aba no ERP"):
        _leitura(_Pagina(erp), principal)
    assert erp.logins == []


def test_controller_que_nao_roda_vira_erro_claro():
    erp = _Erp(logado=False)
    principal, _ = _principal(erp, controller_ok=False)
    with pytest.raises(ErpErro, match="login automático"):
        _leitura(_Pagina(erp), principal)


def test_sessao_que_cai_no_meio_pede_um_relogin_e_repete_o_get():
    erp = _Erp(logado=True)
    principal, trava = _principal(erp)
    pag = _Pagina(erp, respostas=[{"__deslogar": True}, {"ok": 2}])
    s = _leitura(pag, principal)
    try:
        assert s.pedir(f"{LEG}/lista") == {"ok": 2}
        assert erp.logins == ["dono@exemplo"] and trava.entradas == 1
        assert s.reentrou() is True
    finally:
        s.fechar()


def test_relogar_pede_o_principal_quando_a_recarga_cai_no_login():
    erp = _Erp(logado=True)
    principal, _ = _principal(erp)
    pag = _Pagina(erp)
    s = _leitura(pag, principal)
    try:
        erp.logado = False
        s.relogar()
        assert erp.logins == ["dono@exemplo"] and s.viva
    finally:
        s.fechar()


def test_tela_que_nao_mostra_nada_explica_sem_culpar_o_porteiro():
    erp = _Erp(logado=False)
    pag = _Pagina(erp)
    pag.locator = lambda seletor: _Visivel(False)   # nem área logada, nem login
    with pytest.raises(ErpErro) as e:
        _leitura(pag, lambda caiu=False: False, espera=0.5)
    assert "porteiro" not in str(e.value) and "tela de login" in str(e.value)


# ------------------------------------------------------- o login principal


def test_tres_pedidos_simultaneos_fazem_um_login_so():
    erp = _Erp(logado=False)
    trava = _Trava(ao_entrar=lambda: time.sleep(0.2))
    principal, _ = _principal(erp, trava=trava)
    resultados, erros = [], []

    def pedir():
        try:
            resultados.append(principal())
        except Exception as e:                    # pragma: no cover - é a falha
            erros.append(e)
    t = [threading.Thread(target=pedir) for _ in range(3)]
    for x in t:
        x.start()
    for x in t:
        x.join(10)
    assert erros == [] and erp.logins == ["dono@exemplo"]
    assert sorted(resultados) == [False, False, True]


def test_queda_no_meio_tres_pedidos_caiu_fazem_um_relogin_so():
    erp = _Erp(logado=True)
    principal, _ = _principal(erp, trava=_Trava(ao_entrar=lambda: time.sleep(0.2)))
    assert principal() is False                   # de pé: ninguém loga
    erp.logado = False
    t = [threading.Thread(target=lambda: principal(caiu=True)) for _ in range(3)]
    for x in t:
        x.start()
    for x in t:
        x.join(10)
    assert erp.logins == ["dono@exemplo"]


def test_verificacao_recente_vale_sem_queda_e_nao_vale_com_queda():
    erp = _Erp(logado=True)
    abertas = []

    @contextlib.contextmanager
    def abrir():
        abertas.append(1)
        yield _Pagina(erp, nome="principal")

    def pedir(caiu=False):
        return login_principal.garantir_logado(
            ACESSO, caiu=caiu, abrir_pagina=abrir, credencial=lambda: None,
            trava_arquivo=_Trava(), dormir=lambda s: None)
    pedir()
    pedir()
    assert len(abertas) == 1                      # a 2ª usou a verificação recente
    pedir(caiu=True)
    assert len(abertas) == 2


def test_dentro_da_trava_outro_processo_ja_entrou_e_nao_loga_de_novo():
    erp = _Erp(logado=False)
    trava = _Trava(ao_entrar=lambda: setattr(erp, "logado", True))
    principal, _ = _principal(erp, trava=trava)
    assert principal() is False
    assert trava.entradas == 1 and erp.logins == []


def test_trava_ocupada_demais_vira_erperro():
    erp = _Erp(logado=False)

    @contextlib.contextmanager
    def ocupada():
        raise TimeoutError("trava ocupada há mais de 180 s")
        yield                                     # pragma: no cover
    principal, _ = _principal(erp, trava=ocupada)
    with pytest.raises(ErpErro, match="outro robô"):
        principal()
    assert erp.logins == []


def test_login_principal_termina_parado_no_painel():
    erp = _Erp(logado=False)
    paginas = []

    @contextlib.contextmanager
    def abrir():
        p = _Pagina(erp, nome="principal")
        paginas.append(p)
        yield p
    login_principal.garantir_logado(
        ACESSO, abrir_pagina=abrir, credencial=lambda: ("dono@exemplo", "x"),
        trava_arquivo=_Trava(), dormir=lambda s: None)
    assert paginas[0].gotos[-1] == login_principal.URL_DASHBOARD


def test_login_principal_roda_em_thread_propria():
    erp = _Erp(logado=False)
    threads = set()

    @contextlib.contextmanager
    def abrir():
        threads.add(threading.get_ident())
        yield _Pagina(erp, nome="principal")
    login_principal.garantir_logado(
        ACESSO, abrir_pagina=abrir, credencial=lambda: ("dono@exemplo", "x"),
        trava_arquivo=_Trava(), dormir=lambda s: None)
    assert threads and threading.get_ident() not in threads


# ------------------------------------------------ o caminho é o do MCClient


def test_mcclient_usa_o_mesmo_login_e_os_mesmos_sinais():
    from anexar import mc_client
    assert mc_client._JS_LOGIN_ANGULAR is login_tela.JS_LOGIN_ANGULAR
    assert mc_client.SINAIS_DE_LOGIN is login_tela.SINAIS_DE_LOGIN


def test_mcclient_login_pelo_controller_delega(monkeypatch):
    from anexar import mc_client
    vistos = []
    monkeypatch.setattr(login_tela, "entrar_pelo_controller",
                        lambda page, email, senha, diag=None: vistos.append(
                            (page, email)) or True)
    mc = mc_client.MCClient.__new__(mc_client.MCClient)
    mc.page = object()
    assert mc._login_pelo_controller("dono@exemplo", "x") is True
    assert vistos == [(mc.page, "dono@exemplo")]


def test_mcclient_central_pede_o_login_principal_antes_da_propria_aba(monkeypatch):
    from anexar import mc_client
    ordem = []
    monkeypatch.setattr(login_principal, "garantir_logado",
                        lambda acesso, **k: ordem.append(("principal", k.get("caiu", False))))
    mc = mc_client.MCClient.__new__(mc_client.MCClient)
    mc._acesso, mc.log = ACESSO, lambda m: None
    monkeypatch.setattr(mc_client.MCClient, "central", True)
    monkeypatch.setattr(mc, "_conferir_sessao",
                        lambda: ordem.append(("propria", None)) or True)
    monkeypatch.setattr(mc, "_garantir_login_sem_trava",
                        lambda: pytest.fail("logada: sem login próprio"))
    assert mc.garantir_login() is True
    assert ordem == [("principal", False), ("propria", None)]


def test_mcclient_que_ve_a_queda_pede_o_principal_de_novo_antes_do_proprio(monkeypatch):
    from anexar import mc_client
    ordem, logada = [], iter([False, True])
    monkeypatch.setattr(login_principal, "garantir_logado",
                        lambda acesso, **k: ordem.append(("principal", k.get("caiu"))))
    mc = mc_client.MCClient.__new__(mc_client.MCClient)
    mc._acesso, mc.log = ACESSO, lambda m: None
    monkeypatch.setattr(mc_client.MCClient, "central", True)
    monkeypatch.setattr(mc, "_conferir_sessao", lambda: next(logada))
    monkeypatch.setattr(mc, "_garantir_login_sem_trava",
                        lambda: pytest.fail("o relogin é o principal, não o próprio"))
    assert mc.garantir_login() is True
    assert ordem == [("principal", False), ("principal", True)]


def test_mcclient_do_porteiro_nao_pede_login_principal(monkeypatch):
    from anexar import mc_client
    monkeypatch.setattr(login_principal, "garantir_logado",
                        lambda *a, **k: pytest.fail("o porteiro É o login"))
    mc = mc_client.MCClient.__new__(mc_client.MCClient)
    mc._acesso, mc.log, mc.login_principal = ACESSO, (lambda m: None), False
    monkeypatch.setattr(mc_client.MCClient, "central", True)
    monkeypatch.setattr(mc, "_garantir_login_sem_trava", lambda: True)
    monkeypatch.setattr(mc_client.central, "trava",
                        lambda *a, **k: contextlib.nullcontext())
    assert mc.garantir_login() is True


def test_entrar_pelo_controller_diz_o_motivo_quando_nao_roda():
    motivos = []

    class P:
        def fill(self, *a, **k):
            raise RuntimeError("sem campo")

        def evaluate(self, js, args):
            return {"ok": False, "motivo": "AngularJS ausente"}
    assert login_tela.entrar_pelo_controller(P(), "e", "s", diag=motivos.append) is False
    assert motivos and "AngularJS ausente" in motivos[0]


def test_caminho_da_trava_e_o_mesmo_do_mcclient(tmp_path):
    a = Acesso("principal", tmp_path / "perfis" / "principal", 9230)
    assert login_tela.caminho_da_trava(a) == tmp_path / "perfis" / ".principal.login.trava"


def test_credencial_do_acesso_le_o_arquivo_proprio(tmp_path, monkeypatch):
    import json

    import util
    arq = tmp_path / "principal.login.dat"
    arq.write_bytes(json.dumps({"email": "dono@exemplo", "senha": "x"}).encode())
    monkeypatch.setattr(util, "revelar_bytes", lambda b: b)
    a = Acesso("principal", tmp_path / "p", 9230, arq)
    assert login_tela.credencial_do_acesso(a) == ("dono@exemplo", "x")


def test_credencial_do_acesso_sem_arquivo_usa_o_login_do_app(tmp_path, monkeypatch):
    from anexar import credenciais
    monkeypatch.setattr(credenciais, "carregar", lambda: ("app@exemplo", "y"))
    a = Acesso("principal", tmp_path / "p", 9230, tmp_path / "nao-existe.dat")
    assert login_tela.credencial_do_acesso(a) == ("app@exemplo", "y")


def test_porteiro_abre_o_mcclient_sem_login_principal(monkeypatch):
    """O porteiro É o login: o comportamento dele não muda."""
    from anexar import mc_client
    from erp import porteiro
    criados = []

    class _MC:
        login_principal = True

        def __init__(self, acesso=None, log=None):
            criados.append(self)

        def __enter__(self):
            criados.append(("entrou", self.login_principal))
            return self
    monkeypatch.setattr(mc_client, "MCClient", _MC)
    m = porteiro._mantenedor_real(lambda *_: None)
    m._abrir(ACESSO)
    assert criados[-1] == ("entrou", False)


# ================================================ revisão de 28/10/2026


class _SoPermissao(_Pagina):
    """Fora da sessão, mas mostrando SÓ "não tem permissão" — o que o ERP
    mostra também com sessão boa, enquanto o Firebase devolve o token."""

    def locator(self, seletor):
        return _Visivel(not self.erp.logado and seletor == "text=não tem permissão")


def test_nao_tem_permissao_sozinho_nunca_dispara_o_login_principal():
    erp = _Erp(logado=False)

    @contextlib.contextmanager
    def abrir():
        yield _SoPermissao(erp, nome="principal")
    entrou = login_principal.garantir_logado(
        ACESSO, abrir_pagina=abrir, credencial=lambda: ("dono@exemplo", "x"),
        trava_arquivo=_Trava(), dormir=lambda s: None)
    assert entrou is False and erp.logins == []


def test_nao_tem_permissao_sozinho_nao_faz_a_leitura_pedir_login():
    erp = _Erp(logado=False)
    pedidos = []
    with pytest.raises(ErpErro):
        _leitura(_SoPermissao(erp), lambda caiu=False: pedidos.append(caiu) or False,
                 espera=0.5)
    assert pedidos == [False]                       # nunca o caiu=True


def test_principal_decide_na_rota_de_pagamentos_e_para_no_painel():
    from erp.sessao_pagina import URL_CAPTURA
    erp = _Erp(logado=False)
    paginas = []

    @contextlib.contextmanager
    def abrir():
        p = _Pagina(erp, nome="principal")
        paginas.append(p)
        yield p
    login_principal.garantir_logado(
        ACESSO, abrir_pagina=abrir, credencial=lambda: ("dono@exemplo", "x"),
        trava_arquivo=_Trava(), dormir=lambda s: None)
    assert paginas[0].gotos[0] == URL_CAPTURA
    assert paginas[0].gotos[-1] == login_principal.URL_DASHBOARD


def test_falha_do_principal_fica_em_carencia_e_nao_vira_login_a_cada_pedido():
    erp = _Erp(logado=False)
    abertas, agora = [], [1000.0]

    @contextlib.contextmanager
    def abrir():
        abertas.append(1)
        yield _Pagina(erp, nome="principal")

    def pedir(caiu=False):
        return login_principal.garantir_logado(
            ACESSO, caiu=caiu, abrir_pagina=abrir, credencial=lambda: None,
            trava_arquivo=_Trava(), dormir=lambda s: None,
            relogio=lambda: agora[0])
    with pytest.raises(ErpErro, match="Minha aba no ERP"):
        pedir()
    with pytest.raises(ErpErro, match="Minha aba no ERP"):
        pedir(caiu=True)                            # dentro da carência
    assert len(abertas) == 1
    agora[0] += login_principal.CARENCIA_FALHA + 1
    with pytest.raises(ErpErro):
        pedir()
    assert len(abertas) == 2


def test_trava_do_processo_com_prazo_vira_erperro(monkeypatch):
    monkeypatch.setattr(login_principal, "PRAZO_TRAVA_PROCESSO", 0.3)
    trava = login_principal._trava_do_processo(ACESSO.nome)
    trava.acquire()
    try:
        with pytest.raises(ErpErro, match="outro pedido"):
            login_principal.garantir_logado(
                ACESSO, abrir_pagina=lambda: pytest.fail("não devia abrir"),
                dormir=lambda s: None)
    finally:
        trava.release()


def test_login_principal_que_nao_termina_vira_erperro(monkeypatch):
    monkeypatch.setattr(login_principal, "PRAZO_TOTAL", 0.3)
    solta = threading.Event()

    @contextlib.contextmanager
    def abrir():
        solta.wait(5)
        yield _Pagina(_Erp(logado=True), nome="principal")
    t0 = time.monotonic()
    try:
        with pytest.raises(ErpErro, match="não terminou"):
            login_principal.garantir_logado(ACESSO, abrir_pagina=abrir,
                                            dormir=lambda s: None)
        assert time.monotonic() - t0 < 2
    finally:
        solta.set()


def test_esperar_pronto_tem_teto_mesmo_com_o_principal_preso(monkeypatch):
    import erp.sessao_pagina as sp
    monkeypatch.setattr(sp, "_TETO_PRONTO", 0.5)
    solta = threading.Event()

    def principal(caiu=False):
        if caiu:
            solta.wait(5)
        return False
    t0 = time.monotonic()
    try:
        with pytest.raises(ErpErro):
            _leitura(_Pagina(_Erp(logado=False)), principal, espera=5.0)
        assert time.monotonic() - t0 < 2
    finally:
        solta.set()


def test_sessao_do_central_pede_o_principal_fora_da_trava_dos_centrais(monkeypatch):
    import erp.sessao_pagina as sp
    vistos = []

    def pedir(nome, caiu=False, diag=None):
        vistos.append(("principal", erp_sessao._TRAVA_CENTRAIS.locked()))
        return True

    class _Sessao:
        viva = True

    def do_acesso(nome="principal", **k):
        vistos.append(("abre", erp_sessao._TRAVA_CENTRAIS.locked(), k.get("ja_pedido")))
        return _Sessao()
    monkeypatch.setattr(sp, "pedir_login_principal", pedir)
    monkeypatch.setattr(sp.SessaoPelaPagina, "do_acesso", staticmethod(do_acesso))
    erp_sessao._sessao_do_central("principal")
    assert vistos == [("principal", False), ("abre", True, True)]


def test_do_acesso_com_ja_pedido_nao_pede_de_novo():
    erp = _Erp(logado=True)
    pedidos = []
    s = SessaoPelaPagina.do_acesso(
        "principal", fabrica_aba=lambda: _Aba(_Pagina(erp)), espera_captura=1.0,
        login_principal=lambda caiu=False: pedidos.append(caiu) or False,
        ja_pedido=True)
    try:
        assert pedidos == [] and s.reentrou() is True
    finally:
        s.fechar()


# ----------------------------- a aba do principal: sem evaluate, sem frente


class _Resposta:
    def __init__(self, corpo, status=200):
        self.corpo, self.status = corpo, status

    def read(self):
        return self.corpo

    def __enter__(self):
        return self

    def __exit__(self, *e):
        return False


def test_aba_principal_nasce_por_put_json_new_e_guarda_o_id(tmp_path):
    import json
    from urllib.parse import unquote

    from erp.sessao_pagina import URL_CAPTURA
    a = Acesso("principal", tmp_path / "perfis" / "principal", 9230)
    pedidos = []

    def abrir(pedido, timeout=None):
        pedidos.append((pedido.get_method(), pedido.full_url, timeout))
        if "/json/list" in pedido.full_url:
            return _Resposta(b"[]")
        return _Resposta(json.dumps({"id": "ALVO1", "type": "page"}).encode())
    alvo = login_principal._alvo_da_aba(a, "http://127.0.0.1:1", abrir=abrir)
    assert alvo == "ALVO1"
    metodo, url, prazo = pedidos[-1]
    assert metodo == "PUT" and "/json/new?" in url and prazo
    assert unquote(url.split("/json/new?", 1)[1]) == URL_CAPTURA
    assert login_principal._arquivo_da_aba(a).read_text().strip() == "ALVO1"


def test_aba_principal_guardada_e_viva_e_reaproveitada(tmp_path):
    import json
    a = Acesso("principal", tmp_path / "perfis" / "principal", 9230)
    login_principal._arquivo_da_aba(a).parent.mkdir(parents=True)
    login_principal._arquivo_da_aba(a).write_text("ALVO1")

    def abrir(pedido, timeout=None):
        assert pedido.get_method() == "GET", "não cria aba nova"
        return _Resposta(json.dumps([{"id": "ALVO1", "type": "page"}]).encode())
    assert login_principal._alvo_da_aba(a, "http://127.0.0.1:1", abrir=abrir) == "ALVO1"


def test_pagina_do_alvo_acha_pelo_target_id_sem_evaluate():
    class P:
        def __init__(self, alvo):
            self.alvo = alvo

        def evaluate(self, *a, **k):
            pytest.fail("evaluate em aba que pode ser da pessoa")

    class Sessao:
        def __init__(self, p):
            self.p = p

        def send(self, metodo, params=None):
            assert metodo == "Target.getTargetInfo"
            return {"targetInfo": {"targetId": self.p.alvo}}

        def detach(self):
            pass
    paginas = [P("DA-PESSOA"), P("ALVO1")]

    class Ctx:
        pages = paginas

        def new_cdp_session(self, p):
            return Sessao(p)
    assert login_principal._pagina_do_alvo(Ctx(), "ALVO1") is paginas[1]
    assert login_principal._pagina_do_alvo(Ctx(), "SUMIU") is None


def test_relogio_parado_nao_faz_queda_passar_por_atendida():
    """No Windows o monotonic anda de ~15 ms em ~15 ms: com o relógio parado,
    o pedido de "caiu" tem de relogar mesmo assim (CI de 28/10/2026)."""
    erp = _Erp(logado=True)
    abertas = []

    @contextlib.contextmanager
    def abrir():
        abertas.append(1)
        yield _Pagina(erp, nome="principal")

    def pedir(caiu=False):
        return login_principal.garantir_logado(
            ACESSO, caiu=caiu, abrir_pagina=abrir, credencial=lambda: None,
            trava_arquivo=_Trava(), dormir=lambda s: None, relogio=lambda: 100.0)
    pedir()
    pedir(caiu=True)
    assert len(abertas) == 2
