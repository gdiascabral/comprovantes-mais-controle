# -*- coding: utf-8 -*-
"""O "Reler Sicoob" sem Tk: o controlador nasce por __new__ (como em
test_abas_em_paralelo.py). Prova a thread própria, as mensagens da fila, as
recusas e a regra dos botões (gravando na nuvem ou sem leitura, apagado)."""
import datetime as dt
import queue
import threading
from decimal import Decimal as D
from pathlib import Path

import pytest

pytest.importorskip("playwright")

from tela_do_dia import saldo_sicoob as ss  # noqa: E402
from tela_do_dia import sicoob_na_tela as m  # noqa: E402

HOJE = dt.date(2026, 10, 22)
RAIZ = Path(__file__).resolve().parents[1]


class _Widget:
    def __init__(self): self.estado = {}
    def configure(self, **kw): self.estado.update(kw)
    def after(self, *a, **k): pass


def _leitor(tela):
    l = m.LeitorSicoob.__new__(m.LeitorSicoob)
    l.tela, l.q, l._thread, l._parar = tela, queue.Queue(), None, threading.Event()
    l.leitura, l.contas, l._lendo, l._carregada_de, l._chave_contas = None, [], None, None, None
    l._pode = True
    l.outros_no_sicoob = lambda: None
    l.lbl, l.b_reler, l.barra = _Widget(), _Widget(), _Widget()
    return l


def _tela():
    registro = []
    return type("T", (), {"mapping": object(), "dia": object(), "leitura": object(),
                          "_gravando": False,
                          "periodo": type("P", (), {"fim": HOJE})(),
                          "_log": staticmethod(registro.append), "registro": registro})()


def test_le_numa_thread_propria_e_o_chrome_nasce_e_morre_nela(monkeypatch):
    from extratos_sicoob import saldo, sicoob_client
    threads = []

    class _Cli:
        def __init__(self, log): pass
        def __enter__(self): threads.append(threading.current_thread()); return self
        def __exit__(self, *a): threads.append(threading.current_thread())
        def aguardar_login(self): pass

    monkeypatch.setattr(sicoob_client, "SicoobClient", _Cli)
    monkeypatch.setattr(saldo, "medido", lambda: True)
    monkeypatch.setattr(saldo, "ler_contas", lambda cli, numeros, **kw: [
        saldo.Lido("12.345-6", D("10.00"), dt.datetime(2026, 10, 22, 8, 12))])
    monkeypatch.setattr(m.messagebox, "askokcancel", lambda *a, **k: True)
    l = _leitor(_tela())
    l.contas = [ss.ContaDoPainel("Alfa", numero="12.345-6")]
    l.reler(perguntar=False)
    l._thread.join(5)
    assert threads[0] is threads[1] and threads[0] is not threading.main_thread()
    assert threads[0].name == "sicoob-saldo" and threads[0].daemon
    tipos = []
    while not l.q.empty():
        tipos.append(l.q.get()[0])
    assert tipos[-2:] == ["lida", "fim"]
    assert l.b_reler.estado["state"] == "disabled"      # só o "fim", na tela, religa


def test_falha_vira_recado_e_a_fila_sempre_termina(monkeypatch):
    from extratos_sicoob import saldo, sicoob_client

    class _Cli:
        def __init__(self, log): pass
        def __enter__(self): raise RuntimeError("ProcessSingleton: profile in use")
        def __exit__(self, *a): pass

    monkeypatch.setattr(sicoob_client, "SicoobClient", _Cli)
    monkeypatch.setattr(saldo, "medido", lambda: True)
    l = _leitor(_tela())
    l._t_ler(["12.345-6"], HOJE)
    mensagens = [l.q.get() for _ in range(l.q.qsize())]
    assert mensagens[0][0] == "falhou" and "já está aberto" in mensagens[0][1]
    assert mensagens[-1] == ("fim", None)


def test_recusa_sem_buscar_sem_endereco_e_com_o_chrome_em_uso(monkeypatch):
    from extratos_sicoob import saldo
    avisos = []
    monkeypatch.setattr(m.messagebox, "showinfo", lambda t, msg: avisos.append(msg))
    tela = _tela()
    l = _leitor(tela)
    monkeypatch.setattr(saldo, "medido", lambda: False)
    l.reler()
    assert "ainda não está ligada" in avisos[-1] and l._thread is None
    monkeypatch.setattr(saldo, "medido", lambda: True)
    tela.mapping = None
    l.reler()
    assert "Busque os pagamentos e saldos primeiro" in avisos[-1]
    tela.mapping = object()
    l.contas = [ss.ContaDoPainel("Alfa", numero="12.345-6")]
    l.outros_no_sicoob = lambda: "Extratos Sicoob"
    l.reler()
    assert "em uso (Extratos Sicoob)" in avisos[-1] and l._thread is None


