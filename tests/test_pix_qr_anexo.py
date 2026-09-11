# -*- coding: utf-8 -*-
"""Pix sem chave com o QR Code anexado (11/09/2026): a linha ENTRA.

A guia do cartório e o print da compra de marketplace chegam sem chave no
cadastro e só com a imagem do QR Code do Pix. O ramo do Pix nunca olhava
anexo, e a linha ia para NÃO ENTRARAM como "sem forma de pagar" — o título
vencia sem ninguém ver. O boleto em imagem sempre ficou na planilha; o QR
Code em imagem é o mesmo caso.

Nenhum dado real: nomes, valores e arquivos inventados. O repo é público.
"""
from pagamentos_dia import regras_pagamento as regras
from pagamentos_dia import relatorio
from pagamentos_dia import remessa_dia


def anexo(nome, tag=None, ext=".pdf", url=None):
    return {"filename": nome, "tagName": tag, "extension": ext,
            "downloadUrl": url or f"https://exemplo.invalid/{nome}"}


def linhas(resultado):
    return next(iter(resultado.contas.values()))


def pix_sem_chave(**extra):
    item = {"id": "x1", "tradePayableId": "x1", "paidTo": "Cartorio Exemplo",
            "remainingValue": 123.45, "tradePayablePaymentMethod": "Pix",
            "tradePayableAccount": {"name": "CONTA TESTE"},
            "costCentreDetails": [{"workName": "OBRA X"}]}
    item.update(extra)
    return item


def test_qr_code_em_imagem_faz_a_linha_entrar():
    anexos = {"x1": [anexo("qrcode-pagamento", None, ext=".png")]}
    res = relatorio.montar_registros([pix_sem_chave()], anexos, {}, {})
    assert res.omitidos == []
    linha = linhas(res)[0]
    assert linha["tipo"] == "Pix"
    assert linha["dados"] == ""
    assert "QR Code do anexo 'qrcode-pagamento'" in linha["obs"]
    assert linha["status"].startswith("ATENÇÃO")


def test_extensao_sem_ponto_tambem_e_imagem():
    """O ERP devolve `extension` com ponto; sem ele a imagem não pode sumir."""
    anexos = {"x1": [anexo("guia", None, ext="jpeg")]}
    linha = linhas(relatorio.montar_registros([pix_sem_chave()], anexos, {}, {}))[0]
    assert "QR Code do anexo 'guia'" in linha["obs"]


def test_com_nota_e_print_aponta_o_print():
    anexos = {"x1": [anexo("nf 123", "Nota Fiscal", url="un"),
                     anexo("print da compra", None, ext=".jpg")]}
    res = relatorio.montar_registros([pix_sem_chave()], anexos, {},
                                     {"un": "DANFE NF-e 123"})
    assert "QR Code do anexo 'print da compra'" in linhas(res)[0]["obs"]


def test_pdf_sem_rotulo_entra_mandando_abrir_o_anexo():
    anexos = {"x1": [anexo("documento 9", None, url="ud")]}
    res = relatorio.montar_registros([pix_sem_chave()], anexos, {}, {"ud": ""})
    assert res.omitidos == []
    assert "abrir o anexo 'documento 9'" in linhas(res)[0]["obs"]


def test_so_comprovante_pelo_rotulo_continua_fora():
    """Comprovante prova pagamento JÁ feito: pagar por ele é pagar em dobro."""
    anexos = {"x1": [anexo("Comprovante cartao", "Comprovante", ext=".jpg")]}
    res = relatorio.montar_registros([pix_sem_chave()], anexos, {}, {})
    assert res.contas == {}
    assert res.omitidos[0]["motivo"] == regras.MOTIVO_SEM_PAGAR


def test_pdf_com_texto_de_quem_ja_pagou_continua_fora():
    anexos = {"x1": [anexo("documento 9", None, url="ud")]}
    res = relatorio.montar_registros(
        [pix_sem_chave()], anexos, {},
        {"ud": "Comprovante de pagamento — Pix enviado"})
    assert res.contas == {}
    assert res.omitidos[0]["motivo"] == regras.MOTIVO_SEM_PAGAR


def test_sem_anexo_nenhum_continua_fora():
    res = relatorio.montar_registros([pix_sem_chave()], {}, {}, {})
    assert res.contas == {}
    assert res.omitidos[0]["motivo"] == regras.MOTIVO_SEM_PAGAR


def test_pix_com_chave_no_cadastro_nao_muda():
    item = pix_sem_chave(paidToBankAccount="PIX CNPJ: 22.333.444/0001-55")
    anexos = {"x1": [anexo("qrcode", None, ext=".png")]}
    linha = linhas(relatorio.montar_registros([item], anexos, {}, {}))[0]
    assert linha["dados"] == "22.333.444/0001-55"
    assert "QR Code" not in linha["obs"]


def test_linha_ja_paga_nao_ganha_aviso_de_qr():
    item = pix_sem_chave(paid=True, dateOfPayment="2026-01-01")
    anexos = {"x1": [anexo("qrcode", None, ext=".png")]}
    res = relatorio.montar_registros([item], anexos, {}, {})
    assert res.omitidos == []
    assert linhas(res)[0]["status"].startswith("JÁ PAGO")


def test_a_remessa_continua_recusando_pix_sem_dados():
    """A linha entra na planilha para ser paga À MÃO; no arquivo do banco um
    Pix sem chave não existe."""
    assert remessa_dia._impedimento({"dados": "", "tipo": "Pix"}, "", "Pix") \
        == remessa_dia.MOTIVO_SEM_CHAVE


def test_preferencia_do_anexo():
    files = [anexo("nf 1", "Nota Fiscal"), anexo("foto", None, ext=".png"),
             anexo("qr code pix", None)]
    assert relatorio.anexo_para_pagar_a_mao(files)["filename"] == "qr code pix"
    assert relatorio.anexo_para_pagar_a_mao(files[:2])["filename"] == "foto"
    assert relatorio.anexo_para_pagar_a_mao([]) is None
