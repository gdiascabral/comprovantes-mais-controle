# tests/test_relatorio_aportes.py
# -*- coding: utf-8 -*-
"""Relatório de aportes e distribuições do Controle de aportes (25/11/2026).
Sem tela e sem rede; nomes e contas fictícios."""
import datetime
from decimal import Decimal as D
from urllib.parse import parse_qsl, urlsplit

import pytest

from conciliacao.errors import ErpError
from tela_do_dia import controle_aportes as ca
from tela_do_dia import controle_erp as ce
from tela_do_dia import relatorio_aportes as ra
from tela_do_dia import relatorio_aportes_pdf as rpdf

ALFA, BETA = "FULANO ALFA DA SILVA", "CICRANA BETA DE SOUZA"
SICOOB, INTER = "EMPRESA FICTICIA - SICOOB", "EMPRESA FICTICIA - INTER"
DE, ATE = datetime.date(2026, 1, 1), datetime.date(2026, 11, 25)
CONTA = ca.ContaControlada(SICOOB, datetime.date(2026, 10, 1),
                           (ca.Aportador(ALFA, D(1), id=10), ca.Aportador(BETA, D(1), id=11)),
                           id=1, somadas=(INTER,))


def rec(ident, dia, valor, cliente=ALFA):
    return ca.Recebimento(ident, dia, D(valor), cliente)


def pago(ident, dia, valor_centavos, favorecido=ALFA, conta=SICOOB,
         categoria="Distribuição de Lucros"):
    return {"paidId": ident, "dataFull": dia, "valor": valor_centavos, "favorecido": favorecido,
            "conta": conta, "categoria": categoria}


def _rel(recs=(), pagos=(), socio=ra.TODOS, apontamentos=(), onde=None):
    onde = onde if onde is not None else {r.id: SICOOB for r in recs}
    return ra.montar(CONTA, socio, DE, ATE, list(recs), onde, list(apontamentos), list(pagos))


# ---- aportes ---------------------------------------------------------------

def test_aporte_antes_da_abertura_do_controle_entra_no_relatorio():
    rel = _rel([rec("r1", datetime.date(2026, 3, 10), "5000.00")])
    assert [(m.data, m.conta, m.socio, m.valor) for m in rel.aportes] == [
        (datetime.date(2026, 3, 10), SICOOB, ALFA, D("5000.00"))]


def test_um_socio_so_mostra_o_dele():
    recs = [rec("r1", datetime.date(2026, 3, 10), "100"), rec("r2", datetime.date(2026, 3, 11), "200", BETA)]
    rel = _rel(recs, socio=BETA)
    assert rel.socios == (BETA,)
    assert [m.socio for m in rel.aportes] == [BETA]


def test_socio_que_nao_e_aportador_recusa():
    with pytest.raises(ValueError, match="não é aportador"):
        _rel([], socio="OUTRA PESSOA QUALQUER")


def test_conta_de_cada_aporte_vem_de_quem_leu():
    recs = [rec("r1", datetime.date(2026, 3, 10), "100"), rec("r2", datetime.date(2026, 3, 11), "200")]
    rel = _rel(recs, onde={"r1": SICOOB, "r2": INTER})
    assert [m.conta for m in rel.aportes] == [SICOOB, INTER]


def test_sem_dono_fica_fora_e_a_tela_avisa():
    recs = [rec("r1", datetime.date(2026, 3, 10), "100"), rec("r2", datetime.date(2026, 3, 11), "250", "ALFA")]
    rel = _rel(recs)
    assert len(rel.aportes) == 1 and [r.id for r, _ in rel.fora] == ["r2"]
    aviso = ra.texto_do_fora(rel)
    assert "R$ 250,00" in aviso and "FORA" in aviso and "1 de ALFA: R$ 250,00" in aviso
    assert ra.texto_do_fora(_rel(recs[:1])) == ""


def test_apontamento_vale_no_relatorio_como_na_tela():
    r = rec("r2", datetime.date(2026, 3, 11), "250", "")
    rel = _rel([r], apontamentos=[ca.Apontamento("r2", 11, D("250.00"), "pix dela")])
    assert [(m.socio, m.valor) for m in rel.aportes] == [(BETA, D("250.00"))]
    fora = _rel([r], apontamentos=[ca.Apontamento("r2", None, D("250.00"), "não é")])
    assert fora.aportes == [] and fora.fora == []