def test_recusa_enquanto_grava_na_nuvem(monkeypatch):
    from extratos_sicoob import saldo
    avisos = []
    monkeypatch.setattr(m.messagebox, "showinfo", lambda t, msg: avisos.append(msg))
    monkeypatch.setattr(saldo, "medido", lambda: True)
    tela = _tela()
    tela._gravando = True
    l = _leitor(tela)
    l.contas = [ss.ContaDoPainel("Alfa", numero="12.345-6")]
    l.reler(perguntar=False)
    assert "gravação na nuvem" in avisos[-1] and l._thread is None
    l.ler_se_faltar()                    # o automático também não abre
    assert l._thread is None


def test_ler_se_faltar_nao_abre_sem_endereco(monkeypatch):
    from extratos_sicoob import saldo
    monkeypatch.setattr(saldo, "medido", lambda: False)
    l = _leitor(_tela())
    l.contas = [ss.ContaDoPainel("Alfa", numero="12.345-6")]
    l.ler_se_faltar()
    assert l._thread is None


def test_ler_se_faltar_nao_rele_com_leitura_do_dia(monkeypatch):
    from extratos_sicoob import saldo
    monkeypatch.setattr(saldo, "medido", lambda: True)
    l = _leitor(_tela())
    l.contas = [ss.ContaDoPainel("Alfa", numero="12.345-6")]
    l.leitura = ss.LeituraSicoob(HOJE)
    l.ler_se_faltar()
    assert l._thread is None


def test_botao_segue_a_regra_da_tela_e_o_fim_nao_religa_sem_permissao():
    l = _leitor(_tela())
    l.ligar(False)                        # gravando na nuvem / sem leitura
    assert l.b_reler.estado["state"] == "disabled"
    l.ligar(True)
    assert l.b_reler.estado["state"] == "normal"
    # Lendo o Sicoob, a tela pode religar os botões dela: o Reler fica apagado.
    l._thread = type("T", (), {"is_alive": lambda self: True})()
    l.ligar(True)
    assert l.b_reler.estado["state"] == "disabled"
    # A leitura termina no meio de uma gravação: o "fim" não religa.
    l._thread = None
    l.ligar(False)
    l.q.put(("fim", None))
    l._drain()
    assert l.b_reler.estado["state"] == "disabled"
    l.ligar(True)
    l.q.put(("fim", None))
    l._drain()
    assert l.b_reler.estado["state"] == "normal"


def test_ocupado_diz_qual_aba_esta_com_o_sicoob():
    """Achado 19: a Remessa recusa e a mensagem diz QUEM usa o Sicoob."""
    l = _leitor(_tela())
    assert l.ocupado() is None
    l._thread = type("T", (), {"is_alive": lambda self: True})()
    assert "Pagamentos do dia" in l.ocupado()


def test_cadastro_relido_so_quando_a_leitura_do_erp_muda(monkeypatch):
    from pagamentos_dia import pagamentos_frame
    chamadas = []
    monkeypatch.setattr(pagamentos_frame, "_carregar_mapas",
                        lambda: chamadas.append(1) or ({}, {}))
    monkeypatch.setattr(ss, "contas_do_painel", lambda *a: [])
    monkeypatch.setattr(ss, "ler", lambda arquivo, data: (None, ""))
    monkeypatch.setattr(m.LeitorSicoob, "_ligado", staticmethod(lambda: True))
    l = _leitor(_tela())
    contas, mapping = [], object()
    l.aplicar([], contas, mapping)
    l.aplicar([], contas, mapping)
    assert len(chamadas) == 1
    l.aplicar([], [], mapping)            # Buscar de novo: outra lista, outro objeto
    assert len(chamadas) == 2


def test_aplicar_nao_inventa_saldo_sem_leitura(monkeypatch):
    from tela_do_dia import saldos as sd
    monkeypatch.setattr(ss, "ler", lambda arquivo, data: (None, ""))
    monkeypatch.setattr(m.LeitorSicoob, "_ligado", staticmethod(lambda: True))
    l = _leitor(_tela())
    l._chave_contas = ([], None)
    linha = sd.LinhaSaldo(rotulo="Alfa", linha=1, sistema=D("5.00"), banco=None)
    saida = l.aplicar([linha], l._chave_contas[0], l._chave_contas[1])
    assert saida == [linha] and saida[0].banco is None


def test_frame_nao_abre_o_sicoob_na_thread_do_erp():
    frame = (RAIZ / "tela_do_dia" / "frame.py").read_text(encoding="utf-8")
    leitor = (RAIZ / "tela_do_dia" / "sicoob_na_tela.py").read_text(encoding="utf-8")
    assert "SicoobClient" not in frame
    assert "submeter(" not in leitor and "anx." not in leitor
    assert "self.sicoob.ler_se_faltar()" in frame and "self.sicoob.aplicar(" in frame
    assert "self.sicoob.ligar(" in frame and "self.sicoob.fechar()" in frame


