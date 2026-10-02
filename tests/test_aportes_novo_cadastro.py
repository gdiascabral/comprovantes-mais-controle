# -*- coding: utf-8 -*-
"""Regra do botão "Novo cadastro" da aba Aportes (`aportes/novo_cadastro.py`).

Nomes fictícios: o repositório é público."""
from __future__ import annotations

import csv

import pytest

from aportes import dados as cadastro
from aportes import novo_cadastro as nc
from aportes.novo_cadastro import Novo

CONTAS = [
    {"nome_erp": "Holding - SUBCONTA 111-1 - BANCO", "empresa_id": 7, "ativa": True},
    {"nome_erp": "Holding - SUBCONTA 222-2 - BANCO", "empresa_id": 7, "ativa": True},
    {"nome_erp": "Holding - SUBCONTA 333-3 - BANCO", "empresa_id": 7, "ativa": True},
    {"nome_erp": "OBRA NOVA SPE - BANCO", "empresa_id": 9, "ativa": True},
    {"nome_erp": "CONTA VELHA - BANCO", "empresa_id": 9, "ativa": False},
]
ENTIDADES = [
    {"nome_exibicao": "HOLDING SUB 111", "nome_oficial": "HOLDING SPE",
     "conta": "Holding - SUBCONTA 111-1 - BANCO"},
    {"nome_exibicao": "HOLDING SUB 222", "nome_oficial": "HOLDING SPE",
     "conta": "holding - subconta 222-2 - banco"},
    {"nome_exibicao": "FULANO (pessoa física)", "nome_oficial": "FULANO DE TAL",
     "conta": None},
]


def test_contas_livres_tira_as_ja_usadas_e_as_desativadas():
    # A 222-2 está usada com outra caixa: continua sendo a mesma conta.
    assert nc.contas_livres(CONTAS, ENTIDADES) == [
        "Holding - SUBCONTA 333-3 - BANCO", "OBRA NOVA SPE - BANCO"]


def test_nome_oficial_vem_das_outras_contas_da_mesma_empresa():
    assert nc.nome_oficial_sugerido(
        "Holding - SUBCONTA 333-3 - BANCO", CONTAS, ENTIDADES) == "HOLDING SPE"


def test_empresa_com_contatos_diferentes_nao_sugere_nenhum():
    # Mesma empresa do cadastro, dois contatos: escolher um poria o aporte
    # no contato da outra SPE.
    divergentes = ENTIDADES + [
        {"nome_exibicao": "HOLDING SUB 333 X", "nome_oficial": "OUTRA SPE",
         "conta": "Holding - SUBCONTA 333-3 - BANCO"}]
    contas = CONTAS + [{"nome_erp": "Holding - SUBCONTA 444-4 - BANCO",
                        "empresa_id": 7, "ativa": True}]
    assert nc.nome_oficial_sugerido("Holding - SUBCONTA 444-4 - BANCO",
                                    contas, divergentes) == ""


def test_empresa_sem_nenhuma_conta_na_lista_nao_inventa_nome():
    assert nc.nome_oficial_sugerido("OBRA NOVA SPE - BANCO",
                                    CONTAS, ENTIDADES) == ""
    assert nc.nome_oficial_sugerido("não existe", CONTAS, ENTIDADES) == ""


def test_valido_passa():
    assert nc.validar(Novo("OBRA NOVA - BANCO", "OBRA NOVA SPE LTDA",
                           "OBRA NOVA SPE - BANCO"), ENTIDADES) == ""
    # Pessoa física: sem conta.
    assert nc.validar(Novo("BELTRANO (pessoa física)", "BELTRANO"),
                      ENTIDADES) == ""


@pytest.mark.parametrize("novo, pedaco", [
    (Novo("", "X"), "Falta o nome"),
    (Novo("X", "  "), "Falta o nome do contato"),
    (Novo("holding  sub 111", "X"), "Já existe"),
    (Novo("OUTRO", "X", "HOLDING - SUBCONTA 111-1 - BANCO"), "já está na lista"),
    (Novo("A;B", "X"), "ponto e vírgula"),
    (Novo(cadastro.INVESTIDOR_PREFIXO + "9", "X"), "rateios"),
])
def test_invalido_diz_o_motivo(novo, pedaco):
    assert pedaco in nc.validar(novo, ENTIDADES)


def test_linha_vazio_vira_none_e_apara():
    assert Novo(" A ", " B ", "  ", "").linha() == {
        "nome_exibicao": "A", "nome_oficial": "B", "conta": None,
        "nome_descricao": None}


def test_gravar_vai_ao_banco_antes_do_cache(tmp_path, monkeypatch):
    from nuvem import rest
    arquivo = tmp_path / "contas.csv"
    monkeypatch.setattr(cadastro, "ARQUIVO_CONTAS", arquivo)
    ordem = []

    def inserir(tabela, token, linhas, **_kw):
        ordem.append(("banco", tabela, arquivo.exists()))
        return [dict(linhas[0], id=99)]

    monkeypatch.setattr(rest, "inserir", inserir)
    r = nc.gravar("tok", Novo("OBRA NOVA - BANCO", "OBRA NOVA SPE LTDA",
                              "OBRA NOVA SPE - BANCO"))
    assert ordem == [("banco", "entidade", False)]
    assert r["id"] == 99
    assert cadastro.carregar_contas()["OBRA NOVA - BANCO"]["conta"] == \
        "OBRA NOVA SPE - BANCO"