def test_mesma_decisao_da_apuracao():
    """O relatório e a tela nunca discordam de quem pôs o quê."""
    recs = [rec("r1", datetime.date(2026, 10, 2), "100"), rec("r2", datetime.date(2026, 10, 3), "300", BETA),
            rec("r3", datetime.date(2026, 10, 4), "7", "SEM NOME")]
    ap = ca.apurar(CONTA, recs, [], ATE)
    rel = ra.montar(CONTA, ra.TODOS, CONTA.abertura, ATE, recs, {}, [], [])
    soma = {l.nome: l.do_erp for l in ap.linhas}
    assert {s: a for s, a, _ in ra.resumo_por_socio(rel)} == soma
    assert [r.id for r, _ in rel.fora] == [s.recebimento.id for s in ap.sem_dono]


@pytest.mark.parametrize("recs, msg", [
    ([rec("r1", datetime.date(2026, 3, 1), "1"), rec("r1", datetime.date(2026, 3, 1), "1")], "duas vezes"),
    ([rec("r1", datetime.date(2025, 12, 31), "1")], "fora do período"),
    ([rec("r1", datetime.date(2026, 3, 1), "-5")], "negativo"),
    ([rec("r1", datetime.date(2026, 3, 1), "0")], "zerado"),
])
def test_leitura_duvidosa_para_sem_relatorio(recs, msg):
    with pytest.raises(ValueError, match=msg):
        _rel(recs)


# ---- distribuições ---------------------------------------------------------

def test_distribuicao_so_da_categoria_das_contas_e_para_o_socio():
    pagos = [pago("p1", "2026-06-02", 5000000),
             pago("p2", "2026-06-03", 100, favorecido="OUTRA EMPRESA LTDA"),
             pago("p3", "2026-06-04", 200, conta="OUTRA CONTA - BANCO"),
             pago("p4", "2026-06-05", 300, categoria="Aporte Capital"),
             pago("p5", "2026-06-06", 400, favorecido=BETA, conta=INTER),
             pago("p6", "2025-12-31", 500)]
    rel = _rel(pagos=pagos)
    assert [(m.data.day, m.conta, m.socio, m.valor) for m in rel.distribuicoes] == [
        (2, SICOOB, ALFA, D("50000.00")), (6, INTER, BETA, D("4.00"))]


def test_categoria_e_favorecido_comparam_sem_acento_nem_caixa():
    rel = _rel(pagos=[pago("p1", "2026-06-02", 100, favorecido="fulano  álfa da silva",
                           categoria="DISTRIBUICAO DE LUCROS")])
    assert [m.socio for m in rel.distribuicoes] == [ALFA]


@pytest.mark.parametrize("pagos, msg", [
    ([pago("p1", "2026-06-02", 100), pago("p1", "2026-06-02", 100)], "duas vezes"),
    ([pago("p1", "", 100)], "sem data"),
    ([pago("p1", "2026-06-02", 0)], "sem valor"),
])
def test_distribuicao_duvidosa_para(pagos, msg):
    with pytest.raises(ValueError, match=msg):
        _rel(pagos=pagos)


# ---- resumo, nomes e período ------------------------------------------------

def test_resumo_mensal_e_por_socio():
    recs = [rec("r1", datetime.date(2026, 3, 10), "100"), rec("r2", datetime.date(2026, 3, 20), "50", BETA),
            rec("r3", datetime.date(2026, 5, 1), "10")]
    rel = _rel(recs, pagos=[pago("p1", "2026-05-02", 7000)])
    assert ra.resumo_mensal(rel) == [(datetime.date(2026, 3, 1), D("150.00"), D("0.00")),
                                     (datetime.date(2026, 5, 1), D("10.00"), D("70.00"))]
    assert ra.resumo_por_socio(rel) == [(ALFA, D("110.00"), D("70.00")), (BETA, D("50.00"), D("0.00"))]
    assert rel.total_aportes == D("160.00") and rel.total_distribuicoes == D("70.00")


