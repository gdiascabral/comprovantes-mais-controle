# -*- coding: utf-8 -*-
"""Autenticar o boleto (dono, 09/11/2026): o CNPJ de quem recebe no boleto
(beneficiário, ou sacador/avalista quando há intermediário) tem de ser o do
emitente da nota anexada ou o do cadastro do favorecido. Boleto de outra
empresa sai "ATENÇÃO — boleto de outra empresa" (a remessa nasce desmarcada e
o HTML bloqueia o Copiar). CNPJs gerados aqui: o repositório é público."""
from pagamentos_dia import relatorio
from tests.test_casamento_html import anexo, fmt, gera_cnpj, gera_linha, item, linhas

LOJA, OUTRA, PAGADOR, BANCO = (gera_cnpj("11222333"), gera_cnpj("44555666"),
                               gera_cnpj("55666777"), gera_cnpj("98765432"))


def _boleto(beneficiario, extra=""):
    return (f"Banco Modelo S.A. CNPJ {fmt(BANCO)}\nFicha de Compensação\n"
            f"Beneficiário LOJA MODELO CNPJ {fmt(beneficiario)}\n"
            f"Pagador EMPRESA CNPJ {fmt(PAGADOR)}\n{extra}{gera_linha()}\n"
            "Valor do documento 1.000,00\n")


def _nota(emitente):
    return (f"DANFE Nota Fiscal Eletronica 64000\nEmitente CNPJ {fmt(emitente)}\n"
            f"Destinatario CNPJ {fmt(PAGADOR)}\nValor 1.000,00\n")


def _linha(texto_boleto, texto_nota=None, cadastro=None):
    it = item(tradePayablePaymentMethod="Boleto",
              paidToBankAccount=("PIX CNPJ: " + fmt(cadastro)) if cadastro else "")
    anexos = [anexo("boleto.pdf", "Boleto", url="ub")]
    textos = {"ub": texto_boleto}
    if texto_nota:
        anexos.append(anexo("NF 64000.pdf", "Nota Fiscal", url="un"))
        textos["un"] = texto_nota
    return linhas(relatorio.montar_registros([it], {"x1": anexos}, {}, textos))[0]


def test_boleto_da_mesma_empresa_da_nota_e_do_cadastro_autentica():
    linha = _linha(_boleto(LOJA), _nota(LOJA), cadastro=LOJA)
    assert linha["status"] == "APTO"
    assert "beneficiário ✓ (= NF e cadastro)" in linha["conferencia"]


def test_boleto_de_outra_empresa_vira_atencao():
    linha = _linha(_boleto(OUTRA), _nota(LOJA), cadastro=LOJA)
    assert linha["status"] == "ATENÇÃO — boleto de outra empresa"
    assert "BENEFICIÁRIO DIVERGE" in linha["conferencia"]
    assert fmt(OUTRA) in linha["obs"] and fmt(LOJA) in linha["obs"]


def test_boleto_de_filial_da_mesma_empresa_passa():
    linha = _linha(_boleto(gera_cnpj("11222333", "0002")), _nota(LOJA))
    assert linha["status"] == "APTO" and "filial" in linha["conferencia"]


def test_intermediario_com_a_loja_como_sacador_avalista_passa():
    linha = _linha(_boleto(OUTRA, f"Sacador/Avalista LOJA MODELO {fmt(LOJA)}\n"),
                   _nota(LOJA))
    assert linha["status"] == "APTO" and "beneficiário ✓" in linha["conferencia"]


def test_so_cadastro_sem_nota_tambem_autentica():
    assert "beneficiário ✓ (= cadastro)" in _linha(_boleto(LOJA), cadastro=LOJA)["conferencia"]
    assert _linha(_boleto(OUTRA), cadastro=LOJA)["status"] == "ATENÇÃO — boleto de outra empresa"


def test_sem_com_o_que_comparar_nao_diz_nada():
    linha = _linha(_boleto(LOJA))
    assert linha["status"] == "APTO" and "beneficiário" not in linha["conferencia"]


def test_cnpj_do_banco_e_do_pagador_nao_contam_como_beneficiario():
    assert relatorio.cnpjs_do_beneficiario(_boleto(LOJA)) == [LOJA]


