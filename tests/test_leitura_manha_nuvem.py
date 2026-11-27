# -*- coding: utf-8 -*-
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from leitura_manha import leitura as lt
from leitura_manha import nuvem_leitura as nl

HORA = datetime(2026, 11, 27, 10, 30, tzinfo=timezone.utc)
ONTEM, HOJE = date(2026, 11, 26), date(2026, 11, 27)


class RestFalso:
    def __init__(self, faltar=None, linhas=()):
        self.gravado, self.lido, self.faltar, self.linhas = {}, [], faltar, list(linhas)

    def inserir(self, tabela, token, linhas, devolver=True):
        self.gravado[tabela] = linhas
        return linhas[:-1] if tabela == self.faltar else linhas

    def ler(self, tabela, token, colunas="*", filtro=""):
        self.lido.append((tabela, filtro))
        return self.linhas


@pytest.fixture
def rest(monkeypatch):
    falso = RestFalso()
    monkeypatch.setattr(nl.rest, "inserir", falso.inserir)
    monkeypatch.setattr(nl.rest, "ler", falso.ler)
    return falso


SALDOS = [lt.SaldoLido("A", "sicoob", "E", Decimal("10.5"), "", HORA),
          lt.SaldoLido("B", "erp", "", None, "ERP não lido: porteiro", HORA)]
EXTRATOS = [lt.ExtratoLido("A", "sicoob", "E", ONTEM, 1, 2, 0, 0, "")]
MARCAS = [lt.PreMarca(7, "A", "banco — x", "")]


def test_grava_as_quatro_tabelas_e_so_elas(rest):
    r = nl.gravar("TOK", "r-1", HOJE, ONTEM, SALDOS, EXTRATOS, MARCAS)
    assert r == {"saldo_lido": 2, "extrato_lido": 1, "pre_marca_banco": 1, "leitura_rodada": 1}
    assert list(rest.gravado) == ["saldo_lido", "extrato_lido", "pre_marca_banco", "leitura_rodada"]
    assert "agendado_resposta" not in rest.gravado


def test_nao_lido_vai_como_null_e_dinheiro_como_texto(rest):
    nl.gravar("TOK", "r-1", HOJE, ONTEM, SALDOS, [], [])
    a, b = rest.gravado["saldo_lido"]
    assert a["valor"] == "10.50" and a["motivo"] == "" and a["lido_em"] == "2026-11-27T10:30:00+00:00"
    assert b["valor"] is None and b["motivo"] == "ERP não lido: porteiro"
    assert "quem" not in a and "quando" not in a


def test_pre_marca_leva_o_dia_do_extrato(rest):
    nl.gravar("TOK", "r-1", HOJE, ONTEM, [], [], MARCAS)
    (m,) = rest.gravado["pre_marca_banco"]
    assert m == {"rodada": "r-1", "dia": "2026-11-27", "dia_extrato": "2026-11-26", "agendado_id": 7,
                 "conta": "A", "prova": "banco — x", "nota": ""}


def test_linha_a_menos_e_nao_gravou(rest):
    rest.faltar = "saldo_lido"
    with pytest.raises(nl.NaoGravou):
        nl.gravar("TOK", "r-1", HOJE, ONTEM, SALDOS, EXTRATOS, MARCAS)


def test_float_no_dinheiro_e_recusado():
    with pytest.raises(TypeError):
        nl._dinheiro(10.5)


def test_em_aberto_no_teto_falha_fechado(rest):
    rest.linhas = [{}] * nl.TETO_DE_LINHAS
    with pytest.raises(nl.LeituraCortada):
        nl.em_aberto("TOK")
    rest.linhas = [{"id": 1}]
    assert nl.em_aberto("TOK") == [{"id": 1}]
    assert rest.lido[-1] == ("agendado_em_aberto", "order=dia.asc,id.asc")


