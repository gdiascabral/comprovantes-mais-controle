"""O nível de cada linha do HTML (spec de 19/11/2026). Registros fictícios."""
from pagamentos_dia import nivel

# Linha digitável fictícia com DV fechando e R$ 1.150,00 embutido: a mesma
# que tests/test_html_pagamentos.py e tests/test_confirmacao.py já usam.
from pagamentos_dia import ocr_boleto

LINHA_VALIDA = "34191.57007 00024.924375 24177.010006 9 15340000115000"


def _r(**k):
    base = {"tipo": "Pix", "dados": "fulano@exemplo.com", "valor": 100.0,
            "status": "APTO", "conferencia": "valor ✓ · fornecedor ✓", "id": "1"}
    base.update(k)
    return base


def test_valor_e_quem_recebe_conferidos_pode_pagar():
    n = nivel.nivel_da_linha(_r())
    assert n.nome == nivel.PODE_PAGAR and n.motivos == []


def test_valor_nao_conferido_e_nao_li():
    n = nivel.nivel_da_linha(_r(conferencia="valor ? · fornecedor ✓"))
    assert n.nome == nivel.NAO_LI
    assert "valor não conferido em documento nenhum" in n.motivos


def test_anexo_sem_texto_e_nao_li():
    n = nivel.nivel_da_linha(_r(conferencia="valor/fornecedor ? (anexo sem texto)"))
    assert n.nome == nivel.NAO_LI


def test_conferencia_vazia_nunca_pode_pagar():
    for conf in ("", "(não cruzado)", None, []):
        assert nivel.nivel_da_linha(_r(conferencia=conf)).nome == nivel.NAO_LI


def test_situacao_que_ninguem_conhece_cai_em_olhe():
    n = nivel.nivel_da_linha(_r(status="ATENÇÃO — situação inventada amanhã"))
    assert n.nome == nivel.OLHE and "situação inventada amanhã" in n.motivos


def test_nao_li_ganha_de_olhe():
    n = nivel.nivel_da_linha(_r(status="ATENÇÃO — anexo não lido", conferencia="valor ?"))
    assert n.nome == nivel.NAO_LI


def test_status_que_e_nao_li():
    for st in ("ATENÇÃO — anexo não lido", "ATENÇÃO — sem dados de pgto",
               "ATENÇÃO — QR Code sem valor"):
        assert nivel.nivel_da_linha(_r(status=st)).nome == nivel.NAO_LI


def test_divergencia_e_olhe_e_diz_o_que_diverge():
    n = nivel.nivel_da_linha(_r(status="ATENÇÃO — boleto de outra empresa",
                                conferencia="valor ✓ · BENEFICIÁRIO DIVERGE: boleto x × cadastro y"))
    assert n.nome == nivel.OLHE and "quem recebe diverge" in n.motivos
    assert dict(n.conferido)["quem recebe"] == nivel.DIVERGE


def test_bloqueio_e_vencido_levam_a_olhe():
    assert nivel.nivel_da_linha(_r(), bloqueio="já pago — não pagar de novo").nome == nivel.OLHE
    assert nivel.nivel_da_linha(_r(), vencido=True).nome == nivel.OLHE


def test_ja_pago_liberado_e_a_mao_sao_olhe():
    for st in ("JÁ PAGO em 10/11/2026", "LIBERADO — sem anexo", "À MÃO — motivo"):
        assert nivel.nivel_da_linha(_r(status=st)).nome == nivel.OLHE


def test_reembolso_de_socio_pode_pagar_pela_decisao_1():
    n = nivel.nivel_da_linha(_r(status="APTO* (reembolso)", conferencia="valor ✓"))
    assert nivel.REEMBOLSO_DE_SOCIO_PODE_PAGAR is True
    assert n.nome == nivel.PODE_PAGAR


def test_boleto_prova_o_valor_pelo_codigo_de_barras():
    linha = LINHA_VALIDA
    assert ocr_boleto.codigo_de_barras(linha), "a linha fictícia tem de fechar o DV"
    valor = float(ocr_boleto.valor_embutido(linha))           # 1150.0
    n = nivel.nivel_da_linha(_r(tipo="Boleto", dados=linha, valor=valor,
                                conferencia="fornecedor ✓"))
    assert dict(n.conferido)["valor"] == nivel.BATE and n.nome == nivel.PODE_PAGAR


def test_boleto_de_outro_valor_nao_prova():
    n = nivel.nivel_da_linha(_r(tipo="Boleto", dados=LINHA_VALIDA, valor=1.0,
                                conferencia="fornecedor ✓"))
    assert dict(n.conferido)["valor"] == nivel.NAO_CONFERIDO


def test_qr_pix_com_valor_embutido_prova_o_valor():
    copia = "00020126330014br.gov.bcb.pix0111000000000005204000053039865406100.005802BR5913FULANO DE TAL6008GOIANIA62070503***6304ABCD"
    n = nivel.nivel_da_linha(_r(dados=copia, valor=100.0, conferencia="fornecedor ✓"))
    assert dict(n.conferido)["valor"] == nivel.BATE


def test_endereco_nota_e_oc_aparecem_mas_nao_derrubam():
    n = nivel.nivel_da_linha(_r(conferencia="OC 5678 ✓ · NF ? (sem chave no anexo) · valor ✓ · fornecedor ✓ · endereço ?"))
    c = dict(n.conferido)
    assert c["ordem de compra"] == nivel.BATE and c["nota"] == nivel.NAO_CONFERIDO
    assert c["endereço"] == nivel.NAO_CONFERIDO and n.nome == nivel.PODE_PAGAR


def test_lote_diferente_e_olhe():
    n = nivel.nivel_da_linha(_r(conferencia="valor ✓ · fornecedor ✓ · endereço ⚠ LOTE DIFERENTE (QD 1 LT 9)"))
    assert n.nome == nivel.OLHE and "endereço diverge" in n.motivos


def test_parcela_sem_numero_e_nao_li():
    n = nivel.nivel_da_linha(_r(parcela={"numero": None, "total": 10}))
    assert n.nome == nivel.NAO_LI
    assert "parcelado em 10 — número da parcela não lido" in n.motivos


def test_parcela_com_observacao_e_olhe_e_unica_nao():
    assert nivel.nivel_da_linha(_r(parcela={"numero": 3, "total": 10},
                                   obs_parcela="pagar depois da medição")).nome == nivel.OLHE
    assert nivel.nivel_da_linha(_r(obs_parcela="qualquer coisa")).nome == nivel.PODE_PAGAR


def test_para_o_html_e_rebaixar():
    r = _r(parcela={"numero": 3, "total": 10})
    e = nivel.para_o_html(nivel.nivel_da_linha(r), r)
    assert e["nivel"] == nivel.PODE_PAGAR and e["nivel_rotulo"] == "PODE PAGAR"
    assert e["parcela"] == "3 de 10" and ["valor", nivel.BATE] in e["conferido"]
    nivel.rebaixar_no_html(e, "mesma linha digitável em 2 lançamentos")
    assert e["nivel"] == nivel.OLHE and e["motivos"][-1].startswith("mesma linha")
    e2 = nivel.para_o_html(nivel.nivel_da_linha(_r(conferencia="valor ?")), _r())
    nivel.rebaixar_no_html(e2, "x")
    assert e2["nivel"] == nivel.NAO_LI          # rebaixar nunca sobe "Não li"
