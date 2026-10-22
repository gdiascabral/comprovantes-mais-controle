# tests/test_tela_do_dia_controle_nuvem.py
# -*- coding: utf-8 -*-
"""Controle de aportes na nuvem (`tela_do_dia/controle_nuvem.py`). Dublê do
`nuvem.rest`; nomes fictícios."""
import datetime
from decimal import Decimal
from urllib.parse import unquote

import pytest

from tela_do_dia import controle_aportes as ca
from tela_do_dia import controle_nuvem as cn

D = Decimal
ABRE, HOJE = datetime.date(2026, 10, 21), datetime.date(2026, 10, 23)
ALFA, BETA = "FULANO ALFA DA SILVA", "FULANO BETA SOUZA"


class Banco:
    def __init__(self):
        self.t = {cn.CONTAS: [], cn.APORTADORES: [], cn.APONTAMENTOS: []}
        self.ordem, self._id = [], 0

    @staticmethod
    def _casa(linha, filtro):
        for parte in filter(None, filtro.split("&")):
            campo, _, cond = parte.partition("=")
            op, _, valor = cond.partition(".")
            valor = unquote(valor)
            if op == "eq" and str(linha.get(campo)) != valor:
                return False
            if op == "in" and str(linha.get(campo)) not in valor.strip("()").split(","):
                return False
        return True

    def ler(self, tabela, _tok, colunas="*", filtro=""):
        return [dict(l) for l in self.t[tabela] if self._casa(l, filtro)]

    def inserir(self, tabela, _tok, linhas, devolver=True):
        self.ordem.append(f"inserir {tabela}")
        saida = []
        for l in linhas:
            self._id += 1
            nova = dict(l, id=self._id)
            self.t[tabela].append(nova)
            saida.append(dict(nova))
        return saida

    def alterar(self, tabela, _tok, filtro, mudancas):
        self.ordem.append(f"alterar {tabela}")
        for l in self.t[tabela]:
            if self._casa(l, filtro):
                l.update(mudancas)
        return []

    def apagar(self, tabela, _tok, filtro):
        self.ordem.append(f"apagar {tabela}")
        self.t[tabela] = [l for l in self.t[tabela] if not self._casa(l, filtro)]


@pytest.fixture
def banco(monkeypatch):
    from nuvem import rest
    b = Banco()
    for nome in ("ler", "inserir", "alterar", "apagar"):
        monkeypatch.setattr(rest, nome, getattr(b, nome))
    return b


def _conta(**kw):
    base = dict(conta_erp="CONTA MAE - BANCO", abertura=ABRE, aportadores=(
        ca.Aportador(ALFA, D(1), D("50000.00")), ca.Aportador(BETA, D(1), D("0.00"))))
    base.update(kw)
    return ca.ContaControlada(**base)


def _salva():
    """Conta já gravada (id 7) com o aportador de id 3."""
    return ca.ContaControlada("CONTA MAE - BANCO", ABRE, id=7, aportadores=(
        ca.Aportador(ALFA, D(1), D("0.00"), id=3), ca.Aportador(BETA, D(1), id=4)))


def test_grava_conta_nova_com_numero_em_texto_e_le_de_volta(banco):
    anotado = []
    cn.gravar_conta("tok", _conta(), HOJE, anotar=lambda a, d: anotado.append(a))
    assert banco.t[cn.CONTAS][0]["abertura"] == "2026-10-21"
    assert {(l["nome_erp"], l["peso"], l["abertura"]) for l in banco.t[cn.APORTADORES]} == \
        {(ALFA, "1", "50000.00"), (BETA, "1", "0.00")}
    contas, apont = cn.ler("tok")
    assert contas[0].aportadores[0].abertura == D("50000.00") and apont == {}
    assert anotado and "Controle de aportes" in anotado[0]


