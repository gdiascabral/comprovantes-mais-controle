# -*- coding: utf-8 -*-
"""
Testes do módulo de extratos do Sicoob — a parte que decide em que pasta cada
extrato vai parar. É onde um erro custa caro e não aparece sozinho.

Mapa fictício: o repositório é público, nunca dado real da empresa.
"""
import json
import queue

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


def _mapa(tmp_path, dados) -> sc.Mapa:
    arq = tmp_path / "m.json"
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return sc.carregar(arq)


def _dividindo_a_pasta(sufixo_a="", sufixo_b="") -> dict:
    """Duas contas da MESMA empresa na MESMA pasta — o caso da Moura Dantas,
    que tem quatro. O banco autoriza (`unique (empresa_id, pasta, sufixo)`);
    o que ele não autoriza é as duas caírem no mesmo arquivo."""
    return {"raiz": "R:/EXTRATOS", "empresas": [
        {"nome": "DELTA", "pastas_vazias": [], "contas": [
            {"numero": "55.555-5", "pasta": "SICOOB", "sufixo": sufixo_a},
            {"numero": "66.666-6", "pasta": "SICOOB", "sufixo": sufixo_b},
        ]}]}


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


# ------------------------------------- o aviso que precisou virar impedimento

def test_duas_contas_no_mesmo_arquivo_sao_impedimento(tmp_path):
    m = _mapa(tmp_path, _dividindo_a_pasta())          # nenhuma tem sufixo
    barram = sc.impedimentos(m)
    assert len(barram) == 1
    assert "55.555-5" in barram[0] and "66.666-6" in barram[0]
    # e nada deixa de aparecer no registro: `validar` inclui os impedimentos
    assert barram[0] in sc.validar(m)


def test_sufixos_diferentes_liberam_a_pasta_compartilhada(tmp_path):
    """Dividir a pasta é legítimo, e é como quatro contas da mesma empresa
    são arquivadas juntas hoje. O que não pode é as duas gravarem o mesmo
    arquivo — e é só isso que a trava julga."""
    m = _mapa(tmp_path, _dividindo_a_pasta("55555-5", "66666-6"))
    assert sc.impedimentos(m) == []
    assert sc.validar(m) == []


def test_pasta_compartilhada_nao_vira_aviso_de_pasta_repetida(tmp_path):
    """Antes, contar as contas da pasta fazia a empresa certa levar um aviso
    de 'pasta repetida' por conta — ruído que ensina a ignorar aviso."""
    m = _mapa(tmp_path, _dividindo_a_pasta("55555-5", "66666-6"))
    assert not any("repetida" in a for a in sc.validar(m))


def test_pasta_vazia_declarada_duas_vezes_ainda_avisa(tmp_path):
    dados = _dividindo_a_pasta("55555-5", "66666-6")
    dados["empresas"][0]["pastas_vazias"] = ["CAIXA", "CAIXA"]
    avisos = sc.validar(_mapa(tmp_path, dados))
    assert any("Pasta 'CAIXA' repetida" in a for a in avisos)


def _aba(monkeypatch, mapa_falso):
    """A aba sem janela: `_garantir_mapa` só fala com o mapa e com a fila."""
    import extratos_frame
    aba = extratos_frame.ExtratosSicoobFrame.__new__(
        extratos_frame.ExtratosSicoobFrame)
    aba.q = queue.Queue()
    monkeypatch.setattr(extratos_frame.sc, "carregar",
                        lambda *_a, **_k: mapa_falso)
    return aba


def _registro(aba) -> str:
    linhas = []
    while True:
        try:
            _tipo, valor = aba.q.get_nowait()
        except queue.Empty:
            return "\n".join(linhas)
        linhas.append(str(valor))


