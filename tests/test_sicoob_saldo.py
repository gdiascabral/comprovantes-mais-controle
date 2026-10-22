# -*- coding: utf-8 -*-
"""Saldo do Sicoob sem rede. A maior parte dos testes usa um endereço e um
formato FICTÍCIOS, plugados pelo fixture `medido`; os do fim provam o formato
MEDIDO em 22/10/2026 (a estrutura do Sicoob, com valores inventados). Contas
fictícias."""
import datetime as dt
import json
import re
from decimal import Decimal as D

import pytest

from extratos_sicoob import saldo as S
from extratos_sicoob import sicoob_client as sc

AGORA = dt.datetime(2026, 10, 22, 8, 12, 30)


@pytest.fixture
def medido(monkeypatch):
    monkeypatch.setattr(S, "ROTA_SALDO", "/api/ficticio/saldo")
    monkeypatch.setattr(S, "METODO_SALDO", "GET")
    monkeypatch.setattr(S, "CORPO_SALDO", None)
    monkeypatch.setattr(S, "CAMPO_SALDO", "saldo.valor")
    monkeypatch.setattr(S, "CAMPO_SINAL", "")
    monkeypatch.setattr(S, "CAMPO_CONTA", "")
    monkeypatch.setattr(S, "CAMPO_ERRO", "")


def ok(valor):
    return {"status": 200, "corpo": json.dumps({"saldo": {"valor": valor}})}


class Pagina:
    def __init__(self, respostas):
        self.aberta, self.respostas, self.pedidos = "", respostas, []
        self.url = "https://ib.sicoob.com.br/sicoobnet/ib/#/home"
        self.recargas = 0

    def evaluate(self, js, args=None):
        if js == sc.JS_TEXTOS_DA_CONTA:
            novo = f"0001 | {self.aberta} | PJ | X" if self.aberta else None
            return {"novo": novo, "corpo": ""}
        url, metodo, corpo = args
        self.pedidos.append((url, metodo, corpo, self.aberta))
        r = self.respostas[re.sub(r"\D", "", self.aberta)]
        return r() if callable(r) else r

    def reload(self): self.recargas += 1
    def wait_for_timeout(self, _ms): pass


class Cliente:
    def __init__(self, pagina, na_lista, trava=()):
        self.page, self.na_lista, self.trava, self.trocas = pagina, na_lista, trava, []

    def listar_contas(self):
        return list(self.na_lista)

    def acessar_conta(self, numero):
        # Como o real: procura a linha da lista pelo TEXTO (`has_text`), então
        # "12345-6" não acha "12.345-6".
        self.trocas.append(numero)
        if numero not in self.na_lista:
            return False
        if numero not in self.trava:                # troca que "não pegou"
            self.page.aberta = numero
        return True


def test_conta_do_cadastro_sem_o_ponto_casa_pelos_digitos(medido):
    """Prova ao vivo 22/10: o cadastro tinha a conta sem o ponto e o Sicoob a
    escreve com ele — ficava "não aparece neste login". Conta fictícia."""
    pagina = Pagina({"123456": ok("7.00")})
    cli = Cliente(pagina, ["12.345-6"])
    [a] = S.ler_contas(cli, ["12345-6"], agora=lambda: AGORA)
    assert a.ok and a.saldo == D("7.00") and a.numero == "12345-6"
    assert cli.trocas == ["12.345-6"]               # entrou com o número da lista


def test_conta_que_a_lista_nao_mostra_ainda_tenta_como_veio(medido):
    """A lista não reconheceu a linha (formato novo): vale o caminho antigo."""
    pagina = Pagina({"123456": ok("1")})
    cli = Cliente(pagina, ["12.345-6"])
    cli.listar_contas = lambda: []
    [a] = S.ler_contas(cli, ["12.345-6"], agora=lambda: AGORA)
    assert a.ok and cli.trocas == ["12.345-6"]


def test_sem_endereco_medido_recusa_antes_de_tocar_no_banco(monkeypatch):
    monkeypatch.setattr(S, "ROTA_SALDO", "")
    cli = Cliente(Pagina({}), ["12.345-6"])
    with pytest.raises(S.SaldoFalhou, match="ainda não está ligada"):
        S.ler_contas(cli, ["12.345-6"], agora=lambda: AGORA)
    assert cli.trocas == []


def test_le_cada_conta_com_a_sua_conta_aberta(medido):
    pagina = Pagina({"123456": ok("1500.10"), "234567": ok("-20.5")})
    cli = Cliente(pagina, ["12.345-6", "23.456-7"])
    lidos = S.ler_contas(cli, ["12.345-6", "23.456-7"], agora=lambda: AGORA)
    assert [(l.numero, l.saldo, l.lido_em) for l in lidos] == [
        ("12.345-6", D("1500.10"), AGORA), ("23.456-7", D("-20.50"), AGORA)]
    assert [p[3] for p in pagina.pedidos] == ["12.345-6", "23.456-7"]
    assert pagina.pedidos[0][0] == S.BASE + "/api/ficticio/saldo"


