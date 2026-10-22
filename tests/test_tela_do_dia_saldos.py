"""Saldos da tela do dia. Contas fictícias."""
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