def test_app_liga_as_tres_pontas():
    app = (RAIZ / "comprovantes_app.py").read_text(encoding="utf-8")
    assert "aba_dia.sicoob.outros_no_sicoob" in app
    assert "aba_dia.sicoob.ocupado()" in app
    assert '("dia", aba_dia.sicoob.ocupado())' in app
    # A linha antiga (só Extratos) foi substituída, não duplicada.
    assert "aba_pag.sicoob_ocupado = aba_ext.ocupado\n" not in app


def test_guarda_nenhum_teste_puro_chega_ao_messagebox_real():
    """22/10: um teste deste arquivo abriu na tela do dono a pergunta real
    "abrir o Chrome do Sicoob". O `conftest` troca as janelas do
    `tkinter.messagebox` por dublês que registram, e arma o `Message.show`
    (por onde TODA janela do messagebox passa) para derrubar o teste."""
    import tkinter.messagebox as mb
    for nome in ("askokcancel", "askyesno", "askyesnocancel", "askretrycancel",
                 "askquestion", "showinfo", "showwarning", "showerror"):
        assert getattr(mb, nome).__module__ != "tkinter.messagebox", nome
        assert getattr(m.messagebox, nome) is getattr(mb, nome)
    # O caminho comum de todas elas: chegar nele é falha, não janela.
    with pytest.raises(AssertionError, match="janela real"):
        mb.Message(title="x", message="y").show()
    # E o leitor, sem dublê no teste, cai no registro e não abre nada.
    assert m.messagebox.askokcancel("t", "m") is False


# ---------------------------------------------------------------- onda de menores (22/10)
@pytest.fixture(autouse=True)
def _hoje_fixo(monkeypatch):
    """O "hoje" do leitor é o da tela dos testes (a virada da meia-noite é
    conferida contra ele, e não contra o relógio da máquina)."""
    monkeypatch.setattr(m, "_hoje", lambda: HOJE)


def test_baixar_comprovantes_rodando_conta_como_sicoob_em_uso():
    class _Tarefa:
        def __init__(self, viva): self.viva = viva
        def done(self): return not self.viva

    aba = type("Bxc", (), {"worker": None})()
    assert m.baixar_comprovantes_no_sicoob(aba) is None
    aba.worker = _Tarefa(viva=True)
    assert "Baixar comprovantes" in m.baixar_comprovantes_no_sicoob(aba)
    aba.worker = _Tarefa(viva=False)
    assert m.baixar_comprovantes_no_sicoob(aba) is None
    # Aba sem o atributo (ou que falha ao responder): não trava ninguém.
    assert m.baixar_comprovantes_no_sicoob(object()) is None


def test_app_pergunta_ao_baixar_comprovantes_nas_duas_pontas():
    app = (RAIZ / "comprovantes_app.py").read_text(encoding="utf-8")
    trecho_dia = app.split("aba_dia.sicoob.outros_no_sicoob =", 1)[1].split("\n    #", 1)[0]
    trecho_pag = app.split("aba_pag.sicoob_ocupado =", 1)[1].split("\n    #", 1)[0]
    assert "baixar_comprovantes_no_sicoob(aba_bxc)" in trecho_dia
    assert "baixar_comprovantes_no_sicoob(aba_bxc)" in trecho_pag


def test_ler_se_faltar_com_outra_aba_no_sicoob_so_escreve_no_registro(monkeypatch):
    from extratos_sicoob import saldo
    janelas = []
    monkeypatch.setattr(m.messagebox, "showinfo", lambda *a, **k: janelas.append(a))
    monkeypatch.setattr(m.messagebox, "askokcancel", lambda *a, **k: janelas.append(a))
    monkeypatch.setattr(saldo, "medido", lambda: True)
    tela = _tela()
    l = _leitor(tela)
    l.contas = [ss.ContaDoPainel("Alfa", numero="12.345-6")]
    l.outros_no_sicoob = lambda: "Baixar comprovantes"
    l.ler_se_faltar()
    assert janelas == [] and l._thread is None
    assert any("Baixar comprovantes" in r for r in tela.registro)


def test_reler_depois_da_meia_noite_pede_novo_buscar(monkeypatch):
    from extratos_sicoob import saldo
    avisos = []
    monkeypatch.setattr(m.messagebox, "showinfo", lambda t, msg: avisos.append(msg))
    monkeypatch.setattr(saldo, "medido", lambda: True)
    tela = _tela()
    tela.periodo = type("P", (), {"fim": HOJE - dt.timedelta(days=1)})()
    l = _leitor(tela)
    l.contas = [ss.ContaDoPainel("Alfa", numero="12.345-6")]
    l.reler()
    assert avisos[-1] == "Busque de novo: a tela é de 21/10." and l._thread is None
    # O automático (fim do Buscar) também recusa, sem janela.
    n = len(avisos)
    l.ler_se_faltar()
    assert len(avisos) == n and l._thread is None
    assert any("Busque de novo: a tela é de 21/10" in r for r in tela.registro)
