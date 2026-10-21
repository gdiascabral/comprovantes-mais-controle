"""A Remessa recebe a leitura da tela do dia: o que não sai não vai para a
remessa. Dublê no lugar da janela; lançamentos fictícios."""
import queue
from datetime import date
from types import SimpleNamespace

from pagamentos_dia import confirmacao, leitura_do_dia
from pagamentos_dia import pagamentos_frame
from pagamentos_dia import regras_pagamento as regras
from pagamentos_dia.pagamentos_frame import PagamentosDiaFrame

DIA = date(2026, 10, 21)


def _lanc(ident):
    return {"id": ident, "tradePayableId": f"T-{ident}", "paidTo": "Fornecedor Modelo Ltda",
            "remainingValue": 100.0, "plannedDate": "2026-10-21",
            "tradePayableAccount": {"name": "CONTA EXEMPLO - SICOOB"},
            "tradePayablePaymentMethod": "Pix", "paidToBankAccount": "PIX EMAIL f@exemplo.com",
            "documentNumber": "1234", "costCentreDetails": [{"workName": "OBRA MODELO"}], "paid": False}


class _Var:
    def __init__(self):
        self.valor = ""

    def set(self, v):
        self.valor = v


def _leitura(**extra):
    anexo = lambda n: {"filename": n, "tagName": "Nota Fiscal", "extension": ".pdf",  # noqa: E731
                       "downloadUrl": f"https://exemplo.invalid/{n}.pdf"}
    entradas = confirmacao.Entradas(
        selecionados=[_lanc("L1"), _lanc("L2")], anexos={"T-L1": [anexo("n1")], "T-L2": [anexo("n2")]},
        overviews={}, textos={}, urls_ocr=set(), cadastro_reembolso=None,
        regras_fornecedor={}, participantes={}, periodo=(DIA, DIA))
    return leitura_do_dia.LeituraDosPagamentos(
        periodo=(DIA, DIA), lancamentos=entradas.selecionados, anexos=entradas.anexos,
        entradas=entradas, **extra)


def _aba(gerou):
    return SimpleNamespace(worker=None, q=queue.Queue(), v_ini=_Var(), v_fim=_Var(),
                           _log=lambda m="": None, gerar_remessa=lambda: gerou.append(True))


def test_receber_apuracao_poe_em_memoria_so_o_que_sai_e_abre_a_remessa():
    gerou = []
    aba = _aba(gerou)
    PagamentosDiaFrame.receber_apuracao(aba, _leitura(), {"L2"})
    ids = [r["id"] for regs in aba.resultado.contas.values() for r in regs]
    assert ids == ["L1"]
    assert any(o["motivo"] == regras.MOTIVO_NAO_CONFIRMADO for o in aba.resultado.omitidos)
    assert aba._periodo_do_resultado == aba._periodo_da_busca == (DIA, DIA)
    assert aba.v_ini.valor == "21/10/2026" and gerou == [True]


def test_leitura_interrompida_nao_vira_remessa(monkeypatch):
    avisos = []
    monkeypatch.setattr(pagamentos_frame.messagebox, "showinfo", lambda *a, **k: avisos.append(a))
    gerou = []
    aba = _aba(gerou)
    PagamentosDiaFrame.receber_apuracao(aba, _leitura(interrompida=True), set())
    assert gerou == [] and not hasattr(aba, "resultado")
    assert "busque de novo na aba Pagamentos do dia" in avisos[0][1]
