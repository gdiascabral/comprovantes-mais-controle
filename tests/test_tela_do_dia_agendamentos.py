# -*- coding: utf-8 -*-
""""Conferir agendamentos" na aba "Pagamentos do dia" (dono, 23/10/2026: "já
acrescente o de verificar os agendamentos no pagamentos do dia").

Sem Tk, sem Chrome e sem banco: o controlador nasce por __new__ (como o
`LeitorSicoob` em test_tela_do_dia_sicoob_na_tela.py), os botões e a thread
são dublês e o `conftest` troca as janelas do messagebox. Dados FICTÍCIOS."""
import datetime as dt
import os
import queue
import threading
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

from pagamentos_dia import agendamentos_sicoob as A
from pagamentos_dia import conferir_agendamentos as ca
from pagamentos_dia import html_pagamentos
from tela_do_dia import agendamentos_na_tela as m

HOJE = dt.date(2026, 10, 23)
RAIZ = Path(__file__).resolve().parents[1]


class _Widget:
    def __init__(self):
        self.estado = {}

    def configure(self, **kw):
        self.estado.update(kw)


class _Tela:
    def __init__(self, pasta, periodo=None, leitura=None):
        self.pasta, self.periodo, self.leitura = pasta, periodo, leitura
        self.v_ini = NS(get=lambda: "23/10/2026")
        self.v_fim = NS(get=lambda: "23/10/2026")
        self._sugerido = ("23/10/2026", "23/10/2026")
        self.registro = []

    def _pasta_pagamentos(self):
        return self.pasta

    def _log(self, msg=""):
        self.registro.append(msg)


def _conf(tela):
    c = m.ConferenciaNaTela.__new__(m.ConferenciaNaTela)
    c.tela, c.q, c._thread, c._parar = tela, queue.Queue(), None, threading.Event()
    c.outros_no_sicoob = lambda: None
    c.b_conferir = _Widget()
    return c


def _html(pasta, ini, fim, contas):
    texto = ("<html><script>\nconst DATA = "
             + html_pagamentos.json_para_script({"contas": contas})
             + ";\nfunction x(){}\n</script></html>")
    p = pasta / f"pagamentos_{html_pagamentos.rotulo_periodo(ini, fim)}.html"
    p.write_text(texto, encoding="utf-8")
    return p


@pytest.fixture(autouse=True)
def _hoje_fixo(monkeypatch):
    monkeypatch.setattr(m, "_hoje", lambda: HOJE)


@pytest.fixture
def janelas(monkeypatch):
    vistas = []
    for nome in ("showinfo", "showwarning"):
        monkeypatch.setattr(m.messagebox, nome,
                            lambda t, txt, _n=nome, **k: vistas.append((_n, txt)))
    monkeypatch.setattr(ca.messagebox, "showinfo",
                        lambda t, txt, **k: vistas.append(("showinfo", txt)))
    monkeypatch.setattr(ca.messagebox, "showwarning",
                        lambda t, txt, **k: vistas.append(("showwarning", txt)))
    return vistas


@pytest.fixture
def threads(monkeypatch):
    criadas = []

    class _Thread:
        def __init__(self, target=None, args=(), name=None, daemon=None):
            criadas.append((target, args, name, daemon))

        def start(self):
            pass

        def is_alive(self):
            return True

    monkeypatch.setattr(m.threading, "Thread", _Thread)
    return criadas


# ------------------------------------------------------------ o HTML do dia


def test_html_do_dia_e_o_que_esta_tela_grava(tmp_path):
    ini = fim = HOJE
    assert m.html_do_dia(tmp_path, ini, fim) is None
    p = _html(tmp_path, ini, fim, [])
    assert m.html_do_dia(tmp_path, ini, fim) == p
    # O de pessoa física e o de outro período não servem.
    (tmp_path / "pagamentos_pessoa_fisica_lancamento_2026-10-22.html").write_text("x")
    assert m.html_do_dia(tmp_path, HOJE - dt.timedelta(days=1), HOJE - dt.timedelta(days=1)) \
        is None


