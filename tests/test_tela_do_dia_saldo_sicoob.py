# -*- coding: utf-8 -*-
"""O saldo do Sicoob na tela do dia, sem tela e sem navegador. Fictício."""
import datetime as dt
from decimal import Decimal as D
from types import SimpleNamespace as NS

import pytest

from conciliacao.mapping import AccountMapping
from conciliacao.models import ErpAccount
from tela_do_dia import saldo_sicoob as ss
from tela_do_dia import saldos as sd

HOJE = dt.date(2026, 10, 22)
MAPA = ("model_rows:\n"
        "- row: 8\n  label: Alfa - Sicoob\n  uuid: u-alfa\n  erp_name: ALFA LTDA - SICOOB\n"
        "- row: 9\n  label: Beta - Inter\n  uuid: u-beta\n  erp_name: BETA LTDA - INTER\n"
        "- row: 10\n  label: Gama - Sicoob\n  uuid: u-gama\n  erp_name: GAMA LTDA - SICOOB\n"
        "- row: 11\n  label: Delta - Sicoob\n  uuid: u-delta\n  erp_name: DELTA LTDA - SICOOB\n")
ERP = [ErpAccount("u-alfa", "ALFA LTDA - SICOOB", balance=D("100")),
       ErpAccount("u-beta", "BETA LTDA - INTER", balance=D("50")),
       ErpAccount("u-gama", "GAMA LTDA - SICOOB", balance=D("10"))]   # Delta sem saldo


def _destino(erp, empresa, banco):
    return NS(erp=erp, empresa=empresa, pasta=banco, banco=banco, sufixo="")


DESTINOS = [_destino("ALFA LTDA - SICOOB", "ALFA", "SICOOB"),
            _destino("BETA LTDA - INTER", "BETA", "INTER"),
            _destino("DELTA LTDA - SICOOB", "DELTA", "SICOOB")]          # Gama fora
MAPA_MC = NS(de=lambda nome: next((d for d in DESTINOS if d.erp == nome), None))
EMPRESAS = [NS(nome="ALFA", contas=[NS(numero="12.345-6", pasta="SICOOB", sufixo="")]),
            NS(nome="DELTA", contas=[NS(numero="23.456-7", pasta="SICOOB", sufixo="")])]


@pytest.fixture
def mapa(tmp_path):
    p = tmp_path / "mapping.yaml"
    p.write_text(MAPA, encoding="utf-8")
    return AccountMapping.load(p)


@pytest.fixture
def linhas(mapa):
    return sd.montar_saldos(ERP, mapa)


def test_cada_linha_sabe_se_e_do_sicoob_e_qual_conta(linhas, mapa):
    contas = {c.rotulo: c for c in ss.contas_do_painel(linhas, ERP, mapa, MAPA_MC, EMPRESAS)}
    assert contas["Alfa - Sicoob"].numero == "12.345-6"
    assert not contas["Beta - Inter"].do_sicoob                      # digitada
    assert contas["Gama - Sicoob"].motivo and not contas["Gama - Sicoob"].numero
    # Delta não veio do ERP: cai no erp_name da linha
    assert contas["Delta - Sicoob"].numero == "23.456-7"
    assert ss.numeros_a_ler(contas.values()) == ["12.345-6", "23.456-7"]


def test_duas_linhas_na_mesma_conta_nao_sao_preenchidas(linhas, mapa):
    empresas = [NS(nome="ALFA", contas=[NS(numero="12.345-6", pasta="SICOOB", sufixo="")]),
                NS(nome="DELTA", contas=[NS(numero="12.345-6", pasta="SICOOB", sufixo="")])]
    contas = {c.rotulo: c for c in ss.contas_do_painel(linhas, ERP, mapa, MAPA_MC, empresas)}
    assert "mesma conta do Sicoob" in contas["Alfa - Sicoob"].motivo
    assert "mesma conta do Sicoob" in contas["Delta - Sicoob"].motivo
    assert ss.numeros_a_ler(contas.values()) == []


def _leitura():
    return ss.LeituraSicoob.de_resultados(HOJE, [
        NS(numero="12.345-6", saldo=D("90.00"), lido_em=dt.datetime(2026, 10, 22, 8, 12), motivo=""),
        NS(numero="23.456-7", saldo=None, lido_em=None, motivo="esta conta não aparece neste login")])


