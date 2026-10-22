"""Altura em linhas das tabelas do Controle de aportes (regra pura)."""
from tela_do_dia import controle_aportes as ca


def test_vazia_fica_no_minimo():
    assert ca.linhas_da_tabela(0, 4, 10) == 4


def test_cresce_com_o_conteudo():
    assert ca.linhas_da_tabela(7, 4, 10) == 7


def test_passa_do_teto_rola_dentro_da_tabela():
    assert ca.linhas_da_tabela(60, 4, 10) == 10
