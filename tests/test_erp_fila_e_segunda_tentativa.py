# -*- coding: utf-8 -*-
"""A fila de conexão e a segunda tentativa do `central.conectar` (18/11/2026),
e o `erp.cdp_cru`, o CDP cru oficial dos scripts de `ferramentas/`.

Em 18/11/2026, medido num Chrome de teste: UMA aba com a página presa faz
todo `connect_over_cdp` estourar. O `conectar` agora espera a aba calada
voltar e tenta de novo uma vez, dentro de uma fila entre processos; e o
`cdp_cru` abre a aba dele na mesma fila, registra na faxina e a fecha."""
import inspect
import json
import threading
import time

import pytest
from playwright.sync_api import TimeoutError as PWTimeout

from erp import cdp_cru, central, faxina
from erp.sessao import ErpErro


def _s(tid, responde, titulo=""):
    return central.AlvoSondado(tid, "page", titulo, "https://h.invalid/x", responde, 0.0)


class _Cromo:
    """`connect_over_cdp` que devolve, a cada chamada, o próximo efeito."""

    def __init__(self, *efeitos, antes=None):
        self.efeitos, self.chamadas, self.antes = list(efeitos), 0, antes

    def connect_over_cdp(self, endereco, **kw):
        self.chamadas += 1
        if self.antes:
            self.antes()
        e = self.efeitos.pop(0)
        if isinstance(e, BaseException):
            raise e
        return e


class _Pw:
    def __init__(self, *efeitos, antes=None):
        self.chromium = _Cromo(*efeitos, antes=antes)


ESTOURO = PWTimeout("BrowserType.connect_over_cdp: Timeout 45000ms exceeded.")


# ------------------------------------------------------ a segunda tentativa


def test_aba_calada_que_volta_ganha_a_segunda_tentativa():
    respostas = iter([[_s("1", False, "ERP")], [_s("1", False, "ERP")],
                      [_s("1", True, "ERP")]])
    pw = _Pw(ESTOURO, "browser")
    sonos = []
    b = central.conectar(pw, "http://127.0.0.1:1", sondar=lambda e: next(respostas),
                         espera_volta=60, passo_volta=5, dormir=sonos.append)
    assert b == "browser"
    assert pw.chromium.chamadas == 2
    assert sonos == [5, 5]                         # perguntou de 5 em 5 s


def test_aba_que_nao_volta_vira_recado_com_a_sonda_mais_nova():
    t = [0.0]

    def dormir(s):
        t[0] += s
    n = [0]

    def sondar(_e):
        n[0] += 1
        return [_s("1", False, f"Calada {n[0]}")]
    pw = _Pw(ESTOURO, "nunca")
    with pytest.raises(central.ChromeSemResposta) as e:
        central.conectar(pw, "http://127.0.0.1:1", sondar=sondar, espera_volta=20,
                         passo_volta=5, dormir=dormir, relogio=lambda: t[0])
    assert pw.chromium.chamadas == 1               # não tentou de novo à toa
    assert "Calada 5" in str(e.value)              # 1ª sonda + 4 esperas de 5 s
    assert e.value.__cause__ is ESTOURO


def test_todas_respondendo_tenta_de_novo_na_hora():
    """O caso das 17:48 de 18/11: estourou e a sonda viu todas respondendo.
    Antes a pessoa lia "tente de novo"; agora o app tenta sozinho."""
    pw = _Pw(ESTOURO, "browser")
    sonos = []
    assert central.conectar(pw, "http://127.0.0.1:1",
                            sondar=lambda e: [_s("1", True)], dormir=sonos.append) == "browser"
    assert pw.chromium.chamadas == 2 and sonos == []


def test_segunda_tentativa_que_estoura_da_o_recado_da_nova_sonda():
    sondas = iter([[_s("1", True, "Primeira")], [_s("2", False, "Segunda")]])
    pw = _Pw(ESTOURO, PWTimeout("Timeout de novo"))
    with pytest.raises(central.ChromeSemResposta) as e:
        central.conectar(pw, "http://127.0.0.1:1", sondar=lambda _e: next(sondas))
    assert "“Segunda”" in str(e.value)
    assert pw.chromium.chamadas == 2


def test_sonda_que_falha_nao_tenta_de_novo():
    def sondar(_e):
        raise ConnectionRefusedError("porta fechada")
    pw = _Pw(ESTOURO, "browser")
    with pytest.raises(central.ChromeSemResposta, match="não consegui conferir"):
        central.conectar(pw, "http://127.0.0.1:1", sondar=sondar)
    assert pw.chromium.chamadas == 1


def test_erro_que_nao_e_estouro_na_segunda_passa_igual():
    erro = RuntimeError("ECONNREFUSED")
    pw = _Pw(ESTOURO, erro)
    with pytest.raises(RuntimeError) as e:
        central.conectar(pw, "http://127.0.0.1:1", sondar=lambda _e: [_s("1", True)])
    assert e.value is erro


