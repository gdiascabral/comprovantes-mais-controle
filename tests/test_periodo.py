"""Intervalo de vencimentos: a regra da segunda-feira e a virada de mes."""

from datetime import date
from decimal import Decimal

import pytest

from conciliacao.erp.payments import meses_do_periodo
from conciliacao.models import ErpPayment, Periodo, sugerir_periodo
from conciliacao.rules import aggregate_by_row, classify_payments

# Julho/2026: 25 e 26 sao sabado e domingo; 27 e segunda.
SABADO = date(2026, 7, 25)
DOMINGO = date(2026, 7, 26)
SEGUNDA = date(2026, 7, 27)
TERCA = date(2026, 7, 28)


def test_periodo_de_um_dia():
    p = Periodo.de_um_dia(SEGUNDA)
    assert p.um_dia_so
    assert p.dias == [SEGUNDA]
    assert p.descrever() == "27/07/2026"


def test_periodo_invertido_e_erro():
    with pytest.raises(ValueError, match="invertido"):
        Periodo(inicio=SEGUNDA, fim=SABADO)


def test_periodo_contem():
    p = Periodo(inicio=SABADO, fim=SEGUNDA)
    assert p.contem(SABADO) and p.contem(DOMINGO) and p.contem(SEGUNDA)
    assert not p.contem(TERCA)
    assert not p.contem(date(2026, 7, 24))
    assert not p.contem(None)
    assert len(p.dias) == 3
    assert p.descrever() == "25/07/2026 a 27/07/2026"


def test_na_segunda_a_sugestao_cobre_o_fim_de_semana():
    """O caso que motivou tudo: segunda tem que somar sabado e domingo."""
    p = sugerir_periodo(SEGUNDA)
    assert (p.inicio, p.fim) == (SABADO, SEGUNDA)
    assert len(p.dias) == 3


def test_nos_outros_dias_a_sugestao_e_so_o_dia():
    for dia in (TERCA, date(2026, 7, 29), date(2026, 7, 30), date(2026, 7, 31)):
        p = sugerir_periodo(dia)
        assert p.um_dia_so, dia


def test_no_sabado_e_domingo_a_sugestao_e_so_o_dia():
    """Sabado nao deve arrastar a sexta: sexta e dia util e ja foi conciliada."""
    assert sugerir_periodo(SABADO).um_dia_so
    assert sugerir_periodo(DOMINGO) == Periodo(inicio=SABADO, fim=DOMINGO)


def test_segunda_apos_virada_de_mes_puxa_o_mes_anterior():
    """01/06/2026 e segunda; sabado e domingo caem em maio."""
    segunda_dia_1 = date(2026, 6, 1)
    assert segunda_dia_1.weekday() == 0
    p = sugerir_periodo(segunda_dia_1)
    assert p.inicio == date(2026, 5, 30)
    assert meses_do_periodo(p) == [(2026, 5), (2026, 6)]


def test_meses_do_periodo():
    assert meses_do_periodo(Periodo.de_um_dia(SEGUNDA)) == [(2026, 7)]
    assert meses_do_periodo(Periodo(inicio=SABADO, fim=SEGUNDA)) == [(2026, 7)]
    assert meses_do_periodo(
        Periodo(inicio=date(2025, 12, 30), fim=date(2026, 1, 2))
    ) == [(2025, 12), (2026, 1)]


# ------------------------------------------------------- filtro dos pagamentos


def pagamento(conta, valor, venc, status="Em aberto"):
    return ErpPayment(
        due_date=venc,
        status=status,
        amount=Decimal(valor),
        payee="FORNECEDOR",
        account_label=conta,
    )


def test_soma_o_fim_de_semana_inteiro_na_segunda(mapping):
    pagamentos = [
        pagamento("MORAIS ENGENHARIA - INTER", "100.00", SABADO),
        pagamento("MORAIS ENGENHARIA - INTER", "200.00", DOMINGO),
        pagamento("MORAIS ENGENHARIA - INTER", "300.00", SEGUNDA),
        pagamento("MORAIS ENGENHARIA - INTER", "999.00", TERCA),  # fora
    ]
    resultado = classify_payments(pagamentos, mapping, Periodo(inicio=SABADO, fim=SEGUNDA))

    assert aggregate_by_row(resultado) == {8: (Decimal("600.00"), 3)}
    assert resultado.skipped_other_date == 1


def test_data_solta_continua_funcionando(mapping):
    """Compatibilidade: passar um `date` vale como periodo de um dia."""
    pagamentos = [
        pagamento("MORAIS ENGENHARIA - INTER", "100.00", SEGUNDA),
        pagamento("MORAIS ENGENHARIA - INTER", "200.00", SABADO),
    ]
    resultado = classify_payments(pagamentos, mapping, SEGUNDA)
    assert aggregate_by_row(resultado) == {8: (Decimal("100.00"), 1)}


def test_exclusoes_valem_em_todo_o_periodo(mapping):
    """A regra do R$ 1,00 nao pode valer so no ultimo dia."""
    pagamentos = [
        pagamento("MORAIS ENGENHARIA - INTER", "1.00", SABADO),
        pagamento("MORAIS ENGENHARIA - INTER", "1.00", SEGUNDA),
        pagamento("MORAIS ENGENHARIA - INTER", "50.00", DOMINGO),
    ]
    resultado = classify_payments(pagamentos, mapping, Periodo(inicio=SABADO, fim=SEGUNDA))
    assert len(resultado.excluded_one_real) == 2
    assert aggregate_by_row(resultado) == {8: (Decimal("50.00"), 1)}


