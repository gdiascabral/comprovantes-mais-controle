# -*- coding: utf-8 -*-
"""Quando o Playwright não consegue conectar no Chrome central.

04/11 e 09/11/2026: `connect_over_cdp` estourou 180 s no Chrome central
(porta 9230) e quem esperava só via `Timeout 180000ms exceeded`. Em 09/11 uma
sonda alvo por alvo achou UMA aba do ERP que não respondia a `Runtime.enable`
enquanto as outras respondiam. Aqui: o prazo menor, a sonda e o recado.

Nada aqui abre navegador nem fala com o Chrome de verdade: o "Chrome" é um
servidor websocket falso, num socket local de porta sorteada, que responde ao
CDP como o Chrome responde — inclusive ficando calado no alvo travado.
"""
import base64
import hashlib
import json
import socket
import struct
import threading
import time

import pytest
from playwright.sync_api import TimeoutError as PWTimeout

from erp import central

_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


# ------------------------------------------------------------ o Chrome falso


def _ler_exato(conn, buf, n):
    while len(buf[0]) < n:
        dados = conn.recv(65536)
        if not dados:
            raise ConnectionError("fechou")
        buf[0] += dados
    saida, buf[0] = buf[0][:n], buf[0][n:]
    return saida


def _ler_quadro(conn, buf):
    b0, b1 = _ler_exato(conn, buf, 2)
    n = b1 & 0x7F
    if n == 126:
        n = struct.unpack(">H", _ler_exato(conn, buf, 2))[0]
    elif n == 127:
        n = struct.unpack(">Q", _ler_exato(conn, buf, 8))[0]
    assert b1 & 0x80, "o cliente tem de mascarar todo quadro (RFC 6455)"
    mascara = _ler_exato(conn, buf, 4)
    dados = bytes(x ^ mascara[i % 4] for i, x in enumerate(_ler_exato(conn, buf, n)))
    return b0 & 0x0F, dados


def _quadro_do_servidor(op, dados, fin=True):
    n = len(dados)
    if n < 126:
        cab = bytes([(0x80 if fin else 0) | op, n])
    elif n < 65536:
        cab = bytes([(0x80 if fin else 0) | op, 126]) + struct.pack(">H", n)
    else:
        cab = bytes([(0x80 if fin else 0) | op, 127]) + struct.pack(">Q", n)
    return cab + dados