def test_troca_que_nao_pegou_nao_le_o_saldo_da_outra(medido):
    pagina = Pagina({"123456": ok("10.00"), "234567": ok("99.00")})
    cli = Cliente(pagina, ["12.345-6", "23.456-7"], trava=("23.456-7",))
    a, b = S.ler_contas(cli, ["12.345-6", "23.456-7"], agora=lambda: AGORA)
    assert a.ok and not b.ok and "a tela está em 12.345-6" in b.motivo
    assert len(pagina.pedidos) == 1                 # B nem chegou a pedir


def test_conta_fora_do_login_vira_motivo_e_a_fila_segue(medido):
    pagina = Pagina({"234567": ok("5")})
    cli = Cliente(pagina, ["23.456-7"])
    a, b = S.ler_contas(cli, ["12.345-6", "23.456-7"], agora=lambda: AGORA)
    assert "não aparece neste login" in a.motivo and b.saldo == D("5.00")


def test_sessao_caida_para_e_marca_as_que_faltavam(medido):
    pagina = Pagina({"123456": ok("1"), "234567": {"status": 401, "corpo": ""},
                     "345678": ok("3")})
    cli = Cliente(pagina, ["12.345-6", "23.456-7", "34.567-8"])
    a, b, c = S.ler_contas(cli, ["12.345-6", "23.456-7", "34.567-8"], agora=lambda: AGORA)
    assert a.ok and b.motivo == S.SESSAO_CAIU and c.motivo == S.SESSAO_CAIU
    assert cli.trocas == ["12.345-6", "23.456-7"]


def test_sessao_caida_pela_tela_de_login(medido):
    pagina = Pagina({"123456": ok("1")})
    pagina.url = "https://ib.sicoob.com.br/sicoobnet/ib/#/login"
    [a] = S.ler_contas(Cliente(pagina, ["12.345-6"]), ["12.345-6"], agora=lambda: AGORA)
    assert a.motivo == S.SESSAO_CAIU


def test_endereco_mudou_para_tudo_com_recado_claro(medido):
    pagina = Pagina({"123456": {"status": 404, "corpo": "Not Found"}, "234567": ok("2")})
    cli = Cliente(pagina, ["12.345-6", "23.456-7"])
    a, b = S.ler_contas(cli, ["12.345-6", "23.456-7"], agora=lambda: AGORA)
    assert "não reconhece mais o endereço do saldo" in a.motivo
    assert "/api/ficticio/saldo" in a.motivo and "HTTP 404" in a.motivo
    assert b.motivo == a.motivo and cli.trocas == ["12.345-6"]


def test_formato_novo_sem_o_campo_e_recado_claro(medido):
    pagina = Pagina({"123456": {"status": 200, "corpo": '{"outro": 1}'}})
    [a] = S.ler_contas(Cliente(pagina, ["12.345-6"]), ["12.345-6"], agora=lambda: AGORA)
    assert "não tem mais 'saldo.valor'" in a.motivo


def test_resposta_que_nao_e_json(medido):
    pagina = Pagina({"123456": {"status": 200, "corpo": "<html>"}})
    [a] = S.ler_contas(Cliente(pagina, ["12.345-6"]), ["12.345-6"], agora=lambda: AGORA)
    assert "não devolveu JSON" in a.motivo


def test_erro_qualquer_numa_conta_nao_derruba_as_outras(medido):
    pagina = Pagina({"123456": {"status": 500, "corpo": "pane"}, "234567": ok("2")})
    a, b = S.ler_contas(Cliente(pagina, ["12.345-6", "23.456-7"]),
                        ["12.345-6", "23.456-7"], agora=lambda: AGORA)
    assert "HTTP 500" in a.motivo and b.ok


def test_dinheiro_e_decimal_nunca_float(medido):
    assert S.interpretar({"status": 200, "corpo": '{"saldo": {"valor": 0.1}}'}, "12.345-6") == D("0.10")
    assert S.para_decimal("1.234,56") == D("1234.56")
    assert S.para_decimal("-1.234,56") == D("-1234.56")
    with pytest.raises(S.EnderecoMudou):
        S.para_decimal(True)


def test_sinal_devedor(medido, monkeypatch):
    monkeypatch.setattr(S, "CAMPO_SALDO", "valor")
    monkeypatch.setattr(S, "CAMPO_SINAL", "natureza")
    r = {"status": 200, "corpo": '{"valor": 50.00, "natureza": "D"}'}
    assert S.interpretar(r, "12.345-6") == D("-50.00")


