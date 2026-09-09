# -*- coding: utf-8 -*-
"""A lista de pagamentos pela API, sem rede e sem navegador.

O que se prova aqui, com parcelas ENLATADAS (nomes e valores ficticios — o
repositorio e publico):

  - o mapeamento coluna da grade -> campo da API (`converter`);
  - o dinheiro sai de `remainingValue`, nunca de `value` (que vem NULL);
  - o status e derivado de `paid` + data, e `rules.py` o aceita;
  - a deduplicacao e pelo `id` da parcela, e texto igual nao deduplica;
  - a particao em janelas de 15 dias e a paginacao por `hasNextPage`;
  - o filtro "em aberto" e o agregado que substitui o rodape;
  - o `SessaoApi.pedir` manda o `accessToken` para o legado;
  - `collect.coletar` obedece a chave e nao abre navegador;
  - o `comparar-coleta` com dois coletores falsos.
"""
from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from erp import hosts
from erp import sessao as erp_sessao

from conciliacao import cli
from conciliacao.config import load_config
from conciliacao.erp import api, collect, payments_api
from conciliacao.errors import ErpError, SessaoExpirada
from conciliacao.models import ErpAccount, ErpPayment, Periodo, Snapshot
from conciliacao.rules import conta_como_a_pagar

HOJE = date(2026, 7, 30)
PERIODO = Periodo(inicio=date(2026, 7, 27), fim=date(2026, 7, 30))


def _parcela(**campos) -> dict:
    """Uma parcela como a lista devolve, com os campos que o painel le."""
    base = {
        "id": "parc-1",
        "tradePayableId": "tit-1",
        "plannedDate": "2026-07-30",
        "dueDate": "2026-07-30",
        "paid": False,
        "value": None,                       # vem NULL na lista, medido
        "remainingValue": 1234.56,
        "sumOfPaidValues": 0.0,
        "paids": [],
        "paidTo": "Fornecedor A",
        "description": "Material da obra",
        "category": {"name": "Materiais"},
        "documentNumber": "NF 100",
        "tradePayableAccount": {"id": "cta-1", "name": "CONTA 1 - BANCO X"},
        "costCentreDetails": [{"workName": "Obra 1"}, {"workName": "Obra 1"}],
        "worksNames": ["Obra 1"],
        "hasAnyFile": True,
        "tradePayablePaymentMethod": "Boleto",
        # O texto livre da conta do favorecido NAO pode ir para o snapshot.
        "paidToBankAccount": "PIX CNPJ 00.000.000/0000-00",
    }
    base.update(campos)
    return base


def _resposta(itens, *, proxima=False) -> dict:
    return {"content": itens, "hasNextPage": proxima,
            "numberOfElements": len(itens), "pageNumber": 0}


class _SessaoFalsa:
    """Responde a `pedir(url)` pelo par (startDate, page) e guarda as URLs."""

    def __init__(self, paginas: dict, base_legado=None):
        self.paginas = paginas
        self.urls = []
        if base_legado:
            self.base_legado = base_legado

    def pedir(self, url):
        self.urls.append(url)
        consulta = parse_qs(urlsplit(url).query)
        chave = (consulta["startDate"][0], int(consulta["page"][0]))
        return self.paginas.get(chave, _resposta([]))


def _silencio(*_a, **_k):
    pass


# ---------------------------------------------------------------- mapeamento
def test_mapeia_cada_coluna_da_grade_para_o_campo_da_api():
    p = payments_api.converter(_parcela(), hoje=HOJE)

    assert p.due_date == date(2026, 7, 30)            # Vencimento <- plannedDate
    assert p.status == "Em aberto"                    # Status <- paid + data
    assert p.amount == Decimal("1234.56")             # Valor <- remainingValue
    assert p.payee == "Fornecedor A"                  # Favorecido <- paidTo
    assert p.account_label == "CONTA 1 - BANCO X"     # Conta <- tradePayableAccount
    assert p.raw["description"] == "Material da obra"
    assert p.raw["category"] == "Materiais"           # dict com name
    assert p.raw["documentNumber"] == "NF 100"
    assert p.raw["costCentre"] == "Obra 1"            # rateio nao repete
    assert p.raw["hasAnyFile"] is True
    assert p.raw["paid"] is False
    assert p.raw["id"] == "parc-1"
    assert p.raw["fonte"] == "api"


