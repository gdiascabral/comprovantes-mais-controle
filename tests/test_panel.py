from decimal import Decimal

from conciliacao.models import RowFill
from conciliacao.panel import compute_panel

#: Onde o rateio secundário (Julio/Livian) mora hoje. Vem do config e
#: não escrito à mão: a célula desce toda vez que uma conta entra no
#: painel, e em 17/08/2026 ela desceu de F32 para F34.
def _celula_rateio():
    from conciliacao.config import load_config
    from pathlib import Path as _P
    cfg = load_config(_P(__file__).resolve().parent.parent / 'config.yaml')
    return cfg.planilha.rateios[0].celula_secundario


CELULA_RATEIO = _celula_rateio()



def fills_de(valores: dict[int, tuple], planilha, mapping) -> list[RowFill]:
    """Monta os fills do painel; linhas nao citadas ficam com saldo 0 e E=0.

    `valores` mapeia linha -> (saldo, pagamento). Use None para celula vazia.
    """
    resultado = []
    for row in planilha.linhas:
        modelo = mapping.by_row(row)
        if modelo is not None and not modelo.exists_in_erp:
            resultado.append(RowFill(row, None, None, None, None))
            continue
        saldo, pagamento = valores.get(row, (Decimal("0"), Decimal("0")))
        resultado.append(
            RowFill(
                row=row,
                balance=saldo,
                total=pagamento,
                count=0 if pagamento == 0 else 1,
                bank_count=0 if pagamento == 0 else None,
            )
        )
    return resultado


def test_sem_deficit_o_aporte_minimo_espelha_o_traco_do_excel(planilha, mapping):
    """M mostra "-" quando o saldo cobre o pagamento — representamos como None."""
    fills = fills_de({8: (Decimal("5000"), Decimal("1000"))}, planilha, mapping)
    linha = compute_panel(fills, mapping, planilha).by_row(8)

    assert linha.aporte_minimo is None
    assert not linha.precisa_aporte
    assert linha.saldo_final == Decimal("4000")
    assert linha.saldo_pos_aporte == Decimal("4000")


def test_deficit_simples_gera_aporte_igual_ao_buraco(planilha, mapping):
    fills = fills_de({10: (Decimal("300"), Decimal("1000"))}, planilha, mapping)
    linha = compute_panel(fills, mapping, planilha).by_row(10)

    assert linha.saldo_final == Decimal("-700")
    assert linha.aporte_minimo == Decimal("700")
    assert linha.precisa_aporte
    assert linha.saldo_pos_aporte == Decimal("0")  # aporte exato zera a conta


def test_rateio_do_buritis_inter_e_dois_para_um(planilha, mapping):
    """Morais Engenharia sempre aporta o dobro da Julio/Livian."""
    fills = fills_de({9: (Decimal("0"), Decimal("30000"))}, planilha, mapping)
    resultado = compute_panel(fills, mapping, planilha)
    linha = resultado.by_row(9)

    parte_morais = linha.aporte_minimo
    parte_julio_livian = resultado.rateios_secundarios[CELULA_RATEIO]

    assert parte_morais == Decimal("30000") * Decimal("0.667")
    assert parte_morais / parte_julio_livian == Decimal("2")
    # Os dois aportes juntos cobrem o deficit (com o leve excesso do 0,667).
    assert parte_morais + parte_julio_livian >= Decimal("30000")
    assert linha.saldo_pos_aporte == linha.saldo_final + parte_morais + parte_julio_livian


def test_fator_0667_sobre_aporta_meio_milesimo(planilha, mapping):
    """0,667 e aproximacao de 2/3: a soma passa 0,05% do deficit, para cima."""
    deficit = Decimal("30000")
    fills = fills_de({9: (Decimal("0"), deficit)}, planilha, mapping)
    resultado = compute_panel(fills, mapping, planilha)

    soma = resultado.by_row(9).aporte_minimo + resultado.rateios_secundarios[CELULA_RATEIO]
    assert soma == deficit * Decimal("1.0005")
    assert soma - deficit == Decimal("15.000")  # sobra em 30 mil de deficit


def test_sem_deficit_no_buritis_nao_ha_rateio(planilha, mapping):
    fills = fills_de({9: (Decimal("50000"), Decimal("1000"))}, planilha, mapping)
    resultado = compute_panel(fills, mapping, planilha)

    assert resultado.by_row(9).aporte_minimo is None
    assert resultado.rateios_secundarios[CELULA_RATEIO] == Decimal("0")


def test_aporte_da_linha_12_e_direcionado_para_a_linha_8(planilha, mapping):
    """N12 aponta para "MORAIS ENGENHARIA - INTER", logo F8 recebe M12."""
    fills = fills_de(
        {
            12: (Decimal("0"), Decimal("1000")),  # deficit de 1000 na Sicoob
            8: (Decimal("500"), Decimal("0")),  # Inter tem 500 e nada a pagar
        },
        planilha,
        mapping,
    )
    resultado = compute_panel(fills, mapping, planilha)

    linha12, linha8 = resultado.by_row(12), resultado.by_row(8)
    assert linha12.aporte_minimo == Decimal("1000")
    assert linha12.aporte_direcionado_para == "MORAIS ENGENHARIA - INTER"

    # O aporte de 1000 chega na linha 8 e derruba o saldo final dela.
    assert linha8.aportes_recebidos == Decimal("1000")
    assert linha8.saldo_final == Decimal("-500")
    assert linha8.aporte_minimo == Decimal("500")


def test_linha_12_nao_recebe_aporte_porque_f12_e_zero_fixo(planilha, mapping):
    fills = fills_de({12: (Decimal("0"), Decimal("1000"))}, planilha, mapping)
    assert compute_panel(fills, mapping, planilha).by_row(12).aportes_recebidos == Decimal("0")


def test_linhas_sem_conta_no_erp_nao_pedem_aporte(planilha, mapping):
    resultado = compute_panel(fills_de({}, planilha, mapping), mapping, planilha)
    for row in (30, 31):
        linha = resultado.by_row(row)
        assert linha.aporte_minimo == Decimal("0")
        assert not linha.precisa_aporte
        assert linha.saldo_final == Decimal("0")


def test_total_de_pagamentos_espelha_e33(planilha, mapping):
    fills = fills_de(
        {8: (Decimal("0"), Decimal("1000.50")), 10: (Decimal("0"), Decimal("2000.25"))},
        planilha,
        mapping,
    )
    assert compute_panel(fills, mapping, planilha).total_pagamentos == Decimal("3000.75")


def test_saldo_negativo_aparece_no_resumo(planilha, mapping):
    fills = fills_de({8: (Decimal("-1500.75"), Decimal("0"))}, planilha, mapping)
    negativos = compute_panel(fills, mapping, planilha).saldos_negativos
    assert [r.row for r in negativos] == [8]


def test_saldo_nao_lido_e_sinalizado(planilha, mapping):
    """Saldo vazio faria o painel pedir aporte do valor inteiro — precisa alertar."""
    fills = fills_de({8: (None, Decimal("1000"))}, planilha, mapping)
    resultado = compute_panel(fills, mapping, planilha)

    assert [r.row for r in resultado.saldos_nao_lidos] == [8]
    # Confirma o risco: sem saldo, o aporte minimo vira o pagamento inteiro.
    assert resultado.by_row(8).aporte_minimo == Decimal("1000")


def test_dia_sem_pagamentos_nao_pede_aporte_de_ninguem(planilha, mapping):
    resultado = compute_panel(fills_de({}, planilha, mapping), mapping, planilha)
    assert resultado.precisam_aporte == []
    assert resultado.total_pagamentos == Decimal("0")
