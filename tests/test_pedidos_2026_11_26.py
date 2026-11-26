# -*- coding: utf-8 -*-
"""Pedidos do dono de 26/11/2026 sobre o HTML dos pagamentos (dados fictícios).

1. Foto que não é aviso tem o texto lido por OCR e entra na conferência (o
   print do pedido no WhatsApp: centro de custo, fornecedor e valor).
2. Papel dividido: o total lido pela IA contra a SOMA dos lançamentos que
   usam o mesmo papel.
3. Observação que só repete a chave que a linha vai pagar não é "manda pagar
   outra pessoa".
"""
from pagamentos_dia import ia_do_dia, leitura_do_dia as ld
from pagamentos_dia import leitura_ia as li
from pagamentos_dia import nivel
from pagamentos_dia import regras_pagamento as regras


# --------------------------------------------------------------- 1. a foto
def test_foto_que_nao_e_aviso_tem_o_texto_lido_por_ocr():
    alvos = [("u-foto", False, False), ("u-pdf", True, True)]
    textos, ocr, _nl, _q = ld.baixar_textos(
        lambda u: b"x", alvos, ler_qr=lambda d, p: [],
        texto_pdf=lambda d: "texto do pdf", ocr_pdf=lambda d, log=print: "",
        ocr_imagem=lambda d: "SV 26 QD 40 LT 17 despachante fulana 1500,00")
    assert textos["u-foto"].startswith("SV 26") and "u-foto" in ocr
    assert textos["u-pdf"] == "texto do pdf" and "u-pdf" not in ocr


def test_foto_sem_texto_fica_fora_dos_textos_como_antes():
    textos, ocr, _nl, _q = ld.baixar_textos(
        lambda u: b"x", [("u-foto", False, False)], ler_qr=lambda d, p: [],
        texto_pdf=lambda d: "", ocr_pdf=lambda d, log=print: "", ocr_imagem=lambda d: "")
    assert textos == {} and not ocr


def test_a_ia_reaproveita_o_ocr_da_foto_que_a_leitura_ja_fez():
    item = {"id": "L1", "tradePayableId": "T1", "value": 1500.0, "remainingValue": 1500.0}
    foto = {"downloadUrl": "u-foto", "filename": "pedido.jpg", "extension": ".jpg", "tag": "Outros"}
    chamadas = []
    cand = ia_do_dia.selecionar([item], {"T1": [foto]}, {"u-foto": "pedido 1500,00"},
                                {"u-foto": (b"jpeg", False)},
                                ocr_imagem=lambda d: chamadas.append(d) or "")
    assert cand == {} and chamadas == []       # o valor já está no texto: nem vai à IA


# ------------------------------------------------------- 2. papel dividido
def _leitura(total="8973.55"):
    return {"legivel": True, "tipo_papel": "pedido", "total": total,
            "itens": [{"descricao": "piso", "valor": total}]}


def _entradas(ids_por_url, chave="papel-1"):
    return {url: {"ok": True, "leitura": _leitura(), "origem": "cache", "ids": set(ids),
                  "chave": chave} for url, ids in ids_por_url.items()}


def test_papel_de_dois_lancamentos_bate_pela_soma():
    a_pagar = [{"id": "A", "value": 6223.56, "remainingValue": 6223.56},
               {"id": "B", "value": 2749.99, "remainingValue": 2749.99}]
    leituras = _entradas({"u1": {"A"}, "u2": {"B"}})          # o mesmo papel em duas URLs
    ia_do_dia.anotar_papeis(leituras, a_pagar)
    for id_, url in (("A", "u1"), ("B", "u2")):
        r = ia_do_dia.leitura_do_item(a_pagar[0] if id_ == "A" else a_pagar[1],
                                      [{"downloadUrl": url}], leituras)
        assert r["estado"] != li.DIVERGE
        assert r["dividido"].startswith("papel dividido em 2 lançamentos")
        assert "8.973,55" in r["dividido"]