def test_o_raw_nao_carrega_a_conta_do_favorecido():
    """O snapshot e arquivo comum no disco e a chave Pix pode ser CPF."""
    p = payments_api.converter(_parcela(), hoje=HOJE)
    assert "paidToBankAccount" not in p.raw
    assert "PIX" not in str(p.raw)


def test_a_conta_vem_ja_sem_o_prefixo_da_condicao():
    """A grade escreve "A Vista - CONTA"; a API entrega a conta sozinha, e o
    `mapping.resolve_label` vai receber o mesmo texto que recebia depois do
    `strip_condition_prefix`."""
    p = payments_api.converter(
        _parcela(tradePayableAccount={"name": "CONTA 2 - BANCO Y"}), hoje=HOJE)
    assert p.account_label == "CONTA 2 - BANCO Y"


def test_espaco_duplo_do_cadastro_cai_como_na_grade():
    """O cadastro do ERP tem conta com dois espacos ("LTDA  - Conta
    corrente"); a grade os colapsa ao ler a celula, e a API tem de entregar
    o mesmo rotulo, senao a comparacao ve duas contas onde ha uma (09/09/2026)."""
    from conciliacao.parsing import strip_condition_prefix

    p = payments_api.converter(
        _parcela(tradePayableAccount={"name": "CONTA 2  - BANCO Y"}), hoje=HOJE)
    assert p.account_label == "CONTA 2 - BANCO Y"
    assert p.account_label == strip_condition_prefix("À Vista CONTA 2  - BANCO Y")


def test_categoria_em_string_e_centro_de_custo_de_reserva():
    p = payments_api.converter(
        _parcela(category="Servicos", costCentreDetails=[],
                 worksNames=["Obra 2", "Obra 3"]), hoje=HOJE)
    assert p.raw["category"] == "Servicos"
    assert p.raw["costCentre"] == "Obra 2 | Obra 3"


def test_data_prevista_aceita_iso_com_hora_e_epoch():
    assert payments_api.data_prevista(
        {"plannedDate": "2026-07-29T00:00:00.000Z"}) == date(2026, 7, 29)
    # Sem plannedDate, cai para dueDate — a ordem do relatorio dos pagamentos.
    assert payments_api.data_prevista({"dueDate": "28/07/2026"}) == date(2026, 7, 28)
    assert payments_api.data_prevista({"plannedDate": None}) is None


# ------------------------------------------------------------------- dinheiro
def test_o_valor_sai_de_remainingValue_e_nunca_de_value():
    """`value` vem NULL na lista; `remainingValue` e o que falta pagar."""
    p = payments_api.converter(_parcela(value=None, remainingValue=99.9), hoje=HOJE)
    assert p.amount == Decimal("99.9")

    # Mesmo com `value` preenchido, o que vai sair da conta e o que falta.
    p = payments_api.converter(_parcela(value=500.0, remainingValue=120.0), hoje=HOJE)
    assert p.amount == Decimal("120.0")


def test_pagamento_parcial_entra_com_o_que_falta():
    """R$ 4.000,00 de um titulo de R$ 7.230,00 ja pago em R$ 3.230,00: a
    grade mostra "R$ 4.000,00 Pago: R$ 3.230,00" e o raspador pegava o
    primeiro. Aqui e o mesmo numero, sem parse."""
    p = payments_api.converter(
        _parcela(remainingValue=4000.0, sumOfPaidValues=3230.0,
                 paids=[{"id": "pg-1", "paidValue": 3230.0}]), hoje=HOJE)
    assert p.amount == Decimal("4000.0")
    assert p.raw["paids"] == 1
    assert p.status == "Em aberto"


def test_valor_ausente_vira_None_e_nao_zero():
    """None e o `invalid_amount` de `rules.py` — um alerta. Zero passaria."""
    p = payments_api.converter(_parcela(remainingValue=None), hoje=HOJE)
    assert p.amount is None


def test_o_decimal_nao_herda_lixo_binario():
    p = payments_api.converter(_parcela(remainingValue=0.1), hoje=HOJE)
    assert p.amount == Decimal("0.1")


