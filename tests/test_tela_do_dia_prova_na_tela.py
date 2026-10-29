# -*- coding: utf-8 -*-
"""O botão "📸 Prova de saldos" sem Tk: o controlador nasce por __new__.
Prova as recusas (antes de apagar botão), a thread própria, o ERP pela vaga
do Anexar (dona = a tela), o Parar, o PDF no fim e a trava entre abas.
Bancos, ERP e PDF são dublês; contas fictícias."""
import concurrent.futures
import datetime as dt
import queue
import threading
from decimal import Decimal as D
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

pytest.importorskip("playwright")

from tela_do_dia import prova_erp  # noqa: E402
from tela_do_dia import prova_na_tela as m  # noqa: E402
from tela_do_dia import prova_pdf  # noqa: E402
from tela_do_dia import prova_saldos as ps  # noqa: E402

AGORA = dt.datetime(2026, 10, 27, 14, 5)
RAIZ = Path(__file__).resolve().parents[1]
ALFA = ps.ContaDaProva(8, "CONTA ALFA", ps.SICOOB, numero="12.345-6")
BETA = ps.ContaDaProva(9, "CONTA BETA", ps.INTER, numero="123456789", apelido="BETA",
                       nomes=("EMPRESA FICTICIA",))


class _Widget:
    def __init__(self):
        self.estado = {}

    def configure(self, **kw):
        self.estado.update(kw)

    def after(self, *a, **k):
        pass


class _Anx:
    def __init__(self, ocupado=False, erp=None, erro=None):
        self.ocupado_, self.erp, self.erro = ocupado, erp or {}, erro
        self.submetidos, self.avisos = [], []

    def avisar_se_ocupado(self, dona, *, aba=None):
        self.avisos.append((dona, aba))
        return self.ocupado_

    def submeter(self, rotulo, fn, *a, dona=None, **k):
        self.submetidos.append((rotulo, fn, a, dona, k))
        fut = concurrent.futures.Future()
        if self.erro is not None:
            fut.set_exception(self.erro)
        else:
            fut.set_result(self.erp)
        return fut


def _tela(tmp_path, anx):
    registro, abertos = [], []
    return NS(mapping=object(), contas_erp=[object()], cfg="cfg", anx=anx,
              _log=registro.append, registro=registro, abertos=abertos,
              _pasta_pagamentos=lambda: tmp_path, _abrir=abertos.append)


def _prova(tela):
    p = m.ProvaNaTela.__new__(m.ProvaNaTela)
    p.tela, p.q, p._thread, p._erp, p._contas = tela, queue.Queue(), None, None, []
    p._parar, p._pode = threading.Event(), True
    p.outros_no_sicoob = lambda: None
    p.barra, p.lbl, p.b_prova, p.b_parar = _Widget(), _Widget(), _Widget(), _Widget()
    return p


@pytest.fixture
def cenario(monkeypatch, tmp_path):
    monkeypatch.setattr(m, "_carregar_cadastros", lambda: (None, [], []))
    monkeypatch.setattr(m.sd, "montar_saldos", lambda contas, mapping: [])
    monkeypatch.setattr(m.ps, "contas_da_prova", lambda *a: [ALFA, BETA])
    monkeypatch.setattr(m, "_agora", lambda: AGORA)
    gerados = []

    def gerar(linhas, quando, destino):
        gerados.append(linhas)
        Path(destino).write_bytes(b"%PDF")
        return Path(destino)
    monkeypatch.setattr(prova_pdf, "gerar", gerar)
    return NS(gerados=gerados, tmp=tmp_path)


def _fila(p):
    itens = []
    while not p.q.empty():
        itens.append(p.q.get())
    return itens


def _sim(monkeypatch):
    monkeypatch.setattr(m.messagebox, "askokcancel", lambda *a, **k: True)


def test_sem_buscar_recusa_e_nada_apaga(cenario, janelas_do_messagebox):
    anx = _Anx()
    tela = _tela(cenario.tmp, anx)
    tela.mapping = None
    p = _prova(tela)
    p.comecar()
    assert anx.avisos == [] and anx.submetidos == [] and p._thread is None
    assert p.b_prova.estado == {}
    assert "Busque" in janelas_do_messagebox[0][1][1]


def test_chrome_do_banco_em_uso_recusa_antes_de_tudo(cenario, janelas_do_messagebox):
    anx = _Anx()
    p = _prova(_tela(cenario.tmp, anx))
    p.outros_no_sicoob = lambda: "Baixar comprovantes — baixando do banco"
    p.comecar()
    assert anx.avisos == [] and anx.submetidos == [] and p._thread is None
    assert p.b_prova.estado == {} and p.q.empty()
    assert "Baixar comprovantes" in janelas_do_messagebox[0][1][1]


