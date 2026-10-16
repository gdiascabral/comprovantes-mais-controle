# -*- coding: utf-8 -*-
"""Aportes: a leitura dos cadastros não sobrevive ao Chrome que ela leu.

Visto em 09/10/2026 (v2.0.233): outra aba encontrou o Chrome do app fechado
("Target page, context or browser has been closed") e o reabriu; minutos depois
o "Lançar" dos Aportes morreu com "Event loop is closed! Is Playwright already
stopped?". Os catálogos tinham sido lidos na página do Playwright ANTIGO e
continuavam em `self.catalogos`, então `_preparar_sessao` voltava cedo e o
primeiro `pagina.evaluate` estourava — um erro do Playwright, que não é
`ErpRecusou`, e por isso o relogin + releitura do 401 nem entrava.

Os catálogos valem enquanto a página deles for a página viva do navegador.
"""
from decimal import Decimal
from types import SimpleNamespace

import pytest
from playwright.sync_api import Error as PlaywrightError

from aportes import aportes_frame as af
from aportes import mc_catalogos as mcc

_MSG = "Event loop is closed! Is Playwright already stopped?"


class _PaginaMorta:
    """A página do Playwright que já parou: toda chamada estoura."""

    def evaluate(self, *_a, **_k):
        raise PlaywrightError(_MSG)


class _PaginaViva:
    def __init__(self):
        self.chamadas = 0

    def evaluate(self, *_a, **_k):
        self.chamadas += 1
        return {"ok": True}


class _Mc:
    def __init__(self, page):
        self.page = page
        self.logins = 0

    def garantir_login(self):
        self.logins += 1
        return True


class _Anx:
    """`garantir_sessao` como o do Anexar: reabre o Chrome quando ele morreu,
    e aí `mc.page` passa a ser outra página."""

    def __init__(self, page):
        self.mc = _Mc(page)
        self.sessoes = 0
        self.reabrir_com = None

    def garantir_sessao(self, _log):
        self.sessoes += 1
        if self.reabrir_com is not None:
            self.mc = _Mc(self.reabrir_com)
            self.reabrir_com = None
        return object()


def _cat(pagina):
    return mcc.Catalogos(pagina, {"prod-erp-api.x": {"user-id": "u1",
                                                      "authorization": "Bearer t"}},
                         log=lambda *_: None)


def _aba(raiz, monkeypatch, anx, respostas):
    aba = af.AportesFrame(raiz, anx)
    fila = list(respostas)
    aba.leituras = 0

    def ler():
        aba.leituras += 1
        r = fila.pop(0)
        if callable(r):
            r = r()
        if isinstance(r, BaseException):
            raise r
        return r

    aba.anotado = []
    monkeypatch.setattr(aba, "_log", lambda txt="", *_a, **_k: aba.anotado.append(str(txt)))
    monkeypatch.setattr(aba, "_ler_cadastros", ler)
    monkeypatch.setattr(aba, "_carregar_obras", lambda api: None)
    return aba


# ------------------------------------------------------------- _preparar_sessao
def test_catalogos_de_outra_pagina_sao_relidos(raiz, monkeypatch):
    viva = _PaginaViva()
    anx = _Anx(viva)
    novo = _cat(viva)
    aba = _aba(raiz, monkeypatch, anx, [novo])
    try:
        aba.catalogos = _cat(_PaginaMorta())       # leitura do Chrome anterior
        aba._preparar_sessao()
        assert aba.leituras == 1
        assert aba.catalogos is novo
    finally:
        aba.destroy()


def test_catalogos_da_pagina_viva_nao_sao_relidos(raiz, monkeypatch):
    viva = _PaginaViva()
    anx = _Anx(viva)
    aba = _aba(raiz, monkeypatch, anx, [])
    try:
        atual = _cat(viva)
        aba.catalogos = atual
        aba._preparar_sessao()
        assert aba.leituras == 0                   # cadastro lido uma vez por sessão
        assert aba.catalogos is atual
    finally:
        aba.destroy()


def test_erro_do_playwright_na_leitura_reabre_e_le_de_novo(raiz, monkeypatch):
    """O Chrome morreu no MEIO da leitura: pede a sessão de novo (que reabre o
    navegador) e lê uma vez mais, na página nova."""
    viva = _PaginaViva()
    anx = _Anx(_PaginaMorta())

    def morreu():
        anx.reabrir_com = viva
        return PlaywrightError(_MSG)

    aba = _aba(raiz, monkeypatch, anx, [morreu, lambda: _cat(anx.mc.page)])
    try:
        aba._preparar_sessao()
        assert aba.leituras == 2
        assert anx.sessoes == 2
        assert aba.catalogos.pagina is viva
    finally:
        aba.destroy()


def test_erro_do_playwright_duas_vezes_sobe_e_nao_guarda(raiz, monkeypatch):
    anx = _Anx(_PaginaMorta())
    aba = _aba(raiz, monkeypatch, anx,
               [PlaywrightError(_MSG), PlaywrightError(_MSG)])
    try:
        with pytest.raises(PlaywrightError):
            aba._preparar_sessao()
        assert aba.leituras == 2                   # uma releitura, não um laço
        assert aba.catalogos is None
    finally:
        aba.destroy()


# ------------------------------------------------------------------- o Lançar
def test_lancar_com_catalogos_do_chrome_anterior_rele_em_vez_de_morrer(raiz, monkeypatch):
    viva = _PaginaViva()
    anx = _Anx(viva)
    novo = _cat(viva)
    aba = _aba(raiz, monkeypatch, anx, [novo])
    usados = []

    def criar_pagamento(catalogos, id_usuario, **item):
        usados.append(catalogos)
        catalogos.pagina.evaluate("js", {})         # o que o de verdade faz
        return SimpleNamespace(ok=True, id_criado="1", erro=None)

    monkeypatch.setattr(af, "criar_pagamento", criar_pagamento)
    monkeypatch.setattr(af, "expandir", lambda *a, **k: [
        {"tipo_lancamento": "pagamento", "valor": Decimal("10.00")}])
    monkeypatch.setattr(aba, "_rateios_frescos", lambda: None)
    monkeypatch.setattr(af.widgets, "registrar_atividade", lambda *a, **k: None)
    try:
        aba.operacoes = [SimpleNamespace(valor=Decimal("10.00"), pagador="p")]
        aba.criados = [set()]
        aba.incertos = [set()]
        aba.catalogos = _cat(_PaginaMorta())
        aba._t_lancar()
        assert not any(_MSG in t for t in aba.anotado), aba.anotado
        assert usados == [novo]
        assert viva.chamadas == 1
        assert aba.criados == [{0}]
    finally:
        aba.destroy()
