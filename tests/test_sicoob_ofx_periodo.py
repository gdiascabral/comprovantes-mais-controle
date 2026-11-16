# -*- coding: utf-8 -*-
"""OFX do Sicoob de um período (aba Conciliação). O cliente do Sicoob é
dublê: aqui se prova a fila (cada conta no seu arquivo, a que não está no
login diz por quê, sessão caída para tudo) e a conferência do período
marcado no calendário. Contas fictícias."""
import datetime as dt
from pathlib import Path

import pytest

from extratos_sicoob import ofx_periodo as m
from extratos_sicoob import saldo

INI, FIM = dt.date(2026, 10, 28), dt.date(2026, 10, 29)


class _Cli:
    def __init__(self):
        self.feitos = []

    def abrir_extrato(self):
        self.feitos.append("extrato")

    def definir_ordenacao(self):
        self.feitos.append("ordem")

    def exportar_ofx(self, destino):
        Path(destino).write_text("OFX", encoding="cp1252")
        self.feitos.append(("ofx", Path(destino).name))
        return destino


def _baixar(tmp_path, contas, *, entrar, definir=lambda cli, ini, fim: None,
            parar=lambda: False, ignorar=()):
    return m.baixar(_Cli(), contas, INI, FIM, tmp_path, lista={}, parar=parar,
                    log=lambda s: None, entrar=entrar, definir=definir, ignorar=ignorar)


def test_cada_conta_no_seu_arquivo(tmp_path):
    entradas = []
    r = _baixar(tmp_path, ["12.345-6", "23.456-7"],
                entrar=lambda cli, n, lista: entradas.append(n))
    assert r == {"123456": (tmp_path / "123456.ofx", ""),
                 "234567": (tmp_path / "234567.ofx", "")}
    assert entradas == ["12.345-6", "23.456-7"]


def test_conta_fora_deste_login_diz_por_que_e_segue(tmp_path):
    def entrar(cli, n, lista):
        if n == "12.345-6":
            raise saldo.ContaNaoEncontrada(saldo.FORA_DESTE_LOGIN)
    r = _baixar(tmp_path, ["12.345-6", "23.456-7"], entrar=entrar)
    assert r["123456"] == (None, saldo.FORA_DESTE_LOGIN)
    assert r["234567"] == (tmp_path / "234567.ofx", "")


def test_periodo_que_nao_marcou_nao_exporta(tmp_path):
    def definir(cli, ini, fim):
        raise m.PeriodoNaoMarcou("o período ficou '01/10/2026 - 29/10/2026'")
    r = _baixar(tmp_path, ["12.345-6"], entrar=lambda *a: None, definir=definir)
    assert r["123456"][0] is None and "01/10/2026" in r["123456"][1]
    assert not (tmp_path / "123456.ofx").exists()


def test_sessao_caida_para_a_fila(tmp_path):
    def entrar(cli, n, lista):
        raise saldo.SessaoPerdida(saldo.SESSAO_CAIU)
    r = _baixar(tmp_path, ["12.345-6", "23.456-7"], entrar=entrar)
    assert r == {"123456": (None, saldo.SESSAO_CAIU), "234567": (None, saldo.SESSAO_CAIU)}


def test_parar_deixa_as_que_faltam_paradas(tmp_path):
    vezes = []
    r = _baixar(tmp_path, ["12.345-6", "23.456-7"], entrar=lambda *a: vezes.append(1),
                parar=lambda: len(vezes) >= 1)
    assert r["123456"] == (tmp_path / "123456.ofx", "")
    assert r["234567"] == (None, m.PARADO)


def test_conta_ignorada_nunca_e_baixada(tmp_path):
    r = _baixar(tmp_path, ["99.990-0"], entrar=lambda *a: pytest.fail("entrou"),
                ignorar={"999900"})
    assert r == {}


def test_ignoradas_vem_do_cadastro_fora_do_repo(tmp_path):
    assert m.ignoradas(tmp_path) == frozenset()                 # sem arquivo: nenhuma
    (tmp_path / m.ARQUIVO_IGNORAR).write_text('{"ignorar": ["99.990-0", ""]}',
                                              encoding="utf-8")
    assert m.ignoradas(tmp_path) == frozenset({"999900"})
    (tmp_path / m.ARQUIVO_IGNORAR).write_text("torto", encoding="utf-8")
    assert m.ignoradas(tmp_path) == frozenset()


class _Calendario:
    """O p-calendar do Sicoob: marca o que o robô escolheu e mostra o texto."""

    def __init__(self, texto_final):
        self.escolhas, self.texto_final = [], texto_final
        self.first = self

    def click(self):
        pass

    def wait_for(self, state=None, timeout=None):
        pass

    def locator(self, sel):
        return _Select(self, sel)

    def get_by_text(self, texto, exact=False):
        return self


class _Select:
    def __init__(self, cal, sel):
        self.cal, self.sel = cal, sel

    def select_option(self, valor):
        self.cal.escolhas.append((self.sel, valor))


class _CliCal:
    def __init__(self, texto_final):
        self.cal = _Calendario(texto_final)
        self.dias = []
        self.page = self

    def locator(self, sel):
        return self.cal

    def wait_for_timeout(self, ms):
        pass

    def _clicar_dia(self, cal, dia):
        self.dias.append(dia)

    def texto_periodo(self):
        return self.cal.texto_final


def test_definir_intervalo_marca_os_dois_dias_e_confere_o_texto():
    cli = _CliCal("28/10/2026 - 29/10/2026")
    m.definir_intervalo(cli, INI, FIM)
    assert cli.dias == [28, 29]
    assert ("select.ui-datepicker-month", "9") in cli.cal.escolhas      # outubro = 9
    with pytest.raises(m.PeriodoNaoMarcou, match="01/10/2026"):
        m.definir_intervalo(_CliCal("01/10/2026 - 29/10/2026"), INI, FIM)