# --------------------------------------------------------------------- status
@pytest.mark.parametrize("paid, planned, esperado", [
    (True, "2026-07-30", "Pago"),
    (True, "2026-07-01", "Pago"),
    (False, "2026-07-30", "Em aberto"),
    (False, "2026-08-02", "Em aberto"),
    (False, "2026-07-29", "Vencido"),
    (False, None, "Em aberto"),
])
def test_o_status_e_derivado_de_paid_e_da_data(paid, planned, esperado):
    p = payments_api.converter(_parcela(paid=paid, plannedDate=planned,
                                        dueDate=planned), hoje=HOJE)
    assert p.status == esperado


def test_rules_aceita_os_status_derivados_como_a_grade():
    """"Em aberto" e "Vencido" contam como a pagar; "Pago" fica de fora — e
    sao as MESMAS palavras da grade, entao `STATUS_A_PAGAR` nao muda."""
    assert conta_como_a_pagar("Em aberto")
    assert conta_como_a_pagar("Vencido")
    assert not conta_como_a_pagar("Pago")


# --------------------------------------------------------------- janelas/url
def test_periodo_curto_e_uma_janela_so():
    assert payments_api.janelas(PERIODO) == [PERIODO]


def test_periodo_longo_parte_em_janelas_de_15_dias_sem_furo_nem_sobreposicao():
    periodo = Periodo(inicio=date(2026, 7, 1), fim=date(2026, 8, 14))   # 45 dias
    partes = payments_api.janelas(periodo)
    assert [(j.inicio, j.fim) for j in partes] == [
        (date(2026, 7, 1), date(2026, 7, 15)),
        (date(2026, 7, 16), date(2026, 7, 30)),
        (date(2026, 7, 31), date(2026, 8, 14)),
    ]
    # Dezesseis dias: a ultima janela tem um dia so.
    partes = payments_api.janelas(Periodo(inicio=date(2026, 7, 1), fim=date(2026, 7, 16)))
    assert partes[-1] == Periodo(inicio=date(2026, 7, 16), fim=date(2026, 7, 16))


def test_a_url_e_a_que_a_tela_manda():
    url = payments_api.montar_url(hosts.LEGACY, PERIODO, 0)
    assert url.startswith(hosts.LEGACY + "/payable-installments/paginated-result?")
    consulta = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert consulta == {
        "page": "0", "size": "3000", "type": "ALL", "dateField": "PLANNED",
        "onlyWork": "false", "costCentreType": "ALL", "conciliationType": "ALL",
        "tradePayableType": "ALL", "batchOperationType": "NONE",
        "startDate": "2026-07-27", "endDate": "2026-07-30",
    }


def test_a_base_vem_da_sessao_ou_do_erp_hosts():
    sessao = _SessaoFalsa({}, base_legado="https://outro-legado.exemplo.test/")
    payments_api.listar_parcelas(sessao, PERIODO, log=_silencio)
    assert sessao.urls[0].startswith(
        "https://outro-legado.exemplo.test/payable-installments/")

    sessao = _SessaoFalsa({})
    payments_api.listar_parcelas(sessao, PERIODO, log=_silencio)
    assert sessao.urls[0].startswith(hosts.LEGACY)


# ------------------------------------------------------------- paginacao/dedupe
def test_hasNextPage_pede_a_pagina_seguinte_em_base_zero():
    sessao = _SessaoFalsa({
        ("2026-07-27", 0): _resposta([_parcela(id="a")], proxima=True),
        ("2026-07-27", 1): _resposta([_parcela(id="b")], proxima=True),
        ("2026-07-27", 2): _resposta([_parcela(id="c")]),
    })
    itens = payments_api.listar_parcelas(sessao, PERIODO, log=_silencio)
    assert [i["id"] for i in itens] == ["a", "b", "c"]
    paginas = [parse_qs(urlsplit(u).query)["page"][0] for u in sessao.urls]
    assert paginas == ["0", "1", "2"]