def test_resposta_de_outra_conta_e_recusada(medido, monkeypatch):
    monkeypatch.setattr(S, "CAMPO_CONTA", "conta")
    r = {"status": 200, "corpo": '{"saldo": {"valor": 1}, "conta": "234567"}'}
    with pytest.raises(S.OutraConta):
        S.interpretar(r, "12.345-6")


def test_conta_no_endereco_e_no_corpo(medido, monkeypatch):
    monkeypatch.setattr(S, "ROTA_SALDO", "/api/ficticio/{conta}/saldo")
    monkeypatch.setattr(S, "METODO_SALDO", "POST")
    monkeypatch.setattr(S, "CORPO_SALDO", {"contas": ["{conta}"], "tipo": 1})
    url, metodo, corpo = S.montar_pedido("12.345-6")
    assert url.endswith("/api/ficticio/123456/saldo") and metodo == "POST"
    assert corpo == {"contas": ["123456"], "tipo": 1}
    assert S.CORPO_SALDO == {"contas": ["{conta}"], "tipo": 1}     # não mutou


def test_parar_marca_as_que_faltavam(medido):
    pagina = Pagina({"123456": ok("1"), "234567": ok("2")})
    feitas = []
    lidos = S.ler_contas(Cliente(pagina, ["12.345-6", "23.456-7"]), ["12.345-6", "23.456-7"],
                         agora=lambda: AGORA, parar=lambda: len(feitas) >= 1,
                         log=feitas.append)
    assert lidos[0].ok and lidos[1].motivo == S.INTERROMPIDA


def test_mesma_conta_duas_vezes_e_lida_uma(medido):
    pagina = Pagina({"123456": ok("1")})
    lidos = S.ler_contas(Cliente(pagina, ["12.345-6"]), ["12.345-6", "123456"], agora=lambda: AGORA)
    assert len(lidos) == 1 and len(pagina.pedidos) == 1


def test_endereco_no_repositorio_nao_carrega_numero_de_conta():
    texto = S.ROTA_SALDO + json.dumps(S.CORPO_SALDO)
    assert not re.search(r"\d{5,}", texto)


# ------------------------------------------- o formato medido em 22/10/2026

def medida(saldo=1234.56, natureza="C", conta=123456, erro=False, cooperativa=1):
    """A ESTRUTURA da resposta medida em 22/10/2026; todo valor é inventado."""
    return {"status": 200, "corpo": json.dumps({"contaCorrente": {
        "erroServicoMovimentoContaCorrente": erro,
        "extratoContaCorrente": {
            "cabecalho": {"numContaCorrente": conta, "numeroCooperativa": cooperativa},
            "resumo": {"saldoEmContaCorrente": saldo, "naturezaSaldoRes": natureza},
        }}})}


def test_leitura_ligada():
    assert S.medido()


def test_endereco_medido_e_get_sem_conta_e_sem_block_ui():
    url, metodo, corpo = S.montar_pedido("12.345-6")
    assert url == ("https://ib.sicoob.com.br/sicoobnet"
                   "/api/home/obter-informacoes-widget-movimentacoes-inicio")
    assert metodo == "GET" and corpo is None


def test_formato_medido_em_22_10():
    """Estrutura do Sicoob medida em 22/10/2026; valores fictícios."""
    assert S.interpretar(medida(), "12.345-6") == D("1234.56")


def test_formato_medido_devedor_vira_negativo():
    assert S.interpretar(medida(saldo=50.5, natureza="D"), "12.345-6") == D("-50.50")
    # já negativo e devedor não vira positivo
    assert S.interpretar(medida(saldo=-50.5, natureza="D"), "12.345-6") == D("-50.50")


def test_formato_medido_natureza_desconhecida_e_recusada():
    with pytest.raises(S.SaldoFalhou, match="naturezaSaldoRes") as e:
        S.interpretar(medida(natureza="X"), "12.345-6")
    assert not isinstance(e.value, S.EnderecoMudou)       # só esta conta
    with pytest.raises(S.SaldoFalhou) as e:
        S.interpretar(medida(natureza=""), "12.345-6")
    assert not isinstance(e.value, S.EnderecoMudou)
    # saldo zero não depende do sinal
    assert S.interpretar(medida(saldo=0, natureza=""), "12.345-6") == D("0.00")


def test_formato_medido_conta_com_o_digito_e_zeros_a_esquerda():
    """`numContaCorrente` traz todos os dígitos COM o DV (medido ao vivo)."""
    assert S.interpretar(medida(conta=123456), "12.345-6") == D("1234.56")
    assert S.interpretar(medida(conta=12345), "01.234-5") == D("1234.56")
    assert S.interpretar(medida(saldo=110.4), "12.345-6") == D("110.40")


def test_formato_medido_conta_sem_o_digito_e_recusada():
    with pytest.raises(S.OutraConta):
        S.interpretar(medida(conta=12345), "12.345-6")


