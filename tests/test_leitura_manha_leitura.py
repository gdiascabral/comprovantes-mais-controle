# -*- coding: utf-8 -*-
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from conciliacao.models import ErpAccount
from leitura_manha import config as cf
from leitura_manha import leitura as lt
from leitura_manha.transporte import ErroLeitura

ONTEM, HOJE = date(2026, 11, 26), date(2026, 11, 27)
HORA = datetime(2026, 11, 27, 10, 30, tzinfo=timezone.utc)


def agora():
    return HORA


def _cfg():
    return cf.de_dict({"ambiente": "producao", "nuvem_email": "r@e.com", "nuvem_senha": "s",
                       "pasta": "p", "empresas": [
        {"nome": "EMP A", "sicoob": {"client_id": "A", "cert": ["c", "k"]},
         "contas": [{"banco": "sicoob", "numero": 11, "conta_erp": "A1 - SICOOB"},
                    {"banco": "sicoob", "numero": 12, "conta_erp": "A2 - SICOOB"}]},
        {"nome": "EMP B", "sicoob": {"client_id": "B", "cert": ["c", "k"]},
         "inter": {"client_id": "i", "client_secret": "s", "cert": ["c", "k"]},
         "contas": [{"banco": "sicoob", "numero": 21, "conta_erp": "B1 - SICOOB"},
                    {"banco": "inter", "conta_erp": "B2 - INTER"}]}]})


def _ext(*linhas):
    return {"transacoes": list(linhas)}


def _deb(valor, desc, data="2026-11-26"):
    return {"tipo": "DEBITO", "valor": valor, "data": data, "descInfComplementar": desc}


class Sicoob:
    """`extratos[numero]`: a resposta de cada pedido, ou uma função (inicio, fim)."""

    def __init__(self, saldos, extratos):
        self.saldos, self.extratos, self.pedidos = saldos, extratos, []

    def saldo(self, numero):
        v = self.saldos[numero]
        if isinstance(v, Exception):
            raise v
        return v

    def extrato(self, numero, inicio, fim):
        assert inicio.month == fim.month and inicio <= fim
        self.pedidos.append((numero, inicio, fim))
        v = self.extratos[numero]
        if callable(v):
            v = v(inicio, fim)
        if isinstance(v, Exception):
            raise v
        return v


class Inter:
    def __init__(self, saldo, extrato):
        self._s, self._e = saldo, extrato

    def saldo(self):
        if isinstance(self._s, Exception):
            raise self._s
        return self._s

    def extrato(self, inicio, fim):
        self.pedido = (inicio, fim)
        return self._e


class Fabrica:
    def __init__(self, sicoob, inter=None):
        self._sicoob, self._inter = sicoob, inter

    def sicoob(self, empresa):
        c = self._sicoob[empresa.nome]
        if isinstance(c, Exception):
            raise c
        return c

    def inter(self, empresa, conta):
        return self._inter


def _tudo_bom():
    return Fabrica({"EMP A": Sicoob({11: {"saldo": Decimal("100.00")}, 12: {"saldo": 0}},
                                    {11: _ext(_deb("150,00", "OBRA X LT 10")), 12: _ext()}),
                    "EMP B": Sicoob({21: {"saldo": Decimal("5.50")}}, {21: _ext()})},
                   Inter({"disponivel": Decimal("7.00")},
                         {"transacoes": [{"tipoOperacao": "C", "valor": "1.00",
                                          "dataEntrada": "2026-11-26"}]}))


def _saldo(le, conta):
    (s,) = [s for s in le.saldos if s.conta == conta]
    return s


def test_tudo_lido():
    le = lt.ler_bancos(_cfg(), _tudo_bom(), ONTEM, agora)
    assert [(s.conta, s.valor) for s in le.saldos] == [
        ("A1 - SICOOB", Decimal("100.00")), ("A2 - SICOOB", Decimal("0.00")),
        ("B1 - SICOOB", Decimal("5.50")), ("B2 - INTER", Decimal("7.00"))]
    assert le.lidas == {"A1 - SICOOB", "A2 - SICOOB", "B1 - SICOOB", "B2 - INTER"}
    assert [m.valor for m in le.movimentos] == [Decimal("150.00")] and le.falhas == {}


