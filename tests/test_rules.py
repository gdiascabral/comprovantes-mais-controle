from datetime import date
from decimal import Decimal

from conciliacao.models import ErpAccount, ErpPayment
from conciliacao.rules import (
    aggregate_by_row,
    build_row_fills,
    classify_payments,
    resolve_balances,
)

HOJE = date(2026, 7, 29)


def pagamento(conta, valor, *, venc=HOJE, status="Em aberto", favorecido="FORNECEDOR"):
    return ErpPayment(
        due_date=venc,
        status=status,
        amount=Decimal(valor) if valor is not None else None,
        payee=favorecido,
        account_label=conta,
    )


def test_soma_e_conta_por_linha(mapping):
    pagamentos = [
        pagamento("MORAIS ENGENHARIA - INTER", "1000.00"),
        pagamento("MORAIS ENGENHARIA - INTER", "500.50"),
        pagamento("TERRA BELA - SICOOB", "200.00"),
    ]
    resultado = classify_payments(pagamentos, mapping, HOJE)
    assert aggregate_by_row(resultado) == {
        8: (Decimal("1500.50"), 2),
        10: (Decimal("200.00"), 1),
    }


def test_exclui_exatamente_um_real(mapping):
    pagamentos = [
        pagamento("MORAIS ENGENHARIA - INTER", "1.00"),
        pagamento("MORAIS ENGENHARIA - INTER", "1.01"),
        pagamento("MORAIS ENGENHARIA - INTER", "0.99"),
    ]
    resultado = classify_payments(pagamentos, mapping, HOJE)
    assert len(resultado.excluded_one_real) == 1
    # R$ 1,01 e R$ 0,99 continuam valendo — a regra e valor exato.
    assert aggregate_by_row(resultado) == {8: (Decimal("2.00"), 2)}


def test_nao_exclui_reembolso(mapping):
    pagamentos = [
        pagamento("MORAIS ENGENHARIA - INTER", "300.00", favorecido="REEMBOLSO GUSTAVO"),
        pagamento("MORAIS ENGENHARIA - INTER", "150.00", favorecido="VIDRO ALVES"),
    ]
    resultado = classify_payments(pagamentos, mapping, HOJE)
    assert aggregate_by_row(resultado) == {8: (Decimal("450.00"), 2)}


def test_filtra_por_data_e_status(mapping):
    pagamentos = [
        pagamento("MORAIS ENGENHARIA - INTER", "100.00"),
        pagamento("MORAIS ENGENHARIA - INTER", "999.00", venc=date(2026, 7, 30)),
        pagamento("MORAIS ENGENHARIA - INTER", "888.00", status="Pago"),
    ]
    resultado = classify_payments(pagamentos, mapping, HOJE)
    assert resultado.skipped_other_date == 1
    assert resultado.skipped_not_open == 1
    assert aggregate_by_row(resultado) == {8: (Decimal("100.00"), 1)}


def test_conta_fora_do_painel_vai_para_log_nao_para_planilha(mapping):
    pagamentos = [
        pagamento("PESSOA FISICA - APENAS LANÇAMENTO", "5000.00"),
        pagamento("EMPREENDIMENTO NOVO XPTO - SICOOB", "700.00"),
    ]
    resultado = classify_payments(pagamentos, mapping, HOJE)
    assert len(resultado.ignored_by_config) == 1
    assert len(resultado.unmapped) == 1  # alerta: possivel conta nova
    assert aggregate_by_row(resultado) == {}
    assert resultado.total_out_of_panel == Decimal("5700.00")


def test_valor_ilegivel_e_alerta_nao_zero(mapping):
    resultado = classify_payments(
        [pagamento("MORAIS ENGENHARIA - INTER", None)], mapping, HOJE
    )
    assert len(resultado.invalid_amount) == 1
    assert aggregate_by_row(resultado) == {}


def test_regra_do_zero_quando_nada_vence_hoje(mapping):
    resultado = classify_payments([], mapping, HOJE)
    fills = {f.row: f for f in build_row_fills(mapping, {}, aggregate_by_row(resultado))}

    linha = fills[8]
    assert (linha.total, linha.count, linha.bank_count) == (Decimal("0"), 0, 0)