# ------------------------------------------- revisão de dinheiro, 09/11/2026
def test_cnpj_da_loja_nas_instrucoes_nao_autentica_boleto_alheio():
    texto = (f"Ficha de Compensação\nBeneficiário COBRANCA X CNPJ {fmt(OUTRA)}\n"
             f"Instruções: referente NF 64000 de LOJA MODELO CNPJ {fmt(LOJA)}\n"
             f"Pagador EMPRESA CNPJ {fmt(PAGADOR)}\n{gera_linha()}\n")
    assert relatorio.cnpjs_do_beneficiario(texto) == [OUTRA]
    assert _linha(texto, _nota(LOJA), cadastro=LOJA)["status"] == \
        "ATENÇÃO — boleto de outra empresa"


def test_nota_e_boleto_alheio_no_mesmo_pdf_nao_sai_verde():
    it = item(tradePayablePaymentMethod="Boleto", paidToBankAccount="PIX CNPJ: " + fmt(LOJA))
    junto = _nota(LOJA) + _boleto(OUTRA)
    anexos = {"x1": [anexo("NF 64000.pdf", "Nota Fiscal", url="un")]}
    linha = linhas(relatorio.montar_registros([it], anexos, {}, {"un": junto}))[0]
    assert "beneficiário ✓" not in linha["conferencia"]
    assert linha["status"] == "ATENÇÃO — boleto de outra empresa"


def test_nota_e_boleto_da_loja_no_mesmo_pdf_autentica():
    it = item(tradePayablePaymentMethod="Boleto")
    anexos = {"x1": [anexo("NF 64000.pdf", "Nota Fiscal", url="un")]}
    linha = linhas(relatorio.montar_registros(
        [it], anexos, {}, {"un": _nota(LOJA) + _boleto(LOJA)}))[0]
    assert linha["status"] == "APTO" and "beneficiário ✓ (= NF)" in linha["conferencia"]


def test_44_digitos_no_nome_do_boleto_nao_viram_nota():
    it = item(tradePayablePaymentMethod="Boleto")
    anexos = {"x1": [anexo("boleto " + "2" * 44 + ".pdf", "Boleto", url="ub")]}
    linha = linhas(relatorio.montar_registros([it], anexos, {}, {"ub": _boleto(LOJA)}))[0]
    # (o nome com 44 dígitos ainda é lido como chave pela conferência da NF,
    # que já existia; aqui só importa que ele não vire "a NF" do beneficiário)
    assert "BENEFICIÁRIO DIVERGE" not in linha["conferencia"]
    assert linha["status"] != "ATENÇÃO — boleto de outra empresa"


def test_guia_de_arrecadacao_nao_e_conferida():
    from pagamentos_dia import ocr_boleto
    guia = "85800000010-0 00000000000-0 00000000000-0 00000000000-0"
    assert not ocr_boleto.eh_arrecadacao(gera_linha())
    # a regra do montar_registros só roda para linha de 47 dígitos de cobrança
    assert len(ocr_boleto.digitos(guia)) == 48 and ocr_boleto.eh_arrecadacao(guia)


# ------------------------------------- beneficiário aceito (dono, 09/11/2026)
def test_beneficiario_aceito_no_regras_fornecedor_passa():
    from pagamentos_dia import regras_pagamento as regras
    r = {"LOJA MODELO": {"beneficiarios_aceitos": [OUTRA[:8]]}}
    aceitos = regras.beneficiarios_aceitos("Loja Modelo Ltda", r)
    assert aceitos == [OUTRA[:8]]
    res, txt = relatorio.conferir_beneficiario_do_boleto(
        _boleto(OUTRA), "Loja Modelo Ltda", "PIX CNPJ: " + fmt(LOJA), {}, [], {},
        aceitos=aceitos)
    assert res == "ok" and "aceito" in txt


def test_sem_regra_o_mesmo_boleto_diverge():
    res, _ = relatorio.conferir_beneficiario_do_boleto(
        _boleto(OUTRA), "Loja Modelo Ltda", "PIX CNPJ: " + fmt(LOJA), {}, [], {})
    assert res == "diverge"
