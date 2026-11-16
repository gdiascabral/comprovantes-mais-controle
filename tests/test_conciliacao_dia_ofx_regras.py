# -*- coding: utf-8 -*-
"""Regras do Baixar OFX (aba Conciliação): lista, período, conferência do
OFX. Contas, nomes e números fictícios."""
import datetime as dt
from types import SimpleNamespace as NS

from conciliacao_dia import ofx_regras as r

D = dt.date
OFX = ("OFXHEADER:100\n<OFX><BANKACCTFROM><ACCTID>0012345-6</ACCTID></BANKACCTFROM>"
       "<BANKTRANLIST><DTSTART>20261028</DTSTART><DTEND>20261029</DTEND>"
       "<STMTTRN><TRNAMT>1.00</TRNAMT></STMTTRN><STMTTRN><TRNAMT>-2.00</TRNAMT></STMTTRN>")


def test_periodo_padrao_e_ontem_a_hoje():
    assert r.periodo_padrao(D(2026, 10, 29)) == (D(2026, 10, 28), D(2026, 10, 29))


def test_validar_periodo():
    hoje = D(2026, 10, 29)
    assert r.validar_periodo(D(2026, 10, 28), hoje, hoje) == ""
    assert r.validar_periodo(hoje, hoje, hoje) == ""
    assert "depois" in r.validar_periodo(D(2026, 10, 29), D(2026, 10, 28), hoje)
    assert "futuro" in r.validar_periodo(D(2026, 10, 28), D(2026, 10, 30), hoje)
    assert "2 anos" in r.validar_periodo(D(2024, 10, 28), hoje, hoje)


def test_conferir_ofx_conta_e_periodo():
    assert r.conferir_ofx(OFX, "12.345-6", D(2026, 10, 28), D(2026, 10, 29)) == ""
    assert "conta" in r.conferir_ofx(OFX, "99.999-9", D(2026, 10, 28), D(2026, 10, 29))
    assert "período" in r.conferir_ofx(OFX, "12.345-6", D(2026, 10, 27), D(2026, 10, 29))
    assert "ACCTID" in r.conferir_ofx("<OFX></OFX>", "12.345-6", D(2026, 10, 28),
                                      D(2026, 10, 29))
    assert "número" in r.conferir_ofx(OFX, "", D(2026, 10, 28), D(2026, 10, 29))


def test_conta_que_so_termina_igual_nao_confere():
    """"123456" não é "23456": a comparação é do número inteiro (sem os
    zeros à esquerda), nunca do fim."""
    assert "conta" in r.conferir_ofx(OFX, "2.345-6", D(2026, 10, 28), D(2026, 10, 29))


def test_ofx_sem_lancamento_confere_e_conta_zero():
    vazio = OFX.split("<STMTTRN>")[0]
    assert r.conferir_ofx(vazio, "12.345-6", D(2026, 10, 28), D(2026, 10, 29)) == ""
    assert r.lancamentos(vazio) == 0 and r.lancamentos(OFX) == 2


def _mapa(destinos):
    return NS(de=lambda nome: destinos.get(nome))


def _lista(monkeypatch, linha_de, linhas_do_dia, inter=None, destinos=None):
    numeros = {"ALFA - SICOOB": "12.345-6", "BETA - SICOOB": "12.345-6",
               "GAMA - SICOOB": "99.990-0", "DELTA - SICOOB": "23.456-7"}
    monkeypatch.setattr(r.ag, "conta_sicoob",
                        lambda nome, mapa, emp: (numeros.get(nome, ""),
                                                 "" if nome in numeros else "x"))
    contas_erp = [NS(id=f"id{i}", name=n, account_number="") for i, n in
                  enumerate(["DELTA - SICOOB", "ALFA - SICOOB", "BETA - SICOOB",
                             "GAMA - SICOOB", "EPSILON - INTER", "ZETA - CAIXA"])]
    mapping = NS(is_ignored=lambda n: False,
                 resolve_account=lambda c: NS(row=linha_de[c.name], exists_in_erp=True)
                 if c.name in linha_de else None)
    destinos = destinos if destinos is not None else {
        "EPSILON - INTER": NS(banco="077", empresa="EMPRESA E"),
        "ZETA - CAIXA": NS(banco="104", empresa="EMPRESA Z")}
    inter = inter if inter is not None else [NS(apelido="E", empresa="EMPRESA E")]
    return r.contas_para_ofx(contas_erp, mapping, _mapa(destinos), [], inter,
                             linhas_do_dia=linhas_do_dia, ignorar={"99.990-0"})