def test_empresa_sem_banco_e_banco_sem_empresa():
    assert ra.empresa_da_conta(CONTA) == "EMPRESA FICTICIA"
    assert ra.banco_da_conta(INTER) == "INTER"
    mista = ca.ContaControlada("A - X", DE, somadas=("B - Y",))
    assert ra.empresa_da_conta(mista) == "A - X + B - Y"


def test_nome_do_arquivo_seguro_no_windows():
    rel = _rel(socio=ALFA)
    rel.empresa = 'EMPRESA: "X/Y"'
    nome = ra.nome_do_arquivo(rel)
    assert nome.endswith(".pdf") and not any(c in nome for c in '\\/:*?"<>|')
    assert "01-01-2026 a 25-11-2026" in nome and ALFA in nome


def test_periodo_do_formulario():
    hoje = datetime.date(2026, 11, 25)
    assert ra.periodo_do_formulario("01/01/2026", "31/12/2026", hoje) == (DE, hoje)
    with pytest.raises(ValueError, match="antes"):
        ra.periodo_do_formulario("10/11/2026", "01/11/2026", hoje)
    with pytest.raises(ValueError, match="DD/MM/AAAA"):
        ra.periodo_do_formulario("ontem", "01/11/2026", hoje)


# ---- PDF ---------------------------------------------------------------------

def _texto(doc):
    return " ".join(" ".join(c) for _, _, c in doc)


def test_documento_para_o_socio_nao_tem_saldo_nem_para_igualar():
    recs = [rec("r1", datetime.date(2026, 3, 10), "100")]
    doc = rpdf.linhas_do_documento(_rel(recs, pagos=[pago("p1", "2026-05-02", 7000)]),
                                   datetime.datetime(2026, 11, 25, 10, 0))
    texto = _texto(doc).lower()
    assert "saldo" not in texto and "igualar" not in texto and "deve" not in texto
    assert "R$ 100,00" in _texto(doc) and "R$ 70,00" in _texto(doc) and "março/2026" in texto
    assert ("cab", "socio", ("SÓCIO", "APORTOU", "RECEBEU")) in doc       # dois sócios


def test_um_socio_sem_quadro_por_socio_e_vazio_diz_que_nao_houve():
    doc = rpdf.linhas_do_documento(_rel(socio=ALFA), datetime.datetime(2026, 11, 25))
    assert not any(tabela == "socio" for _, tabela, _ in doc)
    assert "Nenhum aporte nem distribuição no período." in _texto(doc)


def test_tabela_que_continua_repete_o_cabecalho():
    recs = [rec(f"r{i}", datetime.date(2026, 3, 1) + datetime.timedelta(days=i % 200), "1")
            for i in range(90)]
    paginas = rpdf.paginar(rpdf.linhas_do_documento(_rel(recs), datetime.datetime(2026, 11, 25)))
    com_aportes = [p for p in paginas if any(t == "linha" and tb == "mov" for t, tb, _ in p)]
    assert len(com_aportes) >= 3
    for p in com_aportes:
        assert any(t == "cab" and tb == "mov" for t, tb, _ in p)
    linhas = sum(1 for p in paginas for t, tb, _ in p if t == "linha" and tb == "mov")
    assert linhas == 90


def test_gerar_grava_o_pdf(tmp_path):
    from pypdf import PdfReader
    recs = [rec("r1", datetime.date(2026, 3, 10), "100")]
    destino = rpdf.gerar(_rel(recs), tmp_path / "sub" / "r.pdf", datetime.datetime(2026, 11, 25))
    assert len(PdfReader(destino).pages) == 3          # resumo, aportes, distribuições
    assert not (tmp_path / "sub" / "r.pdf.tmp").exists()


# ---- leitura do ERP (dublê) ---------------------------------------------------

