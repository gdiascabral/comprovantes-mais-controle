"""Pedidos do dono de 13/11/2026 para o HTML das PJ:

- contas MOURA DANTAS sempre por último (acesso separado no banco), mesmo
  quando aportam no dia;
- Pix ganha o QR montado pela chave, com a descrição de colar dentro, igual
  ao HTML das PF (`html_pf.descricao_do_pix`: não corta NF/OC nem palavra, e
  "LT 10-11" vira "LT 10 E 11"); no reembolso, o nome é o da pessoa; boleto
  não ganha; chave incerta não ganha; o HTML não mostra o QR em linha
  bloqueada.
"""
import pytest

from pagamentos_dia import html_pagamentos as h
from pagamentos_dia import html_pf, modelos_html, qr_pix

CNPJ = "11222333000181"          # fictício, o mesmo dos outros testes
CNPJ_PONTUADO = "11.222.333/0001-81"


def _conta(nome, n):
    return {"nome": nome, "entries": [{}] * n}


def test_moura_dantas_sempre_por_ultimo():
    contas = [_conta("MOURA DANTAS EMPREENDIMENTOS SICOOB - 16.335-0", 20),
              _conta("ALFA", 2), _conta("MOURA  dantas SICOOB 10774-3", 1), _conta("BETA", 5)]
    saida = h.ordenar_contas(contas, primeiras=["MOURA DANTAS EMPREENDIMENTOS SICOOB - 16.335-0", "ALFA"])
    assert [c["nome"] for c in saida] == [
        "ALFA", "BETA", "MOURA DANTAS EMPREENDIMENTOS SICOOB - 16.335-0", "MOURA  dantas SICOOB 10774-3"]


def _par(dados=CNPJ, original=CNPJ_PONTUADO, valor=104000, **reg):
    """(entrada do HTML, registro do passo 2) mínimos."""
    e = {"tipo": "Pix", "dados_limpo": dados, "dados_original": original,
         "centavos": valor, "favorecido": "Fulano de Tal"}
    r = {"centro_custo": "RESIDENCIAL MODELO QD 12 LT 34", "favorecido": "Fulano de Tal",
         "descricao_lancamento": "C 240 M 14", **reg}
    return e, r


def test_pix_por_cnpj_ganha_qr_com_descricao_e_valor():
    out = h.qr_do_pix(*_par(oc_da_descricao="9218"))
    br = out["pix_montado"]
    assert qr_pix.valido(br)
    assert "0114" + CNPJ in br                             # a chave
    assert "RESIDENCIAL MODELO QD 12 LT 34 OC 9218" in br   # a descrição dentro
    assert "5407" + "1040.00" in br                        # o valor
    assert out["qr_svg"].startswith("<svg")


def test_copia_e_cola_pronto_vai_como_veio():
    pronto = html_pf.pix_estatico(CNPJ, 10.0, "X", "ABC")
    assert h.qr_do_pix(*_par(dados=pronto, original=pronto))["pix_montado"] == pronto


def test_boleto_e_chave_incerta_nao_ganham_qr():
    e, r = _par()
    e["tipo"] = "Boleto"
    assert h.qr_do_pix(e, r) == {}
    assert h.qr_do_pix(*_par(dados="12345678901", original="12345678901")) == {}  # incerto
    assert h.qr_do_pix(*_par(dados="", original="")) == {}


def test_descricao_longa_nao_perde_a_nf_nem_corta_palavra():
    e, r = _par(nf="123456", nf_anexada=True,
                descricao_lancamento="MATERIAL ELETRICO E HIDRAULICO PARA ACABAMENTO")
    br = h.qr_do_pix(e, r)["pix_montado"]
    assert qr_pix.valido(br)
    assert "NF 123456" in br
    assert "HIDRAULI5" not in br and "HIDRAULIC5" not in br     # palavra cortada antes do TLV 52


def test_lote_com_hifen_vira_e_dentro_do_qr():
    e, r = _par(centro_custo="RESIDENCIAL MODELO QD 12 LT 10-11", oc_da_descricao="77")
    br = h.qr_do_pix(e, r)["pix_montado"]
    assert "LT 10 E 11" in br and "1011" not in br


def test_reembolso_usa_o_nome_da_pessoa():
    e, r = _par(reembolso=True, reembolso_nome="Beltrano Silva")
    e["favorecido"] = "Beltrano Silva (reembolso de Loja)"
    br = h.qr_do_pix(e, r)["pix_montado"]
    assert "5914BELTRANO SILVA" in br and "REEMBOLSO" not in br


def test_modelo_nao_mostra_codigo_em_linha_bloqueada():
    js = modelos_html.MODELO_GERAL
    assert "const pixQrCell = (pixCopia && !bloq)" in js
    assert "copyText(pixCopia, bPix)" in js


@pytest.mark.parametrize("tipo", ["Pix", "Pix (QR)"])
def test_tipos_de_pix(tipo):
    e, r = _par()
    e["tipo"] = tipo
    assert h.qr_do_pix(e, r)
