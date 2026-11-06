"""Duas travas nascidas do caso de 05/11/2026 (dono, 06/11/2026).

1. O anexo traz UM valor em dinheiro, diferente do lançamento: a linha não
   pode sair APTA com "valor ?" (era o recibo da semana nova, R$ 8.805,24,
   num lançamento lido com R$ 10.274,04).
2. A leitura do dia lista os lançamentos e só DEPOIS lê os anexos. O que foi
   alterado no ERP nesse intervalo não pode sair APTO misturando o valor de
   antes com o arquivo de depois.

Lançamentos e textos fictícios.
"""
from datetime import date

from pagamentos_dia import leitura_do_dia as ld
from pagamentos_dia import relatorio

from test_leitura_do_dia import LEITORES, ApiFalsa, _anexo, _lanc

DIA = date(2026, 10, 21)

RECIBO_8805 = ("RECIBO DE PRESTACAO DE SERVICOS\nRecebi de EMPRESA MODELO LTDA a quantia de "
               "R$ 8.805,24 referente a servico de limpeza no periodo de 29/10/2026 a "
               "04/11/2026.\nFORNECEDOR MODELO")
NF_VARIOS = ("NOTA FISCAL\nITEM A 2 x 150,00 = 300,00\nITEM B 1 x 315,00\nTOTAL 615,00\n"
             "FORNECEDOR MODELO")


def _item(valor, **extra):
    extra.setdefault("numberOfFinancingInstallments", 1)
    return _lanc("L1", remainingValue=valor, paidTo="Fornecedor Modelo Ltda",
                 documentNumber="", **extra)


# ---------------------------------------------------------------- trava 1

def test_anexo_com_um_valor_so_e_diferente_diverge():
    resumo, divergiu = relatorio.conferir_documento(_item(10274.04), [], [RECIBO_8805])
    assert divergiu is True
    assert "VALOR DIVERGE" in resumo and "8.805,24" in resumo and "10.274,04" in resumo


def test_anexo_com_o_mesmo_valor_continua_valor_ok():
    resumo, divergiu = relatorio.conferir_documento(_item(8805.24), [], [RECIBO_8805])
    assert "valor ✓" in resumo and divergiu is False


def test_anexo_com_varios_valores_sem_o_do_lancamento_continua_interrogacao():
    # NF de itens: vários números, nenhum é o do lançamento. Não dá para dizer
    # qual seria "o" valor, e barrar aqui pararia pagamento certo.
    resumo, divergiu = relatorio.conferir_documento(_item(999.99), [], [NF_VARIOS])
    assert "valor ?" in resumo and "DIVERGE" not in resumo and divergiu is False


def test_anexo_sem_nenhum_valor_continua_interrogacao():
    resumo, divergiu = relatorio.conferir_documento(
        _item(47.60), [], ["A T E N Ç Ã O\nPAGAR PARA\nFORNECEDOR MODELO\nPIX: 000.000.000-00"])
    assert "valor ?" in resumo and divergiu is False


def test_segunda_parcela_com_o_valor_cheio_no_anexo_nao_diverge():
    # Título pago em parte: o recibo traz o total (R$ 1.000,00), o lançamento
    # traz o que falta (R$ 600,00) e R$ 400,00 já foi pago.
    item = _item(600.0, sumOfPaidValues=400.0)
    resumo, divergiu = relatorio.conferir_documento(
        item, [], ["RECIBO\nValor R$ 1.000,00\nFORNECEDOR MODELO"])
    assert divergiu is False and "DIVERGE" not in resumo


def test_titulo_parcelado_com_o_total_da_compra_no_anexo_nao_diverge():
    # NF de R$ 1.500 de uma compra em três vezes; a parcela é de R$ 500.
    resumo, divergiu = relatorio.conferir_documento(
        _item(500.0, numberOfFinancingInstallments=3), [],
        ["DANFE Nota Fiscal 64000 FORNECEDOR MODELO Total 1.500,00"])
    assert divergiu is False and "valor ?" in resumo


def test_sem_o_numero_de_parcelas_nao_se_acusa():
    item = _item(10274.04)
    del item["numberOfFinancingInstallments"]
    resumo, divergiu = relatorio.conferir_documento(item, [], [RECIBO_8805])
    assert divergiu is False and "valor ?" in resumo