def test_token_de_uma_empresa_caido_nao_derruba_a_outra_e_nao_vira_zero():
    f = _tudo_bom()
    f._sicoob["EMP A"] = Sicoob({11: ErroLeitura(None, "token recusado"),
                                 12: ErroLeitura(None, "token recusado")},
                                {11: ErroLeitura(None, "token recusado"),
                                 12: ErroLeitura(None, "token recusado")})
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    for conta in ("A1 - SICOOB", "A2 - SICOOB"):
        s = _saldo(le, conta)
        assert s.valor is None and "token recusado" in s.motivo
        assert conta in le.falhas and conta not in le.lidas
    assert _saldo(le, "B1 - SICOOB").valor == Decimal("5.50") and "B2 - INTER" in le.lidas


def test_fabrica_que_estoura_vira_motivo_de_cada_conta_da_empresa():
    f = _tudo_bom()
    f._sicoob["EMP A"] = KeyError("cert")
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    assert _saldo(le, "A1 - SICOOB").motivo == "Sicoob: erro inesperado (KeyError)"
    assert _saldo(le, "B1 - SICOOB").valor == Decimal("5.50")


def test_fabrica_da_empresa_e_chamada_uma_vez_mesmo_quando_falha():
    f = _tudo_bom()
    chamadas = []
    original = f.sicoob

    def contando(empresa):
        chamadas.append(empresa.nome)
        if empresa.nome == "EMP A":
            raise ErroLeitura(None, "token recusado")
        return original(empresa)
    f.sicoob = contando
    lt.ler_bancos(_cfg(), f, ONTEM, agora)
    assert chamadas == ["EMP A", "EMP B"]


def test_erro_inesperado_numa_conta_nao_para_as_seguintes():
    f = _tudo_bom()
    f._sicoob["EMP A"].saldos[11] = RuntimeError("bug")
    f._sicoob["EMP A"].extratos[11] = RuntimeError("bug")
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    assert _saldo(le, "A1 - SICOOB").valor is None
    assert _saldo(le, "A2 - SICOOB").valor == Decimal("0.00")
    assert le.falhas["A1 - SICOOB"] == "Sicoob: erro inesperado (RuntimeError)"


def test_saldo_lido_e_extrato_caido_sao_independentes():
    f = _tudo_bom()
    f._sicoob["EMP A"].extratos[11] = ErroLeitura(503, "fora")
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    assert _saldo(le, "A1 - SICOOB").valor == Decimal("100.00")
    assert le.falhas["A1 - SICOOB"] == "Sicoob respondeu HTTP 503"
    assert le.movimentos == []


def test_uma_linha_ilegivel_tira_a_conta_do_casamento():
    f = _tudo_bom()
    f._sicoob["EMP A"].extratos[11] = _ext(_deb("150,00", "OBRA X LT 10"),
                                           {"tipo": "lorem", "valor": "x", "data": "y"})
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    assert "A1 - SICOOB" not in le.lidas and "1 linha(s) ilegível(is)" in le.falhas["A1 - SICOOB"]
    assert le.movimentos == []
    (x,) = [x for x in le.extratos if x.conta == "A1 - SICOOB"]
    assert x.ilegiveis == 1 and x.motivo


def test_saldo_lido_sem_motivo_e_nao_lido_sem_motivo_sao_recusados():
    with pytest.raises(ValueError):
        lt.SaldoLido("A", "sicoob", "E", None, "", HORA)
    with pytest.raises(ValueError):
        lt.SaldoLido("A", "sicoob", "E", Decimal("1.00"), "não lido", HORA)


