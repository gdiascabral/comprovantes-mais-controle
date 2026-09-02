# -*- coding: utf-8 -*-
"""A captura dos cabeçalhos do SEGUNDO back-end do Mais Controle.

Caso real de 11/08/2026: a aba Contratos parava em "Credenciais de anexos
ainda não capturadas" logo depois de "Lendo as obras...", em qualquer mês. As
obras e os anexos vivem num back-end diferente do dos pagamentos, e o
cabeçalho dele só nasce quando o navegador abre a tela de um lançamento.

As outras abas passavam o id de um pagamento que já tinham na mão; a de
Contratos parte de recebimentos e obras e não tem esse id — por isso a captura
passou a saber procurar a própria isca.

Nada aqui toca o ERP: a página é um dublê que registra para onde foi.
"""
from urllib.parse import parse_qsl, urlsplit

import pytest

from anexar import mc_api

BASE = "https://acessar.maiscontroleerp.com.br"
URL_PAGOS = (BASE + "/maiscontrole/services/payable-installments/"
             "paginated-result?organizationUnitId=ou-1&page=3&size=20"
             "&type=ALL&dateField=PLANNED")
HEADERS = {"authorization": "Bearer xyz", "company-id": "emp-1"}
URL_ANEXOS = BASE + "/maiscontrole/attachments"


class PaginaFalsa:
    """Só o que a MCApi usa da página: ouvir, navegar, esperar e rodar fetch."""

    def __init__(self, resposta=None):
        self.resposta = {"content": []} if resposta is None else resposta
        self.visitadas = []
        self.urls_fetch = []
        self.dispara_anexos = None    # trecho de URL que "faz a tela pedir os anexos"
        self.api = None

    def on(self, evento, fn):
        pass

    def goto(self, url, wait_until=None):
        self.visitadas.append(url)
        if self.dispara_anexos and self.dispara_anexos in url:
            self.api._req_anexos = (URL_ANEXOS, HEADERS)

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, js, arg):
        self.urls_fetch.append(arg.get("url"))
        return self.resposta


class ClienteFalso:
    def __init__(self, page):
        self.page = page


class RequisicaoFalsa:
    def __init__(self, url, headers):
        self.url, self.headers = url, headers


def api_falsa(pagina, req_pagos=(URL_PAGOS, HEADERS), req_anexos=None):
    api = mc_api.MCApi.__new__(mc_api.MCApi)
    api._cliente = ClienteFalso(pagina)
    api._pagina_ouvida = pagina
    api._req_pagos = req_pagos
    api._req_anexos = req_anexos
    api._diag_avisado = False
    pagina.api = api
    return api


def test_ja_capturado_nao_mexe_no_navegador():
    """Cada ida ao ERP custa tempo e recarrega a tela de quem está olhando."""
    p = PaginaFalsa()
    api = api_falsa(p, req_anexos=(URL_ANEXOS, HEADERS))
    assert api.garantir_credenciais_anexos(log=lambda m: None) is True
    assert p.visitadas == [] and p.urls_fetch == []


def test_procura_um_pagamento_recente_e_abre_a_tela_dele():
    p = PaginaFalsa({"content": [{"id": "lanc-42"}]})
    p.dispara_anexos = "payable-installments/lanc-42"
    api = api_falsa(p)
    assert api.garantir_credenciais_anexos(log=lambda m: None) is True
    assert any("#/payable-installments/lanc-42" in u for u in p.visitadas)
    assert api._req_anexos[1]["authorization"] == "Bearer xyz"


def test_a_consulta_da_isca_e_de_uma_linha_so_e_de_pagamento_pago():
    p = PaginaFalsa({"content": [{"id": "lanc-42"}]})
    p.dispara_anexos = "lanc-42"
    api = api_falsa(p)
    api.garantir_credenciais_anexos(log=lambda m: None)

    q = dict(parse_qsl(urlsplit(p.urls_fetch[0]).query))
    assert q["page"] == "0" and q["size"] == "1"
    assert q["type"] == "PAID" and q["dateField"] == "DATE_OF_PAYMENT"
    assert q["startDate"] < q["endDate"]
    # o que a tela mandou (a organização) continua; o filtro dela, não
    assert q["organizationUnitId"] == "ou-1"


def test_sem_pagamento_no_periodo_devolve_falso_e_diz_o_que_fazer():
    p = PaginaFalsa({"content": []})
    api = api_falsa(p)
    recados = []
    assert api.garantir_credenciais_anexos(log=recados.append) is False
    assert p.visitadas == []                       # não abriu tela nenhuma
    assert any("pagamento" in m for m in recados)


def test_erro_da_api_ao_procurar_a_isca_sobe_com_o_codigo():
    """401 aqui é sessão caída, não "mês sem pagamento": os dois não podem
    terminar na mesma frase."""
    p = PaginaFalsa({"__erro": 401})
    api = api_falsa(p)
    with pytest.raises(RuntimeError) as e:
        api.garantir_credenciais_anexos(log=lambda m: None)
    assert "401" in str(e.value)


def test_a_escuta_guarda_a_url_de_anexos_sem_a_query():
    """A query do endpoint de anexos muda a cada consulta (entityIds,
    entityOrigin): o que se guarda é a base, e só os cabeçalhos que interessam
    — cookie e afins o navegador completa sozinho."""
    p = PaginaFalsa()
    api = api_falsa(p)
    api._on_request(RequisicaoFalsa(
        URL_ANEXOS + "?entityIds=abc&entityOrigin=PAID",
        {"Authorization": "Bearer xyz", "company-id": "emp-1",
         "cookie": "sessao=1"}))

    base, headers = api._req_anexos
    assert base == URL_ANEXOS
    assert "cookie" not in headers
