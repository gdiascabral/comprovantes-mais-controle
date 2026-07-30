# -*- coding: utf-8 -*-
"""Testes de extração de campos a partir do TEXTO do comprovante.

As fixtures em tests/fixtures/*.txt são o texto que sairia do pdfplumber (ou
do OCR, no layout impresso). São SINTÉTICAS — nomes/documentos fake — porque
o repositório é público e não pode conter comprovantes reais. Para cobrir um
banco/layout novo, salve aqui o texto ANONIMIZADO de um exemplo."""
from pathlib import Path

import pytest

# separar_renomear importa tkinter/pdfplumber no topo; se faltarem, pula.
sr = pytest.importorskip("separar_renomear")

FIX = Path(__file__).resolve().parent / "fixtures"


def _ler(nome):
    return (FIX / nome).read_text(encoding="utf-8")


def test_campos_inter_pix_antigo():
    c = sr.campos(_ler("inter_pix_antigo.txt"))
    assert c["banco"] == "INTER"
    assert c["valor"] == "70,00"
    assert c["data"] == "20/07/2026"
    assert "OC 5979" in c["desc"]


def test_campos_sicoob_pix_impresso():
    c = sr.campos(_ler("sicoob_pix_impresso.txt"))
    assert c["banco"] == "SICOOB"
    assert c["valor"] == "1.890,00"
    assert "5428" in c["desc"]


def test_nome_arquivo_round_trip_para_o_matcher():
    """O nome gerado pelo Separar precisa ser lido de volta pelo matcher."""
    import matcher
    c = sr.campos(_ler("inter_pix_antigo.txt"))
    nome = sr.nome_arquivo(c) + ".pdf"
    p = matcher.parse_pdf(nome)
    assert p is not None
    assert p["valor"] == 7000
    assert "5979" in p["ocs"]
