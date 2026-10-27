# -*- coding: utf-8 -*-
"""ERP na Prova de saldos: o saldo vem da API (como o Buscar) e o print da
linha da conta na grade #/accounts, numa aba do robô fechada no fim. Página
e Chrome são dublês; UUIDs e valores fictícios."""
import datetime as dt
import re
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("playwright")

from conciliacao.models import ErpAccount, ModelRow  # noqa: E402
from tela_do_dia import prova_erp as pe  # noqa: E402
from tela_do_dia import prova_saldos as ps  # noqa: E402

AGORA = dt.datetime(2026, 10, 27, 14, 5)
UA, UB, UC = "aaaaaaaa-0001", "bbbbbbbb-0002", "cccccccc-0003"


class _Loc:
    def __init__(self, pagina, sel):
        self.p, self.sel = pagina, sel

    @property
    def first(self):
        return self

    def count(self):
        return self.p.conta(self.sel)

    def click(self):
        self.p.cliques.append(self.sel)
        if self.sel == pe.SEL_PROXIMA_PAGINA:
            self.p.atual += 1

    def is_enabled(self):
        return self.p.atual + 1 < len(self.p.paginas)

    def scroll_into_view_if_needed(self):
        pass

    def bounding_box(self):
        if self.sel == pe.SEL_CABECALHO_GRADE:
            return self.p.caixa_cabecalho
        return self.p.caixa_linha if "data-id" in self.sel else None

    def screenshot(self, path):
        Path(path).write_bytes(b"png")
        self.p.fotos.append(self.sel)


class _Pagina:
    def __init__(self, paginas, quebra=None):
        self.paginas, self.atual, self.quebra = paginas, 0, quebra
        self.cliques, self.fotos, self.fechada, self.url = [], [], False, ""
        self.caixa_cabecalho = self.caixa_linha = None
        self.recortes, self.recorte_quebra = [], False

    def screenshot(self, path, clip=None):
        if self.recorte_quebra:
            raise RuntimeError("Clipped area is either empty or outside the resulting image")
        Path(path).write_bytes(b"png")
        self.recortes.append(clip)

    def goto(self, url, **k):
        if self.quebra:
            raise RuntimeError(self.quebra)
        self.url = url

    def wait_for_selector(self, sel, **k):
        pass

    def wait_for_timeout(self, ms):
        pass

    def locator(self, sel):
        return _Loc(self, sel)

    def conta(self, sel):
        if sel in (pe.SEL_CONTAS_OLHO, pe.SEL_PROXIMA_PAGINA):
            return 1
        achado = re.search(r'data-id="([^"]+)"', sel)
        return 1 if achado and achado.group(1) in self.paginas[self.atual] else 0

    def close(self):
        self.fechada = True


class _Mc:
    def __init__(self, pagina):
        self.pagina, self._minhas, self.abertas = pagina, set(), 0

    def _nova_aba_do_robo(self):
        self.abertas += 1
        self._minhas.add(self.pagina)
        return self.pagina


def test_fotografa_cada_conta_procurando_nas_paginas(tmp_path):
    pagina = _Pagina([[UA], [UB]])
    mc = _Mc(pagina)
    prints = pe.fotografar_contas(mc, [(8, UA), (9, UB)], tmp_path)
    assert prints == {8: (tmp_path / "08 erp.png", ""), 9: (tmp_path / "09 erp.png", "")}
    assert pagina.url == pe.URL_CONTAS
    assert pagina.cliques == [pe.SEL_CONTAS_OLHO, pe.SEL_PROXIMA_PAGINA]
    assert pagina.fechada and mc._minhas == set()


def test_avisa_assim_que_a_aba_do_robo_abre(tmp_path):
    """A aba nova vem para a frente: a prova só abre os bancos depois dela
    (revisão de 27/10, foco roubado no meio do login do Sicoob)."""
    pagina = _Pagina([[UA]])
    mc = _Mc(pagina)
    vistos = []
    pe.fotografar_contas(mc, [(8, UA)], tmp_path,
                         ao_abrir_aba=lambda: vistos.append((mc.abertas, pagina.url)))
    assert vistos == [(1, "")]


def test_conta_que_nao_aparece_diz_por_que(tmp_path):
    prints = pe.fotografar_contas(_Mc(_Pagina([[UA]])), [(8, UC)], tmp_path)
    assert prints == {8: (None, pe.NAO_ACHEI)}


def test_uuid_invalido_nem_abre_aba(tmp_path):
    mc = _Mc(_Pagina([[UA]]))
    prints = pe.fotografar_contas(mc, [(8, ""), (9, 'x"]; drop')], tmp_path)
    assert prints == {8: (None, pe.SEM_UUID), 9: (None, pe.SEM_UUID)}
    assert mc.abertas == 0


def test_aba_que_cai_vira_motivo_e_fecha(tmp_path):
    pagina = _Pagina([[UA]], quebra="net::ERR_ABORTED\ndetalhe")
    mc = _Mc(pagina)
    prints = pe.fotografar_contas(mc, [(8, UA)], tmp_path, log=lambda s: None)
    assert prints == {8: (None, "print do ERP falhou: net::ERR_ABORTED")}
    assert pagina.fechada and mc._minhas == set()


def test_parar_deixa_as_que_faltam_sem_print(tmp_path):
    prints = pe.fotografar_contas(_Mc(_Pagina([[UA, UB]])), [(8, UA)], tmp_path,
                                  parar=lambda: True)
    assert prints == {8: (None, ps.INTERROMPIDA)}


