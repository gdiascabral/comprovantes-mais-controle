# tests/test_tela_do_dia_controle.py
# -*- coding: utf-8 -*-
"""Controle de aportes (`tela_do_dia/controle_aportes.py`). Sem tela, sem rede.

Nomes fictícios: o repositório é público. Os dois aportadores têm o MESMO
primeiro nome de propósito — são pessoas diferentes e nunca se misturam."""
import datetime
from dataclasses import replace
from decimal import Decimal

import pytest

from tela_do_dia import controle_aportes as ca

D = Decimal
ZERO = D("0.00")
ABRE = datetime.date(2026, 10, 21)
HOJE = datetime.date(2026, 10, 23)
ALFA, BETA = "FULANO ALFA DA SILVA", "FULANO BETA SOUZA"


def _conta(alfa_abertura="40000.00", beta_abertura="0.00", pesos=("1", "1")):
    return ca.ContaControlada(
        conta_erp="CONTA MAE - BANCO", abertura=ABRE, id=1, aportadores=(
            ca.Aportador(ALFA, D(pesos[0]), D(alfa_abertura), id=10),
            ca.Aportador(BETA, D(pesos[1]), D(beta_abertura), id=11)))


def _rec(ident, valor, cliente, data=HOJE):
    return ca.Recebimento(id=ident, data=data, valor=D(valor), cliente=cliente)


def test_recebimento_do_erp_le_os_campos_que_a_aba_contratos_ja_le():
    r = ca.recebimento_do_erp(
        {"id": "r1", "dateOfReceipt": "2026-10-22T00:00:00", "sumOfReceivedValues": 1500.5,
         "customerName": f" {ALFA} ", "description": "APORTE CAPITAL - X PARA Y",
         "workName": "CENTRO FICTICIO"}, "Aporte de Capital")
    assert r == ca.Recebimento(id="r1", data=datetime.date(2026, 10, 22), valor=D("1500.50"),
                               cliente=ALFA, natureza="Aporte de Capital",
                               descricao="APORTE CAPITAL - X PARA Y", centro="CENTRO FICTICIO")


@pytest.mark.parametrize("item", [
    {"dateOfReceipt": "2026-10-22", "sumOfReceivedValues": 1},
    {"id": "r", "sumOfReceivedValues": 1},
    {"id": "r", "dateOfReceipt": "2026-10-22"},
    {"id": "r", "dateOfReceipt": "2026-10-22", "sumOfReceivedValues": "abc"},
    {"id": "r", "dateOfReceipt": "2026-10-22", "sumOfReceivedValues": float("nan")},
    {"id": "r", "dateOfReceipt": "2026-10-22", "sumOfReceivedValues": True},
])
def test_recebimento_ilegivel_levanta_e_nunca_vira_zero(item):
    with pytest.raises(ValueError):
        ca.recebimento_do_erp(item)


def test_problemas_da_conta():
    assert ca.problemas_da_conta(_conta(), HOJE) == []
    assert ca.problemas_da_conta(_conta(), HOJE, [_conta()]) == []   # ela mesma não é outra
    texto = lambda c, outras=(): " ".join(ca.problemas_da_conta(c, HOJE, outras))  # noqa: E731
    assert "depois de hoje" in texto(replace(_conta(), abertura=HOJE + datetime.timedelta(days=1)))
    assert "repetido" in texto(replace(_conta(), aportadores=(
        ca.Aportador(ALFA, D(1)), ca.Aportador("fulano álfa da  silva", D(1)))))
    assert "Falta aportador" in texto(replace(_conta(), aportadores=()))
    assert "Proporção" in texto(replace(_conta(), aportadores=(
        ca.Aportador(ALFA, D(0)), ca.Aportador(BETA, D(1)))))
    assert "Proporção" in texto(replace(_conta(), aportadores=(
        ca.Aportador(ALFA, None), ca.Aportador(BETA, D(1)))))
    assert "inválido" in texto(_conta(alfa_abertura="-1.00"))
    assert "já está no controle" in texto(replace(_conta(), id=2), [_conta()])
    assert "nome da conta" in texto(replace(_conta(), conta_erp="  "))


