# -*- coding: utf-8 -*-
"""Duas travas que nasceram de olhar o ERP de verdade, em 11/08/2026.

Complementa `test_pagamentos_melhorias.py` — mesmo módulo, outro par de
perguntas:

1. **O boleto manda no valor.** A regra "R$ 1,00 é marcador de recorrência"
   apagava uma conta de luz real: no arquivo de 08 a 10/08/2026 havia uma
   Equatorial lançada como R$ 1,00 cujo código de barras anexado dizia
   R$ 56,24. Naquele arquivo, essa regra excluía exatamente UMA linha — e era
   a única que não devia sair.
2. **O tipo da chave Pix.** O ERP não tem o campo: a chave chega dentro de um
   texto livre. Dos 116 lançamentos com o campo preenchido no período, 75
   declaram o tipo por escrito ("PIX CNPJ" 65 vezes, "PIX CELULAR" 7,
   "PIX CPF" 3) e ~30 não declaram nada. CPF e celular têm os dois onze
   dígitos: onde ninguém declarou e a pontuação não entrega, ninguém chuta.

Nenhum dado real: os números são inventados e as linhas digitáveis não dizem
quem pagou. O repo é público.
"""
import pytest

import ocr_boleto
import regras_pagamento as regras
import relatorio
import util

from test_pagamentos_melhorias import LINHA_BANCARIA, VALOR_BANCARIA, anexo, lancamento, linhas


# ==========================================================================
# 1. O boleto manda no valor
# ==========================================================================
def test_boleto_que_diz_outro_valor_contradiz_o_lancamento():
    assert regras.documento_contradiz_valor(1.00, VALOR_BANCARIA)


def test_boleto_do_mesmo_valor_nao_contradiz():
    assert not regras.documento_contradiz_valor(VALOR_BANCARIA, VALOR_BANCARIA)
    # Centavo de diferença é arredondamento, não divergência.
    assert not regras.documento_contradiz_valor(1150.00, 1150.009)


def test_sem_boleto_nao_ha_o_que_contradizer():
    assert not regras.documento_contradiz_valor(1.00, None)


def test_um_real_com_boleto_de_outro_valor_NAO_e_omitido():
    """O caso Equatorial: o valor simbólico perde para o código de barras."""
    assert regras.motivo_omissao(1.00, "Equatorial", LINHA_BANCARIA, True, {},
                                 valor_documento=VALOR_BANCARIA) == ""


def test_um_real_sem_boleto_continua_omitido():
    """A regra não foi desligada — só deixou de valer contra prova."""
    assert regras.motivo_omissao(1.00, "Fulano", "", False, {}) == \
        regras.MOTIVO_SIMBOLICO


def test_um_real_com_boleto_do_mesmo_valor_continua_omitido():
    assert regras.motivo_omissao(1.00, "Fulano", "linha", True, {},
                                 valor_documento=1.00) == regras.MOTIVO_SIMBOLICO


def test_a_conta_de_luz_de_um_real_aparece_na_planilha_com_alarme():
    """Ponta a ponta: entra, com os DOIS valores à vista de quem confere."""
    item = lancamento(paidTo="Equatorial", remainingValue=1.00,
                      documentNumber="113")
    anexos = {"x1": [anexo("boleto energia", "Boleto", url="ub")]}
    res = relatorio.montar_registros([item], anexos, {}, {"ub": LINHA_BANCARIA})

    assert res.omitidos == [], "a conta foi apagada em vez de denunciada"
    linha = linhas(res)[0]
    assert linha["status"] == "ATENÇÃO — valor do boleto diverge"
    assert "1.150,00" in linha["obs"] and "1,00" in linha["obs"]


def test_boleto_que_confere_nao_vira_alarme():
    """Alarme falso ensina a ignorar alarme: valor batendo, nada a dizer."""
    item = lancamento(paidTo="Fornecedor", remainingValue=VALOR_BANCARIA,
                      documentNumber="113")
    anexos = {"x1": [anexo("boleto", "Boleto", url="ub")]}
    res = relatorio.montar_registros([item], anexos, {}, {"ub": LINHA_BANCARIA})
    linha = linhas(res)[0]
    assert "diverge" not in linha["status"]
    assert "conferir ANTES de pagar" not in linha["obs"]


# ----------------------------------------------------- pagamento parcial
# O ERP quita um título em vezes: nos 1.118 lançamentos de 25/07 a 12/08/2026,
# dezessete tinham dois pagamentos. Aí o boleto é do valor CHEIO e o lançamento
# traz o que FALTA — e a conferência de valor acusava divergência num caso
# perfeitamente normal.

