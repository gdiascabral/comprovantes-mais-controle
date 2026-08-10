# -*- coding: utf-8 -*-
"""
Testes do módulo de extratos do Sicoob — a parte que decide em que pasta cada
extrato vai parar. É onde um erro custa caro e não aparece sozinho.

Mapa fictício: o repositório é público, nunca dado real da empresa.
"""
import json

import pytest

import sicoob_config as cfg
import sicoob_contas as sc
import sicoob_pastas as sp

MAPA = {
    "raiz": "R:/EXTRATOS",
    "empresas": [
        {"nome": "ALFA",
         "pastas_vazias": ["CAIXA", "INTER"],
         "contas": [{"numero": "11.111-1", "pasta": "SICOOB"}]},
        {"nome": "BETA",
         "pastas_vazias": [],
         "contas": [
             {"numero": "22.222-2", "pasta": "CONTA PRINCIPAL - 22222-2 - SICOOB"},
             {"numero": "33.333-3", "pasta": "SUBCONTA - 33333-3 - LOTE 01 - SICOOB"},
             {"numero": "44.444-4", "pasta": "SUBCONTA - 44444-4 - SICOOB"},
         ]},
        {"nome": "GAMA",                      # só pasta, sem download
         "pastas_vazias": ["BRADESCO", "SICOOB"],
         "contas": []},
    ],
}


@pytest.fixture
def mapa(tmp_path):
    arq = tmp_path / "contas_sicoob.json"
    dados = dict(MAPA, raiz=str(tmp_path / "EXTRATOS"))
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return sc.carregar(arq)


# ------------------------------------------------------------------ mapa

def test_carrega_contas_e_empresas(mapa):
    assert [e.nome for e in mapa.empresas] == ["ALFA", "BETA", "GAMA"]
    assert len(mapa.contas) == 4


def test_conta_encontrada_com_ou_sem_pontuacao(mapa):
    # O OFX traz o ACCTID sem ponto; a pessoa escreve com. Os dois têm de achar.
    for escrita in ("11.111-1", "11111-1", "111111"):
        assert mapa.conta_por_numero(escrita).empresa == "ALFA"


def test_conta_inexistente_devolve_none(mapa):
    assert mapa.conta_por_numero("99.999-9") is None


def test_arquivo_ausente_da_recado_util(tmp_path):
    with pytest.raises(sc.MapaInvalido, match="não existe"):
        sc.carregar(tmp_path / "nao_existe.json")


def test_json_sem_empresas_e_recusado(tmp_path):
    arq = tmp_path / "m.json"
    arq.write_text('{"raiz": "R:/X"}', encoding="utf-8")
    with pytest.raises(sc.MapaInvalido):
        sc.carregar(arq)


def test_modelo_nao_sobrescreve_existente(tmp_path):
    arq = tmp_path / "contas_sicoob.json"
    arq.write_text("original", encoding="utf-8")
    sc.criar_modelo(arq)
    assert arq.read_text(encoding="utf-8") == "original"


# ------------------------------------------------------------- validação

def test_mapa_valido_nao_gera_aviso(mapa):
    assert sc.validar(mapa) == []


def test_conta_repetida_em_duas_empresas_e_apontada(tmp_path):
    dados = json.loads(json.dumps(MAPA))
    dados["empresas"][2]["contas"] = [{"numero": "11111-1", "pasta": "SICOOB"}]
    arq = tmp_path / "m.json"
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    avisos = sc.validar(sc.carregar(arq))
    assert any("duas vezes" in a for a in avisos)


def test_subconta_fora_do_padrao_e_apontada(tmp_path):
    dados = json.loads(json.dumps(MAPA))
    # Sem o hífen depois de SUBCONTA e com ponto no número: as duas
    # inconsistências que a padronização eliminou.
    dados["empresas"][1]["contas"][2]["pasta"] = "SUBCONTA 44.444-4 - SICOOB"
    arq = tmp_path / "m.json"
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    assert any("fora do padrão" in a for a in sc.validar(sc.carregar(arq)))


# ------------------------------------------------------------ nomes/datas

def test_nome_do_arquivo():
    assert cfg.nome_arquivo(2026, 7) == "202607 SICOOB"
    assert cfg.nome_arquivo(2026, 12) == "202612 SICOOB"


def test_nome_da_pasta_da_empresa():
    assert cfg.nome_pasta_empresa(2026, 7, "BURITIS") == "JULHO 2026 - BURITIS"


def test_mes_anterior_vira_o_ano():
    assert cfg.mes_anterior(2026, 8) == (2026, 7)
    assert cfg.mes_anterior(2026, 1) == (2025, 12)


# ---------------------------------------------------------------- pastas

def test_plano_cobre_empresas_e_subpastas(mapa):
    plano = sp.planejar(mapa, 2026, 7)
    # 3 empresas + (2+1) + 3 + 2 subpastas
    assert len(plano) == 3 + 3 + 3 + 2
    assert all(p.nova for p in plano)          # nada existe ainda


def test_caminho_da_conta(mapa):
    alvo = sp.caminho_da_conta(mapa, 2026, 7, "33333-3")
    assert alvo.parts[-3:] == ("JULHO", "JULHO 2026 - BETA",
                               "SUBCONTA - 33333-3 - LOTE 01 - SICOOB")


def test_conta_de_gama_nao_existe_pois_e_so_pasta(mapa):
    assert sp.caminho_da_conta(mapa, 2026, 7, "55.555-5") is None


def test_criar_cria_tudo_e_e_idempotente(mapa):
    plano = sp.planejar(mapa, 2026, 7)
    assert len(sp.criar(plano)) == len(plano)
    assert all(p.caminho.is_dir() for p in plano)
    # Segunda passada: nada mais é novo.
    assert sp.criar(sp.planejar(mapa, 2026, 7)) == []


def test_pasta_que_ja_existe_nao_e_marcada_como_nova(mapa):
    sp.criar(sp.planejar(mapa, 2026, 7))
    novo = sp.planejar(mapa, 2026, 7)
    assert not any(p.nova for p in novo)


def test_empresa_do_mes_anterior_ausente_do_mapa_vira_aviso(mapa):
    anterior = mapa.raiz / "2026" / "JUNHO"
    (anterior / "JUNHO 2026 - ALFA").mkdir(parents=True)
    (anterior / "JUNHO 2026 - EMPRESA NOVA").mkdir(parents=True)
    assert sp.comparar_com_mes_anterior(mapa, 2026, 7) == ["EMPRESA NOVA"]


def test_sem_mes_anterior_nao_reclama(mapa):
    assert sp.comparar_com_mes_anterior(mapa, 2026, 7) == []


def test_resumo_marca_novas_e_conta_o_total(mapa):
    texto = sp.resumo(sp.planejar(mapa, 2026, 7))
    assert "NOVA" in texto
    assert "11 pastas no total, 11 a criar." in texto
    assert "<- extratos" in texto