def test_lista_do_dia_primeiro_ignorada_fora_e_outro_banco_fora(monkeypatch):
    lista = _lista(monkeypatch, {"ALFA - SICOOB": 9, "BETA - SICOOB": 8}, {8, 9})
    assert [(c.nome, c.do_dia) for c in lista] == [
        ("BETA - SICOOB", True), ("ALFA - SICOOB", True),
        ("DELTA - SICOOB", False), ("EPSILON - INTER", False)]
    assert lista[2].numero == "23.456-7" and lista[2].erp_id == "id0"
    assert lista[3].banco == r.INTER and lista[3].apelido == "E" and lista[3].motivo == ""


def test_mesma_conta_do_sicoob_em_duas_linhas_so_entra_uma(monkeypatch):
    lista = _lista(monkeypatch, {"ALFA - SICOOB": 9, "BETA - SICOOB": 8}, {8, 9})
    assert lista[0].motivo == "" and lista[1].motivo == r.REPETIDA


def test_inter_sem_login_ou_com_dois_diz_por_que(monkeypatch):
    sem = _lista(monkeypatch, {}, set(), inter=[])
    assert sem[-1].nome == "EPSILON - INTER" and sem[-1].motivo == r.INTER_SEM_LOGIN
    dois = _lista(monkeypatch, {}, set(), inter=[NS(apelido="E1", empresa="EMPRESA E"),
                                                 NS(apelido="E2", empresa="Empresa  E")])
    assert dois[-1].motivo == r.INTER_DOIS_LOGINS and dois[-1].apelido == ""


def test_duas_contas_do_erp_no_mesmo_login_do_inter_so_uma_vai(monkeypatch):
    """Uma com o número no ERP e outra sem: chaves diferentes pelo número, o
    mesmo QR e o mesmo extrato — o OFX iria às duas (revisão de 16/11/2026)."""
    destinos = {"EPSILON - INTER": NS(banco="077", empresa="EMPRESA E"),
                "ZETA - CAIXA": NS(banco="077", empresa="EMPRESA E")}
    lista = _lista(monkeypatch, {}, set(), destinos=destinos)
    inter = [c for c in lista if c.banco == r.INTER]
    assert [c.apelido for c in inter] == ["E", "E"]
    assert sorted(c.motivo for c in inter) == ["", r.REPETIDA]


def test_linha_do_resultado():
    c = r.ContaOfx("i", "ALFA - SICOOB", r.SICOOB, numero="1")
    ini, fim = D(2026, 10, 28), D(2026, 10, 29)
    assert r.linha_do_resultado(r.Resultado(c, r.IMPORTADO, 0), ini, fim) == (
        "ALFA - SICOOB", "28/10 a 29/10", "0", "importado")
    assert r.linha_do_resultado(r.Resultado(c, r.NAO_IMPORTADO, motivo="parado"),
                                ini, fim) == (
        "ALFA - SICOOB", "28/10 a 29/10", "—", "não importado: parado")


def test_ler_data_dd_mm_aaaa():
    assert r.ler_data(" 28/10/2026 ") == D(2026, 10, 28)
    for ruim in ("", "28/10", "2026-10-28", "31/02/2026"):
        try:
            r.ler_data(ruim)
        except ValueError as e:
            assert "dd/mm/aaaa" in str(e)
        else:
            raise AssertionError(ruim)


def test_nomes_da_conta_inter_vem_do_cadastro():
    """Como na Prova de saldos: o nome curto da empresa, o do login e a
    razão social inteira (que confere a conta quando o ERP não tem o número)."""
    conta = r.ContaOfx("i", "EPSILON - INTER", r.INTER, apelido="E")
    mapa = _mapa({"EPSILON - INTER": NS(banco="077", empresa="EMPRESA E")})
    empresas = [NS(nome="Empresa E", razao_social="EMPRESA E SPE LTDA"),
                NS(nome="OUTRA", razao_social="OUTRA LTDA")]
    inter = [NS(apelido="E", empresa="EMPRESA E")]
    assert r.nomes_da_conta(conta, mapa, empresas, inter) == (
        ("EMPRESA E", "EMPRESA E SPE LTDA"), ("EMPRESA E SPE LTDA",))
    assert r.nomes_da_conta(r.ContaOfx("j", "SEM MAPA", r.INTER), mapa, empresas,
                            inter) == ((), ())
