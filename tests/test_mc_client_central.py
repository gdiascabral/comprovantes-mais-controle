# -*- coding: utf-8 -*-
"""MCClient conectado ao Chrome central: entra, trabalha, sai sem fechar nada
dos outros. Sem navegador: o Playwright é dublê."""
import contextlib
import json
import sys

import pytest

import util
from anexar import mc_client
from erp import central


class _P:
    def __init__(self, reg, opener=None):
        self.reg, self._opener, self.fechada, self.ouvintes = reg, opener, False, {}
    def opener(self): return self._opener
    def on(self, ev, fn): self.ouvintes.setdefault(ev, []).append(fn)
    def close(self):
        self.fechada = True
        self.reg.append("page.close")
    def is_closed(self): return self.fechada
    url = ""
    def goto(self, url, **k):
        self.url = url
        self.reg.append(f"goto {url}")
    def bring_to_front(self): self.reg.append("frente")


class _C:
    def __init__(self, reg):
        self.reg, self.pages, self.ouvintes = reg, [_P(reg)], {}
    def new_page(self):
        p = _P(self.reg)
        self.pages.append(p)
        return p
    def on(self, ev, fn): self.ouvintes.setdefault(ev, []).append(fn)
    def close(self): self.reg.append("ctx.close")


class _B:
    def __init__(self, reg): self.reg, self.contexts = reg, [_C(reg)]
    def close(self): self.reg.append("browser.close")


class _PW:
    def __init__(self, reg):
        self.reg = reg
        r = reg
        class _Ch:
            def connect_over_cdp(self, end):
                r.append(f"cdp {end}")
                return _B(r)
            def launch_persistent_context(self, **k):
                raise AssertionError("modo central não lança Chrome próprio")
        self.chromium = _Ch()
    def stop(self): self.reg.append("pw.stop")


@pytest.fixture
def central_falso(tmp_path, monkeypatch):
    reg = []
    a = central.Acesso("principal", tmp_path / "perfil", 9230,
                       tmp_path / "principal.login.dat")
    monkeypatch.setattr(mc_client, "sync_playwright",
                        lambda: type("S", (), {"start": lambda self: _PW(reg)})())
    monkeypatch.setattr(central, "garantir_chrome", lambda a, **k: "http://127.0.0.1:9230")
    monkeypatch.setattr(util, "limpar_historico_de_downloads",
                        lambda *_a, **_k: reg.append("limpou historico"))
    return a, reg


def test_entra_pelo_cdp_e_sai_sem_fechar_o_chrome(central_falso):
    a, reg = central_falso
    mc = mc_client.MCClient(log=lambda *_: None, acesso=a)
    with mc:
        alheia = mc.ctx.pages[0]
        assert mc.central is True and mc.page is not alheia
        assert mc.page in mc._minhas and alheia not in mc._minhas
    assert "cdp http://127.0.0.1:9230" in reg
    assert "ctx.close" not in reg and "browser.close" not in reg
    assert "limpou historico" not in reg
    assert reg[-1] == "pw.stop"
    assert alheia.fechada is False and mc.page.fechada is True


def test_aba_de_outro_robo_nao_e_adotada_nem_ouvida(central_falso):
    a, reg = central_falso
    mc = mc_client.MCClient(log=lambda *_: None, acesso=a)
    with mc:
        de_outro = _P(reg)
        mc._nova_aba(de_outro)
        assert de_outro not in mc._minhas and "download" not in de_outro.ouvintes
        filha = _P(reg, opener=mc.page)
        mc._nova_aba(filha)
        assert filha in mc._minhas
    assert filha.fechada is True and de_outro.fechada is False


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI só no Windows")
def test_credencial_do_acesso_e_usada(central_falso, monkeypatch):
    a, _ = central_falso
    a.credencial.write_bytes(util.proteger_bytes(
        json.dumps({"email": "fulano@exemplo.test", "senha": "s"}).encode()))
    monkeypatch.setattr(mc_client.credenciais, "carregar",
                        lambda: pytest.fail("não devia ler o login.dat do app"))
    mc = mc_client.MCClient(log=lambda *_: None, acesso=a)
    assert mc._credencial() == ("fulano@exemplo.test", "s")


def test_credencial_ilegivel_vira_none_sem_vazar_a_senha(central_falso, monkeypatch):
    a, _ = central_falso
    a.credencial.write_bytes(b"lixo")
    monkeypatch.setattr(util, "revelar_bytes",
                        lambda d: json.dumps({"email": "x", "senha": "segredo"}
                                             ).encode()[:10])
    ditos = []
    monkeypatch.setattr(mc_client.config, "diag", ditos.append)
    mc = mc_client.MCClient(log=lambda *_: None, acesso=a)
    assert mc._credencial() is None
    assert ditos and all("segredo" not in d for d in ditos)


def test_acesso_sem_credencial_usa_o_login_do_app(central_falso, monkeypatch):
    a, _ = central_falso
    a = central.Acesso(a.nome, a.perfil, a.porta, None)
    monkeypatch.setattr(mc_client.credenciais, "carregar",
                        lambda: ("app@exemplo.test", "x"))
    mc = mc_client.MCClient(log=lambda *_: None, acesso=a)
    assert mc._credencial() == ("app@exemplo.test", "x")


