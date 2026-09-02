# -*- coding: utf-8 -*-
"""A captura de autenticação da aba Aportes: quais hosts, e de qual tela.

Em 12/08/2026 a aba parou no meio: `contas` e `participantes` entraram, e
então veio "401 em .../categories/all" seguido de "não achei o usuário
responsável". Dois sintomas, uma causa — os cabeçalhos do `legacy-api` não
tinham sido capturados. Ele serve as categorias E é o único que manda o
`user-id`, que é o responsável pelo lançamento.

Duas coisas o deixavam de fora, e as duas estão cobertas aqui.
"""
from aportes import erp_sessao


# ==========================================================================
# 1. A espera não pode parar no primeiro host
# ==========================================================================
def test_os_dois_back_ends_de_cadastro_sao_esperados():
    """O prod-erp-api sozinho não basta: sem o legacy não há user-id."""
    assert "prod-erp-api.maiscontroleerp.com.br" in erp_sessao.HOSTS_CADASTRO
    assert "legacy-api.maiscontroleerp.com.br" in erp_sessao.HOSTS_CADASTRO


def test_esperar_todos_e_diferente_de_esperar_um():
    """A prova do defeito: com só o primeiro capturado, a espera continua."""
    capturados = {"prod-erp-api.maiscontroleerp.com.br": {"authorization": "x"}}
    assert not all(a in capturados for a in erp_sessao.HOSTS_CADASTRO)
    capturados["legacy-api.maiscontroleerp.com.br"] = {"authorization": "y"}
    assert all(a in capturados for a in erp_sessao.HOSTS_CADASTRO)


# ==========================================================================
# 2. Recarregar a tela CERTA
# ==========================================================================
BASE = "https://acessar.maiscontroleerp.com.br"


def test_a_lista_de_pagamentos_e_reconhecida():
    assert erp_sessao.na_lista_de_pagamentos(f"{BASE}/#/payable-installments")
    assert erp_sessao.na_lista_de_pagamentos(f"{BASE}/#/payable-installments/")


def test_a_tela_de_um_lancamento_nao_e_a_lista():
    """O detalhe também tem "payable-installments" no endereço, e recarregar
    ELE não dispara as chamadas de cadastro. Como a busca das obras abre um
    lançamento para capturar o outro back-end, a página compartilhada fica
    justamente ali — e a rodada seguinte recarregava a tela errada."""
    assert not erp_sessao.na_lista_de_pagamentos(
        f"{BASE}/#/payable-installments/8f2c1e40-1234")
    assert not erp_sessao.na_lista_de_pagamentos(
        f"{BASE}/#/payable-installments/8f2c1e40-1234/edit")


def test_query_string_nao_engana():
    assert erp_sessao.na_lista_de_pagamentos(
        f"{BASE}/#/payable-installments?page=0")


def test_outra_tela_qualquer_nao_e_a_lista():
    assert not erp_sessao.na_lista_de_pagamentos(f"{BASE}/#/cash-flow")
    assert not erp_sessao.na_lista_de_pagamentos("")
    assert not erp_sessao.na_lista_de_pagamentos(None)


# ==========================================================================
# 3. O filtro de host, que o aviso antigo acusava sem razão
# ==========================================================================
def test_os_hosts_do_erp_servem_e_a_telemetria_nao():
    assert erp_sessao.host_util("legacy-api.maiscontroleerp.com.br")
    assert erp_sessao.host_util("prod-erp-api.maiscontroleerp.com.br")
    assert erp_sessao.host_util("abc123.execute-api.us-east-1.amazonaws.com")
    assert not erp_sessao.host_util("api-data-event.maiscontroleerp.com.br")
    assert not erp_sessao.host_util("www.google-analytics.com")