class Api:
    def __init__(self, paginas, categorias=None, erro=None):
        self._req_pagos = ("https://legacy/maiscontrole/services/payable-installments/"
                           "paginated-result?organizationUnitId=ou&categoryIds=velha&page=3",
                           {"authorization": "a"})
        self._req_anexos = ("https://erp/attachments/v2", {"authorization": "b"})
        self.paginas, self.erro, self.urls = paginas, erro, []
        self.categorias = categorias if categorias is not None else [
            {"id": "c-dist", "name": "Distribuição de Lucros"}, {"id": "c-ap", "name": "Aporte Capital"}]

    def _base_legacy(self, caminho):
        return f"https://legacy/maiscontrole/services/{caminho}", {"authorization": "a"}

    def _consulta_pagos(self, filtros):
        from anexar.mc_api import MCApi
        return MCApi._consulta_pagos(self, filtros)

    def _fetch_json(self, url, headers):
        self.urls.append(url)
        if "categories/all" in url:
            return self.categorias
        if self.erro:
            return self.erro
        q = dict(parse_qsl(urlsplit(url).query))
        lotes = self.paginas.get((q["accountIds"], q["startDate"]), [[]])
        pagina = int(q["page"])
        return {"content": lotes[pagina], "hasNextPage": pagina + 1 < len(lotes)}


def _item(ident, paid, conta=SICOOB, quando="2026-06-02"):
    return {"id": ident, "category": "Distribuição de Lucros", "paidTo": ALFA,
            "description": "x", "paids": [{"id": paid, "payingDate": quando, "paidValue": 50000.0,
                                            "accountName": conta}]}


def test_pagos_mes_a_mes_com_categoria_e_conta_e_sem_repetir():
    api = Api({("id-s", "2026-06-01"): [[_item("t1", "p1")], [_item("t2", "p2")]],
               ("id-i", "2026-06-01"): [[_item("t1", "p1")]]})
    pagos = ce.pagos_de_distribuicao(api, ["id-s", "id-i"], ra.CATEGORIA_DISTRIBUICAO,
                                     datetime.date(2026, 5, 15), datetime.date(2026, 7, 3))
    assert [p["paidId"] for p in pagos] == ["p1", "p2"]
    assert pagos[0]["valor"] == 5000000 and pagos[0]["favorecido"] == ALFA
    pedidos = [dict(parse_qsl(urlsplit(u).query)) for u in api.urls if "paginated-result" in u]
    janelas = sorted({(q["startDate"], q["endDate"]) for q in pedidos})
    assert janelas == [("2026-05-15", "2026-05-31"), ("2026-06-01", "2026-06-30"),
                       ("2026-07-01", "2026-07-03")]
    assert all(q["categoryIds"] == "c-dist" and q["type"] == "PAID"
               and q["dateField"] == "DATE_OF_PAYMENT" and q["organizationUnitId"] == "ou"
               and q["costCentreType"] == "ALL" and q["conciliationType"] == "ALL"
               for q in pedidos)


@pytest.mark.parametrize("categorias, msg", [
    ([{"id": "c-ap", "name": "Aporte Capital"}], "não existe"),
    ([{"id": "a", "name": "Distribuição de Lucros"}, {"id": "b", "name": "DISTRIBUICAO DE LUCROS"}],
     "duas vezes"),
])
def test_categoria_que_falta_ou_repete_para(categorias, msg):
    with pytest.raises(ErpError, match=msg):
        ce.pagos_de_distribuicao(Api({}, categorias), ["id-s"], ra.CATEGORIA_DISTRIBUICAO, DE, ATE)


@pytest.mark.parametrize("erro, msg", [({"__erro": 403}, "403"), ({"x": 1}, "formato")])
def test_erro_ou_formato_desconhecido_para(erro, msg):
    with pytest.raises(ErpError, match=msg):
        ce.pagos_de_distribuicao(Api({}, erro=erro), ["id-s"], ra.CATEGORIA_DISTRIBUICAO, DE, ATE)


def test_ler_recebimentos_conta_de_onde_veio_cada_item():
    from tests.test_tela_do_dia_controle_erp import Api as ApiReceb, _item as item_rec
    abre = datetime.date(2026, 10, 21)
    a = ca.Par("CONTA A - BANCO", "id-a", "CONTA A - BANCO", abre)
    b = ca.Par("CONTA A - BANCO", "id-b", "CONTA A - OUTRO", abre)
    api = ApiReceb({("id-a", "n-cap"): [item_rec("r1")], ("id-b", "n-inv"): [item_rec("r2")]})
    onde: dict = {}
    crus = ce.ler_recebimentos(api, [a, b], datetime.date(2026, 10, 23), onde=onde)
    assert onde == {"r1": "CONTA A - BANCO", "r2": "CONTA A - OUTRO"}
    assert len(crus["CONTA A - BANCO"]["Aporte de Capital"]) == 1


