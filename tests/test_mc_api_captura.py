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


# --------------------------------------------- a URL herdada da tela


class _PaginaQueResponde(PaginaFalsa):
    """Guarda a URL de cada `fetch` feito de dentro da página."""

    def __init__(self, url="https://acessar.maiscontroleerp.com.br/#/painel"):
        super().__init__(url)
        self.pedidas: list[str] = []

    def evaluate(self, _js, argumento):
        self.pedidas.append(argumento["url"])
        return {"content": [], "hasNextPage": False}


#: O que a tela mandou na véspera, com um filtro escolhido por gente: uma conta
#: só, um período velho e o centro de custo restrito. Nomes e ids inventados.
_URL_DA_TELA = (
    "https://legado.exemplo.invalido/payable-installments/paginated-result"
    "?organizationUnitId=99&page=0&size=25&type=PAID&dateField=DATE_OF_PAYMENT"
    "&startDate=2026-08-01&endDate=2026-08-31&accountIds=7"
    "&costCentreType=ONLY_ONE&onlyWork=true&conciliationType=CONCILIATED"
    "&tradePayableType=BILL&batchOperationType=SOME")


def _api_com_url_capturada():
    pagina = _PaginaQueResponde()
    api = _api(pagina)
    api._req_pagos = (_URL_DA_TELA, {"authorization": "Bearer x"})
    return api, pagina


def _parametros(url):
    from urllib.parse import parse_qsl, urlsplit
    return parse_qsl(urlsplit(url).query)


def test_o_filtro_que_ficou_na_tela_NAO_estreita_a_leitura():
    """A tela de Pagamentos guarda na query o filtro que alguém escolheu. Uma
    lista que volta curta por causa dele não dá erro nenhum — volta "com
    sucesso" —, e quem CRIA lançamento a partir do que não encontrou faz um
    segundo título para uma conta que já existe."""
    api, pagina = _api_com_url_capturada()

    api.listar_a_pagar("2026-09-01", "2026-10-31", log=lambda _m: None)

    p = dict(_parametros(pagina.pedidas[0]))
    assert p["type"] == "ALL" and p["dateField"] == "PLANNED"
    assert p["onlyWork"] == "false"
    assert p["costCentreType"] == "ALL"
    assert p["conciliationType"] == "ALL"
    assert p["tradePayableType"] == "ALL"
    assert p["batchOperationType"] == "NONE"
    assert "accountIds" not in p
    # O que é da organização continua vindo da tela, intacto.
    assert p["organizationUnitId"] == "99"


def test_nenhum_parametro_sai_repetido_na_query():
    """Chave duplicada na query é o ERP escolhendo qual vale — e ele pode
    escolher a da tela. `dict()` esconderia isso: a conta tem de ser feita na
    lista de pares."""
    api, pagina = _api_com_url_capturada()

    api.listar_a_pagar("2026-09-01", "2026-10-31", log=lambda _m: None)

    nomes = [k for k, _ in _parametros(pagina.pedidas[0])]
    assert len(nomes) == len(set(nomes)), sorted(nomes)
