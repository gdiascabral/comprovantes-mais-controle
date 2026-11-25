# -*- coding: utf-8 -*-
"""Aporte dentro da lista e do total da conta de onde o dinheiro SAI (25/11/2026).

Dono: "inclua os aportes dentro da lista e valor de pgtos da conta". O aporte
vira linha da conta de origem (`de`), sem chave nem Copiar, e soma no total da
conta e no total geral. Transferência e distribuição seguem só informativas;
nada disso vai para `Resultado.contas` (remessa/planilha). Tudo fictício."""
from decimal import Decimal

from pagamentos_dia import html_pagamentos as hp
from pagamentos_dia import modelos_html
from tests.test_html_pagamentos import _gravar, _json, _ler, _resultado

APORTE = {"de": "CONTA ALFA - SICOOB", "para": "CONTA GAMA - SICOOB",
          "tipo": "Aporte (aba Regras)", "valor": Decimal("400.00")}
TRANSF = {"de": "CONTA ALFA - SICOOB", "para": "CONTA BETA - INTER",
          "tipo": "Transferência entre contas", "valor": Decimal("0.10")}
DISTRIB = {"de": "CONTA ALFA - SICOOB", "para": "SOCIO FICTICIO",
           "tipo": "Distribuição de lucros", "valor": Decimal("0.20")}
FORA = {"de": "CONTA INEXISTENTE", "para": "CONTA GAMA - SICOOB",
        "tipo": "Aporte que entra na mãe", "valor": Decimal("50.00")}


def _conta(dados, nome):
    return next(c for c in dados["contas"] if c["nome"] == nome)


def test_aporte_vira_linha_da_conta_de_origem_e_soma_no_total(tmp_path):
    sem = _json(_ler(_gravar(tmp_path / "s").geral), "DATA")
    g = _gravar(tmp_path / "c", movimentos=[APORTE])
    dados = _json(_ler(g.geral), "DATA")
    alfa = _conta(dados, "CONTA ALFA - SICOOB")
    antes = _conta(sem, "CONTA ALFA - SICOOB")
    assert len(alfa["entries"]) == len(antes["entries"]) + 1
    linha = alfa["entries"][-1]
    assert linha["aporte"] is True
    assert linha["tipo"] == "Aporte" and linha["favorecido"] == "CONTA GAMA - SICOOB"
    assert linha["valor"] == "400,00" and linha["centavos"] == 40000
    assert linha["dados_limpo"] == "" and linha["link"] == "" and linha["bloqueio"] == ""
    assert "nivel" not in linha
    # total da conta: 0,10 + 0,20 + 1.234,56 + 400,00
    assert alfa["total"] == "1.634,86"
    assert _conta(dados, "CONTA BETA - INTER")["entries"] == _conta(
        sem, "CONTA BETA - INTER")["entries"]
    assert dados["movimentos"] == []
    assert g.total == Decimal("1634.86") + Decimal("99.99")
    assert g.aportes_na_conta == 1 and g.total_aportes_na_conta == Decimal("400.00")


def test_id_do_aporte_e_estavel_e_nao_colide_com_lancamento(tmp_path):
    outro = dict(APORTE, valor=Decimal("400.00"))
    g = _gravar(tmp_path, movimentos=[APORTE, outro])
    alfa = _conta(_json(_ler(g.geral), "DATA"), "CONTA ALFA - SICOOB")
    ids = [e["id"] for e in alfa["entries"] if e.get("aporte")]
    assert ids == ["aporte:CONTA ALFA - SICOOB:CONTA GAMA - SICOOB:40000:1",
                   "aporte:CONTA ALFA - SICOOB:CONTA GAMA - SICOOB:40000:2"]
    todos = [e["id"] for c in _json(_ler(g.geral), "DATA")["contas"] for e in c["entries"]]
    assert len(todos) == len(set(todos))
    # gerar de novo dá os mesmos ids (a marca PAGO sobrevive)
    g2 = _gravar(tmp_path / "2", movimentos=[APORTE, outro])
    alfa2 = _conta(_json(_ler(g2.geral), "DATA"), "CONTA ALFA - SICOOB")
    assert [e["id"] for e in alfa2["entries"] if e.get("aporte")] == ids


def test_casa_a_conta_pelo_rotulo_do_painel_sem_acento_nem_caixa(tmp_path):
    mov = dict(APORTE, de="  rotulo   alfa ")
    g = _gravar(tmp_path, movimentos=[mov],
                rotulo_de=lambda conta: "ROTULO ALFA" if "ALFA" in conta else "")
    dados = _json(_ler(g.geral), "DATA")
    assert any(e.get("aporte") for e in _conta(dados, "CONTA ALFA - SICOOB")["entries"])
    assert dados["movimentos"] == []


def test_de_que_nao_casa_continua_na_secao_informativa_com_aviso(tmp_path):
    g = _gravar(tmp_path, movimentos=[FORA])
    dados = _json(_ler(g.geral), "DATA")
    assert all(not e.get("aporte") for c in dados["contas"] for e in c["entries"])
    assert len(dados["movimentos"]) == 1
    assert dados["movimentos"][0]["aviso"] == "conta de origem não está no HTML"
    assert g.total_aportes_na_conta == 0 and g.movimentos == 1


def test_transferencia_e_distribuicao_seguem_so_informativas(tmp_path):
    sem = _gravar(tmp_path / "s")
    g = _gravar(tmp_path / "c", movimentos=[TRANSF, DISTRIB])
    dados = _json(_ler(g.geral), "DATA")
    assert dados["contas"] == _json(_ler(sem.geral), "DATA")["contas"]
    assert [m["tipo"] for m in dados["movimentos"]] == [TRANSF["tipo"], DISTRIB["tipo"]]
    assert all("aviso" not in m for m in dados["movimentos"])
    assert g.total == sem.total


def test_aporte_nao_vai_para_o_resultado_da_remessa(tmp_path):
    res = _resultado()
    antes = {k: list(v) for k, v in res.contas.items()}
    _gravar(tmp_path, resultado=res, movimentos=[APORTE])
    assert {k: list(v) for k, v in res.contas.items()} == antes


def test_contadores_dos_tres_niveis_nao_contam_o_aporte():
    m = modelos_html.MODELO_GERAL
    i = m.index("function renderNiveis")
    corpo = m[i:m.index("function renderSummary")]
    assert "e.aporte" in corpo


def test_modelo_desenha_o_aporte_sem_copiar_chave_e_com_etiqueta():
    m = modelos_html.MODELO_GERAL
    assert "if(e.aporte)" in m
    i = m.index("function linhaDoAporte")
    corpo = m[i:m.index("\n}\n", i)]
    assert "copybtn" not in corpo and "copyText" not in corpo
    assert "tipo-aporte" in corpo and "data-nivel" not in corpo
    assert "m.aviso" in m


def test_registro_diz_que_aporte_soma_na_conta_de_origem(tmp_path):
    g = _gravar(tmp_path, movimentos=[APORTE, TRANSF])
    texto = "\n".join(g.registro())
    assert "aporte(s) na conta de origem" in texto and "R$ 400,00" in texto
    assert "somam no total" in texto
    # a frase dos informativos não promete mais "fora do total" dos aportes
    assert "R$ 0,10" in texto


def test_movimentos_do_html_continua_so_com_cinco_chaves_sem_aviso():
    assert set(hp.movimentos_do_html([APORTE])[0]) == {
        "de", "para", "tipo", "valor", "centavos"}