def test_aviso_do_fora_soma_por_cliente_maior_primeiro():
    recs = [rec(f"e{i}", datetime.date(2026, 3, 1), "1000", "OUTRA EMPRESA LTDA") for i in range(3)]
    recs += [rec("p1", datetime.date(2026, 3, 2), "5000", "EMPRESA FICTICIA"),
             rec("v1", datetime.date(2026, 3, 3), "10", "")]
    recs += [rec(f"x{i}", datetime.date(2026, 3, 4), "1", f"CLIENTE {i}") for i in range(3)]
    aviso = ra.texto_do_fora(_rel(recs))
    linhas = [l for l in aviso.splitlines() if l.startswith("  •")]
    assert linhas[0] == "  • 1 de EMPRESA FICTICIA: R$ 5.000,00"
    assert linhas[1] == "  • 3 de OUTRA EMPRESA LTDA: R$ 3.000,00"
    assert "1 de sem Cliente: R$ 10,00" in aviso
    assert linhas[-1].startswith("  • e mais 2 ")


def test_distribuicao_que_nao_entra_vai_para_o_aviso():
    pagos = [pago("p1", "2026-06-02", 100, favorecido="FULANO A. DA SILVA"),
             pago("p2", "2026-06-03", 200, categoria="Rateio de Lucros"),
             pago("p3", "2026-06-04", 300, favorecido=BETA),
             pago("p4", "2026-06-05", 400, conta="OUTRA CONTA - BANCO")]
    rel = _rel(pagos=pagos, socio=ALFA)
    assert rel.distribuicoes == []
    assert [(m.socio, m.valor) for m, _ in rel.distribuicoes_fora] == [
        ("FULANO A. DA SILVA", D("1.00")), (ALFA, D("2.00"))]     # BETA é sócio; conta alheia calada
    aviso = ra.texto_do_fora(rel)
    assert "2 pagamento(s)" in aviso and "1 de FULANO A. DA SILVA: R$ 1,00" in aviso
    assert "recebimento(s)" not in aviso


def test_data_da_distribuicao_com_fuso_e_a_de_brasilia():
    rel = _rel(pagos=[pago("p1", "2026-07-01T02:00:00Z", 100)])
    assert [m.data for m in rel.distribuicoes] == [datetime.date(2026, 6, 30)]


def test_mesmo_subpagamento_em_duas_consultas_conta_uma_vez_e_metades_somam():
    meia = lambda paid, conta: {"id": paid, "payingDate": "2026-06-02", "paidValue": 25000.0,
                                "accountName": conta}
    item_s = dict(_item("t1", "p1"), paids=[meia("p1", SICOOB)])
    item_i = dict(_item("t1", "p1"), paids=[meia("p1", SICOOB), meia("p2", INTER)])
    api = Api({("id-s", "2026-06-01"): [[item_s]], ("id-i", "2026-06-01"): [[item_i]]})
    pagos = ce.pagos_de_distribuicao(api, ["id-s", "id-i"], ra.CATEGORIA_DISTRIBUICAO,
                                     datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))
    assert sorted((p["paidId"], p["conta"]) for p in pagos) == [("p1", SICOOB), ("p2", INTER)]


def test_mesmo_subpagamento_com_valor_diferente_para():
    a = _item("t1", "p1")
    b = dict(a, paids=[dict(a["paids"][0], paidValue=1.0)])
    api = Api({("id-s", "2026-06-01"): [[a]], ("id-i", "2026-06-01"): [[b]]})
    with pytest.raises(ErpError, match="valores diferentes"):
        ce.pagos_de_distribuicao(api, ["id-s", "id-i"], ra.CATEGORIA_DISTRIBUICAO,
                                 datetime.date(2026, 6, 1), datetime.date(2026, 6, 30))
