"""O botão "Autenticar no banco": recusas, a thread e a fiação. Sem janela."""
import ast
import queue
import threading
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace

from tela_do_dia import agendados as agd
from tela_do_dia import autenticar as au
from tela_do_dia import autenticar_na_tela as ant
from tela_do_dia import autenticar_sicoob as asi

RAIZ = Path(__file__).resolve().parents[1]


def _peca(tela, outros=None):
    p = object.__new__(ant.AutenticarNaTela)
    p.tela, p.q, p._thread, p._parar = tela, queue.Queue(), None, threading.Event()
    p.outros_no_sicoob = outros or (lambda: None)
    p.b = SimpleNamespace(configure=lambda **k: None)
    return p


def _avisos(monkeypatch):
    ditos = []
    monkeypatch.setattr(ant.messagebox, "showinfo", lambda t, m: ditos.append(m))
    monkeypatch.setattr(ant.messagebox, "askokcancel", lambda t, m: ditos.append(m) or False)
    return ditos


def test_sem_buscar_recusa_e_nao_abre_nada(monkeypatch):
    ditos = _avisos(monkeypatch)
    _peca(SimpleNamespace(lido=None, leitura=None)).autenticar()
    assert "Buscar" in ditos[0]


def test_com_outro_no_sicoob_recusa(monkeypatch):
    ditos = _avisos(monkeypatch)
    a = agd.Agendado(id=1, dia=date(2026, 10, 28), conta="C", alvo="1", lancamento_id="L",
                     favorecido="F", valor=D("1.00"))
    tela = SimpleNamespace(lido=SimpleNamespace(pendentes=[(a, None, None)]), leitura=object())
    _peca(tela, outros=lambda: "Extratos Sicoob").autenticar()
    assert "Extratos Sicoob" in ditos[0]


def test_a_thread_casa_e_manda_pronto_e_sempre_fim(monkeypatch):
    a = agd.Agendado(id=1, dia=date(2026, 10, 28), conta="C", alvo="1", lancamento_id="L",
                     favorecido="F", valor=D("1.00"), foto={"descricao_colada": "X" * 30})
    mov = au.Movimento("C", date(2026, 10, 28), D("1.00"), "", "X" * 30, "", "Sicoob comprovante")
    monkeypatch.setattr(asi, "ler", lambda *a, **k: asi.Leitura([mov], [], {"C"}, {}))
    p = _peca(SimpleNamespace(_log=lambda *a: None))
    p._t_ler([a], {"1": "C"}, {}, date(2026, 10, 27), date(2026, 10, 29))
    tipo, aut = p.q.get_nowait()
    assert tipo == "pronto" and aut[1].prova
    assert p.q.get_nowait() == ("fim", None)


def test_a_thread_que_estoura_diz_e_termina(monkeypatch):
    def quebra(*a, **k):
        raise RuntimeError("x")
    monkeypatch.setattr(asi, "ler", quebra)
    p = _peca(SimpleNamespace(_log=lambda *a: None))
    p._t_ler([], {}, {}, date(2026, 10, 27), date(2026, 10, 29))
    assert p.q.get_nowait()[0] == "falhou" and p.q.get_nowait() == ("fim", None)


def test_o_app_cruza_as_travas_do_sicoob_com_o_autenticar():
    fonte = (RAIZ / "comprovantes_app.py").read_text(encoding="utf-8")
    assert "aba_dia.autenticar.outros_no_sicoob" in fonte
    arvore = ast.parse(fonte)
    alvos = {}
    for no in ast.walk(arvore):
        if isinstance(no, ast.Assign) and isinstance(no.targets[0], ast.Attribute) \
                and no.targets[0].attr == "outros_no_sicoob":
            dono = ast.unparse(no.targets[0].value)
            alvos[dono] = ast.unparse(no.value)
    for dono in ("aba_dia.sicoob", "aba_dia.agendamentos", "aba_dia.prova"):
        assert "aba_dia.autenticar.ocupado()" in alvos[dono], dono


def test_a_aba_conta_o_autenticar_no_sicoob_ocupado_e_fecha_ele():
    frame = ast.parse((RAIZ / "tela_do_dia/frame.py").read_text(encoding="utf-8"))
    fn = {n.name: ast.unparse(n) for n in ast.walk(frame) if isinstance(n, ast.FunctionDef)}
    assert "self.autenticar.ocupado()" in fn["sicoob_ocupado"]
    assert "self.autenticar.fechar()" in fn["fechar"]
