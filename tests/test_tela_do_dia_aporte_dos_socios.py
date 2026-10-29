"""Aporte de fora dividido entre os sócios e o aviso de igualar. Cadastro fictício."""
from datetime import date
from decimal import Decimal as D

import pytest

from conciliacao.aportadores import Regra
from tela_do_dia import aporte_dos_socios as ads
from tela_do_dia import controle_aportes as ca
from tela_do_dia import para_aportes as pa

HOJE = date(2026, 10, 29)
MAE = "Mae - Banco A"
MAE_B = "Mae - Banco B"
ENTIDADES = {
    "MAE - BANCO A": {"nome_oficial": "MAE FICTICIA LTDA", "conta": "MAE - BANCO A"},
    "MAE - BANCO B": {"nome_oficial": "MAE FICTICIA LTDA B", "conta": "MAE - BANCO B"},
    "FILHA UM - BANCO": {"nome_oficial": "FILHA UM LTDA", "conta": "FILHA UM - BANCO"},
    "SOCIO FICTICIO UM COMPLETO": {"nome_oficial": "", "conta": None},
    "SOCIO FICTICIO DOIS COMPLETO": {"nome_oficial": "", "conta": None},
    "HOLDING - SUBCONTA 33333-3": {"nome_oficial": "HOLDING", "conta": "HOLDING - SUBCONTA 33.333-3"},
    "INVESTIDOR SUBCONTA 33333-3": {"nome_oficial": "", "conta": None},
}
UM, DOIS = "SOCIO FICTICIO UM COMPLETO", "SOCIO FICTICIO DOIS COMPLETO"
REGRAS = [
    Regra("Filha Um - Banco", MAE, None, "Aporte", True, linha=5),
    Regra(MAE_B, MAE, D(1), "Transferência", True, linha=6),
    Regra("Filha Dois - Banco", MAE, None, "Aporte", True, linha=7),
]


def _apuracao(conta="MAE - BANCO A", linhas=None, erro="", sem_dono=(), pesos=(1, 1)):
    aportadores = (ca.Aportador(UM.lower(), D(pesos[0])), ca.Aportador(DOIS.lower(), D(pesos[1])))
    c = ca.ContaControlada(conta, HOJE, aportadores)
    return ca.Apuracao(conta=c, linhas=list(linhas or []), sem_dono=list(sem_dono), erro=erro)


def _linha(nome, diferenca):
    return ca.LinhaAportador(nome, D(50), D(0), D(0), D(0), D(0), D(diferenca))


# ------------------------------------------------------------ contas e movimentos
def test_contas_da_mae_inclui_a_conta_para_onde_ela_so_transfere():
    assert ads.contas_da_mae(REGRAS, MAE) == [MAE, MAE_B]
    assert ads.contas_da_mae(REGRAS, None) == []


def test_movimentos_de_fora_somam_por_destino_e_separam_outras_contas():
    a_mao = [(None, MAE, D("100.00")), (None, MAE, D("50.00")),
             (None, "Filha Um - Banco", D("7.00")), ("Filha Um - Banco", MAE, D("9.00")),
             (None, MAE_B, D("0"))]
    nas, outras = ads.movimentos_de_fora(a_mao, [MAE, MAE_B])
    assert nas == {MAE: D("150.00")}
    assert outras == [("Filha Um - Banco", D("7.00"))]


# ------------------------------------------------------------------- sócios
def test_socios_vem_do_controle_com_o_nome_completo_do_cadastro():
    socios, recado = ads.socios_da_mae([_apuracao()], MAE, ENTIDADES)
    assert recado == "" and socios == [(UM, D(1)), (DOIS, D(1))]


def test_sem_controle_da_mae_nao_divide_e_diz_por_que():
    socios, recado = ads.socios_da_mae([_apuracao(conta="OUTRA")], MAE, ENTIDADES)
    assert socios == [] and "Controle de aportes não foi lido" in recado