def test_erp_lido_sem_saldo_e_nao_lido_nunca_zero():
    contas = [ErpAccount("1", "A1 - SICOOB", balance=Decimal("99.9")),
              ErpAccount("2", "B1 - SICOOB", raw_balance="R$ ***", balance=None)]
    saida = lt.ler_erp(lambda: contas, ["A1 - SICOOB", "B1 - SICOOB", "B2 - INTER"], agora)
    por = {s.conta: s for s in saida}
    assert por["A1 - SICOOB"].valor == Decimal("99.90") and por["A1 - SICOOB"].fonte == "erp"
    assert por["B1 - SICOOB"].valor is None and "não mostrou" in por["B1 - SICOOB"].motivo
    assert por["B2 - INTER"].valor is None and "não encontrada" in por["B2 - INTER"].motivo


def test_erp_fora_marca_cada_conta_como_nao_lida():
    def cai():
        raise RuntimeError("porteiro do ERP desligado (Chrome central)")
    saida = lt.ler_erp(cai, ["A1 - SICOOB", "B2 - INTER"], agora)
    assert [(s.conta, s.valor) for s in saida] == [("A1 - SICOOB", None), ("B2 - INTER", None)]
    assert all("porteiro" in s.motivo for s in saida)


@pytest.mark.parametrize("agora_utc, hoje, ontem", [
    (datetime(2026, 11, 27, 10, 30, tzinfo=timezone.utc), date(2026, 11, 27), date(2026, 11, 26)),
    (datetime(2026, 11, 27, 2, 0, tzinfo=timezone.utc), date(2026, 11, 26), date(2026, 11, 25)),
    (datetime(2026, 1, 1, 2, 59, tzinfo=timezone.utc), date(2025, 12, 31), date(2025, 12, 30)),
    (datetime(2026, 3, 1, 3, 0, tzinfo=timezone.utc), date(2026, 3, 1), date(2026, 2, 28)),
])
def test_ontem_e_o_de_sao_paulo(agora_utc, hoje, ontem):
    assert lt.dias_sp(agora_utc) == (hoje, ontem)


def test_agora_sem_fuso_e_recusado():
    with pytest.raises(ValueError):
        lt.dias_sp(datetime(2026, 11, 27, 7, 30))


def _linha(id_, conta, valor, desc, dia="2026-11-26", **foto):
    return {"id": id_, "dia": dia, "conta": conta, "alvo": f"t{id_}", "lancamento_id": f"L{id_}",
            "favorecido": "FORNECEDOR TESTE", "valor": valor, "descricao": desc,
            "foto": {"descricao_colada": desc, **foto}}


def test_pre_marca_so_o_que_o_extrato_de_ontem_prova():
    le = lt.ler_bancos(_cfg(), _tudo_bom(), ONTEM, agora)
    linhas = [_linha(1, "A1 - SICOOB", "150.00", "OBRA X LT 10"),
              _linha(2, "A1 - SICOOB", "150.00", "OUTRA COISA"),
              _linha(3, "B1 - SICOOB", "150.00", "OBRA X LT 10")]
    marcas = {m.agendado_id: m for m in lt.pre_marcas(linhas, le, HOJE)}
    assert marcas[1].prova.startswith("banco — Sicoob extrato (API) 26/11: mesmo valor e descrição")
    assert marcas[2].prova == "" and "mesmo valor" in marcas[2].nota
    assert marcas[3].prova == "" and marcas[3].nota == "nada no banco ainda"


def test_conta_nao_lida_nunca_pre_marca():
    f = _tudo_bom()
    f._sicoob["EMP A"].extratos[11] = _ext(_deb("150,00", "OBRA X LT 10"),
                                           {"tipo": "lorem", "valor": "x", "data": "y"})
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    (m,) = lt.pre_marcas([_linha(1, "A1 - SICOOB", "150.00", "OBRA X LT 10")], le, HOJE)
    assert m.prova == "" and m.nota.startswith("banco não lido: Sicoob: 1 linha(s) ilegível(is)")


def test_conta_fora_do_arquivo_nao_aparece_e_linha_ruim_e_contada():
    le = lt.ler_bancos(_cfg(), _tudo_bom(), ONTEM, agora)
    avisos = []
    ruim = {"id": 9, "dia": "", "valor": None}
    marcas = lt.pre_marcas([_linha(5, "OUTRA CONTA - CAIXA", "150.00", "OBRA X LT 10"), ruim],
                           le, HOJE, log=avisos.append)
    assert marcas == [] and avisos == ["  1 agendado(s) em aberto ilegível(is) na nuvem: ficaram fora",
                                       "  1 agendado(s) de conta fora do arquivo do servidor"]