def test_segunda_parcela_nao_e_divergencia():
    assert regras.pagamento_parcial(4000.0, 2490.0, 6490.0)


def test_parcial_precisa_que_a_soma_feche():
    """Não basta ter pagamento anterior: a conta tem de bater. Senão qualquer
    divergência viraria "parcial" e o alarme morria."""
    assert not regras.pagamento_parcial(4000.0, 2490.0, 9999.0)


def test_sem_pagamento_anterior_nao_ha_parcial():
    assert not regras.pagamento_parcial(4000.0, 0.0, 6490.0)


def test_ja_pago_de_titulo_quitado_e_zero():
    """Em título quitado o `valor_do_item` já devolve o total pago; somar de
    novo daria o dobro e inventaria uma parcial que não existe."""
    assert relatorio.ja_pago_do_item(
        {"remainingValue": 0, "sumOfPaidValues": 6490.0}) == 0.0
    assert relatorio.ja_pago_do_item(
        {"remainingValue": 4000.0, "sumOfPaidValues": 2490.0}) == 2490.0


def test_a_planilha_explica_a_parcial_em_vez_de_alarmar():
    item = lancamento(paidTo="Fornecedor", remainingValue=150.00,
                      sumOfPaidValues=1000.00, documentNumber="113")
    anexos = {"x1": [anexo("boleto", "Boleto", url="ub")]}
    res = relatorio.montar_registros([item], anexos, {}, {"ub": LINHA_BANCARIA})
    linha = linhas(res)[0]
    assert "diverge" not in linha["status"], linha["status"]
    assert "Pagamento parcial" in linha["obs"]
    assert "1.150,00" in linha["obs"]        # o boleto cheio
    assert "150,00" in linha["obs"]          # o que falta


def test_linha_digitavel_invalida_nao_vira_valor():
    """Número que não fecha o DV não tem opinião sobre valor nenhum."""
    assert ocr_boleto.valor_da_linha("12345") is None
    assert regras.motivo_omissao(1.00, "Fulano", "12345", True, {},
                                 valor_documento=None) == regras.MOTIVO_SIMBOLICO


# ==========================================================================
# 1b. Observação que redireciona o pagamento
# ==========================================================================
# Em 28/07/2026 um título tinha o FORNECEDOR como favorecido
# e a observação mandando pagar parte a uma pessoa física, com a chave dela.
# Enquanto quem paga é gente, alguém lê a coluna Obs. Numa remessa não há quem
# leia. Os textos abaixo são os reais, com nomes e chaves trocados.

@pytest.mark.parametrize("obs", [
    "PAGAR 8.000,00 PARA FULANO DE TAL – PIX 123.456.789-09",
    "PAGAR 8.000,00 PARA FULANO DE TAL\n\nAPENAS A DIFERENÇA AO BELTRANO",
    "transferir R$ 2.500,00 para o sócio",
    "chave pix do recebedor: fulano@exemplo.com",
])
def test_observacao_que_manda_pagar_outra_pessoa_e_pega(obs):
    assert regras.observacao_redireciona_pagamento(obs)


@pytest.mark.parametrize("obs", [
    # As cinco observações reais do arquivo de 08 a 10/08/2026 — 9% das linhas.
    "Pagamento deve ser efetuado, a nota será encaminhada após comprovação de pgto",
    "solicitada carta de correção - nota sem endereço",
    "SOLICITAR FATURA PARA FULANA",
    "Valor lançado para reembolso foi o valor do pedido",
    "Carta de correção solicitada - endereço errado",
    "",
])
def test_observacao_comum_nao_trava_nada(obs):
    """"SOLICITAR FATURA PARA FULANA" tem "PARA <nome>" e não é pagamento
    nenhum: é nota. Travar nela transformaria a regra em ruído diário."""
    assert not regras.observacao_redireciona_pagamento(obs)


def _cadastro(nome, **flags):
    """A chave do cadastro passa por `util.norm_espaco` no carregador — é ela
    que faz "Mármores Aurora" achar "MARMORES AURORA E GRANITOS LTDA", com o
    nome digitado de qualquer jeito no ERP. Montar o dicionário à mão sem
    normalizar testaria um caminho que não existe.

    O nome é INVENTADO, como todo dado de teste aqui: o repositório é público.
    O que ele precisa ter é a forma do problema — acento, caixa diferente e
    razão social mais longa que o apelido do cadastro."""
    return {util.norm_espaco(nome): flags}


