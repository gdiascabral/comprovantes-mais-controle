# -*- coding: utf-8 -*-
"""A regra que diz o que fazer com cada documento do calendário.

Nomes INVENTADOS: o repositório é público.
"""
import json

import pytest

from guias import regras as mod


def _arquivo(tmp_path, dados):
    caminho = tmp_path / "guias_regras.json"
    caminho.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return caminho


def test_classifica_por_palavra_inteira_e_sem_acento(tmp_path):
    """"RET" não pode casar com "RETENCAO": casar por pedaço de palavra já
    produziu lançamento errado neste projeto (lote 1 x lote 10)."""
    caminho = _arquivo(tmp_path, {"versao": 1, "tipos": [
        {"nome": "regularizacao", "quando": {"desc_contem": ["RET"]},
         "acao": "criar", "categoria": "Taxa de abertura"},
    ]})
    r = mod.Regras.carregar(caminho)

    assert r.classificar("BOLETO RET 62 UNIDADES")["nome"] == "regularizacao"
    assert r.classificar("Guia de RETENCAO na fonte") is None


def test_classifica_ignorando_acento_e_caixa(tmp_path):
    caminho = _arquivo(tmp_path, {"versao": 1, "tipos": [
        {"nome": "honorario", "quando": {"desc_contem": ["HONORARIO"]},
         "acao": "alterar", "categoria": "Honorários"},
    ]})
    r = mod.Regras.carregar(caminho)

    assert r.classificar("Honorário contábil 09/2026")["acao"] == "alterar"


def test_arquivo_ausente_nao_quebra_e_nao_classifica_nada(tmp_path):
    """Primeiro mês: sem regra, tudo cai em "você decide" — e isso é o certo."""
    r = mod.Regras.carregar(tmp_path / "nao-existe.json")

    assert r.classificar("qualquer coisa") is None
    assert r.tipos == []


def test_versao_desconhecida_recusa_em_vez_de_adivinhar(tmp_path):
    caminho = _arquivo(tmp_path, {"versao": 99, "tipos": []})

    with pytest.raises(mod.RegraInvalida):
        mod.Regras.carregar(caminho)


def test_aprender_recorrencia_sobrevive_ao_disco(tmp_path):
    """O que o dono confirma uma vez não pode ser perguntado de novo."""
    caminho = _arquivo(tmp_path, {"versao": 1, "tipos": [
        {"nome": "honorario", "quando": {"desc_contem": ["HONORARIO"]},
         "acao": "alterar", "categoria": "Honorários"},
    ]})
    r = mod.Regras.carregar(caminho)

    r.aprender_recorrencia("honorario", "701", "tp-123", "obra-9")
    r.gravar()

    outra = mod.Regras.carregar(caminho)
    assert outra.recorrencia("honorario", "701") == {
        "trade_payable_id": "tp-123", "obra": "obra-9"}
    assert outra.recorrencia("honorario", "702") == {}


def test_nao_ha_conta_bancaria_em_regra_nenhuma(tmp_path):
    """Decisão do dono (21/09/2026): a conta vem da obra, nunca do cadastro."""
    caminho = _arquivo(tmp_path, {"versao": 1, "tipos": [
        {"nome": "honorario", "quando": {"desc_contem": ["HONORARIO"]},
         "acao": "alterar", "categoria": "Honorários", "conta": "alguma"},
    ]})

    with pytest.raises(mod.RegraInvalida) as e:
        mod.Regras.carregar(caminho)
    assert "conta" in str(e.value).lower()
