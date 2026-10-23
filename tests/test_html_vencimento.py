# -*- coding: utf-8 -*-
"""Vencimento em cada linha e movimentos do dia logo depois do resumo
(pedidos do dono, 23/10/2026, olhando o HTML real do dia).

1. "faltou colocar a data de vcto de cada lançamento": cada linha das contas
   leva o vencimento do lançamento (o `plannedDate` que o relatório já lê,
   `relatorio.data_do_item`), numa coluna VENC.; anterior ao dia do HTML sai
   em vermelho com "vencido"; linha à mão sem vencimento mostra "—".
2. "não veio os lançamentos de aportes": vieram, mas a seção ficava no FIM
   da página. Ela sobe para logo depois do quadro-resumo, e o resumo ganha
   uma linha com link para ela.

Puro: sem janela, sem ERP, sem rede. Tudo fictício (o repositório é público).
"""
from decimal import Decimal

from pagamentos_dia import html_pagamentos as hp
from pagamentos_dia import modelos_html
from pagamentos_dia import relatorio
from pagamentos_dia.relatorio import Resultado
from tests.test_descricao_e_ordem import CUPOM, _boleto_sem_anexo
from tests.test_html_pagamentos import INI, _gravar, _json, _ler, _linha


# ------------------------------------------------------------ do ERP ao registro
def test_o_registro_leva_o_vencimento_do_lancamento():
    item = _boleto_sem_anexo(plannedDate="2026-08-31T00:00:00")
    res = relatorio.montar_registros([item], CUPOM, {}, {})
    (linha,) = [r for regs in res.contas.values() for r in regs]
    assert linha["vencimento"] == "2026-08-31"


def test_lancamento_sem_data_leva_vencimento_vazio():
    res = relatorio.montar_registros([_boleto_sem_anexo()], CUPOM, {}, {})
    (linha,) = [r for regs in res.contas.values() for r in regs]
    assert linha["vencimento"] == ""


# ------------------------------------------------------------ registro ao HTML
def _res(*linhas):
    return Resultado({"CONTA ALFA - SICOOB": list(linhas)}, [])


def test_entries_levam_o_vencimento_em_dd_mm_aaaa_e_se_esta_vencido():
    res = _res(_linha("FORNECEDOR UM", 1, "1", vencimento="2026-08-31"),
               _linha("FORNECEDOR DOIS", 2, "2", vencimento="2026-09-01"),
               _linha("FORNECEDOR TRES", 3, "3", vencimento="2026-09-05"),
               _linha("A MAO SEM LANCAMENTO", 4, "", a_mao="mao:1"))
    e = hp.contas_do_html_geral(res, dia=INI)[0]["entries"]
    assert [(x["vencimento"], x["vencido"]) for x in e] == [
        ("31/08/2026", True), ("01/09/2026", False), ("05/09/2026", False),
        ("", False)]


def test_sem_dia_nada_sai_vencido():
    res = _res(_linha("FORNECEDOR UM", 1, "1", vencimento="2020-01-01"))
    (e,) = hp.contas_do_html_geral(res)[0]["entries"]
    assert e["vencimento"] == "01/01/2020" and e["vencido"] is False


def test_partes_de_um_lancamento_dividido_levam_o_mesmo_vencimento():
    base = _linha("FORNECEDOR UM", 1, "9", tipo="Boleto", vencimento="2026-08-30")
    res = _res(dict(base, parte_linha="111"), dict(base, parte_linha="222"))
    e = hp.contas_do_html_geral(res, dia=INI)[0]["entries"]
    assert {(x["vencimento"], x["vencido"]) for x in e} == {("30/08/2026", True)}


def test_gravar_usa_o_primeiro_dia_do_periodo(tmp_path):
    res = _res(_linha("FORNECEDOR UM", 1, "1", vencimento="2026-08-31"),
               _linha("FORNECEDOR DOIS", 2, "2", vencimento="2026-09-01"))
    g = _gravar(tmp_path, resultado=res)
    e = _json(_ler(g.geral), "DATA")["contas"][0]["entries"]
    assert [(x["vencimento"], x["vencido"]) for x in e] == [
        ("31/08/2026", True), ("01/09/2026", False)]


def test_o_modelo_tem_a_coluna_venc():
    m = modelos_html.MODELO_GERAL
    inicio = m.index("function renderAccounts")
    corpo = m[inicio:m.index("\n}\n", inicio)]
    assert "<th>Venc.</th>" in corpo
    assert "e.vencimento" in corpo and "e.vencido" in corpo
    assert "vencido" in corpo and "—" in corpo
    # oito colunas, somando 100%
    larguras = [int(x) for x in
                corpo.split("<colgroup>")[1].split("</colgroup>")[0]
                .replace('<col style="width:', " ").replace('%">', " ").split()]
    assert len(larguras) == 8 and sum(larguras) == 100


# ------------------------------------------------------------ movimentos no topo
def test_a_secao_de_movimentos_vem_antes_das_contas():
    m = modelos_html.MODELO_GERAL
    resumo, movs, contas = (m.index('id="resumo"'), m.index('id="movimentos"'),
                            m.index('id="accounts"'))
    assert resumo < movs < contas


def test_o_resumo_tem_o_link_para_os_movimentos():
    m = modelos_html.MODELO_GERAL
    resumo = m[m.index('id="resumo"'):m.index('id="movimentos"')]
    assert 'href="#movimentos"' in resumo and 'id="movResumo"' in resumo
    inicio = m.index("function renderMovimentos")
    corpo = m[inicio:m.index("\n}\n", inicio)]
    assert "movResumo" in corpo and "Movimentos do dia:" in corpo


def test_movimentos_continuam_fora_do_total_geral(tmp_path):
    movs = [{"de": "de fora", "para": "CONTA ALFA - SICOOB",
             "tipo": "Aporte que entra na mãe", "valor": Decimal("400.00")}]
    sem = _gravar(tmp_path / "sem")
    com = _gravar(tmp_path / "com", movimentos=movs)
    assert com.total == sem.total and com.total_movimentos == Decimal("400.00")