# ------------------------------------------------------------------ a fila


def test_conectar_com_acesso_segura_a_fila(tmp_path):
    a = central.Acesso("principal", tmp_path / "p", 9230)
    vistos = []
    pw = _Pw("browser", antes=lambda: vistos.append(central.caminho_fila(a).exists()))
    central.conectar(pw, "http://127.0.0.1:1", acesso=a)
    assert vistos == [True]                        # dentro da fila
    assert not central.caminho_fila(a).exists()    # e solta no fim


def test_conectar_sem_acesso_nao_tem_fila():
    assert central.conectar(_Pw("browser"), "http://127.0.0.1:1") == "browser"


def test_fila_poe_um_de_cada_vez(tmp_path):
    a = central.Acesso("principal", tmp_path / "p", 9230)
    dentro, maximo = [0], [0]
    trava = threading.Lock()

    def trabalho():
        with central.fila(a, espera=10):
            with trava:
                dentro[0] += 1
                maximo[0] = max(maximo[0], dentro[0])
            time.sleep(0.05)
            with trava:
                dentro[0] -= 1
    th = [threading.Thread(target=trabalho) for _ in range(4)]
    for x in th:
        x.start()
    for x in th:
        x.join()
    assert maximo[0] == 1


def test_fila_ocupada_e_timeouterror(tmp_path):
    """No app `TimeoutError` quer dizer "outro robô está entrando no ERP" —
    é o que está acontecendo quando a fila não anda."""
    a = central.Acesso("principal", tmp_path / "p", 9230)
    erro = []
    with central.fila(a):
        def outro():
            try:
                with central.fila(a, espera=0.2):
                    pass
            except TimeoutError as e:
                erro.append(e)
        t = threading.Thread(target=outro)
        t.start()
        t.join()
    assert erro


def test_quem_conecta_passa_o_acesso():
    """Os três que conectam no central entram na fila."""
    from anexar import mc_client
    from erp import login_principal
    assert "acesso=self.acesso" in inspect.getsource(central.AbaCentral.__enter__)
    assert "acesso=self._acesso" in inspect.getsource(mc_client.MCClient)
    assert "acesso=self.acesso" in inspect.getsource(login_principal)


# --------------------------------------------------------- faxina dos mortos


def test_faxina_de_uma_passada_fecha_so_a_aba_de_robo_morto(tmp_path):
    """O que `faxina.limpar_mortos` faz (o conftest a troca por nada, para
    nenhum teste falar com o Chrome de verdade): uma `Faxina` nova, uma
    passada, e só a aba registrada por processo morto fecha."""
    a = central.Acesso("principal", tmp_path / "p", 9230)
    reg = tmp_path / faxina.PASTA_REGISTRO
    faxina.registrar("MORTA", 9230, tmp_path, pid=111)
    faxina.registrar("VIVA", 9230, tmp_path, pid=222)
    fechadas = []
    fx = faxina.Faxina(listar=lambda _a: [{"id": "MORTA", "url": "about:blank"},
                                          {"id": "VIVA", "url": "about:blank"},
                                          {"id": "DE-NINGUEM", "url": "about:blank"}],
                       fechar=lambda _a, t: fechadas.append(t),
                       pid_vivo=lambda pid: pid == 222, pasta_reg=reg)
    assert len(fx.passar(a, logado=False)) == 1
    assert fechadas == ["MORTA"]
    assert [p.name for p in reg.glob("*.json")] == ["222-VIVA.json"]


def test_limpar_mortos_e_uma_faxina_de_uma_passada():
    fonte = inspect.getsource(faxina)
    assert "def limpar_mortos" in fonte
    assert "Faxina(pasta_reg=pasta_registro(pasta), **kw).passar(a, logado=False)" in fonte


# ------------------------------------------------------------------- cdp_cru


class _Resp:
    def __init__(self, corpo=b""):
        self._c = corpo

    def __enter__(self):
        return self

    def __exit__(self, *e):
        return False

    def read(self):
        return self._c


class _ChromeHttp:
    """`/json/new` e `/json/close` de mentira, anotando a fila na hora."""

    def __init__(self, a):
        self.a, self.pedidos, self.fila_no_new = a, [], None

    def __call__(self, pedido, timeout=None):
        url = getattr(pedido, "full_url", pedido)
        self.pedidos.append(url)
        if "/json/new" in url:
            assert pedido.get_method() == "PUT"
            self.fila_no_new = central.caminho_fila(self.a).exists()
            return _Resp(json.dumps({"id": "T1", "webSocketDebuggerUrl":
                                     "ws://127.0.0.1:1/devtools/page/T1"}).encode())
        return _Resp()