# --------------------------------------------------- leitura do que o usuario digita


class ArgsFake:
    """Imita o namespace do argparse."""

    def __init__(self, **kw):
        self.data = kw.get("data")
        self.de = kw.get("de")
        self.ate = kw.get("ate")
        self.sem_perguntar = kw.get("sem_perguntar", True)


def test_ler_data_solta_aceita_formatos_do_dia_a_dia():
    from conciliacao.cli import _ler_data_solta

    hoje = date(2026, 7, 30)
    assert _ler_data_solta("25/07", hoje) == date(2026, 7, 25)
    assert _ler_data_solta("25/07/2026", hoje) == date(2026, 7, 25)
    assert _ler_data_solta("25-07-2026", hoje) == date(2026, 7, 25)
    assert _ler_data_solta("2026-07-25", hoje) == date(2026, 7, 25)
    assert _ler_data_solta("25/07/26", hoje) == date(2026, 7, 25)
    assert _ler_data_solta("  27/07  ", hoje) == date(2026, 7, 27)
    # Lixo nao virar data errada em silencio.
    assert _ler_data_solta("", hoje) is None
    assert _ler_data_solta("abc", hoje) is None
    assert _ler_data_solta("99/99/2026", hoje) is None


def test_resolver_periodo_por_parametro():
    from conciliacao.cli import resolver_periodo

    p = resolver_periodo(ArgsFake(de="25/07/2026", ate="27/07/2026"), interativo=False)
    assert (p.inicio, p.fim) == (SABADO, SEGUNDA)


def test_resolver_periodo_inverte_se_vier_trocado():
    from conciliacao.cli import resolver_periodo

    p = resolver_periodo(ArgsFake(de="27/07/2026", ate="25/07/2026"), interativo=False)
    assert (p.inicio, p.fim) == (SABADO, SEGUNDA)


def test_resolver_periodo_com_apenas_uma_ponta():
    from conciliacao.cli import resolver_periodo

    p = resolver_periodo(ArgsFake(de="27/07/2026"), interativo=False)
    assert p.um_dia_so and p.fim == SEGUNDA


def test_resolver_periodo_com_data_unica():
    from conciliacao.cli import resolver_periodo

    p = resolver_periodo(ArgsFake(data="2026-07-28"), interativo=False)
    assert p == Periodo.de_um_dia(TERCA)


# ------------------------------------------- status: o ERP troca por "Vencido"


def test_vencido_conta_como_a_pagar(mapping):
    """Titulo nao pago com vencimento passado vira "Vencido" no Mais Controle."""
    pagamentos = [pagamento("MORAIS ENGENHARIA - INTER", "500.00", SABADO, status="Vencido")]
    resultado = classify_payments(pagamentos, mapping, Periodo(inicio=SABADO, fim=SEGUNDA))
    assert aggregate_by_row(resultado) == {8: (Decimal("500.00"), 1)}


def test_fim_de_semana_com_vencido_e_hoje_em_aberto(mapping):
    """O caso real: sabado/domingo aparecem como Vencido e segunda como Em aberto."""
    pagamentos = [
        pagamento("MORAIS ENGENHARIA - INTER", "1000.00", SABADO, status="Vencido"),
        pagamento("MORAIS ENGENHARIA - INTER", "2000.00", DOMINGO, status="Vencido"),
        pagamento("MORAIS ENGENHARIA - INTER", "3000.00", SEGUNDA, status="Em aberto"),
        pagamento("MORAIS ENGENHARIA - INTER", "9000.00", SABADO, status="Pago"),
    ]
    resultado = classify_payments(pagamentos, mapping, Periodo(inicio=SABADO, fim=SEGUNDA))

    assert aggregate_by_row(resultado) == {8: (Decimal("6000.00"), 3)}
    assert resultado.skipped_not_open == 1  # o Pago
    assert not resultado.status_desconhecido


def test_status_desconhecido_nao_e_descartado_em_silencio(mapping):
    """Status novo pode ser algo a pagar: precisa aparecer para conferencia."""
    pagamentos = [
        pagamento("MORAIS ENGENHARIA - INTER", "700.00", SEGUNDA, status="Agendado"),
        pagamento("MORAIS ENGENHARIA - INTER", "100.00", SEGUNDA, status="Em aberto"),
    ]
    resultado = classify_payments(pagamentos, mapping, SEGUNDA)

    assert aggregate_by_row(resultado) == {8: (Decimal("100.00"), 1)}
    assert [p.status for p in resultado.status_desconhecido] == ["Agendado"]


def test_listas_de_status_vem_do_config(config):
    """As listas do config.yaml precisam incluir Vencido, senao o periodo quebra."""
    considerados = [s.upper() for s in config.status_considerados]
    assert "EM ABERTO" in considerados
    assert "VENCIDO" in considerados
    assert [s.upper() for s in config.status_ignorados] == ["PAGO"]


def test_status_do_config_e_respeitado(mapping):
    """Se o Gustavo tirar "Vencido" da lista, o comportamento muda de verdade."""
    pagamentos = [pagamento("MORAIS ENGENHARIA - INTER", "500.00", SABADO, status="Vencido")]
    resultado = classify_payments(
        pagamentos,
        mapping,
        Periodo(inicio=SABADO, fim=SEGUNDA),
        status_a_pagar=("Em aberto",),
        status_fora=("Pago", "Vencido"),
    )
    assert aggregate_by_row(resultado) == {}
    assert resultado.skipped_not_open == 1