def test_aberturas_para_divida_meio_a_meio():
    assert ca.aberturas_para_divida(_conta().aportadores, "Fulano Beta  Souza", D("40000")) \
        == {ALFA: D("40000.00"), BETA: ZERO}


def test_aberturas_para_divida_recusa_primeiro_nome_e_negativo():
    with pytest.raises(ValueError):
        ca.aberturas_para_divida(_conta().aportadores, "FULANO", D("1"))
    with pytest.raises(ValueError):
        ca.aberturas_para_divida(_conta().aportadores, BETA, D("-1"))


def test_so_a_abertura_quem_esta_em_dia_nao_deve_e_o_outro_deve_tudo():
    ap = ca.apurar(_conta(), [], [], HOJE)
    a, b = ap.linhas
    assert (a.aportou, a.deveria, a.diferenca) == (D("40000.00"), D("40000.00"), ZERO)
    assert (b.aportou, b.deveria, b.diferenca) == (ZERO, D("40000.00"), D("40000.00"))
    assert ca.resumo(ap) == [f"CONTA MAE - BANCO: {BETA} deve R$ 40.000,00 para igualar."]
    assert [str(l.parte) for l in ap.linhas] == ["50.00", "50.00"]


def test_aporte_do_devedor_abate_e_o_que_passa_vira_divida_do_outro():
    ap = ca.apurar(_conta(), [_rec("r1", "20000.00", BETA)], [], HOJE)
    assert ap.linhas[1].diferenca == D("20000.00") and ap.total == D("60000.00")
    ap = ca.apurar(_conta(), [_rec("r1", "60000.00", BETA)], [], HOJE)
    assert [l.diferenca for l in ap.linhas] == [D("20000.00"), ZERO]
    assert ca.situacao_do_aportador(ap.linhas[1]) == "em dia"


def test_primeiro_nome_nao_casa_e_vai_para_sem_dono():
    ap = ca.apurar(_conta(), [_rec("r1", "100.00", "FULANO"),
                              _rec("r2", "100.00", "Fulano Álfa da  Silva")], [], HOJE)
    assert [s.recebimento.id for s in ap.sem_dono] == ["r1"]
    assert "não é aportador" in ap.sem_dono[0].motivo
    assert (ap.linhas[0].do_erp, ap.linhas[1].do_erp) == (D("100.00"), ZERO)


def test_dois_aportadores_de_mesmo_primeiro_nome_nao_se_misturam():
    ap = ca.apurar(_conta(), [_rec("r1", "10.00", BETA), _rec("r2", "5.00", ALFA)], [], HOJE)
    assert [l.do_erp for l in ap.linhas] == [D("5.00"), D("10.00")]


def test_sem_cliente_e_valor_zero_vao_para_sem_dono():
    ap = ca.apurar(_conta(), [_rec("r1", "10.00", ""), _rec("r2", "0.00", ALFA)], [], HOJE)
    motivos = {s.recebimento.id: s.motivo for s in ap.sem_dono}
    assert "sem Cliente" in motivos["r1"] and "zero" in motivos["r2"]
    assert ap.linhas[0].do_erp == ZERO
    assert any("sem dono" in linha for linha in ca.resumo(ap))


def test_fora_do_periodo_nao_entra():
    ap = ca.apurar(_conta(), [_rec("r1", "10.00", BETA, ABRE - datetime.timedelta(days=1)),
                              _rec("r2", "10.00", BETA, HOJE + datetime.timedelta(days=1)),
                              _rec("r3", "10.00", BETA, ABRE)], [], HOJE)
    assert ap.linhas[1].do_erp == D("10.00")


def test_parcela_repetida_para_a_conta():
    ap = ca.apurar(_conta(), [_rec("r1", "10.00", BETA), _rec("r1", "10.00", BETA)], [], HOJE)
    assert "duas vezes" in ap.erro and ap.linhas == []


def test_apontamento_conta_para_quem_foi_apontado():
    p = ca.Apontamento("r1", 11, D("100.00"), "pix por outra conta")
    ap = ca.apurar(_conta(), [_rec("r1", "100.00", "OUTRA PESSOA")], [p], HOJE)
    assert ap.linhas[1].do_erp == D("100.00") and not ap.sem_dono
    assert ap.apontados[0][2] == BETA