def test_editar_muda_so_o_que_mudou_e_insere_antes_de_apagar(banco):
    cn.gravar_conta("tok", _conta(), HOJE, anotar=lambda *a: None)
    salva = cn.ler("tok")[0][0]
    banco.ordem.clear()
    nova = ca.ContaControlada(salva.conta_erp, ABRE, id=salva.id, aportadores=(
        ca.Aportador(ALFA, D(1), D("40000.00")), ca.Aportador("CICLANO GAMA", D(1))))
    cn.gravar_conta("tok", nova, HOJE, [salva], anotar=lambda *a: None)
    assert banco.ordem == [f"alterar {cn.CONTAS}", f"inserir {cn.APORTADORES}",
                           f"alterar {cn.APORTADORES}", f"apagar {cn.APORTADORES}"]
    assert {l["nome_erp"] for l in banco.t[cn.APORTADORES]} == {ALFA, "CICLANO GAMA"}


def test_nao_tira_aportador_com_apontamento_e_nao_escreve_nada(banco):
    cn.gravar_conta("tok", _conta(), HOJE, anotar=lambda *a: None)
    salva = cn.ler("tok")[0][0]
    beta = salva.aportadores[1]
    cn.apontar("tok", salva, ca.Recebimento("r1", HOJE, D("10.00"), "X"), beta.id, "pix",
               anotar=lambda *a: None)
    banco.ordem.clear()
    sem_beta = ca.ContaControlada(salva.conta_erp, ABRE, (salva.aportadores[0],), id=salva.id)
    with pytest.raises(ValueError, match=BETA):
        cn.gravar_conta("tok", sem_beta, HOJE, [salva], anotar=lambda *a: None)
    assert banco.ordem == []


def test_conta_com_problema_nao_toca_no_banco(banco):
    with pytest.raises(ValueError):
        cn.gravar_conta("tok", _conta(aportadores=()), HOJE, anotar=lambda *a: None)
    assert banco.ordem == []


def test_apontar_insere_e_depois_corrige_o_mesmo_recebimento(banco):
    rec = ca.Recebimento("r/1", HOJE, D("10.00"), "X")
    cn.apontar("tok", _salva(), rec, 3, "pix", anotar=lambda *a: None)
    cn.apontar("tok", _salva(), rec, None, "devolução", anotar=lambda *a: None)
    linhas = banco.t[cn.APONTAMENTOS]
    assert len(linhas) == 1 and linhas[0]["aportador_id"] is None
    assert linhas[0]["valor"] == "10.00" and linhas[0]["recebimento_erp"] == "r/1"
    _c, apont = cn.ler("tok")
    assert apont[7][0].motivo == "devolução"
    cn.desfazer("tok", apont[7][0].id, anotar=lambda *a: None)
    assert banco.t[cn.APONTAMENTOS] == []


def test_apontar_sem_motivo_recusa(banco):
    with pytest.raises(ValueError, match="motivo"):
        cn.apontar("tok", _salva(), ca.Recebimento("r1", HOJE, D("10.00"), "X"), 3, "  ",
                   anotar=lambda *a: None)


def test_apontar_aportador_de_outra_conta_recusa_antes_de_gravar(banco):
    rec = ca.Recebimento("r1", HOJE, D("10.00"), "X")
    with pytest.raises(ValueError, match="não é desta conta"):
        cn.apontar("tok", _salva(), rec, 99, "pix", anotar=lambda *a: None)
    assert banco.ordem == [] and banco.t[cn.APONTAMENTOS] == []


def test_apontar_em_conta_nao_gravada_recusa(banco):
    sem_id = ca.ContaControlada("CONTA MAE - BANCO", ABRE, (ca.Aportador(ALFA, D(1), id=3),))
    with pytest.raises(ValueError, match="gravada"):
        cn.apontar("tok", sem_id, ca.Recebimento("r1", HOJE, D("10.00"), "X"), 3, "pix",
                   anotar=lambda *a: None)
    assert banco.ordem == []


def test_apontar_nao_exige_a_coluna_de_autor(banco):
    cn.apontar("tok", _salva(), ca.Recebimento("r1", HOJE, D("10.00"), "X"), 3, "pix",
               anotar=lambda *a: None)
    assert "alterado_por" not in banco.t[cn.APONTAMENTOS][0]
