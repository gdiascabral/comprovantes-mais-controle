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
    def __init__(self, saldos, extratos):
        self.saldos, self.extratos = saldos, extratos

    def saldo(self, numero):
        v = self.saldos[numero]
        if isinstance(v, Exception):
            raise v
        return v

    def extrato(self, numero, dia):
        assert dia == ONTEM
        v = self.extratos[numero]
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

    def extrato(self, dia):
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
    assert marcas == [] and avisos == ["  1 agendado(s) em aberto ilegível(is) na nuvem: ficaram fora"]


def test_erp_conta_sem_nome_ganha_rotulo_e_mantem_valor_e_motivo():
    contas = [ErpAccount("1", "   ", balance=Decimal("5.00")),
              ErpAccount("2", "", raw_balance="R$ ***", balance=None)]
    saida = lt.ler_erp(lambda: contas, [], agora)
    assert [s.conta for s in saida] == ["(sem nome no ERP)"] * 2
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