def test_cada_janela_e_pedida_e_os_ids_repetidos_entre_janelas_caem():
    periodo = Periodo(inicio=date(2026, 7, 1), fim=date(2026, 7, 20))   # 2 janelas
    sessao = _SessaoFalsa({
        ("2026-07-01", 0): _resposta([_parcela(id="x"), _parcela(id="y")]),
        ("2026-07-16", 0): _resposta([_parcela(id="y"), _parcela(id="z")]),
    })
    itens = payments_api.listar_parcelas(sessao, periodo, log=_silencio)
    assert [i["id"] for i in itens] == ["x", "y", "z"]
    inicios = [parse_qs(urlsplit(u).query)["startDate"][0] for u in sessao.urls]
    assert inicios == ["2026-07-01", "2026-07-16"]


def test_texto_identico_com_ids_diferentes_nao_deduplica():
    """Duas tarifas de R$ 0,90 no mesmo dia e conta sao dois lancamentos.
    Deduplicar por texto subtrairia dinheiro do painel sem aviso."""
    tarifa = dict(paidTo="Banco", description="Tarifa PIX", remainingValue=0.9)
    sessao = _SessaoFalsa({
        ("2026-07-27", 0): _resposta([_parcela(id="t-1", **tarifa),
                                      _parcela(id="t-2", **tarifa),
                                      _parcela(id="t-1", **tarifa)]),
    })
    pagamentos = payments_api.coletar_pagamentos_api(sessao, PERIODO, log=_silencio,
                                                     hoje=HOJE)
    assert [p.raw["id"] for p in pagamentos] == ["t-1", "t-2"]
    assert payments_api.agregado_em_aberto(pagamentos) == Decimal("1.8")


def test_hasNextPage_preso_em_true_vira_erro_e_nao_lista_pela_metade():
    sempre = _resposta([_parcela(id="a")], proxima=True)
    sessao = _SessaoFalsa({("2026-07-27", n): sempre for n in range(200)})
    with pytest.raises(ErpError, match="nao terminou"):
        payments_api.listar_parcelas(sessao, PERIODO, log=_silencio)


def test_resposta_que_nao_e_dicionario_e_contrato_mudado():
    class _Lista:
        base_legado = None

        def pedir(self, _url):
            return [1, 2, 3]

    with pytest.raises(ErpError, match="contrato"):
        payments_api.listar_parcelas(_Lista(), PERIODO, log=_silencio)


# ------------------------------------------------------- em aberto/agregado
def test_por_padrao_so_o_que_esta_em_aberto_entra_e_o_log_conta_o_resto():
    sessao = _SessaoFalsa({
        ("2026-07-27", 0): _resposta([
            _parcela(id="aberta", remainingValue=100.0),
            _parcela(id="vencida", plannedDate="2026-07-28", remainingValue=50.0),
            _parcela(id="paga", paid=True, remainingValue=0.0, sumOfPaidValues=70.0),
        ]),
    })
    linhas = []
    pagamentos = payments_api.coletar_pagamentos_api(
        sessao, PERIODO, log=linhas.append, hoje=HOJE)

    assert [p.raw["id"] for p in pagamentos] == ["aberta", "vencida"]
    assert [p.status for p in pagamentos] == ["Em aberto", "Vencido"]
    assert any("2 em aberto (1 vencida(s)), 1 ja paga(s)" in l for l in linhas)
    assert payments_api.agregado_em_aberto(pagamentos) == Decimal("150.0")


def test_com_somente_em_aberto_desligado_os_pagos_vem_com_status_pago():
    sessao = _SessaoFalsa({
        ("2026-07-27", 0): _resposta([
            _parcela(id="aberta"),
            _parcela(id="paga", paid=True, remainingValue=0.0),
        ]),
    })
    pagamentos = payments_api.coletar_pagamentos_api(
        sessao, PERIODO, log=_silencio, hoje=HOJE, somente_em_aberto=False)
    assert [(p.raw["id"], p.status) for p in pagamentos] == [
        ("aberta", "Em aberto"), ("paga", "Pago")]
    # O agregado continua somando so o que esta a pagar.
    assert payments_api.agregado_em_aberto(pagamentos) == Decimal("1234.56")


def test_agregado_ignora_valor_ilegivel_e_status_fora():
    pagamentos = [
        ErpPayment(due_date=HOJE, status="Em aberto", amount=Decimal("10")),
        ErpPayment(due_date=HOJE, status="Vencido", amount=Decimal("5")),
        ErpPayment(due_date=HOJE, status="Em aberto", amount=None),
        ErpPayment(due_date=HOJE, status="Pago", amount=Decimal("99")),
    ]
    assert payments_api.agregado_em_aberto(pagamentos) == Decimal("15")