def test_apontamento_com_valor_mudado_volta_para_sem_dono():
    p = ca.Apontamento("r1", 11, D("100.00"), "x")
    ap = ca.apurar(_conta(), [_rec("r1", "150.00", "OUTRA PESSOA")], [p], HOJE)
    motivo = ap.sem_dono[0].motivo
    assert "R$ 100,00" in motivo and "R$ 150,00" in motivo and ap.linhas[1].do_erp == ZERO


def test_nao_e_aporte_fica_fora_da_conta_mas_a_vista():
    p = ca.Apontamento("r1", None, D("100.00"), "devolução")
    ap = ca.apurar(_conta(), [_rec("r1", "100.00", ALFA)], [p], HOJE)
    assert ap.linhas[0].do_erp == ZERO and ap.apontados[0][2] == "" and not ap.sem_dono


def test_apontamento_para_quem_saiu_da_conta_volta_para_sem_dono():
    p = ca.Apontamento("r1", 99, D("100.00"), "x")
    ap = ca.apurar(_conta(), [_rec("r1", "100.00", "OUTRA PESSOA")], [p], HOJE)
    assert "não é mais aportador" in ap.sem_dono[0].motivo


def test_apontamento_de_recebimento_que_sumiu_vira_alerta():
    ap = ca.apurar(_conta(), [], [ca.Apontamento("r9", 11, D("100.00"), "x")], HOJE)
    assert any("R$ 100,00" in a for a in ap.alertas)


def test_conta_com_problema_nao_mostra_numero():
    ap = ca.apurar(replace(_conta(), aportadores=()), [_rec("r1", "1.00", ALFA)], [], HOJE)
    assert ap.erro and ap.linhas == [] and ca.situacao_da_conta(ap).startswith("erro")


@pytest.mark.parametrize("pesos, valor", [(("1", "1"), "40000.00"), (("2", "1"), "100.00"),
                                          (("1", "2"), "100.00"), (("60", "40"), "40000.00")])
def test_aberturas_para_divida_reproduzem_a_divida_na_apuracao(pesos, valor):
    conta = _conta(alfa_abertura="0", pesos=pesos)
    conta = ca.com_aberturas(conta, ca.aberturas_para_divida(conta.aportadores, BETA, D(valor)))
    ap = ca.apurar(conta, [], [], HOJE)
    assert (ap.linhas[0].diferenca, ap.linhas[1].diferenca) == (ZERO, D(valor))


# --- Revisão da Tarefa 2: peso 0, proporções desiguais, centavos, mesma conta ---

@pytest.mark.parametrize("peso_ruim", ["0", "-1", None])
def test_aberturas_para_divida_com_peso_invalido_levanta_valueerror(peso_ruim):
    aps = (ca.Aportador(ALFA, D(1)),
           ca.Aportador(BETA, None if peso_ruim is None else D(peso_ruim)))
    with pytest.raises(ValueError):          # o devedor com peso ruim
        ca.aberturas_para_divida(aps, BETA, D("100.00"))
    with pytest.raises(ValueError):          # OUTRO aportador com peso ruim
        ca.aberturas_para_divida(aps, ALFA, D("100.00"))


def test_dois_para_um_com_aportes_do_erp():
    # ALFA parte 2, BETA parte 1. ALFA pôs 300,00 ao todo; BETA 50,00.
    # Nível = 300 ÷ 2 = 150 por parte → BETA deveria 150,00, deve 100,00.
    conta = _conta(alfa_abertura="100.00", pesos=("2", "1"))
    ap = ca.apurar(conta, [_rec("r1", "200.00", ALFA), _rec("r2", "50.00", BETA)], [], HOJE)
    a, b = ap.linhas
    assert (str(a.parte), str(b.parte)) == ("66.67", "33.33")
    assert (a.aportou, a.deveria, a.diferenca) == (D("300.00"), D("300.00"), ZERO)
    assert (b.aportou, b.deveria, b.diferenca) == (D("50.00"), D("150.00"), D("100.00"))
    # quem tem a parte MENOR pode ser o líder: aí o de parte maior é que deve
    ap = ca.apurar(conta, [_rec("r2", "400.00", BETA)], [], HOJE)
    assert [l.diferenca for l in ap.linhas] == [D("700.00"), ZERO]