def test_boleto_nao_passa_por_esta_trava():
    # No boleto quem prova o valor é o código de barras ("valor do boleto
    # diverge"); o histórico de pagamento no texto não é o valor da cobrança.
    anexo = [{"filename": "cobranca", "tagName": "Boleto"}]
    resumo, divergiu = relatorio.conferir_documento(
        _item(1000.0), anexo, ["Historico: valor pago 950,00 FORNECEDOR MODELO"])
    assert divergiu is False and "DIVERGE" not in resumo


def test_valor_da_observacao_nao_conta_como_valor_do_anexo():
    # A observação é o que o próprio lançamento diz: um valor diferente nela
    # não prova nada contra ele (mesma regra do "valor ✓", 01/10/2026).
    resumo, divergiu = relatorio.conferir_documento(
        _item(100.0), [], ["obs: combinado R$ 8.805,24", "FORNECEDOR MODELO"],
        textos_valor=["FORNECEDOR MODELO sem valor nenhum"])
    assert divergiu is False and "DIVERGE" not in resumo


# ---------------------------------------------------------------- trava 2

class ApiQueMudaNoMeio(ApiFalsa):
    """A 1ª lista é a de antes; a partir da 2ª o ERP já mudou."""

    def __init__(self, antes, depois, **k):
        super().__init__(antes, **k)
        self._depois, self.listas = depois, 0

    def listar_a_pagar(self, ini, fim, log=print):
        self.listas += 1
        return list(self._lanc if self.listas == 1 else self._depois)


def _ler(api):
    return ld.ler_pagamentos(api, DIA, DIA, abrir_historico=_sem, carregar_mapas=_sem,
                             **LEITORES)


def _sem():
    raise RuntimeError("sem nuvem nem cadastro no teste")


def _linhas(leitura):
    return {ln.id: ln for g in leitura.grupos for ln in (*g.entram, *g.nao_aptos)}


def _registros(leitura):
    return {r["id"]: r for regs in leitura.resultado.contas.values() for r in regs}


def test_lancamento_alterado_durante_a_leitura_sai_atencao():
    antes = [_lanc("L1"), _lanc("L2")]
    depois = [_lanc("L1", remainingValue=80.0, plannedDate="2026-10-21"), _lanc("L2")]
    anexos = {"T-L1": [_anexo("nota 1234")], "T-L2": [_anexo("nota 1234")]}
    api = ApiQueMudaNoMeio(antes, depois, anexos=anexos)
    leitura = _ler(api)
    assert api.listas == 2
    regs = _registros(leitura)
    assert regs["L1"]["status"] == relatorio.STATUS_ALTERADO_NA_LEITURA
    assert "alterado no ERP durante a leitura" in regs["L1"]["obs"]
    assert regs["L2"]["status"] != relatorio.STATUS_ALTERADO_NA_LEITURA   # o vizinho intocado
    assert any("alterado" in a and "L1" not in a for a in leitura.avisos)


def test_lancamento_que_some_durante_a_leitura_sai_da_apuracao_com_aviso():
    antes = [_lanc("L1"), _lanc("L2")]
    depois = [_lanc("L2")]                       # L1 mudou de data, foi excluído ou pago
    anexos = {"T-L1": [_anexo("nota 1234")], "T-L2": [_anexo("nota 1234")]}
    leitura = _ler(ApiQueMudaNoMeio(antes, depois, anexos=anexos))
    assert "L1" not in _registros(leitura) and "L1" not in _linhas(leitura)
    assert "L2" in _registros(leitura)
    assert any("saiu" in a for a in leitura.avisos)


def test_nada_mudou_nada_alarma():
    lanc = [_lanc("L1"), _lanc("L2")]
    anexos = {"T-L1": [_anexo("nota 1234")]}
    api = ApiQueMudaNoMeio(lanc, [dict(x) for x in lanc], anexos=anexos)
    leitura = _ler(api)
    assert api.listas == 2
    assert all(r["status"] != relatorio.STATUS_ALTERADO_NA_LEITURA
               for r in _registros(leitura).values())
    assert not any("alterado" in a for a in leitura.avisos)