def test_erp_ocupado_recusa_pelo_aviso_da_vaga_da_tela(cenario):
    anx = _Anx(ocupado=True)
    tela = _tela(cenario.tmp, anx)
    p = _prova(tela)
    p.comecar()
    assert anx.avisos == [("a Prova de saldos", tela)]
    assert anx.submetidos == [] and p._thread is None and p.b_prova.estado == {}


def test_pergunta_com_nao_nao_comeca(cenario):
    anx = _Anx()
    p = _prova(_tela(cenario.tmp, anx))
    p.comecar()                                   # o dublê responde "não"
    assert anx.submetidos == [] and p._thread is None


def test_caminho_feliz_erp_na_vaga_bancos_na_thread_e_pdf(cenario, monkeypatch):
    _sim(monkeypatch)
    lido = ps.Leitura(D("10.00"), AGORA)
    anx = _Anx(erp={8: lido, 9: lido})
    tela = _tela(cenario.tmp, anx)
    p = _prova(tela)
    monkeypatch.setattr(m.ProvaNaTela, "_ler_bancos",
                        lambda self, contas, pasta: {8: lido, 9: ps.Leitura(D("10.01"), AGORA)})
    p.comecar()
    p._thread.join(5)
    assert p._thread.name == "prova-saldos" and p._thread.daemon
    [(rotulo, fn, args, dona, kw)] = anx.submetidos
    assert (rotulo, fn, dona) == (m.ROTULO_ERP, prova_erp.ler, tela)
    assert args[0] is anx and args[3] == [ALFA, BETA]
    # Revisão de 27/10: tudo numa pasta "Prova de saldos"; os PNGs de cada
    # rodada dentro de UMA subpasta "prints".
    assert args[4] == cenario.tmp / "Prova de saldos" / "prints" / "2026-10-27 14h05"
    assert p.b_prova.estado["state"] == "disabled" and p.b_parar.estado["state"] == "normal"
    itens = _fila(p)
    pdf = cenario.tmp / "Prova de saldos" / "Prova de saldos 2026-10-27 14h05.pdf"
    assert ("pronto", (pdf, "1 batem, 1 não batem, 0 não lidas")) in itens
    assert itens[-1] == ("fim", None)
    [linhas] = cenario.gerados
    assert [l.situacao for l in linhas] == [ps.BATE, ps.NAO_BATE]


def test_bancos_so_abrem_depois_da_aba_do_erp(cenario, monkeypatch):
    """Revisão de 27/10: a aba do robô no ERP vinha para a frente no meio do
    login do Sicoob. Agora ela abre primeiro e os bancos esperam."""
    import time
    _sim(monkeypatch)
    anx = _Anx()
    anx.submeter = lambda rotulo, fn, *a, dona=None, **k: (
        anx.submetidos.append((rotulo, fn, a, dona, k)) or concurrent.futures.Future())
    p = _prova(_tela(cenario.tmp, anx))
    chamado = threading.Event()

    def ler_bancos(self, contas, pasta):
        chamado.set()
        self._parar.set()
        return {}
    monkeypatch.setattr(m.ProvaNaTela, "_ler_bancos", ler_bancos)
    p.comecar()
    [(_r, _f, _a, _d, kw)] = anx.submetidos
    time.sleep(0.4)
    assert not chamado.is_set()
    kw["ao_abrir_aba"]()
    assert chamado.wait(3)
    p._thread.join(5)


def test_erp_que_falha_vira_nao_lida_e_o_pdf_sai(cenario, monkeypatch):
    _sim(monkeypatch)
    anx = _Anx(erro=RuntimeError("sessão caiu"))
    p = _prova(_tela(cenario.tmp, anx))
    monkeypatch.setattr(m.ProvaNaTela, "_ler_bancos", lambda self, contas, pasta: {})
    p.comecar()
    p._thread.join(5)
    [linhas] = cenario.gerados
    assert all(l.situacao == ps.NAO_LIDA for l in linhas)
    assert linhas[0].motivo == "ERP: RuntimeError: sessão caiu"


def test_parar_nao_gera_pdf_e_diz_por_que(cenario, monkeypatch):
    _sim(monkeypatch)
    p = _prova(_tela(cenario.tmp, _Anx()))

    def para(self, contas, pasta):
        self._parar.set()
        return {}
    monkeypatch.setattr(m.ProvaNaTela, "_ler_bancos", para)
    p.comecar()
    p._thread.join(5)
    itens = _fila(p)
    assert cenario.gerados == []
    assert ("falhou", "Prova interrompida — nenhum PDF foi gerado.") in itens
    assert itens[-1] == ("fim", None)


