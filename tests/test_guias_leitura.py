# -*- coding: utf-8 -*-
"""Leitura do texto de uma guia/boleto. Texto INVENTADO: o repo é público."""
from datetime import date
from decimal import Decimal

from guias import leitura


def test_valor_com_milhar_e_virgula():
    """`R$ 1.234,56` é mil duzentos e trinta e quatro — não 1,234 e não erro."""
    item = leitura.ler_texto("Valor do documento R$ 1.234,56")

    assert item.valor == Decimal("1234.56")


def test_valor_sem_milhar():
    assert leitura.ler_texto("Valor R$ 641,31").valor == Decimal("641.31")


def test_vencimento_em_dd_mm_aaaa():
    item = leitura.ler_texto("Vencimento 18/09/2026")

    assert item.vencimento == date(2026, 9, 18)


def test_numero_do_documento_pelo_rotulo():
    item = leitura.ler_texto("Nosso numero 0126090459266352-0")

    assert item.documento == "0126090459266352-0"


def test_linha_digitavel_vira_documento_quando_nao_ha_rotulo():
    """Boleto sem "nosso número" legível ainda tem a linha digitável."""
    linha = "34191.79001 01043.510047 91020.150008 1 96610000104200"
    item = leitura.ler_texto(f"Pague em qualquer banco {linha}")

    assert item.documento.replace(".", "").replace(" ", "").isdigit()
    assert len(item.documento.replace(".", "").replace(" ", "")) >= 44


def test_texto_sem_nada_devolve_item_vazio_e_nao_explode():
    item = leitura.ler_texto("pagina em branco")

    assert item.valor is None
    assert item.vencimento is None
    assert item.documento == ""


def test_duas_paginas_com_cobranca_viram_dois_itens(tmp_path, monkeypatch):
    """Guia com duas cobranças no mesmo arquivo (imposto + consignado) é
    separada por página: uma cobrança, um lançamento."""
    paginas = ["Valor R$ 10,00 Vencimento 01/09/2026 Nosso numero AAA",
               "Valor R$ 20,00 Vencimento 02/09/2026 Nosso numero BBB"]
    monkeypatch.setattr(leitura, "_paginas_de_texto", lambda _c: paginas)

    itens = leitura.ler_pdf(tmp_path / "qualquer.pdf")

    assert [i.valor for i in itens] == [Decimal("10.00"), Decimal("20.00")]
    assert [i.pagina for i in itens] == [1, 2]


def test_pagina_sem_cobranca_nao_vira_item(tmp_path, monkeypatch):
    paginas = ["Valor R$ 10,00 Vencimento 01/09/2026 Nosso numero AAA",
               "Instrucoes ao caixa: nao receber apos o vencimento"]
    monkeypatch.setattr(leitura, "_paginas_de_texto", lambda _c: paginas)

    assert len(leitura.ler_pdf(tmp_path / "qualquer.pdf")) == 1
