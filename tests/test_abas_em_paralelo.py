# -*- coding: utf-8 -*-
"""Abas em paralelo no modo central (plano de 15/10/2026).

Teste do dono na v2.0.238: com "Pagamentos do Dia — buscar" rodando, o
"Saldo de pagamentos" levou "Navegador ocupado". Com o Chrome central ligado,
cada aba do app tem a SUA thread e o SEU `MCClient` (a "vaga"); o aviso só
vale quando a MESMA aba já trabalha. Desligado, tudo como antes: uma thread,
um cliente, o mesmo aviso.

Testes puros: a `AnexarFrame` nasce sem `__init__` (sem Tk), com só o que o
código lê — como em `test_aba_da_pessoa.py`."""
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest


class _Dona:
    """Uma aba do app qualquer (só a identidade importa)."""


class _DonaB:
    pass


@pytest.fixture
def modulo():
    pytest.importorskip("playwright")
    from anexar import anexar_comprovantes as modulo
    return modulo


def _frame(modulo, monkeypatch, *, ligado: bool):
    monkeypatch.setattr(modulo.central, "ligado", lambda *a, **k: ligado)
    f = modulo.AnexarFrame.__new__(modulo.AnexarFrame)
    f.mc = None
    f.api = None
    f.exec = ThreadPoolExecutor(max_workers=1)
    f._trabalho_atual = None
    f._rotulo_atual = None
    f._pulso_nav = None
    f._encerrando = False
    f.registro = []
    f._log = f.registro.append
    f.after = lambda *a, **k: None
    f.winfo_children = lambda: []
    f.chamadas = []
    from tkinter import messagebox
    monkeypatch.setattr(messagebox, "askyesno",
                        lambda *a, **k: f.chamadas.append(("pergunta",)) or False)
    monkeypatch.setattr(messagebox, "showinfo",
                        lambda *a, **k: f.chamadas.append(("aviso",)))
    return f


@pytest.fixture
def desligado(modulo, monkeypatch):
    f = _frame(modulo, monkeypatch, ligado=False)
    try:
        yield f
    finally:
        f._encerrando = True
        f.exec.shutdown(wait=False)


@pytest.fixture
def ligado(modulo, monkeypatch):
    f = _frame(modulo, monkeypatch, ligado=True)
    try:
        yield f
    finally:
        f._encerrando = True
        for vaga in list(getattr(f, "_vagas", {}).values()):
            vaga.executor.shutdown(wait=False)
        f.exec.shutdown(wait=False)


# ------------------------------------------------------------ desligado
def test_desligado_duas_donas_dividem_a_thread_e_o_aviso(desligado):
    a, b = _Dona(), _DonaB()
    solta = threading.Event()
    ids = []
    fa = desligado.submeter("A", lambda: (ids.append(threading.get_ident()),
                                          solta.wait(5)), dona=a)
    try:
        assert desligado.avisar_se_ocupado("a aba B", aba=b) is True
        assert desligado.chamadas == [("pergunta",)]
        assert desligado.ocupado() == "A"
        assert desligado.dona_ocupada() is a
    finally:
        solta.set()
    fa.result(timeout=5)
    fb = desligado.submeter("B", lambda: ids.append(threading.get_ident()), dona=b)
    fb.result(timeout=5)
    assert ids[0] == ids[1]                   # o mesmo executor de sempre
    assert not getattr(desligado, "_vagas", None)


# -------------------------------------------------------------- ligado
def test_ligado_donas_diferentes_nao_se_esperam(ligado):
    a, b = _Dona(), _DonaB()
    solta = threading.Event()
    ordem, ids = [], {}

    def trabalho_a():
        ids["a"] = threading.current_thread()
        solta.wait(5)
        ordem.append("a")

    def trabalho_b():
        ids["b"] = threading.current_thread()
        ordem.append("b")

    fa = ligado.submeter("A", trabalho_a, dona=a)
    try:
        assert ligado.avisar_se_ocupado("a aba B", aba=b) is False
        assert ligado.chamadas == []
        fb = ligado.submeter("B", trabalho_b, dona=b)
        fb.result(timeout=5)                  # B termina com A ainda presa
        assert ordem == ["b"]
    finally:
        solta.set()
    fa.result(timeout=5)
    assert ids["a"] is not ids["b"]
    assert ids["a"].name.startswith("nav-_Dona")
    assert ids["b"].name.startswith("nav-_DonaB")


