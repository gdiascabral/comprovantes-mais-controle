# -*- coding: utf-8 -*-
"""
Testes da explicação para a grade de pagamentos vazia.

Caso real de 10/08/2026: a grade veio sem linhas e o erro dizia "o layout do
ERP pode ter mudado". Não era layout — a sessão do navegador não estava
válida e o ERP respondeu sem dados. O rodapé denunciava isso o tempo todo,
somando R$ 1.804.164,67 no mês enquanto a lista mostrava "Nenhum registro
encontrado". Uma hora foi perdida procurando no lugar errado.
"""
from conciliacao.erp.payments import motivo_da_grade_vazia


def test_rodape_com_valor_aponta_sessao_e_nao_layout():
    m = motivo_da_grade_vazia("R$ 1.804.164,67", tem_texto_vazio=True)
    assert "sessao" in m
    assert "1.804.164,67" in m
    assert "layout" not in m


def test_rodape_zerado_e_mes_sem_lancamentos():
    m = motivo_da_grade_vazia(None, tem_texto_vazio=True)
    assert "nao tem lancamentos" in m
    assert "sessao" not in m


def test_rodape_escrito_zero_tambem_e_mes_sem_lancamentos():
    """"R$ 0,00" é string NÃO vazia — e toda string não vazia é verdadeira.

    O mês legitimamente zerado caía no ramo do "sua sessão caiu" e mandava
    procurar problema onde não havia."""
    m = motivo_da_grade_vazia("R$ 0,00", tem_texto_vazio=True)
    assert "nao tem lancamentos" in m
    assert "sessao" not in m


def test_sem_rodape_e_sem_aviso_admite_layout():
    # Nem totais nem "nenhum registro": a tela pode nem ter aberto direito.
    m = motivo_da_grade_vazia(None, tem_texto_vazio=False)
    assert "layout" in m or "nao ter aberto" in m


def test_a_mensagem_sempre_diz_o_que_fazer():
    for total, vazio in (("R$ 10,00", True), (None, True), (None, False)):
        m = motivo_da_grade_vazia(total, vazio)
        assert any(p in m for p in ("rode de novo", "confira", "veja o screenshot"))
