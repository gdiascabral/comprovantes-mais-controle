# -*- coding: utf-8 -*-
"""O robô contra dublês: o Sicoob, o ERP e o livro são de mentira, e cada teste
diz o que o banco responde. Nenhuma rede."""
from datetime import date
from decimal import Decimal

import pytest

from pagamento_api import executor as ex
from pagamento_api import lote as lt
from pagamento_api.sicoob import ContaApi, ErroSicoob

CONTA = "OBRA X - SICOOB"
DOC = "11222333000181"
BARRAS = "34191153400001150501570000249243752417701000"   # 44 dígitos, do BANCARIO dos testes do lote


def _item(ordem, tipo, valor="100.00", doc=DOC, dados=None):
    dados = dados or {lt.PIX_CHAVE: "a@b.com", lt.PIX_QR: "000201...6304ABCD",
                      lt.BOLETO: BARRAS, lt.CONVENIO: "8" + "1" * 43}[tipo]
    return lt.ItemLote(ordem, f"T{ordem}", f"T{ordem}", CONTA, tipo, dados, Decimal(valor),
                       "FORNECEDOR A", doc, f"OBRA X NF {ordem}")


class Livro:
    def __init__(self):
        self.lista = []

    def eventos(self):
        return list(self.lista)

    def gravar(self, e):
        self.lista.append(e)


class Erp:
    def __init__(self, titulos):
        self.t = dict(titulos)
        self.anexos, self.baixas = [], []

    def titulo(self, tid):
        return self.t.get(tid)

    def anexar(self, tid, caminho):
        self.anexos.append((tid, caminho))
        return True

    def baixar(self, tid, valor, dia, conta):
        self.baixas.append((tid, valor))
        v = self.t[tid]
        self.t[tid] = ex.Titulo(False, v.valor, True)
        return True


class Sicoob:
    def __init__(self, **resp):
        self.resp = resp
        self.chamadas = []

    def _r(self, nome, *a):
        self.chamadas.append(nome)
        r = self.resp.get(nome)
        if isinstance(r, Exception):
            raise r
        return r(*a) if callable(r) else (r if r is not None else {})

    def pix_iniciar(self, chave):
        return self._r("pix_iniciar", chave)

    def pix_confirmar(self, e2e, valor, descricao):
        return self._r("pix_confirmar", e2e, valor, descricao)

    def pix_qrcode(self, qr, valor, doc):
        return self._r("pix_qrcode", qr, valor, doc)

    def pix_consultar(self, e2e):
        return self._r("pix_consultar", e2e)

    def boleto_consultar(self, codigo, conta):
        return self._r("boleto_consultar", codigo, conta)

    def boleto_pagar(self, *a):
        return self._r("boleto_pagar", *a)

    def boleto_comprovante(self, chave):
        return self._r("boleto_comprovante", chave)

    def convenio_consultar(self, codigo, dia):
        return self._r("convenio_consultar", codigo, dia)

    def convenio_pagar(self, *a):
        return self._r("convenio_pagar", *a)


def _aberto(valor="100.00"):
    return ex.Titulo(True, Decimal(valor), False)


def _rodar(itens, total, sicoob, erp, tmp_path, livro=None, parar=lambda: False):
    livro = livro or Livro()
    portas = ex.Portas(sicoob, erp, livro, {CONTA: ContaApi(4342, 1234569, 1)},
                       tmp_path, date(2026, 11, 27), parar, lambda: "uuid-fixo")
    ex.Executor(itens, Decimal(total), portas).rodar()
    return livro


def _estados(livro, ordem):
    return [e.estado for e in livro.lista if e.ordem == ordem]


PIX_OK = dict(pix_iniciar={"endToEndId": "E1", "proprietario": {"identificador": DOC}},
              pix_confirmar={"estado": "REALIZADO"},
              pix_consultar={"estado": "REALIZADO", "valor": 100.0})


def test_pix_por_chave_paga_anexa_e_conclui(tmp_path):
    erp = Erp({"T1": _aberto()})
    s = Sicoob(**PIX_OK)
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, erp, tmp_path)
    assert _estados(livro, 1) == [ex.INICIADO, ex.REALIZADO, ex.CONCLUIDO]
    assert erp.baixas == [("T1", Decimal("100.00"))]
    assert erp.anexos[0][1].read_bytes().startswith(b"%PDF-1.4")