def test_aportador_do_controle_fora_do_cadastro_e_recado_e_nunca_chute():
    ap = _apuracao()
    ap.conta = ca.ContaControlada("MAE - BANCO A", HOJE,
                                  (ca.Aportador("SOCIO FICTICIO UM", D(1)),
                                   ca.Aportador(DOIS, D(1))))
    socios, recado = ads.socios_da_mae([ap], MAE, ENTIDADES)
    assert socios == [] and "SOCIO FICTICIO UM" in recado


def test_mae_fora_do_cadastro_e_recado():
    assert ads.socios_da_mae([_apuracao()], "Nao Existe", ENTIDADES)[0] == []


# ------------------------------------------------------------------ divisão
def test_divisao_inicial_meio_a_meio_fecha_o_centavo_impar():
    socios = [(UM, D(1)), (DOIS, D(1))]
    d = ads.divisao_inicial(D("100.01"), socios)
    assert sum(d.values()) == D("100.01")
    assert sorted(d.values()) == [D("50.00"), D("50.01")]


def test_divisao_inicial_segue_o_peso_do_controle():
    d = ads.divisao_inicial(D("300.00"), [(UM, D(2)), (DOIS, D(1))])
    assert d == {UM: D("200.00"), DOIS: D("100.00")}


@pytest.mark.parametrize("partes,recado", [
    ([D("60"), D("40")], ""),
    ([D("100"), D("0")], ""),
    ([D("60"), D("30")], "faltam R$ 10,00"),
    ([D("60"), D("50")], "passou R$ 10,00"),
    ([D("0"), D("0")], "as partes estão zeradas"),
])
def test_validar_divisao(partes, recado):
    assert ads.validar_divisao(D("100.00"), partes) == recado


def test_ler_parte_vazio_e_zero_e_negativo_recusa():
    assert ads.ler_parte("") == D("0.00")
    assert ads.ler_parte("1.234,56") == D("1234.56")
    with pytest.raises(ValueError):
        ads.ler_parte("-5,00")


# ---------------------------------------------------------------- operações
def _ops(divisoes, valores=None, **kw):
    valores = valores if valores is not None else {d: sum(p.values()) for d, p in divisoes.items()}
    return ads.operacoes(divisoes, valores, ENTIDADES, {}, HOJE, **kw)


def test_cada_parte_vira_aporte_de_capital_do_socio_com_chave_propria():
    envio, dobro = _ops({MAE: {UM: D("60.00"), DOIS: D("40.00")}})
    assert dobro == set() and envio.pendentes == []
    ops = [(op.pagador, op.recebedor, op.valor, op.tipo, op.modo) for op, _ in envio.itens]
    assert ops == [(UM, "MAE - BANCO A", D("60.00"), "Aporte de Capital", "Só recebimento"),
                   (DOIS, "MAE - BANCO A", D("40.00"), "Aporte de Capital", "Só recebimento")]
    assert [k for _op, ks in envio.itens for k in ks] == [ads.chave(UM, MAE), ads.chave(DOIS, MAE)]
    assert envio.valores == {ads.chave(UM, MAE): D("60.00"), ads.chave(DOIS, MAE): D("40.00")}


def test_parte_zero_nao_vira_operacao():
    envio, _ = _ops({MAE: {UM: D("100.00"), DOIS: D("0.00")}})
    assert [op.pagador for op, _ in envio.itens] == [UM]


def test_soma_que_nao_bate_com_o_movimento_segura_o_destino_inteiro():
    envio, _ = _ops({MAE: {UM: D("60.00"), DOIS: D("30.00")}}, valores={MAE: D("100.00")})
    assert envio.itens == [] and all("faltam" in p.motivo for p in envio.pendentes)


def test_movimento_que_sumiu_da_tela_nao_vai():
    envio, _ = _ops({MAE: {UM: D("60.00"), DOIS: D("40.00")}}, valores={})
    assert envio.itens == [] and envio.pendentes


@pytest.mark.parametrize("antes", [D("60.00"), D("10.00")])
def test_ja_mandado_hoje_nao_vai_de_novo_nem_com_valor_corrigido(antes):
    envio, _ = _ops({MAE: {UM: D("60.00"), DOIS: D("40.00")}},
                    enviados={ads.chave(UM, MAE): antes})
    assert [op.pagador for op, _ in envio.itens] == [DOIS]
    (p,) = envio.pendentes
    assert "já mandado" in p.motivo and UM in p.aportador


