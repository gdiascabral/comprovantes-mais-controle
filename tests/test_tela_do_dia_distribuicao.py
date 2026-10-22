"""Item A (22/10/2026): distribuição de lucros nos movimentos à mão, o
aportador composto da aba Regras ("Fulano/Beltrano") e a transferência que
não é aporte. Cadastro, contas e pessoas fictícios."""
import json
from datetime import date
from decimal import Decimal as D

import pytest

from aportes.regras import TIPO_INVESTIDOR
from conciliacao.aportadores import Regra
from tela_do_dia import aportes as ap
from tela_do_dia import decisoes as dc
from tela_do_dia import dia_de_trabalho as ddt
from tela_do_dia import para_aportes as pa

HOJE = date(2026, 10, 21)
ENTIDADES = {
    "MAE - BANCO": {"nome_oficial": "MAE FICTICIA LTDA", "conta": "MAE - BANCO", "nome_descricao": None},
    "FILHA UM - BANCO": {"nome_oficial": "FILHA UM LTDA", "conta": "FILHA UM - BANCO", "nome_descricao": None},
    "FILHA DOIS - BANCO": {"nome_oficial": "FILHA DOIS LTDA", "conta": "FILHA DOIS - SUBCONTA 44.444-4",
                           "nome_descricao": None},
    "SOCIO FICTICIO A": {"nome_oficial": "SOCIO FICTICIO A", "conta": None, "nome_descricao": None},
    "HOLDING FICTICIA": {"nome_oficial": "HOLDING FICTICIA SA", "conta": "HOLDING - BANCO",
                         "nome_descricao": None},
}
SUBCONTAS = {"44444-4": {"obras": ["OBRA MODELO"],
                         "investidores": ["PESSOA FICTICIA UM SOBRENOME", "PESSOA FICTICIA DOIS SOBRENOME"],
                         "pesos": {}}}
REGRAS = [
    Regra("Filha Um - Banco", "Mae - Banco", None, "Aporte", True, linha=5),
    Regra("Filha Dois - Banco", "Pessoa Um/Pessoa Dois", None, "Aporte", False, linha=6),
    Regra("Filha Um - Banco", "Pessoa Um/Pessoa Dois", None, "Aporte", False, linha=7),
    Regra("Filha Dois - Banco", "Pessoa Um/Pessoa Dois/Pessoa Tres", None, "Aporte", False, linha=8),
    Regra("Filha Um - Banco", "Holding - Banco", None, "Transferência", True, linha=9),
]


def _envio(definidos=None, distribuicoes=(), enviados=None, sem_saldo=(), subcontas=SUBCONTAS):
    return pa.operacoes(definidos or {}, REGRAS, ENTIDADES, subcontas, HOJE, enviados=enviados,
                        sem_saldo=sem_saldo, distribuicoes=distribuicoes)


# ------------------------------------------------- distribuição de lucros
def test_distribuicao_para_socio_sem_conta_vai_como_so_pagamento():
    envio = _envio(distribuicoes=[("Mae - Banco", "SOCIO FICTICIO A", D("1500.00"))])
    (op, chaves), = envio.itens
    assert (op.pagador, op.recebedor, op.valor, op.tipo, op.modo) == (
        "MAE - BANCO", "SOCIO FICTICIO A", D("1500.00"), "Distribuição de Lucro", "Só pagamento")
    assert op.validar(ENTIDADES, SUBCONTAS) == []
    assert chaves == [pa.chave_da_distribuicao("Mae - Banco", "SOCIO FICTICIO A")]
    assert envio.valores[chaves[0]] == D("1500.00")
    assert envio.pendentes == [] and envio.avisos == []


def test_distribuicao_para_quem_tem_conta_lanca_as_duas_pernas():
    (op, _), = _envio(distribuicoes=[("Mae - Banco", "HOLDING FICTICIA", D("10.00"))]).itens
    assert op.modo == "Pagamento + Recebimento" and op.tipo == "Distribuição de Lucro"


def test_chave_da_distribuicao_nao_colide_com_aporte_da_regra():
    assert pa.chave_da_distribuicao("Mae - Banco", "SOCIO FICTICIO A") != \
        pa.chave_de_envio("SOCIO FICTICIO A", "Mae - Banco")


def test_duas_distribuicoes_do_mesmo_par_viram_uma_operacao_somada():
    envio = _envio(distribuicoes=[("Mae - Banco", "SOCIO FICTICIO A", D("100.00")),
                                  ("Mae - Banco", "SOCIO FICTICIO A", D("50.10"))])
    (op, chaves), = envio.itens
    assert op.valor == D("150.10") and envio.valores[chaves[0]] == D("150.10")


def test_distribuicao_ja_mandada_nao_vai_de_novo():
    chave = pa.chave_da_distribuicao("Mae - Banco", "SOCIO FICTICIO A")
    envio = _envio(distribuicoes=[("Mae - Banco", "SOCIO FICTICIO A", D("100.00"))],
                   enviados={chave: D("100.00")})
    assert envio.itens == [] and "já mandado" in envio.pendentes[0].motivo