def test_fornecedor_marcado_confirma_mesmo_sem_observacao():
    """O dia perigoso é aquele em que ninguém escreveu a observação."""
    forn = _cadastro("marmores aurora", confirmar_sempre=True)
    assert regras.precisa_de_olhar_humano("", "Mármores Aurora e Granitos", forn)
    assert not regras.precisa_de_olhar_humano("", "Outro Fornecedor", forn)


def test_o_motivo_diz_qual_das_duas_portas_pegou():
    forn = _cadastro("marmores aurora", confirmar_sempre=True)
    assert "observação" in regras.precisa_de_olhar_humano(
        "PAGAR 8.000,00 PARA FULANO", "Qualquer Um", {})
    assert "confirmar sempre" in regras.precisa_de_olhar_humano(
        "", "Mármores Aurora", forn)


# ==========================================================================
# 2. O tipo da chave Pix
# ==========================================================================
@pytest.mark.parametrize("texto, esperado", [
    # Como as pessoas escrevem de verdade, na frequência medida no período.
    ("PIX CNPJ: 11.222.333/0001-44", regras.CHAVE_CNPJ),
    ("CHAVE PIX CELULAR: 62 91234-5678", regras.CHAVE_TELEFONE),
    ("PIX CPF 123.456.789-09", regras.CHAVE_CPF),
    ("CHAVE PIX ALEATORIA", regras.CHAVE_ALEATORIA),
    ("PIX E-MAIL: fulano@exemplo.com.br", regras.CHAVE_EMAIL),
])
def test_o_tipo_declarado_no_texto_vence(texto, esperado):
    assert regras.tipo_de_chave_pix(texto) == esperado


@pytest.mark.parametrize("texto, esperado", [
    ("11.222.333/0001-44 - Chave pix", regras.CHAVE_CNPJ),   # pontuação de CNPJ
    ("PIX 123.456.789-09", regras.CHAVE_CPF),                # pontuação de CPF
    ("11222333000144", regras.CHAVE_CNPJ),                   # 14 dígitos crus
    ("anacnbento@exemplo.com", regras.CHAVE_EMAIL),
    ("PIX (62) 91234-5678", regras.CHAVE_TELEFONE),
    ("f47ac10b-58cc-4372-a567-0e02b2c3d479", regras.CHAVE_ALEATORIA),
])
def test_o_formato_inequivoco_resolve_quem_nao_declarou(texto, esperado):
    assert regras.tipo_de_chave_pix(texto) == esperado


@pytest.mark.parametrize("texto", [
    "CHAVE PIX: 62984863610",     # celular sem pontuação... ou CPF?
    "PIX 12345678909",            # CPF sem pontuação... ou celular?
    "PX 62984863610",
    "",
    "VER COMENTÁRIO DA SOLICITAÇÃO",
])
def test_onze_digitos_crus_nao_sao_chutados(texto):
    """CPF e celular têm os dois onze dígitos. Escolher entre eles é escolher
    para quem o dinheiro vai — e isso não é decisão de regex."""
    assert regras.tipo_de_chave_pix(texto) == ""


def test_chave_ambigua_so_alarma_quando_ha_chave():
    assert regras.chave_pix_ambigua("CHAVE PIX: 62984863610", "62984863610")
    assert not regras.chave_pix_ambigua("PIX CNPJ: 11.222.333/0001-44",
                                        "11.222.333/0001-44")
    # Sem chave nenhuma o problema é outro, e o recado também.
    assert not regras.chave_pix_ambigua("VER COMENTÁRIO DA SOLICITAÇÃO", "")


def test_a_planilha_pede_confirmacao_da_chave_sem_tipo():
    item = lancamento(tradePayablePaymentMethod="Pix", documentNumber="113",
                      paidToBankAccount="CHAVE PIX: 62984863610")
    res = relatorio.montar_registros([item], {}, {}, {})
    assert "sem tipo declarado" in linhas(res)[0]["obs"]


def test_chave_com_tipo_declarado_nao_vira_ruido():
    item = lancamento(tradePayablePaymentMethod="Pix", documentNumber="113",
                      paidToBankAccount="PIX CNPJ: 11.222.333/0001-44")
    res = relatorio.montar_registros([item], {}, {}, {})
    assert "sem tipo declarado" not in linhas(res)[0]["obs"]
