# -*- coding: utf-8 -*-
"""Aba "Anexar (novo)": a Anexar de sempre + somas, sem um segundo navegador.

Testes puros: sem janela Tk. O `__init__` roda com ttk/StringVar trocados por
dublês, como `tests/test_abas_em_paralelo.py` faz com `__new__`."""
import copy
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.fixture
def modulo():
    pytest.importorskip("playwright")
    from anexar import anexar_comprovantes as modulo
    return modulo


class _Var:
    def __init__(self, master=None, value=None, **_k):
        self._v = value

    def get(self):
        return self._v

    def set(self, v):
        self._v = v


def _sem_tk(*_a, **_k):
    raise RuntimeError("sem Tk no teste")


def _construir(modulo, monkeypatch, classe, *args):
    import tkinter as tk
    from tkinter import ttk
    ch = {"executor": 0, "after": []}

    def executor(*_a, **_k):
        ch["executor"] += 1
        return object()

    monkeypatch.setattr(ttk.Frame, "__init__", lambda self, *a, **k: None)
    monkeypatch.setattr(tk, "StringVar", _Var)
    monkeypatch.setattr(tk, "BooleanVar", _Var)
    monkeypatch.setattr(ttk, "Style", _sem_tk)
    monkeypatch.setattr(modulo.AnexarFrame, "_build", lambda self: None)
    monkeypatch.setattr(modulo.AnexarFrame, "after",
                        lambda self, ms, fn=None, *a: ch["after"].append(fn.__name__))
    monkeypatch.setattr(modulo, "ThreadPoolExecutor", executor)
    return classe(None, *args), ch


def test_a_anexar_de_sempre_continua_dona_do_navegador(modulo, monkeypatch):
    assert modulo.AnexarFrame.DONO_DO_NAVEGADOR is True
    assert modulo.AnexarFrame.TITULO == "Anexar Comprovantes"
    assert modulo.AnexarFrame.TRILHA == "Comprovantes  ›  Anexar"
    f, ch = _construir(modulo, monkeypatch, modulo.AnexarFrame)
    assert ch["executor"] == 1 and f.exec is not None
    assert ch["after"] == ["_drain", "_pulsar_navegador"]


def test_o_cabecalho_le_titulo_e_trilha_da_classe(modulo, monkeypatch):
    """O `_build` de sempre passa os atributos ao `Cabecalho` — com os
    padrões, os mesmos textos de antes."""
    vistos = {}

    class _Parou(Exception):
        pass

    def cabecalho(pai, titulo, sub, trilha=None, **_k):
        vistos.update(titulo=titulo, trilha=trilha)
        raise _Parou

    monkeypatch.setattr(modulo.widgets, "Cabecalho", cabecalho)
    f = modulo.AnexarFrame.__new__(modulo.AnexarFrame)
    with pytest.raises(_Parou):
        f._build()
    assert vistos == {"titulo": "Anexar Comprovantes",
                      "trilha": "Comprovantes  ›  Anexar"}


# ------------------------------------------------- tarefa 8: a aba cópia
@pytest.fixture
def novo(modulo):
    from anexar import anexar_novo
    return anexar_novo


class _Dono:
    def __init__(self):
        self.chamadas, self.mc, self.api = [], "mc-do-dono", "api-do-dono"

    def submeter(self, rotulo, fn, *a, dona=None, **k):
        self.chamadas.append(("submeter", rotulo, dona))
        return "fut"

    def avisar_se_ocupado(self, texto, *, aba=None):
        self.chamadas.append(("avisar", aba))
        return False

    def ocupado(self, aba=None):
        self.chamadas.append(("ocupado", aba))

    def dona_ocupada(self, aba=None):
        self.chamadas.append(("dona_ocupada", aba))

    def garantir_sessao(self, log=None):
        self.chamadas.append(("sessao", log))
        return self.api

    def abrir_minha_aba(self):
        self.chamadas.append(("minha aba",))

    def fechar(self):
        self.chamadas.append(("fechar",))