def test_periodo_vem_da_leitura_na_tela_e_sem_ela_dos_campos():
    leitura = NS(periodo=(dt.date(2026, 10, 20), dt.date(2026, 10, 22)))
    assert m.periodo_do_html(_Tela(None, leitura=leitura), HOJE) == leitura.periodo
    assert m.periodo_do_html(_Tela(None), HOJE) == (HOJE, HOJE)
    tela = _Tela(None)
    tela.v_fim = NS(get=lambda: "99/99/2026")
    with pytest.raises(ValueError):
        m.periodo_do_html(tela, HOJE)


# --------------------------------------------------------------- recusas


def test_sem_html_do_dia_diz_para_gerar_primeiro(tmp_path, janelas, threads):
    c = _conf(_Tela(tmp_path))
    c.conferir()
    assert janelas == [("showinfo", m.SEM_HTML)]
    assert "gere o html do dia primeiro" in m.SEM_HTML.lower()
    assert threads == [] and c.b_conferir.estado == {}


def test_sicoob_em_uso_recusa_antes_de_tudo_e_diz_quem(tmp_path, janelas, threads):
    c = _conf(_Tela(tmp_path))
    c.outros_no_sicoob = lambda: "Pagamentos do dia — lendo o saldo do Sicoob"
    c.conferir()
    assert len(janelas) == 1 and "lendo o saldo do Sicoob" in janelas[0][1]
    assert threads == [] and c.b_conferir.estado == {}


def test_conferencia_rodando_nao_abre_outra(tmp_path, janelas, threads):
    c = _conf(_Tela(tmp_path))
    c._thread = NS(is_alive=lambda: True)
    c.conferir()
    assert len(janelas) == 1 and "ainda está rodando" in janelas[0][1]
    assert threads == []


def test_html_sem_conta_do_sicoob_e_recado_neutro(tmp_path, monkeypatch, janelas, threads):
    _html(tmp_path, HOJE, HOJE, [{"nome": "B - INTER", "entries": []}])
    monkeypatch.setattr(m, "_carregar_mapas", lambda: (None, None))
    monkeypatch.setattr(A, "conta_sicoob", lambda n, mm, e: ("", A.MOTIVO_FORA_SICOOB))
    _conf(_Tela(tmp_path)).conferir()
    assert janelas and "Nenhuma conta deste HTML é do Sicoob" in janelas[0][1]
    assert threads == []


def test_cadastro_ilegivel_avisa_e_nao_abre_o_chrome(tmp_path, monkeypatch, janelas, threads):
    _html(tmp_path, HOJE, HOJE, [{"nome": "A - SICOOB", "entries": []}])

    def quebra():
        raise OSError("contas_sicoob.json estragado")
    monkeypatch.setattr(m, "_carregar_mapas", quebra)
    _conf(_Tela(tmp_path)).conferir()
    assert janelas and janelas[0][0] == "showwarning"
    assert threads == []


def test_dono_cancela_e_nada_abre(tmp_path, monkeypatch, janelas, threads):
    _html(tmp_path, HOJE, HOJE, [{"nome": "A - SICOOB", "entries": []}])
    monkeypatch.setattr(m, "_carregar_mapas", lambda: (None, None))
    monkeypatch.setattr(A, "conta_sicoob", lambda n, mm, e: ("11.111-1", ""))
    monkeypatch.setattr(m.messagebox, "askokcancel", lambda *a, **k: False)
    c = _conf(_Tela(tmp_path))
    c.conferir()
    assert threads == [] and c.b_conferir.estado == {}


# ------------------------------------------------------------- caminho feliz


