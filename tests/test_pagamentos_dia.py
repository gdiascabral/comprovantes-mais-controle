# -*- coding: utf-8 -*-
"""Regras do relatório de Pagamentos do Dia.

Nenhum dado real: os payloads abaixo têm a FORMA que a API do ERP devolve,
com nomes e números inventados. O repo é público.
"""
import datetime

import pytest

relatorio = pytest.importorskip("relatorio")


def anexo(nome, tag=None, ext=".pdf", url=None):
    return {"filename": nome, "tagName": tag, "extension": ext,
            "downloadUrl": url or f"https://exemplo.invalid/{nome}"}


# --------------------------------------------------------------- tipo de pgto
def test_boleto_ganha_de_pix_mesmo_com_o_erp_dizendo_pix():
    """O ERP marca 'Pix' porque o fornecedor tem chave no cadastro, mas o
    título veio com boleto anexado. Pagar por pix duplicaria o pagamento."""
    item = {"tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": "PIX CNPJ: 11.222.333/0001-44"}
    files = [anexo("boleto oc 1234", "Boleto"), anexo("oc 1234", "Recibo")]
    assert relatorio.tipo_de_pagamento(item, files) == "Boleto"


def test_sem_boleto_continua_pix():
    item = {"tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": "PIX CNPJ: 11.222.333/0001-44"}
    assert relatorio.tipo_de_pagamento(item, [anexo("oc 1234", "Recibo")]) == "Pix"


def test_nota_fiscal_nao_conta_como_boleto():
    item = {"tradePayablePaymentMethod": "Pix", "paidToBankAccount": "PIX CPF: 111.222.333-44"}
    assert relatorio.tipo_de_pagamento(item, [anexo("DANFE 999", "Nota Fiscal")]) == "Pix"


def test_extension_vem_com_ponto():
    assert relatorio.eh_pdf({"extension": ".pdf", "filename": "1234-PED-5678"})


def test_nao_chuta_a_nota_como_boleto():
    assert relatorio.escolher_pdf_do_boleto([anexo("DANFE 999", "Nota Fiscal")]) is None


def test_aceita_fatura_sem_a_palavra_boleto():
    """Fatura de concessionária vem com tagName nulo e nome só de número."""
    escolhido = relatorio.escolher_pdf_do_boleto([anexo("000449239501236")])
    assert escolhido and escolhido["filename"] == "000449239501236"


# ------------------------------------------------------------------ descrição
def test_descricao_usa_nf_e_oc():
    item = {"documentNumber": "5909",
            "costCentreDetails": [{"workName": "RPB 24 QD 26A LT 12"}]}
    overview = {"purchaseOrder": {"number": 6510}}
    assert relatorio.monta_descricao(item, [], "", overview) == \
        "RPB 24 QD 26A LT 12 NF 5909 OC 6510"


def test_oc_do_overview_vence_o_nome_do_anexo():
    item = {"documentNumber": "1", "costCentreDetails": [{"workName": "OBRA"}]}
    assert relatorio.achar_oc(item, [anexo("oc 999")], "", {"purchaseOrder": {"number": 6510}}) \
        == "6510"


def test_oc_por_extenso_no_comentario():
    item = {"costCentreDetails": [{"workName": "OBRA"}]}
    assert relatorio.achar_oc(item, [], "Ordem de Compra: 5413") == "5413"


def test_mao_de_obra_vira_contrato_e_medicao():
    item = {"costCentreDetails": [{"workName": "OBRA X"}],
            "description": "Serviço - 4412 - Medição: 7"}
    assert relatorio.monta_descricao(item, []) == "OBRA X C 4412 M 7"


def test_agua_e_luz_usam_a_descricao_e_nao_o_numero_da_fatura():
    item = {"paidTo": "Equatorial", "documentNumber": "2026068284705",
            "description": "UC 451784501210 REF JUL 2026 CASA 1",
            "costCentreDetails": [{"workName": "TB 17 QD 48 LT 38"}]}
    assert relatorio.monta_descricao(item, []) == \
        "TB 17 QD 48 LT 38 UC 451784501210 REF JUL 2026 CASA 1"


def test_descricao_longa_nao_corta_o_que_distingue_as_linhas():
    """Três lançamentos só diferem no 'CASA 1/2/3' lá no fim do texto."""
    item = {"costCentreDetails": [{"workName": "Pos obra"}],
            "description": "SUPRESSAO DE AGUA (casa entregue sem transferencia) - CASA 3"}
    assert "CASA 3" in relatorio.monta_descricao(item, [])


# ----------------------------------------------------------------- chave Pix
@pytest.mark.parametrize("bruto, esperado", [
    ("PIX CNPJ: 11.222.333/0001-44", "11.222.333/0001-44"),
    ("CHAVE PIX : 111.222.333-44", "111.222.333-44"),
    ("PIX CELULAR: (62) 99876-5432", "(62) 99876-5432"),
    ("CHAVE PIX: fulano@exemplo.invalid", "fulano@exemplo.invalid"),
])
def test_extrai_so_a_chave(bruto, esperado):
    assert relatorio.extrair_chave_pix(bruto) == esperado