def _nova(novo, dono):
    f = novo.AnexarNovoFrame.__new__(novo.AnexarNovoFrame)
    f.anx, f.q, f.pagos = dono, novo._FilaComDesvio(), []
    f._parar, f._pausa, f._esperas = threading.Event(), threading.Event(), set()
    f._encerrando = False
    f.winfo_children = lambda: []
    return f


def test_a_copia_nao_cria_executor_nem_pulso(modulo, novo, monkeypatch):
    dono = _Dono()
    f, ch = _construir(modulo, monkeypatch, novo.AnexarNovoFrame, dono)
    assert novo.AnexarNovoFrame.DONO_DO_NAVEGADOR is False
    assert novo.AnexarNovoFrame.TITULO == "Anexar (novo)"
    assert novo.AnexarNovoFrame.TRILHA == "Comprovantes  ›  Anexar (novo)"
    assert ch["executor"] == 0 and f.exec is None
    assert ch["after"] == ["_drain"]
    assert f.anx is dono and isinstance(f.q, novo._FilaComDesvio)
    assert f.pagos == []


def test_todo_trabalho_vai_para_o_dono_com_a_copia_como_dona(novo):
    dono = _Dono()
    f = _nova(novo, dono)
    assert f.submeter("Anexar — casar", print) == "fut"
    assert f.submeter("Anexar — casar", print, dona="outra") == "fut"
    f.avisar_se_ocupado("o Anexar (novo)")
    f.ocupado()
    f.dona_ocupada()
    f.abrir_minha_aba()
    assert dono.chamadas.count(("submeter", "Anexar — casar", f)) == 2
    assert ("avisar", f) in dono.chamadas and ("ocupado", f) in dono.chamadas
    assert ("dona_ocupada", f) in dono.chamadas and ("minha aba",) in dono.chamadas
    assert f.mc == "mc-do-dono" and f.api == "api-do-dono"
    f.mc = "outro"
    f.api = "outra"
    assert dono.mc == "outro" and dono.api == "outra"
    assert f.garantir_sessao() == dono.api
    assert ("sessao", f._log) in dono.chamadas          # o registro é o da cópia


def test_fechar_da_copia_solta_quem_espera_e_nao_fecha_o_chrome(novo):
    dono = _Dono()
    f = _nova(novo, dono)
    ev = threading.Event()
    f._esperas.add(ev)
    f._pausa.set()
    f.fechar()
    assert ev.is_set() and f._parar.is_set() and not f._pausa.is_set()
    assert f._encerrando and ("fechar",) not in dono.chamadas


def test_o_pulso_da_copia_nao_faz_nada(novo):
    f = _nova(novo, _Dono())
    f.after = lambda *a, **k: pytest.fail("a cópia não pulsa nem reagenda")
    assert f._pulsar_navegador() is None


def test_a_fila_segura_o_fim_so_enquanto_desvia(novo):
    q = novo._FilaComDesvio()
    q.desviar = True
    q.put(("log", "a"))
    q.put(("fim", (1, 1, 0, 0, "")))
    q.desviar = False
    q.put(("fim", (2, 2, 0, 0, "")))
    assert [q.get_nowait() for _ in range(2)] == [("log", "a"), ("fim", (2, 2, 0, 0, ""))]
    assert q.fim_desviado == (1, 1, 0, 0, "")


def _itens(q):
    saida = []
    while not q.empty():
        saida.append(q.get_nowait())
    return saida


def _somas(novo, **k):
    return novo.varios_comprovantes.Somas(**k)


def _anexou_um(novo):
    return lambda *a, **k: _somas(novo, anexados=[{"resultado": "anexado", "valor": 1,
                                                    "pdf": "a + b"}])


