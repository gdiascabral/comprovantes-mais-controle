# -*- coding: utf-8 -*-
"""OFX do Inter de um período (aba Conciliação), pela sessão da página.
A página é dublê: aqui se prova que a conta é conferida ANTES de baixar,
que sem sessão nada é pedido e que o download vira arquivo. Números e
nomes fictícios."""
import datetime as dt
from contextlib import contextmanager
from pathlib import Path

from baixar_comprovantes import inter_ofx as m
from baixar_comprovantes import inter_saldo

INI, FIM = dt.date(2026, 10, 28), dt.date(2026, 10, 29)
TELA = "Saldo\nR$ 1,00\n123456789\nEMPRESA FICTICIA LTDA\nInício"
SESSAO = {"authorization": "Bearer x", "x-inter-conta-corrente": "1",
          "x-inter-organization": "2"}


def test_url_do_ofx():
    assert m.url_do_ofx(INI, FIM) == (m.URL_EXPORTAR + "?formato=OFX&data-inicio=28-10-2026"
                                      "&data-fim=29-10-2026")


class _Download:
    def __init__(self):
        self.salvo = None

    def save_as(self, caminho):
        Path(caminho).write_text("OFXHEADER:100", encoding="cp1252")
        self.salvo = caminho


class _Pag:
    def __init__(self, texto=TELA, resposta=None, baixa=True):
        self.texto, self.resposta, self.baixa = texto, resposta or {"status": 200}, baixa
        self.pedidos = []

    def evaluate(self, js, args=None):
        if args is None:
            return self.texto
        self.pedidos.append(args)
        return self.resposta

    @contextmanager
    def expect_download(self, timeout=None):
        espera = type("E", (), {})()
        yield espera
        if not self.baixa:
            raise TimeoutError("Timeout 60000ms exceeded while waiting for event \"download\"")
        espera.value = _Download()


def _baixar(pag, tmp_path, numero="123456789", sessao=SESSAO):
    return m._baixar_na_pagina(pag, dict(sessao), numero, ("EMPRESA FICTICIA",), (),
                               INI, FIM, tmp_path / "a.ofx")


def test_conta_certa_baixa_e_diz_o_numero_da_tela(tmp_path):
    pag = _Pag()
    r = _baixar(pag, tmp_path)
    assert r == m.OfxInter(tmp_path / "a.ofx", "123456789", "")
    assert (tmp_path / "a.ofx").exists()
    assert pag.pedidos == [[m.url_do_ofx(INI, FIM), SESSAO]]


def test_conta_errada_na_tela_nao_baixa(tmp_path):
    """29/10/2026: o QR lido com outra empresa no celular abriu outra conta."""
    pag = _Pag(texto=TELA.replace("123456789", "987654321"))
    r = _baixar(pag, tmp_path)
    assert r.arquivo is None and m.QR_DA_EMPRESA_CERTA in r.motivo
    assert pag.pedidos == []


def test_sem_numero_na_tela_nao_baixa(tmp_path):
    pag = _Pag(texto="Saldo\nR$ 1,00\nEMPRESA FICTICIA LTDA")
    r = _baixar(pag, tmp_path)
    assert r.arquivo is None and r.motivo == inter_saldo.SEM_NUMERO
    assert pag.pedidos == []


def test_sem_sessao_nada_e_pedido(tmp_path):
    pag = _Pag()
    r = _baixar(pag, tmp_path, sessao={})
    assert r.arquivo is None and r.motivo == m.SEM_SESSAO and pag.pedidos == []


def test_inter_que_recusa_diz_o_status(tmp_path):
    r = _baixar(_Pag(resposta={"status": 412}), tmp_path)
    assert r.arquivo is None and "HTTP 412" in r.motivo
    r = _baixar(_Pag(resposta={"status": 200, "semArquivo": True}), tmp_path)
    assert r.arquivo is None and r.motivo == m.SEM_ARQUIVO


def test_download_que_nao_chega(tmp_path):
    r = _baixar(_Pag(baixa=False), tmp_path)
    assert r.arquivo is None and r.motivo == m.NAO_ENTREGOU
