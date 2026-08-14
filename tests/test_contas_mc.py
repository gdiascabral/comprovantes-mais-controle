# -*- coding: utf-8 -*-
"""
Testes do mapa conta do Mais Controle -> pasta.

É onde um erro manda o extrato de uma empresa para a pasta de outra sem que
nada no disco denuncie. Mapa fictício: o repositório é público.
"""
import datetime
import json
import queue
from threading import Event

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
    fora = cm.caminhos_longos(cm.carregar(_mapa_absurdo(tmp_path)), 2026, 7)
    assert fora and fora[0][1] > cm.LIMITE_CAMINHO


def _mapa_absurdo(tmp_path):
    """Um mapa com um destino que não cabe nos 260 do Windows, e outro que
    cabe — para separar "o lote tem problema" de "a conta marcada tem"."""
    dados = {"raiz": "R:/EXTRATOS", "contas": [
        {"erp": "CONTA ENORME", "empresa": "E" * 120, "pasta": "P" * 120,
         "banco": "SICOOB"},
        {"erp": "CONTA NORMAL", "empresa": "ALFA", "pasta": "SICOOB",
         "banco": "SICOOB"}]}
    arq = tmp_path / "absurdo.json"
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return arq


def test_conta_nao_marcada_nao_barra_o_lote(tmp_path):
    """Recusar o lote por causa de uma conta que ninguém marcou é recusar
    trabalho que ia dar certo — a mesma regra da trava de conta sem destino,
    que também só olha as escolhidas."""
    m = cm.carregar(_mapa_absurdo(tmp_path))
    assert cm.caminhos_longos(m, 2026, 7, contas=["CONTA NORMAL"]) == []
    fora = cm.caminhos_longos(m, 2026, 7, contas=["CONTA ENORME"])
    assert [n for n, _t in fora] == ["CONTA ENORME"]


def test_periodo_parcial_e_medido_no_tamanho_que_vai_ser_gravado(tmp_path):
    """"01-07-2026 a 15-07-2026" tem 17 caracteres a mais que "202607":
    medir o nome curto e gravar o longo aprovaria o caminho que estoura."""
    # 255 caracteres com "202607", 272 com as duas datas: cabe de um jeito e
    # não cabe do outro, que é exatamente o caso que a conferência perdia.
    dados = {"raiz": "R:/EXTRATOS", "contas": [
        {"erp": "X", "empresa": "E" * 93, "pasta": "P" * 93,
         "banco": "SICOOB"}]}
    arq = tmp_path / "m.json"
    arq.write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    m = cm.carregar(arq)
    curto = cm.caminhos_longos(m, 2026, 7)
    longo = cm.caminhos_longos(m, 2026, 7, periodo="01-07-2026 a 15-07-2026")
    assert curto == [] and longo != []


# ------------------------------------------------- período parcial no nome

def test_periodo_parcial_nao_usa_o_nome_do_mes_fechado(mapa):
    """Pedir 01/07 a 15/07 para tirar uma dúvida gravava por cima do extrato
    de julho já arquivado, e nada barrava: a trava de paginação aprova,
    porque o extrato parcial está completo *para o período pedido*."""
    d = mapa.de("ALFA SPE - SICOOB")
    fechado = cm.nome_arquivo(d, 2026, 7)
    parcial = cm.nome_arquivo(d, 2026, 7, periodo="01-07-2026 a 15-07-2026")
    assert fechado == "202607 SICOOB MAIS CONTROLE.pdf"
    assert parcial == "01-07-2026 a 15-07-2026 SICOOB MAIS CONTROLE.pdf"
    assert parcial != fechado


def test_periodo_parcial_preserva_o_sufixo_da_conta(mapa):
    # O desempate das contas que dividem a pasta vale para os dois nomes.
    d = mapa.de("BETA LTDA SICOOB - 11111-1")
    assert cm.nome_arquivo(d, 2026, 7, periodo="01-07-2026 a 15-07-2026") == (
        "01-07-2026 a 15-07-2026 SICOOB MAIS CONTROLE 11111-1.pdf")


def _rf():
    from relatorio_frame import RelatorioFrame
    return RelatorioFrame


