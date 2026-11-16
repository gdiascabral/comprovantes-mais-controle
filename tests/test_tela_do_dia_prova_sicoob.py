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


class _Loc:
    def __init__(self, pagina, sel):
        self.p, self.sel = pagina, sel

    first = property(lambda self: self)

    def filter(self, has_text):
        self.p.ordem.append(("filtro", self.sel, has_text))
        return self

    def wait_for(self, state, timeout):
        self.p.ordem.append(("espera", self.sel, state))


class _Home:
    def __init__(self):
        self.ordem = []

    def locator(self, sel):
        return _Loc(self, sel)

    def evaluate(self, js):
        self.ordem.append(("js", js))


def test_print_espera_o_carregando_e_empilha_cabecalho_e_card(monkeypatch, tmp_path):
    """Ao vivo em 27/10 o print saiu com o "carregando" escuro por cima e sem
    o saldo; medido em 29/10: cabeçalho + card "Saldo da conta"."""
    from PIL import Image
    pagina = _Home()
    _motor(monkeypatch, pagina)
    cores = {m.SEL_CABECALHO: ((400, 60), "red"), m.SEL_CARD_SALDO: ((300, 200), "blue")}
    monkeypatch.setattr(m.util, "recorte_da_tela",
                        lambda page, loc: (Image.new("RGB", *cores[loc.sel]), 0))
    monkeypatch.setattr(m.util, "fotografar", lambda alvo, arquivo: "não devia cair aqui")
    lida = _ler(tmp_path)["123456"]
    assert lida.imagem == tmp_path / "sicoob 123456.png" and lida.sem_imagem == ""
    assert pagina.ordem[0] == ("espera", m.SEL_CARREGANDO, "hidden")
    assert ("filtro", m.SEL_CARD_SALDO, m.TEXTO_DO_CARD) in pagina.ordem
    img = Image.open(lida.imagem)
    assert img.size == (400, 60 + 12 + 200)
    assert img.getpixel((5, 5)) == (255, 0, 0) and img.getpixel((5, 100)) == (0, 0, 255)


def test_sem_o_card_cai_no_print_da_tela(monkeypatch, tmp_path):
    pagina = _Home()
    _motor(monkeypatch, pagina)
    monkeypatch.setattr(m.util, "recorte_da_tela", lambda page, loc: None)
    fotos = []
    monkeypatch.setattr(m.util, "fotografar", lambda alvo, arquivo: fotos.append(alvo) or "")
    assert _ler(tmp_path)["123456"].imagem == tmp_path / "sicoob 123456.png"
    assert fotos == [pagina]


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