def test_casar_e_anexar_roda_a_fase_1_inteira_e_sai_um_fim_somado(modulo, novo,
                                                                  monkeypatch, tmp_path):
    dono = _Dono()
    f = _nova(novo, dono)
    f.pagos = [{"paidId": "P1", "valor": 100}]                   # como o montar_pagos deu

    def fase1(self, contas_sel, termos, pasta, simular):
        self.pagos[0].update(status="SEM PAR")
        self.q.put(("fim", (0, 0, 0, 1, "rel.xlsx")))

    chamadas = []

    def somas(api, pagos, pasta, **k):
        chamadas.append((api, pagos))
        return _anexou_um(novo)()

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas", somas)
    relatorio = []
    monkeypatch.setattr(novo.varios_comprovantes, "acrescentar_ao_relatorio",
                        lambda caminho, somas: relatorio.append(caminho))
    f._t_auto({"C"}, [], str(tmp_path), False)
    fins = [v for k, v in _itens(f.q) if k == "fim"]
    assert fins == [(1, 1, 0, 0, "rel.xlsx")]
    assert [api for api, _ in chamadas] == ["api-do-dono"]
    assert chamadas[0][1] is f.pagos and relatorio == ["rel.xlsx"]
    assert f.q.desviar is False


def test_cada_rodada_remonta_os_pagos_sem_sobra_da_anterior(modulo, novo, monkeypatch,
                                                           tmp_path):
    """`motivo_soma`, status, PDF e afins de uma rodada não podem prender a
    seguinte: cada "Casar e anexar" começa dos pagos como a busca os trouxe."""
    f = _nova(novo, _Dono())
    f.pagos = [{"paidId": "P1", "valor": 100, "works": ["OBRA MODELO"]}]
    vistos, nas_somas = [], []

    def fase1(self, *a):
        vistos.append(copy.deepcopy(self.pagos))
        self.pagos[0].update(status="SEM PAR", motivo_sem_par="x", motivo_soma="x",
                             pdf="velho.pdf", resultado="anexado")
        self.pagos[0]["works"].append("SUJEIRA")
        self.q.put(("fim", (0, 0, 0, 1, "")))

    def somas(api, pagos, pasta, **k):
        nas_somas.append(pagos)
        return _somas(novo)

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas", somas)
    monkeypatch.setattr(novo.varios_comprovantes, "acrescentar_ao_relatorio",
                        lambda *a: None)
    f._t_auto({"C"}, [], str(tmp_path), False)
    f._t_auto({"C"}, [], str(tmp_path), False)
    limpo = [{"paidId": "P1", "valor": 100, "works": ["OBRA MODELO"]}]
    assert vistos == [limpo, limpo]
    assert nas_somas[0] is not nas_somas[1]              # lista nova a cada rodada


def test_fase_1_com_erro_nao_roda_a_fase_2(modulo, novo, monkeypatch, tmp_path):
    f = _nova(novo, _Dono())

    def fase1(self, *a):
        self.q.put(("reabilitar2", None))

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas",
                        lambda *a, **k: pytest.fail("não devia somar"))
    f._t_auto({"C"}, [], str(tmp_path), False)
    assert _itens(f.q) == [("reabilitar2", None)] and f.q.desviar is False


def test_fase_1_que_explode_solta_a_fila(modulo, novo, monkeypatch, tmp_path):
    f = _nova(novo, _Dono())

    def fase1(self, *a):
        raise RuntimeError("bug")

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    with pytest.raises(RuntimeError):
        f._t_auto({"C"}, [], str(tmp_path), False)
    assert f.q.desviar is False


def test_parado_na_fase_1_nao_soma_e_devolve_o_fim_dela(modulo, novo, monkeypatch, tmp_path):
    f = _nova(novo, _Dono())

    def fase1(self, *a):
        self._parar.set()
        self.q.put(("fim", (1, 2, 0, 0, "")))

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas",
                        lambda *a, **k: pytest.fail("não devia somar"))
    f._t_auto({"C"}, [], str(tmp_path), False)
    assert _itens(f.q) == [("fim", (1, 2, 0, 0, ""))]