def test_linha_fora_do_periodo_e_avisada_e_mantida():
    """`rules.py` recorta por data; a coleta so avisa que a API nao filtrou."""
    sessao = _SessaoFalsa({
        ("2026-07-27", 0): _resposta([_parcela(id="fora", plannedDate="2026-08-15",
                                               dueDate="2026-08-15")]),
    })
    linhas = []
    pagamentos = payments_api.coletar_pagamentos_api(
        sessao, PERIODO, log=linhas.append, hoje=HOJE)
    assert len(pagamentos) == 1
    assert any("fora do periodo" in l for l in linhas)


# ------------------------------------------------- o token certo para o host
class _TransporteFalso:
    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.chamadas = []

    def request(self, metodo, url, headers=None, json=None, timeout=None):
        self.chamadas.append({"metodo": metodo, "url": url, "headers": headers})
        indice = min(len(self.chamadas), len(self.respostas)) - 1
        status, corpo = self.respostas[indice]
        return _Resposta(status, corpo)


class _Resposta:
    text = ""

    def __init__(self, status_code, corpo):
        self.status_code = status_code
        self._corpo = corpo

    def json(self):
        return self._corpo


class _ConfigFalso:
    def __init__(self, **erp):
        self.erp = erp


def _sessao_logada() -> api.SessaoApi:
    corpo = {"jwtToken": "j" * 348, "accessToken": "a" * 27, "id": "user-1",
             "organizationUnitId": "unidade-2", "username": "fulano@exemplo.test",
             "companies": [{"id": "empresa-3333", "tradeName": "Empresa"}]}
    interna = erp_sessao.Sessao.de_login(corpo)
    return api.SessaoApi(token=interna.jwt_token, company_id=interna.company_id,
                         usuario="fulano@exemplo.test", empresa="Empresa",
                         config=_ConfigFalso(), _sessao=interna)


def test_a_lista_de_parcelas_vai_ao_legado_com_o_accessToken_e_os_quatro_cabecalhos(
        monkeypatch):
    """E a regra dos dois tokens, escrita uma vez em `erp.Sessao.token_para`:
    a mesma sessao que le saldos com o `jwtToken` le parcelas com o
    `accessToken`, e so o legado leva `user-id`."""
    falso = _TransporteFalso((200, _resposta([_parcela()])))
    monkeypatch.setattr(erp_sessao, "_SESSAO", falso)

    pagamentos = payments_api.coletar_pagamentos_api(
        _sessao_logada(), PERIODO, log=_silencio, hoje=HOJE)

    assert len(pagamentos) == 1
    chamada = falso.chamadas[-1]
    assert hosts.eh_legacy(chamada["url"])
    cab = chamada["headers"]
    assert cab["authorization"] == f"Bearer {'a' * 27}"
    assert cab["company-id"] == "empresa-3333"
    assert cab["user-id"] == "user-1"
    assert cab["organization-unit-id"] == "unidade-2"
    assert "Chrome/" in cab["user-agent"]


def test_sessao_montada_a_mao_nao_tem_accessToken_e_o_legado_recusa(monkeypatch):
    """Sem credencial nao ha relogin: o 401 sobe como `SessaoExpirada`, na
    lingua deste pacote."""
    monkeypatch.setattr(erp_sessao, "_SESSAO", _TransporteFalso((401, {})))
    sessao = api.SessaoApi(token="j" * 348, company_id="empresa-3333",
                           usuario="fulano@exemplo.test", empresa="Empresa",
                           config=_ConfigFalso())
    with pytest.raises(SessaoExpirada):
        payments_api.coletar_pagamentos_api(sessao, PERIODO, log=_silencio)


def test_base_legado_do_SessaoApi_segue_o_config():
    assert _sessao_logada().base_legado == hosts.LEGACY
    sessao = api.SessaoApi(token="j", company_id="c", usuario="u", empresa=None,
                           config=_ConfigFalso(legacy_api_base="https://x.test/"))
    assert sessao.base_legado == "https://x.test"


