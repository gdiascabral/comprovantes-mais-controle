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
