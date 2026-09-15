# -*- coding: utf-8 -*-
"""Ordem das linhas e descrição para colar no banco (pedido do dono, 14/09/2026).

Puro: só `relatorio` e `html_pagamentos`, sem janela, sem ERP e sem rede.
Nenhum nome, lote, OC, NF ou valor aqui é de verdade — o repositório é público.
"""
from pagamentos_dia import relatorio


def anexo(nome, tag=None, ext=".pdf", url=None):
    return {"filename": nome, "tagName": tag, "extension": ext,
            "downloadUrl": url or f"https://exemplo.invalid/{nome}"}


# ------------------------------------------------- REEMBOLSO não é número de NF
def test_reembolso_no_documento_do_detalhe_nao_vira_nf():
    """O `documentNumber` do item já era filtrado, mas o do detalhe (que traz o
    mesmo texto) não: saía "NF REEMBOLSO FULANO", e a conferência procurava
    uma nota que não existe."""
    item = {"documentNumber": "REEMBOLSO FULANO MODELO",
            "costCentreDetails": [{"workName": "QD 99 LT 99"}]}
    overview = {"documentNumber": "REEMBOLSO FULANO MODELO",
                "purchaseOrder": {"number": 1234}}
    assert relatorio.achar_doc(item, [], overview) == ""
    assert relatorio.monta_descricao(item, [], "", overview) == "QD 99 LT 99 OC 1234"


def test_reembolso_no_nome_do_anexo_nao_vira_nf():
    item = {"costCentreDetails": [{"workName": "QD 99 LT 99"}]}
    files = [anexo("REEMBOLSO FULANO MODELO NO 55")]
    assert relatorio.achar_doc(item, files) == ""


def test_nf_de_verdade_no_nome_do_anexo_continua_valendo():
    item = {"costCentreDetails": [{"workName": "QD 99 LT 99"}]}
    files = [anexo("REEMBOLSO FULANO MODELO"), anexo("NF 5678 Fornecedor Modelo")]
    assert relatorio.achar_doc(item, files) == "5678"


# ------------------------------------------------------------------- a ordem
CONTA = "CONTA MODELO - INTER"


def _pix(ident, favorecido):
    return {"id": ident, "tradePayableId": f"t{ident}", "paid": False,
            "tradePayableAccount": {"name": CONTA}, "paidTo": favorecido,
            "remainingValue": 10.0, "tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": "PIX EMAIL fornecedor@exemplo.com",
            "documentNumber": "5678",
            "costCentreDetails": [{"workName": "QD 99 LT 99"}]}


def _boleto(ident, favorecido):
    item = dict(_pix(ident, favorecido), tradePayablePaymentMethod="Boleto")
    item.pop("paidToBankAccount")
    return item


def _ids(lancamentos, anexos=None):
    res = relatorio.montar_registros(lancamentos, anexos or {}, {}, {})
    return [(r["tipo"], r["id"]) for r in res.contas[CONTA]]


def test_boleto_antes_de_pix_e_o_ultimo_do_sistema_primeiro():
    """Pedido do dono: continua boleto antes de Pix; dentro do tipo, a ordem em
    que aparecem no sistema, invertida — o último vem primeiro."""
    lancamentos = [_pix("1", "Fornecedor A"), _boleto("2", "Fornecedor B"),
                   _pix("3", "Fornecedor C"), _boleto("4", "Fornecedor D"),
                   _pix("5", "Fornecedor E")]
    anexos = {f"t{i}": [anexo(f"boleto {i}", "Boleto")] for i in ("2", "4")}
    assert _ids(lancamentos, anexos) == [
        ("Boleto", "4"), ("Boleto", "2"),
        ("Pix", "5"), ("Pix", "3"), ("Pix", "1")]


def test_o_favorecido_nao_decide_mais_a_ordem():
    """Até aqui a segunda chave era o favorecido em ordem alfabética, e a lista
    do HTML não conversava com a tela do sistema."""
    lancamentos = [_pix("1", "Zeta Modelo"), _pix("2", "Alfa Modelo"),
                   _pix("3", "Alfa Modelo")]
    assert _ids(lancamentos) == [("Pix", "3"), ("Pix", "2"), ("Pix", "1")]
    # a mesma entrada dá sempre a mesma saída
    assert _ids(lancamentos) == _ids(list(lancamentos))