# ------------------------------------------------------------ collect.coletar
class _Config:
    """O bastante do `Config` da Conciliacao, com a chave."""

    def __init__(self, pagamentos_via_api=True):
        self.erp = {"rota_pagamentos": "#/payable-installments"}
        self.pagamentos_via_api = pagamentos_via_api

    def caminho(self, *_a):
        return Path(".")


def _snapshot(pagamentos=(), agregado=None, contas=()) -> Snapshot:
    return Snapshot(reference_date=PERIODO.fim, collected_at="",
                    accounts=list(contas), payments=list(pagamentos),
                    page_aggregate_open=agregado, periodo=PERIODO)


@pytest.fixture
def sem_navegador(monkeypatch):
    """`abrir_erp` explode: qualquer caminho que o toque falha o teste."""
    def _explode(*_a, **_k):
        raise AssertionError("abriu navegador")
    monkeypatch.setattr(collect, "abrir_erp", _explode)


def test_com_a_chave_ligada_coletar_vai_pela_api_e_nao_abre_navegador(
        monkeypatch, sem_navegador):
    chamadas = []
    monkeypatch.setattr(collect, "coletar_pela_api",
                        lambda config, *, periodo, log: (chamadas.append(periodo),
                                                         _snapshot())[1])
    snap = collect.coletar(_Config(True), periodo=PERIODO, log=_silencio)
    assert chamadas == [PERIODO]
    assert snap.periodo == PERIODO


def test_com_a_chave_desligada_coletar_vai_pela_tela(monkeypatch):
    chamadas = []
    monkeypatch.setattr(collect, "coletar_pela_tela",
                        lambda config, *, periodo, visivel, log: (
                            chamadas.append((periodo, visivel)), _snapshot())[1])
    collect.coletar(_Config(False), periodo=PERIODO, visivel=True, log=_silencio)
    assert chamadas == [(PERIODO, True)]


def test_config_sem_a_chave_vale_api():
    class _SemChave:
        erp = {}
    assert collect.usa_api(_SemChave()) is True
    assert collect.usa_api(_Config(False)) is False


def test_coletar_pela_api_faz_um_login_so_e_soma_o_agregado(monkeypatch, sem_navegador):
    """Saldos e parcelas pela MESMA sessao, e o agregado que `validate.py`
    compara e a soma da lista."""
    logins = []

    class _Sessao:
        base_legado = hosts.LEGACY

        def contas(self, *, ativas=True):
            return [ErpAccount(id="u1", name="CONTA 1 - BANCO X",
                               balance=Decimal("500"))]

        def pedir(self, url):
            return _resposta([_parcela(id="a", remainingValue=10.0),
                              _parcela(id="b", remainingValue=20.5),
                              _parcela(id="p", paid=True, remainingValue=0.0)])

    def _logar(config, log=print):
        logins.append(config)
        return _Sessao()

    monkeypatch.setattr(collect.SessaoApi, "logar", staticmethod(_logar))
    snap = collect.coletar_pela_api(_Config(), periodo=PERIODO, log=_silencio)

    assert len(logins) == 1
    assert [a.name for a in snap.accounts] == ["CONTA 1 - BANCO X"]
    assert [p.raw["id"] for p in snap.payments] == ["a", "b"]
    assert snap.page_aggregate_open == Decimal("30.5")
    assert snap.periodo == PERIODO
    assert snap.reference_date == PERIODO.fim


def test_coletar_pela_api_sem_contas_e_erro(monkeypatch, sem_navegador):
    class _Vazia:
        def contas(self, *, ativas=True):
            return []

    monkeypatch.setattr(collect.SessaoApi, "logar",
                        staticmethod(lambda config, log=print: _Vazia()))
    with pytest.raises(ErpError, match="nenhuma conta"):
        collect.coletar_pela_api(_Config(), periodo=PERIODO, log=_silencio)


def test_testar_login_com_a_chave_ligada_nao_abre_navegador(monkeypatch, sem_navegador):
    class _Sessao:
        base_legado = hosts.LEGACY

        def contas(self, *, ativas=True):
            return [ErpAccount(id="u1", name="CONTA 1")]

        def pedir(self, url):
            return _resposta([])

    monkeypatch.setattr(collect.SessaoApi, "logar",
                        staticmethod(lambda config, log=print: _Sessao()))
    assert collect.testar_login(_Config(True), log=_silencio) is True