def test_recado_no_lugar_da_chave_nao_e_chave():
    assert not relatorio.parece_chave_pix("VER COMENTARIO DA SOLICITACAO")
    assert relatorio.parece_chave_pix("111.222.333-44")


def test_copia_e_cola_vem_da_observacao():
    """Pedido de marketplace: o EMV inteiro estava no campo de observação."""
    coment = ("CODIGO PIX: 00020126540014br.gov.bcb.pix0132pix@exemplo.invalid"
              "52040000530398654061.005802BR5910EXEMPLO_06008Sao Paulo6304ABCD")
    achado = relatorio.chave_pix_do_comentario(coment)
    assert achado.startswith("000201") and achado.endswith("6304ABCD")


def test_observacao_sem_pix_nao_inventa_chave():
    assert relatorio.chave_pix_do_comentario("favor pagar até sexta") == ""


# --------------------------------------------------------------- cruzamento
CHAVE_NFE = "52260711222333000144550010000059090001234567"


def test_chave_de_acesso_entrega_numero_e_cnpj():
    d = relatorio.dados_da_chave_nfe(CHAVE_NFE)
    assert d["numero"] == "5909"
    assert d["cnpj"] == "11222333000144"
    assert d["modelo"] == "55"


def test_nf_do_anexo_diferente_do_lancamento_e_divergencia():
    item = {"documentNumber": "999999", "remainingValue": 10.0, "paidTo": "Fornecedor"}
    resumo, divergiu = relatorio.conferir_documento(item, [anexo(CHAVE_NFE)], ["x"])
    assert divergiu and "DIVERGE" in resumo


def test_cnpj_do_pix_diferente_do_emitente_e_divergencia():
    item = {"documentNumber": "5909", "remainingValue": 10.0, "paidTo": "Fornecedor",
            "paidToBankAccount": "PIX CNPJ: 99.888.777/0001-66"}
    resumo, divergiu = relatorio.conferir_documento(item, [anexo(CHAVE_NFE)], ["x"])
    assert divergiu and "CNPJ DIVERGE" in resumo


def test_tudo_batendo_nao_diverge():
    item = {"documentNumber": "5909", "remainingValue": 5020.28, "paidTo": "Tintas Exemplo",
            "paidToBankAccount": "PIX CNPJ: 11.222.333/0001-44"}
    resumo, divergiu = relatorio.conferir_documento(
        item, [anexo(CHAVE_NFE)], ["TINTAS EXEMPLO LTDA  TOTAL 5.020,28"])
    assert not divergiu
    assert "NF 5909 ✓" in resumo and "CNPJ ✓" in resumo
    assert "valor ✓" in resumo and "fornecedor ✓" in resumo


def test_nao_verifiquei_nao_pode_virar_alarme():
    item = {"documentNumber": "", "remainingValue": 77.0, "paidTo": "Fulano"}
    resumo, divergiu = relatorio.conferir_documento(item, [], [])
    assert not divergiu and "?" in resumo


def test_uc_confere_pelo_nome_do_anexo_sem_baixar_pdf():
    item = {"paidTo": "Equatorial", "description": "UC 451784501210 REF JUL 2026",
            "costCentreDetails": [{"workName": "TB 17 QD 48 LT 38"}]}
    resumo, divergiu = relatorio.conferir_documento(item, [anexo("000451784501210")], [])
    assert not divergiu and "UC 451784501210 ✓" in resumo


def test_uc_de_outra_unidade_e_divergencia():
    item = {"paidTo": "Equatorial", "description": "UC 451784501210 REF JUL 2026",
            "costCentreDetails": [{"workName": "TB 17"}]}
    _, divergiu = relatorio.conferir_documento(item, [anexo("000999999999999")], [])
    assert divergiu


def test_endereco_confere_pelo_nome_da_rua():
    """A concessionária escreve o logradouro; o ERP escreve QD/LT."""
    item = {"paidTo": "Equatorial", "description": "UC 449239501236 REF jul 2026",
            "costCentreDetails": [{"workName": "RUA CASSIMIRO MARQUES QD 18 LT 8"}]}
    resumo, _ = relatorio.conferir_documento(
        item, [anexo("000449239501236")], ["CASSIMIRO MARQUES, 100 - CENTRO"])
    assert "endereço ✓" in resumo


# ---------------------------------------------------------------- valor/contas
def test_titulo_quitado_tem_valor_em_sumOfPaidValues():
    assert relatorio.valor_do_item({"remainingValue": 0.0, "sumOfPaidValues": 5020.28}) == 5020.28


def test_titulo_aberto_usa_remainingValue():
    assert relatorio.valor_do_item({"remainingValue": 300.0, "sumOfPaidValues": 0.0}) == 300.0