def test_ja_mandado_reconhece_o_destino():
    assert ads.ja_mandado({ads.chave(UM, MAE): D(1)}, MAE)
    assert not ads.ja_mandado({ads.chave(UM, MAE): D(1)}, MAE_B)
    assert not ads.ja_mandado({f"{MAE}|{UM}": D(1)}, MAE)


def test_destino_subconta_de_investidor_e_pendencia():
    envio, _ = _ops({"Holding - Subconta 33333-3": {UM: D("10.00"), DOIS: D("10.00")}})
    assert envio.itens == [] and "subconta de investidor" in envio.pendentes[0].motivo


def test_mesmo_socio_na_mesma_conta_pela_aba_regras_vira_pendencia_dos_dois_lados():
    definidos = {(MAE, UM): D("30.00")}
    envio, dobro = _ops({MAE: {UM: D("60.00"), DOIS: D("40.00")}}, definidos=definidos)
    assert dobro == {(MAE, UM)}
    assert [op.pagador for op, _ in envio.itens] == [DOIS]
    assert "aba Regras" in envio.pendentes[0].motivo
    regras = [Regra(MAE, UM, None, "Aporte", False, linha=9)]
    lado_regras = pa.operacoes(definidos, regras, ENTIDADES, {}, HOJE, pares_em_dobro=dobro)
    assert lado_regras.itens == [] and "à mão" in lado_regras.pendentes[0].motivo


def test_conta_sem_saldo_avisa_mas_vai():
    envio, _ = _ops({MAE: {UM: D("60.00"), DOIS: D("40.00")}}, sem_saldo={MAE})
    assert len(envio.itens) == 2 and len(envio.sem_saldo) == 2
    assert all(a.motivo == pa.MOTIVO_SEM_SALDO for a in envio.avisos)


def test_juntar_soma_no_envio_da_regras_e_marca_como_mandado():
    regras, _ = _ops({MAE: {UM: D("60.00"), DOIS: D("40.00")}})
    base = pa.Envio()
    ads.juntar(base, regras)
    mandadas = [op for op, _ in base.itens]
    assert pa.enviados_apos({}, base, mandadas, []) == {ads.chave(UM, MAE): D("60.00"),
                                                       ads.chave(DOIS, MAE): D("40.00")}


# ----------------------------------------------------------------- igualar
def test_aviso_de_quem_precisa_igualar():
    ap = _apuracao(linhas=[_linha("Socio Um", 0), _linha("Socio Dois", "40000")])
    assert ads.avisos_de_igualar([ap]) == [
        "Socio Dois precisa aportar R$ 40.000,00 para igualar Socio Um em MAE - BANCO A"]


def test_conta_igualada_nao_aparece_e_erro_aparece():
    em_dia = _apuracao(linhas=[_linha("A", 0), _linha("B", 0)])
    com_erro = _apuracao(conta="FILHA UM - BANCO", erro="parcela repetida")
    assert ads.avisos_de_igualar([em_dia, com_erro]) == [
        "Controle de aportes: FILHA UM - BANCO não fechou (parcela repetida) — veja a aba"]


def test_controle_nao_lido_diz_por_que():
    assert ads.avisos_de_igualar([], erro="sem rede") == ["Controle de aportes não lido: sem rede"]


def test_sem_dono_avisa_que_a_conta_pode_mudar():
    sd = ca.SemDono(None, "sem cliente")
    ap = _apuracao(linhas=[_linha("A", 0), _linha("B", 5)], sem_dono=[sd])
    avisos = ads.avisos_de_igualar([ap])
    assert len(avisos) == 2 and "sem dono" in avisos[1]


def test_avisos_dos_socios_so_da_mae():
    mae = _apuracao(linhas=[_linha("A", 0), _linha("B", 5)])
    outra = _apuracao(conta="FILHA UM - BANCO", linhas=[_linha("C", 0), _linha("D", 9)])
    assert ads.avisos_dos_socios([mae, outra], MAE, ENTIDADES) == [
        "B precisa aportar R$ 5,00 para igualar A em MAE - BANCO A"]
