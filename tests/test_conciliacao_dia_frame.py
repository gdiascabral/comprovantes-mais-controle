# -*- coding: utf-8 -*-
"""A aba Conciliação montada de verdade (fixture `raiz`: só com a tela livre).

O que se prova aqui é o desenho do spec de 29/10/2026: a lista nasce toda
desmarcada, o período nasce ontem/hoje, "Baixar e importar" só acende depois
da leitura do ERP e com uma conta marcada, e a Prova de saldos só liga depois
da leitura. Nenhum Chrome, nenhum ERP: o Anexar é um dublê."""
from __future__ import annotations

import datetime
from concurrent.futures import Future
from types import SimpleNamespace as NS

import pytest

from conciliacao_dia import frame as f
from conciliacao_dia import ofx_regras as r


class _Anx:
    def __init__(self):
        self.pedidos = []

    def avisar_se_ocupado(self, quem, aba=None):
        return False

    def submeter(self, nome, fn, *a, dona=None, **kw):
        self.pedidos.append((nome, dona))
        fut = Future()
        fut.set_result(None)
        return fut


def _conta(erp_id, banco=r.SICOOB, do_dia=False, motivo=""):
    return r.ContaOfx(erp_id=erp_id, nome=f"CONTA {erp_id}", banco=banco,
                      numero="12345-6", do_dia=do_dia, motivo=motivo)


@pytest.fixture
def aba(raiz):
    a = f.ConciliacaoDiaFrame(raiz, _Anx())
    a.pack(fill="both", expand=True)
    raiz.update_idletasks()
    yield a
    a.fechar()
    a.destroy()


def _lida(aba, contas):
    """O que o `_receber` deixa depois da leitura, sem o ERP."""
    aba.mapping = object()
    aba.contas_ofx = contas
    aba.marcadas = set()
    aba._desenhar_lista()
    aba._ligar(True)


def test_o_cartao_do_ofx_tem_altura_dentro_da_area_que_rola(aba, raiz):
    """A armadilha da v2.0.208: o cartão existia e ficava com altura zero."""
    raiz.update()
    assert aba.c1.winfo_height() > 0 and aba.c2.winfo_height() > 0


def test_periodo_nasce_ontem_a_hoje(aba):
    hoje = datetime.date.today()
    ini, fim = r.periodo_padrao(hoje)
    assert (aba.v_ini.get(), aba.v_fim.get()) == (f"{ini:%d/%m/%Y}", f"{fim:%d/%m/%Y}")


def test_antes_da_leitura_nada_acende_e_a_prova_fica_desligada(aba, monkeypatch):
    ligadas = []
    monkeypatch.setattr(aba.prova, "ligar", ligadas.append)
    aba._ligar(False)
    assert str(aba.b_baixar.cget("state")) == "disabled"
    assert str(aba.b_dia.cget("state")) == "disabled"
    assert ligadas == [False]


def test_lista_nasce_desmarcada_e_baixar_so_acende_com_uma_marcada(aba, monkeypatch):
    ligadas = []
    monkeypatch.setattr(aba.prova, "ligar", ligadas.append)
    _lida(aba, [_conta("a", do_dia=True), _conta("b", banco=r.INTER),
                _conta("c", motivo="sem número no cadastro")])
    assert aba.marcadas == set()
    assert all(f.MARCADA not in aba.t_lista.item(i, "text") for i in ("a", "b", "c"))
    assert str(aba.b_baixar.cget("state")) == "disabled" and ligadas[-1] is True
    aba._alternar("a")
    assert aba.marcadas == {"a"} and str(aba.b_baixar.cget("state")) == "normal"
    aba._alternar("c")                       # conta com motivo não marca
    assert aba.marcadas == {"a"}
    aba._alternar("a")
    assert str(aba.b_baixar.cget("state")) == "disabled"


def test_marcar_as_do_dia_e_desmarcar_todas(aba):
    _lida(aba, [_conta("a", do_dia=True), _conta("b", do_dia=True, motivo="x"),
                _conta("c")])
    aba._marcar_grupo(True)
    assert aba.marcadas == {"a"}
    aba._desmarcar()
    assert aba.marcadas == set() and f.DESMARCADA in aba.t_lista.item("a", "text")


def test_os_dois_grupos_aparecem_na_lista(aba):
    _lida(aba, [_conta("a", do_dia=True), _conta("c")])
    assert set(aba.t_lista.get_children()) == {f.GRUPO_DIA, f.GRUPO_OUTRAS}
    assert aba.t_lista.get_children(f.GRUPO_DIA) == ("a",)


def test_ocupado_so_com_a_thread_viva(aba):
    assert aba.ocupado() is None
    aba._thread = NS(is_alive=lambda: True)
    assert aba.ocupado() == f.OCUPADO
    aba._thread = None
