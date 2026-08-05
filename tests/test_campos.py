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


def test_campos_inter_pix_sobre_transacao():
    """Layout atual do Inter: traz 'Sobre a transação' e 'Banco Inter', mas os
    rótulos vêm com o valor NA MESMA LINHA — tem de cair no parser clássico.
    Antes o parser 'impresso' sequestrava esse layout e o nome saía
    '4632,00 - Instituição Banco Inter', sem descrição e sem data."""
    c = sr.campos(_ler("inter_pix_sobre_transacao.txt"))
    assert c["banco"] == "INTER"
    assert c["valor"] == "4.632,00"
    assert c["data"] == "31/07/2026"
    assert c["desc"] == "ADM - GESTOR COMERCIAL - 06 2026"
    assert sr.nome_arquivo(c) == "4632,00 - ADM - GESTOR COMERCIAL - 06 2026 - 31-07"


def test_campos_inter_pagamento_boleto():
    """Pagamento de boleto pelo Inter: a descrição não tem OC/NF/centro de
    custo, e o nome saía com a linha de 'Autenticação' no lugar dela."""
    c = sr.campos(_ler("inter_pgto_boleto.txt"))
    assert c["valor"] == "7.020,00"
    assert c["data"] == "31/07/2026"
    assert sr.nome_arquivo(c) == "7020,00 - RECRUTAMENTO E SELECAO - 31-07"


def test_campos_sicoob_boleto_impresso():
    """Layout impresso (rótulos num bloco, valores em outro): a descrição boa
    é a observação com centro de custo — não a razão social do fornecedor,
    que casava com 'DISTRIBUI' e passava na frente."""
    c = sr.campos(_ler("sicoob_boleto_impresso.txt"))
    assert c["valor"] == "1.150,00"
    assert c["desc"] == "DONA MORENA QD 18 LT 8 11 B1 OC 5624"
    assert sr.nome_arquivo(c) == "1150,00 - DONA MORENA QD 18 LT 8 11 B1 OC 5624 - 31-07"


def test_campos_sicoob_darf():
    """Comprovante de tributo: rótulos em CAIXA ALTA ('VALOR TOTAL:',
    'DATA DE PAGAMENTO:'). Sem o casamento sem diferenciar maiúsculas o
    arquivo saía como 'SEM VALOR - SEM DESCRICAO' e não casava com nada."""
    c = sr.campos(_ler("sicoob_darf.txt"))
    assert c["valor"] == "240,22"
    assert c["data"] == "31/07/2026"
    assert sr.nome_arquivo(c) == "240,22 - PAGAMENTO DARF - 31-07"


def test_rotulo_nunca_vira_descricao():
    """Rótulos técnicos ('Instituição', 'CPF/CNPJ', 'Autenticação') não podem
    virar o miolo do nome do arquivo."""
    for fix in ("inter_pix_sobre_transacao.txt", "inter_pgto_boleto.txt",
                "sicoob_boleto_impresso.txt", "sicoob_pix_impresso.txt"):
        nome = sr.nome_arquivo(sr.campos(_ler(fix)))
        for lixo in ("Instituição", "CPF/CNPJ", "CPFCNPJ", "Autentica",
                     "Descrição", "Identificador"):
            assert lixo not in nome, f"{fix}: {nome}"


def test_nome_arquivo_round_trip_para_o_matcher():
    """O nome gerado pelo Separar precisa ser lido de volta pelo matcher."""
    import matcher
    c = sr.campos(_ler("inter_pix_antigo.txt"))
    nome = sr.nome_arquivo(c) + ".pdf"
    p = matcher.parse_pdf(nome)
    assert p is not None
    assert p["valor"] == 7000
    assert "5979" in p["ocs"]