def test_inter_com_conta_errada_vira_nao_lida(cenario, monkeypatch, tmp_path):
    from baixar_comprovantes import inter_saldo
    chamadas = []

    def ler_conta(apelido, numero, nomes, arquivo, *, razoes, log, avisar_qr, parar,
                  ao_entrar):
        assert parar() is False
        avisar_qr(apelido)
        chamadas.append((apelido, numero, nomes, arquivo, razoes))
        return inter_saldo.LidoInter(motivo="a tela do Inter está na conta 987654321 — "
                                            "outra conta aberta, não leio")
    monkeypatch.setattr(inter_saldo, "ler_conta", ler_conta)
    p = _prova(_tela(tmp_path, _Anx()))
    lidas = p._ler_bancos([BETA], tmp_path)
    assert chamadas == [("BETA", "123456789", ("EMPRESA FICTICIA",),
                         tmp_path / "09 banco.png", ())]
    assert ("qr", "BETA") in _fila(p)
    linha = ps.comparar(BETA, ps.Leitura(D("1.00"), AGORA), lidas[9])
    assert linha.situacao == ps.NAO_LIDA and "outra conta aberta" in linha.motivo


def test_parar_nao_espera_o_erp(tmp_path, monkeypatch):
    """Revisão de 27/10: parado, a thread ainda esperava o ERP até 600 s."""
    import time
    p = _prova(_tela(tmp_path, _Anx()))
    p._erp = concurrent.futures.Future()                 # o ERP nunca responde
    monkeypatch.setattr(m, "ESPERA_ERP", 6)
    threading.Timer(0.3, p._parar.set).start()
    comeco = time.monotonic()
    lidas = p._esperar_erp([ALFA, BETA])
    assert time.monotonic() - comeco < 3
    assert {k: v.motivo for k, v in lidas.items()} == {8: ps.PARADO, 9: ps.PARADO}


def test_erp_que_falha_com_timeout_proprio_nao_prende_a_espera(tmp_path, monkeypatch):
    import time
    p = _prova(_tela(tmp_path, _Anx()))
    p._erp = concurrent.futures.Future()
    p._erp.set_exception(TimeoutError("socket"))
    monkeypatch.setattr(m, "ESPERA_ERP", 6)
    comeco = time.monotonic()
    lidas = p._esperar_erp([ALFA])
    assert time.monotonic() - comeco < 3
    assert lidas[8].motivo == "TimeoutError: socket"


def test_rotulo_acompanha_cada_fase_e_qr_vencido_vai_ao_registro(tmp_path, monkeypatch):
    """Revisão de 27/10: o rótulo ficava em "Leia o QR da X" até o fim, e o
    QR que estourava o tempo não aparecia no Registro."""
    from baixar_comprovantes import inter_saldo
    from tela_do_dia import prova_sicoob

    def ler_com_prints(abrir, numeros, pasta, *, progresso, **k):
        progresso(0, 1)
        progresso(1, 1)
        return {}

    def ler_conta(apelido, numero, nomes, arquivo, *, avisar_qr, ao_entrar, **k):
        avisar_qr(apelido)
        return inter_saldo.LidoInter(motivo="passaram 300s e a tela do extrato não apareceu")
    monkeypatch.setattr(prova_sicoob, "ler_com_prints", ler_com_prints)
    monkeypatch.setattr(inter_saldo, "ler_conta", ler_conta)
    tela = _tela(tmp_path, _Anx())
    p = _prova(tela)
    p._ler_bancos([ALFA, BETA], tmp_path)
    itens = _fila(p)
    estados = [v for t, v in itens if t == "estado"]
    assert "Sicoob: lendo a conta 1 de 1…" in estados
    assert estados[-1] == "Inter BETA: não lido"
    registro = [v for t, v in itens if t == "log"]
    assert any("Inter BETA" in r and "passaram 300s" in r for r in registro)


def test_rotulo_no_fim_diz_erp_e_pdf(cenario, monkeypatch):
    _sim(monkeypatch)
    lido = ps.Leitura(D("10.00"), AGORA)
    p = _prova(_tela(cenario.tmp, _Anx(erp={8: lido, 9: lido})))
    monkeypatch.setattr(m.ProvaNaTela, "_ler_bancos", lambda self, contas, pasta: {})
    p.comecar()
    p._thread.join(5)
    estados = [v for t, v in _fila(p) if t == "estado"]
    assert estados[-1] == "Gerando o PDF…"
    assert p.lbl.estado["text"] == "Prova de saldos: lendo o ERP…"