def test_garantir_login_central_roda_dentro_da_trava(central_falso, monkeypatch):
    a, _ = central_falso
    passos = []

    @contextlib.contextmanager
    def trava(caminho, *, espera=60.0, velha=120.0):
        passos.append(("trava", caminho, espera, velha))
        yield
        passos.append("solta")

    monkeypatch.setattr(central, "trava", trava)
    mc = mc_client.MCClient(log=lambda *_: None, acesso=a)
    mc.login_principal = False        # aqui se prova a trava, não o principal
    monkeypatch.setattr(mc, "_garantir_login_sem_trava",
                        lambda: passos.append("login") or True)
    assert mc.garantir_login() is True
    assert passos == [("trava", a.perfil.parent / ".principal.login.trava", 600, 600),
                      "login", "solta"]


def test_trava_de_login_ocupada_vira_false_com_recado(central_falso, monkeypatch):
    a, _ = central_falso

    def trava(caminho, *, espera=60.0, velha=120.0):
        raise TimeoutError(f"trava ocupada há mais de {espera:.0f} s: {caminho}")

    monkeypatch.setattr(central, "trava", trava)
    ditos = []
    mc = mc_client.MCClient(log=ditos.append, acesso=a)
    mc.login_principal = False
    monkeypatch.setattr(mc, "_garantir_login_sem_trava",
                        lambda: pytest.fail("não devia tentar entrar sem a trava"))
    assert mc.garantir_login() is False
    assert any("outro robô está entrando no ERP" in d for d in ditos)


def test_garantir_login_sem_central_nao_usa_trava(monkeypatch):
    monkeypatch.setattr(central, "trava",
                        lambda *a, **k: pytest.fail("sem central não há trava"))
    mc = mc_client.MCClient(log=lambda *_: None)
    monkeypatch.setattr(mc, "_garantir_login_sem_trava", lambda: "direto")
    assert mc.garantir_login() == "direto"


def test_central_ligado_sem_acesso_explicito_entra_em_modo_central(
        central_falso, monkeypatch):
    a, _ = central_falso
    monkeypatch.setattr(central, "ligado", lambda *x, **k: True)
    monkeypatch.setattr(central, "acesso", lambda *x, **k: a)
    mc = mc_client.MCClient(log=lambda *_: None)
    assert mc.central is True and mc._acesso is a


def test_sem_central_continua_lancando_o_chrome_proprio(monkeypatch):
    monkeypatch.setattr(central, "ligado", lambda *a, **k: False)
    mc = mc_client.MCClient(log=lambda *_: None)
    assert mc.central is False


def test_aba_da_pessoa_no_central_e_sempre_nova_e_nao_e_do_robo(central_falso):
    a, reg = central_falso
    mc = mc_client.MCClient(log=lambda *_: None, acesso=a)
    with mc:
        de_outro = mc.ctx.pages[0]
        de_outro.url = "https://app.maiscontroleerp.com.br/#/x"
        assert mc._abas_da_pessoa() == []
        aba = mc.abrir_aba_da_pessoa("https://app.maiscontroleerp.com.br/#/y")
        assert aba is not de_outro and aba is not mc.page
        assert aba not in mc._minhas
        assert aba.url.endswith("#/y")
    assert aba.fechada is False


def test_central_fora_do_ar_nao_liga_o_playwright(central_falso, monkeypatch):
    a, reg = central_falso
    iniciou = []
    monkeypatch.setattr(mc_client, "sync_playwright",
                        lambda: type("S", (), {"start": lambda self: iniciou.append(1)})())

    def cai(_a, **_k):
        raise FileNotFoundError("Chrome não encontrado")

    monkeypatch.setattr(central, "garantir_chrome", cai)
    with pytest.raises(FileNotFoundError):
        with mc_client.MCClient(log=lambda *_: None, acesso=a):
            pass
    assert iniciou == []


def test_cdp_que_falha_para_o_playwright(central_falso, monkeypatch):
    a, reg = central_falso

    class _PWQueCai(_PW):
        def __init__(self, reg):
            super().__init__(reg)
            def cai(end):
                raise RuntimeError("cdp recusou")
            self.chromium.connect_over_cdp = cai

    monkeypatch.setattr(mc_client, "sync_playwright",
                        lambda: type("S", (), {"start": lambda self: _PWQueCai(reg)})())
    with pytest.raises(RuntimeError, match="cdp recusou"):
        with mc_client.MCClient(log=lambda *_: None, acesso=a):
            pass
    assert reg == ["pw.stop"]


def test_timeout_de_dentro_do_login_nao_vira_trava_ocupada(central_falso, monkeypatch):
    a, _ = central_falso
    mc = mc_client.MCClient(log=lambda *_: None, acesso=a)
    mc.login_principal = False

    def cai():
        raise TimeoutError("rede")

    monkeypatch.setattr(mc, "_garantir_login_sem_trava", cai)
    with pytest.raises(TimeoutError, match="rede"):
        mc.garantir_login()
    assert not (a.perfil.parent / ".principal.login.trava").exists()