def test_chave_de_outra_pessoa_nao_confirma(tmp_path):
    s = Sicoob(pix_iniciar={"endToEndId": "E1", "proprietario": {"identificador": "99999999999"}})
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert _estados(livro, 1) == [ex.NAO_PAGO]
    assert livro.lista[-1].detalhe == "chave de outra pessoa"
    assert "pix_confirmar" not in s.chamadas


@pytest.mark.parametrize("titulo,motivo", [
    (None, "ERP não confirmou o título"),
    (ex.Titulo(True, Decimal("100.00"), None), "ERP não confirmou o título"),
    (ex.Titulo(False, Decimal("100.00"), False), "ERP mudou"),
    (ex.Titulo(True, Decimal("100.00"), True), "ERP mudou"),
    (ex.Titulo(True, Decimal("100.01"), False), "ERP mudou"),
])
def test_erp_mudou_nao_paga(tmp_path, titulo, motivo):
    s = Sicoob(**PIX_OK)
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, Erp({"T1": titulo} if titulo else {}), tmp_path)
    assert livro.lista == [ex.Evento(1, ex.NAO_PAGO, motivo)]
    assert s.chamadas == []


def test_nunca_passa_do_total_aprovado(tmp_path):
    erp = Erp({"T1": _aberto(), "T2": _aberto()})
    livro = _rodar([_item(1, lt.PIX_CHAVE), _item(2, lt.PIX_CHAVE)], "150.00",
                   Sicoob(**PIX_OK), erp, tmp_path)
    assert _estados(livro, 1)[-1] == ex.CONCLUIDO
    assert livro.lista[-1] == ex.Evento(2, ex.NAO_PAGO, "passaria do total aprovado")


def test_queda_no_confirmar_retoma_pela_consulta_e_nao_paga_de_novo(tmp_path):
    erp = Erp({"T1": _aberto()})
    s = Sicoob(pix_iniciar=PIX_OK["pix_iniciar"], pix_confirmar=ErroSicoob(None, "timeout"),
               pix_consultar={"estado": "REALIZADO"})
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, erp, tmp_path)
    assert s.chamadas.count("pix_confirmar") == 1
    assert _estados(livro, 1) == [ex.INICIADO, ex.REALIZADO, ex.CONCLUIDO]


def test_erro_500_no_confirmar_tambem_e_ambiguo(tmp_path):
    s = Sicoob(pix_iniciar=PIX_OK["pix_iniciar"], pix_confirmar=ErroSicoob(500, "erro"),
               pix_consultar={"estado": "NAO_REALIZADO"})
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert _estados(livro, 1) == [ex.INICIADO, ex.NAO_PAGO]
    assert "não realizado" in livro.lista[-1].detalhe


def test_retomada_de_rodada_anterior_nao_chama_o_pagamento(tmp_path):
    livro = Livro()
    livro.gravar(ex.Evento(1, ex.INICIADO, "", "E1"))
    s = Sicoob(pix_consultar={"estado": "EM_PROCESSAMENTO"})
    _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, Erp({"T1": _aberto()}), tmp_path, livro)
    assert s.chamadas == ["pix_consultar"]
    assert _estados(livro, 1)[-1] == ex.EM_PROCESSAMENTO


def test_em_processamento_nao_anexa(tmp_path):
    erp = Erp({"T1": _aberto()})
    s = Sicoob(pix_iniciar=PIX_OK["pix_iniciar"], pix_confirmar={"estado": "EM_PROCESSAMENTO"})
    _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, erp, tmp_path)
    assert erp.anexos == [] and erp.baixas == []


def test_pix_com_estado_acentuado_do_sandbox_e_nao_pago(tmp_path):
    s = Sicoob(pix_iniciar=PIX_OK["pix_iniciar"], pix_confirmar={"estado": "NÃO_REALIZADO"})
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert _estados(livro, 1)[-1] == ex.NAO_PAGO


