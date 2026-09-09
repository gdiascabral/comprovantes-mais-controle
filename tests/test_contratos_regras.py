# -*- coding: utf-8 -*-
"""Regras dos contratos de venda: do recebimento ao imóvel.

Nenhum dado real: os payloads têm a FORMA que a API devolve, com nomes e
valores inventados. O repositório é público e contrato tem nome de gente.
"""
from decimal import Decimal

from contratos.regras import (Imovel, imoveis_do_mes, numero_da_unidade,
                              partes_da_descricao, rotulo_da_unidade)


def receb(descricao, condicao="1ª Sinal", obra="TB 21 QD 46 LT 18",
          valor=10000.0, data="2026-08-05", ident="r1", venda=260000.0):
    """Um recebimento no formato que o ERP devolve."""
    r = {"workName": obra, "description": descricao,
         "readjustmentType": condicao, "nature": "Venda",
         "dateOfReceipt": data, "sumOfReceivedValues": valor,
         "customerName": "EMPRESA EXEMPLO", "id": ident}
    if venda is not None:
        r["saleValue"] = venda
    return r


def _sem_log(_m):
    pass


# ------------------------------------------------------------------ unidade
def test_as_quatro_grafias_de_casa():
    assert numero_da_unidade("VENDA CASA 01") == 1
    assert numero_da_unidade("VENDA CS 3") == 3
    assert numero_da_unidade("venda cs1") == 1
    assert numero_da_unidade("VENDA C12") == 12


def test_sem_unidade_devolve_none():
    assert numero_da_unidade("VENDA DO IMOVEL") is None
    assert numero_da_unidade("") is None


def test_cs_manda_sobre_o_c_solto_do_centro_de_custo():
    """`LT 8 C 259 M 5` tem um C que não é casa; o CS 01 do fim é que vale."""
    assert numero_da_unidade("DONA MORENA QD 18 LT 8 C 259 M 5 CS 01") == 1


def test_rotulo_sai_com_dois_digitos():
    assert rotulo_da_unidade(1) == "CS 01"
    assert rotulo_da_unidade(12) == "CS 12"
    assert rotulo_da_unidade(None) == "CS ??"


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
def test_toda_condicao_entra():
    """Sinal, entrada, financiamento, juros, vistoria, FGTS: com imposto em
    todo recebimento, nenhuma condição fica de fora."""
    condicoes = ["1ª Sinal", "1ª Entrada", "1ª FINANCIAMENTO",
                 "1ª JUROS FINANCIAMENTO", "1ª Reembolso Vistoria", "FGTS"]
    registros = [receb(f"VENDA CASA {n:02d} - COMPRADOR {n}", c, ident=f"r{n}")
                 for n, c in enumerate(condicoes, 1)]
    imoveis = imoveis_do_mes(registros, log=_sem_log)
    assert [i.unidade for i in imoveis] == [1, 2, 3, 4, 5, 6]
    assert not any(i.revisao for i in imoveis)


def test_recebimentos_da_mesma_casa_viram_um_imovel_com_a_lista():
    registros = [
        receb("VENDA CASA 01 - FULANO", "1ª Entrada", valor=20000.0,
              data="2026-08-20", ident="b"),
        receb("VENDA CASA 01 - FULANO", "1ª Sinal", valor=10000.0,
              data="2026-08-05", ident="a"),
    ]
    imoveis = imoveis_do_mes(registros, log=_sem_log)
    assert len(imoveis) == 1
    i = imoveis[0]
    assert i.recebido == Decimal("30000.00")
    assert len(i.recebimentos) == 2
    assert i.condicoes == ["1ª Sinal", "1ª Entrada"]      # em ordem de data
    assert i.data == "2026-08-05"
    assert i.ids == ["a", "b"]


def test_mes_so_com_juros_tambem_entra():
    """Antes era revisão ("o financiamento caiu em outro mês"). Agora o juro
    é um recebimento como outro qualquer, e o contrato é o mesmo."""
    registros = [receb("VENDA CASA 01 - FULANO", "1ª JUROS FINANCIAMENTO",
                       valor=4800.0)]
    imoveis = imoveis_do_mes(registros, log=_sem_log)
    assert len(imoveis) == 1 and not imoveis[0].revisao