def test_aplicar_preenche_o_banco_e_o_digitado_continua_valendo(linhas, mapa):
    contas = ss.contas_do_painel(linhas, ERP, mapa, MAPA_MC, EMPRESAS)
    com_lido = ss.aplicar(linhas, contas, _leitura())
    por = {ln.rotulo: ln for ln in com_lido}
    assert por["Alfa - Sicoob"].banco == D("90.00")
    assert por["Beta - Inter"].banco is None and por["Beta - Inter"].nota_banco == ""
    assert por["Delta - Sicoob"].nota_banco == "Sicoob não lido: esta conta não aparece neste login"
    assert por["Gama - Sicoob"].nota_banco.startswith("Sicoob não lido: ")
    digitado = sd.aplicar_ajustes(com_lido, {"Alfa - Sicoob": {
        sd.BANCO: sd.Ajuste(valor=D("95.00"), original=D("90.00"))}})
    alfa = next(ln for ln in digitado if ln.rotulo == "Alfa - Sicoob")
    assert alfa.saldo_do_dia == D("95.00") and alfa.banco == D("90.00")


def test_sem_leitura_nada_muda(linhas, mapa):
    contas = ss.contas_do_painel(linhas, ERP, mapa, MAPA_MC, EMPRESAS)
    assert ss.aplicar(linhas, contas, None) == linhas


def test_hora_no_alto(linhas, mapa):
    contas = ss.contas_do_painel(linhas, ERP, mapa, MAPA_MC, EMPRESAS)
    assert ss.texto_da_hora(None, contas) == "Sicoob ainda não lido hoje"
    assert ss.texto_da_hora(_leitura(), contas) == (
        "Sicoob lido às 08:12 · 1 de 2 contas (as outras: veja a situação)")
    assert ss.texto_da_hora(None, contas, lendo=(3, 20)) == "Lendo o Sicoob… 3 de 20 contas"
    assert "ainda não ligada" in ss.texto_da_hora(None, contas, ligado=False)


def test_hora_e_a_da_conta_lida_ha_mais_tempo():
    leitura = ss.LeituraSicoob.de_resultados(HOJE, [
        NS(numero="12.345-6", saldo=D("1"), lido_em=dt.datetime(2026, 10, 22, 8, 15), motivo=""),
        NS(numero="23.456-7", saldo=D("2"), lido_em=dt.datetime(2026, 10, 22, 8, 12), motivo="")])
    contas = [ss.ContaDoPainel("A", numero="12.345-6"), ss.ContaDoPainel("B", numero="23.456-7")]
    assert ss.texto_da_hora(leitura, contas) == "Sicoob lido às 08:12"


def test_recado_quando_o_perfil_esta_em_uso():
    erro = RuntimeError("Failed to create a ProcessSingleton for your profile directory")
    assert "já está aberto por outra aba" in ss.recado_da_falha(erro)
    assert ss.recado_da_falha(RuntimeError("linha 1\nlinha 2")) == "Sicoob: linha 1"


def test_gravar_e_ler_volta_igual_em_decimal(tmp_path):
    p = ss.caminho(tmp_path, HOJE)
    ss.gravar(_leitura(), p)
    lida, aviso = ss.ler(p, HOJE)
    assert aviso == "" and lida.contas["123456"].saldo == D("90.00")
    assert lida.contas["234567"].saldo is None and lida.contas["234567"].motivo
    assert p.name == "22 10 - saldos do sicoob.json"


def test_leitura_de_outro_dia_e_ignorada_e_estragada_nao_derruba(tmp_path):
    p = ss.caminho(tmp_path, HOJE)
    ss.gravar(_leitura(), p)
    assert ss.ler(p, HOJE + dt.timedelta(days=1)) == (None, "")
    p.write_text("{", encoding="utf-8")
    lida, aviso = ss.ler(p, HOJE)
    assert lida is None and "não consegui ler" in aviso
    assert ss.ler(tmp_path / "nao-existe.json", HOJE) == (None, "")


def test_arquivo_com_saldo_sem_hora_nao_derruba_a_frase():
    leitura = ss.de_dict({"data": HOJE.isoformat(), "contas": [
        {"numero": "12.345-6", "saldo": "1.00", "lido_em": None, "motivo": ""}]}, HOJE)
    contas = [ss.ContaDoPainel("A", numero="12.345-6")]
    assert ss.texto_da_hora(leitura, contas) == "Sicoob não lido — veja a situação de cada conta"


def test_conta_lida_sem_saldo_no_painel_nao_vira_zero(linhas, mapa):
    contas = ss.contas_do_painel(linhas, ERP, mapa, MAPA_MC, EMPRESAS)
    leitura = ss.LeituraSicoob.de_resultados(HOJE, [])           # leitura vazia
    por = {ln.rotulo: ln for ln in ss.aplicar(linhas, contas, leitura)}
    assert por["Alfa - Sicoob"].banco is None
    assert "não estava na leitura" in por["Alfa - Sicoob"].nota_banco