def test_erp_conta_sem_nome_ganha_rotulo_e_mantem_valor_e_motivo():
    contas = [ErpAccount("1", "   ", balance=Decimal("5.00")),
              ErpAccount("2", "B1 - SICOOB", raw_balance="R$ ***", balance=None)]
    saida = lt.ler_erp(lambda: contas, [], agora)
    assert [s.conta for s in saida] == ["(sem nome no ERP)", "B1 - SICOOB"]
    assert saida[0].valor == Decimal("5.00") and saida[0].motivo == ""
    assert saida[1].valor is None and "não mostrou" in saida[1].motivo


def test_erp_arredonda_meio_para_cima():
    (s,) = lt.ler_erp(lambda: [ErpAccount("1", "A", balance=Decimal("10.125"))], [], agora)
    assert s.valor == Decimal("10.13")


def test_extrato_que_falha_sai_nao_lido_e_motivo_obrigatorio():
    with pytest.raises(ValueError):
        lt.ExtratoLido("A", "sicoob", "E", date(2026, 11, 26), lido=False)
    f = _tudo_bom()
    f._sicoob["EMP A"].extratos[11] = ErroLeitura(503, "fora")
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    (x,) = [x for x in le.extratos if x.conta == "A1 - SICOOB"]
    assert not x.lido and x.motivo == "Sicoob respondeu HTTP 503"
    f2 = _tudo_bom()
    f2._sicoob["EMP A"] = RuntimeError("fábrica")
    le2 = lt.ler_bancos(_cfg(), f2, ONTEM, agora)
    assert all(not x.lido for x in le2.extratos if x.empresa == "EMP A")


# ------------------------------------------- F3: nome repetido no ERP
REPETIDO = "nome repetido no ERP: confira o cadastro"


def test_erp_nome_repetido_nenhum_vale_e_ganha_sufixo():
    contas = [ErpAccount("1", "A1 - SICOOB", balance=Decimal("10.00")),
              ErpAccount("2", "B1 - SICOOB", balance=Decimal("5.00")),
              ErpAccount("3", "A1 - SICOOB", balance=Decimal("20.00")),
              ErpAccount("4", "A1 - SICOOB", raw_balance="R$ ***", balance=None)]
    saida = lt.ler_erp(lambda: contas, ["A1 - SICOOB"], agora)
    assert [(s.conta, s.valor, s.motivo) for s in saida] == [
        ("A1 - SICOOB", None, REPETIDO), ("B1 - SICOOB", Decimal("5.00"), ""),
        ("A1 - SICOOB #2", None, REPETIDO), ("A1 - SICOOB #3", None, REPETIDO)]


def test_erp_sem_nome_repetido_e_nome_longo_cortado_em_200():
    longo = "X" * 250
    contas = [ErpAccount("1", "", balance=Decimal("1.00")), ErpAccount("2", " ", balance=Decimal("2.00")),
              ErpAccount("3", longo, balance=Decimal("3.00")),
              ErpAccount("4", longo[:200] + "Y", balance=Decimal("4.00"))]
    saida = lt.ler_erp(lambda: contas, [], agora)
    nomes = [s.conta for s in saida]
    assert nomes[:2] == ["(sem nome no ERP)", "(sem nome no ERP) #2"]
    assert nomes[2] == "X" * 200 and nomes[3] == "X" * 197 + " #2"
    assert all(s.valor is None and s.motivo == REPETIDO for s in saida)
    assert len(set(nomes)) == 4 and all(len(n) <= 200 for n in nomes)


def test_erp_sufixo_nao_colide_com_nome_que_ja_existe():
    contas = [ErpAccount("1", "A", balance=Decimal("1.00")), ErpAccount("2", "A #2", balance=Decimal("2.00")),
              ErpAccount("3", "A", balance=Decimal("3.00"))]
    saida = lt.ler_erp(lambda: contas, [], agora)
    assert [s.conta for s in saida] == ["A", "A #2", "A #3"]
    assert saida[1].valor == Decimal("2.00")


