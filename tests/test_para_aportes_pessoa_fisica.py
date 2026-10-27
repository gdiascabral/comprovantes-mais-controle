# -*- coding: utf-8 -*-
"""O rótulo da aba Regras casa com o nome de exibição do cadastro mesmo com o
"(pessoa física)" que o cadastro põe no fim (dono, 26/10/2026: o aporte de
uma sócia escrita só pelo primeiro nome na aba Regras ficou de fora com "não
achei no cadastro"). Continua exigindo o nome INTEIRO: primeiro nome de outra
pessoa não casa."""
from tela_do_dia import para_aportes as pa

ENT = {
    "FULANA (pessoa física)": {"nome_oficial": "FULANA DE TAL SOBRENOME", "conta": None},
    "BELTRANO SILVA (pessoa física)": {"nome_oficial": "BELTRANO SILVA FILHO", "conta": None},
    "EMPRESA ALFA - BANCO": {"nome_oficial": "EMPRESA ALFA LTDA", "conta": "EMPRESA ALFA - BANCO"},
}


def test_rotulo_casa_sem_o_sufixo_de_pessoa_fisica():
    assert pa.nome_no_cadastro("Fulana", ENT) == "FULANA (pessoa física)"


def test_primeiro_nome_de_outra_pessoa_nao_casa():
    assert pa.nome_no_cadastro("Beltrano", ENT) is None


def test_nome_inteiro_com_sufixo_continua_casando():
    assert pa.nome_no_cadastro("FULANA (pessoa física)", ENT) == "FULANA (pessoa física)"


def test_casar_no_cadastro_tambem_ignora_o_sufixo():
    c = pa.casar_no_cadastro("Fulana", ENT)
    assert c.nome == "FULANA (pessoa física)"
