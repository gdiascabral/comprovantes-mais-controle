# -*- coding: utf-8 -*-
from datetime import date
from decimal import Decimal

import pytest

from leitura_manha import extrato as ex

ONTEM = date(2026, 11, 26)


@pytest.mark.parametrize("v, esperado", [
    (Decimal("1234.56"), Decimal("1234.56")), (0, Decimal("0.00")), (Decimal("-10.5"), Decimal("-10.50")),
    (Decimal("436196.58701458573"), None), (1234.56, None), (True, None), ("10.00", None), (None, None),
])
def test_centavos_so_numero_com_ate_duas_casas(v, esperado):
    assert ex.centavos(v) == esperado


@pytest.mark.parametrize("t, esperado", [
    ("1234.56", Decimal("1234.56")), ("1234,56", Decimal("1234.56")), ("1.234,56", Decimal("1234.56")),
    ("150", Decimal("150.00")), ("150.5", Decimal("150.50")),
    ("1.234", None), ("-150.00", None), ("R$ 10,00", None), ("ullamco anim", None), ("", None),
    ("1,234.56", None), (None, None),
])
def test_valor_texto_nao_adivinha(t, esperado):
    assert ex.valor_texto(t) == esperado


def test_saldo_do_sandbox_com_muitas_casas_e_nao_lido_nunca_zero():
    valor, motivo = ex.saldo_sicoob({"saldo": Decimal("436196.58701458573")})
    assert valor is None and "fora do formato" in motivo


def test_saldo_ausente_e_nao_lido():
    assert ex.saldo_sicoob({})[0] is None and ex.saldo_inter({"limite": Decimal("5")})[0] is None


def test_saldo_zero_de_verdade_e_zero():
    assert ex.saldo_sicoob({"saldo": 0}) == (Decimal("0.00"), "")
    assert ex.saldo_inter({"disponivel": Decimal("12.30")}) == (Decimal("12.30"), "")


#: Copiado da resposta do Sandbox em 27/11/2026 (lorem ipsum em todo campo).
LOREM = {"saldoAnterior": "Duis", "transacoes": [
    {"descricao": "minim", "valor": "ullamco anim id aliqua ad", "data": "commodo sit ut cupidatat",
     "tipo": "elit magna", "transactionId": "x"},
    {"descricao": "dolor", "valor": "do fugiat labore in", "data": "qui tempor sunt in Lorem",
     "tipo": "consectetur"}]}


def test_extrato_lorem_do_sandbox_fica_todo_ilegivel():
    x = ex.movimentos_sicoob(LOREM, "CONTA A", ONTEM)
    assert x.movimentos == () and x.ilegiveis == 2 and x.entradas == 0
    assert len(x.motivos) == 2


def test_extrato_sicoob_so_saidas_do_dia_viram_movimento():
    corpo = {"transacoes": [
        {"tipo": "DEBITO", "valor": "150,00", "data": "2026-11-26", "descricao": "PAGAMENTO",
         "descInfComplementar": "OBRA X LT 10", "transactionId": "T1"},
        {"tipo": "CREDITO", "valor": "900.00", "data": "2026-11-26", "descricao": "PIX RECEBIDO"},
        {"tipo": "D", "valor": "80.00", "data": "25/11/2026", "descricao": "ANTERIOR"},
    ]}
    x = ex.movimentos_sicoob(corpo, "CONTA A", ONTEM)
    assert x.ilegiveis == 0 and x.entradas == 1 and x.fora_do_dia == 1
    (m,) = x.movimentos
    assert (m.conta, m.data, m.valor, m.descricao, m.ident) == (
        "CONTA A", ONTEM, Decimal("150.00"), "OBRA X LT 10", "T1")


def test_valor_com_sinal_fica_ilegivel_ate_confirmar_o_formato():
    x = ex.movimentos_sicoob({"transacoes": [
        {"tipo": "DEBITO", "valor": "-150.00", "data": "2026-11-26"}]}, "A", ONTEM)
    assert x.movimentos == () and x.ilegiveis == 1


def test_valor_zero_fica_ilegivel():
    x = ex.movimentos_sicoob({"transacoes": [
        {"tipo": "DEBITO", "valor": "0.00", "data": "2026-11-26"}]}, "A", ONTEM)
    assert x.ilegiveis == 1


def test_extrato_sem_lista_de_transacoes_e_ilegivel_inteiro():
    with pytest.raises(ex.ExtratoIlegivel):
        ex.movimentos_sicoob({"saldoAtual": "1"}, "A", ONTEM)
    with pytest.raises(ex.ExtratoIlegivel):
        ex.movimentos_inter({"transacoes": "nada"}, "A", ONTEM)


def test_inter_tipo_operacao_d_e_saida_c_e_entrada_outro_e_ilegivel():
    corpo = {"transacoes": [
        {"tipoOperacao": "D", "valor": "1171.23", "dataEntrada": "2026-11-26", "titulo": "Pagamento",
         "descricao": "CONVENIO SANEAMENTO"},
        {"tipoOperacao": "C", "valor": "10.00", "dataEntrada": "2026-11-26"},
        {"tipoOperacao": "X", "valor": "10.00", "dataEntrada": "2026-11-26"},
    ]}
    x = ex.movimentos_inter(corpo, "CONTA I", ONTEM)
    assert x.entradas == 1 and x.ilegiveis == 1
    (m,) = x.movimentos
    assert (m.valor, m.descricao, m.origem) == (Decimal("1171.23"), "CONVENIO SANEAMENTO",
                                                "Inter extrato (API)")


def test_inter_na_forma_medida_no_sandbox():
    """Forma medida no Sandbox do Inter em 27/11/2026: tipoOperacao só C/D,
    valor string com ponto e sem sinal, dataEntrada YYYY-MM-DD, tipoTransacao
    às vezes None (não é usado), dados de 2023 (fora do dia pedido)."""
    corpo = {"transacoes": [
        {"dataEntrada": "2026-11-26", "tipoTransacao": None, "tipoOperacao": "D",
         "valor": "33.33", "titulo": "Pix enviado", "descricao": ""},
        {"dataEntrada": "2023-01-26", "tipoTransacao": "PIX", "tipoOperacao": "D",
         "valor": "10.00", "titulo": "Pix enviado", "descricao": "X"},
    ]}
    x = ex.movimentos_inter(corpo, "CONTA I", ONTEM)
    assert x.ilegiveis == 0 and x.fora_do_dia == 1
    (m,) = x.movimentos
    assert (m.valor, m.descricao) == (Decimal("33.33"), "Pix enviado")


def test_saldo_inter_em_float_no_json_chega_decimal_exato():
    import json
    corpo = json.loads('{"disponivel": 1234.5, "limite": 0}', parse_float=Decimal)
    assert ex.saldo_inter(corpo) == (Decimal("1234.50"), "")


def test_linha_que_nao_e_objeto_e_ilegivel():
    assert ex.movimentos_inter({"transacoes": ["x", 3]}, "A", ONTEM).ilegiveis == 2


def test_numero_absurdo_nao_estoura_e_e_none():
    assert ex.centavos(Decimal("1e40")) is None
    assert ex.valor_texto("1" * 30 + ",00") is None
    assert ex.valor_texto("1" * 30) is None


def test_linha_com_valor_absurdo_e_contada_como_ilegivel():
    x = ex.movimentos_sicoob({"transacoes": [
        {"tipo": "DEBITO", "valor": "1" * 30 + ",00", "data": "2026-11-26"}]}, "A", ONTEM)
    assert x.movimentos == () and x.ilegiveis == 1
