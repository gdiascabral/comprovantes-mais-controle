# -*- coding: utf-8 -*-
"""Pedidos do dono de 26/11/2026, segunda leva (dados fictícios).

1. Nota escrita à mão lida por OCR não diz "VALOR DIVERGE" pelo valor único:
   o OCR pega um pedaço (uma linha do meio, um rabisco) e o alarme era falso.
2. Papel dividido CONFIRMADO (soma fecha com segunda prova, OC do papel é a
   do lançamento, nenhum pago do período com a mesma OC) não segura a linha
   em "Olhe": "se bater, colocar como pode pagar".
"""
from pagamentos_dia import ia_do_dia, nivel, relatorio
from pagamentos_dia import leitura_ia as li


# ------------------------------------------------------- 1. nota à mão
def _nota(texto, urls_ocr):
    item = {"id": "L1", "tradePayableId": "T-L1", "paidTo": "Madeireira Modelo",
            "remainingValue": 2806.50, "plannedDate": "2026-11-26",
            "numberOfFinancingInstallments": 1,
            "tradePayableAccount": {"name": "CONTA EXEMPLO - SICOOB"},
            "tradePayablePaymentMethod": "Pix", "paidToBankAccount": "PIX EMAIL m@exemplo.com",
            "documentNumber": "", "costCentreDetails": [{"workName": "OBRA MODELO"}],
            "paid": False}
    pdf = {"filename": "9185", "tagName": None, "extension": ".pdf", "downloadUrl": "u-nota"}
    res = relatorio.montar_registros([item], {"T-L1": [pdf]}, {}, {"u-nota": texto},
                                     urls_ocr=urls_ocr)
    linha, = [x for regs in res.contas.values() for x in regs]
    return linha


def test_nota_a_mao_lida_por_ocr_nao_diverge_pelo_valor_unico():
    linha = _nota("MADEIREIRA MODELO caibrao 966,00", {"u-nota"})
    assert "VALOR DIVERGE" not in linha["conferencia"] and "valor ?" in linha["conferencia"]


def test_pdf_com_texto_continua_divergindo_pelo_valor_unico():
    linha = _nota("MADEIREIRA MODELO total 966,00", set())
    assert "VALOR DIVERGE" in linha["conferencia"]


# ------------------------------------------- 2. papel dividido confirmado
def _leitura(oc="9543"):
    return {"legivel": True, "tipo_papel": "pedido", "total": "8973.55",
            "ordem_de_compra": oc, "itens": [{"descricao": "piso", "total": "8973.55"}]}


A = {"id": "A", "value": 6223.56, "remainingValue": 6223.56}
B = {"id": "B", "value": 2749.99, "remainingValue": 2749.99}


def _ia(oc_do_papel="9543", ocs_pagas=(), oc_lanc="9543"):
    leituras = {"u1": {"ok": True, "leitura": _leitura(oc_do_papel), "origem": "cache",
                       "ids": {"A", "B"}, "chave": "u1", "papel": "p1"}}
    ia_do_dia.anotar_papeis(leituras, [A, B], ocs_pagas=ocs_pagas)
    return ia_do_dia.leitura_do_item(A, [{"downloadUrl": "u1"}], leituras, oc=oc_lanc)


def _reg(ia):
    return {"status": "APTO* (reembolso)", "valor": 6223.56, "conferencia": "valor ?",
            "reembolso_socio": True, "leitura_ia": ia}


def test_papel_dividido_confirmado_pode_pagar():
    ia = _ia()
    assert ia["estado"] == li.BATE and ia["dividido_confirmado"]
    assert "OC 9543 ✓" in ia["dividido"]
    n = nivel.nivel_da_linha(_reg(ia))
    assert n.nome == nivel.PODE_PAGAR, n.motivos


def test_oc_ja_paga_no_periodo_nao_confirma():
    ia = _ia(ocs_pagas={"9543"})
    assert not ia["dividido_confirmado"]
    assert nivel.nivel_da_linha(_reg(ia)).nome == nivel.OLHE


def test_oc_do_papel_diferente_do_lancamento_nao_confirma():
    ia = _ia(oc_lanc="1111")
    assert not ia["dividido_confirmado"]
    assert nivel.nivel_da_linha(_reg(ia)).nome != nivel.PODE_PAGAR


def test_papel_sem_oc_nao_confirma():
    ia = _ia(oc_do_papel="")
    assert not ia["dividido_confirmado"]
    assert nivel.nivel_da_linha(_reg(ia)).nome != nivel.PODE_PAGAR


def test_confirmado_nao_apaga_os_outros_motivos():
    reg = {**_reg(_ia()), "status": "ATENÇÃO — chave do reembolso divergente"}
    n = nivel.nivel_da_linha(reg)
    assert n.nome != nivel.PODE_PAGAR
