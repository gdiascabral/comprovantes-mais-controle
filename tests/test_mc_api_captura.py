# -*- coding: utf-8 -*-
"""A captura de credenciais na tela de Pagamentos.

Sem navegador: a página é falsa e só anota o que foi pedido dela. O que se
prova aqui é que o app SEMPRE faz a tela buscar a lista de novo — inclusive
quando já está nela, que era o caso em que ele travava.
"""
from anexar import mc_api


class PaginaFalsa:
    """O bastante da página do Playwright para esta regra."""

    def __init__(self, url="https://acessar.maiscontroleerp.com.br/#/painel"):
        self.url = url
        self.gotos: list[str] = []
        self.reloads = 0

    def on(self, _evento, _funcao):
        pass

    def goto(self, url, **_kw):
        self.gotos.append(url)
        self.url = url

    def reload(self, **_kw):
        self.reloads += 1

    def wait_for_timeout(self, _ms):
        pass


class ClienteFalso:
    def __init__(self, pagina):
        self.page = pagina


def _api(pagina):
    return mc_api.MCApi(ClienteFalso(pagina))


def test_fora_da_tela_de_pagamentos_ele_navega():
    pag = PaginaFalsa()
    api = _api(pag)
    api.capturar_credenciais(log=lambda _m: None)
    assert pag.gotos and "payable-installments" in pag.gotos[0]


def test_JA_na_tela_de_pagamentos_ele_recarrega():
    """O defeito de 20/08/2026: `goto` para a MESMA rota não re-roteia a SPA.

    A lista não era buscada de novo, e a captura esperava 30 segundos por uma
    requisição que nunca vinha — com a tela carregada na frente do usuário.
    Ir ao dashboard e voltar resolvia à mão; `reload` faz isso sozinho.
    """
    pag = PaginaFalsa(url="https://acessar.maiscontroleerp.com.br/#/payable-installments")
    api = _api(pag)
    api.capturar_credenciais(log=lambda _m: None)
    assert pag.reloads >= 1
    assert not any("payable-installments" in u for u in pag.gotos), \
        "navegou para a rota em que já estava, em vez de recarregar"


def test_credencial_ja_capturada_nao_mexe_na_pagina():
    """Recarregar à toa custa uma volta inteira do ERP em cada aba."""
    pag = PaginaFalsa()
    api = _api(pag)
    api._req_pagos = ("url", {"authorization": "x"})
    assert api.capturar_credenciais(log=lambda _m: None) is True
    assert pag.gotos == [] and pag.reloads == 0
