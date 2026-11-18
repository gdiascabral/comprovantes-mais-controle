# -*- coding: utf-8 -*-
"""Baixa pelo arquivo do HTML das PF: conferência e trava contra baixa repetida.
Nomes fictícios: o repositório é público."""
import datetime as dt
import json
from decimal import Decimal

import pytest

from pagamentos_dia import baixa_pelo_arquivo as bpa

HOJE = dt.date(2026, 11, 18)
CONTA = {"id": "c1", "name": "FULANO - BANCO X", "openingBalanceDate": "2026-10-01T00:00:00"}
OUTRA = {"id": "c2", "name": "BELTRANO - BANCO X", "openingBalanceDate": "2026-07-01"}


def _item(lid="L1", valor="100.00", conta="FULANO - BANCO X", conta_id="c1",
          data="2026-11-18", parte=""):
    return {"lancamento_id": lid, "parte": parte, "titulo_id": "T" + lid,
            "fornecedor": "Fornecedor Alfa", "valor": valor, "vencimento": "2026-11-18",
            "conta": conta, "conta_id": conta_id, "data_pagamento": data}


def _arquivo(*itens):
    return json.dumps({"gerado_em": "x", "html": "y.html", "baixas": list(itens)})


class ErpFalso:
    """GET do título / default-paid e POST da baixa, com registro do que veio."""

    def __init__(self, titulos):
        self.titulos = titulos           # {lid: dict}
        self.posts = []
        self.falhar_post = None          # Exception a levantar no POST
        self.post_entra_mesmo_assim = False
        self.falhar_releitura = False

    def __call__(self, url, metodo="GET", corpo=None):
        lid = url.split("/payable-installments/")[1].split("/")[0].split("?")[0]
        if metodo == "POST":
            self.posts.append((lid, corpo))
            if self.post_entra_mesmo_assim:
                self.titulos[lid] = {**self.titulos[lid], "paid": True,
                                     "paids": [{"id": "P-" + lid}]}
            if self.falhar_post:
                if self.falhar_releitura:
                    self.titulos = None
                raise self.falhar_post
            self.titulos[lid] = {**self.titulos[lid], "paid": True,
                                 "paids": [{"id": "P-" + lid}], "remainingValue": 0}
            return {"id": "P-" + lid}
        if self.titulos is None:
            raise RuntimeError("aba caiu")
        if url.endswith("/default-paid"):
            return {"account": {"id": "outra"}, "payingDate": "2026-01-01",
                    "documentNumber": "", "paymentMethod": "PIX"}
        if lid not in self.titulos:
            raise RuntimeError("404")
        return self.titulos[lid]


def _aberto(valor=100.0):
    return {"paid": False, "paids": [], "remainingValue": valor}


@pytest.fixture
def registro(tmp_path):
    return bpa.Registro(tmp_path / bpa.ARQ_REGISTRO)


def _conferir(erp, texto, registro, contas=(CONTA, OUTRA)):
    return bpa.conferir(erp, bpa.ler_arquivo(texto), list(contas), registro, hoje=HOJE)


def _agora():
    return "2026-11-18 22:00"


# ------------------------------------------------------------------ arquivo

def test_le_o_arquivo_do_html():
    itens = bpa.ler_arquivo(_arquivo(_item()))
    assert itens[0].valor == Decimal("100.00")
    assert itens[0].data == HOJE
    assert itens[0].conta_id == "c1"


@pytest.mark.parametrize("texto", ["não é json", "[]", json.dumps({"baixas": []}),
                                   json.dumps({"outra": 1}), json.dumps({"baixas": [1]})])
def test_arquivo_que_nao_e_o_do_html_e_recusado(texto):
    with pytest.raises(ValueError):
        bpa.ler_arquivo(texto)


# ------------------------------------------------------------------ conferir

def test_tudo_certo_e_apto(registro):
    erp = ErpFalso({"L1": _aberto()})
    [c] = _conferir(erp, _arquivo(_item()), registro)
    assert c.apto and c.em_aberto == Decimal("100.00")


def test_ja_pago_no_erp_fica_vermelho(registro):
    erp = ErpFalso({"L1": {"paid": False, "paids": [{"id": "x"}], "remainingValue": 0}})
    [c] = _conferir(erp, _arquivo(_item()), registro)
    assert c.motivo == bpa.M_JA_PAGO


def test_valor_em_aberto_diferente_fica_vermelho(registro):
    erp = ErpFalso({"L1": _aberto(100.01)})
    [c] = _conferir(erp, _arquivo(_item()), registro)
    assert "em aberto no ERP R$ 100,01" in c.motivo


def test_sem_valor_em_aberto_nao_adivinha(registro):
    erp = ErpFalso({"L1": {"paid": False, "paids": []}})
    [c] = _conferir(erp, _arquivo(_item()), registro)
    assert c.motivo == bpa.M_SEM_EM_ABERTO


def test_conta_inexistente_ou_com_outro_nome(registro):
    erp = ErpFalso({"L1": _aberto(), "L2": _aberto()})
    c1, c2 = _conferir(erp, _arquivo(_item(conta_id="zz"),
                                     _item("L2", conta="OUTRO NOME")), registro)
    assert "não está entre as contas ativas" in c1.motivo
    assert "tem outro nome no ERP" in c2.motivo


