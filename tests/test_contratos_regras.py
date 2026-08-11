# -*- coding: utf-8 -*-
"""Regras dos contratos de financiamento: do recebimento ao imóvel.

Nenhum dado real: os payloads têm a FORMA que a API devolve, com nomes e
valores inventados. O repositório é público e contrato tem nome de gente.
"""
from decimal import Decimal

from contratos.regras import (Imovel, imoveis_do_mes, numero_da_unidade,
                              partes_da_descricao, rotulo_da_unidade)


def receb(descricao, condicao="1ª FINANCIAMENTO", obra="TB 21 QD 46 LT 18",
          valor=100000.0, data="2026-07-30", ident="r1"):
    """Um recebimento no formato que o ERP devolve."""
    return {"workName": obra, "description": descricao,
            "readjustmentType": condicao, "nature": "Venda",
            "dateOfReceipt": data, "sumOfReceivedValues": valor,
            "customerName": "EMPRESA EXEMPLO", "id": ident}


# ------------------------------------------------------------------ unidade
def test_as_quatro_grafias_de_casa():
    assert numero_da_unidade("VENDA CASA 01") == 1
    assert numero_da_unidade("VENDA CS 3") == 3
    assert numero_da_unidade("venda cs1") == 1
    assert numero_da_unidade("VENDA C12") == 12


def test_sem_unidade_devolve_none():
    assert numero_da_unidade("VENDA DO IMOVEL") is None
    assert numero_da_unidade("") is None


def test_rotulo_sai_com_dois_digitos():
    assert rotulo_da_unidade(1) == "CS 01"
    assert rotulo_da_unidade(12) == "CS 12"


def test_comprador_comecando_com_c_nao_vira_casa():
    """"CARLOS" tem C seguido de nada, mas "CASA 2 - C3PO" tentaria enganar.

    A unidade só é procurada ANTES do primeiro " - "; o comprador é o resto."""
    unidade, comprador = partes_da_descricao("VENDA CASA 02 - CARLOS ANDRADE")
    assert unidade == 2
    assert comprador == "CARLOS ANDRADE"


def test_descricao_sem_separador_nao_tem_comprador():
    unidade, comprador = partes_da_descricao("VENDA CASA 02")
    assert unidade == 2 and comprador == ""


# ------------------------------------------------------------------ imóveis
def test_so_financiamento_entra():
    registros = [
        receb("VENDA CASA 01 - FULANO", "1ª FINANCIAMENTO"),
        receb("VENDA CASA 02 - BELTRANO", "1ª Sinal"),
        receb("VENDA CASA 03 - CICRANO", "1ª Entrada"),
        receb("VENDA CASA 04 - DETRANO", "1ª Reembolso Vistoria"),
    ]
    imoveis = imoveis_do_mes(registros, log=lambda m: None)
    assert [i.unidade for i in imoveis] == [1]


def test_financiamento_e_juros_da_mesma_casa_viram_um_imovel():
    registros = [
        receb("VENDA CASA 01 - FULANO", "1ª FINANCIAMENTO", valor=240000.0),
        receb("VENDA CASA 01 - FULANO", "1ª JUROS FINANCIAMENTO", valor=4800.0),
    ]
    imoveis = imoveis_do_mes(registros, log=lambda m: None)
    assert len(imoveis) == 1
    assert imoveis[0].valor_financiamento == Decimal("240000.00")
    assert imoveis[0].juros == Decimal("4800.00")


def test_mes_so_com_juros_vai_para_revisao():
    """O financiamento caiu em outro mês: aqui não há contrato novo a buscar."""
    registros = [receb("VENDA CASA 01 - FULANO", "1ª JUROS FINANCIAMENTO",
                       valor=4800.0)]
    imoveis = imoveis_do_mes(registros, log=lambda m: None)
    assert len(imoveis) == 1
    assert "JUROS" in imoveis[0].revisao


def test_duas_casas_no_mesmo_lote_sao_dois_imoveis():
    """A obra "2 casas" é o caso normal, não a exceção."""
    registros = [
        receb("VENDA CASA 01 - FULANO"),
        receb("VENDA CASA 02 - BELTRANO"),
    ]
    imoveis = imoveis_do_mes(registros, log=lambda m: None)
    assert len(imoveis) == 2
    assert {i.unidade for i in imoveis} == {1, 2}


def test_obras_diferentes_com_a_mesma_casa_nao_se_misturam():
    registros = [
        receb("VENDA CASA 01 - FULANO", obra="TB 21 QD 46 LT 18"),
        receb("VENDA CASA 01 - BELTRANO", obra="RPB 24 QD 26A LT 14"),
    ]
    imoveis = imoveis_do_mes(registros, log=lambda m: None)
    assert len(imoveis) == 2


def test_work_name_vazio_fica_de_fora():
    registros = [receb("VENDA CASA 01 - FULANO", obra="")]
    assert imoveis_do_mes(registros, log=lambda m: None) == []


def test_descricao_sem_casa_fica_de_fora():
    """Sem a casa não dá para escolher o contrato: são vários por obra."""
    registros = [receb("VENDA DO IMOVEL - FULANO")]
    assert imoveis_do_mes(registros, log=lambda m: None) == []


def test_dinheiro_e_decimal_e_nao_float():
    registros = [receb("VENDA CASA 01 - FULANO", valor=0.1),
                 receb("VENDA CASA 01 - FULANO", valor=0.2)]
    imoveis = imoveis_do_mes(registros, log=lambda m: None)
    # 0.1 + 0.2 == 0.30000000000000004 em float
    assert imoveis[0].valor_financiamento == Decimal("0.30")


def test_chave_do_imovel_ignora_acento_e_espaco_duplo():
    a = Imovel(obra="TB 21  QD 46 LT 18", unidade=1, comprador="X")
    b = Imovel(obra="tb 21 qd 46 lt 18", unidade=1, comprador="Y")
    assert a.chave == b.chave