def test_formato_medido_outra_conta_e_recusada():
    with pytest.raises(S.OutraConta):
        S.interpretar(medida(conta=234567), "12.345-6")
    with pytest.raises(S.OutraConta):
        S.interpretar(medida(conta=23456), "12.345-6")
    with pytest.raises(S.OutraConta):                     # sem conta: falha fechada
        S.interpretar(medida(conta=""), "12.345-6")
    with pytest.raises(S.OutraConta):                     # só o DV não basta
        S.interpretar(medida(conta=6), "12.345-6")


def test_formato_medido_erro_do_servico_nao_vira_saldo():
    with pytest.raises(S.SaldoFalhou, match="não conseguiu ler") as e:
        S.interpretar(medida(erro=True), "12.345-6")
    assert not isinstance(e.value, S.EnderecoMudou)       # só esta conta


def test_formato_medido_na_fila_inteira():
    pagina = Pagina({"123456": medida(saldo=10, conta=123456),
                     "234567": medida(saldo=20, natureza="D", conta=234567)})
    cli = Cliente(pagina, ["12.345-6", "23.456-7"])
    lidos = S.ler_contas(cli, ["12.345-6", "23.456-7"], agora=lambda: AGORA)
    assert [l.saldo for l in lidos] == [D("10.00"), D("-20.00")]
    assert all(p[1] == "GET" and p[2] is None for p in pagina.pedidos)


# ------------------------------- conserto: formato ruim numa conta só segue

def _so_da_conta(resposta):
    with pytest.raises(S.SaldoFalhou) as e:
        S.interpretar(resposta, "12.345-6")
    assert not isinstance(e.value, S.EnderecoMudou)
    return str(e.value)


def test_campo_ausente_ou_saldo_que_nao_e_numero_e_falha_so_da_conta():
    nulo = {"status": 200, "corpo": json.dumps(
        {"contaCorrente": {"erroServicoMovimentoContaCorrente": False,
                           "extratoContaCorrente": None}})}
    assert "o formato do Sicoob mudou" in _so_da_conta(nulo)
    texto = medida(saldo="abc")
    assert "não é número" in _so_da_conta(texto)
    assert "não é número" in _so_da_conta(medida(saldo=None))


def test_natureza_desconhecida_numa_conta_e_a_fila_segue():
    pagina = Pagina({"123456": medida(natureza="X"),
                     "234567": medida(saldo=20, conta=234567)})
    cli = Cliente(pagina, ["12.345-6", "23.456-7"])
    a, b = S.ler_contas(cli, ["12.345-6", "23.456-7"], agora=lambda: AGORA)
    assert not a.ok and "naturezaSaldoRes" in a.motivo
    assert b.saldo == D("20.00") and cli.trocas == ["12.345-6", "23.456-7"]


def test_formato_ruim_alternado_nao_para_a_fila():
    ruim = {"status": 200, "corpo": '{"contaCorrente": null}'}
    pagina = Pagina({"123456": ruim, "234567": medida(saldo=2, conta=234567),
                     "345678": ruim})
    cli = Cliente(pagina, ["12.345-6", "23.456-7", "34.567-8"])
    a, b, c = S.ler_contas(cli, ["12.345-6", "23.456-7", "34.567-8"], agora=lambda: AGORA)
    assert not a.ok and b.ok and not c.ok
    assert cli.trocas == ["12.345-6", "23.456-7", "34.567-8"]


def test_duas_contas_seguidas_com_formato_ruim_param_a_fila():
    ruim = {"status": 200, "corpo": '{"contaCorrente": null}'}
    pagina = Pagina({"123456": medida(saldo=1), "234567": ruim, "345678": ruim,
                     "456789": medida(saldo=4, conta=456789)})
    cli = Cliente(pagina, ["12.345-6", "23.456-7", "34.567-8", "45.678-9"])
    a, b, c, d = S.ler_contas(cli, ["12.345-6", "23.456-7", "34.567-8", "45.678-9"],
                              agora=lambda: AGORA)
    assert a.ok and not b.ok
    assert "o formato do Sicoob mudou" in b.motivo
    assert "duas contas seguidas" in c.motivo and d.motivo == c.motivo
    assert cli.trocas == ["12.345-6", "23.456-7", "34.567-8"]   # a 4ª nem é aberta


def test_resposta_que_nao_e_json_ainda_para_a_fila(medido):
    pagina = Pagina({"123456": {"status": 200, "corpo": "<html>"}, "234567": ok("2")})
    cli = Cliente(pagina, ["12.345-6", "23.456-7"])
    a, b = S.ler_contas(cli, ["12.345-6", "23.456-7"], agora=lambda: AGORA)
    assert "não devolveu JSON" in a.motivo and b.motivo == a.motivo
    assert cli.trocas == ["12.345-6"]