def test_distribuicao_para_nome_fora_do_cadastro_e_pendencia():
    envio = _envio(distribuicoes=[("Mae - Banco", "Socio Ficticio", D("100.00"))])
    assert envio.itens == [] and "não achei" in envio.pendentes[0].motivo


def test_distribuicao_de_conta_sem_saldo_vai_com_aviso():
    envio = _envio(distribuicoes=[("Mae - Banco", "SOCIO FICTICIO A", D("100.00"))],
                   sem_saldo={"Mae - Banco"})
    (op, _), = envio.itens
    assert envio.sem_saldo == [op] and envio.avisos


# ------------------------------------- aportador composto da aba Regras
def test_composto_em_subconta_de_investidor_vira_aporte_de_investidor():
    envio = _envio({("Filha Dois - Banco", "Pessoa Um/Pessoa Dois"): D("5000.00")})
    (op, chaves), = envio.itens
    assert (op.pagador, op.recebedor, op.valor, op.tipo, op.modo) == (
        "INVESTIDOR SUBCONTA 44444-4", "FILHA DOIS - BANCO", D("5000.00"), TIPO_INVESTIDOR,
        "Só recebimento")
    assert op.validar(ENTIDADES, SUBCONTAS) == []
    assert chaves == [pa.chave_de_envio("Filha Dois - Banco", "Pessoa Um/Pessoa Dois")]
    assert envio.pendentes == []
    # foi, mas o dono confere: a divisão é a do cadastro, com os nomes de lá
    (aviso,) = envio.avisos
    assert "44444-4" in aviso.motivo and "PESSOA FICTICIA UM SOBRENOME" in aviso.motivo


def test_composto_com_numero_de_nomes_diferente_da_subconta_e_pendencia():
    envio = _envio({("Filha Dois - Banco", "Pessoa Um/Pessoa Dois/Pessoa Tres"): D("10.00")})
    assert envio.itens == []
    motivo = envio.pendentes[0].motivo
    assert "3 nomes" in motivo and "2 investidores" in motivo


def test_composto_em_conta_que_nao_e_subconta_diz_o_que_cadastrar():
    envio = _envio({("Filha Um - Banco", "Pessoa Um/Pessoa Dois"): D("5000.00")})
    assert envio.itens == []
    motivo = envio.pendentes[0].motivo
    assert "subconta de investidor" in motivo and "Novo cadastro" in motivo
    assert "um aportador por linha" in motivo


def test_composto_nunca_casa_por_primeiro_nome():
    # "Socio/Outro" não vira o "SOCIO FICTICIO A" do cadastro
    regras = [Regra("Filha Um - Banco", "Socio/Outro", None, "Aporte", False, linha=5)]
    envio = pa.operacoes({("Filha Um - Banco", "Socio/Outro"): D("1.00")}, regras, ENTIDADES,
                         SUBCONTAS, HOJE)
    assert envio.itens == [] and envio.pendentes


def test_composto_ja_mandado_segura():
    chave = pa.chave_de_envio("Filha Dois - Banco", "Pessoa Um/Pessoa Dois")
    envio = _envio({("Filha Dois - Banco", "Pessoa Um/Pessoa Dois"): D("5000.00")},
                   enviados={chave: D("5000.00")})
    assert envio.itens == [] and "já mandado" in envio.pendentes[0].motivo


# ----------------------------------------- transferência não é aporte
def test_transferencia_da_regra_e_informativo_e_nao_pendencia():
    envio = _envio({("Filha Um - Banco", "Holding - Banco"): D("10000.00")})
    assert envio.itens == [] and envio.pendentes == [] and envio.avisos == []
    (info,) = envio.informativos
    assert "transferência entre contas" in info.motivo
    assert "lance no banco" in info.motivo and "não é aporte" in info.motivo
    assert dc.linhas_informativas(envio) == [
        f"Holding - Banco → Filha Um - Banco (R$ 10.000,00): {info.motivo}"]


# ------------------------------------------- saldo e mínimo da tela
def test_distribuicao_sai_da_conta_de_origem_no_minimo_e_no_saldo_final():
    saldos = {"Mae - Banco": D("1000.00")}
    a_pagar = {"Mae - Banco": D("500.00")}
    painel = ap.montar_aportes(saldos, a_pagar, [], {},
                               distribuicoes=[("Mae - Banco", "SOCIO FICTICIO A", D("800.00"))])
    (mae,) = painel.contas
    assert mae.distribui == D("800.00")
    assert mae.minimo == D("300.00")
    assert mae.saldo_final == D("-300.00")


def test_distribuicao_de_conta_fora_do_dia_ou_negativa_e_ignorada_com_alerta():
    saldos = {"Mae - Banco": D("1000.00")}
    painel = ap.montar_aportes(saldos, {}, [], {},
                               distribuicoes=[("Fantasma - Banco", "SOCIO FICTICIO A", D("5.00")),
                                              ("Mae - Banco", "SOCIO FICTICIO A", D("-5.00"))])
    assert all(c.distribui == D("0.00") for c in painel.contas)
    avisos = [f for t, f in painel.alertas if t == "atencao"]
    assert any("Fantasma - Banco" in f and "ignorad" in f for f in avisos)
    assert any("negativo" in f for f in avisos)


