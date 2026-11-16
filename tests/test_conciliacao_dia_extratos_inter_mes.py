# -*- coding: utf-8 -*-
"""Extratos do Inter do mês (aba Acessórias): o mês inteiro é pedido, OFX de
outra conta não chega à pasta do mês, e QR da empresa errada vira linha com
o porquê. Dados fictícios; nenhum Chrome."""
from __future__ import annotations

import datetime as dt
from types import SimpleNamespace as NS

from baixar_comprovantes.contas_inter import ContaInter
from baixar_comprovantes.inter_ofx import OfxInter
from conciliacao_dia import extratos_inter_mes as m
from conciliacao_dia import ofx_regras as r


def _ofx(acct="123456789", ini="20260201", fim="20260228", n=2):
    trn = "<STMTTRN><TRNAMT>-1.00</STMTTRN>" * n
    return (f"OFXHEADER:100\n<ACCTID>{acct}\n<DTSTART>{ini}\n<DTEND>{fim}\n{trn}")


def _baixar(textos, pedidos):
    def baixar(apelido, numero, nomes, razoes, ini, fim, arquivo, **kw):
        pedidos.append((apelido, numero, nomes, razoes, ini, fim))
        texto = textos[apelido]
        if texto is None:
            return OfxInter(None, motivo="a tela do Inter está na conta 999 — outra conta aberta")
        arquivo.write_text(texto, encoding="cp1252")
        return OfxInter(arquivo, numero_na_tela="123456789")
    return baixar


LOGINS = [ContaInter("EMPRESA A", "EMPRESA A"), ContaInter("EMPRESA B", "EMPRESA B"),
          ContaInter("", "")]
EMPRESAS = [NS(nome="EMPRESA A", razao_social="EMPRESA A FICTICIA LTDA")]


def test_periodo_do_mes():
    assert r.periodo_do_mes(2026, 2) == (dt.date(2026, 2, 1), dt.date(2026, 2, 28))
    assert r.periodo_do_mes(2026, 12) == (dt.date(2026, 12, 1), dt.date(2026, 12, 31))


def test_pede_o_mes_inteiro_e_grava_so_o_que_confere(tmp_path):
    pedidos = []
    textos = {"EMPRESA A": _ofx(), "EMPRESA B": _ofx(acct="555")}
    res = m.baixar_mes(LOGINS, 2026, 2, tmp_path / "mes", tmp_path / "espera",
                       empresas=EMPRESAS, baixar=_baixar(textos, pedidos))
    assert [p[4:] for p in pedidos] == [(dt.date(2026, 2, 1), dt.date(2026, 2, 28))] * 2
    assert pedidos[0][2:4] == (("EMPRESA A", "EMPRESA A FICTICIA LTDA"),
                               ("EMPRESA A FICTICIA LTDA",))
    a, b = res
    assert a.arquivo == (tmp_path / "mes" / "FEVEREIRO 2026 - EMPRESA A" / "INTER"
                         / "123456789.ofx") and a.arquivo.exists() and a.lancamentos == 2
    assert b.arquivo is None and "não gravado" in b.motivo and "555" in b.motivo
    assert not (tmp_path / "mes" / "FEVEREIRO 2026 - EMPRESA B").exists()


def test_qr_da_empresa_errada_vira_linha_com_o_porque(tmp_path):
    res = m.baixar_mes(LOGINS[:1], 2026, 2, tmp_path / "mes", tmp_path / "espera",
                       baixar=_baixar({"EMPRESA A": None}, []))
    assert res[0].arquivo is None and "outra conta aberta" in res[0].motivo


def test_periodo_diferente_nao_grava(tmp_path):
    res = m.baixar_mes(LOGINS[:1], 2026, 2, tmp_path / "mes", tmp_path / "espera",
                       baixar=_baixar({"EMPRESA A": _ofx(fim="20260227")}, []))
    assert res[0].arquivo is None and "período" in res[0].motivo


def test_parar_nao_abre_as_seguintes(tmp_path):
    pedidos = []
    res = m.baixar_mes(LOGINS, 2026, 2, tmp_path / "mes", tmp_path / "espera",
                       baixar=_baixar({"EMPRESA A": _ofx(), "EMPRESA B": _ofx()}, pedidos),
                       parar=lambda: True)
    assert pedidos == [] and all("parado" in x.motivo for x in res)
