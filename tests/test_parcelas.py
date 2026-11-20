"""Qual parcela do título a linha paga (spec de 19/11/2026, parte 2).
Títulos fictícios no formato medido na Tarefa 1 do plano."""
from pagamentos_dia import parcelas
from pagamentos_dia.relatorio import Resultado


def _titulo(*ids, campo="order"):
    # Medido em 20/11/2026: `order` começa em 0 (respostas guardadas de
    # trade-payables/<id>).
    return {"installments": [{"id": i, campo: k, "plannedDate": f"2026-{k + 1:02d}-10"}
                             for k, i in enumerate(ids)]}


def test_posicao_pela_ordem_do_erp():
    assert parcelas.posicao(_titulo("a", "b", "c"), "b") == 2


def test_posicao_pela_data_quando_nao_ha_campo_de_ordem():
    t = {"installments": [{"id": "x", "plannedDate": "2026-03-10"},
                          {"id": "y", "plannedDate": "2026-01-10"}]}
    assert parcelas.posicao(t, "x") == 2 and parcelas.posicao(t, "y") == 1


def test_parcela_fora_do_titulo_ou_titulo_vazio_e_none():
    assert parcelas.posicao(_titulo("a"), "z") is None
    assert parcelas.posicao(None, "a") is None and parcelas.posicao({}, "a") is None


def test_titulos_parcelados_so_os_de_mais_de_uma():
    itens = [{"tradePayableId": "T1", "numberOfFinancingInstallments": 1},
             {"tradePayableId": "T2", "numberOfFinancingInstallments": 10},
             {"tradePayableId": "T3", "numberOfFinancingInstallments": "lixo"},
             {"tradePayableId": "T2", "numberOfFinancingInstallments": 10}]
    assert parcelas.titulos_parcelados(itens) == ["T2"]


def _res(*regs):
    return Resultado({"CONTA EXEMPLO": list(regs)}, [])


def test_anotar_parcela_e_observacao():
    sel = [{"id": "b", "tradePayableId": "T2", "numberOfFinancingInstallments": 3}]
    r = {"id": "b"}
    parcelas.anotar(_res(r), sel, {"T2": _titulo("a", "b", "c")},
                    {"b": {"comment": "pagar depois da medição"}})
    assert r["parcela"] == {"numero": 2, "total": 3}
    assert r["obs_parcela"] == "pagar depois da medição"


def test_titulo_que_nao_leu_fica_sem_numero():
    sel = [{"id": "b", "tradePayableId": "T2", "numberOfFinancingInstallments": 3}]
    r = {"id": "b"}
    parcelas.anotar(_res(r), sel, {}, {})
    assert r["parcela"] == {"numero": None, "total": 3}


def test_parcela_unica_nao_ganha_parcela_mas_ganha_observacao():
    sel = [{"id": "u", "tradePayableId": "T1", "numberOfFinancingInstallments": 1}]
    r = {"id": "u"}
    parcelas.anotar(_res(r), sel, {}, {"u": {"comment": "nota da parcela"}})
    assert "parcela" not in r and r["obs_parcela"] == "nota da parcela"


def test_lancamento_dividido_em_boletos_nao_e_parcela():
    # boletos_somados: duas linhas do MESMO id, com "parte" 1/2 e 2/2,
    # num título de UMA parcela. Nenhuma das duas vira "Parcela k de N".
    sel = [{"id": "d", "tradePayableId": "T9", "numberOfFinancingInstallments": 1}]
    p1, p2 = {"id": "d", "parte": "1/2"}, {"id": "d", "parte": "2/2"}
    parcelas.anotar(_res(p1, p2), sel, {}, {})
    assert "parcela" not in p1 and "parcela" not in p2


def test_remontar_sem_parcelas_erp_nao_anota(monkeypatch):
    from pagamentos_dia import confirmacao
    chamou = []
    monkeypatch.setattr(parcelas, "anotar", lambda *a, **k: chamou.append(1) or a[0])
    e = confirmacao.Entradas(selecionados=[], anexos={}, overviews={}, textos={}, urls_ocr=set(),
                             cadastro_reembolso=None, regras_fornecedor={}, participantes={},
                             periodo=(None, None))
    confirmacao.remontar(e)
    assert chamou == []
    e.parcelas_erp = {}
    confirmacao.remontar(e)
    assert chamou == [1]


def test_leitura_le_o_titulo_so_dos_parcelados_e_anota_a_linha():
    from datetime import date

    from pagamentos_dia import leitura_do_dia as ld
    from test_leitura_do_dia import LEITORES, ApiFalsa, _anexo, _lanc, _sem_cadastro, _sem_nuvem

    pedidos = []
    original = ld.titulo_no_erp

    def titulo_falso(api, tpid):
        pedidos.append(tpid)
        return {"installments": [{"id": "outra", "order": 0}, {"id": "L1", "order": 1},
                                 {"id": "mais", "order": 2}]}
    ld.titulo_no_erp = titulo_falso
    try:
        api = ApiFalsa([_lanc("L1", numberOfFinancingInstallments=3), _lanc("L2")],
                       anexos={"T-L1": [_anexo("nota 1234")], "T-L2": [_anexo("nota 99")]})
        leitura = ld.ler_pagamentos(api, date(2026, 10, 21), date(2026, 10, 21),
                                    abrir_historico=_sem_nuvem, carregar_mapas=_sem_cadastro,
                                    **LEITORES)
    finally:
        ld.titulo_no_erp = original
    assert pedidos == ["T-L1"]
    regs = {r["id"]: r for rs in leitura.resultado.contas.values() for r in rs}
    assert regs["L1"]["parcela"] == {"numero": 2, "total": 3}
    assert "parcela" not in regs["L2"]
