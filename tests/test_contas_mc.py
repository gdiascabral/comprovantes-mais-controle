# -*- coding: utf-8 -*-
"""
Testes do mapa conta do Mais Controle -> pasta.

É onde um erro manda o extrato de uma empresa para a pasta de outra sem que
nada no disco denuncie. Mapa fictício: o repositório é público.
"""
import json

import pytest

import contas_mc as cm

MAPA = {
    "raiz": "R:/EXTRATOS",
    "contas": [
        {"erp": "ALFA SPE - SICOOB", "empresa": "ALFA", "pasta": "SICOOB", "banco": "SICOOB"},
        {"erp": "ALFA SPE - INTER", "empresa": "ALFA", "pasta": "INTER", "banco": "INTER"},
        {"erp": "APLICAÇÃO FUNDO - ALFA SPE - CAIXA", "empresa": "ALFA",
         "pasta": "CAIXA/APLICAÇÃO", "banco": "CAIXA"},
        {"erp": "BETA LTDA SICOOB - 11111-1", "empresa": "BETA", "pasta": "SICOOB",
         "banco": "SICOOB", "sufixo": "11111-1"},
        {"erp": "BETA LTDA SICOOB - 22222-2", "empresa": "BETA", "pasta": "SICOOB",
         "banco": "SICOOB", "sufixo": "22222-2"},
    ],
}


@pytest.fixture
def mapa(tmp_path):
    arq = tmp_path / "contas_mc.json"
    arq.write_text(json.dumps(MAPA, ensure_ascii=False), encoding="utf-8")
    return cm.carregar(arq)


# ------------------------------------------------------------------ mapa

def test_carrega_todas_as_contas(mapa):
    assert len(mapa.destinos) == 5


def test_encontra_conta_pelo_nome(mapa):
    assert mapa.de("ALFA SPE - SICOOB").pasta == "SICOOB"


def test_comparacao_ignora_acento_caixa_e_espaco(mapa):
    # O nome vem do cadastro do ERP, digitado por gente.
    for escrita in ("APLICAÇÃO FUNDO - ALFA SPE - CAIXA",
                    "aplicacao fundo - alfa spe - caixa",
                    "APLICACAO  FUNDO -  ALFA SPE - CAIXA"):
        assert mapa.de(escrita) is not None, escrita


def test_conta_desconhecida_devolve_none(mapa):
    assert mapa.de("CONTA QUE NAO EXISTE") is None


def test_json_sem_contas_e_recusado(tmp_path):
    arq = tmp_path / "m.json"
    arq.write_text('{"raiz": "R:/X"}', encoding="utf-8")
    with pytest.raises(cm.MapaInvalido):
        cm.carregar(arq)


def test_conta_incompleta_aponta_o_que_falta(tmp_path):
    arq = tmp_path / "m.json"
    arq.write_text(json.dumps({"contas": [{"erp": "X", "empresa": "Y"}]}), encoding="utf-8")
    with pytest.raises(cm.MapaInvalido, match="pasta"):
        cm.carregar(arq)


def test_arquivo_ausente_da_recado_util(tmp_path):
    with pytest.raises(cm.MapaInvalido, match="não existe"):
        cm.carregar(tmp_path / "nao_existe.json")


# -------------------------------------------------------------- caminhos

def test_nome_do_arquivo(mapa):
    d = mapa.de("ALFA SPE - SICOOB")
    assert cm.nome_arquivo(d, 2026, 7) == "202607 SICOOB MAIS CONTROLE.pdf"


def test_nome_leva_o_banco_certo(mapa):
    d = mapa.de("ALFA SPE - INTER")
    assert cm.nome_arquivo(d, 2026, 7) == "202607 INTER MAIS CONTROLE.pdf"


def test_contas_na_mesma_pasta_se_distinguem_pelo_sufixo(mapa):
    a = mapa.de("BETA LTDA SICOOB - 11111-1")
    b = mapa.de("BETA LTDA SICOOB - 22222-2")
    n1, n2 = cm.nome_arquivo(a, 2026, 7), cm.nome_arquivo(b, 2026, 7)
    assert n1 == "202607 SICOOB MAIS CONTROLE 11111-1.pdf"
    assert n1 != n2
    # e caem na MESMA pasta — é isso que torna o sufixo necessário
    p1 = cm.caminho_do_arquivo(mapa, a, 2026, 7).parent
    p2 = cm.caminho_do_arquivo(mapa, b, 2026, 7).parent
    assert p1 == p2


def test_caminho_completo(mapa):
    d = mapa.de("ALFA SPE - SICOOB")
    p = cm.caminho_do_arquivo(mapa, d, 2026, 7)
    assert p.parts[-4:] == ("JULHO", "JULHO 2026 - ALFA", "SICOOB",
                            "202607 SICOOB MAIS CONTROLE.pdf")


def test_pasta_com_subnivel(mapa):
    d = mapa.de("APLICAÇÃO FUNDO - ALFA SPE - CAIXA")
    p = cm.caminho_do_arquivo(mapa, d, 2026, 7)
    assert p.parts[-3:-1] == ("CAIXA", "APLICAÇÃO")


def test_dezembro_nao_estoura_o_indice_do_mes(mapa):
    d = mapa.de("ALFA SPE - SICOOB")
    p = cm.caminho_do_arquivo(mapa, d, 2026, 12)
    assert "DEZEMBRO" in p.parts and p.name.startswith("202612")


# -------------------------------------------------------------- resolver

def test_resolver_separa_conhecidas_de_desconhecidas(mapa):
    contas = [{"id": "1", "nome": "ALFA SPE - SICOOB"},
              {"id": "2", "nome": "CONTA MISTERIOSA"}]
    pares, desconhecidas = cm.resolver(mapa, contas, 2026, 7)
    assert len(pares) == 1
    assert desconhecidas == ["CONTA MISTERIOSA"]


def test_caminhos_longos_vazio_no_mapa_ficticio(mapa):
    assert cm.caminhos_longos(mapa, 2026, 7) == []


def test_caminho_absurdo_e_apontado(tmp_path):
    dados = {"raiz": "R:/EXTRATOS", "contas": [
        {"erp": "X", "empresa": "E" * 120, "pasta": "P" * 120, "banco": "SICOOB"}]}
    arq = tmp_path / "m.json"
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    fora = cm.caminhos_longos(cm.carregar(arq), 2026, 7)
    assert fora and fora[0][1] > cm.LIMITE_CAMINHO