def test_confirma_e_abre_a_thread_propria_com_o_html_do_dia(tmp_path, monkeypatch,
                                                           janelas, threads):
    p = _html(tmp_path, HOJE, HOJE, [{"nome": "A - SICOOB", "entries": []},
                                     {"nome": "B - INTER", "entries": []}])
    os.utime(p, (dt.datetime(2026, 10, 23, 9, 41).timestamp(),) * 2)
    monkeypatch.setattr(m, "_carregar_mapas", lambda: (None, None))
    monkeypatch.setattr(A, "conta_sicoob", lambda n, mm, e: (
        ("11.111-1", "") if "SICOOB" in n else ("", A.MOTIVO_FORA_SICOOB)))
    perguntas = []
    monkeypatch.setattr(m.messagebox, "askokcancel",
                        lambda t, txt, **k: perguntas.append(txt) or True)
    tela = _Tela(tmp_path)
    c = _conf(tela)
    c.conferir()
    assert janelas == []
    assert "1 conta(s)" in perguntas[0] and "só leitura" in perguntas[0].lower()
    assert p.name in perguntas[0] and "09:41" in perguntas[0]
    assert c.b_conferir.estado == {"state": "disabled"}
    (alvo, args, nome, daemon), = threads
    assert alvo == c._t_conferir and daemon is True and nome == "sicoob-agendamentos-dia"
    assert args[0] == p
    assert any("fora da conferência: B - INTER" in r for r in tela.registro)


def test_thread_le_pelo_motor_com_o_outro_acesso_e_sempre_termina(tmp_path, monkeypatch):
    chamadas = []

    def ler(no_sicoob, fora, inicio, fim, **k):
        chamadas.append(k)
        return ["confronto"]
    monkeypatch.setattr(ca, "ler_no_banco", ler)
    c = _conf(_Tela(tmp_path))
    c._t_conferir(Path("x.html"), [], [], HOJE, HOJE)
    assert chamadas[0]["perguntar"] == c._perguntar_outro_acesso
    assert chamadas[0]["parar"] == c._parar.is_set
    assert [c.q.get_nowait()[0] for _ in range(2)] == ["pronto", "fim"]


def test_thread_que_estoura_ainda_religa_o_botao(tmp_path, monkeypatch):
    def ler(*a, **k):
        raise RuntimeError("pane")
    monkeypatch.setattr(ca, "ler_no_banco", ler)
    tela = _Tela(tmp_path)
    c = _conf(tela)
    c._t_conferir(Path("x.html"), [], [], HOJE, HOJE)
    assert [c.q.get_nowait()[0] for _ in range(2)] == ["falhou", "fim"]


def test_fim_religa_o_botao_e_pronto_abre_a_janela(tmp_path, monkeypatch):
    abertas = []
    monkeypatch.setattr(ca, "abrir_janela", lambda master, cam, confs: abertas.append(
        (cam, confs)))
    c = _conf(_Tela(tmp_path))
    c.b_conferir = _Widget()
    c.b_conferir.winfo_toplevel = lambda: "janela"
    c.b_conferir.after = lambda *a: None
    c.q.put(("pronto", (Path("x.html"), ["c"])))
    c.q.put(("fim", None))
    c._drain()
    assert abertas == [(Path("x.html"), ["c"])]
    assert c.b_conferir.estado == {"state": "normal"}


def test_pergunta_do_outro_acesso_vai_pela_fila_e_fechar_responde_nao(tmp_path):
    c = _conf(_Tela(tmp_path))
    c._parar.set()
    assert c._perguntar_outro_acesso(["M - SICOOB"]) is False
    tipo, (texto, _caixa) = c.q.get_nowait()
    assert tipo == "perguntar" and "M - SICOOB" in texto and "QR Code" in texto


def test_ocupado_diz_o_nome_da_tela():
    c = _conf(_Tela(None))
    assert c.ocupado() is None
    c._thread = NS(is_alive=lambda: True)
    assert c.ocupado() == m.OCUPADO and "Pagamentos do dia" in m.OCUPADO


# ------------------------------------------------------------ quem espera quem