# ------------------------------------------------------------- comparar
def _pag(conta, valor, ident, *, status="Em aberto", venc=HOJE, **raw):
    return ErpPayment(due_date=venc, status=status,
                      amount=None if valor is None else Decimal(valor),
                      payee="Fornecedor A", account_label=conta,
                      raw={"id": ident, **raw})


def test_comparar_coletas_soma_por_conta_e_aponta_a_diferenca():
    tela = _snapshot(
        [_pag("CONTA 1", "100.00", "1"), _pag("CONTA 1", "50.00", "2"),
         _pag("CONTA 2", "7.00", "3")],
        agregado=Decimal("999"))
    apis = _snapshot(
        [_pag("CONTA 1", "100.00", "1"), _pag("CONTA 1", "50.00", "2"),
         _pag("CONTA 2", "9.00", "3", plannedDate="2026-07-30", dueDate="2026-08-05"),
         _pag("CONTA 3", "1.00", "4")],
        agregado=Decimal("160"))

    c = collect.comparar_coletas(tela, apis)

    por_conta = {linha.conta: linha for linha in c.linhas}
    assert por_conta["CONTA 1"].bate
    assert (por_conta["CONTA 1"].qtd_tela, por_conta["CONTA 1"].total_api) == (2, Decimal("150.00"))
    assert por_conta["CONTA 2"].diferenca == Decimal("2.00")
    assert (por_conta["CONTA 3"].qtd_tela, por_conta["CONTA 3"].qtd_api) == (0, 1)
    assert not c.bate
    assert (c.total_tela, c.total_api, c.qtd_tela, c.qtd_api) == (
        Decimal("157.00"), Decimal("160.00"), 3, 4)
    assert (c.so_na_tela, c.so_na_api) == ([], ["4"])
    assert c.datas_divergentes == 1
    assert (c.agregado_tela, c.agregado_api) == (Decimal("999"), Decimal("160"))

    texto = c.relatorio()
    assert "CONTA 2" in texto and "<-- difere" in texto and "DIFEREM" in texto
    assert "R$ 157,00" in texto and "R$ 160,00" in texto


def test_comparar_coletas_aplica_o_recorte_de_rules_nos_dois_lados():
    """A grade vem filtrada pela tela e a API vem com type=ALL: comparar as
    listas cruas acusaria diferenca onde so ha filtro."""
    tela = _snapshot([_pag("CONTA 1", "10", "1")])
    apis = _snapshot([_pag("CONTA 1", "10", "1"),
                      _pag("CONTA 1", "99", "2", status="Pago"),
                      _pag("CONTA 1", "99", "3", venc=date(2026, 8, 20))])
    c = collect.comparar_coletas(tela, apis)
    assert c.bate
    assert "BATEM" in c.relatorio()


def test_comparar_coletas_com_valor_ilegivel_conta_e_nao_soma():
    tela = _snapshot([_pag("CONTA 1", None, "1")])
    apis = _snapshot([_pag("CONTA 1", None, "1")])
    c = collect.comparar_coletas(tela, apis)
    assert c.linhas[0].qtd_tela == 1 and c.linhas[0].total_tela == Decimal("0")


def test_comparar_coletas_titulo_pago_em_parte_soma_na_conta_cadastrada():
    """Em titulo pago em parte a grade mostra a conta do pagamento ja feito;
    a API mostra a cadastrada no titulo, e e a cadastrada que vale (dono,
    09/09/2026: em conta pessoa fisica cada parte pode sair de uma conta
    diferente). A linha da tela soma na conta da API, e o caso fica listado."""
    tela = _snapshot([_pag("CONTA PESSOAL", "4000.00", "1"),
                      _pag("CONTA 1", "10", "2")])
    apis = _snapshot([_pag("APENAS LANCAMENTO", "4000.00", "1", sumOfPaidValues=2422.0),
                      _pag("CONTA 1", "10", "2")])

    c = collect.comparar_coletas(tela, apis)

    assert c.bate
    assert {linha.conta for linha in c.linhas} == {"APENAS LANCAMENTO", "CONTA 1"}
    [parcial] = c.parciais_em_outra_conta
    assert (parcial.id, parcial.conta_tela, parcial.conta_api, parcial.valor) == (
        "1", "CONTA PESSOAL", "APENAS LANCAMENTO", Decimal("4000.00"))
    texto = c.relatorio()
    assert "pago(s) em parte" in texto and "CONTA PESSOAL" in texto and "BATEM" in texto


