# tests/test_relatorio_aportes_tela.py
# -*- coding: utf-8 -*-
"""O fio do relatório na aba Controle de aportes, sem Tk e sem navegador
(dublês no padrão de `test_tela_do_dia_aporte_dos_socios._controle`)."""
import datetime
import queue
from decimal import Decimal as D
from types import SimpleNamespace

from tela_do_dia import controle_aportes as ca
from tela_do_dia import controle_erp
from tela_do_dia import controle_frame as cf
from tela_do_dia import relatorio_aportes as ra
from tela_do_dia.controle_frame import ControleAportesFrame as F

ALFA = "FULANO ALFA DA SILVA"
CONTA = ca.ContaControlada("EMPRESA FICTICIA - SICOOB", datetime.date(2026, 10, 1),
                           (ca.Aportador(ALFA, D(1), id=10),), id=1)
CONTAS_ERP = [SimpleNamespace(id="id-s", name="EMPRESA FICTICIA - SICOOB"),
              SimpleNamespace(id="id-x", name="OUTRA - BANCO")]
DE, ATE = datetime.date(2026, 1, 1), datetime.date(2026, 11, 25)


class Botao:
    def __init__(self):
        self.estado = None

    def configure(self, state=None, **_):
        self.estado = state


def _aba(**kw):
    c = SimpleNamespace(q=queue.Queue(), _lendo=False, _leu_bem=True, pode_editar=False,
                        b_nova=Botao(), b_editar=Botao(), b_apontar=Botao(), b_desfazer=Botao(),
                        b_relatorio=Botao(), lbl=Botao(), registro=[])
    c.__dict__.update(kw)
    c._botoes_do_dono = (c.b_nova, c.b_editar, c.b_apontar, c.b_desfazer)
    c._log = lambda m="": c.registro.append(m)
    c.lbl.configure = lambda text="", **_: c.registro.append(f"STATUS {text}")
    return c


def _fila(c):
    saida = []
    while not c.q.empty():
        saida.append(c.q.get())
    return saida


def test_botao_do_relatorio_so_acende_com_leitura_inteira_e_parada():
    for leu, lendo, esperado in ((True, False, "normal"), (False, False, "disabled"),
                                 (True, True, "disabled")):
        c = _aba(_leu_bem=leu, _lendo=lendo)
        F._acender_botoes(c)
        assert c.b_relatorio.estado == esperado
        assert c.b_nova.estado == "disabled"          # quem não é admin continua sem editar


def test_thread_le_o_periodo_pedido_e_manda_o_relatorio(monkeypatch):
    pedidos = {}

    def ler(api, pares, hoje, *, contraprova=None, log=print, onde=None):
        pedidos["pares"], pedidos["hoje"], pedidos["prova"] = pares, hoje, contraprova
        onde["r1"] = "EMPRESA FICTICIA - SICOOB"
        return {CONTA.conta_erp: {"Aporte de Capital": [
            {"id": "r1", "dateOfReceipt": "2026-03-10", "sumOfReceivedValues": 500.0,
             "customerName": ALFA}]}}

    def pagos(api, contas, categoria, de, ate, log=print):
        pedidos["dist"] = (contas, categoria, de, ate)
        return [{"paidId": "p1", "dataFull": "2026-06-02", "valor": 70000, "favorecido": ALFA,
                 "conta": "EMPRESA FICTICIA - SICOOB", "categoria": categoria}]

    monkeypatch.setattr(controle_erp, "ler_recebimentos", ler)
    monkeypatch.setattr(controle_erp, "pagos_de_distribuicao", pagos)
    c = _aba(anx=SimpleNamespace(garantir_sessao=lambda log: "api"))
    F._t_relatorio(c, CONTA, ra.TODOS, DE, ATE, [], CONTAS_ERP)
    fila = _fila(c)
    rel = [v for t, v in fila if t == "relatorio"][0]
    assert [p.inicio for p in pedidos["pares"]] == [DE] and pedidos["hoje"] == ATE
    assert pedidos["prova"].conta_id == "id-x"
    assert pedidos["dist"] == (["id-s"], ra.CATEGORIA_DISTRIBUICAO, DE, ATE)
    assert rel.total_aportes == D("500.00") and rel.total_distribuicoes == D("700.00")
    assert fila[-1] == ("relatorio_fim", None)


def test_thread_que_falha_diz_que_nao_gerou_e_libera_a_aba(monkeypatch):
    def cai(*a, **k):
        raise RuntimeError("Failed to fetch")
    monkeypatch.setattr(controle_erp, "ler_recebimentos", cai)
    c = _aba(anx=SimpleNamespace(garantir_sessao=lambda log: "api"))
    F._t_relatorio(c, CONTA, ra.TODOS, DE, ATE, [], CONTAS_ERP)
    fila = _fila(c)
    assert not any(t == "relatorio" for t, _ in fila)
    assert ("status", "Relatório não gerado — veja o Registro.") in fila
    assert fila[-1] == ("relatorio_fim", None) and ("botoes", "normal") in fila


def _rel(fora=()):
    return ra.Relatorio("EMPRESA FICTICIA", (ALFA,), DE, ATE,
                        aportes=[ra.Movimento(datetime.date(2026, 3, 10), "EMPRESA FICTICIA - SICOOB",
                                              ALFA, D("500.00"))],
                        fora=list(fora))


def test_salvar_grava_o_pdf_na_pasta_do_app_e_abre(monkeypatch, tmp_path):
    abertos = []
    monkeypatch.setattr(cf.util, "pasta_base", lambda: tmp_path)
    monkeypatch.setattr(cf.os, "startfile", abertos.append, raising=False)
    c = _aba()
    F._salvar_relatorio(c, _rel())
    pdf = tmp_path / cf.PASTA_RELATORIOS / ra.nome_do_arquivo(_rel())
    assert pdf.is_file() and abertos == [pdf]
    assert "STATUS Relatório gerado." in c.registro


def test_com_aporte_fora_pergunta_e_o_nao_nao_grava(monkeypatch, tmp_path):
    perguntas = []
    monkeypatch.setattr(cf.util, "pasta_base", lambda: tmp_path)
    monkeypatch.setattr(cf.messagebox, "askyesno",
                        lambda titulo, texto, parent=None: perguntas.append(texto) or False)
    fora = [(ca.Recebimento("r9", datetime.date(2026, 4, 1), D("250.00"), "OUTRA EMPRESA LTDA"),
             "o Cliente não é aportador")]
    c = _aba()
    F._salvar_relatorio(c, _rel(fora))
    assert "1 de OUTRA EMPRESA LTDA: R$ 250,00" in perguntas[0]
    assert not (tmp_path / cf.PASTA_RELATORIOS).exists()
    assert "STATUS Relatório não gerado." in c.registro
    assert any("Fora do relatório: 01/04/2026" in l for l in c.registro)