def test_quando_ha_pagamento_a_coluna_j_fica_vazia(mapping):
    pagamentos = [pagamento("MORAIS ENGENHARIA - INTER", "1000.00")]
    resultado = classify_payments(pagamentos, mapping, HOJE)
    fills = {f.row: f for f in build_row_fills(mapping, {}, aggregate_by_row(resultado))}

    linha = fills[8]
    assert (linha.total, linha.count) == (Decimal("1000.00"), 1)
    assert linha.bank_count is None  # J so e preenchido na conferencia manual


def test_linhas_sem_conta_no_erp_ficam_totalmente_vazias(mapping):
    fills = {f.row: f for f in build_row_fills(mapping, {}, {})}
    for row in (28, 30, 31):
        linha = fills[row]
        assert (linha.balance, linha.total, linha.count, linha.bank_count) == (
            None,
            None,
            None,
            None,
        )


def test_saldo_nao_lido_fica_vazio_e_nao_zero(mapping):
    fills = {f.row: f for f in build_row_fills(mapping, {8: None, 10: Decimal("500")}, {})}
    assert fills[8].balance is None
    assert fills[10].balance == Decimal("500")


def test_saldo_negativo_e_preservado(mapping):
    fills = {f.row: f for f in build_row_fills(mapping, {8: Decimal("-1500.75")}, {})}
    assert fills[8].balance == Decimal("-1500.75")


# --------------------------------------------------- precedencia das ignoradas
#
# Regressao real: a conta "APLICACAO FUNDO INVESTIMENTOS - MORAIS
# EMPREENDIMENTOS BURITIS - CAIXA ECONOMICA FEDERAL" CONTEM o erp_name da
# linha 27, entao casava com ela por continencia. As duas contas disputavam a
# mesma linha e quem vencia era a ULTIMA lida — o painel dependia da ordem em
# que o ERP devolvia as contas, e a descoberta de uuid (onde a PRIMEIRA vence)
# teria gravado a conta errada de vez, com diferenca de centenas de milhares.


def conta(nome, saldo, *, uuid=""):
    return ErpAccount(id=uuid, name=nome, balance=Decimal(saldo))


APLICACAO = "APLICAÇÃO FUNDO INVESTIMENTOS - MORAIS EMPREENDIMENTOS BURITIS - CAIXA ECONÔMICA FEDERAL"
BURITIS_CEF = "MORAIS EMPREENDIMENTOS BURITIS - CAIXA ECONÔMICA FEDERAL"


def test_conta_ignorada_nao_rouba_linha_do_painel(mapping):
    resolucao = resolve_balances(
        [conta(APLICACAO, "-22222.22"), conta(BURITIS_CEF, "500000.00")], mapping
    )
    assert resolucao.balances[27] == Decimal("500000.00")


def test_ordem_das_contas_nao_muda_o_saldo(mapping):
    """A mesma leitura, invertida, tem de dar o mesmo painel."""
    direta = resolve_balances(
        [conta(APLICACAO, "-22222.22"), conta(BURITIS_CEF, "500000.00")], mapping
    )
    invertida = resolve_balances(
        [conta(BURITIS_CEF, "500000.00"), conta(APLICACAO, "-22222.22")], mapping
    )
    assert direta.balances[27] == invertida.balances[27] == Decimal("500000.00")


def test_conta_ignorada_nao_vira_conta_desconhecida(mapping):
    """Ignorada e ignorada: nao entra no painel nem no alerta de conta nova."""
    resolucao = resolve_balances([conta(APLICACAO, "-22222.22")], mapping)
    assert resolucao.contas_desconhecidas == []


def test_pagamento_em_conta_ignorada_nao_entra_no_painel(mapping):
    resultado = classify_payments([pagamento(APLICACAO, "5000.00")], mapping, HOJE)
    assert aggregate_by_row(resultado) == {}
    assert len(resultado.ignored_by_config) == 1