def test_frame_junta_saldo_e_conferencia_numa_resposta_so():
    from tela_do_dia import frame as f
    t = f.TelaDoDiaFrame.__new__(f.TelaDoDiaFrame)
    t.sicoob = NS(ocupado=lambda: None)
    t.agendamentos = NS(ocupado=lambda: None)
    t.prova = NS(ocupado=lambda: None)
    t.autenticar = NS(ocupado=lambda: None)
    assert t.sicoob_ocupado() is None
    t.agendamentos = NS(ocupado=lambda: m.OCUPADO)
    assert t.sicoob_ocupado() == m.OCUPADO
    t.sicoob = NS(ocupado=lambda: "saldo")
    assert t.sicoob_ocupado() == "saldo"


def test_app_liga_a_conferencia_da_tela_em_todas_as_pontas():
    app = (RAIZ / "comprovantes_app.py").read_text(encoding="utf-8")

    def trecho(chave):
        return app.split(chave, 1)[1].split("\n    #", 1)[0]
    # Ela pergunta a todos os outros que abrem o perfil do Sicoob...
    propria = trecho("aba_dia.agendamentos.outros_no_sicoob =")
    for quem in ("aba_ext.ocupado()", "baixar_comprovantes_no_sicoob(aba_bxc)",
                 "aba_dia.sicoob.ocupado()", "_remessa_conferindo()"):
        assert quem in propria, quem
    # ...e todos perguntam a ela.
    assert "aba_dia.agendamentos.ocupado()" in trecho("aba_dia.sicoob.outros_no_sicoob =")
    assert "aba_pag._agendamentos.is_alive()" in trecho("def _remessa_conferindo")
    assert "aba_dia.sicoob_ocupado()" in trecho("aba_pag.sicoob_ocupado =")
    assert "aba_ext.sicoob_ocupado = aba_dia.sicoob_ocupado\n" in app
    assert "aba_bxc.sicoob_ocupado = aba_dia.sicoob_ocupado\n" in app
    assert '("dia", aba_dia.sicoob_ocupado())' in app


def test_frame_nao_abre_o_sicoob_e_fecha_a_conferencia():
    frame = (RAIZ / "tela_do_dia" / "frame.py").read_text(encoding="utf-8")
    modulo = (RAIZ / "tela_do_dia" / "agendamentos_na_tela.py").read_text(encoding="utf-8")
    assert "SicoobClient" not in frame and "SicoobClient(" not in modulo
    assert "submeter(" not in modulo and "anx." not in modulo
    assert "self.agendamentos.fechar()" in frame
    # O motor é o da Remessa, não uma cópia.
    assert "ca.ler_no_banco(" in modulo and "ca.abrir_janela(" in modulo
    assert "ca.separar(" in modulo and "A.confrontar(" not in modulo


def test_saldo_que_abre_o_sicoob_durante_a_pergunta_segura_a_conferencia(
        tmp_path, monkeypatch, janelas, threads):
    """Revisão de 23/10/2026: a pergunta é modal, mas o saldo (o Buscar) pode
    abrir o Chrome do Sicoob enquanto ela está aberta."""
    _html(tmp_path, HOJE, HOJE, [{"nome": "A - SICOOB", "entries": []}])
    monkeypatch.setattr(m, "_carregar_mapas", lambda: (None, None))
    monkeypatch.setattr(A, "conta_sicoob", lambda n, mm, e: ("11.111-1", ""))
    c = _conf(_Tela(tmp_path))
    quem = {"agora": None}
    c.outros_no_sicoob = lambda: quem["agora"]

    def ok(*a, **k):
        quem["agora"] = "Pagamentos do dia — lendo o saldo do Sicoob"
        return True
    monkeypatch.setattr(m.messagebox, "askokcancel", ok)
    c.conferir()
    assert threads == [] and c.b_conferir.estado == {}
    assert len(janelas) == 1 and "lendo o saldo do Sicoob" in janelas[0][1]
