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
    assert chaves == [pa.chave_da_subconta("44444-4", "Filha Dois - Banco")]
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


def test_socios_do_cadastro_tira_subconta_de_investidor_e_junta_a_mesma_conta():
    entidades = {"SOCIO FICTICIO A": {}, "INVESTIDOR SUBCONTA 44444-4": {}, "Mae - Banco": {},
                 "HOLDING FICTICIA": {}}
    # Pessoas primeiro; depois empresas e contas do painel, sem repetir a
    # conta que está no cadastro e no painel (fica o rótulo do painel).
    assert dc.socios_do_cadastro(entidades, ROTULOS) == [
        "SOCIO FICTICIO A", "Filha Um - Banco", "HOLDING FICTICIA", "Mae - Banco"]
    assert dc.socios_do_cadastro(None, ROTULOS) == ["Filha Um - Banco", "Mae - Banco"]


#: O print do dono (23/10/2026), com nomes fictícios: a SPE distribui lucro
#: para a empresa sócia, que é conta do PAINEL e está no cadastro com conta.
ROTULOS_PRINT = ["Origem Spe - Sicoob", "Empresa Socia Eng - Inter", "Outra Conta - Banco"]
ENTIDADES_PRINT = {
    "SOCIO FICTICIO A": {"nome_oficial": "SOCIO FICTICIO A", "conta": None},
    "SOCIA FICTICIA B": {"nome_oficial": "SOCIA FICTICIA B", "conta": None},
    "PESSOA COM CONTA": {"nome_oficial": "PESSOA COM CONTA", "conta": "PESSOA - BANCO"},
    "EMPRESA SOCIA ENG": {"nome_oficial": "EMPRESA SOCIA ENGENHARIA LTDA",
                          "conta": "EMPRESA SOCIA ENG - INTER"},
    "ORIGEM SPE - SICOOB": {"nome_oficial": "ORIGEM SPE LTDA", "conta": "ORIGEM SPE - SICOOB"},
    "NOME DIFERENTE": {"nome_oficial": "NOME DIFERENTE LTDA", "conta": "OUTRA CONTA - BANCO"},
    "EMPRESA GAMA": {"nome_oficial": "EMPRESA GAMA SPE LTDA", "conta": None},
    "INVESTIDOR SUBCONTA 44444-4": {"nome_oficial": "INVESTIDOR SUBCONTA 44444-4",
                                    "conta": "SUBCONTA 44.444-4"},
}


def test_socios_do_cadastro_tem_a_empresa_socia_que_e_conta_do_painel():
    """Dono, 23/10/2026: "NAO APARECEU" a empresa sócia — o filtro de "cara
    de empresa" e o de conta do painel a tiravam da lista "Para"."""
    lista = dc.socios_do_cadastro(ENTIDADES_PRINT, ROTULOS_PRINT,
                                  origem="Origem Spe - Sicoob")
    assert lista == ["SOCIA FICTICIA B", "SOCIO FICTICIO A",
                     "EMPRESA GAMA", "Empresa Socia Eng - Inter", "Outra Conta - Banco",
                     "PESSOA COM CONTA"]
    # A própria origem nunca, nem pelo nome do cadastro; subconta de investidor nunca.
    assert not any("ORIGEM" in n.upper() or "INVESTIDOR" in n for n in lista)


def test_socios_do_cadastro_aportador_com_conta_conta_como_pessoa():
    lista = dc.socios_do_cadastro(ENTIDADES_PRINT, ROTULOS_PRINT,
                                  aportadores=["Pessoa com Conta"], origem="Origem Spe - Sicoob")
    assert lista[:3] == ["PESSOA COM CONTA", "SOCIA FICTICIA B", "SOCIO FICTICIO A"]


def test_socios_sem_origem_lista_todas_as_contas_do_painel():
    lista = dc.socios_do_cadastro(ENTIDADES_PRINT, ROTULOS_PRINT)
    assert "Origem Spe - Sicoob" in lista and "ORIGEM SPE - SICOOB" not in lista


def test_nova_distribuicao_para_conta_do_painel_e_aceita():
    assert dc.nova_distribuicao("Mae - Banco", "Filha Um - Banco", "10,00", ROTULOS,
                                ["Filha Um - Banco"]) == ("Mae - Banco", "Filha Um - Banco",
                                                          D("10.00"))
    # O SUMIF do Excel ignora maiúsculas: o texto vira o rótulo exato do painel.
    feita = dc.nova_distribuicao("Mae - Banco", "FILHA UM - BANCO", "10,00", ROTULOS)
    assert feita[1] == "Filha Um - Banco"


