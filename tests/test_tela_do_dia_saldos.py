"""Saldos da tela do dia. Contas fictícias."""
from dataclasses import replace
from decimal import Decimal as D

import pytest

from conciliacao.mapping import AccountMapping
from conciliacao.models import ErpAccount
from tela_do_dia import saldos as sd

MAPA = ("model_rows:\n"
        "- row: 8\n  label: Conta Alfa - Banco\n  uuid: uuid-alfa\n  erp_name: ALFA LTDA - BANCO\n"
        "- row: 9\n  label: Conta Beta - Banco\n  uuid: uuid-beta\n  erp_name: BETA LTDA - BANCO\n"
        "- row: 10\n  label: Conta Gama - Banco\n  uuid: uuid-gama\n  erp_name: GAMA LTDA - BANCO\n"
        "- row: 11\n  label: Conta Morta - Banco\n  exists_in_erp: false\n")
CONTAS = [ErpAccount("uuid-alfa", "ALFA LTDA - BANCO", balance=D("100.00")),
          ErpAccount("uuid-beta", "BETA LTDA - BANCO", balance=D("50.00"))]


@pytest.fixture
def mapa(tmp_path):
    caminho = tmp_path / "mapping.yaml"
    caminho.write_text(MAPA, encoding="utf-8")
    return AccountMapping.load(caminho)


def test_uma_linha_por_conta_viva_e_saldo_nao_lido_e_none(mapa):
    linhas = sd.montar_saldos(CONTAS, mapa)
    assert [(ln.linha, ln.sistema) for ln in linhas] == [(8, D("100.00")), (9, D("50.00")), (10, None)]


def test_situacao_sem_banco_bate_e_nao_bate(mapa):
    alfa = sd.montar_saldos(CONTAS, mapa)[0]
    assert alfa.situacao()[0] == "info"
    ok = sd.aplicar_ajustes([alfa], {"Conta Alfa - Banco": {sd.BANCO: sd.novo_ajuste(alfa, sd.BANCO, D("100.00"))}})[0]
    assert ok.situacao() == ("ok", "bate")
    ruim = sd.aplicar_ajustes([alfa], {"Conta Alfa - Banco": {sd.BANCO: sd.novo_ajuste(alfa, sd.BANCO, D("90.00"))}})[0]
    tag, frase = ruim.situacao()
    assert tag == "erro" and "R$ 10,00" in frase and ruim.diferenca == D("-10.00")


def test_ajuste_no_sistema_guarda_o_original_e_o_motivo(mapa):
    alfa = sd.montar_saldos(CONTAS, mapa)[0]
    aj = sd.novo_ajuste(alfa, sd.SISTEMA, D("-5.00"), "  simulação  ", quando="2026-10-21T09:00")
    nova = sd.aplicar_ajustes([alfa], {"Conta Alfa - Banco": {sd.SISTEMA: aj}})[0]
    assert (nova.sistema, nova.sistema_usado, nova.ajuste_sistema.original) == (D("100.00"), D("-5.00"), D("100.00"))
    assert nova.ajuste_sistema.motivo == "simulação"
    assert nova.saldo_do_dia == D("-5.00")


def test_o_banco_manda_no_saldo_do_dia_quando_existe(mapa):
    alfa = sd.montar_saldos(CONTAS, mapa)[0]
    com_banco = sd.aplicar_ajustes([alfa], {"Conta Alfa - Banco": {sd.BANCO: sd.novo_ajuste(alfa, sd.BANCO, D("80.00"))}})[0]
    assert com_banco.saldo_do_dia == D("80.00")


def test_sistema_que_mudou_depois_do_ajuste_e_avisado(mapa):
    alfa = sd.montar_saldos(CONTAS, mapa)[0]
    aj = sd.Ajuste(valor=D("70.00"), original=D("60.00"))
    tag, frase = sd.aplicar_ajustes([alfa], {"Conta Alfa - Banco": {sd.SISTEMA: aj}})[0].situacao()
    assert tag == "atencao" and "era R$ 60,00" in frase and "R$ 100,00" in frase