@pytest.mark.parametrize("ini,fim", [
    (datetime.date(2026, 7, 1), datetime.date(2026, 7, 31)),   # julho inteiro
    (datetime.date(2024, 2, 1), datetime.date(2024, 2, 29)),   # bissexto
])
def test_mes_fechado_continua_com_o_nome_de_sempre(ini, fim):
    assert _rf()._mes_fechado(ini, fim)
    assert _rf()._periodo_no_nome(ini, fim) == ""


@pytest.mark.parametrize("ini,fim", [
    (datetime.date(2026, 7, 1), datetime.date(2026, 7, 15)),   # meio do mês
    (datetime.date(2026, 7, 2), datetime.date(2026, 7, 31)),   # falta o dia 1
    (datetime.date(2026, 7, 1), datetime.date(2026, 8, 31)),   # dois meses
])
def test_periodo_que_nao_e_mes_fechado_leva_as_duas_datas(ini, fim):
    assert not _rf()._mes_fechado(ini, fim)
    nome = _rf()._periodo_no_nome(ini, fim)
    assert nome == f"{ini:%d-%m-%Y} a {fim:%d-%m-%Y}"
    # nome de arquivo válido no Windows: nada de \ / : * ? " < > |
    assert not set(nome) & set('\\/:*?"<>|')


# --------------------------------------------- a trava, na aba de verdade

class _AnxFalso:
    """O dono do navegador, de mentira. Guarda o que foi submetido: é o que
    separa "barrou antes do primeiro download" de "barrou depois"."""

    def __init__(self):
        self.submetidos = []

    def avisar_se_ocupado(self, _quem):
        return False

    def submeter(self, *a, **_k):
        self.submetidos.append(a)
        return None


@pytest.fixture
def dito(monkeypatch):
    """O que a aba mostrou em caixa de diálogo."""
    import relatorio_frame
    ditos = []
    for funcao in ("showwarning", "showinfo", "showerror"):
        monkeypatch.setattr(relatorio_frame.messagebox, funcao,
                            lambda t, m, _l=ditos: _l.append((t, m)))
    return ditos


def _aba(raiz, mapa, contas):
    """A aba sem `_build`: `gerar()` só toca no mapa, nas marcações e no anx."""
    import tkinter as tk
    aba = _rf().__new__(_rf())
    aba.worker = None
    aba.q = queue.Queue()
    aba._parar = Event()
    aba.mapa = mapa
    aba.anx = _AnxFalso()
    aba.contas = contas
    aba.vars_contas = {c["id"]: tk.BooleanVar(master=raiz, value=True)
                       for c in contas}
    aba.sem_destino = set()
    aba.v_personalizado = tk.BooleanVar(master=raiz, value=False)
    aba.v_mes = tk.StringVar(master=raiz, value="Julho")
    aba.v_ano = tk.StringVar(master=raiz, value="2026")
    aba.v_ini = tk.StringVar(master=raiz, value="01/07/2026")
    aba.v_fim = tk.StringVar(master=raiz, value="15/07/2026")
    return aba


def test_caminho_longo_barra_antes_do_primeiro_download(raiz, tmp_path, dito):
    """A conferência existia desde sempre e não tinha um único chamador.
    Estourar os 260 aparecia como falha de escrita na conta 7 de 34, com
    causa nada óbvia — e as 6 primeiras já tinham custado meia hora de ERP."""
    mapa = cm.carregar(_mapa_absurdo(tmp_path))
    aba = _aba(raiz, mapa, [{"id": "1", "nome": "CONTA ENORME"}])
    aba.gerar()
    assert aba.anx.submetidos == []           # nada foi baixado
    assert dito and "CONTA ENORME" in dito[0][1]
    assert str(cm.LIMITE_CAMINHO) in dito[0][1]


def test_caminho_dentro_do_limite_deixa_o_lote_seguir(raiz, tmp_path, dito):
    mapa = cm.carregar(_mapa_absurdo(tmp_path))
    aba = _aba(raiz, mapa, [{"id": "1", "nome": "CONTA NORMAL"}])
    aba.gerar()
    assert dito == []
    assert len(aba.anx.submetidos) == 1