def test_extrato_nao_lido_vai_com_lido_falso_e_contagens_null(rest):
    nao = lt.ExtratoLido("A", "inter", "E", ONTEM, lido=False, motivo="Inter respondeu HTTP 500")
    nl.gravar("TOK", "r-1", HOJE, ONTEM, [], [nao] + EXTRATOS, [])
    a, b = rest.gravado["extrato_lido"]
    assert a["lido"] is False and a["motivo"] == "Inter respondeu HTTP 500"
    assert (a["saidas"], a["entradas"], a["ilegiveis"], a["fora_do_dia"]) == (None,) * 4
    assert b["lido"] is True and (b["saidas"], b["entradas"]) == (1, 2)


def test_extrato_nao_lido_sem_motivo_e_recusado():
    with pytest.raises(ValueError):
        lt.ExtratoLido("A", "inter", "E", ONTEM, lido=False)


def test_gravacao_parcial_diz_o_que_ja_entrou(rest):
    rest.faltar = "extrato_lido"
    with pytest.raises(nl.GravacaoParcial) as e:
        nl.gravar("TOK", "r-1", HOJE, ONTEM, SALDOS, EXTRATOS, MARCAS)
    msg = str(e.value)
    assert "gravou saldo_lido 2" in msg and "falhou extrato_lido" in msg and "NaoGravou" in msg
    assert "TOK" not in msg and e.value.gravado == {"saldo_lido": 2}
    assert isinstance(e.value, nl.rest.ErroDaNuvem)


def test_falha_na_primeira_tabela_nao_e_parcial(rest):
    rest.faltar = "saldo_lido"
    with pytest.raises(nl.NaoGravou):
        nl.gravar("TOK", "r-1", HOJE, ONTEM, SALDOS, EXTRATOS, MARCAS)


# --------------------------------- F6: marcador de rodada completa
def test_marcador_da_rodada_vai_por_ultimo_e_completo(rest):
    nl.gravar("TOK", "r-1", HOJE, ONTEM, SALDOS, EXTRATOS, [])
    assert list(rest.gravado)[-1] == "leitura_rodada"
    (r,) = rest.gravado["leitura_rodada"]
    assert r == {"rodada": "r-1", "dia": "2026-11-27", "dia_extrato": "2026-11-26", "completa": True,
                 "marcas_puladas": False, "contas": 1}


def test_marcador_diz_quando_as_pre_marcas_foram_puladas(rest):
    nl.gravar("TOK", "r-1", HOJE, ONTEM, SALDOS, EXTRATOS, [], marcas_puladas=True)
    (r,) = rest.gravado["leitura_rodada"]
    assert r["completa"] is True and r["marcas_puladas"] is True


def test_falha_antes_do_marcador_deixa_a_rodada_sem_marcador(rest):
    rest.faltar = "pre_marca_banco"
    with pytest.raises(nl.GravacaoParcial):
        nl.gravar("TOK", "r-1", HOJE, ONTEM, SALDOS, EXTRATOS, MARCAS)
    assert "leitura_rodada" not in rest.gravado


def test_falha_no_proprio_marcador_e_parcial(rest):
    rest.faltar = "leitura_rodada"
    with pytest.raises(nl.GravacaoParcial) as e:
        nl.gravar("TOK", "r-1", HOJE, ONTEM, SALDOS, EXTRATOS, MARCAS)
    assert "falhou leitura_rodada" in str(e.value)


# ------------------------------------------------------ F7: dia explícito
def test_toda_linha_leva_o_dia_de_hoje_de_sao_paulo(rest):
    nl.gravar("TOK", "r-1", HOJE, ONTEM, SALDOS, EXTRATOS, MARCAS)
    for tabela in ("saldo_lido", "extrato_lido", "pre_marca_banco", "leitura_rodada"):
        assert rest.gravado[tabela] and all(linha["dia"] == "2026-11-27" for linha in rest.gravado[tabela])