def test_tres_para_sete_com_centavo_que_nao_divide():
    # ALFA parte 3 pôs 100,00; BETA parte 7 pôs 0. O exato seria 233,333…:
    # a fração de centavo fica a favor do devedor (corta no centavo): 233,33.
    ap = ca.apurar(_conta(alfa_abertura="100.00", pesos=("3", "7")), [], [], HOJE)
    a, b = ap.linhas
    assert (str(a.parte), str(b.parte)) == ("30.00", "70.00")
    assert (a.diferenca, b.deveria, b.diferenca) == (ZERO, D("233.33"), D("233.33"))
    # Sete para três: 100 × 3 ÷ 7 = 42,857… → 42,85 (e não 42,86).
    ap = ca.apurar(_conta(alfa_abertura="100.00", pesos=("7", "3")), [], [], HOJE)
    assert ap.linhas[1].diferenca == D("42.85")


@pytest.mark.parametrize("pesos, alfa, beta", [
    (("3", "7"), "100.00", "0.00"), (("7", "3"), "100.00", "0.00"),
    (("1", "3"), "0.01", "0.00"), (("2", "1"), "33.33", "0.01"),
    (("0.3333", "0.6667"), "1000.00", "17.17"), (("3", "7"), "0.00", "99.99")])
def test_pagando_o_que_a_tela_manda_todos_ficam_em_dia_sem_vai_e_vem(pesos, alfa, beta):
    """O centavo que sobra: cada devedor deve o exato CORTADO no centavo.
    Pago exatamente isso, ninguém passa a dever um centavo de volta — com o
    arredondamento comum (meio para cima) o líder voltaria a "dever R$ 0,01"
    (7:3, 100,00 × 0: o outro pagaria 42,86 e o líder passaria a dever 0,01)."""
    conta = _conta(alfa_abertura=alfa, beta_abertura=beta, pesos=pesos)
    ap = ca.apurar(conta, [], [], HOJE)
    pagos = [_rec(f"p{i}", str(l.diferenca), l.nome) for i, l in enumerate(ap.linhas)
             if l.diferenca > 0]
    depois = ca.apurar(conta, pagos, [], HOJE)
    assert [l.diferenca for l in depois.linhas] == [ZERO, ZERO]


def test_soma_das_diferencas_fica_a_menos_de_um_centavo_por_devedor_do_exato():
    """A soma das diferenças da conta é explicável: é a soma, devedor a devedor,
    do exato (nível × parte − aportou) cortado no centavo. Nunca passa do exato;
    fica abaixo dele menos de R$ 0,01 por devedor. Nenhum centavo é jogado
    de um aportador para outro."""
    pesos = (D("3"), D("7"), D("1"))
    conta = ca.ContaControlada("CONTA MAE - BANCO", ABRE, id=1, aportadores=(
        ca.Aportador(ALFA, pesos[0], D("100.00"), id=10),
        ca.Aportador(BETA, pesos[1], D("10.00"), id=11),
        ca.Aportador("FULANO GAMA LIMA", pesos[2], D("0.01"), id=12)))
    ap = ca.apurar(conta, [], [], HOJE)
    nivel = D("100.00") / pesos[0]
    exato = sum(nivel * p - l.aportou for p, l in zip(pesos, ap.linhas))
    # 233,333… − 10 = 223,333… → 223,33 ; 33,333… − 0,01 = 33,323… → 33,32
    assert [l.diferenca for l in ap.linhas] == [ZERO, D("223.33"), D("33.32")]
    assert 0 <= exato - sum(l.diferenca for l in ap.linhas) < D("0.01") * 2


@pytest.mark.parametrize("pesos, valor", [
    (("3", "7"), "100.00"), (("7", "3"), "100.00"), (("1", "3"), "100.00"),
    (("3", "1"), "0.01"), (("2", "1"), "0.01"), (("0.3333", "0.6667"), "12345.67")])
def test_aberturas_para_divida_com_centavos_reproduzem_a_divida_exata(pesos, valor):
    conta = _conta(alfa_abertura="0", pesos=pesos)
    aberturas = ca.aberturas_para_divida(conta.aportadores, BETA, D(valor))
    assert all(v >= 0 for v in aberturas.values())
    ap = ca.apurar(ca.com_aberturas(conta, aberturas), [], [], HOJE)
    assert (ap.linhas[0].diferenca, ap.linhas[1].diferenca) == (ZERO, D(valor))