def test_nova_distribuicao_para_a_propria_origem_e_recusada():
    with pytest.raises(ValueError, match="origem"):
        dc.nova_distribuicao("Mae - Banco", "mae - banco", "10,00", ROTULOS)


def test_distribuicao_para_conta_do_painel_entra_no_destino():
    saldos = {"Mae - Banco": D("1000.00"), "Filha Um - Banco": D("100.00")}
    painel = ap.montar_aportes(saldos, {}, [], {},
                               distribuicoes=[("Mae - Banco", "Filha Um - Banco", D("300.00")),
                                              ("Mae - Banco", "SOCIO FICTICIO A", D("50.00"))])
    contas = {c.rotulo: c for c in painel.contas}
    assert contas["Mae - Banco"].distribui == D("350.00")
    assert contas["Mae - Banco"].saldo_final == D("650.00")
    assert contas["Filha Um - Banco"].entra_a_mao == D("300.00")
    assert contas["Filha Um - Banco"].saldo_final == D("400.00")


def test_excel_e_html_levam_a_distribuicao_para_conta_do_painel():
    from tela_do_dia import excel_do_dia as ex
    dist = [("Mae - Banco", "Filha Um - Banco", D("300.00"))]
    celulas = ex._celulas_a_mao([], set(ROTULOS), dist)
    linha = ex.PRIMEIRA_LINHA_A_MAO
    assert (celulas[f"B{linha}"], celulas[f"C{linha}"]) == ("Mae - Banco", "Filha Um - Banco")
    assert dc.movimentos_do_dia([], dist) == [
        {"de": "Mae - Banco", "para": "Filha Um - Banco", "tipo": "Distribuição de lucros",
         "valor": D("300.00")}]


def test_mandar_distribuicao_para_conta_do_painel_vai_com_as_duas_pernas():
    envio = _envio(distribuicoes=[("Mae - Banco", "Filha Um - Banco", D("300.00"))])
    (op, chaves), = envio.itens
    assert (op.pagador, op.recebedor, op.tipo, op.modo) == (
        "MAE - BANCO", "FILHA UM - BANCO", "Distribuição de Lucro", "Pagamento + Recebimento")
    assert chaves == [pa.chave_da_distribuicao("Mae - Banco", "Filha Um - Banco")]
    # Já mandado: a mesma chave segura.
    envio = _envio(distribuicoes=[("Mae - Banco", "Filha Um - Banco", D("300.00"))],
                   enviados={chaves[0]: D("300.00")})
    assert envio.itens == [] and "já mandado" in envio.pendentes[0].motivo


def test_mandar_casa_conta_do_painel_pela_conta_do_cadastro():
    """Rótulo do painel que só bate com a CONTA do cadastro (o nome é outro)."""
    (op, _), = _envio(distribuicoes=[("Mae - Banco", "Holding - Banco", D("10.00"))]).itens
    assert op.recebedor == "HOLDING FICTICIA" and op.modo == "Pagamento + Recebimento"


def test_mandar_para_conta_do_painel_sem_conta_no_cadastro_e_pendencia():
    entidades = dict(ENTIDADES, **{"FILHA UM - BANCO": {"nome_oficial": "FILHA UM LTDA",
                                                        "conta": None, "nome_descricao": None}})
    envio = pa.operacoes({}, REGRAS, entidades, SUBCONTAS, HOJE,
                         distribuicoes=[("Mae - Banco", "Filha Um - Banco", D("10.00"))],
                         contas_do_painel=ROTULOS)
    assert envio.itens == []
    (p,) = envio.pendentes
    assert "sem a conta do ERP" in p.motivo and "FILHA UM - BANCO" in p.motivo


def test_mandar_para_conta_do_painel_sem_saldo_vai_com_aviso():
    envio = _envio(distribuicoes=[("Mae - Banco", "Filha Um - Banco", D("10.00"))],
                   sem_saldo={"Filha Um - Banco"})
    (op, _), = envio.itens
    assert envio.sem_saldo == [op] and envio.avisos[0].motivo == pa.MOTIVO_SEM_SALDO


