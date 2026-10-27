# -*- coding: utf-8 -*-
"""O saldo do Inter para a Prova de saldos. Sem Chrome: a parte de tela é
dublê; a lógica (resposta, conta aberta) é pura. Tela e números fictícios,
no formato medido ao vivo em 27/10/2026."""
from decimal import Decimal as D

import pytest

from baixar_comprovantes import inter_baixar as ib
from baixar_comprovantes import inter_saldo as m

TELA = ("Saldo\nR$ 1.234,56\n123456789\n\nEMPRESA FICTICIA LTDA\n"
        "Saldo em conta R$ 1.234,56")


def test_saldo_e_o_disponivel_em_decimal():
    dado = {"disponivel": 1234.56, "chequeEspecialDisponivel": 0.0,
            "disponivelComChequeEspecial": 1234.56}
    assert m.saldo_da_resposta(200, dado) == D("1234.56")
    assert m.saldo_da_resposta(200, {"disponivel": -12.3}) == D("-12.30")
    assert m.saldo_da_resposta(200, {"disponivel": 0}) == D("0.00")


@pytest.mark.parametrize("dado", [{}, {"disponivel": None}, {"disponivel": True},
                                  {"disponivel": "1.234,56"}, [], None])
def test_resposta_sem_disponivel_valido_nao_vira_saldo(dado):
    with pytest.raises(m.SaldoInterFalhou):
        m.saldo_da_resposta(200, dado)


def test_sessao_vencida_e_erro_do_banco():
    with pytest.raises(m.SaldoInterFalhou, match="sessão"):
        m.saldo_da_resposta(401, {"disponivel": 1})
    with pytest.raises(m.SaldoInterFalhou, match="HTTP 500"):
        m.saldo_da_resposta(500, None)


def test_numero_no_texto_da_tela_medida():
    assert ib.numero_no_texto(TELA) == "123456789"
    assert ib.numero_no_texto("R$ 1.234,56\n01/10/2026") == ""
    assert ib.numero_no_texto("") == ""


def test_conta_da_pagina_usa_a_mesma_leitura():
    pagina = type("P", (), {"evaluate": lambda self, js: TELA})()
    assert ib.conta_da_pagina(pagina) == "123456789"


def test_conferir_a_conta_certa():
    assert m.conferir_conta(TELA, "12345678-9", ("Empresa Fictícia",)) == ""
    assert m.conferir_conta(TELA, "0123456789", ("EMPRESA FICTICIA",)) == ""


def test_outra_conta_aberta_nao_le():
    motivo = m.conferir_conta(TELA, "987654321", ("EMPRESA FICTICIA",))
    assert "outra conta aberta" in motivo and "987654321" in motivo


def test_nome_de_outra_empresa_nao_le():
    motivo = m.conferir_conta(TELA, "123456789", ("OUTRA EMPRESA",))
    assert "nome da empresa" in motivo and "outra conta aberta" in motivo


def test_sem_numero_na_tela_nao_le():
    assert m.conferir_conta("Saldo\nR$ 1,00", "123456789", ("X",)) == m.SEM_NUMERO


def test_sem_numero_esperado_o_nome_curto_nao_basta():
    """Revisão de dinheiro (27/10): sem o número no ERP, "EMPRESA FICTICIA"
    também está dentro de "EMPRESA FICTICIA 2 LTDA" — o nome curto não prova
    de quem é a conta aberta."""
    assert m.conferir_conta(TELA, "", ("EMPRESA FICTICIA",)) == m.SEM_COMO_CONFERIR
    assert "o ERP não tem o número desta conta Inter" in m.SEM_COMO_CONFERIR
    assert "confira o cadastro" in m.SEM_COMO_CONFERIR


def test_sem_numero_esperado_so_a_razao_social_inteira_confere():
    assert m.conferir_conta(TELA, "", ("EMPRESA FICTICIA",),
                            razoes=("Empresa  Fictícia Ltda",)) == ""


def test_sem_numero_esperado_razao_social_pela_metade_nao_confere():
    # A linha da tela é "EMPRESA FICTICIA LTDA": a razão tem de ser ELA inteira.
    assert m.conferir_conta(TELA, "", (), razoes=("EMPRESA FICTICIA",)) ==         m.SEM_COMO_CONFERIR
    tela_maior = TELA.replace("EMPRESA FICTICIA LTDA", "EMPRESA FICTICIA LTDA ME")
    assert m.conferir_conta(tela_maior, "", (), razoes=("EMPRESA FICTICIA LTDA",)) ==         m.SEM_COMO_CONFERIR


def test_sem_numero_nem_nome_recusa():
    assert m.conferir_conta(TELA, "", ()) == m.SEM_COMO_CONFERIR


class _Resp:
    def __init__(self, status, dado, url=m.URL_SALDO):
        self.status, self._dado, self.url = status, dado, url

    def json(self):
        return self._dado