class ChromeFalso:
    """Um Chrome de mentira: fala o handshake do websocket e o pouco de CDP
    que a sonda usa. `mudos` não respondem ao `Runtime.enable`;
    `mudos_no_attach` nem aceitam a sessão."""

    def __init__(self, alvos, *, mudos=(), mudos_no_attach=(), ping=False,
                 fragmentar=False, aceite_errado=False):
        self.alvos = alvos
        self.mudos, self.mudos_no_attach = set(mudos), set(mudos_no_attach)
        self.ping, self.fragmentar = ping, fragmentar
        self.aceite_errado = aceite_errado
        self.recebidos: list[dict] = []
        self.pongs = 0
        self.fechou_limpo = False
        self._srv = socket.socket()
        self._srv.bind(("127.0.0.1", 0))
        self._srv.listen(4)
        self.porta = self._srv.getsockname()[1]
        self._t = threading.Thread(target=self._servir, daemon=True)
        self._t.start()

    @property
    def endereco(self):
        return f"http://127.0.0.1:{self.porta}"

    def abrir(self, url, timeout):
        """O `urlopen` do `/json/version`, sem rede."""
        assert url == f"{self.endereco}/json/version"
        corpo = json.dumps({"Browser": "Chrome/157", "webSocketDebuggerUrl":
                            f"ws://127.0.0.1:{self.porta}/devtools/browser/x"})

        class _R:
            def __enter__(s): return s
            def __exit__(s, *e): return False
            def read(s): return corpo.encode()
        return _R()

    def metodos(self):
        return [m["method"] for m in self.recebidos]

    def fechar(self):
        self._srv.close()

    def _enviar(self, conn, obj):
        dados = json.dumps(obj).encode()
        if self.ping:
            conn.sendall(_quadro_do_servidor(0x9, b"oi"))
        if self.fragmentar and len(dados) > 4:
            meio = len(dados) // 2
            conn.sendall(_quadro_do_servidor(0x1, dados[:meio], fin=False))
            if self.ping:              # controle no meio dos fragmentos vale
                conn.sendall(_quadro_do_servidor(0x9, b"no meio"))
            conn.sendall(_quadro_do_servidor(0x0, dados[meio:]))
        else:
            conn.sendall(_quadro_do_servidor(0x1, dados))

    def _servir(self):
        try:
            conn, _ = self._srv.accept()
        except OSError:
            return
        buf = [b""]
        try:
            while b"\r\n\r\n" not in buf[0]:
                buf[0] += conn.recv(4096)
            cab, buf[0] = buf[0].split(b"\r\n\r\n", 1)
            linhas = cab.decode().split("\r\n")
            assert linhas[0].startswith("GET /devtools/browser/x ")
            campos = {k.lower(): v.strip() for k, v in
                      (x.split(":", 1) for x in linhas[1:] if ":" in x)}
            chave = campos["sec-websocket-key"].encode()
            aceite = base64.b64encode(hashlib.sha1(chave + _GUID).digest())
            if self.aceite_errado:
                aceite = base64.b64encode(b"x" * 20)
            conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                         b"Connection: Upgrade\r\nSec-WebSocket-Accept: "
                         + aceite + b"\r\n\r\n")
            while True:
                op, dados = _ler_quadro(conn, buf)
                if op == 0x8:
                    self.fechou_limpo = True
                    return
                if op == 0xA:
                    self.pongs += 1
                    continue
                msg = json.loads(dados)
                self.recebidos.append(msg)
                self._responder(conn, msg)
        except (OSError, ConnectionError):
            return
        finally:
            conn.close()

    def _responder(self, conn, msg):
        metodo, mid = msg["method"], msg["id"]
        params = msg.get("params") or {}
        if metodo == "Target.getTargets":
            infos = [{"targetId": "B", "type": "browser", "title": "", "url": ""}]
            infos += self.alvos
            self._enviar(conn, {"id": mid, "result": {"targetInfos": infos}})
        elif metodo == "Target.attachToTarget":
            alvo = params["targetId"]
            assert params.get("flatten") is True
            if alvo in self.mudos_no_attach:
                return
            if alvo == "SUMIU":
                self._enviar(conn, {"id": mid, "error": {"code": -32602,
                                                         "message": "No target"}})
                return
            self._enviar(conn, {"id": mid, "result": {"sessionId": f"S-{alvo}"}})
        elif metodo == "Runtime.enable":
            alvo = msg["sessionId"][2:]
            if alvo in self.mudos:
                return                       # a aba travada: silêncio
            # evento da sessão antes da resposta, como o Chrome faz
            self._enviar(conn, {"method": "Runtime.executionContextCreated",
                                "sessionId": msg["sessionId"], "params": {}})
            self._enviar(conn, {"id": mid, "sessionId": msg["sessionId"],
                                "result": {}})
        elif metodo == "Target.detachFromTarget":
            self._enviar(conn, {"id": mid, "result": {}})
        else:
            self._enviar(conn, {"id": mid, "error": {"code": -32601,
                                                     "message": "desconhecido"}})


def _alvo(tid, tipo="page", titulo="", url=""):
    return {"targetId": tid, "type": tipo, "title": titulo or tid,
            "url": url or f"https://exemplo.invalid/{tid}"}


#: O que a sonda pode pedir ao Chrome. Nada que feche, recarregue ou navegue.
_PERMITIDOS = {"Target.getTargets", "Target.attachToTarget", "Runtime.enable",
               "Target.detachFromTarget"}


@pytest.fixture
def chrome():
    feitos = []

    def fazer(*a, **k):
        c = ChromeFalso(*a, **k)
        feitos.append(c)
        return c
    yield fazer
    for c in feitos:
        c.fechar()


# ------------------------------------------------------------------ a sonda