def test_repetido_no_arquivo_fica_vermelho_nas_duas(registro):
    erp = ErpFalso({"L1": _aberto()})
    cs = _conferir(erp, _arquivo(_item(), _item()), registro)
    assert [c.motivo for c in cs] == [bpa.M_REPETIDO] * 2


def test_dividido_nunca_e_automatico(registro):
    erp = ErpFalso({"L1": _aberto()})
    [c] = _conferir(erp, _arquivo(_item(parte="1/2")), registro)
    assert "dividido" in c.motivo


@pytest.mark.parametrize("valor", ["0", "-5", "abc", "", "10.005"])
def test_valor_invalido(registro, valor):
    erp = ErpFalso({"L1": _aberto()})
    [c] = _conferir(erp, _arquivo(_item(valor=valor)), registro)
    assert "valor inválido" in c.motivo


def test_data_invalida_ou_futura(registro):
    erp = ErpFalso({"L1": _aberto(), "L2": _aberto()})
    c1, c2 = _conferir(erp, _arquivo(_item(data="18/11/2026"),
                                     _item("L2", data="2026-11-19")), registro)
    assert "inválida" in c1.motivo and "futuro" in c2.motivo


def test_titulo_que_nao_se_le_fica_vermelho(registro):
    erp = ErpFalso({})
    [c] = _conferir(erp, _arquivo(_item()), registro)
    assert "não consegui ler" in c.motivo


def test_conferir_nao_escreve_no_erp(registro):
    erp = ErpFalso({"L1": _aberto()})
    _conferir(erp, _arquivo(_item()), registro)
    assert erp.posts == []


# ------------------------------------------------------------------ baixar

def _baixar(erp, conferidos, registro, contas=(CONTA, OUTRA)):
    return bpa.baixar(erp, conferidos, list(contas), registro, agora=_agora, log=lambda *_: None)


def test_baixa_com_conta_data_e_valor_do_arquivo(registro):
    erp = ErpFalso({"L1": _aberto()})
    cs = _conferir(erp, _arquivo(_item()), registro)
    r = _baixar(erp, cs, registro)
    assert r.ok == 1 and not r.parou
    [(lid, corpo)] = erp.posts
    assert corpo["account"] == {"id": "c1", "name": "FULANO - BANCO X",
                                "openingBalanceDate": "2026-10-01"}
    assert corpo["payingDate"] == "2026-11-18"
    assert corpo["value"] == corpo["paidValue"] == 100.0
    assert registro.de("L1")["estado"] == "ok"
    assert registro.de("L1")["paid_id"] == "P-L1"


def test_o_mesmo_arquivo_duas_vezes_nao_baixa_de_novo(tmp_path):
    caminho = tmp_path / bpa.ARQ_REGISTRO
    erp = ErpFalso({"L1": _aberto()})
    reg = bpa.Registro(caminho)
    _baixar(erp, _conferir(erp, _arquivo(_item()), reg), reg)
    # app reaberto: o registro vem do disco; o ERP "esqueceu" a baixa
    erp.titulos["L1"] = _aberto()
    reg2 = bpa.Registro(caminho)
    [c] = _conferir(erp, _arquivo(_item()), reg2)
    assert "já baixado por este app" in c.motivo
    assert _baixar(erp, [c], reg2).ok == 0
    assert len(erp.posts) == 1


def test_baixado_por_outro_entre_conferir_e_baixar_nao_posta(registro):
    erp = ErpFalso({"L1": _aberto()})
    cs = _conferir(erp, _arquivo(_item()), registro)
    erp.titulos["L1"] = {"paid": True, "paids": [{"id": "x"}], "remainingValue": 0}
    r = _baixar(erp, cs, registro)
    assert r.ok == 0 and erp.posts == []
    assert r.resultados[0].recado == bpa.M_JA_PAGO


def test_so_baixa_os_aptos(registro):
    erp = ErpFalso({"L1": _aberto(), "L2": _aberto(5)})
    cs = _conferir(erp, _arquivo(_item(), _item("L2")), registro)
    _baixar(erp, cs, registro)
    assert [lid for lid, _ in erp.posts] == ["L1"]


def test_post_com_erro_que_entrou_conta_como_baixa_e_nao_repete(registro):
    erp = ErpFalso({"L1": _aberto()})
    erp.falhar_post = RuntimeError("prazo")
    erp.post_entra_mesmo_assim = True
    cs = _conferir(erp, _arquivo(_item()), registro)
    r = _baixar(erp, cs, registro)
    assert r.ok == 1 and len(erp.posts) == 1
    assert registro.de("L1")["estado"] == "ok"


def test_post_recusado_sem_baixa_nao_tenta_de_novo_e_limpa_o_registro(registro):
    erp = ErpFalso({"L1": _aberto(), "L2": _aberto()})
    erp.falhar_post = RuntimeError("o ERP respondeu 400")
    cs = _conferir(erp, _arquivo(_item(), _item("L2")), registro)
    r = _baixar(erp, cs, registro)
    assert r.ok == 0 and not r.parou
    assert [lid for lid, _ in erp.posts] == ["L1", "L2"]      # um POST por item
    assert registro.de("L1") is None


