# -*- coding: utf-8 -*-
"""Regras de aporte e distribuição — o módulo que ESCREVE valores no ERP.

Nada aqui toca navegador: `expandir` só transforma uma operação na lista de
lançamentos a criar. Nenhum dado real — nomes e contas são inventados.
"""
import datetime
from decimal import Decimal

import pytest

import regras
from regras import Operacao, como_dinheiro, dividir_em_centavos, expandir

HOJE = datetime.date(2026, 8, 11)

ENTIDADES = {
    "EMPRESA A": {"nome_oficial": "EMPRESA A LTDA", "conta": "EMPRESA A - BANCO",
                  "nome_descricao": None},
    "EMPRESA B": {"nome_oficial": "EMPRESA B LTDA", "conta": "EMPRESA B - BANCO",
                  "nome_descricao": None},
    "SUBCONTA 111-1": {"nome_oficial": "EMPRESA C LTDA",
                       "conta": "EMPRESA C - SUBCONTA 111-1",
                       "nome_descricao": None},
    "PESSOA FISICA": {"nome_oficial": "FULANO DE TAL", "conta": None,
                      "nome_descricao": None},
}
SUBCONTAS = {
    "111-1": {"obras": ["OBRA 1", "OBRA 2"],
              "investidores": ["INVESTIDOR X", "INVESTIDOR Y"]},
    "_obra_padrao": "CONTROLE DE APORTES",
}


def op(**kw):
    base = dict(data=HOJE, pagador="EMPRESA A", recebedor="EMPRESA B",
                valor=como_dinheiro("1000.00"), tipo="Aporte de Capital",
                modo="Pagamento + Recebimento", forma="Pix")
    base.update(kw)
    return Operacao(**base)


# ------------------------------------------------------------------ dinheiro
def test_como_dinheiro_limpa_o_lixo_do_float():
    # 0.1 + 0.2 == 0.30000000000000004 em float
    assert como_dinheiro(0.1 + 0.2) == Decimal("0.30")


def test_divisao_fecha_com_o_total_ate_no_caso_feio():
    for total, n in (("100.00", 3), ("0.01", 1), ("10.00", 7), ("999.99", 4)):
        partes = dividir_em_centavos(Decimal(total), n)
        assert len(partes) == n
        assert sum(partes) == Decimal(total), f"{total} / {n} não fechou"


def test_divisao_por_zero_e_erro_e_nao_silencio():
    with pytest.raises(ValueError):
        dividir_em_centavos(Decimal("10.00"), 0)


# ------------------------------------------------------------------ expandir
def test_pagamento_mais_recebimento_gera_dois():
    itens = expandir(op(), ENTIDADES, SUBCONTAS, "OBRA PADRAO")
    assert [i["tipo_lancamento"] for i in itens] == ["pagamento", "recebimento"]
    assert all(isinstance(i["valor"], Decimal) for i in itens)


def test_so_pagamento_gera_um():
    itens = expandir(op(modo="Só pagamento"), ENTIDADES, SUBCONTAS, "OBRA")
    assert len(itens) == 1 and itens[0]["tipo_lancamento"] == "pagamento"


def test_rateio_uma_linha_por_obra_x_investidor_e_soma_fecha():
    o = op(pagador="Investidor conta 111-1", recebedor="SUBCONTA 111-1",
           modo="Só recebimento", valor=como_dinheiro("1000.00"))
    itens = expandir(o, ENTIDADES, SUBCONTAS, "OBRA")
    assert len(itens) == 4                       # 2 obras x 2 investidores
    assert sum(i["valor"] for i in itens) == Decimal("1000.00")


# --------------------------------------------------- rateio vazio come o valor
def test_validar_reclama_de_subconta_sem_investidores():
    subcontas = {"111-1": {"obras": ["OBRA 1"], "investidores": []}}
    o = op(pagador="Investidor conta 111-1", recebedor="SUBCONTA 111-1",
           modo="Só recebimento")
    erros = o.validar(ENTIDADES, subcontas)
    assert any("INVESTIDORES" in e for e in erros)


def test_validar_reclama_de_subconta_sem_obras():
    subcontas = {"111-1": {"obras": [], "investidores": ["X"]}}
    o = op(pagador="Investidor conta 111-1", recebedor="SUBCONTA 111-1",
           modo="Só recebimento")
    erros = o.validar(ENTIDADES, subcontas)
    assert any("OBRAS" in e for e in erros)


def test_expandir_recusa_rateio_vazio_em_vez_de_sumir_com_o_valor():
    """Antes: `max(1, 0)` evitava a divisão por zero, o laço não rodava e a
    operação virava ZERO lançamentos — o valor sumia sem erro nem aviso."""
    subcontas = {"111-1": {"obras": [], "investidores": []}}
    o = op(pagador="Investidor conta 111-1", recebedor="SUBCONTA 111-1",
           modo="Só recebimento", valor=como_dinheiro("500.00"))
    with pytest.raises(ValueError, match="sumiria|rateio"):
        expandir(o, ENTIDADES, subcontas, "OBRA")


# ------------------------------------------------------------------ validação
def test_pessoa_fisica_sem_conta_so_pode_ser_recebimento():
    erros = op(pagador="PESSOA FISICA", modo="Só pagamento").validar(
        ENTIDADES, SUBCONTAS)
    assert any("pessoa física" in e for e in erros)


def test_pagador_igual_recebedor_e_erro():
    erros = op(recebedor="EMPRESA A").validar(ENTIDADES, SUBCONTAS)
    assert any("não podem ser o mesmo" in e for e in erros)


def test_valor_zero_e_erro():
    erros = op(valor=como_dinheiro("0")).validar(ENTIDADES, SUBCONTAS)
    assert any("maior que zero" in e for e in erros)


def test_descricao_usa_o_apelido_quando_existe():
    entidades = dict(ENTIDADES)
    entidades["EMPRESA B"] = {**ENTIDADES["EMPRESA B"],
                              "nome_descricao": "B / SÓCIOS"}
    d = op().descricao(entidades, SUBCONTAS)
    assert d.endswith("PARA B / SÓCIOS")
    assert d.startswith("APORTE CAPITAL - ")


def test_o_modulo_nao_usa_float_para_dinheiro():
    """Guarda-corpo: se alguém reintroduzir float aqui, o teste avisa."""
    itens = expandir(op(), ENTIDADES, SUBCONTAS, "OBRA")
    assert not any(isinstance(i["valor"], float) for i in itens)
    assert regras.como_dinheiro("1.005") == Decimal("1.01")   # arredonda p/ cima