def test_sonda_acha_a_aba_que_nao_responde(chrome):
    c = chrome([_alvo("ERP", titulo="Mais Controle ERP",
                      url="https://acessar.maiscontroleerp.com.br/#/app/x"),
                _alvo("OK"),
                _alvo("SW", "service_worker"),
                _alvo("POP", "other", url="chrome://omnibox-popup.top-chrome/")],
               mudos={"ERP"})
    inicio = time.monotonic()
    alvos = central.sondar_alvos(c.endereco, prazo_alvo=0.5, abrir=c.abrir)
    assert time.monotonic() - inicio < 3
    por_id = {a.id: a for a in alvos}
    assert set(por_id) == {"ERP", "OK", "SW", "POP"}       # o "browser" fica fora
    assert por_id["ERP"].responde is False
    assert all(por_id[x].responde is True for x in ("OK", "SW", "POP"))
    assert por_id["ERP"].titulo == "Mais Controle ERP"
    # Presença primeiro (o captador vê os pedidos), depois a ausência.
    assert c.metodos().count("Target.attachToTarget") == 4
    assert c.metodos().count("Target.detachFromTarget") == 4
    assert set(c.metodos()) <= _PERMITIDOS                  # nunca fecha nada
    assert c.fechou_limpo


def test_aba_que_nem_aceita_a_sessao_conta_como_muda(chrome):
    c = chrome([_alvo("A"), _alvo("B")], mudos_no_attach={"A"})
    alvos = central.sondar_alvos(c.endereco, prazo_alvo=0.4, abrir=c.abrir)
    por_id = {a.id: a for a in alvos}
    assert por_id["A"].responde is False and por_id["B"].responde is True
    # sem sessão, não há o que destacar nem Runtime para pedir
    assert ("Runtime.enable", "S-A") not in [
        (m["method"], m.get("sessionId")) for m in c.recebidos]


def test_alvo_que_sumiu_no_meio_nao_vira_mudo(chrome):
    c = chrome([_alvo("SUMIU"), _alvo("OK")])
    por_id = {a.id: a for a in central.sondar_alvos(c.endereco, prazo_alvo=0.4,
                                                    abrir=c.abrir)}
    assert por_id["SUMIU"].responde is None
    assert por_id["OK"].responde is True


def test_sonda_tem_teto_total(chrome):
    c = chrome([_alvo(x) for x in "ABCDE"], mudos=set("ABCDE"))
    inicio = time.monotonic()
    alvos = central.sondar_alvos(c.endereco, prazo_alvo=0.3, prazo_total=0.7,
                                 abrir=c.abrir)
    gasto = time.monotonic() - inicio
    assert gasto < 3, gasto
    estados = [a.responde for a in alvos]
    assert False in estados                       # sondou alguns
    assert None in estados                        # e desistiu do resto no teto
    assert len(alvos) == 5


def test_canal_aguenta_ping_fragmento_e_mensagem_grande(chrome):
    titulo = "x" * 70000                           # comprimento de 64 bits
    c = chrome([_alvo("A", titulo=titulo), _alvo("B", titulo="y" * 300)],
               ping=True, fragmentar=True)
    alvos = central.sondar_alvos(c.endereco, prazo_alvo=1.0, abrir=c.abrir)
    assert [a.responde for a in alvos] == [True, True]
    assert alvos[0].titulo == titulo
    assert c.pongs > 0                             # respondeu ao ping


def test_canal_confere_o_aceite_do_handshake(chrome):
    c = chrome([_alvo("A")], aceite_errado=True)
    with pytest.raises(ConnectionError, match="handshake"):
        central.sondar_alvos(c.endereco, prazo_alvo=0.5, abrir=c.abrir)


@pytest.mark.parametrize("url", ["ws://10.1.2.3:9230/devtools/browser/x",
                                 "ws://exemplo.invalid:9230/x",
                                 "wss://127.0.0.1:9230/x"])
def test_canal_so_fala_com_chrome_local(url, monkeypatch):
    def nunca(*a, **k):
        raise AssertionError("não podia abrir conexão")
    monkeypatch.setattr(central.socket, "create_connection", nunca)
    with pytest.raises(ValueError):
        central._CanalCdp(url, 0.5)


# ------------------------------------------------------------------ o recado


def _s(tid, responde, tipo="page", titulo="", url="https://h.invalid/x"):
    return central.AlvoSondado(tid, tipo, titulo or tid, url, responde, 12.0)