def test_ordem_poe_o_que_nao_bate_em_cima(mapa):
    linhas = sd.montar_saldos(CONTAS, mapa)
    beta = linhas[1]
    linhas = sd.aplicar_ajustes(linhas, {"Conta Beta - Banco": {sd.BANCO: sd.novo_ajuste(beta, sd.BANCO, D("1.00"))}})
    assert [ln.linha for ln in sd.ordenar(linhas)] == [9, 10, 8]


# ------------------------------------- entrega 4: o banco lido do Sicoob

def test_lido_do_banco_vira_saldo_do_dia(mapa):
    alfa = replace(sd.montar_saldos(CONTAS, mapa)[0], banco=D("100.00"))
    assert alfa.saldo_do_dia == D("100.00") and alfa.situacao() == ("ok", "bate")


def test_digitado_vale_sobre_o_lido_e_avisa_quando_o_lido_mudou(mapa):
    alfa = sd.montar_saldos(CONTAS, mapa)[0]                       # banco None
    digitado = sd.aplicar_ajustes([alfa], {alfa.rotulo: {
        sd.BANCO: sd.novo_ajuste(alfa, sd.BANCO, D("100.00"))}})[0]
    lido_depois = replace(digitado, banco=D("80.00"))              # Sicoob leu depois
    assert lido_depois.saldo_do_dia == D("100.00")                 # vale o digitado
    assert lido_depois.banco_mudou
    tag, frase = lido_depois.situacao()
    assert tag == "atencao" and "o banco leu R$ 80,00 depois do seu ajuste" in frase


def test_ajuste_feito_sobre_o_lido_nao_avisa(mapa):
    lida = replace(sd.montar_saldos(CONTAS, mapa)[0], banco=D("80.00"))
    simulada = sd.aplicar_ajustes([lida], {lida.rotulo: {
        sd.BANCO: sd.novo_ajuste(lida, sd.BANCO, D("100.00"), "simulação")}})[0]
    assert not simulada.banco_mudou and simulada.situacao()[0] == "ok"


def test_digitado_igual_ao_lido_nao_avisa(mapa):
    alfa = sd.montar_saldos(CONTAS, mapa)[0]
    d = sd.aplicar_ajustes([alfa], {alfa.rotulo: {sd.BANCO: sd.novo_ajuste(alfa, sd.BANCO, D("100.00"))}})[0]
    assert not replace(d, banco=D("100.00")).banco_mudou


def test_diferenca_continua_erro_e_leva_o_aviso(mapa):
    alfa = sd.montar_saldos(CONTAS, mapa)[0]
    d = sd.aplicar_ajustes([alfa], {alfa.rotulo: {sd.BANCO: sd.novo_ajuste(alfa, sd.BANCO, D("90.00"))}})[0]
    tag, frase = replace(d, banco=D("70.00")).situacao()
    assert tag == "erro" and "R$ 10,00" in frase and "o banco leu R$ 70,00" in frase


def test_nota_do_banco_sobe_como_atencao(mapa):
    alfa = replace(sd.montar_saldos(CONTAS, mapa)[0], nota_banco="Sicoob não lido: x")
    assert alfa.situacao() == ("atencao", "Sicoob não lido: x")
    assert sd.ordenar([sd.montar_saldos(CONTAS, mapa)[1], alfa])[0] is alfa


def test_nota_do_banco_some_quando_ha_digitado(mapa):
    alfa = replace(sd.montar_saldos(CONTAS, mapa)[0], nota_banco="Sicoob não lido: x")
    d = sd.aplicar_ajustes([alfa], {alfa.rotulo: {sd.BANCO: sd.novo_ajuste(alfa, sd.BANCO, D("100.00"))}})[0]
    assert d.situacao() == ("ok", "bate") and d.nota_banco == "Sicoob não lido: x"


def test_campo_novo_por_ultimo_nao_quebra_quem_constroi_por_posicao():
    ln = sd.LinhaSaldo(8, "x", D("1"), D("1"), None, None)
    assert ln.nota_banco == "" and ln.situacao() == ("ok", "bate")
