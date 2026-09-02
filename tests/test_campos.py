# -*- coding: utf-8 -*-
"""Testes de extração de campos a partir do TEXTO do comprovante.

As fixtures em tests/fixtures/*.txt são o texto que sairia do pdfplumber (ou
do OCR, no layout impresso). São SINTÉTICAS — nomes/documentos fake — porque
o repositório é público e não pode conter comprovantes reais. Para cobrir um
banco/layout novo, salve aqui o texto ANONIMIZADO de um exemplo."""
from pathlib import Path

import pytest

# separar_renomear importa tkinter/pdfplumber no topo; se faltarem, pula.
sr = pytest.importorskip("separar_renomear.separar_renomear")

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


def test_descricao_colada_vence_o_nome_do_recebedor():
    """PIX impresso: o OCR come os espaços do centro de custo e a descrição
    vira um bloco só ('TB21QD51LT23C282M3'). Antes ela era descartada (parecia
    código, por ser cheia de dígito) e o nome caía no DESTINATÁRIO — saía
    '7130,00 - Fulano de Tal Exemplo'. Deve sair o centro de custo, espaçado
    para o matcher enxergar QD/LT."""
    c = sr.campos(_ler("sicoob_pix_desc_colada.txt"))
    assert c["valor"] == "7.130,00"
    assert c["data"] == "31/07/2026"
    assert sr.nome_arquivo(c) == "7130,00 - TB 21 QD 51 LT 23 C 282 M 3 - 31-07"


def test_espacar_codigo_so_mexe_no_que_deve():
    assert sr._espacar_codigo("TB21QD51LT23C282M3") == "TB 21 QD 51 LT 23 C 282 M 3"
    # vale por palavra: conserta também a descrição meio colada
    assert sr._espacar_codigo("DONA MORENA QD 18LT811B1C259M5") == \
        "DONA MORENA QD 18 LT 811 B 1 C 259 M 5"
    # já espaçado, curto demais, texto normal ou ID: não mexe
    for intocado in ("RPB 24 QD 26A LT 10 OC 6332", "COMBUSTIVEL",
                     "E0438868820260731180053vasuoyr4V", "ENGENHEIRO",
                     "Pos obra OC6323", "ADM - GESTOR COMERCIAL - 06 2026"):
        assert sr._espacar_codigo(intocado) == intocado


def test_recebedor_desempata_nomes_repetidos():
    """Dois comprovantes de mesmo valor e mesma descrição no mesmo dia viravam
    'X' e 'X (2)'. Com com_recebedor entra quem recebeu, que é o que de fato
    distingue os dois."""
    c = sr.campos(_ler("inter_pix_sobre_transacao.txt"))
    assert sr.nome_arquivo(c) == "4632,00 - ADM - GESTOR COMERCIAL - 06 2026 - 31-07"
    assert sr.nome_arquivo(c, com_recebedor=True) == (
        "4632,00 - ADM - GESTOR COMERCIAL - 06 2026 - FULANO DE TAL EXEMPLO - 31-07")
    # modelo personalizado que já pede RECEBEDOR não pode duplicar o nome
    modelo = "VALOR - DESCRIÇÃO - RECEBEDOR"
    assert sr.nome_arquivo(c, modelo, com_recebedor=True) == \
        sr.nome_arquivo(c, modelo)


def _pix(valor, desc, dest):
    return dict(banco="INTER", tipo="PIX", valor=valor, data="31/07/2026",
                desc=desc, pag="EMPRESA EXEMPLO LTDA", dest=dest)


def test_valor_repetido_poe_o_recebedor_em_TODOS():
    """Antes só o segundo do grupo levava o nome de quem recebeu, e sobrava um
    '1621,00 - ESTAGIÁRIO - 31-07' sem dono. Para o casamento distinguir os
    dois, os dois precisam do nome."""
    nomes = sr._nomes_finais([
        _pix("1.621,00", "ESTAGIÁRIO", "Fulano de Tal Exemplo"),
        _pix("1.621,00", "ESTAGIÁRIO", "Beltrano Exemplo"),
        _pix("500,00", "COMBUSTIVEL", "Sicrano Exemplo"),   # não repete
    ])
    assert nomes == [
        "1621,00 - ESTAGIÁRIO - Fulano de Tal Exemplo - 31-07",
        "1621,00 - ESTAGIÁRIO - Beltrano Exemplo - 31-07",
        "500,00 - COMBUSTIVEL - 31-07",
    ]


def test_nome_que_ja_existe_na_pasta_tambem_ganha_recebedor():
    nomes = sr._nomes_finais(
        [_pix("500,00", "COMBUSTIVEL", "Fulano de Tal Exemplo")],
        ja_existe=lambda b: b == "500,00 - COMBUSTIVEL - 31-07")
    assert nomes == ["500,00 - COMBUSTIVEL - Fulano de Tal Exemplo - 31-07"]


def test_recebedor_nao_repete_quando_ja_esta_no_nome():
    """Em aporte/transferência o miolo já é 'PAGADOR PARA RECEBEDOR'."""
    c = dict(banco="INTER", tipo="PIX", valor="1.000,00", data="31/07/2026",
             desc="APORTE CAPITAL", pag="EMPRESA A LTDA", dest="EMPRESA B LTDA")
    assert sr.nome_arquivo(c, com_recebedor=True) == \
        "1000,00 - EMPRESA A PARA EMPRESA B - 31-07"


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
    from anexar import matcher
    c = sr.campos(_ler("inter_pix_antigo.txt"))
    nome = sr.nome_arquivo(c) + ".pdf"
    p = matcher.parse_pdf(nome)
    assert p is not None
    assert p["valor"] == 7000
    assert "5979" in p["ocs"]
