# -*- coding: utf-8 -*-
"""Aportes: a leitura dos cadastros do ERP sobrevive a um login feito por fora.

O ERP aceita UMA sessão por usuário. Um login por fora — o do próprio app na
abertura, no "Atualizar contas" ou na coleta dos saldos — cancela o token curto
do legacy-api do Chrome, e o JWT do prod-erp-api continua valendo. Em
06/10/2026 isso fez a leitura vir pela metade (contas e participantes sim,
categorias 401), a metade ficou guardada como se fosse a leitura inteira, e o
"Lançar" acusou "Categoria não encontrada ... Nada parecido no cadastro" para
cadastros que existiam. Reproduzido ao vivo: login por fora entre a captura e a
leitura -> 401 só no legacy; `garantir_login` + nova captura -> leitura inteira.
"""
import pytest

from aportes import aportes_frame as af
from aportes import mc_catalogos as mcc


# ------------------------------------------------------------------ Catalogos
class _PaginaRecusa:
    """`evaluate` como o _JS_FETCH responde: {__erro: status} quando o ERP recusa."""

    def __init__(self, recusar):
        self.recusar = recusar

    def evaluate(self, _js, arg):
        url = arg["url"]
        if self.recusar(url):
            return {"__erro": 401}
        return [{"id": "1", "name": "X"}]


def test_carregar_levanta_recusa_com_o_status_e_o_endereco():
    cat = mcc.Catalogos(_PaginaRecusa(lambda u: "legacy-api" in u), {}, log=lambda *_: None)
    with pytest.raises(mcc.ErpRecusou) as e:
        cat.carregar()
    assert e.value.status == 401
    assert "categories/all" in e.value.url
    assert "o ERP respondeu 401" in str(e.value)          # o recado continua o mesmo
    assert isinstance(e.value, RuntimeError)


# --------------------------------------------------------------- a aba
class _Mc:
    def __init__(self):
        self.page = object()
        self.logins = 0

    def garantir_login(self):
        self.logins += 1
        return True


class _Anx:
    def __init__(self):
        self.mc = _Mc()

    def garantir_sessao(self, _log):
        return object()


class _CatFalso:
    pass


def _aba(raiz, monkeypatch, respostas):
    """Aba com `_ler_cadastros` dublado: cada chamada consome uma resposta
    (uma exceção é levantada, um objeto é devolvido)."""
    anx = _Anx()
    aba = af.AportesFrame(raiz, anx)
    fila = list(respostas)
    obras = []

    def ler():
        r = fila.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    aba.anotado = []
    monkeypatch.setattr(aba, "_log", lambda txt="", *_a, **_k: aba.anotado.append(str(txt)))
    monkeypatch.setattr(aba, "_ler_cadastros", ler)
    monkeypatch.setattr(aba, "_carregar_obras", lambda api: obras.append(aba.catalogos))
    return aba, anx, obras


def test_401_do_legado_refaz_o_login_e_le_de_novo(raiz, monkeypatch):
    cat = _CatFalso()
    aba, anx, obras = _aba(raiz, monkeypatch,
                           [mcc.ErpRecusou(401, "https://legacy-api/x/categories/all"), cat])
    try:
        aba._preparar_sessao()
        assert anx.mc.logins == 1
        assert aba.catalogos is cat
        assert obras == [cat]                      # as obras usam a leitura boa
        assert any("entrando de novo" in t for t in aba.anotado)
    finally:
        aba.destroy()


def test_pagina_que_cai_no_login_tambem_refaz_o_login(raiz, monkeypatch):
    """Sem o token velho, a página recarregada com a sessão cancelada vai para
    o login e não faz as chamadas: a captura falha antes de haver 401."""
    cat = _CatFalso()
    aba, anx, obras = _aba(raiz, monkeypatch,
                           [af.AutenticacaoNaoCapturada("não consegui a autenticação de x"), cat])
    try:
        aba._preparar_sessao()
        assert anx.mc.logins == 1
        assert aba.catalogos is cat
    finally:
        aba.destroy()


def test_leitura_que_falha_duas_vezes_nao_fica_guardada(raiz, monkeypatch):
    aba, anx, obras = _aba(raiz, monkeypatch,
                           [mcc.ErpRecusou(401, "u"), mcc.ErpRecusou(401, "u")])
    try:
        with pytest.raises(mcc.ErpRecusou):
            aba._preparar_sessao()
        assert anx.mc.logins == 1                  # tenta uma vez só, não em laço
        assert aba.catalogos is None               # o próximo comando lê de novo
        assert obras == []
    finally:
        aba.destroy()


def test_outra_recusa_nao_relogin_e_nao_guarda(raiz, monkeypatch):
    aba, anx, _ = _aba(raiz, monkeypatch, [mcc.ErpRecusou(500, "u")])
    try:
        with pytest.raises(mcc.ErpRecusou):
            aba._preparar_sessao()
        assert anx.mc.logins == 0
        assert aba.catalogos is None
    finally:
        aba.destroy()


def test_leitura_ja_feita_nao_e_refeita(raiz, monkeypatch):
    cat = _CatFalso()
    aba, anx, _ = _aba(raiz, monkeypatch, [cat])
    try:
        aba._preparar_sessao()
        aba._preparar_sessao()                     # a fila só tinha uma resposta
        assert aba.catalogos is cat
    finally:
        aba.destroy()


# ------------------------------------------------- a captura não usa token velho
class _Req:
    def __init__(self, url, token):
        self.url = url
        self.headers = {"authorization": f"Bearer {token}", "company-id": "c",
                        "user-id": "u", "organization-unit-id": "o"}


class _PaginaCaptura:
    url = "https://acessar.maiscontroleerp.com.br/#/payable-installments"

    def __init__(self):
        self.ouvintes = []

    def on(self, _ev, fn):
        self.ouvintes.append(fn)

    def remove_listener(self, _ev, fn):
        self.ouvintes.remove(fn)

    def reload(self, **_k):
        for fn in list(self.ouvintes):
            fn(_Req("https://prod-erp-api.maiscontroleerp.com.br/a", "JWTNOVO"))
            fn(_Req("https://legacy-api.maiscontroleerp.com.br/b", "CURTONOVO"))

    def goto(self, *_a, **_k):
        self.reload()

    def wait_for_timeout(self, _ms):
        pass


def test_captura_descarta_o_token_velho_antes_de_escutar(raiz, monkeypatch):
    anx = _Anx()
    anx.mc.page = _PaginaCaptura()
    aba = af.AportesFrame(raiz, anx)
    try:
        aba._cabecalhos["legacy-api.maiscontroleerp.com.br"] = {"authorization": "Bearer VELHO"}
        monkeypatch.setattr(af.Catalogos, "carregar", lambda self: None)
        cat = aba._ler_cadastros()
        assert aba._cabecalhos["legacy-api.maiscontroleerp.com.br"]["authorization"] == "Bearer CURTONOVO"
        assert cat.headers is aba._cabecalhos
    finally:
        aba.destroy()
