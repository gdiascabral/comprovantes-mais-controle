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