# ------------- revisão de dinheiro do 669eb6a (23/10/2026): casamento e dobro
ENTIDADES_CASA = dict(ENTIDADES, **{
    "INVESTIDOR SUBCONTA 30001-1": {"nome_oficial": "INVESTIDOR SUBCONTA 30001-1",
                                    "conta": None, "nome_descricao": None},
    "EMPRESA DELTA": {"nome_oficial": "EMPRESA DELTA LTDA", "conta": "DELTA - BANCO 30.002-2",
                      "nome_descricao": None},
    "NOME DIFERENTE": {"nome_oficial": "NOME DIFERENTE LTDA", "conta": "OUTRA CONTA - BANCO",
                       "nome_descricao": None},
    "PESSOA X": {"nome_oficial": "PESSOA X", "conta": "OUTRA CONTA - BANCO",
                 "nome_descricao": None},
    "CONTA X - BANCO": {"nome_oficial": "CONTA X LTDA", "conta": None, "nome_descricao": None},
    "OUTRO NOME": {"nome_oficial": "OUTRO NOME LTDA", "conta": "CONTA X - BANCO",
                   "nome_descricao": None},
})
SUB_DO_PAINEL = "Empresa Socia - Sicoob - Subconta 30001-1"


def _envio_casa(destino, origem="Mae - Banco", **kw):
    return pa.operacoes({}, REGRAS, ENTIDADES_CASA, SUBCONTAS, HOJE,
                        distribuicoes=[(origem, destino, D("10.00"))], **kw)


def test_casamento_nome_vence_conta_que_vence_numero():
    assert pa.casar_no_cadastro("Conta X - Banco", ENTIDADES_CASA) == pa.Casamento(
        "CONTA X - BANCO", "nome", ("CONTA X - BANCO",))
    assert pa.casar_no_cadastro("Holding - Banco", ENTIDADES_CASA).como == "conta"
    assert pa.casar_no_cadastro("Delta Nova 30002-2", ENTIDADES_CASA) == pa.Casamento(
        "EMPRESA DELTA", "numero", ("EMPRESA DELTA",))
    amb = pa.casar_no_cadastro("Outra Conta - Banco", ENTIDADES_CASA)
    assert (amb.nome, amb.como, set(amb.candidatos)) == (
        None, "ambiguo", {"NOME DIFERENTE", "PESSOA X"})


def test_distribuicao_que_so_bate_pelo_numero_e_pendencia():
    envio = _envio_casa("Delta Nova 30002-2")
    assert envio.itens == []
    assert "só o número bate" in envio.pendentes[0].motivo


def test_distribuicao_para_subconta_de_investidor_e_pendencia():
    for destino in ("INVESTIDOR SUBCONTA 30001-1", SUB_DO_PAINEL):
        envio = _envio_casa(destino)
        assert envio.itens == [], destino
        assert "subconta de investidor" in envio.pendentes[0].motivo, destino


def test_distribuicao_ambigua_no_cadastro_e_pendencia():
    envio = _envio_casa("Outra Conta - Banco")
    assert envio.itens == []
    motivo = envio.pendentes[0].motivo
    assert "mais de um" in motivo and "NOME DIFERENTE" in motivo and "PESSOA X" in motivo


def test_lista_para_tira_a_subconta_de_investidor_do_painel_pelo_numero():
    lista = dc.socios_do_cadastro(ENTIDADES_CASA, ["Mae - Banco", SUB_DO_PAINEL],
                                  origem="Mae - Banco")
    assert SUB_DO_PAINEL not in lista
    assert not any(n.startswith("INVESTIDOR") for n in lista)


def test_lista_para_com_conta_ambigua_mostra_os_dois_nomes():
    lista = dc.socios_do_cadastro(ENTIDADES_CASA, ["Mae - Banco", "Outra Conta - Banco"],
                                  origem="Mae - Banco")
    assert {"NOME DIFERENTE", "PESSOA X", "Outra Conta - Banco"} <= set(lista)


def test_lista_para_esconde_so_quem_casou_pelo_nome():
    lista = dc.socios_do_cadastro(ENTIDADES_CASA, ["Mae - Banco", "Conta X - Banco"],
                                  origem="Mae - Banco")
    assert "Conta X - Banco" in lista and "CONTA X - BANCO" not in lista
    assert "OUTRO NOME" in lista