def test_comparar_coletas_conta_diferente_sem_parcial_continua_diferenca():
    """Sem pagamento parcial, conta diferente e diferenca de verdade."""
    tela = _snapshot([_pag("CONTA PESSOAL", "4000.00", "1")])
    apis = _snapshot([_pag("APENAS LANCAMENTO", "4000.00", "1", sumOfPaidValues=0.0)])

    c = collect.comparar_coletas(tela, apis)

    assert not c.bate and c.parciais_em_outra_conta == []
    assert "<-- difere" in c.relatorio()


def test_cmd_comparar_coleta_roda_os_dois_coletores_e_imprime(monkeypatch, capsys):
    """Tela primeiro, API depois — a ordem que a sessao unica do ERP impoe —,
    o mesmo periodo para os dois, e o relatorio na saida."""
    ordem = []
    tela = _snapshot([_pag("CONTA 1", "10", "1")])
    apis = _snapshot([_pag("CONTA 1", "10", "1")])

    def _tela(config, *, periodo, visivel, log):
        ordem.append(("tela", periodo, visivel))
        return tela

    def _api(config, *, periodo, log):
        ordem.append(("api", periodo))
        return apis

    monkeypatch.setattr(cli, "_base", lambda args: (_Config(), None))
    args = cli.build_parser().parse_args(
        ["comparar-coleta", "--de", "27/07/2026", "--ate", "30/07/2026"])

    codigo = cli.cmd_comparar_coleta(args, coletar_tela=_tela, coletar_api=_api)

    assert codigo == 0
    assert ordem == [("tela", PERIODO, True), ("api", PERIODO)]
    saida = capsys.readouterr().out
    assert "CONTA 1" in saida and "BATEM" in saida


def test_cmd_comparar_coleta_devolve_1_quando_diferem(monkeypatch, capsys):
    monkeypatch.setattr(cli, "_base", lambda args: (_Config(), None))
    args = cli.build_parser().parse_args(
        ["comparar-coleta", "--de", "27/07/2026", "--ate", "30/07/2026"])
    codigo = cli.cmd_comparar_coleta(
        args,
        coletar_tela=lambda config, **_k: _snapshot([_pag("CONTA 1", "10", "1")]),
        coletar_api=lambda config, **_k: _snapshot([_pag("CONTA 1", "11", "1")]))
    assert codigo == 1
    assert "DIFEREM" in capsys.readouterr().out


def test_a_ajuda_do_comparar_coleta_avisa_do_navegador_visivel():
    parser = cli.build_parser()
    sub = next(a for a in parser._actions if a.dest == "comando")
    descricao = sub.choices["comparar-coleta"].description
    assert "ABRE o Chrome" in descricao and "177.046,30" in descricao


# --------------------------------------------------------------- config.yaml
_YAML_MINIMO = """
planilha:
  aba: Painel
  primeira_linha: 8
  ultima_linha: 31
  linha_totais: 33
  ultima_coluna: J
  celula_data: B3
  celula_total_pagamentos: E33
  formato_data: dd/mm/yyyy
  colunas_escritas: {saldo: D, pagamento: E, qtd_sistema: I, qtd_banco: J}
  colunas_formula: [F, G, H]
"""


def test_a_chave_pagamentos_via_api_vale_true_quando_ausente(tmp_path):
    caminho = tmp_path / "config.yaml"
    caminho.write_text(_YAML_MINIMO, encoding="utf-8")
    assert load_config(caminho).pagamentos_via_api is True


def test_a_chave_pagamentos_via_api_e_lida_da_secao_erp(tmp_path):
    caminho = tmp_path / "config.yaml"
    caminho.write_text(_YAML_MINIMO + "erp:\n  pagamentos_via_api: false\n",
                       encoding="utf-8")
    cfg = load_config(caminho)
    assert cfg.pagamentos_via_api is False
    assert cfg.erp == {"pagamentos_via_api": False}
