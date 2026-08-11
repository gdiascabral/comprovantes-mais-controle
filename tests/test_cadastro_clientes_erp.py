# -*- coding: utf-8 -*-
"""Gravar cliente do ERP → empresa no `contas_sicoob.json`.

A aba Contratos descobre o cliente de uma obra na hora de arquivar. Obrigar a
pessoa a editar JSON à mão para seguir era o caminho mais curto para o contrato
ir parar na pasta de outra empresa — e nada no disco denuncia isso depois.

Este arquivo cobre as duas travas que fazem a gravação valer: cliente que já é
de outra empresa não muda de dono em silêncio, e o cadastro do fechamento
inteiro não pode ficar pela metade.
"""
import json

import pytest

import sicoob_contas as sc

CADASTRO = {
    "raiz": "C:/Arquivos Morais/EXTRATOS",
    "_ajuda": ["esta linha existe para provar que o resto do arquivo sobrevive"],
    "empresas": [
        {"nome": "TERRA BELA",
         "pastas_vazias": ["CAIXA"],
         "contas": [{"numero": "12.345-6", "pasta": "SICOOB"}],
         "clientes_erp": ["TERRA BELA MORAIS ENGENHARIA SPE"]},
        {"nome": "MORAIS ENG",
         "pastas_vazias": [],
         "contas": [{"numero": "22.222-2", "pasta": "SICOOB"}]},
    ],
}


@pytest.fixture
def arquivo(tmp_path):
    caminho = tmp_path / "contas_sicoob.json"
    caminho.write_text(json.dumps(CADASTRO, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    return caminho


def lido(caminho) -> dict:
    return json.loads(caminho.read_text(encoding="utf-8"))


def test_grava_o_cliente_na_empresa(arquivo):
    sc.adicionar_cliente_erp("MORAIS ENG", "FULANO DE TAL DA SILVA",
                             arquivo)
    empresas = {e["nome"]: e for e in lido(arquivo)["empresas"]}
    assert empresas["MORAIS ENG"]["clientes_erp"] == [
        "FULANO DE TAL DA SILVA"]
    # e o mapa continua enxergando o que já existia
    assert empresas["TERRA BELA"]["clientes_erp"] == [
        "TERRA BELA MORAIS ENGENHARIA SPE"]


def test_o_resto_do_cadastro_sobrevive(arquivo):
    sc.adicionar_cliente_erp("TERRA BELA", "OUTRO CLIENTE", arquivo)
    dados = lido(arquivo)
    assert dados["raiz"] == CADASTRO["raiz"]
    assert dados["_ajuda"] == CADASTRO["_ajuda"]
    assert dados["empresas"][0]["contas"] == [{"numero": "12.345-6",
                                               "pasta": "SICOOB"}]
    assert dados["empresas"][0]["pastas_vazias"] == ["CAIXA"]


def test_gravar_duas_vezes_nao_duplica(arquivo):
    for _ in range(2):
        sc.adicionar_cliente_erp("MORAIS ENG", "CLIENTE REPETIDO", arquivo)
    empresas = {e["nome"]: e for e in lido(arquivo)["empresas"]}
    assert empresas["MORAIS ENG"]["clientes_erp"] == ["CLIENTE REPETIDO"]


def test_cliente_de_outra_empresa_nao_muda_de_dono_em_silencio(arquivo):
    """O mesmo defeito que o `validar()` denuncia: cliente em duas empresas
    manda o contrato para a pasta errada."""
    with pytest.raises(sc.MapaInvalido) as e:
        sc.adicionar_cliente_erp("MORAIS ENG",
                                 "terra bela morais engenharia spe", arquivo)
    assert "TERRA BELA" in str(e.value)
    assert lido(arquivo) == CADASTRO         # nada foi tocado


def test_empresa_que_nao_existe_e_recusada(arquivo):
    with pytest.raises(sc.MapaInvalido):
        sc.adicionar_cliente_erp("EMPRESA QUE NAO EXISTE", "FULANO", arquivo)
    assert lido(arquivo) == CADASTRO


def test_arquivo_ilegivel_vira_recado_e_nao_traceback(tmp_path):
    caminho = tmp_path / "contas_sicoob.json"
    caminho.write_text("{isto não é json", encoding="utf-8")
    with pytest.raises(sc.MapaInvalido):
        sc.adicionar_cliente_erp("TERRA BELA", "FULANO", caminho)


def test_o_cadastro_gravado_continua_carregando(arquivo):
    """A prova que interessa: depois de gravar, o mapa lido pelas outras abas
    é válido e já traz o cliente novo."""
    sc.adicionar_cliente_erp("MORAIS ENG", "FULANO DE TAL DA SILVA", arquivo)
    mapa = sc.carregar(arquivo)
    dona = next(e for e in mapa.empresas if "FULANO DE TAL DA SILVA" in e.clientes_erp)
    assert dona.nome == "MORAIS ENG"
    assert sc.validar(mapa) == []