REGRAS_DIST = [Regra("Filha Um - Banco", "Mae - Banco", None, "Distribuição", True, linha=3)]
DEFINIDOS_DIST = {("Filha Um - Banco", "Mae - Banco"): D("300.00")}


def test_nova_distribuicao_recusa_o_par_que_ja_vem_da_aba_regras():
    with pytest.raises(ValueError, match=r"já vem da aba Regras \(R\$ 300,00\)"):
        dc.nova_distribuicao("Mae - Banco", "Filha Um - Banco", "10,00", ROTULOS,
                             definidos=DEFINIDOS_DIST, regras=REGRAS_DIST)
    # Sem valor definido na Regras, ou outro par: segue.
    assert dc.nova_distribuicao("Mae - Banco", "Filha Um - Banco", "10,00", ROTULOS,
                                definidos={}, regras=REGRAS_DIST)[2] == D("10.00")


def test_envio_nao_manda_a_mao_o_par_que_ja_vem_da_aba_regras():
    envio = pa.operacoes(DEFINIDOS_DIST, REGRAS_DIST, ENTIDADES, SUBCONTAS, HOJE,
                         distribuicoes=[("Mae - Banco", "Filha Um - Banco", D("300.00"))])
    chave = pa.chave_da_distribuicao("Mae - Banco", "Filha Um - Banco")
    assert all(chave not in chaves for _op, chaves in envio.itens)
    assert any("aba Regras" in p.motivo and "distribuição de lucros" in p.destino
               for p in envio.pendentes)


# ---------------------- revisão de dinheiro de 22/10/2026 (A4, A5) e geral
SUB = "44444-4"
DESTINO_SUB = "Filha Dois - Subconta 44444-4"
INV_UM, INV_DOIS = "PESSOA FICTICIA UM SOBRENOME", "PESSOA FICTICIA DOIS SOBRENOME"
#: A mesma subconta pelas duas portas: uma linha composta e uma por investidor.
REGRAS_SUB = [
    Regra("Filha Dois - Banco", "Pessoa Um/Pessoa Dois", None, "Aporte", False, linha=6),
    Regra(DESTINO_SUB, INV_UM, None, "Aporte", False, linha=7),
    Regra(DESTINO_SUB, INV_DOIS, None, "Aporte", False, linha=8),
]
ENTIDADES_SUB = dict(ENTIDADES, **{
    "FILHA DOIS - SUBCONTA 44444-4": {"nome_oficial": "FILHA DOIS SUB LTDA",
                                      "conta": "FILHA DOIS - SUBCONTA 44.444-4",
                                      "nome_descricao": None}})


def _envio_sub(definidos, enviados=None):
    return pa.operacoes(definidos, REGRAS_SUB, ENTIDADES_SUB, SUBCONTAS, HOJE,
                        enviados=enviados)


def test_a4_chave_da_subconta_e_pelo_numero_nos_dois_ramos():
    composto = _envio_sub({("Filha Dois - Banco", "Pessoa Um/Pessoa Dois"): D("5000.00")})
    (_op, chaves), = composto.itens
    assert chaves == [pa.chave_da_subconta(SUB, "Filha Dois - Banco")]
    assert composto.valores == {chaves[0]: D("5000.00")}
    por_investidor = _envio_sub({(DESTINO_SUB, INV_UM): D("100.00"),
                                 (DESTINO_SUB, INV_DOIS): D("100.00")})
    (_op, chaves), = por_investidor.itens
    assert chaves == [pa.chave_da_subconta(SUB, DESTINO_SUB)]
    assert por_investidor.valores == {chaves[0]: D("200.00")}
    assert pa.chave_da_subconta(SUB, "X").startswith(f"subconta:{SUB}|")


def test_a4_composto_ja_mandado_segura_a_linha_por_investidor_e_vice_versa():
    """A aba Regras mudou de composto para uma linha por investidor (ou o
    contrário) no mesmo dia: a subconta é a mesma, e o aporte não vai de novo."""
    enviados = {pa.chave_da_subconta(SUB, "Filha Dois - Banco"): D("5000.00")}
    # A mesma subconta, chave pelo número: vale para qualquer rótulo do destino.
    envio = pa.operacoes({(DESTINO_SUB, INV_UM): D("100.00"),
                          (DESTINO_SUB, INV_DOIS): D("100.00")},
                         REGRAS_SUB, ENTIDADES_SUB, SUBCONTAS, HOJE,
                         enviados={pa.chave_da_subconta(SUB, DESTINO_SUB): D("200.00")})
    assert envio.itens == [] and all("já mandado" in p.motivo for p in envio.pendentes)
    envio = _envio_sub({("Filha Dois - Banco", "Pessoa Um/Pessoa Dois"): D("5000.00")},
                       enviados=enviados)
    assert envio.itens == [] and "já mandado" in envio.pendentes[0].motivo


