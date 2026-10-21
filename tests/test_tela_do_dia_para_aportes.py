"""Da tela do dia para a aba Aportes. Cadastro fictício."""
from datetime import date
from decimal import Decimal as D

from aportes.regras import TIPO_INVESTIDOR
from conciliacao.aportadores import Regra
from tela_do_dia import para_aportes as pa

HOJE = date(2026, 10, 21)
ENTIDADES = {
    "MAE - BANCO": {"nome_oficial": "MAE FICTICIA LTDA", "conta": "MAE - BANCO", "nome_descricao": None},
    "FILHA UM - BANCO": {"nome_oficial": "FILHA UM LTDA", "conta": "FILHA UM - BANCO", "nome_descricao": None},
    "SOCIO FICTICIO A": {"nome_oficial": "SOCIO FICTICIO A", "conta": None, "nome_descricao": None},
    "SOCIO FICTICIO B": {"nome_oficial": "SOCIO FICTICIO B", "conta": None, "nome_descricao": None},
    "HOLDING - SUBCONTA 33333-3": {"nome_oficial": "HOLDING FICTICIA", "conta": "HOLDING - SUBCONTA 33.333-3",
                                   "nome_descricao": None},
}
SUBCONTAS = {"33333-3": {"obras": ["OBRA MODELO"], "investidores": ["INVESTIDOR X", "INVESTIDOR Y"],
                         "pesos": {"INVESTIDOR X": 1, "INVESTIDOR Y": 1}}}
REGRAS = [
    Regra("Filha Um - Banco", "Mae - Banco", None, "Aporte", True, linha=5),
    Regra("Mae - Banco", "Socio Ficticio A", None, "Aporte", False, linha=6),
    Regra("Holding - Subconta 33333-3", "INVESTIDOR X", None, "Aporte", False, linha=7),
    Regra("Holding - Subconta 33333-3", "INVESTIDOR Y", None, "Aporte", False, linha=8),
    Regra("Filha Um - Banco", "Desconhecido Ficticio", None, "Aporte", False, linha=9),
    Regra("Mae - Banco", "Socio Ficticio", None, "Aporte", False, linha=10),
]


def _envio(definidos, enviados=None, sem_saldo=()):
    return pa.operacoes(definidos, REGRAS, ENTIDADES, SUBCONTAS, HOJE, enviados=enviados,
                        sem_saldo=sem_saldo)


def test_conta_do_painel_para_conta_do_painel_e_pagamento_mais_recebimento():
    envio = _envio({("Filha Um - Banco", "Mae - Banco"): D("300.00")})
    (op, chaves), = envio.itens
    assert (op.pagador, op.recebedor, op.valor, op.tipo, op.modo) == (
        "MAE - BANCO", "FILHA UM - BANCO", D("300.00"), "Aporte de Capital", "Pagamento + Recebimento")
    assert chaves == [pa.chave_de_envio("Filha Um - Banco", "Mae - Banco")]
    assert envio.valores == {chaves[0]: D("300.00")}
    assert op.validar(ENTIDADES, SUBCONTAS) == []
    assert envio.pendentes == []


def test_chave_de_envio_nao_leva_o_valor():
    assert pa.chave_de_envio("Filha Um - Banco", "Mae - Banco") == "Filha Um - Banco|Mae - Banco"


def test_socio_pessoa_fisica_e_so_recebimento():
    (op, _), = _envio({("Mae - Banco", "Socio Ficticio A"): D("50.00")}).itens
    assert op.modo == "Só recebimento"


def test_nome_que_o_cadastro_nao_tem_vira_pendencia_e_nunca_chute():
    envio = _envio({("Filha Um - Banco", "Desconhecido Ficticio"): D("10.00")})
    assert envio.itens == [] and "não achei" in envio.pendentes[0].motivo


def test_nome_incompleto_nao_casa_com_quem_comeca_igual():
    # "Socio Ficticio" não é "Socio Ficticio A" nem "Socio Ficticio B":
    # nome completo, sem chute pelo começo.
    assert pa.nome_no_cadastro("Socio Ficticio", ENTIDADES) is None
    envio = _envio({("Mae - Banco", "Socio Ficticio"): D("10.00")})
    assert envio.itens == [] and "não achei" in envio.pendentes[0].motivo