def test_papel_dividido_que_nao_fecha_continua_divergindo():
    a_pagar = [{"id": "A", "value": 6223.56, "remainingValue": 6223.56},
               {"id": "B", "value": 2000.00, "remainingValue": 2000.00}]
    leituras = _entradas({"u1": {"A", "B"}})
    ia_do_dia.anotar_papeis(leituras, a_pagar)
    r = ia_do_dia.leitura_do_item(a_pagar[0], [{"downloadUrl": "u1"}], leituras)
    assert r["estado"] == li.DIVERGE and r["dividido"] == ""


def test_irmao_fora_da_lista_a_pagar_desfaz_o_grupo():
    a_pagar = [{"id": "A", "value": 6223.56, "remainingValue": 6223.56}]
    leituras = _entradas({"u1": {"A", "B"}})                  # B não está a pagar
    ia_do_dia.anotar_papeis(leituras, a_pagar)
    assert "papel_ids" not in leituras["u1"]
    r = ia_do_dia.leitura_do_item(a_pagar[0], [{"downloadUrl": "u1"}], leituras)
    assert r["estado"] == li.DIVERGE


def test_papel_dividido_nunca_passa_de_olhe():
    a_pagar = [{"id": "A", "value": 6223.56, "remainingValue": 6223.56},
               {"id": "B", "value": 2749.99, "remainingValue": 2749.99}]
    leituras = _entradas({"u1": {"A", "B"}})
    ia_do_dia.anotar_papeis(leituras, a_pagar)
    ia = ia_do_dia.leitura_do_item(a_pagar[0], [{"downloadUrl": "u1"}], leituras)
    reg = {"status": "APTO", "valor": 6223.56, "conferencia": "fornecedor ✓",
           "fornecedor_no_anexo": True, "leitura_ia": ia}
    n = nivel.nivel_da_linha(reg)
    assert n.nome == nivel.OLHE
    assert any("papel dividido" in m for m in n.motivos)


# --------------------------------------------- 3. a chave da observação
OBS = "PIX CPF: 111.444.777-35. Corretor FULANA. Comissão total R$ 14.487,50 em 2 x R$ 7.243,75."


def test_chave_da_observacao_igual_a_paga_nao_e_outra_pessoa():
    assert regras.observacao_redireciona_pagamento(OBS)
    assert not regras.observacao_redireciona_pagamento(OBS, chave_e_a_paga=True)


def test_verbo_de_pagar_com_valor_vale_mesmo_com_a_chave_igual():
    obs = "PAGAR 8.000,00 PARA FULANO PIX CPF 111.444.777-35"
    assert regras.observacao_redireciona_pagamento(obs, chave_e_a_paga=True)


def _corretor(chave_cadastro):
    from pagamentos_dia import relatorio
    item = {"id": "L1", "tradePayableId": "T-L1", "paidTo": "Fulana Corretora",
            "remainingValue": 7243.75, "plannedDate": "2026-11-26",
            "tradePayableAccount": {"name": "CONTA EXEMPLO - SICOOB"},
            "tradePayablePaymentMethod": "Pix", "paidToBankAccount": chave_cadastro,
            "documentNumber": "", "costCentreDetails": [{"workName": "OBRA MODELO"}],
            "paid": False}
    anexos = {"T-L1": [{"filename": "recibo", "tagName": None, "extension": ".pdf",
                        "downloadUrl": "https://exemplo.invalid/recibo"}]}
    res = relatorio.montar_registros([item], anexos, {"L1": {"comment": OBS}},
                                     {"https://exemplo.invalid/recibo": "recibo fulana 7.243,75"})
    return [x for regs in res.contas.values() for x in regs]


def test_montar_registros_chave_da_observacao_igual_a_do_cadastro_nao_e_a_mao():
    linha, = _corretor("PIX CPF 111.444.777-35")
    assert "pagar à mão" not in linha["status"].lower()
    assert "manda pagar outra pessoa" not in (linha.get("obs") or "")


def test_montar_registros_chave_da_observacao_diferente_continua_a_mao():
    linha, = _corretor("PIX CPF 222.555.888-46")
    assert "manda pagar outra pessoa" in (linha.get("obs") or "")