def test_pasta_repetida_barra_o_lote_em_vez_de_so_avisar(tmp_path, monkeypatch):
    """Era aviso e o lote seguia: o `_garantir_mapa` registrava e devolvia
    True sempre. Só que aqui o estrago não espera correção — o extrato que
    foi sobrescrito não volta —, então vale a mesma regra da conta sem
    destino: travar ANTES do primeiro download."""
    aba = _aba(monkeypatch, _mapa(tmp_path, _dividindo_a_pasta()))
    assert aba._garantir_mapa() is False
    texto = _registro(aba)
    assert "MESMO arquivo" in texto and "55.555-5" in texto


def test_aviso_de_outra_natureza_continua_so_avisando(tmp_path, monkeypatch):
    """Subpasta fora do padrão é cadastro desleixado, não arquivo perdido:
    aparece no registro e o lote segue."""
    dados = json.loads(json.dumps(MAPA))
    dados["empresas"][1]["contas"][2]["pasta"] = "SUBCONTA 44.444-4 - SICOOB"
    aba = _aba(monkeypatch, _mapa(tmp_path, dados))
    assert aba._garantir_mapa() is True
    assert "fora do padrão" in _registro(aba)


# ------------------------------------------------------------ nomes/datas

def test_nome_do_arquivo():
    assert cfg.nome_arquivo(2026, 7) == "202607 SICOOB"
    assert cfg.nome_arquivo(2026, 12) == "202612 SICOOB"


def test_conta_sem_sufixo_mantem_o_nome_de_sempre(mapa):
    # A esmagadora maioria das contas tem a pasta só para si: o nome não pode
    # mudar por causa de um campo que ninguém preencheu.
    assert all(c.sufixo == "" for c in mapa.contas)
    assert cfg.nome_arquivo(2026, 7, mapa.contas[0].sufixo) == "202607 SICOOB"


def test_sufixo_e_lido_do_json(tmp_path):
    m = _mapa(tmp_path, _dividindo_a_pasta("55555-5", "66666-6"))
    assert [c.sufixo for c in m.contas] == ["55555-5", "66666-6"]


def test_duas_contas_na_mesma_pasta_geram_nomes_diferentes(tmp_path):
    """O defeito que obrigou o campo a existir.

    Sem desempate as duas gravavam "202607 SICOOB.ofx" no MESMO caminho e a
    segunda passava por cima da primeira: a pasta sai da conta, cada OFX é
    conferido contra a SUA conta (a trava do ACCTID aprova as duas), o
    `shutil.move` sobrescreve calado e o relatório fecha dizendo que as duas
    ficaram completas."""
    m = _mapa(tmp_path, _dividindo_a_pasta("55555-5", "66666-6"))
    a, b = m.contas
    n1 = cfg.nome_arquivo(2026, 7, a.sufixo)
    n2 = cfg.nome_arquivo(2026, 7, b.sufixo)
    assert n1 == "202607 SICOOB 55555-5"
    assert n1 != n2
    # e as duas caem na MESMA pasta — é isso que torna o sufixo necessário
    assert (sp.caminho_da_conta(m, 2026, 7, a.numero)
            == sp.caminho_da_conta(m, 2026, 7, b.numero))


def test_o_sufixo_entra_igual_ao_do_mais_controle(tmp_path):
    """Espaço e sufixo no fim, o mesmo formato de `contas_mc.nome_arquivo`.

    O PDF do ERP e o OFX do banco são da mesma conta e caem na mesma pasta:
    terminando igual, dá para ver de olho que são um par."""
    import contas_mc as cm
    m = _mapa(tmp_path, _dividindo_a_pasta("55555-5", "66666-6"))
    destino = cm.Destino(erp="X", empresa="DELTA", pasta="SICOOB",
                         banco="SICOOB", sufixo="55555-5")
    assert cm.nome_arquivo(destino, 2026, 7).endswith(" 55555-5.pdf")
    assert cfg.nome_arquivo(2026, 7, m.contas[0].sufixo).endswith(" 55555-5")


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