# --------------------------------- F1: janela de 7 dias no casamento
def test_janela_le_7_dias_e_pede_uma_vez_no_mesmo_mes():
    f = _tudo_bom()
    lt.ler_bancos(_cfg(), f, ONTEM, agora)
    assert f._sicoob["EMP A"].pedidos == [(11, date(2026, 11, 20), ONTEM), (12, date(2026, 11, 20), ONTEM)]
    assert f._inter.pedido == (date(2026, 11, 20), ONTEM)


def test_pagamento_em_dobro_em_dias_seguidos_nao_pre_marca():
    f = _tudo_bom()
    f._sicoob["EMP A"].extratos[11] = _ext(_deb("150,00", "OBRA X LT 10", "2026-11-25"),
                                           _deb("150,00", "OBRA X LT 10", "2026-11-26"))
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    (m,) = lt.pre_marcas([_linha(1, "A1 - SICOOB", "150.00", "OBRA X LT 10", dia="2026-11-25")],
                         le, HOJE)
    assert m.prova == "" and m.nota.startswith("pagamentos parecidos no banco")


def test_janela_que_cruza_o_mes_pede_duas_vezes_com_os_dias_certos():
    f = _tudo_bom()
    ontem = date(2026, 12, 2)

    def por_mes(inicio, fim):
        return _ext(_deb("150,00", "OBRA X LT 10", f"{inicio:%Y-%m-%d}"))
    f._sicoob["EMP A"].extratos[11] = por_mes
    le = lt.ler_bancos(_cfg(), f, ontem, agora)
    assert [p for p in f._sicoob["EMP A"].pedidos if p[0] == 11] == [
        (11, date(2026, 11, 26), date(2026, 11, 30)), (11, date(2026, 12, 1), date(2026, 12, 2))]
    assert sorted(m.data for m in le.movimentos if m.conta == "A1 - SICOOB") == [
        date(2026, 11, 26), date(2026, 12, 1)]
    assert "A1 - SICOOB" in le.lidas


def test_um_pedaco_da_janela_falhando_tira_a_conta_do_casamento():
    f = _tudo_bom()

    def cai_em_dezembro(inicio, fim):
        if inicio.month == 12:
            return ErroLeitura(503, "fora")
        return _ext(_deb("150,00", "OBRA X LT 10", "2026-11-27"))
    f._sicoob["EMP A"].extratos[11] = cai_em_dezembro
    le = lt.ler_bancos(_cfg(), f, date(2026, 12, 2), agora)
    assert "A1 - SICOOB" not in le.lidas and le.falhas["A1 - SICOOB"] == "Sicoob respondeu HTTP 503"
    assert not [m for m in le.movimentos if m.conta == "A1 - SICOOB"]
    (x,) = [x for x in le.extratos if x.conta == "A1 - SICOOB"]
    assert not x.lido


def test_pedaco_da_janela_com_linha_ilegivel_tira_a_conta():
    f = _tudo_bom()

    def ilegivel_em_dezembro(inicio, fim):
        if inicio.month == 12:
            return _ext({"tipo": "lorem", "valor": "x", "data": "y"})
        return _ext()
    f._sicoob["EMP A"].extratos[11] = ilegivel_em_dezembro
    le = lt.ler_bancos(_cfg(), f, date(2026, 12, 2), agora)
    assert "A1 - SICOOB" not in le.lidas and "ilegível" in le.falhas["A1 - SICOOB"]


def test_agendado_antigo_recebe_nota_e_nunca_prova():
    f = _tudo_bom()
    f._sicoob["EMP A"].extratos[11] = _ext(_deb("150,00", "OBRA X LT 10", "2026-11-20"))
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    linhas = [_linha(1, "A1 - SICOOB", "150.00", "OBRA X LT 10", dia="2026-11-18",
                     vencimento="2026-11-19"),
              _linha(2, "A1 - SICOOB", "150.00", "OBRA X LT 10", dia="2026-11-21")]
    marcas = {m.agendado_id: m for m in lt.pre_marcas(linhas, le, HOJE)}
    assert marcas[1].prova == "" and marcas[1].nota == "agendado antigo: fora dos 7 dias lidos do extrato"
    # o antigo continua disputando o pagamento: o de 21 não fica com ele sozinho
    assert marcas[2].prova == ""