def test_recado_nomeia_a_aba_muda_e_diz_o_que_fazer():
    alvos = [_s("1", True, titulo="Outra"),
             _s("2", False, titulo="Mais Controle ERP",
                url="https://acessar.maiscontroleerp.com.br/#/app/y")]
    texto = central.recado_sem_resposta("http://127.0.0.1:9230", 45, alvos)
    assert "45 s" in texto and "9230" in texto
    assert "“Mais Controle ERP”" in texto
    assert "acessar.maiscontroleerp.com.br" in texto
    assert "/#/app/y" not in texto                 # só o host, nunca o caminho
    assert "“Outra”" not in texto
    assert "feche" in texto.lower() and "tente de novo" in texto
    assert "Não feche o Chrome inteiro" in texto
    assert "Timeout" not in texto


def test_recado_quando_todas_respondem_agora():
    texto = central.recado_sem_resposta("http://127.0.0.1:9230", 45,
                                        [_s("1", True), _s("2", True)])
    assert "todas as 2 abas respondem" in texto and "tente de novo" in texto


def test_recado_quando_a_sonda_falha():
    texto = central.recado_sem_resposta("http://127.0.0.1:9230", 45, None,
                                        OSError("recusou"))
    assert "não consegui conferir as abas" in texto
    assert "tente de novo" in texto


def test_recado_com_muitas_mudas_resume():
    alvos = [_s(str(i), False, titulo=f"Aba {i}") for i in range(6)]
    texto = central.recado_sem_resposta("http://127.0.0.1:9230", 45, alvos)
    assert "“Aba 0”" in texto and "“Aba 2”" in texto and "“Aba 3”" not in texto
    assert "e mais 3" in texto


def test_titulo_comprido_e_cortado_no_recado():
    alvos = [_s("1", False, titulo="T" * 300)]
    texto = central.recado_sem_resposta("http://127.0.0.1:9230", 45, alvos)
    assert "T" * 300 not in texto and "…" in texto


# ------------------------------------------------------------------ conectar


class _Cromo:
    def __init__(self, efeito):
        self.efeito, self.pedidos = efeito, []

    def connect_over_cdp(self, endereco, **kw):
        self.pedidos.append((endereco, kw))
        if isinstance(self.efeito, BaseException):
            raise self.efeito
        return self.efeito


class _PwDuble:
    def __init__(self, efeito):
        self.chromium = _Cromo(efeito)


def test_conectar_passa_o_prazo_menor_ao_playwright():
    pw = _PwDuble("browser")
    sondas = []
    assert central.conectar(pw, "http://127.0.0.1:1", sondar=sondas.append) == "browser"
    assert pw.chromium.pedidos == [("http://127.0.0.1:1",
                                    {"timeout": central.PRAZO_CONEXAO * 1000})]
    assert central.PRAZO_CONEXAO < 180            # o de antes era 180 s
    assert sondas == []                           # conectou: não sonda


def test_estouro_sonda_e_vira_recado_em_portugues():
    erro = PWTimeout("BrowserType.connect_over_cdp: Timeout 45000ms exceeded.")
    pw = _PwDuble(erro)
    pedidos = []

    def sondar(endereco):
        pedidos.append(endereco)
        return [_s("1", False, titulo="Mais Controle ERP")]

    with pytest.raises(central.ChromeSemResposta) as e:
        central.conectar(pw, "http://127.0.0.1:1", prazo=45, sondar=sondar)
    assert pedidos == ["http://127.0.0.1:1"]
    assert "“Mais Controle ERP”" in str(e.value)
    assert e.value.__cause__ is erro
    assert e.value.alvos[0].responde is False
    assert "não responde" in e.value.relatorio()


def test_erro_que_nao_e_estouro_passa_igual_e_nao_sonda():
    erro = RuntimeError("ECONNREFUSED")
    pw = _PwDuble(erro)
    sondas = []
    with pytest.raises(RuntimeError) as e:
        central.conectar(pw, "http://127.0.0.1:1", sondar=sondas.append)
    assert e.value is erro and sondas == []


def test_estouro_com_a_sonda_falhando_ainda_da_recado():
    pw = _PwDuble(PWTimeout("Timeout 45000ms exceeded."))

    def sondar(_e):
        raise ConnectionRefusedError("porta fechada")
    with pytest.raises(central.ChromeSemResposta, match="não consegui conferir"):
        central.conectar(pw, "http://127.0.0.1:1", sondar=sondar)