class _Pag:
    def __init__(self):
        self.pedidos, self.ouvintes = [], {}

    def evaluate(self, js, args=None):
        self.pedidos.append((js, args))
        return {"status": 200, "dado": {"disponivel": 1.5}}

    def wait_for_timeout(self, ms):
        pass

    def on(self, evento, fn):
        self.ouvintes[evento] = fn


def test_resposta_ouvida_vale():
    pag = _Pag()
    assert m._resposta_do_saldo(pag, [_Resp(200, {"disponivel": 2})], {"valor": ""},
                                tempo=0) == (200, {"disponivel": 2})
    assert pag.pedidos == []


def test_sem_ouvir_pede_de_dentro_da_pagina():
    pag = _Pag()
    assert m._resposta_do_saldo(pag, [], {"valor": "Bearer x"}, tempo=0) == (
        200, {"disponivel": 1.5})
    assert pag.pedidos[0][1] == [m.URL_SALDO, "Bearer x"]


def test_sem_ouvir_e_sem_sessao_falha():
    with pytest.raises(m.SaldoInterFalhou, match="não pediu o saldo"):
        m._resposta_do_saldo(_Pag(), [], {"valor": ""}, tempo=0)


def test_escutar_saldo_so_guarda_a_rota_do_saldo():
    pag = _Pag()
    ouvidas = m.escutar_saldo(pag)
    pag.ouvintes["response"](_Resp(200, {}, url=ib.API_INTER + "/cc/pix/v1/extrato"))
    pag.ouvintes["response"](_Resp(200, {"disponivel": 1}))
    assert [r.url for r in ouvidas] == [m.URL_SALDO]


class _PagDaTela(_Pag):
    """Tela inicial do Inter já logada: o texto, a resposta e o print."""

    def __init__(self, texto=TELA):
        super().__init__()
        self.texto, self.fotos = texto, []

    def evaluate(self, js, args=None):
        return self.texto if args is None else super().evaluate(js, args)

    def screenshot(self, path):
        self.fotos.append(path)


def test_conta_certa_le_e_fotografa(tmp_path):
    pag = _PagDaTela()
    lido = m._ler_na_pagina(pag, [_Resp(200, {"disponivel": 9.9})], {"valor": ""},
                            "123456789", ("EMPRESA FICTICIA",), (), tmp_path / "b.png",
                            agora=lambda: "agora")
    assert (lido.saldo, lido.lido_em, lido.motivo) == (D("9.90"), "agora", "")
    assert lido.imagem == tmp_path / "b.png" and pag.fotos == [str(tmp_path / "b.png")]


def test_conta_errada_nao_e_fotografada(tmp_path):
    """Revisão de 27/10: o print era tirado ANTES de conferir, e a página
    "CONTA X" do PDF mostrava o saldo de outra empresa."""
    pag = _PagDaTela()
    lido = m._ler_na_pagina(pag, [_Resp(200, {"disponivel": 9.9})], {"valor": ""},
                            "987654321", ("EMPRESA FICTICIA",), (), tmp_path / "b.png",
                            agora=lambda: "agora")
    assert lido.saldo is None and "outra conta aberta" in lido.motivo
    assert lido.imagem is None and lido.sem_imagem == m.SEM_PRINT_OUTRA_CONTA
    assert "conta aberta era outra" in m.SEM_PRINT_OUTRA_CONTA
    assert pag.fotos == []


def test_conta_que_nao_da_para_conferir_tambem_fica_sem_print(tmp_path):
    pag = _PagDaTela(texto="Saldo\nR$ 1,00")
    lido = m._ler_na_pagina(pag, [_Resp(200, {"disponivel": 1})], {"valor": ""},
                            "123456789", (), (), tmp_path / "b.png", agora=lambda: None)
    assert lido.motivo == m.SEM_NUMERO and lido.sem_imagem == m.SEM_PRINT_SEM_CONFERIR
    assert pag.fotos == []


def test_parar_interrompe_a_espera_do_qr(monkeypatch):
    """Revisão de 27/10: o Parar não chegava ao esperar_login (até 300 s)."""
    monkeypatch.setattr(ib.time, "sleep", lambda s: None)
    pag = _PagDaTela(texto="Ler o QR code")
    vezes = []

    def parar():
        vezes.append(1)
        return len(vezes) > 2
    with pytest.raises(ib.InterFalhou, match="parad"):
        ib.esperar_login(pag, tempo=3600, log=lambda s: None, parar=parar)
    assert len(vezes) == 3


def test_gancho_do_olho_do_inter_clica_antes_do_print(monkeypatch, tmp_path):
    ordem = []
    monkeypatch.setattr(m, "SELETOR_MOSTRAR_SALDO", "#olho")
    monkeypatch.setattr(m.util, "revelar", lambda page, sel: ordem.append(("olho", sel)))
    monkeypatch.setattr(m.util, "fotografar", lambda alvo, arquivo: ordem.append("foto") or "")
    m._fotografar(_PagDaTela(), tmp_path / "b.png")
    assert ordem == [("olho", "#olho"), "foto"]