class _Canal:
    """O websocket da aba, de mentira: responde ao que o `cdp_cru` pede."""

    def __init__(self, cabecalhos=None, respostas=None):
        self.enviados, self.fechou, self._eventos = [], False, []
        self.cabecalhos = cabecalhos or {}
        self.respostas = list(respostas or [])

    def __call__(self, ws, prazo):                 # faz o papel do construtor
        return self

    def enviar(self, metodo, params=None, *, sessao=None):
        self.enviados.append(metodo)
        if metodo == "Page.navigate":
            for host, cab in self.cabecalhos.items():
                self._eventos.append({"method": "Network.requestWillBeSent", "params": {
                    "request": {"url": f"https://{host}/x", "headers": cab}}})
        return 1

    def proxima(self, limite):
        if self._eventos:
            return self._eventos.pop(0)
        raise central._SemResposta()

    def pedir(self, metodo, params=None, *, sessao=None, prazo=3.0):
        self.enviados.append(metodo)
        if metodo == "Runtime.evaluate":
            if params["expression"] == "document.readyState":
                return {"result": {"result": {"value": "complete"}}}
            return {"result": {"result": {"value": self.respostas.pop(0)}}}
        return {"result": {}}

    def fechar(self):
        self.fechou = True


CAB = {"legacy-api.maiscontroleerp.com.br": {"Authorization": "tok-legado", "user-id": "7"},
       "prod-erp-api.maiscontroleerp.com.br": {"authorization": "Bearer jwt"}}


def _aba(tmp_path, canal, monkeypatch):
    a = central.Acesso("principal", tmp_path / "p", 9230)
    http = _ChromeHttp(a)
    monkeypatch.setattr(faxina, "pasta_registro", lambda pasta=None: tmp_path / "reg")
    aba = cdp_cru.AbaCdp(a, abrir=http, canal=canal,
                         garantir=lambda _a: "http://127.0.0.1:9230")
    return aba, http, a


def test_cdp_cru_abre_na_fila_registra_captura_e_fecha(tmp_path, monkeypatch):
    canal = _Canal(CAB, [{"status": 200, "dados": {"ok": 1}}])
    aba, http, a = _aba(tmp_path, canal, monkeypatch)
    s = cdp_cru.SessaoCdp(aba=aba)
    assert http.fila_no_new is True                        # abriu dentro da fila
    assert not central.caminho_fila(a).exists()            # e soltou a fila
    assert len(list((tmp_path / "reg").glob("*.json"))) == 1   # registrada
    assert s.cabecalhos_para("https://legacy-api.maiscontroleerp.com.br/x") == {
        "authorization": "tok-legado", "user-id": "7"}
    assert s.cabecalhos_para("https://prod-erp-api.maiscontroleerp.com.br/y") == {
        "authorization": "Bearer jwt"}
    assert "Page.reload" not in canal.enviados             # nunca recarrega aba
    assert s.pedir("https://legacy-api.maiscontroleerp.com.br/x") == {"ok": 1}
    s.fechar()
    s.fechar()                                             # pode repetir
    assert [u for u in http.pedidos if "/json/close/" in u] == [
        "http://127.0.0.1:9230/json/close/T1"]
    assert canal.fechou
    assert not list((tmp_path / "reg").glob("*.json"))     # desregistrou


def test_cdp_cru_get_com_401_recaptura_uma_vez(tmp_path, monkeypatch):
    canal = _Canal(CAB, [{"status": 401, "dados": None}, {"status": 200, "dados": [1]}])
    aba, _http, _a = _aba(tmp_path, canal, monkeypatch)
    with cdp_cru.SessaoCdp(aba=aba) as s:
        assert s.pedir("https://legacy-api.maiscontroleerp.com.br/x") == [1]
    assert canal.enviados.count("Page.navigate") == 2


def test_cdp_cru_post_com_401_nao_repete(tmp_path, monkeypatch):
    canal = _Canal(CAB, [{"status": 401, "dados": None}])
    aba, _http, _a = _aba(tmp_path, canal, monkeypatch)
    with cdp_cru.SessaoCdp(aba=aba) as s:
        with pytest.raises(ErpErro) as e:
            s.pedir("https://legacy-api.maiscontroleerp.com.br/x", metodo="POST", corpo={})
    assert e.value.codigo == 401
    assert canal.enviados.count("Page.navigate") == 1


def test_cdp_cru_sem_login_fecha_a_aba_e_explica(tmp_path, monkeypatch):
    canal = _Canal({})                                     # tela não mandou token
    aba, http, _a = _aba(tmp_path, canal, monkeypatch)
    monkeypatch.setattr(cdp_cru, "PRAZO_CAPTURA", 0.1)
    with pytest.raises(ErpErro, match="está logado"):
        cdp_cru.SessaoCdp(aba=aba)
    assert any("/json/close/T1" in u for u in http.pedidos)
    assert not list((tmp_path / "reg").glob("*.json"))


def test_cdp_cru_sem_acesso_ligado_explica(tmp_path):
    with pytest.raises(ErpErro, match="não está ligado"):
        cdp_cru.AbaCdp("principal", pasta=tmp_path)