def test_erro_na_fase_2_ainda_entrega_o_fim_da_fase_1(modulo, novo, monkeypatch, tmp_path):
    f = _nova(novo, _Dono())

    def fase1(self, *a):
        self.q.put(("fim", (1, 1, 0, 1, "")))

    def somas(*a, **k):
        raise RuntimeError("API caiu")

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas", somas)
    f._t_auto({"C"}, [], str(tmp_path), False)
    itens = _itens(f.q)
    assert [v for k, v in itens if k == "fim"] == [(1, 1, 0, 1, "")]
    assert any(k == "log" and "API caiu" in v for k, v in itens)


def test_relatorio_que_nao_grava_nao_apaga_a_conta_das_somas(modulo, novo, monkeypatch,
                                                            tmp_path):
    """Excel aberto na máquina: o anexo já foi feito, o "Concluído" tem de contá-lo."""
    f = _nova(novo, _Dono())

    def fase1(self, *a):
        self.q.put(("fim", (0, 0, 0, 1, "rel.xlsx")))

    def nao_grava(*a):
        raise PermissionError("rel.xlsx aberto")

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas", _anexou_um(novo))
    monkeypatch.setattr(novo.varios_comprovantes, "acrescentar_ao_relatorio", nao_grava)
    f._t_auto({"C"}, [], str(tmp_path), False)
    itens = _itens(f.q)
    assert [v for k, v in itens if k == "fim"] == [(1, 1, 0, 0, "rel.xlsx")]
    assert any(k == "log" and "rel.xlsx aberto" in v for k, v in itens)


# ---- a fase das somas roda INTEIRA na thread do navegador (Playwright sync)
def _dono_de_verdade(modulo, monkeypatch, *, ligado):
    monkeypatch.setattr(modulo.central, "ligado", lambda *a, **k: ligado)
    d = modulo.AnexarFrame.__new__(modulo.AnexarFrame)
    d.mc = "mc-do-dono"
    d.api = "api-do-dono"
    d.exec = ThreadPoolExecutor(max_workers=1, thread_name_prefix="nav-do-dono")
    d._trabalho_atual = d._rotulo_atual = d._pulso_nav = None
    d._encerrando = False
    return d


def _desligar(dono):
    for vaga in list(getattr(dono, "_vagas", {}).values()):
        vaga.executor.shutdown(wait=True)
    dono.exec.shutdown(wait=True)


@pytest.mark.parametrize("ligado", [False, True])
def test_fase_1_e_somas_rodam_na_mesma_thread_do_navegador(modulo, novo, monkeypatch,
                                                           tmp_path, ligado):
    dono = _dono_de_verdade(modulo, monkeypatch, ligado=ligado)
    f = _nova(novo, dono)
    if ligado:
        dono._vaga_de(f).api = "api-da-vaga-da-copia"
    f.pagos = [{"paidId": "P1", "valor": 100}]
    visto = {}

    def fase1(self, *a):
        visto["fase1"] = threading.current_thread()
        visto["api1"] = self.api
        self.q.put(("fim", (0, 0, 0, 1, "")))

    def somas(api, pagos, pasta, **k):
        visto["fase2"] = threading.current_thread()
        visto["api2"] = api
        return _somas(novo)

    monkeypatch.setattr(modulo.AnexarFrame, "_t_auto", fase1)
    monkeypatch.setattr(novo.varios_comprovantes, "fase_das_somas", somas)
    monkeypatch.setattr(novo.varios_comprovantes, "acrescentar_ao_relatorio",
                        lambda *a: None)
    try:
        fut = f.submeter("Anexar — casar e anexar", f._t_auto, {"C"}, [], str(tmp_path),
                         False)
        fut.result(timeout=10)
        assert dono.dona_ocupada(aba=f) is None
    finally:
        _desligar(dono)
    assert visto["fase1"] is visto["fase2"]
    assert visto["fase1"] is not threading.main_thread()
    esperado = "nav-AnexarNovoFrame" if ligado else "nav-do-dono"
    assert visto["fase1"].name.startswith(esperado)
    api = "api-da-vaga-da-copia" if ligado else "api-do-dono"
    assert visto["api1"] == visto["api2"] == api