def test_apontamento_para_aportador_de_outra_conta_nao_conta():
    # id 20 é aportador de OUTRA conta; aqui ele não existe — vai para sem dono.
    p = ca.Apontamento("r1", 20, D("100.00"), "x")
    ap = ca.apurar(_conta(), [_rec("r1", "100.00", "OUTRA PESSOA")], [p], HOJE)
    assert [s.recebimento.id for s in ap.sem_dono] == ["r1"]
    assert sum((l.do_erp for l in ap.linhas), ZERO) == ZERO


def test_aportador_do_apontamento_so_aceita_aportador_da_mesma_conta():
    assert ca.aportador_do_apontamento(_conta(), 11).nome_erp == BETA
    assert ca.aportador_do_apontamento(_conta(), None) is None      # "não é aporte"
    with pytest.raises(ValueError):
        ca.aportador_do_apontamento(_conta(), 20)                    # de outra conta
    with pytest.raises(ValueError):                                  # sem id: nunca casa
        ca.aportador_do_apontamento(replace(_conta(), aportadores=(
            ca.Aportador(ALFA, D(1), id=None),)), 0)


@pytest.mark.parametrize("vazio", ["", "   "])
def test_cliente_vazio_nunca_e_chutado_nem_com_um_aportador_so(vazio):
    """A equipe às vezes lança o aporte e preenche o Cliente depois: vazio é
    "não identificado" e vai para sem dono — nem quando a conta tem um
    aportador só, nem pela descrição ou pelo centro de custo."""
    rec = ca.Recebimento("r1", HOJE, D("10.00"), vazio,
                         descricao=f"APORTE {BETA}", centro=BETA)
    for conta in (_conta(), replace(_conta(), aportadores=_conta().aportadores[1:])):
        dono, motivo = ca.identificar_aportador(conta, rec)
        assert dono is None and "sem Cliente" in motivo
        ap = ca.apurar(conta, [rec], [], HOJE)
        assert [s.recebimento.id for s in ap.sem_dono] == ["r1"]
        assert "sem Cliente" in ap.sem_dono[0].motivo
        assert sum((l.do_erp for l in ap.linhas), ZERO) == ZERO
    # e o mesmo recebimento, apontado pelo dono, passa a contar
    p = ca.Apontamento("r1", 11, D("10.00"), "cliente vazio no ERP")
    assert ca.apurar(_conta(), [rec], [p], HOJE).linhas[1].do_erp == D("10.00")


def test_identificar_aportador_pelo_nome_completo():
    dono, motivo = ca.identificar_aportador(_conta(), _rec("r1", "1.00", "fulano beta  souza"))
    assert dono.nome_erp == BETA and motivo == ""
    dono, motivo = ca.identificar_aportador(_conta(), _rec("r1", "1.00", "FULANO"))
    assert dono is None and "não é aportador" in motivo


def test_abertura_sem_data_e_problema_e_nao_typeerror():
    assert "abertura" in " ".join(ca.problemas_da_conta(replace(_conta(), abertura=None), HOJE))
    assert ca.apurar(replace(_conta(), abertura=None), [], [], HOJE).erro


# --- Conserto da revisão da Tarefa 3 ---

@pytest.mark.parametrize("pesos, valor", [
    (("3", "1", "100"), "1.00"), (("3", "1", "2"), "1.00"),
    (("3", "1", "100"), "12345.67"), (("7", "3", "11"), "0.01")])
def test_aberturas_para_divida_com_tres_so_o_devedor_deve(pesos, valor):
    conta = ca.ContaControlada("CONTA MAE - BANCO", ABRE, id=1, aportadores=tuple(
        ca.Aportador(f"FULANO P{i} SILVA", D(p), ZERO, id=10 + i) for i, p in enumerate(pesos)))
    aberturas = ca.aberturas_para_divida(conta.aportadores, "FULANO P0 SILVA", D(valor))
    assert all(v >= 0 for v in aberturas.values())
    ap = ca.apurar(ca.com_aberturas(conta, aberturas), [], [], HOJE)
    assert [l.diferenca for l in ap.linhas] == [D(valor), ZERO, ZERO]