@pytest.mark.parametrize("resposta", [{}, {"estado": "AGENDADO"}, {"estado": None}])
def test_estado_desconhecido_do_pix_nao_vira_nao_pago(resposta):
    assert ex.estado_pix(resposta) == ex.EM_PROCESSAMENTO


def test_boleto_grava_a_chave_antes_de_pagar_e_busca_o_comprovante_por_ela(tmp_path):
    vistos = []

    def pagar(codigo, conta, consulta, valor, descricao, chave, dia):
        vistos.append([e.estado for e in livro.lista])
        return {}

    livro = Livro()
    s = Sicoob(boleto_consultar={"valorPagamento": 100.0, "numeroCpfCnpjBeneficiario": DOC,
                                 "identificadorConsulta": "h"},
               boleto_pagar=pagar,
               boleto_comprovante={"situacaoPagamento": "EFETIVADO"})
    erp = Erp({"T1": _aberto()})
    _rodar([_item(1, lt.BOLETO)], "100.00", s, erp, tmp_path, livro)
    assert vistos == [[ex.INICIADO]]
    assert livro.lista[0].chave == "4342-1234569-uuid-fixo"
    assert _estados(livro, 1) == [ex.INICIADO, ex.REALIZADO, ex.CONCLUIDO]


@pytest.mark.parametrize("consulta,motivo", [
    ({"valorPagamento": 105.3, "numeroCpfCnpjBeneficiario": DOC}, "boleto diferente: banco cobra 105.30"),
    ({"valorPagamento": 100.0, "numeroCpfCnpjBeneficiario": "99999999000199"},
     "boleto diferente: beneficiário não é o esperado"),
    ({"bloquearPagamento": True, "mensagemBloqueioPagamento": "vencido"}, "banco bloqueia: vencido"),
])
def test_boleto_diferente_nao_paga(tmp_path, consulta, motivo):
    s = Sicoob(boleto_consultar=consulta)
    livro = _rodar([_item(1, lt.BOLETO)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert livro.lista == [ex.Evento(1, ex.NAO_PAGO, motivo)]
    assert "boleto_pagar" not in s.chamadas


def test_boleto_beneficiario_final_tambem_vale(tmp_path):
    s = Sicoob(boleto_consultar={"valorPagamento": 100.0, "numeroCpfCnpjBeneficiario": "1",
                                 "numeroCpfCnpjBeneficiarioFinal": DOC},
               boleto_comprovante={"situacaoPagamento": "EFETIVADO"})
    livro = _rodar([_item(1, lt.BOLETO)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert _estados(livro, 1)[-1] == ex.CONCLUIDO


def test_convenio_guarda_o_comprovante_da_resposta(tmp_path):
    s = Sicoob(convenio_consultar={"valorTotal": 100.0},
               convenio_pagar={"comprovante": "QUJD", "arrecadacao": {"nsu": 1833, "valorPago": 100.0}})
    erp = Erp({"T1": _aberto()})
    livro = _rodar([_item(1, lt.CONVENIO)], "100.00", s, erp, tmp_path)
    assert _estados(livro, 1) == [ex.INICIADO, ex.REALIZADO, ex.CONCLUIDO]
    assert livro.lista[1].chave == "1833"


def test_falha_no_anexo_fica_falta_anexar_e_repete_so_o_anexo(tmp_path):
    erp = Erp({"T1": _aberto()})
    erp.anexar = lambda tid, c: False
    s = Sicoob(**PIX_OK)
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, erp, tmp_path)
    assert _estados(livro, 1)[-1] == ex.FALTA_ANEXAR
    erp2 = Erp({"T1": _aberto()})
    _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, erp2, tmp_path, livro)
    assert s.chamadas.count("pix_confirmar") == 1
    assert _estados(livro, 1)[-1] == ex.CONCLUIDO


def test_parar_interrompe_antes_do_proximo_item(tmp_path):
    vezes = iter([False, True])
    erp = Erp({"T1": _aberto(), "T2": _aberto()})
    livro = _rodar([_item(1, lt.PIX_CHAVE), _item(2, lt.PIX_CHAVE)], "200.00",
                   Sicoob(**PIX_OK), erp, tmp_path, parar=lambda: next(vezes))
    assert _estados(livro, 2) == []


def test_conta_sem_cadastro_da_api_nao_paga(tmp_path):
    item = lt.ItemLote(1, "T1", "T1", "OUTRA - SICOOB", lt.PIX_CHAVE, "a@b.com",
                       Decimal("100.00"), "F", DOC, "D")
    livro = _rodar([item], "100.00", Sicoob(**PIX_OK), Erp({"T1": _aberto()}), tmp_path)
    assert livro.lista == [ex.Evento(1, ex.NAO_PAGO, "conta sem cadastro da API no servidor")]


def test_convenio_com_valor_diferente_nao_paga(tmp_path):
    s = Sicoob(convenio_consultar={"valorTotal": 117.5})
    livro = _rodar([_item(1, lt.CONVENIO)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert livro.lista == [ex.Evento(1, ex.NAO_PAGO, "convênio diferente: banco cobra 117.50")]
    assert "convenio_pagar" not in s.chamadas


# ---------------------------------------------------------------------------
# Revisão da Task 5 (26/11/2026): depois de INICIADO, só o banco dizendo
# "não realizado" vira NAO_PAGO; o resto fica EM_PROCESSAMENTO (conta no total).

def test_consulta_da_retomada_que_falha_nao_vira_nao_pago(tmp_path):
    s = Sicoob(pix_iniciar=PIX_OK["pix_iniciar"], pix_confirmar=ErroSicoob(None, "timeout"),
               pix_consultar=ErroSicoob(503, "fora"))
    livro = _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert _estados(livro, 1) == [ex.INICIADO, ex.EM_PROCESSAMENTO]
    assert ex.CONFERIR in livro.lista[-1].detalhe


@pytest.mark.parametrize("resposta", [ErroSicoob(None, "timeout"), ErroSicoob(200, "Pix por QR sem estado")])
def test_pix_qr_que_cai_fica_em_processamento_e_conta_no_total(tmp_path, resposta):
    erp = Erp({"T1": _aberto(), "T2": _aberto()})
    s = Sicoob(pix_qrcode=resposta, **PIX_OK)
    livro = _rodar([_item(1, lt.PIX_QR), _item(2, lt.PIX_CHAVE)], "100.00", s, erp, tmp_path)
    assert _estados(livro, 1)[-1] == ex.EM_PROCESSAMENTO
    assert livro.lista[-1] == ex.Evento(2, ex.NAO_PAGO, "passaria do total aprovado")
    assert "pix_iniciar" not in s.chamadas


def test_pix_qr_em_processamento_e_consultado_na_rodada_seguinte(tmp_path):
    erp = Erp({"T1": _aberto()})
    s = Sicoob(pix_qrcode={"estado": "EM_PROCESSAMENTO", "endToEndId": "Q1"},
               pix_consultar={"estado": "REALIZADO"})
    livro = _rodar([_item(1, lt.PIX_QR)], "100.00", s, erp, tmp_path)
    assert _estados(livro, 1)[-1] == ex.EM_PROCESSAMENTO
    _rodar([_item(1, lt.PIX_QR)], "100.00", s, erp, tmp_path, livro)
    assert _estados(livro, 1)[-1] == ex.CONCLUIDO
    assert s.chamadas.count("pix_qrcode") == 1


def test_pix_qr_que_o_banco_recusa_com_codigo_e_nao_pago(tmp_path):
    s = Sicoob(pix_qrcode={"estado": "NAO_REALIZADO", "endToEndId": "Q1", "detalheRejeicao": "x"})
    livro = _rodar([_item(1, lt.PIX_QR)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert _estados(livro, 1)[-1] == ex.NAO_PAGO


def test_convenio_que_cai_fica_em_processamento(tmp_path):
    s = Sicoob(convenio_consultar={"valorTotal": 100.0}, convenio_pagar=ErroSicoob(None, "timeout"))
    livro = _rodar([_item(1, lt.CONVENIO)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert _estados(livro, 1) == [ex.INICIADO, ex.EM_PROCESSAMENTO]


def test_convenio_pago_com_disco_falhando_nao_vira_nao_pago(tmp_path, monkeypatch):
    def quebra(*a, **k):
        raise OSError("disco cheio")
    monkeypatch.setattr(ex.cp, "salvar_bruto", quebra)
    s = Sicoob(convenio_consultar={"valorTotal": 100.0},
               convenio_pagar={"comprovante": "QUJD", "arrecadacao": {"nsu": 9}})
    livro = _rodar([_item(1, lt.CONVENIO)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert ex.NAO_PAGO not in _estados(livro, 1)
    assert livro.lista[1].estado == ex.REALIZADO and "não gravado" in livro.lista[1].detalhe
    assert _estados(livro, 1)[-1] == ex.FALTA_ANEXAR


@pytest.mark.parametrize("situacao", ["REJEITADO", "PENDENTE", "AGENDADO", None])
def test_boleto_sem_comprovante_efetivado_nao_anexa_nem_baixa(tmp_path, situacao):
    s = Sicoob(boleto_consultar={"valorPagamento": 100.0, "numeroCpfCnpjBeneficiario": DOC},
               boleto_comprovante={"situacaoPagamento": situacao} if situacao else {})
    erp = Erp({"T1": _aberto()})
    livro = _rodar([_item(1, lt.BOLETO)], "100.00", s, erp, tmp_path)
    assert _estados(livro, 1) == [ex.INICIADO, ex.EM_PROCESSAMENTO]
    assert erp.anexos == [] and erp.baixas == []


def test_falta_anexar_com_baixa_ja_feita_no_erp_conclui_sem_baixar_de_novo(tmp_path):
    erp = Erp({"T1": _aberto()})
    livro = Livro()
    livro.gravar(ex.Evento(1, ex.INICIADO, "", "E1"))
    livro.gravar(ex.Evento(1, ex.FALTA_ANEXAR, "ERP recusou a baixa", "E1"))
    erp.t["T1"] = ex.Titulo(False, Decimal("100.00"), True)
    _rodar([_item(1, lt.PIX_CHAVE)], "100.00", Sicoob(**PIX_OK), erp, tmp_path, livro)
    assert _estados(livro, 1)[-1] == ex.CONCLUIDO and erp.baixas == [] and erp.anexos == []


def test_comprovante_ja_anexado_so_baixa(tmp_path):
    erp = Erp({"T1": ex.Titulo(True, Decimal("100.00"), True)})
    livro = Livro()
    livro.gravar(ex.Evento(1, ex.INICIADO, "", "E1"))
    livro.gravar(ex.Evento(1, ex.FALTA_ANEXAR, "ERP recusou a baixa", "E1"))
    _rodar([_item(1, lt.PIX_CHAVE)], "100.00", Sicoob(**PIX_OK), erp, tmp_path, livro)
    assert erp.anexos == [] and erp.baixas == [("T1", Decimal("100.00"))]
    assert _estados(livro, 1)[-1] == ex.CONCLUIDO


def test_em_processamento_sem_novidade_nao_enche_o_livro(tmp_path):
    erp = Erp({"T1": _aberto()})
    s = Sicoob(pix_qrcode=ErroSicoob(None, "timeout"))
    livro = _rodar([_item(1, lt.PIX_QR)], "100.00", s, erp, tmp_path)
    n = len(livro.lista)
    for _ in range(3):
        _rodar([_item(1, lt.PIX_QR)], "100.00", s, erp, tmp_path, livro)
    assert len(livro.lista) == n


def test_erp_que_levanta_antes_de_pagar_nao_derruba_o_lote(tmp_path):
    erp = Erp({"T2": _aberto()})
    erp.titulo = lambda tid: (_ for _ in ()).throw(RuntimeError("caiu")) if tid == "T1" else erp.t.get(tid)
    livro = _rodar([_item(1, lt.PIX_CHAVE), _item(2, lt.PIX_CHAVE)], "200.00",
                   Sicoob(**PIX_OK), erp, tmp_path)
    assert _estados(livro, 1) == [ex.NAO_PAGO] and _estados(livro, 2)[-1] == ex.CONCLUIDO


def test_banco_sem_documento_do_dono_da_chave_nao_confirma(tmp_path):
    s = Sicoob(pix_iniciar={"endToEndId": "E1", "proprietario": {}})
    livro = _rodar([_item(1, lt.PIX_CHAVE, doc="")], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert livro.lista[-1].detalhe == "chave de outra pessoa" and "pix_confirmar" not in s.chamadas


# Re-revisão da Task 5 (rodada 2): anexo/baixa só com o ERP respondendo.

def test_erp_que_nao_responde_no_anexo_nao_anexa_nem_baixa(tmp_path):
    erp = Erp({"T1": ex.Titulo(False, Decimal("100.00"), None)})
    livro = Livro()
    livro.gravar(ex.Evento(1, ex.INICIADO, "", "E1"))
    livro.gravar(ex.Evento(1, ex.FALTA_ANEXAR, "ERP não confirmou anexo e baixa", "E1"))
    for _ in range(3):
        _rodar([_item(1, lt.PIX_CHAVE)], "100.00", Sicoob(**PIX_OK), erp, tmp_path, livro)
    assert erp.anexos == [] and erp.baixas == []
    assert livro.lista[-1] == ex.Evento(1, ex.FALTA_ANEXAR, "ERP não respondeu", "E1")


def test_titulo_baixado_a_mao_so_recebe_o_anexo(tmp_path):
    erp = Erp({"T1": ex.Titulo(False, Decimal("100.00"), False)})
    livro = Livro()
    livro.gravar(ex.Evento(1, ex.INICIADO, "", "E1"))
    livro.gravar(ex.Evento(1, ex.REALIZADO, "", "E1"))
    erp.anexar = lambda tid, c: (erp.anexos.append((tid, c)),
                                 erp.t.__setitem__(tid, ex.Titulo(False, Decimal("100.00"), True)))[0] is None
    _rodar([_item(1, lt.PIX_CHAVE)], "100.00", Sicoob(**PIX_OK), erp, tmp_path, livro)
    assert len(erp.anexos) == 1 and erp.baixas == []
    assert _estados(livro, 1)[-1] == ex.CONCLUIDO


def test_convenio_sem_nsu_nao_vira_pago_sozinho(tmp_path):
    s = Sicoob(convenio_consultar={"valorTotal": 100.0}, convenio_pagar={"comprovante": "QUJD"})
    erp = Erp({"T1": _aberto()})
    livro = _rodar([_item(1, lt.CONVENIO)], "100.00", s, erp, tmp_path)
    for _ in range(2):
        _rodar([_item(1, lt.CONVENIO)], "100.00", s, erp, tmp_path, livro)
    assert _estados(livro, 1)[-1] == ex.EM_PROCESSAMENTO and erp.baixas == []


def test_erp_fora_no_anexo_nao_derruba_o_lote(tmp_path):
    erp = Erp({"T2": _aberto()})
    original = erp.titulo
    erp.titulo = lambda tid: (_ for _ in ()).throw(ConnectionError("ERP fora")) if tid == "T1" else original(tid)
    livro = Livro()
    livro.gravar(ex.Evento(1, ex.INICIADO, "", "E1"))
    livro.gravar(ex.Evento(1, ex.REALIZADO, "", "E1"))
    _rodar([_item(1, lt.PIX_CHAVE), _item(2, lt.PIX_CHAVE)], "200.00", Sicoob(**PIX_OK), erp, tmp_path, livro)
    ult1 = [e for e in livro.lista if e.ordem == 1][-1]
    assert ult1.estado == ex.FALTA_ANEXAR and "ERP fora" in ult1.detalhe
    assert _estados(livro, 2)[-1] == ex.CONCLUIDO


def test_motivo_do_erro_ao_pagar_fica_gravado(tmp_path):
    s = Sicoob(pix_qrcode=ErroSicoob(400, "QR expirado"))
    livro = _rodar([_item(1, lt.PIX_QR)], "100.00", s, Erp({"T1": _aberto()}), tmp_path)
    assert "QR expirado" in livro.lista[-1].detalhe and ex.CONFERIR in livro.lista[-1].detalhe


def test_comprovante_de_boleto_em_lista_e_lido(tmp_path):
    assert ex.estado_boleto([{"situacaoPagamento": "EFETIVADO"}]) == ex.REALIZADO
    assert ex.estado_boleto(["x"]) == ex.EM_PROCESSAMENTO
