# -*- coding: utf-8 -*-
"""Condomínio: a venda é de UNIDADE, não de casa.

O robô de venda descreve o recebimento do condomínio como
"VENDA UNIDADE 15 - NOME" (regra do dono, 07/10/2026). Até 05/11/2026 a aba
Contratos só entendia CASA/CS e mostrava essas linhas como "CS ??".

Nenhum dado real: nomes e valores inventados (o repositório é público).
"""
from contratos.conferencia import conferir_casa, CONFERE, DIVERGE
from contratos.destino import nome_arquivo
from contratos.escolha import contrato_de
from contratos.regras import (imoveis_do_mes, numero_da_unidade,
                              partes_da_descricao, rotulo_da_unidade,
                              tipo_da_descricao, tipo_da_unidade)

OBRA = "CONDOMINIO EXEMPLO"


def receb(descricao, ident="r1"):
    return {"workName": OBRA, "description": descricao,
            "readjustmentType": "0ª Sinal", "nature": "Venda",
            "dateOfReceipt": "2026-10-05", "sumOfReceivedValues": 3000.0,
            "customerName": "FULANO EXEMPLO", "id": ident,
            "saleValue": 300000.0}


def test_unidade_vira_numero():
    assert numero_da_unidade("VENDA UNIDADE 15") == 15
    assert numero_da_unidade("VENDA UNIDADE 07") == 7
    assert numero_da_unidade("UNID. 3") == 3
    assert numero_da_unidade("UN 31") == 31


def test_tipo_da_unidade():
    assert tipo_da_unidade("VENDA UNIDADE 15") == "UN"
    assert tipo_da_unidade("VENDA CASA 01") == "CS"
    assert tipo_da_unidade("VENDA CS 2") == "CS"
    assert tipo_da_unidade("VENDA DO IMOVEL") == "CS"


def test_tipo_so_olha_antes_do_traco():
    """O nome do comprador é texto livre: "UN 2" nele não muda o tipo."""
    assert tipo_da_descricao("VENDA CASA 01 - JOAO UN 2") == "CS"
    assert tipo_da_descricao("VENDA UNIDADE 17 - FULANO") == "UN"


def test_rotulo_do_condominio():
    assert rotulo_da_unidade(15, "UN") == "UN 15"
    assert rotulo_da_unidade(None, "UN") == "UN ??"
    assert rotulo_da_unidade(1) == "CS 01"


def test_unidade_do_condominio_nao_cai_em_revisao():
    imoveis = imoveis_do_mes(
        [receb("VENDA UNIDADE 15 - FULANO EXEMPLO", "a"),
         receb("VENDA UNIDADE 17 - CICLANA EXEMPLO", "b")], log=lambda _m: None)
    assert [(i.unidade, i.rotulo, i.revisao) for i in imoveis] == [
        (15, "UN 15", ""), (17, "UN 17", "")]
    assert imoveis[0].comprador == "FULANO EXEMPLO"


def test_unidade_00_de_teste_segue_em_revisao():
    """A venda de teste "UNIDADE 00" não é unidade nenhuma."""
    unidade, _ = partes_da_descricao("VENDA UNIDADE 00 - TESTE")
    assert not unidade
    [i] = imoveis_do_mes([receb("VENDA UNIDADE 00 - TESTE")],
                         log=lambda _m: None)
    assert i.revisao
    assert i.rotulo == "UN ??"


def test_contrato_da_unidade_e_mensagem_com_un():
    anexos = [{"filename": "CONTRATO DE COMPRA E VENDA UNIDADE 15 - FULANO"},
              {"filename": "CONTRATO DE COMPRA E VENDA UNIDADE 17 - CICLANA"}]
    anexo, _ = contrato_de(anexos, 15, "UN")
    assert anexo is anexos[0]
    anexo, motivo = contrato_de(anexos, 18, "UN")
    assert anexo is None
    assert "UN 18" in motivo


def test_nome_do_arquivo_do_condominio():
    assert nome_arquivo(OBRA, 15, "FULANO EXEMPLO", tipo="UN") == (
        f"CONTRATO DE COMPRA E VENDA {OBRA} UN 15 - FULANO EXEMPLO.pdf")
    # casa de rua continua igual
    assert " CS 02 - " in nome_arquivo("TB 21 QD 46 LT 18", 2, "FULANO")


def test_conferencia_da_unidade():
    """O texto chega preparado (UNIDADE já virou UN pelos sinônimos)."""
    assert conferir_casa("OBJETO UN 15 DO CONDOMINIO", 15, "UN") == CONFERE
    assert conferir_casa("OBJETO UN 16 DO CONDOMINIO", 15, "UN") == DIVERGE
    # casa de rua não é afetada
    assert conferir_casa("LT 18 CS 02", 2) == CONFERE