def test_conta_de_ajuste_fica_de_fora():
    assert not relatorio.conta_entra("PESSOA FISICA - APENAS LANÇAMENTO")
    assert relatorio.conta_entra("TERRA BELA - SICOOB")


def test_excluir_vence_incluir_e_ignora_acento():
    assert not relatorio.conta_entra("JOÃO VITOR - CONTA PESSOAL",
                                     incluir=["joao"], excluir=["joao vitor"])


def test_abas_com_prefixo_igual_nao_colidem():
    """O Excel corta em 31 caracteres e recusa nome repetido."""
    nomes = relatorio.nomes_de_aba(["MORAIS EMPREENDIMENTOS BURITIS - INTER",
                                    "MORAIS EMPREENDIMENTOS BURITIS - SICOOB"])
    assert len(set(nomes.values())) == 2
    assert all(len(v) <= 31 for v in nomes.values())


def test_periodo_e_conferido_no_cliente():
    """Se a API ignorar o filtro, a linha de fora não pode entrar calada."""
    hoje = datetime.date(2026, 8, 7)
    itens = [{"plannedDate": "2026-08-07"}, {"plannedDate": "2026-08-07T00:00:00Z"},
             {"plannedDate": "2026-09-01"}]
    assert len(relatorio.filtrar_periodo(itens, hoje, hoje, log=lambda *_: None)) == 2


# ------------------------------------------------------------ linha completa
def test_linha_de_boleto_com_aviso_de_pix_no_cadastro():
    item = {"id": "i1", "tradePayableId": "t1", "paidTo": "Fornecedor Exemplo",
            "remainingValue": 1850.0, "tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": "PIX CNPJ: 11.222.333/0001-44",
            "documentNumber": "5909",
            "tradePayableAccount": {"name": "CONTA TESTE"},
            "costCentreDetails": [{"workName": "OBRA X"}]}
    anexos = {"t1": [anexo("boleto oc 6510", "Boleto", url="u1")]}
    overviews = {"i1": {"purchaseOrder": {"number": 6510}, "comment": ""}}
    textos = {"u1": "34191.57007 00024.434375 24177.010000 1 99990000185000"}

    reg = relatorio.montar_registros([item], anexos, overviews, textos)
    linha = reg["CONTA TESTE"][0]
    assert linha["tipo"] == "Boleto"
    assert linha["dados"].startswith("34191.57007")
    assert linha["descricao"] == "OBRA X NF 5909 OC 6510"
    assert "pagar o boleto" in linha["obs"]


def test_reembolso_sem_chave_cadastrada_vira_atencao():
    item = {"id": "i2", "tradePayableId": "t2", "paidTo": "Concessionaria",
            "remainingValue": 32.28, "documentNumber": "REEMBOLSO",
            "tradePayableAccount": {"name": "CONTA TESTE"},
            "costCentreDetails": [{"workName": "OBRA"}]}
    anexos = {"t2": [anexo("PAGAR PARA FULANO", ext=".pdf", url="u2")]}
    reg = relatorio.montar_registros([item], anexos, {}, {"u2": ""})
    linha = reg["CONTA TESTE"][0]
    assert linha["dados"] == ""
    assert linha["status"].startswith("ATEN")
    assert "fulano" in linha["obs"].lower()


def test_reembolso_com_chave_cadastrada():
    item = {"id": "i3", "tradePayableId": "t3", "paidTo": "Concessionaria",
            "remainingValue": 32.28, "documentNumber": "REEMBOLSO",
            "tradePayableAccount": {"name": "CONTA TESTE"},
            "costCentreDetails": [{"workName": "OBRA"}]}
    anexos = {"t3": [anexo("PAGAR PARA FULANO", url="u3")]}
    reg = relatorio.montar_registros([item], anexos, {}, {"u3": ""},
                                     pix_reembolso={"FULANO": "Fulano 111.222.333-44"})
    assert reg["CONTA TESTE"][0]["dados"] == "Fulano 111.222.333-44"


def test_excel_sai_com_as_colunas_na_ordem_pedida(tmp_path):
    from openpyxl import load_workbook
    item = {"id": "i4", "tradePayableId": "t4", "paidTo": "Fornecedor",
            "remainingValue": 100.0, "tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": "PIX CPF: 111.222.333-44",
            "tradePayableAccount": {"name": "CONTA TESTE"},
            "costCentreDetails": [{"workName": "OBRA"}]}
    reg = relatorio.montar_registros([item], {}, {}, {})
    destino = relatorio.gerar_excel(reg, tmp_path / "saida.xlsx")
    ws = load_workbook(destino).worksheets[0]
    assert [c.value for c in ws[3]][:5] == \
        ["Tipo de Pgto", "Dados do Pgto", "Valor", "Descrição", "Favorecido"]
    assert ws.cell(row=4, column=3).value == 100.0