def test_sicoob_que_falha_inteiro_vira_motivo_em_cada_conta(cenario, monkeypatch, tmp_path):
    from tela_do_dia import prova_sicoob

    def quebra(*a, **k):
        raise RuntimeError("ProcessSingleton: profile in use")
    monkeypatch.setattr(prova_sicoob, "ler_com_prints", quebra)
    p = _prova(_tela(tmp_path, _Anx()))
    lidas = p._ler_bancos([ALFA], tmp_path)
    assert lidas[8].saldo is None and "já está aberto" in lidas[8].motivo
    # Revisão de 27/10: na prova não há "Reler Sicoob" para clicar.
    assert "Reler Sicoob" not in lidas[8].motivo
    assert "tente de novo a Prova de saldos" in lidas[8].motivo


def test_drain_pronto_abre_a_pasta_com_o_pdf_selecionado_e_fim_religa(cenario, monkeypatch):
    tela = _tela(cenario.tmp, _Anx())
    p = _prova(tela)
    pdf = cenario.tmp / "x.pdf"
    comandos = []
    monkeypatch.setattr(m.subprocess, "Popen", lambda cmd, **k: comandos.append(cmd))
    p.q.put(("qr", "BETA"))
    p.q.put(("pronto", (pdf, "1 batem, 0 não batem, 0 não lidas")))
    p.q.put(("fim", None))
    p._drain()
    assert comandos == [f'explorer /select,"{pdf}"'] and tela.abertos == []
    assert p.b_prova.estado["state"] == "normal" and p.b_parar.estado["state"] == "disabled"
    assert any("leia o QR da BETA" in r for r in tela.registro)
    assert any(pdf.as_posix() in r for r in tela.registro)


def test_sem_explorer_abre_so_a_pasta(cenario, monkeypatch):
    tela = _tela(cenario.tmp, _Anx())
    p = _prova(tela)

    def quebra(cmd, **k):
        raise OSError("sem explorer")
    monkeypatch.setattr(m.subprocess, "Popen", quebra)
    p._abrir_com_o_pdf(cenario.tmp / "x.pdf")
    assert tela.abertos == [cenario.tmp]


def test_ocupado_e_ligar():
    p = _prova(NS())
    assert p.ocupado() is None
    p.ligar(False)
    assert p.b_prova.estado["state"] == "disabled"
    p._thread = NS(is_alive=lambda: True)
    assert p.ocupado() == m.OCUPADO
    p.ligar(True)
    assert p.b_prova.estado["state"] == "disabled"


def test_frame_conta_a_prova_como_dona_do_chrome_do_sicoob():
    from tela_do_dia import frame as f
    t = f.TelaDoDiaFrame.__new__(f.TelaDoDiaFrame)
    t.sicoob = NS(ocupado=lambda: None)
    t.agendamentos = NS(ocupado=lambda: None)
    t.prova = NS(ocupado=lambda: None)
    t.autenticar = NS(ocupado=lambda: None)
    assert t.sicoob_ocupado() is None
    t.prova = NS(ocupado=lambda: m.OCUPADO)
    assert t.sicoob_ocupado() == m.OCUPADO


def test_frame_cria_liga_e_fecha_a_prova():
    frame = (RAIZ / "tela_do_dia" / "frame.py").read_text(encoding="utf-8")
    assert "self.prova = ProvaNaTela(c1, tela=self)" in frame
    assert "self.prova.ligar(b.dia)" in frame and "self.prova.ligar(False)" in frame
    assert "self.prova.fechar()" in frame


def test_app_liga_a_prova_em_todas_as_pontas():
    app = (RAIZ / "comprovantes_app.py").read_text(encoding="utf-8")

    def trecho(chave):
        return app.split(chave, 1)[1].split("\n    #", 1)[0]
    propria = trecho("aba_dia.prova.outros_no_sicoob =")
    for quem in ("aba_ext.ocupado()", "baixar_comprovantes_no_sicoob(aba_bxc)",
                 "aba_dia.sicoob.ocupado()", "aba_dia.agendamentos.ocupado()",
                 "_remessa_conferindo()"):
        assert quem in propria, quem
    assert "aba_dia.prova.ocupado()" in trecho("aba_dia.sicoob.outros_no_sicoob =")
    assert "aba_dia.prova.ocupado()" in trecho("aba_dia.agendamentos.outros_no_sicoob =")
    assert "aba_bxc.inter_ocupado = aba_dia.prova.ocupado\n" in app
