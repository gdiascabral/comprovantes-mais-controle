# -*- coding: utf-8 -*-
"""ERP na Prova de saldos: o saldo vem da API (como o Buscar) e o print da
linha da conta na grade #/accounts, numa aba do robô fechada no fim. Página
e Chrome são dublês; UUIDs e valores fictícios."""
import datetime as dt
import io
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
        self.p.rolou = "linha"

    def bounding_box(self):
        if self.sel == pe.SEL_CABECALHO_GRADE:
            return self.p.caixa_cabecalho
        return self.p.caixa_linha if "data-id" in self.sel else None

    def screenshot(self, path):
        Path(path).write_bytes(b"png")
        self.p.fotos.append(self.sel)

    def evaluate(self, js):
        return self.p.colunas


class _Pagina:
    def __init__(self, paginas, quebra=None):
        self.paginas, self.atual, self.quebra = paginas, 0, quebra
        self.cliques, self.fotos, self.fechada, self.url = [], [], False, ""
        self.caixa_cabecalho = self.caixa_linha = None
        self.recortes, self.recorte_quebra, self.colunas = [], False, []
        self.rolou = ""

    def screenshot(self, path=None):
        """O print da ABA inteira (2000 x 1000), como bytes."""
        if self.recorte_quebra:
            raise RuntimeError("Target page, context or browser has been closed")
        self.recortes.append(self.rolou)
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (2000, 1000), "gray").save(buf, "PNG")
        return buf.getvalue()

    def evaluate(self, js):
        if "devicePixelRatio" in js:
            return 1
        if "scrollTo" in js:
            self.rolou = "topo"
        return None

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


def _colunas():
    # Banco (com texto), um vão vazio, o nome (com texto) e o saldo.
    return [
        {"campo": "banco", "texto": "Banco X", "celula": {"x": 10, "width": 300},
         "cabecalho": {"x": 10, "width": 300}},
        {"campo": "vazio", "texto": "", "celula": {"x": 310, "width": 900},
         "cabecalho": {"x": 310, "width": 900}},
        {"campo": "nome", "texto": "CONTA A", "celula": {"x": 1210, "width": 200},
         "cabecalho": {"x": 1200, "width": 260}},
        {"campo": "isFinancialBlock", "texto": "Bloquear", "celula": {"x": 1460, "width": 150},
         "cabecalho": None},
    ]


def test_ficha_do_erp_e_cabecalho_em_cima_da_linha_so_com_colunas_com_texto(tmp_path):
    """Revisão ao vivo de 27/10: o recorte que unia cabeçalho e linha pegava
    todas as linhas do meio, e a grade inteira ficava miúda no PDF."""
    from PIL import Image
    pagina = _Pagina([[UA]])
    pagina.caixa_cabecalho = {"x": 10, "y": 100, "width": 1600, "height": 40}
    pagina.caixa_linha = {"x": 10, "y": 300, "width": 1600, "height": 50}
    pagina.colunas = _colunas()
    prints = pe.fotografar_contas(_Mc(pagina), [(8, UA)], tmp_path)
    assert prints == {8: (tmp_path / "08 erp.png", "")}
    # Dois prints da aba: um com a grade no topo (cabeçalho), um com a linha.
    assert pagina.recortes == ["topo", "linha"]
    assert pagina.fotos == []
    ficha = Image.open(tmp_path / "08 erp.png")
    # Banco (300 + folga só à direita: a da esquerda cai fora da imagem) +
    # nome (o título, 260, com folga) + um vão; "Bloquear" e vazio fora.
    largura = (300 + pe.FOLGA) + (260 + 2 * pe.FOLGA) + pe.VAO_FICHA
    assert ficha.size == (2 * largura, 2 * (40 + 1 + 50))


def test_sem_cabecalho_sem_colunas_ou_recorte_que_falha_fica_a_linha(tmp_path):
    pagina = _Pagina([[UA]])
    pagina.caixa_linha = {"x": 10, "y": 300, "width": 1200, "height": 52}
    pagina.colunas = _colunas()
    pe.fotografar_contas(_Mc(pagina), [(8, UA)], tmp_path)
    assert len(pagina.fotos) == 1
    for colunas, quebra, y in ((_colunas(), True, 100), ([], False, 100),
                               (_colunas(), False, -30)):
        pagina = _Pagina([[UA]])
        pagina.caixa_cabecalho = {"x": 10, "y": y, "width": 1200, "height": 40}
        pagina.caixa_linha = {"x": 10, "y": 300, "width": 1200, "height": 52}
        pagina.colunas, pagina.recorte_quebra = colunas, quebra
        prints = pe.fotografar_contas(_Mc(pagina), [(8, UA)], tmp_path)
        assert prints == {8: (tmp_path / "08 erp.png", "")} and len(pagina.fotos) == 1


def test_faixas_da_ficha_juntam_celula_e_titulo_e_pulam_coluna_vazia():
    f = pe.FOLGA
    assert pe.faixas_da_ficha(_colunas()) == [(10 - f, 310 + f), (1200 - f, 1460 + f)]
    assert pe.faixas_da_ficha([]) == []


def test_ficha_respeita_a_escala_do_windows():
    """Com 125% no Windows o print tem 1,25 pixel por px de tela."""
    from PIL import Image
    cab, lin = Image.new("RGB", (1250, 50), "red"), Image.new("RGB", (1250, 60), "blue")
    ficha = pe.montar_ficha(cab, lin, [(50, 150)], largura_alvo=100, razao=1.25,
                            x_cabecalho=50, x_linha=50)
    assert ficha.size == (125, 111)
    assert ficha.getpixel((5, 5)) == (255, 0, 0) and ficha.getpixel((5, 100)) == (0, 0, 255)
    assert pe.montar_ficha(cab, lin, [], largura_alvo=100) is None


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
