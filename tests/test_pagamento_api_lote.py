# -*- coding: utf-8 -*-
from decimal import Decimal

from pagamento_api import lote
from pagamentos_dia import nivel

#: Linhas que outros testes do repositório já usam e que fecham nos DVs
#: (test_remessa_dia.py). Nunca escrever linha digitável de memória.
BANCARIO = "34191570070002492437524177010006115340000115050"
ARRECADACAO = "818900000019234500012021610150000001000123456789"
#: Copia-e-cola de test_html_pagamentos.py (CRC fictício: o lote só reconhece a forma).
PIX_QR = ("00020126330014br.gov.bcb.pix0111000000000005204000053039865406100.00"
          "5802BR5913FULANO DE TAL6008GOIANIA62070503***6304ABCD")


def _e(id_, tipo, dados, centavos, **k):
    base = {"id": id_, "tipo": tipo, "dados_limpo": dados, "centavos": centavos,
            "favorecido": "FORNECEDOR A", "descricao": "OBRA X NF 1 OC 2",
            "bloqueio": "", "nivel": nivel.PODE_PAGAR, "nivel_rotulo": "PODE PAGAR"}
    base.update(k)
    return base


def _doc(_fav):
    return "11.222.333/0001-81"


def test_boleto_pix_e_convenio_entram_com_o_tipo_certo():
    contas = [{"nome": "OBRA X - SICOOB", "entries": [
        _e("1", "Boleto", BANCARIO, 115050),
        _e("2", "Boleto", ARRECADACAO, 1923),
        _e("3", "Pix", "fornecedor@exemplo.com", 50000),
        _e("4", "Pix", PIX_QR, 1000)]}]
    itens, fora = lote.itens_do_html(contas, _doc)
    assert fora == []
    assert [i.tipo for i in itens] == [lote.BOLETO, lote.CONVENIO, lote.PIX_CHAVE, lote.PIX_QR]
    assert len(itens[0].dados) == 44 and itens[0].dados.startswith("341")
    assert len(itens[1].dados) == 44 and itens[1].dados.startswith("8")
    assert itens[2].documento_esperado == "11222333000181"
    assert [i.ordem for i in itens] == [1, 2, 3, 4]
    assert lote.total(itens) == Decimal("1679.73")


def test_fica_fora_com_motivo():
    contas = [
        {"nome": "OBRA X - INTER", "entries": [_e("10", "Pix", "a@b.com", 100)]},
        {"nome": "OBRA X - SICOOB", "entries": [
            _e("11", "Pix", "a@b.com", 100, nivel=nivel.OLHE, nivel_rotulo="OLHE"),
            _e("12", "Pix", "a@b.com", 100, bloqueio="mesma linha digitável em 2 lançamentos"),
            _e("13#mao:1", "Pix", "a@b.com", 100),
            _e("14#1/2", "Boleto", BANCARIO, 100),
            _e("14#2/2", "Boleto", BANCARIO, 100),
            _e("15", "Boleto", BANCARIO[:-1] + "1", 100),
            _e("16", "Pix", "a@b.com", 0)]}]
    itens, fora = lote.itens_do_html(contas, _doc)
    assert itens == []
    motivos = {f.alvo: f.motivo for f in fora}
    assert motivos["10"] == "conta não é Sicoob"
    assert motivos["11"] == "nível OLHE"
    assert motivos["12"].startswith("mesma linha")
    assert motivos["13#mao:1"] == "pagamento à mão, sem lançamento"
    assert motivos["14#1/2"] == motivos["14#2/2"] == "lançamento dividido em mais de uma linha"
    assert motivos["15"] == "linha digitável não confere"
    assert motivos["16"] == "valor zero"


def test_pix_por_chave_sem_documento_no_cadastro_fica_fora():
    contas = [{"nome": "OBRA X - SICOOB", "entries": [_e("1", "Pix", "a@b.com", 100)]}]
    itens, fora = lote.itens_do_html(contas, lambda f: "")
    assert itens == [] and fora[0].motivo == "Pix sem CPF/CNPJ do favorecido no cadastro"


def test_descricao_cortada_em_100():
    contas = [{"nome": "OBRA X - SICOOB", "entries": [
        _e("1", "Boleto", BANCARIO, 100, descricao="X" * 150)]}]
    itens, _ = lote.itens_do_html(contas, _doc)
    assert len(itens[0].descricao) == 100
