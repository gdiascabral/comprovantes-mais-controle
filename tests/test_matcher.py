# -*- coding: utf-8 -*-
"""Testes do matcher: parse do NOME do PDF e casamento PDF↔pagamento.

Módulo sem dependências pesadas — roda sempre. Os pagamentos pendentes são
construídos à mão (sem tocar na API); os PDFs vêm de nomes de arquivo, como
o app recebe da pasta de renomeados."""
import matcher


# ------------------------------------------------------------ parse_pdf
def test_parse_pdf_padrao():
    p = matcher.parse_pdf("70,00 - RPB 24 QD 26A LT 12 OC 5979 - 20-07.pdf")
    assert p is not None
    assert p["valor"] == 7000
    assert p["data"] == "2007"
    assert p["desc"] == "RPB 24 QD 26A LT 12 OC 5979"
    assert "5979" in p["ocs"]


def test_parse_pdf_valor_com_milhar():
    p = matcher.parse_pdf("1.890,00 - CONDOMINIO OC 5428 - 01-07.pdf")
    assert p["valor"] == 189000
    assert "5428" in p["ocs"]


def test_parse_pdf_ignora_sufixo_duplicado():
    p = matcher.parse_pdf("70,00 - FORNECEDOR EXEMPLO - 20-07 (2).pdf")
    assert p is not None
    assert p["valor"] == 7000


def test_parse_pdf_valor_e_data_em_qualquer_posicao():
    # modelo personalizado: DATA - VALOR - RECEBEDOR
    p = matcher.parse_pdf("20-07 - 70,00 - FORNECEDOR EXEMPLO.pdf")
    assert p["valor"] == 7000
    assert p["data"] == "2007"
    assert p["desc"] == "FORNECEDOR EXEMPLO"


def test_parse_pdf_sem_valor_retorna_none():
    assert matcher.parse_pdf("FORNECEDOR EXEMPLO - 20-07.pdf") is None


def test_parse_pdf_nao_e_pdf():
    assert matcher.parse_pdf("70,00 - X - 20-07.txt") is None


# ------------------------------------------------------------ casar
def _pend(paid_id, valor, doc="", desc="", works=None, data="", valores=None):
    """Monta um pagamento pendente no formato que montar_pagos() produziria."""
    return {
        "paidId": paid_id, "launchId": "L-" + paid_id, "valor": valor,
        "valores": valores or [valor], "doc": doc, "desc": desc,
        "works": works or [], "data": data,
    }


def test_casar_certeza_por_ocnf():
    # OC ROTULADA na descrição do lançamento: é o sinal forte.
    pdfs = [matcher.parse_pdf("70,00 - RPB QD 26A LT 12 OC 5979 - 20-07.pdf")]
    pend = [_pend("A", 7000, desc="pagamento fornecedor OC 5979")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert len(certezas) == 1 and not duvidas and not sem_par
    assert certezas[0]["pdf"] == "70,00 - RPB QD 26A LT 12 OC 5979 - 20-07.pdf"
    assert "OC/NF" in certezas[0]["motivo"]


def test_ocnf_do_lancamento_exige_rotulo():
    """Número solto na descrição não é OC/NF.

    Um ano ("2026"), um CEP ou um telefone casavam com um PDF chamado
    "OC 2026" e fechavam CERTEZA sozinhos. Com dois pagamentos de mesmo valor
    disputando, o certo é DÚVIDA — não escolher no chute."""
    pdfs = [matcher.parse_pdf("70,00 - OBRA OC 2026 - 20-07.pdf"),
            matcher.parse_pdf("70,00 - OUTRA COISA - 21-07.pdf")]
    pend = [_pend("A", 7000, desc="SERVICO REFERENTE A 2026"),
            _pend("B", 7000, desc="OUTRO SERVICO")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert not certezas, "número solto na descrição não pode fechar CERTEZA"
    assert len(duvidas) == 2


def test_documento_cru_sozinho_nao_fecha_certeza():
    """`documentNumber` cru é sinal FRACO: com concorrente de mesmo valor,
    não basta para casar (mas continua valendo como desempate)."""
    pdfs = [matcher.parse_pdf("70,00 - FORNECEDOR OC 5979 - 20-07.pdf"),
            matcher.parse_pdf("70,00 - OUTRO FORNECEDOR - 21-07.pdf")]
    pend = [_pend("A", 7000, doc="5979", desc="sem rotulo aqui"),
            _pend("B", 7000, desc="outro")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert not certezas
    assert len(duvidas) == 2


def test_documento_cru_com_centro_de_custo_fecha_certeza():
    """Acompanhado do centro de custo, o nº do documento volta a valer."""
    pdfs = [matcher.parse_pdf("70,00 - RPB 24 QD 26A LT 12 OC 5979 - 20-07.pdf"),
            matcher.parse_pdf("70,00 - OUTRO FORNECEDOR - 21-07.pdf")]
    pend = [_pend("A", 7000, doc="5979", desc="x",
                  works=["RPB 24 QD 26A LT 12"]),
            _pend("B", 7000, desc="outro")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert len(certezas) == 1
    assert certezas[0]["paidId"] == "A"


def test_casar_certeza_por_data_sem_concorrente():
    pdfs = [matcher.parse_pdf("70,00 - FORNECEDOR EXEMPLO - 20-07.pdf")]
    pend = [_pend("A", 7000, desc="algo", data="2007")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert len(certezas) == 1
    assert certezas[0]["motivo"] == "data"


def test_casar_duvida_quando_ambiguo():
    # dois pagamentos e dois PDFs de mesmo valor, nada os distingue -> DÚVIDA
    pdfs = [matcher.parse_pdf("70,00 - FORNECEDOR A - 20-07.pdf"),
            matcher.parse_pdf("70,00 - FORNECEDOR B - 21-07.pdf")]
    pend = [_pend("A", 7000, desc="x"), _pend("B", 7000, desc="y")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert not certezas
    assert len(duvidas) == 2


def test_casar_sem_par_quando_nao_ha_valor_igual():
    pdfs = [matcher.parse_pdf("50,00 - OUTRO - 20-07.pdf")]
    pend = [_pend("A", 7000, desc="x")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert len(sem_par) == 1 and not certezas


def test_casar_aceita_valor_pago_com_juros():
    # PDF tem o valor PAGO (com juros); o pagamento guarda nominal e pago
    pdfs = [matcher.parse_pdf("105,00 - BOLETO OC 5428 - 20-07.pdf")]
    pend = [_pend("A", 10000, doc="5428", valores=[10000, 10500])]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert len(certezas) == 1
    assert certezas[0]["pdf"] == "105,00 - BOLETO OC 5428 - 20-07.pdf"
