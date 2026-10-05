# -*- coding: utf-8 -*-
"""A escolha da aba Contratos ("este cliente do ERP é desta empresa") tem de
ir para a NUVEM, não só para o `contas_sicoob.json`.

O arquivo é cache: `nuvem.cadastro.sincronizar` o regrava inteiro na abertura
a partir da tabela `cliente_erp`. Gravar só nele fazia a escolha sumir na
abertura seguinte, e a casa voltava a pedir resolução no mês seguinte.

Mesmo molde do "Novo cadastro" dos Aportes: banco primeiro, cache depois —
banco recusou, cache intocado.
"""
import json

import pytest

from nuvem import cadastro, clientes_erp, rest

EMPRESAS = [{"id": 1, "nome_pasta": "TERRA BELA"},
            {"id": 2, "nome_pasta": "MORAIS ENG"}]
CLIENTES = [{"empresa_id": 1, "nome": "TERRA BELA MORAIS ENGENHARIA SPE"}]


@pytest.fixture
def arquivo(tmp_path):
    caminho = tmp_path / "contas_sicoob.json"
    caminho.write_text(json.dumps({"raiz": "X", "empresas": [
        {"nome": "TERRA BELA", "pastas_vazias": [], "contas": [],
         "clientes_erp": ["TERRA BELA MORAIS ENGENHARIA SPE"]},
        {"nome": "MORAIS ENG", "pastas_vazias": [], "contas": []},
    ]}, ensure_ascii=False), encoding="utf-8")
    return caminho


@pytest.fixture
def banco(monkeypatch):
    """Banco de mentira: `ler` devolve cópias, `inserir` anota e devolve."""
    estado = {"empresa": [dict(e) for e in EMPRESAS],
              "cliente_erp": [dict(c) for c in CLIENTES],
              "inseridos": []}

    def ler(tabela, token, **_):
        return [dict(l) for l in estado[tabela]]

    def inserir(tabela, token, linhas, **_):
        assert tabela == "cliente_erp"
        estado["inseridos"].extend(linhas)
        estado["cliente_erp"].extend(linhas)
        return linhas

    monkeypatch.setattr(rest, "ler", ler)
    monkeypatch.setattr(rest, "inserir", inserir)
    return estado


def clientes_no_cache(caminho, empresa):
    for e in json.loads(caminho.read_text(encoding="utf-8"))["empresas"]:
        if e["nome"] == empresa:
            return e.get("clientes_erp") or []
    raise AssertionError(empresa)


def test_grava_na_nuvem_com_o_id_da_empresa_e_depois_no_cache(banco, arquivo):
    clientes_erp.gravar("tok", "MORAIS ENG", "FULANO", caminho=arquivo)
    assert banco["inseridos"] == [{"empresa_id": 2, "nome": "FULANO"}]
    assert clientes_no_cache(arquivo, "MORAIS ENG") == ["FULANO"]


def test_a_escolha_sobrevive_a_proxima_abertura(banco, arquivo, monkeypatch):
    """O defeito em si: depois de gravar, a sincronização da abertura seguinte
    remonta o arquivo a partir do banco — e o cliente tem de continuar lá."""
    clientes_erp.gravar("tok", "MORAIS ENG", "FULANO", caminho=arquivo)
    dados = {"empresa": [dict(e, cnpj="", razao_social="", convenio="",
                              vip_id="") for e in banco["empresa"]],
             "conta": [], "pasta_vazia": [],
             "cliente_erp": banco["cliente_erp"], "config": {}}
    remontado = cadastro._contas_sicoob(dados)
    por_nome = {e["nome"]: e["clientes_erp"] for e in remontado["empresas"]}
    assert por_nome["MORAIS ENG"] == ["FULANO"]


def test_banco_recusou_nao_toca_o_cache(banco, arquivo, monkeypatch):
    antes = arquivo.read_text(encoding="utf-8")

    def recusa(*a, **k):
        raise rest.RecusadoPeloBanco("HTTP 403: sem permissão")

    monkeypatch.setattr(rest, "inserir", recusa)
    with pytest.raises(rest.RecusadoPeloBanco):
        clientes_erp.gravar("tok", "MORAIS ENG", "FULANO", caminho=arquivo)
    assert arquivo.read_text(encoding="utf-8") == antes


def test_cliente_de_outra_empresa_nao_muda_de_dono(banco, arquivo):
    """A comparação ignora caixa, acento e espaço — a mesma do cache."""
    with pytest.raises(clientes_erp.sicoob_contas.MapaInvalido,
                       match="TERRA BELA"):
        clientes_erp.gravar("tok", "MORAIS ENG",
                            "terra  bela morais engenharia spe",
                            caminho=arquivo)
    assert banco["inseridos"] == []
    assert clientes_no_cache(arquivo, "MORAIS ENG") == []


def test_ja_esta_na_nuvem_nao_insere_de_novo_mas_completa_o_cache(
        banco, arquivo):
    """Nuvem já tem (outra máquina gravou) e o cache desta não: sem INSERT
    (daria 409 no índice único), e o cache fica em dia."""
    banco["cliente_erp"].append({"empresa_id": 2, "nome": "FULANO"})
    clientes_erp.gravar("tok", "MORAIS ENG", "Fulano", caminho=arquivo)
    assert banco["inseridos"] == []
    assert clientes_no_cache(arquivo, "MORAIS ENG") == ["Fulano"]


def test_empresa_que_a_nuvem_nao_conhece_nao_grava_nada(banco, arquivo):
    with pytest.raises(clientes_erp.sicoob_contas.MapaInvalido,
                       match="EMPRESA FANTASMA"):
        clientes_erp.gravar("tok", "EMPRESA FANTASMA", "FULANO",
                            caminho=arquivo)
    assert banco["inseridos"] == []


@pytest.mark.parametrize("empresa, cliente", [("", "FULANO"),
                                              ("MORAIS ENG", "  ")])
def test_vazio_e_recusado_antes_de_ir_ao_banco(banco, arquivo, empresa,
                                               cliente):
    with pytest.raises(clientes_erp.sicoob_contas.MapaInvalido):
        clientes_erp.gravar("tok", empresa, cliente, caminho=arquivo)
    assert banco["inseridos"] == []