@pytest.mark.parametrize("valor", ["0.00", "-100.00"])
def test_apontamento_de_valor_nao_positivo_vai_para_sem_dono(valor):
    for aportador_id in (11, None):
        p = ca.Apontamento("r1", aportador_id, D(valor), "x")
        ap = ca.apurar(_conta(), [_rec("r1", valor, "OUTRA PESSOA")], [p], HOJE)
        assert [s.recebimento.id for s in ap.sem_dono] == ["r1"]
        assert "valor não positivo" in ap.sem_dono[0].motivo and not ap.apontados
        assert [l.aportou for l in ap.linhas] == [D("40000.00"), ZERO]


# ---- formulário, sugestão da subconta e nomes conhecidos (tarefa 6) ----------

SUBS = {"_obra_padrao": "X",
        "11111-1": {"investidores": ["INV A LTDA", "INV B LTDA"],
                    "pesos": {"INV A LTDA": "2", "INV B LTDA": "1"}}}


def test_ler_data():
    assert ca.ler_data("21/10/2026") == ca.ler_data("2026-10-21") == ABRE
    for ruim in ("21/10", "31/02/2026", ""):
        with pytest.raises(ValueError):
            ca.ler_data(ruim)


def test_ler_abertura():
    assert ca.ler_abertura("") == ZERO and ca.ler_abertura("0") == ZERO
    assert ca.ler_abertura("40.000,00") == D("40000.00")
    for ruim in ("1500.50", "-1,00"):
        with pytest.raises(ValueError):
            ca.ler_abertura(ruim)


def test_conta_do_formulario_pula_linha_vazia_e_partes_vazias_sao_iguais():
    c = ca.conta_do_formulario(" CONTA MAE - BANCO ", "21/10/2026",
                               [(ALFA, "", "40.000,00"), ("", "", ""), (BETA, "", "")])
    assert c == ca.ContaControlada("CONTA MAE - BANCO", ABRE, (
        ca.Aportador(ALFA, D(1), D("40000.00")), ca.Aportador(BETA, D(1), ZERO)))


def test_conta_do_formulario_recusa_parte_pela_metade_e_linha_sem_nome():
    with pytest.raises(ValueError, match="parte"):
        ca.conta_do_formulario("C", "21/10/2026", [(ALFA, "60", ""), (BETA, "", "")])
    with pytest.raises(ValueError, match="nome"):
        ca.conta_do_formulario("C", "21/10/2026", [("", "1", "10,00")])
    with pytest.raises(ValueError):
        ca.conta_do_formulario("", "21/10/2026", [(ALFA, "1", "")])


def test_do_rateio_da_subconta():
    assert ca.do_rateio_da_subconta("SUBCONTA 11111-1 - SICOOB - INVESTIDOR", SUBS) == (
        ca.Aportador("INV A LTDA", D(2)), ca.Aportador("INV B LTDA", D(1)))
    assert ca.do_rateio_da_subconta("CONTA MAE - BANCO", SUBS) is None


def test_divergencia_do_rateio():
    nome = "SUBCONTA 11111-1 - SICOOB - INVESTIDOR"
    igual = ca.ContaControlada(nome, ABRE, (ca.Aportador("inv a ltda", D(4)),
                                            ca.Aportador("INV B LTDA", D(2))))
    assert ca.divergencia_do_rateio(igual, SUBS) == ""
    outra = replace(igual, aportadores=(ca.Aportador("INV A LTDA", D(1)),
                                        ca.Aportador("INV B LTDA", D(1))))
    assert "11111-1" in ca.divergencia_do_rateio(outra, SUBS)
    assert ca.divergencia_do_rateio(_conta(), SUBS) == ""


def test_nomes_conhecidos_sem_repetir_e_sem_vazio():
    entidades = {"Alfa": {"nome_oficial": ALFA, "conta": None},
                 "Empresa": {"nome_oficial": "EMPRESA FICTICIA LTDA", "conta": "1"},
                 "Vazia": {"nome_oficial": ""}}
    nomes = ca.nomes_conhecidos(entidades, SUBS, [_rec("r1", "1.00", "fulano alfa da silva"),
                                                  _rec("r2", "1.00", "")])
    assert nomes == ["EMPRESA FICTICIA LTDA", ALFA, "INV A LTDA", "INV B LTDA"]


