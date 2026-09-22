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


def test_campo_zerado_antes_do_total_nao_vira_o_valor():
    """Todo boleto imprime Desconto/Multa zerados ANTES do total. Pegar o
    primeiro `NN,NN` da página é pegar o zero — dinheiro errado no ERP."""
    texto = "Desconto R$ 0,00 Multa R$ 0,00 Valor da cobranca R$ 1.234,56"

    assert leitura.ler_texto(texto).valor == Decimal("1234.56")


def test_valor_a_pagar_e_rotulo_reconhecido():
    texto = "Juros R$ 0,00 Valor a pagar R$ 641,31"

    assert leitura.ler_texto(texto).valor == Decimal("641.31")


def test_valor_sem_rotulo_nenhum_descarta_contexto_de_deducao():
    texto = "Desconto R$ 12,00 R$ 738,00"

    assert leitura.ler_texto(texto).valor == Decimal("738.00")


def test_valor_zero_nunca_e_o_valor_do_documento():
    assert leitura.ler_texto("Valor do documento R$ 0,00").valor is None


def test_linha_digitavel_validada_vira_o_documento(monkeypatch):
    """Só linha que fecha o dígito verificador vira documento."""
    from pagamentos_dia import ocr_boleto

    monkeypatch.setattr(leitura.ocr_boleto, "valida",
                        lambda d: len(ocr_boleto.digitos(d)) == 47)
    linha = "3" * 47
    item = leitura.ler_texto(f"Pague em qualquer banco {linha} Valor R$ 10,00")

    assert ocr_boleto.digitos(item.documento) == linha


def test_linha_que_nao_fecha_o_dv_nao_vira_documento(monkeypatch):
    monkeypatch.setattr(leitura.ocr_boleto, "valida", lambda _d: False)
    item = leitura.ler_texto("Nosso numero 12345 Valor R$ 10,00")

    assert item.documento == "12345"


def test_ficha_de_arrecadacao_de_48_digitos_e_reconhecida():
    """O alvo primário desta função é guia de FGTS/INSS, que é ficha de
    arrecadação: 48 dígitos, quatro blocos de 11 + DV, e NÃO boleto bancário.
    A linha é montada com os DV calculados de verdade — linha inventada não
    fecha o DV e faria o teste provar o caminho errado."""
    from pagamentos_dia import ocr_boleto

    # `d[2]` fora de "89" escolhe o DV por módulo 10. O `_mod10` do próprio
    # módulo é usado para MONTAR a linha: reimplementá-lo aqui seria uma
    # segunda cópia da regra, e é ela que o teste quer exercitar.
    blocos = ["81600000000", "00073800120", "26012345678", "90000000001"]
    linha = "".join(b + str(ocr_boleto._mod10(b)) for b in blocos)
    assert len(linha) == 48
    assert ocr_boleto.valida(linha), "a linha do teste tem de fechar o DV"

    item = leitura.ler_texto(f"Pague em qualquer casa loterica {linha}")

    assert ocr_boleto.digitos(item.documento) == linha


def test_digitos_espalhados_pela_pagina_nao_formam_linha_digitavel():
    """Antes deste conserto a busca corria a página concatenada e podia casar
    CNPJ+CEP+telefone como se fossem uma linha digitável — 2 a 4% das páginas.
    Linha física curta não é candidata, por mais dígitos que a página tenha."""
    texto = "\n".join(["CNPJ 00.000.000/0001-00", "CEP 74000-000",
                       "Fone 62 0000-0000", "Competencia 09/2026",
                       "Valor do documento R$ 641,31"])
    item = leitura.ler_texto(texto)

    assert item.documento == ""
    assert item.valor == Decimal("641.31")