# ------------------------------------------------------ decisões
ROTULOS = ["Mae - Banco", "Filha Um - Banco"]


def test_nova_distribuicao_valida():
    assert dc.nova_distribuicao("Mae - Banco", "SOCIO FICTICIO A", "1.500,00", ROTULOS,
                                ["SOCIO FICTICIO A"]) == ("Mae - Banco", "SOCIO FICTICIO A",
                                                          D("1500.00"))


@pytest.mark.parametrize("origem,socio,valor,socios,trecho", [
    ("", "SOCIO FICTICIO A", "1,00", None, "origem"),
    ("Conta Fora", "SOCIO FICTICIO A", "1,00", None, "não é conta do painel"),
    ("Mae - Banco", "", "1,00", None, "sócio"),
    ("Mae - Banco", "Outro Nome", "1,00", ["SOCIO FICTICIO A"], "cadastro"),
    ("Mae - Banco", "SOCIO FICTICIO A", "0,00", None, "maior que zero"),
])
def test_nova_distribuicao_recusa(origem, socio, valor, socios, trecho):
    with pytest.raises(ValueError, match=trecho):
        dc.nova_distribuicao(origem, socio, valor, ROTULOS, socios)


def test_descrever_distribuicao():
    assert dc.descrever_distribuicao(("Mae - Banco", "SOCIO FICTICIO A", D("10.00"))) == \
        "distribuição de lucros Mae - Banco → SOCIO FICTICIO A: R$ 10,00"


def test_movimentos_do_dia_para_o_html_tem_os_tres_tipos_na_ordem():
    movs = dc.movimentos_do_dia(
        [(None, "Mae - Banco", D("400.00")), ("Mae - Banco", "Filha Um - Banco", D("50.00"))],
        [("Mae - Banco", "SOCIO FICTICIO A", D("70.00"))])
    assert movs == [
        {"de": dc.DE_FORA, "para": "Mae - Banco", "tipo": "Aporte que entra na mãe",
         "valor": D("400.00")},
        {"de": "Mae - Banco", "para": "Filha Um - Banco", "tipo": "Transferência entre contas",
         "valor": D("50.00")},
        {"de": "Mae - Banco", "para": "SOCIO FICTICIO A", "tipo": "Distribuição de lucros",
         "valor": D("70.00")},
    ]


def test_movimentos_do_dia_ignoram_zero_e_negativo():
    assert dc.movimentos_do_dia([(None, "Mae - Banco", D("0"))],
                                [("Mae - Banco", "X", D("-1"))]) == []


# ------------------------------------------------- arquivo do dia
def test_distribuicoes_ida_e_volta_em_decimal(tmp_path):
    caminho = tmp_path / "dia.json"
    dia = ddt.DiaDeTrabalho(HOJE)
    dia.distribuicoes = [("Mae - Banco", "SOCIO FICTICIO A", D("1000.10"))]
    ddt.gravar(dia, caminho)
    volta = ddt.ler(caminho, HOJE)
    assert volta.distribuicoes == dia.distribuicoes
    assert isinstance(volta.distribuicoes[0][2], D)


def test_arquivo_sem_distribuicoes_continua_legivel(tmp_path):
    caminho = tmp_path / "dia.json"
    caminho.write_text(json.dumps({"data": "2026-10-21"}), encoding="utf-8")
    assert ddt.ler(caminho, HOJE).distribuicoes == []


@pytest.mark.parametrize("item", [
    {"origem": None, "socio": "S", "valor": "1"},
    {"origem": "Mae - Banco", "socio": "", "valor": "1"},
    {"origem": "Mae - Banco", "socio": "S", "valor": "abc"},
    {"origem": "Mae - Banco", "socio": "S", "valor": "NaN"},
])
def test_distribuicao_estragada_levanta(tmp_path, item):
    caminho = tmp_path / "dia.json"
    caminho.write_text(json.dumps({"data": "2026-10-21", "distribuicoes": [item]}),
                       encoding="utf-8")
    with pytest.raises(ValueError):
        ddt.ler(caminho, HOJE)


def test_distribuicoes_validas_sao_as_que_a_tela_soma():
    dist = [("Mae - Banco", "SOCIO FICTICIO A", D("10.00")),
            ("Conta Fora", "SOCIO FICTICIO A", D("5.00")),
            ("Mae - Banco", "SOCIO FICTICIO A", D("0.00"))]
    assert dc.distribuicoes_validas(dist, ROTULOS) == [dist[0]]


def test_socios_do_cadastro_tira_subconta_de_investidor_e_conta_do_painel():
    entidades = {"SOCIO FICTICIO A": {}, "INVESTIDOR SUBCONTA 44444-4": {}, "Mae - Banco": {},
                 "HOLDING FICTICIA": {}}
    assert dc.socios_do_cadastro(entidades, ROTULOS) == ["HOLDING FICTICIA", "SOCIO FICTICIO A"]
    assert dc.socios_do_cadastro(None, ROTULOS) == []