def test_opcoes_de_apontamento_e_descricao():
    assert ca.opcoes_de_apontamento(_conta()) == [(ALFA, 10), (BETA, 11), (ca.NAO_E_APORTE, None)]
    texto = ca.descrever_conta(_conta())
    assert "21/10/2026" in texto and ALFA in texto and "R$ 40.000,00" in texto and "50,00%" in texto


def test_nomes_parecidos_nao_se_juntam_nos_nomes_conhecidos():
    # mesmo primeiro nome, pessoas diferentes: os dois ficam
    assert ca.nomes_conhecidos({}, {}, [_rec("a", "1", ALFA), _rec("b", "1", BETA)]) == [ALFA, BETA]


# ---- conserto: peso do cache e parte do formulário ---------------------------

_SUB = "SUBCONTA 11111-1 - SICOOB - INVESTIDOR"


def _subs(pesos):
    return {"11111-1": {"investidores": ["INV A LTDA", "INV B LTDA"], "pesos": pesos}}


def test_rateio_sem_nenhuma_parte_sao_partes_iguais():
    assert ca.do_rateio_da_subconta(_SUB, _subs({})) == (
        ca.Aportador("INV A LTDA", D(1)), ca.Aportador("INV B LTDA", D(1)))


def test_rateio_com_parte_so_de_um_nao_chuta_peso_um():
    subs = _subs({"INV A LTDA": "2"})
    assert ca.do_rateio_da_subconta(_SUB, subs) is None
    conta = ca.ContaControlada(_SUB, ABRE, (ca.Aportador("INV A LTDA", D(1)),
                                            ca.Aportador("INV B LTDA", D(1))))
    assert ca.divergencia_do_rateio(conta, subs) == ""


@pytest.mark.parametrize("pesos", [
    {"INV A LTDA": "abc", "INV B LTDA": "1"},
    {"INV A LTDA": "0", "INV B LTDA": "0"},
    {"INV A LTDA": "-1", "INV B LTDA": "2"},
    {"INV A LTDA": "NaN", "INV B LTDA": "1"},
    {"INV A LTDA": "1,12345", "INV B LTDA": "1"},
])
def test_peso_invalido_do_cache_nao_derruba_a_tela(pesos):
    subs = _subs(pesos)
    assert ca.do_rateio_da_subconta(_SUB, subs) is None
    conta = ca.ContaControlada(_SUB, ABRE, (ca.Aportador("INV A LTDA", D(1)),
                                            ca.Aportador("INV B LTDA", D(1))))
    assert ca.divergencia_do_rateio(conta, subs) == ""


@pytest.mark.parametrize("partes", [("1.500", "1"), ("0", "0"), ("-1", "2"),
                                    ("1,12345", "1"), ("NaN", "1")])
def test_formulario_recusa_parte_ambigua_ou_que_o_rateio_recusaria(partes):
    with pytest.raises(ValueError):
        ca.conta_do_formulario("C", "21/10/2026", [(ALFA, partes[0], ""), (BETA, partes[1], "")])


# ---- o que a tela (Tarefa 7) mostra e manda: tudo decidido aqui, sem janela ----

def test_conta_com_erro_nao_mostra_numero_nenhum():
    ap = ca.Apuracao(conta=_conta(), erro="os recebimentos desta conta não foram lidos")
    parte, aportou, deveria, dif, situacao = ca.valores_da_conta(ap)
    assert (parte, aportou, deveria, dif) == ("", "—", "", "")
    assert situacao.startswith("erro:") and "em dia" not in situacao


def test_linha_do_aportador_mostra_quem_deve_e_quem_esta_em_dia():
    ap = ca.apurar(_conta(), [], [], HOJE)
    alfa, beta = (ca.valores_do_aportador(l) for l in ap.linhas)
    assert alfa == ("50,00%", "R$ 40.000,00", "R$ 40.000,00", "—", "em dia")
    assert beta == ("50,00%", "R$ 0,00", "R$ 40.000,00", "R$ 40.000,00",
                    "deve R$ 40.000,00 para igualar")
    assert ca.valores_da_conta(ap)[1] == "R$ 40.000,00"