def test_a4_ja_mandado_por_qualquer_destino_da_mesma_subconta():
    """O rótulo do destino muda entre as duas portas; o número não."""
    enviados = {pa.chave_da_subconta(SUB, "Filha Dois - Banco"): D("200.00")}
    envio = _envio_sub({(DESTINO_SUB, INV_UM): D("100.00"),
                        (DESTINO_SUB, INV_DOIS): D("100.00")}, enviados=enviados)
    assert envio.itens == [] and len(envio.pendentes) == 2
    assert all(p.motivo.startswith("já mandado") for p in envio.pendentes)
    enviados = {pa.chave_da_subconta(SUB, DESTINO_SUB): D("200.00")}
    envio = _envio_sub({("Filha Dois - Banco", "Pessoa Um/Pessoa Dois"): D("200.00")},
                       enviados=enviados)
    assert envio.itens == [] and envio.pendentes[0].motivo.startswith("já mandado")


def test_a4_chaves_antigas_do_json_do_dia_continuam_segurando():
    # composto gravado com a chave velha "destino|Fulano/Beltrano"
    velha = pa.chave_de_envio("Filha Dois - Banco", "Pessoa Um/Pessoa Dois")
    envio = _envio_sub({("Filha Dois - Banco", "Pessoa Um/Pessoa Dois"): D("5000.00")},
                       enviados={velha: D("5000.00")})
    assert envio.itens == [] and "já mandado" in envio.pendentes[0].motivo
    # e a velha do composto segura a linha por investidor da mesma subconta
    envio = _envio_sub({(DESTINO_SUB, INV_UM): D("100.00"),
                        (DESTINO_SUB, INV_DOIS): D("100.00")}, enviados={velha: D("5000.00")})
    assert envio.itens == []
    # por investidor gravado com a chave velha "destino|investidor"
    velha_inv = pa.chave_de_envio(DESTINO_SUB, INV_UM)
    envio = _envio_sub({(DESTINO_SUB, INV_UM): D("100.00"),
                        (DESTINO_SUB, INV_DOIS): D("100.00")},
                       enviados={velha_inv: D("100.00")})
    assert envio.itens == [] and len(envio.pendentes) == 2
    envio = _envio_sub({("Filha Dois - Banco", "Pessoa Um/Pessoa Dois"): D("200.00")},
                       enviados={velha_inv: D("100.00")})
    assert envio.itens == []


def test_a5_composto_que_nao_e_aporte_vira_pendencia_clara():
    regras = [Regra("Filha Dois - Banco", "Pessoa Um/Pessoa Dois", None,
                    "Distribuição de lucros", False, linha=6)]
    envio = pa.operacoes({("Filha Dois - Banco", "Pessoa Um/Pessoa Dois"): D("10.00")},
                         regras, ENTIDADES, SUBCONTAS, HOJE)
    assert envio.itens == []
    (p,) = envio.pendentes
    assert "Distribuição de lucros" in p.motivo and "aporte" in p.motivo


def test_transferencia_com_destino_em_subconta_e_informativo():
    regras = [Regra(DESTINO_SUB, "Mae - Banco", None, "Transferência", False, linha=6)]
    envio = pa.operacoes({(DESTINO_SUB, "Mae - Banco"): D("10.00")}, regras,
                         ENTIDADES_SUB, SUBCONTAS, HOJE)
    assert envio.itens == [] and envio.pendentes == []
    (info,) = envio.informativos
    assert info.motivo == pa.TRANSFERENCIA


def test_distribuicao_de_origem_sem_conta_no_cadastro_e_pendencia_clara():
    """Revisão geral de 22/10/2026, achado 5: a origem é conta da empresa no
    painel, então o dinheiro SAI dela. Cadastro sem a conta não vira "Só
    recebimento" (que lançaria só a entrada do sócio): é pendência que diz o
    que completar."""
    entidades = dict(ENTIDADES, **{"MAE - BANCO": {"nome_oficial": "MAE FICTICIA LTDA",
                                                   "conta": None, "nome_descricao": None}})
    envio = pa.operacoes({}, REGRAS, entidades, SUBCONTAS, HOJE,
                         distribuicoes=[("Mae - Banco", "SOCIO FICTICIO A", D("100.00"))])
    assert envio.itens == []
    (p,) = envio.pendentes
    assert "sem a conta do ERP" in p.motivo and "MAE - BANCO" in p.motivo


