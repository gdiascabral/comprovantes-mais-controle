"""Aportes do dia. Contas e sócios fictícios."""
from decimal import Decimal as D

from conciliacao.aportadores import Regra
from tela_do_dia import aportes as ap

REGRAS = [
    Regra("Filha Um - Banco", "Mae - Banco", None, "Aporte", True, linha=5),
    Regra("Filha Dois - Banco", "Mae - Banco", D("2"), "Aporte", True, linha=6),
    Regra("Filha Dois - Banco", "Socio Ficticio B", D("1"), "Aporte", False, linha=7),
    Regra("Mae - Banco", "Socio Ficticio A", D("1"), "Aporte", False, linha=8),
    Regra("Mae - Banco", "Socio Ficticio B", D("1"), "Aporte", False, linha=9),
]
SALDOS = {"Mae - Banco": D("1000.00"), "Filha Um - Banco": D("100.00"),
          "Filha Dois - Banco": D("0.00"), "Sobra - Banco": D("50.00")}
A_PAGAR = {"Mae - Banco": D("500.00"), "Filha Um - Banco": D("400.00"),
           "Filha Dois - Banco": D("300.00")}


def _por(painel):
    return {c.rotulo: c for c in painel.contas}


def test_a_conta_mae_e_a_que_mais_aporta_nas_outras():
    assert ap.conta_mae(REGRAS) == "Mae - Banco"
    assert ap.conta_mae([]) is None


def test_minimo_sugestao_e_falta_ratear_sem_nada_definido():
    painel = ap.montar_aportes(SALDOS, A_PAGAR, REGRAS, {})
    assert [c.rotulo for c in painel.contas] == ["Mae - Banco", "Filha Um - Banco", "Filha Dois - Banco"]
    contas = _por(painel)
    assert contas["Filha Um - Banco"].minimo == D("300.00")
    assert contas["Filha Um - Banco"].sugestao == {}                       # sem peso, o rateio é do dono
    assert contas["Filha Dois - Banco"].sugestao == {"Mae - Banco": D("200.00"), "Socio Ficticio B": D("100.00")}
    assert contas["Filha Dois - Banco"].falta_ratear == D("300.00")
    assert contas["Mae - Banco"].minimo == D("0.00") and contas["Mae - Banco"].saldo_final == D("500.00")


def test_o_que_a_mae_manda_entra_no_minimo_e_no_saldo_final_dela():
    definidos = {("Filha Um - Banco", "Mae - Banco"): D("300.00"),
                 ("Filha Dois - Banco", "Mae - Banco"): D("200.00"),
                 ("Filha Dois - Banco", "Socio Ficticio B"): D("100.00")}
    contas = _por(ap.montar_aportes(SALDOS, A_PAGAR, REGRAS, definidos))
    assert contas["Mae - Banco"].sai == D("500.00")
    assert contas["Mae - Banco"].saldo_final == D("0.00")
    assert contas["Filha Dois - Banco"].falta_ratear == D("0.00")
    assert contas["Filha Dois - Banco"].saldo_final == D("0.00")


def test_mae_negativa_da_alerta_forte_e_sobra_aparece():
    painel = ap.montar_aportes(SALDOS, A_PAGAR, REGRAS, {("Filha Um - Banco", "Mae - Banco"): D("800.00")})
    contas = _por(painel)
    assert contas["Mae - Banco"].saldo_final == D("-300.00")
    assert contas["Filha Um - Banco"].sobra == D("500.00")
    fortes = [f for tag, f in painel.alertas if tag == "erro"]
    assert len(fortes) == 1 and "Mae - Banco" in fortes[0] and "NEGATIVA" in fortes[0]


def test_valor_de_quem_nao_esta_na_aba_regras_nao_conta_e_avisa():
    painel = ap.montar_aportes(SALDOS, A_PAGAR, REGRAS, {("Filha Um - Banco", "Intruso Ficticio"): D("10.00")})
    assert painel.definidos_validos == {}
    assert any("Intruso Ficticio" in f for _t, f in painel.alertas)