def test_extrato_lido_conta_so_ontem_e_fora_e_o_que_ficou_fora_da_janela():
    f = _tudo_bom()
    f._sicoob["EMP A"].extratos[11] = _ext(
        _deb("10,00", "A", "2026-11-24"), _deb("20,00", "B", "2026-11-26"),
        {"tipo": "CREDITO", "valor": "5,00", "data": "2026-11-25"},
        {"tipo": "CREDITO", "valor": "6,00", "data": "2026-11-26"},
        _deb("30,00", "C", "2026-11-10"))
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    (x,) = [x for x in le.extratos if x.conta == "A1 - SICOOB"]
    assert (x.dia, x.saidas, x.entradas, x.fora_do_dia, x.lido) == (ONTEM, 1, 1, 1, True)
    assert sorted(m.valor for m in le.movimentos if m.conta == "A1 - SICOOB") == [
        Decimal("10.00"), Decimal("20.00")]


# --------------------------------------- F4: débito devolvido no dia
def test_debito_devolvido_no_mesmo_dia_tira_a_conta_do_casamento():
    f = _tudo_bom()
    f._sicoob["EMP A"].extratos[11] = _ext(_deb("150,00", "OBRA X LT 10", "2026-11-25"),
                                           {"tipo": "CREDITO", "valor": "150,00", "data": "2026-11-25"})
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    assert "A1 - SICOOB" not in le.lidas
    assert le.falhas["A1 - SICOOB"] == "débito devolvido no extrato de 25/11: confira à mão"
    assert not [m for m in le.movimentos if m.conta == "A1 - SICOOB"]
    (x,) = [x for x in le.extratos if x.conta == "A1 - SICOOB"]
    assert x.lido and x.motivo == le.falhas["A1 - SICOOB"]
    (m,) = lt.pre_marcas([_linha(1, "A1 - SICOOB", "150.00", "OBRA X LT 10", dia="2026-11-25")], le, HOJE)
    assert m.prova == "" and "débito devolvido" in m.nota


def test_entrada_de_mesmo_valor_em_outro_dia_nao_e_devolucao():
    f = _tudo_bom()
    f._sicoob["EMP A"].extratos[11] = _ext(_deb("150,00", "OBRA X LT 10", "2026-11-25"),
                                           {"tipo": "CREDITO", "valor": "150,00", "data": "2026-11-26"})
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    assert "A1 - SICOOB" in le.lidas


# ------------------------------ F5: pendência de assinatura do Sicoob
AVISO_PENDENCIA = " · pendências de assinatura não conferidas"


def test_prova_do_sicoob_avisa_que_pendencia_nao_foi_conferida():
    f = _tudo_bom()
    f._inter._e = {"transacoes": [{"tipoOperacao": "D", "valor": "40.00", "dataEntrada": "2026-11-26",
                                   "descricao": "OBRA Y LT 2"}]}
    le = lt.ler_bancos(_cfg(), f, ONTEM, agora)
    linhas = [_linha(1, "A1 - SICOOB", "150.00", "OBRA X LT 10"),
              _linha(2, "B2 - INTER", "40.00", "OBRA Y LT 2")]
    marcas = {m.agendado_id: m for m in lt.pre_marcas(linhas, le, HOJE)}
    assert marcas[1].prova.endswith(AVISO_PENDENCIA)
    assert marcas[2].prova and AVISO_PENDENCIA not in marcas[2].prova


def test_aviso_de_pendencia_respeita_o_corte_de_300():
    p = lt.com_aviso_de_pendencia("x" * 400)
    assert len(p) == 300 and p.endswith(AVISO_PENDENCIA)
    assert lt.com_aviso_de_pendencia("") == ""