# ------------- revisão geral de 22/10/2026, achado 1: nenhum fica para trás
REGRAS_HTML = [
    Regra("Filha Um - Banco", "Mae - Banco", None, "Aporte", True, linha=5),
    Regra("Filha Dois - Banco", "Pessoa Um/Pessoa Dois", None, "Aporte", False, linha=6),
    Regra("Mae - Banco", "Socio Ficticio A", None, "Aporte", False, linha=7),
    Regra("Filha Um - Banco", "Holding - Banco", None, "Transferência", True, linha=9),
]
ROTULOS_HTML = ["Mae - Banco", "Filha Um - Banco", "Filha Dois - Banco", "Holding - Banco"]


def test_html_leva_os_aportes_e_transferencias_da_aba_regras():
    """O pedido do dono: "as transf e aportes e distribuições … criar o
    lançamento no html tb … pra não ficar nenhum pra trás" — os da aba
    Regras (o composto e a transferência do print) também."""
    definidos = {("Filha Um - Banco", "Mae - Banco"): D("300.00"),
                 ("Filha Dois - Banco", "Pessoa Um/Pessoa Dois"): D("5000.00"),
                 ("Filha Um - Banco", "Holding - Banco"): D("10000.00")}
    movs = dc.movimentos_do_dia([], [], definidos=definidos, regras=REGRAS_HTML,
                                rotulos=ROTULOS_HTML)
    assert movs == [
        {"de": "Mae - Banco", "para": "Filha Um - Banco", "tipo": dc.TIPO_APORTE_REGRAS,
         "valor": D("300.00")},
        {"de": "Pessoa Um/Pessoa Dois", "para": "Filha Dois - Banco",
         "tipo": dc.TIPO_APORTE_REGRAS, "valor": D("5000.00")},
        {"de": "Holding - Banco", "para": "Filha Um - Banco",
         "tipo": dc.TIPO_TRANSFERENCIA, "valor": D("10000.00")},
    ]


def test_html_nao_duplica_o_movimento_que_esta_nos_dois():
    definidos = {("Filha Um - Banco", "Mae - Banco"): D("300.00"),
                 ("Mae - Banco", "Socio Ficticio A"): D("50.00")}
    a_mao = [("Mae - Banco", "Filha Um - Banco", D("300.00")),   # a mesma transferência
             (None, "Mae - Banco", D("50.00")),                  # o mesmo aporte de fora
             (None, "Mae - Banco", D("70.00"))]                  # outro: fica
    movs = dc.movimentos_do_dia(a_mao, [("Mae - Banco", "SOCIO FICTICIO A", D("1.00"))],
                                definidos=definidos, regras=REGRAS_HTML, rotulos=ROTULOS_HTML)
    assert [(m["de"], m["para"], m["valor"]) for m in movs] == [
        ("Mae - Banco", "Filha Um - Banco", D("300.00")),
        ("Socio Ficticio A", "Mae - Banco", D("50.00")),
        (dc.DE_FORA, "Mae - Banco", D("70.00")),
        ("Mae - Banco", "SOCIO FICTICIO A", D("1.00")),
    ]


def test_html_sem_definidos_continua_igual():
    a_mao = [(None, "Mae - Banco", D("400.00"))]
    assert dc.movimentos_do_dia(a_mao, []) == dc.movimentos_do_dia(
        a_mao, [], definidos={}, regras=REGRAS_HTML, rotulos=ROTULOS_HTML)


def test_html_ignora_definido_zero_negativo_ou_fora_da_regra():
    definidos = {("Filha Um - Banco", "Mae - Banco"): D("0.00"),
                 ("Mae - Banco", "Socio Ficticio A"): D("-5.00"),
                 ("Filha Um - Banco", "Desconhecido"): D("9.00")}
    assert dc.movimentos_do_dia([], [], definidos=definidos, regras=REGRAS_HTML,
                                rotulos=ROTULOS_HTML) == []
