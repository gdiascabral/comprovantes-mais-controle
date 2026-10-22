# -*- coding: utf-8 -*-
"""Os movimentos à mão do dia no HTML dos pagamentos (item A, 22/10/2026).

Dono: "não precisa colocar os pix pq tem salvo no banco já, só a informação
pra não ficar nenhum pra trás". Linhas INFORMATIVAS: de → para, tipo e valor,
sem chave, sem "Copiar", fora do total das contas e fora da remessa.
Tudo fictício (o repositório é público)."""
from decimal import Decimal

from pagamentos_dia import html_pagamentos as hp
from pagamentos_dia import modelos_html
from tests.test_html_pagamentos import _gravar, _json, _ler

MOVS = [
    {"de": "de fora (sócio ou investidor)", "para": "CONTA ALFA - SICOOB",
     "tipo": "Aporte que entra na mãe", "valor": Decimal("400.00")},
    {"de": "CONTA ALFA - SICOOB", "para": "CONTA BETA - INTER",
     "tipo": "Transferência entre contas", "valor": Decimal("0.10")},
    {"de": "CONTA ALFA - SICOOB", "para": "SOCIO FICTICIO",
     "tipo": "Distribuição de lucros", "valor": Decimal("0.20")},
]


def test_movimentos_do_html_so_tem_de_para_tipo_e_valor():
    linhas = hp.movimentos_do_html(MOVS)
    assert linhas[1] == {"de": "CONTA ALFA - SICOOB", "para": "CONTA BETA - INTER",
                         "tipo": "Transferência entre contas", "valor": "0,10",
                         "centavos": 10}
    for linha in linhas:
        assert set(linha) == {"de", "para", "tipo", "valor", "centavos"}


def test_movimentos_do_html_ignoram_zero_e_negativo():
    assert hp.movimentos_do_html([dict(MOVS[0], valor=Decimal("0")),
                                  dict(MOVS[0], valor=Decimal("-1"))]) == []


def test_movimentos_entram_no_html_e_nao_no_total_das_contas(tmp_path):
    sem = _gravar(tmp_path / "sem")
    com = _gravar(tmp_path / "com", movimentos=MOVS)
    dados = _json(_ler(com.geral), "DATA")
    assert [m["tipo"] for m in dados["movimentos"]] == [m["tipo"] for m in MOVS]
    assert dados["contas"] == _json(_ler(sem.geral), "DATA")["contas"]
    assert com.total == sem.total and com.linhas == sem.linhas
    assert com.movimentos == 3 and com.total_movimentos == Decimal("400.30")
    assert any("movimentos do dia" in linha and "R$ 400,30" in linha
               for linha in com.registro())


def test_sem_movimentos_a_lista_vem_vazia_e_o_registro_nao_fala_dela(tmp_path):
    g = _gravar(tmp_path)
    assert _json(_ler(g.geral), "DATA")["movimentos"] == []
    assert g.movimentos == 0 and not any("movimentos do dia" in x for x in g.registro())


def test_o_modelo_tem_a_secao_informativa_sem_copiar():
    m = modelos_html.MODELO_GERAL
    assert "Movimentos do dia — já cadastrados no banco" in m
    inicio = m.index("function renderMovimentos")
    fim = m.index("\n}\n", inicio)
    corpo = m[inicio:fim]
    assert "DATA.movimentos" in corpo
    assert "copybtn" not in corpo and "copyText" not in corpo
    # a soma da seção é própria; o total geral continua só das contas
    assert "movTotal" in corpo
    assert "renderMovimentos()" in m