def test_incerto_para_a_rodada_e_fica_vermelho_na_proxima(tmp_path):
    caminho = tmp_path / bpa.ARQ_REGISTRO
    erp = ErpFalso({"L1": _aberto(), "L2": _aberto()})
    erp.falhar_post = RuntimeError("prazo")
    erp.falhar_releitura = True
    reg = bpa.Registro(caminho)
    cs = _conferir(erp, _arquivo(_item(), _item("L2")), reg)
    r = _baixar(erp, cs, reg)
    assert r.parou and r.resultados[0].incerto
    assert len(erp.posts) == 1                                 # L2 não foi tentado
    assert bpa.Registro(caminho).de("L1")["estado"] == "em_andamento"
    # próxima carga: ERP de volta, sem baixa → vermelho "confira"
    erp2 = ErpFalso({"L1": _aberto(), "L2": _aberto()})
    c1, c2 = _conferir(erp2, _arquivo(_item(), _item("L2")), bpa.Registro(caminho))
    assert c1.motivo == bpa.M_INCERTO and c2.apto


def test_cancelar_para_antes_do_proximo(registro):
    erp = ErpFalso({"L1": _aberto(), "L2": _aberto()})
    cs = _conferir(erp, _arquivo(_item(), _item("L2")), registro)
    r = bpa.baixar(erp, cs, [CONTA], registro, agora=_agora, log=lambda *_: None,
                   cancelar=lambda: len(erp.posts) >= 1)
    assert r.ok == 1 and len(erp.posts) == 1


def test_registro_estragado_levanta(tmp_path):
    (tmp_path / bpa.ARQ_REGISTRO).write_text("{quebrado", encoding="utf-8")
    with pytest.raises(ValueError):
        bpa.Registro(tmp_path / bpa.ARQ_REGISTRO)


# ------------------------------------------------------- revisão de dinheiro

def test_pago_em_parte_pelo_sum_of_paid_values_fica_vermelho(registro):
    erp = ErpFalso({"L1": {"paid": False, "paids": [], "remainingValue": 100.0,
                           "sumOfPaidValues": 50.0}})
    [c] = _conferir(erp, _arquivo(_item()), registro)
    assert c.motivo == bpa.M_JA_PAGO


def test_data_antiga_demais_ou_antes_da_abertura(registro):
    erp = ErpFalso({"L1": _aberto(), "L2": _aberto()})
    c1, c2 = _conferir(erp, _arquivo(_item(data="2025-11-18"),
                                     _item("L2", data="2026-09-30")), registro)
    assert "antiga demais" in c1.motivo
    assert "antiga demais" in c2.motivo or "abertura" in c2.motivo
    conta_nova = {**CONTA, "openingBalanceDate": "2026-11-10"}
    [c3] = _conferir(ErpFalso({"L1": _aberto()}), _arquivo(_item(data="2026-11-09")),
                     registro, contas=(conta_nova,))
    assert "abertura da conta" in c3.motivo


def test_200_que_nao_fecha_o_titulo_nao_e_ok_e_nao_repete(registro):
    erp = ErpFalso({"L1": _aberto()})
    cs = _conferir(erp, _arquivo(_item()), registro)
    original = erp.__call__

    def pedir(url, metodo="GET", corpo=None):
        r = original(url, metodo, corpo)
        if metodo == "POST":                     # gravou R$ 0,00: segue em aberto
            erp.titulos["L1"] = {"paid": False, "paids": [{"id": "P-L1"}],
                                 "remainingValue": 100.0}
        return r
    r = bpa.baixar(pedir, cs, [CONTA], registro, agora=_agora, log=lambda *_: None)
    assert r.ok == 0 and "em aberto" in r.resultados[0].recado
    assert registro.de("L1")["estado"] == "ok"          # nunca repete o POST
    assert len(erp.posts) == 1


def test_registro_que_nao_grava_depois_do_post_nao_derruba_a_rodada(registro, monkeypatch):
    erp = ErpFalso({"L1": _aberto(), "L2": _aberto()})
    cs = _conferir(erp, _arquivo(_item(), _item("L2")), registro)
    real = registro.anotar

    def anotar(item, estado, agora, **extra):
        if estado == "ok":
            raise OSError("disco")
        return real(item, estado, agora, **extra)
    monkeypatch.setattr(registro, "anotar", anotar)
    r = _baixar(erp, cs, registro)
    assert r.ok == 2 and len(erp.posts) == 2
    assert registro.de("L1")["estado"] == "em_andamento"


def test_conta_que_sumiu_entre_conferir_e_baixar_nao_baixa(registro):
    erp = ErpFalso({"L1": _aberto()})
    cs = _conferir(erp, _arquivo(_item()), registro)
    r = _baixar(erp, cs, registro, contas=(OUTRA,))
    assert r.ok == 0 and erp.posts == []