def test_print_do_erp_leva_o_cabecalho_da_grade_junto(tmp_path):
    """Revisão de 27/10: só a linha (sem o nome das colunas) não prova nada
    para quem lê no celular. O recorte junta o cabeçalho e a linha."""
    pagina = _Pagina([[UA]])
    pagina.caixa_cabecalho = {"x": 10, "y": 100, "width": 1200, "height": 40}
    pagina.caixa_linha = {"x": 10, "y": 300, "width": 1200, "height": 52}
    prints = pe.fotografar_contas(_Mc(pagina), [(8, UA)], tmp_path)
    assert prints == {8: (tmp_path / "08 erp.png", "")}
    assert pagina.recortes == [{"x": 10, "y": 100, "width": 1200, "height": 252}]
    assert pagina.fotos == []                     # não caiu na foto só da linha


def test_sem_cabecalho_ou_recorte_que_falha_fica_a_linha(tmp_path):
    pagina = _Pagina([[UA]])
    pagina.caixa_linha = {"x": 10, "y": 300, "width": 1200, "height": 52}
    pe.fotografar_contas(_Mc(pagina), [(8, UA)], tmp_path)
    assert pagina.recortes == [] and len(pagina.fotos) == 1
    pagina = _Pagina([[UA]])
    pagina.caixa_cabecalho = {"x": 10, "y": 100, "width": 1200, "height": 40}
    pagina.caixa_linha = {"x": 10, "y": 300, "width": 1200, "height": 52}
    pagina.recorte_quebra = True
    prints = pe.fotografar_contas(_Mc(pagina), [(8, UA)], tmp_path)
    assert prints == {8: (tmp_path / "08 erp.png", "")} and len(pagina.fotos) == 1


def test_recorte_une_as_duas_caixas():
    assert pe.recorte({"x": 0, "y": 50, "width": 800, "height": 40},
                      {"x": 5, "y": 120, "width": 900, "height": 50}) == {
        "x": 0, "y": 50, "width": 905, "height": 120}
    assert pe.recorte(None, {"x": 0, "y": 0, "width": 1, "height": 1}) is None
    # Cabeçalho fora da tela (rolado para cima): sem recorte, fica a linha.
    assert pe.recorte({"x": 0, "y": -30, "width": 800, "height": 40},
                      {"x": 0, "y": 200, "width": 800, "height": 50}) is None


class _Mapa:
    def __init__(self, rows):
        self.rows = rows

    @property
    def live_rows(self):
        return [r for r in self.rows if r.exists_in_erp]

    def is_ignored(self, nome):
        return False

    def resolve_account(self, conta):
        return next((r for r in self.rows if r.erp_name == conta.name), None)

    def by_row(self, n):
        return next((r for r in self.rows if r.row == n), None)


def _contas():
    return [ps.ContaDaProva(8, "ALFA", ps.SICOOB, numero="1"),
            ps.ContaDaProva(9, "BETA", ps.INTER, apelido="B")]


def test_ler_junta_o_saldo_da_api_e_o_print(tmp_path):
    mapa = _Mapa([ModelRow(8, "ALFA", erp_name="ALFA"), ModelRow(9, "BETA", erp_name="BETA")])
    contas_erp = [ErpAccount(UA, "ALFA", balance=D("10.00")), ErpAccount(UB, "BETA", balance=None)]
    anx = NS(mc=_Mc(_Pagina([[UA, UB]])), garantir_sessao=lambda log: "api")
    pedidos = []
    lidas = pe.ler(anx, "cfg", mapa, _contas(), tmp_path, log=lambda s: None,
                   agora=lambda: AGORA,
                   ler_saldos=lambda cfg, api, log: pedidos.append((cfg, api)) or contas_erp)
    assert pedidos == [("cfg", "api")]
    assert lidas[8] == ps.Leitura(D("10.00"), AGORA, "", tmp_path / "08 erp.png", "")
    assert lidas[9].saldo is None and lidas[9].motivo == pe.SEM_SALDO
    assert lidas[9].imagem == tmp_path / "09 erp.png"


def test_erp_que_falha_vira_motivo_em_todas_e_nao_abre_aba(tmp_path):
    mc = _Mc(_Pagina([[UA]]))
    anx = NS(mc=mc, garantir_sessao=lambda log: "api")

    def quebra(cfg, api, log):
        raise RuntimeError("o Mais Controle respondeu 500\nmais")
    lidas = pe.ler(anx, "cfg", _Mapa([]), _contas(), tmp_path, log=lambda s: None,
                   ler_saldos=quebra)
    assert {k: (v.saldo, v.motivo) for k, v in lidas.items()} == {
        8: (None, "o Mais Controle respondeu 500"), 9: (None, "o Mais Controle respondeu 500")}
    assert mc.abertas == 0


def test_sessao_do_erp_que_falha_vira_motivo_em_todas(tmp_path):
    def sem_sessao(log):
        raise RuntimeError("o Chrome do app não abriu")
    mc = _Mc(_Pagina([[UA]]))
    lidas = pe.ler(NS(mc=mc, garantir_sessao=sem_sessao), "cfg", _Mapa([]), _contas(),
                   tmp_path, log=lambda s: None, ler_saldos=lambda cfg, api, log: [])
    assert {k: (v.saldo, v.motivo) for k, v in lidas.items()} == {
        8: (None, "o Chrome do app não abriu"), 9: (None, "o Chrome do app não abriu")}
    assert mc.abertas == 0


def test_aba_do_robo_que_nao_abre_vira_motivo(tmp_path):
    class _McQuebrado:
        _minhas = set()

        def _nova_aba_do_robo(self):
            raise RuntimeError("Target closed")
    prints = pe.fotografar_contas(_McQuebrado(), [(8, UA)], tmp_path, log=lambda s: None)
    assert prints == {8: (None, "print do ERP falhou: Target closed")}
