# -*- coding: utf-8 -*-
"""Sicoob com print na Prova de saldos. O motor do saldo é dublê: aqui se
prova que cada conta lida ganha o SEU print, e que o print que falha não
apaga o saldo. Contas fictícias."""
import datetime as dt
from decimal import Decimal as D

from extratos_sicoob import saldo
from tela_do_dia import prova_sicoob as m

AGORA = dt.datetime(2026, 10, 27, 14, 5)


def _motor(monkeypatch, pagina):
    def falso(abrir, numeros, *, perguntar, agora, parar, log, progresso, ao_ler):
        ao_ler(pagina, "12.345-6")
        return [saldo.Lido("12.345-6", D("5.00"), AGORA),
                saldo.Lido("23.456-7", motivo=saldo.FORA_DESTE_LOGIN)]
    monkeypatch.setattr(saldo, "ler_em_dois_acessos", falso)


def _ler(tmp_path):
    return m.ler_com_prints(lambda: None, ["12.345-6", "23.456-7"], tmp_path,
                            perguntar=lambda faltam: False, parar=lambda: False,
                            log=lambda s: None)


def test_cada_conta_lida_ganha_o_seu_print(monkeypatch, tmp_path):
    pagina = object()
    _motor(monkeypatch, pagina)
    fotos = []
    monkeypatch.setattr(m.util, "fotografar",
                        lambda alvo, arquivo: fotos.append((alvo, arquivo)) or "")
    lidas = _ler(tmp_path)
    assert lidas["123456"].saldo == D("5.00") and lidas["123456"].lido_em == AGORA
    assert lidas["123456"].imagem == tmp_path / "sicoob 123456.png"
    assert fotos == [(pagina, tmp_path / "sicoob 123456.png")]
    nao = lidas["234567"]
    assert nao.saldo is None and nao.motivo == saldo.FORA_DESTE_LOGIN
    assert nao.imagem is None and nao.sem_imagem


def test_print_que_falha_mantem_o_saldo(monkeypatch, tmp_path):
    _motor(monkeypatch, object())
    monkeypatch.setattr(m.util, "fotografar", lambda alvo, arquivo: "o print não saiu (x)")
    lida = _ler(tmp_path)["123456"]
    assert lida.saldo == D("5.00") and lida.imagem is None
    assert lida.sem_imagem == "o print não saiu (x)"


def test_seletor_da_area_do_saldo_fotografa_so_ela(monkeypatch, tmp_path):
    class _Area:
        first = property(lambda self: self)
        def count(self): return 1

    area = _Area()
    pagina = type("P", (), {"locator": lambda self, sel: area})()
    _motor(monkeypatch, pagina)
    monkeypatch.setattr(m, "SELETOR_AREA_SALDO", "#saldo")
    fotos = []
    monkeypatch.setattr(m.util, "fotografar", lambda alvo, arquivo: fotos.append(alvo) or "")
    _ler(tmp_path)
    assert fotos == [area]


def test_gancho_do_olho_clica_antes_do_print(monkeypatch, tmp_path):
    """Medir ao vivo (Tarefa 8): se o saldo vier mascarado, o seletor do botão
    'mostrar saldo' entra em SELETOR_MOSTRAR_SALDO; vazio = não clica."""
    pagina = object()
    _motor(monkeypatch, pagina)
    ordem = []
    monkeypatch.setattr(m, "SELETOR_MOSTRAR_SALDO", "#olho")
    monkeypatch.setattr(m.util, "revelar", lambda page, sel: ordem.append(("olho", sel)))
    monkeypatch.setattr(m.util, "fotografar", lambda alvo, arquivo: ordem.append("foto") or "")
    _ler(tmp_path)
    assert ordem == [("olho", "#olho"), "foto"]
