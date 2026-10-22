"""O link do lançamento: id, e a leitura pela sessão do Chrome do app (dublê)."""
from datetime import date
from decimal import Decimal as D

import pytest

from tela_do_dia import lancamento_do_erp as le

ITEM = {"id": "L9", "tradePayableId": "T9", "paidTo": "Fornecedor Modelo Ltda", "remainingValue": 80000.0,
        "plannedDate": "2026-09-29", "tradePayableAccount": {"name": "CONTA EXEMPLO - SICOOB"},
        "documentNumber": "1234", "description": "compra de material",
        "costCentreDetails": [{"workName": "OBRA MODELO"}], "paid": False}


def test_id_do_link_aceita_o_link_e_o_id_cru():
    assert le.id_do_link("https://acessar.maiscontroleerp.com.br/#/payable-installments/abc-123") == "abc-123"
    assert le.id_do_link("  abc-123 ") == "abc-123"
    assert le.id_do_link("https://outro.invalid/x?y=1") == ""
    assert le.id_do_link("") == ""


def test_do_item_le_as_pecas_do_lancamento():
    lido = le.do_item(ITEM, {"purchaseOrder": {"number": "55"}})
    assert (lido.favorecido, lido.centro_custo, lido.nf, lido.oc) == ("Fornecedor Modelo Ltda", "OBRA MODELO", "1234", "55")
    assert lido.em_aberto == D("80000.00") and lido.vencimento == date(2026, 9, 29)
    assert lido.conta == "CONTA EXEMPLO - SICOOB" and not lido.pago


class _Api:
    _req_pagos = ("u", {})

    def __init__(self, overview=None, lista=()):
        self.overview, self.lista, self.pedidos = overview, list(lista), []

    def listar_overviews(self, ids, log=print):
        return {ids[0]: self.overview} if self.overview else {}

    def listar_a_pagar(self, ini, fim, log=print):
        self.pedidos.append((ini, fim))
        return self.lista


def test_le_fora_do_periodo_pela_data_do_detalhe():
    api = _Api(overview={"plannedDate": "2026-09-29", "documentNumber": "1234"}, lista=[ITEM])
    lido = le.ler(api, "L9", conhecidos=[])
    assert api.pedidos == [("2026-09-29", "2026-09-29")] and lido.em_aberto == D("80000.00")
    assert lido.favorecido == "Fornecedor Modelo Ltda" and lido.centro_custo == "OBRA MODELO"


def test_conhecido_nao_pede_a_lista_do_dia():
    api = _Api(overview={"documentNumber": "1234"})
    lido = le.ler(api, "L9", conhecidos=[ITEM])
    assert api.pedidos == [] and lido.favorecido == "Fornecedor Modelo Ltda"


def test_sem_o_item_avisa_e_nao_inventa_valor():
    lido = le.ler(_Api(overview={"documentNumber": "1234"}), "L9")
    assert lido.em_aberto is None and any("confira" in a for a in lido.avisos)
    assert lido.favorecido == "" and lido.centro_custo == "" and lido.nf == "1234"


def test_so_detalhe_usa_o_pendente_e_ignora_paidto_vazio():
    # forma medida em 21/10/2026: paidTo vem {}, o valor em aberto é pendingValue
    det = {"plannedValue": 100.0, "plannedDate": "2026-09-29", "pendingValue": 40.0,
           "sumOfPaidValues": 60.0, "paid": False, "markedAsPaid": False, "paidTo": {}}
    lido = le.ler(_Api(overview=det, lista=[]), "L9")
    assert lido.em_aberto == D("40.00") and lido.favorecido == "" and not lido.pago


def test_so_detalhe_sem_pendente_calcula_pelo_previsto_menos_pago():
    det = {"plannedValue": 100.0, "sumOfPaidValues": 60.0}
    assert le.do_item({**det, "id": "L9"}, det).em_aberto == D("40.00")
    assert le.do_item({"id": "L9", "plannedValue": 100.0}, None).em_aberto is None


def test_titulo_pago_vem_marcado():
    assert le.do_item({**ITEM, "paid": True, "remainingValue": 0.0}, None).pago is True
    assert le.do_item({"id": "L9", "markedAsPaid": True}, None).pago is True


def test_lancamento_que_nao_existe_levanta():
    with pytest.raises(LookupError):
        le.ler(_Api(), "L9")
    with pytest.raises(LookupError):
        le.ler(_Api(), "")


# ------------------------------------------- aba do ERP fechada no meio (D)
class TargetClosedError(Exception):
    """Mesmo nome da exceção do Playwright (o código olha o nome, não importa
    o Playwright)."""


def _leitor(*respostas):
    chamadas = []
    fila = list(respostas)

    def ler(api, ident, conhecidos=(), *, log=print):
        chamadas.append(api)
        r = fila.pop(0)          # sem resposta sobrando: chamada a mais estoura
        if isinstance(r, Exception):
            raise r
        return r
    return ler, chamadas


def _garantir():
    abertas = []

    def garantir():
        abertas.append(len(abertas) + 1)
        return f"api{len(abertas)}"
    return garantir, abertas


def test_aba_fechada_reabre_e_le_uma_vez_de_novo():
    ler, chamadas = _leitor(TargetClosedError("Target page, context or browser has been closed"),
                            "LIDO")
    garantir, abertas = _garantir()
    log = []
    assert le.ler_pela_aba(garantir, "L9", (), log=log.append, ler=ler) == "LIDO"
    assert chamadas == ["api1", "api2"] and abertas == [1, 2]
    assert any("abrindo" in m for m in log)


def test_aba_fechada_duas_vezes_vira_recado_claro_sem_terceira_tentativa():
    erro = TargetClosedError("Target page, context or browser has been closed")
    ler, chamadas = _leitor(erro, erro, "NUNCA")
    garantir, abertas = _garantir()
    with pytest.raises(le.AbaDoErpFechada) as e:
        le.ler_pela_aba(garantir, "L9", (), log=lambda *_: None, ler=ler)
    assert len(chamadas) == 2 and abertas == [1, 2]
    assert "fechou a aba do ERP" in str(e.value) and "Ler de novo" in str(e.value)
    assert "TargetClosedError" not in str(e.value)


def test_aba_fechada_ao_abrir_a_sessao_tambem_tenta_de_novo():
    ler, chamadas = _leitor("LIDO")
    vezes = []

    def garantir():
        vezes.append(1)
        if len(vezes) == 1:
            raise TargetClosedError("Target closed")
        return "api"
    assert le.ler_pela_aba(garantir, "L9", (), log=lambda *_: None, ler=ler) == "LIDO"
    assert chamadas == ["api"] and len(vezes) == 2


def test_outro_erro_nao_tenta_de_novo():
    ler, chamadas = _leitor(LookupError("não achei o lançamento L9 no ERP"), "NUNCA")
    garantir, abertas = _garantir()
    with pytest.raises(LookupError):
        le.ler_pela_aba(garantir, "L9", (), log=lambda *_: None, ler=ler)
    assert len(chamadas) == 1 and abertas == [1]


def test_pagina_fechada_reconhece_pelo_nome_ou_pela_frase():
    assert le.pagina_fechada(TargetClosedError("x"))
    assert le.pagina_fechada(RuntimeError("Target page, context or browser has been closed"))
    assert not le.pagina_fechada(RuntimeError("timeout"))