def test_vistos_sao_os_ids_que_o_formulario_carregou():
    assert ca.vistos_do_formulario(None) is None                 # conta nova
    assert ca.vistos_do_formulario(replace(_conta(), id=None)) is None
    assert ca.vistos_do_formulario(_conta()) == [10, 11]
    sem_ninguem = replace(_conta(), aportadores=())
    assert ca.vistos_do_formulario(sem_ninguem) == []            # [] não é None


def test_dinheiro_do_formulario_volta_igual():
    for v in ("0.00", "0.01", "1500.50", "40000.00", "1234567.89"):
        assert ca.ler_abertura(ca.texto_de_dinheiro(D(v))) == D(v)


def test_rateio_da_subconta_leva_o_ja_aportado_pelo_nome_e_nunca_pela_posicao():
    digitadas = [(BETA, "1", "300,00"), (ALFA, "1", "40.000,00"), ("", "", "")]
    vindos = (ca.Aportador(ALFA, D("2")), ca.Aportador(BETA, D("1")))
    linhas, descartados = ca.linhas_do_rateio(digitadas, vindos)
    assert linhas == [(ALFA, "2", "40.000,00"), (BETA, "1", "300,00"), ("", "", "")]
    assert descartados == []


def test_rateio_da_subconta_avisa_quem_some_com_ja_aportado_e_cresce_o_formulario():
    digitadas = [("FULANO GAMA", "1", "10,00"), (ALFA, "1", "")]
    vindos = (ca.Aportador(ALFA, D("1")), ca.Aportador(BETA, D("1")),
              ca.Aportador("FULANO DELTA", D("1")))
    linhas, descartados = ca.linhas_do_rateio(digitadas, vindos)
    assert [n for n, _p, _a in linhas] == [ALFA, BETA, "FULANO DELTA"]   # ninguém cortado
    assert descartados == ["FULANO GAMA"]
    assert ca.linhas_do_rateio([("FULANO GAMA", "1", "")], vindos)[1] == []  # sem valor: sem aviso


def test_preencher_o_ja_aportado_casa_pelo_nome_completo():
    digitadas = [(ALFA, "1", ""), (BETA.lower() + "  ", "1", "5,00"), ("FULANO", "1", "7,00")]
    saida = ca.aberturas_nas_linhas(digitadas, {ALFA: D("40000.00"), BETA: D("0.00")})
    assert saida == [(ALFA, "1", "40.000,00"), (BETA.lower() + "  ", "1", "0,00"),
                     ("FULANO", "1", "7,00")]                  # primeiro nome não casa


def test_apontamento_exige_aportador_da_lista_e_motivo():
    opcoes = ca.opcoes_de_apontamento(_conta())
    assert ca.escolha_do_apontamento(opcoes, BETA, "  depósito do sócio ") == (11, "depósito do sócio")
    assert ca.escolha_do_apontamento(opcoes, ca.NAO_E_APORTE, "devolução") == (None, "devolução")
    for rotulo, motivo in (("", "x"), ("FULANO", "x"), (BETA, "  ")):
        with pytest.raises(ValueError):
            ca.escolha_do_apontamento(opcoes, rotulo, motivo)


# ---- conserto da Tarefa 7: botões do dono e reler depois de gravar ----------

@pytest.mark.parametrize("pode,lendo,leu_bem,estado", [
    (True, False, True, "normal"),
    (True, True, True, "disabled"),       # leitura rodando: nada de editar
    (True, False, False, "disabled"),     # sem leitura boa (antes da 1ª, ou falhou)
    (False, False, True, "disabled"),     # não é admin
])
def test_botoes_do_dono_so_com_leitura_boa_e_parada(pode, lendo, leu_bem, estado):
    assert ca.estado_dos_botoes_do_dono(pode, lendo, leu_bem) == estado


def test_depois_de_gravar_rele_agora_ou_no_fim_da_leitura_em_curso():
    assert ca.depois_de_gravar(lendo=False) == "reler"
    assert ca.depois_de_gravar(lendo=True) == "reler_no_fim"