def test_banco_recusou_nao_toca_o_cache(tmp_path, monkeypatch):
    from nuvem import rest
    arquivo = tmp_path / "contas.csv"
    monkeypatch.setattr(cadastro, "ARQUIVO_CONTAS", arquivo)

    def inserir(*_a, **_kw):
        raise rest.RecusadoPeloBanco("sem permissão")

    monkeypatch.setattr(rest, "inserir", inserir)
    with pytest.raises(rest.RecusadoPeloBanco):
        nc.gravar("tok", Novo("A", "B"))
    assert not arquivo.exists()


def test_acrescentar_no_cache_existente_preserva_o_que_havia(tmp_path,
                                                            monkeypatch):
    arquivo = tmp_path / "contas.csv"
    # Do jeito que o `nuvem/cache.py` grava: BOM e \r\n.
    arquivo.write_bytes("﻿nome_exibicao;nome_oficial;conta;nome_descricao"
                        "\r\nVELHA;VELHA SPE;VELHA - BANCO;\r\n".encode("utf-8"))
    monkeypatch.setattr(cadastro, "ARQUIVO_CONTAS", arquivo)
    cadastro.acrescentar_conta("NOVA", "NOVA SPE", None)
    with open(arquivo, encoding="utf-8-sig", newline="") as f:
        nomes = [l["nome_exibicao"] for l in csv.DictReader(f, delimiter=";")]
    assert nomes == ["VELHA", "NOVA"]


# ------------------------------------------------- subconta de investidor
SUBCONTAS = {"222-2": {"obras": ["LOTE 1"], "investidores": ["INV"]}}


def test_contas_de_investidor_oferece_livres_e_as_que_ja_sao_subconta():
    # A 333-3 está livre; a 222-2 já está na lista e já tem rateio.
    entidades = ENTIDADES + [
        {"nome_exibicao": "SUB 222", "nome_oficial": "HOLDING SPE",
         "conta": "Holding - SUBCONTA 22222-2 - BANCO"}]
    contas = CONTAS + [{"nome_erp": "Holding - SUBCONTA 22222-2 - BANCO",
                        "empresa_id": 7, "ativa": True}]
    opcoes = nc.contas_de_investidor(contas, entidades, {"22222-2": {}})
    assert "Holding - SUBCONTA 22222-2 - BANCO" in opcoes
    assert "Holding - SUBCONTA 333-3 - BANCO" in opcoes


def test_banco_da_conta():
    contas = [{"nome_erp": "X - SUBCONTA 11111-1", "banco": "sicoob"}]
    assert nc.banco_da_conta("X - SUBCONTA 11111-1", contas) == "SICOOB"
    assert nc.banco_da_conta("Y - 11111-1 - INTER", []) == "INTER"
    assert nc.banco_da_conta("sem banco", []) == "SICOOB"


def _inv(**kw):
    base = dict(conta="Holding - SUBCONTA 44444-4 - BANCO", dono="HOLDING SPE",
                aportadores=["INV A"], obras=["LOTE 1"], pesos={})
    base.update(kw)
    return nc.Investidor(**base)


def test_investidor_nomes_automaticos():
    inv = _inv(banco="SICOOB")
    assert inv.numero == "44444-4"
    assert inv.em_pagou == "INVESTIDOR SUBCONTA 44444-4"
    assert inv.em_recebeu == "SUBCONTA 44444-4 - SICOOB - INVESTIDOR"


def test_validar_investidor():
    assert nc.validar_investidor(_inv(), ENTIDADES) == ""
    assert "número" in nc.validar_investidor(_inv(conta="CONTA SEM NUMERO"),
                                             ENTIDADES)
    assert "dono" in nc.validar_investidor(_inv(dono=""), ENTIDADES)
    assert "aportador" in nc.validar_investidor(_inv(aportadores=[]), ENTIDADES)
    assert "não existe" in nc.validar_investidor(
        _inv(), ENTIDADES, participantes=["OUTRO"], centros=["LOTE 1"])


def test_gravar_investidor_cria_recebeu_so_quando_falta(tmp_path, monkeypatch):
    from nuvem import rest
    from aportes import rateio_subconta
    monkeypatch.setattr(cadastro, "ARQUIVO_CONTAS", tmp_path / "contas.csv")
    inseridas, rateios = [], []
    monkeypatch.setattr(rest, "inserir",
                        lambda tabela, tok, linhas, **kw: inseridas.append(
                            (tabela, linhas[0])) or [linhas[0]])
    monkeypatch.setattr(rateio_subconta, "gravar",
                        lambda *a, **kw: rateios.append(a))
    assert nc.gravar_investidor("tok", _inv(), ENTIDADES) is True
    assert inseridas[0][0] == "entidade"
    assert inseridas[0][1]["nome_exibicao"] == "SUBCONTA 44444-4 - SICOOB - INVESTIDOR"
    assert rateios[0][1:] == ("44444-4", ["INV A"], ["LOTE 1"], {})
    # a conta já está em Recebeu: só o rateio
    inseridas.clear()
    ja = ENTIDADES + [{"nome_exibicao": "QUALQUER", "nome_oficial": "H",
                       "conta": "Holding - SUBCONTA 44444-4 - BANCO"}]
    assert nc.gravar_investidor("tok", _inv(), ja) is False
    assert inseridas == []


def test_numero_que_ja_e_de_outra_conta_e_recusado():
    ja = ENTIDADES + [{"nome_exibicao": "OUTRA", "nome_oficial": "H",
                       "conta": "OUTRO BANCO - 44444-4"}]
    assert "já é da conta" in nc.validar_investidor(_inv(), ja)


def test_dono_conferido_no_erp_quando_a_conta_e_nova():
    assert "não existe" in nc.validar_investidor(
        _inv(), ENTIDADES, participantes=["INV A"], centros=["LOTE 1"])
    assert nc.validar_investidor(
        _inv(), ENTIDADES, participantes=["INV A", "HOLDING SPE"],
        centros=["LOTE 1"]) == ""
