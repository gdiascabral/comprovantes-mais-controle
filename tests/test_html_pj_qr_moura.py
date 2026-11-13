"""Pedidos do dono de 13/11/2026 para o HTML das PJ:

- contas MOURA DANTAS sempre por último (acesso separado no banco), mesmo
  quando aportam no dia;
- Pix ganha o QR montado pela chave, com a descrição de colar dentro, igual
  ao HTML das PF; boleto não ganha; chave incerta não ganha; o HTML não
  mostra o QR em linha bloqueada.
"""
import pytest

from pagamentos_dia import html_pagamentos as h
from pagamentos_dia import html_pf, modelos_html, qr_pix


def _conta(nome, n):
    return {"nome": nome, "entries": [{}] * n}


def test_moura_dantas_sempre_por_ultimo():
    contas = [_conta("MOURA DANTAS EMPREENDIMENTOS SICOOB - 16.335-0", 20),
              _conta("ALFA", 2), _conta("MOURA  dantas SICOOB 10774-3", 1), _conta("BETA", 5)]
    saida = h.ordenar_contas(contas, primeiras=["MOURA DANTAS EMPREENDIMENTOS SICOOB - 16.335-0", "ALFA"])
    assert [c["nome"] for c in saida] == [
        "ALFA", "BETA", "MOURA DANTAS EMPREENDIMENTOS SICOOB - 16.335-0", "MOURA  dantas SICOOB 10774-3"]


def _pix(dados, original=None, descricao="TB 21 QD 51 LT 28 C 240 M 14", valor=104000):
    return {"tipo": "Pix", "dados_limpo": dados, "dados_original": original or dados,
            "descricao": descricao, "centavos": valor, "favorecido": "Fulano de Tal"}


def test_pix_por_cnpj_ganha_qr_com_descricao_e_valor():
    r = h.qr_do_pix(_pix("39311700000132", "39.311.700/0001-32"))
    br = r["pix_montado"]
    assert qr_pix.valido(br)
    assert "0114" + "39311700000132" in br                 # a chave
    assert "TB 21 QD 51 LT 28 C 240 M 14" in br            # a descrição dentro
    assert "5407" + "1040.00" in br                        # o valor
    assert r["qr_svg"].startswith("<svg")


def test_copia_e_cola_pronto_vai_como_veio():
    pronto = html_pf.pix_estatico("39311700000132", 10.0, "X", "ABC")
    assert h.qr_do_pix(_pix(pronto))["pix_montado"] == pronto


def test_boleto_e_chave_incerta_nao_ganham_qr():
    assert h.qr_do_pix({"tipo": "Boleto", "dados_limpo": "1" * 47}) == {}
    assert h.qr_do_pix(_pix("12345678901")) == {}          # 11 dígitos sem DV/DDD: incerto
    assert h.qr_do_pix(_pix("")) == {}


def test_descricao_sem_acento_e_dentro_do_limite():
    chave = "fulano.de.tal.com.nome.comprido@empresa-grande.com.br"
    r = h.qr_do_pix(_pix(chave, descricao="Pós obra – ÁGUA/LUZ " + "X" * 80))
    br = r["pix_montado"]
    assert qr_pix.valido(br)
    desc_tlv = br.split(chave, 1)[1]
    assert desc_tlv.startswith("02")
    tam = int(desc_tlv[2:4])
    assert tam <= html_pf.limite_da_descricao(chave)
    assert desc_tlv[4:4 + tam].startswith("POS OBRA AGUALUZ")


def test_modelo_nao_mostra_codigo_em_linha_bloqueada():
    js = modelos_html.MODELO_GERAL
    assert "const pixQrCell = (pixCopia && !bloq)" in js
    assert "copyText(pixCopia, bPix)" in js


@pytest.mark.parametrize("tipo", ["Pix", "Pix (QR)"])
def test_tipos_de_pix(tipo):
    e = _pix("39311700000132", "39.311.700/0001-32")
    e["tipo"] = tipo
    assert h.qr_do_pix(e)