def test_nome_no_cadastro_casa_por_nome_completo_ou_numero_da_conta():
    assert pa.nome_no_cadastro("Socio Ficticio A", ENTIDADES) == "SOCIO FICTICIO A"
    assert pa.nome_no_cadastro("mãe - banco", ENTIDADES) == "MAE - BANCO"
    assert pa.nome_no_cadastro("Qualquer Coisa 33.333-3", ENTIDADES) == "HOLDING - SUBCONTA 33333-3"


def test_subconta_de_investidor_vira_uma_operacao_quando_a_divisao_bate():
    envio = _envio({("Holding - Subconta 33333-3", "INVESTIDOR X"): D("500.00"),
                    ("Holding - Subconta 33333-3", "INVESTIDOR Y"): D("500.00")})
    (op, chaves), = envio.itens
    assert (op.pagador, op.recebedor, op.valor, op.tipo, op.modo) == (
        "INVESTIDOR SUBCONTA 33333-3", "HOLDING - SUBCONTA 33333-3", D("1000.00"),
        TIPO_INVESTIDOR, "Só recebimento")
    assert len(chaves) == 2 and op.validar(ENTIDADES, SUBCONTAS) == []
    assert envio.valores == {chaves[0]: D("500.00"), chaves[1]: D("500.00")}


def test_subconta_com_divisao_diferente_do_cadastro_vira_pendencia():
    envio = _envio({("Holding - Subconta 33333-3", "INVESTIDOR X"): D("600.00"),
                    ("Holding - Subconta 33333-3", "INVESTIDOR Y"): D("400.00")})
    assert envio.itens == [] and len(envio.pendentes) == 2
    assert all("divisão" in p.motivo for p in envio.pendentes)


def test_o_que_ja_foi_mandado_nao_vai_de_novo():
    chave = pa.chave_de_envio("Filha Um - Banco", "Mae - Banco")
    envio = _envio({("Filha Um - Banco", "Mae - Banco"): D("300.00")}, enviados={chave: D("300.00")})
    assert envio.itens == [] and envio.pendentes[0].motivo.startswith("já mandado")


def test_valor_corrigido_depois_de_mandado_vira_pendencia_e_nao_segunda_operacao():
    chave = pa.chave_de_envio("Filha Um - Banco", "Mae - Banco")
    envio = _envio({("Filha Um - Banco", "Mae - Banco"): D("350.00")}, enviados={chave: D("300.00")})
    assert envio.itens == []
    (p,) = envio.pendentes
    assert p.valor == D("350.00")
    assert p.motivo.startswith("já mandado R$ 300,00 hoje; agora R$ 350,00")
    assert "aba Aportes" in p.motivo


def test_investidor_ja_mandado_segura_a_subconta_inteira():
    chave_x = pa.chave_de_envio("Holding - Subconta 33333-3", "INVESTIDOR X")
    envio = _envio({("Holding - Subconta 33333-3", "INVESTIDOR X"): D("500.00"),
                    ("Holding - Subconta 33333-3", "INVESTIDOR Y"): D("500.00")},
                   enviados={chave_x: D("500.00")})
    assert envio.itens == [] and len(envio.pendentes) == 2
    assert all(p.motivo.startswith("já mandado") for p in envio.pendentes)


def test_conta_sem_saldo_do_sistema_vai_com_pendencia_marcada():
    envio = _envio({("Filha Um - Banco", "Mae - Banco"): D("300.00")}, sem_saldo={"Filha Um - Banco"})
    assert len(envio.itens) == 1
    (p,) = envio.pendentes
    assert p.motivo == pa.MOTIVO_SEM_SALDO and p.destino == "Filha Um - Banco"
    assert envio.sem_saldo == [0]


def test_aportador_sem_saldo_do_sistema_tambem_marca_pendencia():
    envio = _envio({("Filha Um - Banco", "Mae - Banco"): D("300.00")}, sem_saldo={"Mae - Banco"})
    assert [p.motivo for p in envio.pendentes] == [pa.MOTIVO_SEM_SALDO]
    assert envio.sem_saldo == [0]


def test_marcar_enviados_guarda_o_valor_so_das_aceitas():
    envio = _envio({("Filha Um - Banco", "Mae - Banco"): D("300.00"),
                    ("Mae - Banco", "Socio Ficticio A"): D("50.00")})
    enviados = {}
    pa.marcar_enviados(envio, [(1, "recusada")], enviados)
    assert enviados == {pa.chave_de_envio("Filha Um - Banco", "Mae - Banco"): D("300.00")}