def test_ligado_mesma_dona_avisa(ligado):
    a = _Dona()
    solta = threading.Event()
    fa = ligado.submeter("A", solta.wait, 5, dona=a)
    try:
        assert ligado.avisar_se_ocupado("a aba A", aba=a) is True
        assert ligado.chamadas == [("pergunta",)]
        # a barra lateral continua vendo quem trabalha
        assert ligado.ocupado() == "A"
        assert ligado.dona_ocupada() is a
        assert ligado.ocupado(aba=_DonaB()) is None
        assert ligado.dona_ocupada(aba=a) is a
    finally:
        solta.set()
    fa.result(timeout=5)
    assert ligado.ocupado() is None
    assert ligado.dona_ocupada() is None


def test_ligado_sem_dona_e_a_vaga_do_proprio_anexar(ligado):
    solta = threading.Event()
    f = ligado.submeter("Abrir o Mais Controle", solta.wait, 5)
    try:
        assert ligado.avisar_se_ocupado("o Anexar") is True
        assert ligado.dona_ocupada() is ligado
    finally:
        solta.set()
    f.result(timeout=5)


def test_ligado_mc_e_api_sao_da_vaga(ligado):
    a, b = _Dona(), _DonaB()
    x, api_x = object(), object()

    def em_a():
        ligado.mc = x
        ligado.api = api_x
        return ligado.mc

    assert ligado.submeter("A", em_a, dona=a).result(timeout=5) is x
    assert ligado.submeter("B", lambda: (ligado.mc, ligado.api),
                           dona=b).result(timeout=5) == (None, None)
    assert ligado.submeter("A", lambda: (ligado.mc, ligado.api),
                           dona=a).result(timeout=5) == (x, api_x)
    # fora de thread de vaga, o atributo de sempre
    assert ligado.mc is None
    y = object()
    ligado.mc = y
    assert ligado._mc is y
    assert ligado.submeter("B", lambda: ligado.mc, dona=b).result(timeout=5) is None


def test_desligado_mc_e_o_atributo_de_sempre(desligado):
    x = object()
    assert desligado.submeter("A", lambda: setattr(desligado, "mc", x),
                              dona=_Dona()).result(timeout=5) is None
    assert desligado.mc is x
    assert desligado._mc is x


def test_fechar_fecha_cada_mc_na_thread_da_vaga(ligado):
    a, b = _Dona(), _DonaB()
    saidas = []

    class _MC:
        fechado = False

        def __exit__(self, *exc):
            saidas.append((self, threading.get_ident()))

    def abrir():
        ligado.mc = _MC()
        return ligado.mc, threading.get_ident()

    mc_a, id_a = ligado.submeter("A", abrir, dona=a).result(timeout=5)
    mc_b, id_b = ligado.submeter("B", abrir, dona=b).result(timeout=5)
    ligado.fechar()
    assert len(saidas) == 2
    assert set(saidas) == {(mc_a, id_a), (mc_b, id_b)}
    assert ligado._vagas == {}


# ------------------------------------------------- os chamadores (Tarefa 2)
_CHAMADORES = ("anexar/conferencia.py", "aportes/aportes_frame.py",
               "comprovantes_app.py", "conciliacao/frame.py",
               "contratos/frame.py", "guias/painel.py",
               "pagamentos_dia/pagamentos_frame.py",
               "relatorios/relatorio_frame.py")


def _chamadas(arquivo: str, metodo: str, chave: str) -> list[str]:
    import ast
    from pathlib import Path
    raiz_repo = Path(__file__).resolve().parents[1]
    arvore = ast.parse((raiz_repo / arquivo).read_text(encoding="utf-8"))
    achadas = []
    for no in ast.walk(arvore):
        if (isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
                and no.func.attr == metodo):
            kw = [k for k in no.keywords if k.arg == chave]
            achadas.append(ast.unparse(kw[0].value) if kw else "<faltou>")
    return achadas


@pytest.mark.parametrize("arquivo", _CHAMADORES)
def test_todo_aviso_diz_a_aba_que_vai_submeter(arquivo):
    """No central, o aviso só olha a vaga da `aba`. Se ela não for a mesma
    dona do `submeter` daquele fluxo, o aviso olha a vaga errada: deixa
    passar a aba que já trabalha, ou barra a que está livre."""
    abas = _chamadas(arquivo, "avisar_se_ocupado", "aba")
    donas = _chamadas(arquivo, "submeter", "dona")
    assert abas and "<faltou>" not in abas
    assert set(abas) == set(donas)