def test_estouro_nao_e_timeouterror_para_quem_trata_trava():
    """`except TimeoutError` no app quer dizer "a trava de arquivo estourou"
    (mc_client.garantir_login, login_principal): o recado do Chrome não pode
    cair ali e virar "outro robô está entrando"."""
    assert not issubclass(central.ChromeSemResposta, TimeoutError)


def test_ponta_a_ponta_com_o_chrome_falso(chrome):
    """O `conectar` com a sonda DE VERDADE contra o Chrome falso: o recado
    nomeia a aba que o Chrome falso deixa calada."""
    c = chrome([_alvo("ERP", titulo="Mais Controle ERP"), _alvo("OK")],
               mudos={"ERP"})
    pw = _PwDuble(PWTimeout("Timeout 45000ms exceeded."))
    with pytest.raises(central.ChromeSemResposta) as e:
        central.conectar(pw, c.endereco, sondar=lambda end: central.sondar_alvos(
            end, prazo_alvo=0.4, abrir=c.abrir))
    assert "“Mais Controle ERP”" in str(e.value)
    assert "“OK”" not in str(e.value)


# -------------------------------------------- quem conecta passa por conectar


def test_aba_central_usa_o_prazo_e_para_o_driver_no_estouro(tmp_path, monkeypatch):
    reg = []

    class _Pw:
        def __init__(self):
            self.chromium = _Cromo(PWTimeout("Timeout exceeded"))
        def stop(self):
            reg.append("pw.stop")

    pw = _Pw()
    monkeypatch.setattr(central, "sondar_alvos",
                        lambda end, **k: [_s("1", False, titulo="Travada")])
    a = central.Acesso("principal", tmp_path / "p", 9230)
    with pytest.raises(central.ChromeSemResposta, match="Travada"):
        with central.AbaCentral(a, pw=pw, garantir=lambda _a: "http://127.0.0.1:1"):
            pass
    assert pw.chromium.pedidos[0][1] == {"timeout": central.PRAZO_CONEXAO * 1000}
    assert reg == ["pw.stop"]


def test_login_principal_nao_corta_o_recado(tmp_path):
    from erp import login_principal
    from erp.sessao import ErpErro
    login_principal.esquecer()
    recado = central.recado_sem_resposta(
        "http://127.0.0.1:9230", 45, [_s("1", False, titulo="Mais Controle ERP")])
    assert len(recado) > 160                      # o corte antigo era em 160

    class _Cai:
        def __enter__(self):
            raise central.ChromeSemResposta("http://127.0.0.1:9230", 45,
                                            [_s("1", False, titulo="Mais Controle ERP")])
        def __exit__(self, *e):
            return False

    a = central.Acesso("principal", tmp_path / "p", 9230)
    linhas = []
    with pytest.raises(ErpErro) as e:
        login_principal.garantir_logado(a, abrir_pagina=_Cai, log=linhas.append,
                                        trava_arquivo=lambda: None)
    assert str(e.value) == recado
    assert any("não responde" in x for x in linhas)   # o detalhe vai ao log
    login_principal.esquecer()


def test_sessao_pela_pagina_entrega_o_recado_inteiro():
    """A leitura (`SessaoPelaPagina`) embrulhava o erro da aba em "não
    consegui abrir a aba no Chrome central: <erro>". O recado já diz tudo:
    sai como `ErpErro` com o texto dele, e o detalhe vai ao diagnóstico."""
    from erp.sessao import ErpErro
    from erp.sessao_pagina import SessaoPelaPagina
    erro = central.ChromeSemResposta("http://127.0.0.1:9230", 45,
                                     [_s("1", False, titulo="Mais Controle ERP")])

    class _Cai:
        def __enter__(self):
            raise erro
        def __exit__(self, *e):
            return False

    diags = []
    with pytest.raises(ErpErro) as e:
        SessaoPelaPagina.do_acesso("principal", fabrica_aba=_Cai,
                                   espera_captura=1.0, diag=diags.append,
                                   ja_pedido=False)
    assert str(e.value) == str(erro)
    assert e.value.__cause__ is erro
    assert any("não responde" in d for d in diags)
