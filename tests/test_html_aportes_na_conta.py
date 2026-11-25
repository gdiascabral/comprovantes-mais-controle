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
    assert alfa["entries"] == antes["entries"]      # lançamentos intactos
    assert len(alfa["aportes"]) == 1
    linha = alfa["aportes"][0]
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
    ids = [e["id"] for e in alfa["aportes"]]
    assert ids == ["aporte:CONTA ALFA - SICOOB:CONTA GAMA - SICOOB:40000:1",
                   "aporte:CONTA ALFA - SICOOB:CONTA GAMA - SICOOB:40000:2"]
    todos = [e["id"] for c in _json(_ler(g.geral), "DATA")["contas"]
             for e in c["entries"] + c.get("aportes", [])]
    assert len(todos) == len(set(todos))
    # gerar de novo dá os mesmos ids (a marca PAGO sobrevive)
    g2 = _gravar(tmp_path / "2", movimentos=[APORTE, outro])
    alfa2 = _conta(_json(_ler(g2.geral), "DATA"), "CONTA ALFA - SICOOB")
    assert [e["id"] for e in alfa2["aportes"]] == ids


def test_casa_a_conta_pelo_rotulo_do_painel_sem_acento_nem_caixa(tmp_path):
    mov = dict(APORTE, de="  rotulo   alfa ")
    g = _gravar(tmp_path, movimentos=[mov],
                rotulo_de=lambda conta: "ROTULO ALFA" if "ALFA" in conta else "")
    dados = _json(_ler(g.geral), "DATA")
    assert len(_conta(dados, "CONTA ALFA - SICOOB")["aportes"]) == 1
    assert dados["movimentos"] == []


def test_de_que_nao_casa_continua_na_secao_informativa_com_aviso(tmp_path):
    g = _gravar(tmp_path, movimentos=[FORA])
    dados = _json(_ler(g.geral), "DATA")
    assert all(not c.get("aportes") for c in dados["contas"])
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


# ----------------------------------------------- revisão de dinheiro (25/11)
def test_aporte_nao_entra_nas_entries_nem_na_conferencia_de_agendamentos(tmp_path):
    from pagamentos_dia import agendamentos_sicoob as A
    g = _gravar(tmp_path, movimentos=[APORTE])
    contas = A.ler_html(_ler(g.geral))
    alfa = _conta({"contas": contas}, "CONTA ALFA - SICOOB")
    [(_nome, _num, linhas)] = A.agrupar_por_numero([(alfa, "12345-6", "")])
    assert not any(e.get("aporte") for e in linhas)
    # pendência no banco de MESMO valor do aporte: não é absorvida
    banco = {"valor": 400.0, "detalhe": "CONTA GAMA", "observacao": None,
             "nomeTransacao": "Pagamento de Título", "pendencia": "p1"}
    sit = [li.situacao for li in A.confrontar(linhas, [banco])]
    assert A.SO_NO_BANCO in sit


def test_agendamentos_ignora_entrada_marcada_aporte_mesmo_dentro_de_entries():
    from pagamentos_dia import agendamentos_sicoob as A
    conta = {"nome": "X", "entries": [
        {"centavos": 40000, "favorecido": "G", "descricao": "d", "aporte": True},
        {"centavos": 100, "favorecido": "L", "descricao": "d"}]}
    [(_n, _num, linhas)] = A.agrupar_por_numero([(conta, "1", "")])
    assert [e["centavos"] for e in linhas] == [100]


def test_nome_exato_do_erp_vence_o_rotulo_do_painel(tmp_path):
    # o rótulo de ALFA é igual ao NOME de BETA: `de` = nome de BETA -> BETA
    mov = dict(APORTE, de="CONTA BETA - INTER")
    g = _gravar(tmp_path, movimentos=[mov],
                rotulo_de=lambda c: "CONTA BETA - INTER" if "ALFA" in c else "")
    dados = _json(_ler(g.geral), "DATA")
    assert not _conta(dados, "CONTA ALFA - SICOOB").get("aportes")
    assert len(_conta(dados, "CONTA BETA - INTER")["aportes"]) == 1


def test_rotulo_que_aponta_para_duas_contas_e_ambiguo(tmp_path):
    mov = dict(APORTE, de="ROTULO COMUM")
    g = _gravar(tmp_path, movimentos=[mov], rotulo_de=lambda c: "ROTULO COMUM")
    dados = _json(_ler(g.geral), "DATA")
    assert all(not c.get("aportes") for c in dados["contas"])
    assert dados["movimentos"][0]["aviso"] == "conta de origem ambígua"
    assert g.total_aportes_na_conta == 0


def test_so_tipo_declarado_aporte_soma(tmp_path):
    from tela_do_dia import decisoes as dc
    desconhecido = dict(APORTE, tipo=dc._tipo_da_regra("Reserva"))
    vazio = dict(APORTE, tipo=dc._tipo_da_regra(""))
    assert dc._tipo_da_regra("Aporte") == dc.TIPO_APORTE_REGRAS
    assert dc._tipo_da_regra("aporte de capital") == dc.TIPO_APORTE_REGRAS
    assert not hp.e_aporte(desconhecido["tipo"]) and not hp.e_aporte(vazio["tipo"])
    g = _gravar(tmp_path, movimentos=[desconhecido, vazio])
    dados = _json(_ler(g.geral), "DATA")
    assert all(not c.get("aportes") for c in dados["contas"])
    assert len(dados["movimentos"]) == 2
    assert all("aviso" not in m for m in dados["movimentos"])


def test_aporte_de_fora_fica_informativo_com_aviso_proprio(tmp_path):
    from tela_do_dia import decisoes as dc
    mov = dict(APORTE, de=dc.DE_FORA, tipo=dc.TIPO_APORTE_NA_MAE)
    g = _gravar(tmp_path, movimentos=[mov])
    m = _json(_ler(g.geral), "DATA")["movimentos"][0]
    assert m["aviso"] == "aporte de fora — não sai de conta do HTML"
    assert hp.AVISO_DE_FORA_PREFIXO == hp._chave_conta(dc.DE_FORA)[:len(hp.AVISO_DE_FORA_PREFIXO)]


def test_frame_usa_o_rotulo_que_respeita_conta_ignorada():
    from pathlib import Path
    fonte = (Path(__file__).resolve().parents[1] / "tela_do_dia" / "frame.py").read_text(encoding="utf-8")
    assert "rotulo_de=self._rotulo_que_cobre" in fonte
    assert "rotulo_de=self._rotulo_do_painel" not in fonte