def test_valor_da_venda_vem_do_erp_e_nao_da_parcela():
    i = imoveis_do_mes([receb("VENDA CASA 01 - FULANO", valor=10000.0,
                              venda=260000.0)], log=_sem_log)[0]
    assert i.valor_venda == Decimal("260000.00")
    assert i.recebido == Decimal("10000.00")


def test_sem_sale_value_o_valor_da_venda_fica_vazio():
    i = imoveis_do_mes([receb("VENDA CASA 01 - FULANO", venda=None)],
                       log=_sem_log)[0]
    assert i.valor_venda is None


def test_duas_casas_no_mesmo_lote_sao_dois_imoveis():
    """A obra "2 casas" é o caso normal, não a exceção."""
    registros = [
        receb("VENDA CASA 01 - FULANO"),
        receb("VENDA CASA 02 - BELTRANO"),
    ]
    imoveis = imoveis_do_mes(registros, log=_sem_log)
    assert len(imoveis) == 2
    assert {i.unidade for i in imoveis} == {1, 2}


def test_obras_diferentes_com_a_mesma_casa_nao_se_misturam():
    registros = [
        receb("VENDA CASA 01 - FULANO", obra="TB 21 QD 46 LT 18"),
        receb("VENDA CASA 01 - BELTRANO", obra="RPB 24 QD 26A LT 14"),
    ]
    imoveis = imoveis_do_mes(registros, log=_sem_log)
    assert len(imoveis) == 2


def test_work_name_vazio_vira_linha_em_revisao():
    """Nada some em silêncio: sem obra a linha aparece dizendo por quê."""
    imoveis = imoveis_do_mes([receb("VENDA CASA 01 - FULANO", obra="")],
                             log=_sem_log)
    assert len(imoveis) == 1
    assert "sem centro de custo" in imoveis[0].revisao
    assert imoveis[0].obra == ""


def test_descricao_sem_casa_vira_linha_em_revisao():
    """Sem a casa não dá para escolher o contrato: são vários por obra. A
    linha fica, com o pedido de corrigir a descrição no ERP."""
    imoveis = imoveis_do_mes([receb("VENDA DO IMOVEL - FULANO")], log=_sem_log)
    assert len(imoveis) == 1
    i = imoveis[0]
    assert i.unidade is None
    assert i.rotulo == "CS ??"
    assert "não diz a casa" in i.revisao and "VENDA CASA 01 - NOME" in i.revisao
    assert i.comprador == "FULANO"


def test_linhas_sem_casa_iguais_nao_se_multiplicam():
    registros = [receb("VENDA DO IMOVEL - FULANO", "1ª Sinal", ident="a"),
                 receb("VENDA DO IMOVEL - FULANO", "1ª Entrada", ident="b")]
    imoveis = imoveis_do_mes(registros, log=_sem_log)
    assert len(imoveis) == 1 and len(imoveis[0].recebimentos) == 2


def test_aviso_conta_as_linhas_em_revisao():
    recados = []
    imoveis_do_mes([receb("VENDA DO IMOVEL - X"), receb("VENDA CASA 01 - Y")],
                   log=recados.append)
    assert any("1 linha(s)" in m for m in recados)


def test_dinheiro_e_decimal_e_nao_float():
    registros = [receb("VENDA CASA 01 - FULANO", valor=0.1),
                 receb("VENDA CASA 01 - FULANO", valor=0.2)]
    imoveis = imoveis_do_mes(registros, log=_sem_log)
    # 0.1 + 0.2 == 0.30000000000000004 em float
    assert imoveis[0].recebido == Decimal("0.30")


def test_chave_do_imovel_ignora_acento_e_espaco_duplo():
    a = Imovel(obra="TB 21  QD 46 LT 18", unidade=1, comprador="X")
    b = Imovel(obra="tb 21 qd 46 lt 18", unidade=1, comprador="Y")
    assert a.chave == b.chave