def test_peso_zero_nao_quebra_so_nao_sugere():
    regras = [Regra("Filha Um - Banco", "Mae - Banco", D("0"), "Aporte", True, linha=5)]
    assert _por(ap.montar_aportes(SALDOS, A_PAGAR, regras, {}))["Filha Um - Banco"].sugestao == {}


# --- acréscimos do coordenador (preflight C2a) e das regras do dono ---------

def test_saldo_que_o_sistema_nao_trouxe_nao_vira_zero():
    saldos = {**SALDOS, "Filha Dois - Banco": None}
    painel = ap.montar_aportes(saldos, A_PAGAR, REGRAS, {})
    conta = _por(painel)["Filha Dois - Banco"]           # continua visível na tela
    assert conta.sem_saldo
    assert conta.minimo == D("0.00")                     # não calculado (seria 300 sobre zero)
    assert conta.sugestao == {}                          # fora da sugestão
    assert conta.falta_ratear == D("0.00")
    erros = [f for tag, f in painel.alertas if tag == "erro"]
    assert erros == ["Filha Dois - Banco: o sistema não trouxe o saldo — o mínimo não é calculado"]
    assert not any("falta ratear" in f and "Filha Dois" in f for _t, f in painel.alertas)


def test_conta_sem_saldo_e_sem_pagamento_tambem_avisa():
    painel = ap.montar_aportes({"Parada - Banco": None}, {}, [], {})
    assert [c.rotulo for c in painel.contas] == ["Parada - Banco"]
    assert painel.alertas == [("erro", "Parada - Banco: o sistema não trouxe o saldo — o mínimo não é calculado")]


def test_aportadores_de_mesmo_primeiro_nome_sao_pessoas_diferentes():
    regras = [
        Regra("Filha Um - Banco", "Joana Ficticia Lima", D("1"), "Aporte", False, linha=5),
        Regra("Filha Um - Banco", "Joana Ficticia Rocha", D("3"), "Aporte", False, linha=6),
        Regra("Filha Dois - Banco", "Joana Ficticia Lima", None, "Aporte", False, linha=7),
    ]
    definidos = {("Filha Um - Banco", "Joana Ficticia Rocha"): D("100.00"),
                 ("Filha Dois - Banco", "Joana Ficticia Rocha"): D("50.00"),   # Rocha não aporta na Dois
                 ("Filha Dois - Banco", "Joana"): D("20.00")}                  # primeiro nome não casa
    painel = ap.montar_aportes(SALDOS, A_PAGAR, regras, definidos)
    assert painel.definidos_validos == {("Filha Um - Banco", "Joana Ficticia Rocha"): D("100.00")}
    contas = _por(painel)
    assert contas["Filha Um - Banco"].sugestao == {"Joana Ficticia Lima": D("75.00"),
                                                   "Joana Ficticia Rocha": D("225.00")}
    assert contas["Filha Um - Banco"].definidos == {"Joana Ficticia Rocha": D("100.00")}
    assert contas["Filha Dois - Banco"].definido == D("0.00")
    ignorados = [f for _t, f in painel.alertas if "ignorado" in f]
    assert len(ignorados) == 2
    assert any("Joana Ficticia Rocha → Filha Dois - Banco" in f for f in ignorados)
    assert any(f.startswith("Joana → Filha Dois - Banco") for f in ignorados)


def test_valor_negativo_nao_conta_e_avisa():
    painel = ap.montar_aportes(SALDOS, A_PAGAR, REGRAS, {("Filha Um - Banco", "Mae - Banco"): D("-50.00")})
    assert painel.definidos_validos == {}
    assert _por(painel)["Mae - Banco"].sai == D("0.00")
    assert any("negativo" in f for _t, f in painel.alertas)


def test_tudo_e_decimal():
    contas = ap.montar_aportes(SALDOS, A_PAGAR, REGRAS, {("Filha Um - Banco", "Mae - Banco"): D("300.00")}).contas
    for c in contas:
        for v in (c.minimo, c.definido, c.falta_ratear, c.sobra, c.saldo_final, c.sai, *c.sugestao.values()):
            assert isinstance(v, D)
