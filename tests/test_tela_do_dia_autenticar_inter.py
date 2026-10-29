"""Autenticar no banco: a leitura do Inter, com dublês (sem Chrome)."""
import json
from datetime import date, datetime
from decimal import Decimal as D
from types import SimpleNamespace as NS

import pytest

from tela_do_dia import agendados as agd
from tela_do_dia import autenticar_inter as ai
from tela_do_dia import prova_saldos as ps

HOJE = date(2026, 10, 29)
DESC = "OBRA MODELO CASA 7 NF 1234 OC 55 CIMENTO FICTICIO E AREIA FINA"


def _ag(i, conta):
    return agd.Agendado(id=i, dia=date(2026, 10, 28), conta=conta, alvo=str(i),
                        lancamento_id="L", favorecido="F", valor=D("10.00"))


class _Mapa:
    def __init__(self, bancos):
        self.bancos = bancos

    def de(self, nome):
        b = self.bancos.get(nome)
        return None if b is None else NS(banco=b[0], empresa=b[1])


INTER = [NS(apelido="ALFA", empresa="EMPRESA ALFA"), NS(apelido="BETA", empresa="EMPRESA BETA"),
         NS(apelido="GAMA1", empresa="EMPRESA GAMA"), NS(apelido="GAMA2", empresa="EMPRESA GAMA")]


def test_contas_a_ler_pela_regua_da_prova():
    mapa = _Mapa({"ALFA - INTER": ("077", "EMPRESA ALFA"), "SIC": ("756", "EMPRESA ALFA"),
                  "SEM LOGIN - INTER": ("Inter", "EMPRESA ZETA"),
                  "GAMA - INTER": ("Inter", "EMPRESA GAMA"),
                  "BETA A - INTER": ("Inter", "EMPRESA BETA"),
                  "BETA B - INTER": ("Inter", "EMPRESA BETA")})
    erp = [NS(name="ALFA - INTER", account_number="12.345-6")]
    pend = [_ag(i, c) for i, c in enumerate(["ALFA - INTER", "SIC", "SEM LOGIN - INTER",
                                             "GAMA - INTER", "BETA A - INTER",
                                             "BETA B - INTER", "OUTRA"])]
    contas, falhas = ai.contas_a_ler(pend, mapa, [], INTER, erp)
    assert list(contas) == ["ALFA"] and contas["ALFA"].numero == "123456"
    assert falhas["SEM LOGIN - INTER"] == ps.INTER_FORA_DA_LISTA
    assert falhas["GAMA - INTER"] == ps.INTER_DOIS_LOGINS
    assert "mesmo login" in falhas["BETA A - INTER"] or falhas["BETA A - INTER"] == \
        ps.INTER_REPETIDA.format(apelido="BETA")
    assert "SIC" not in falhas and "OUTRA" not in falhas


def _detalhe(tipo, op="D", valor="10.00", dia="2026-10-28"):
    return {"rawValue": valor, "metadata": {"operationType": op, "transactionType": tipo},
            "data": {"transactionDate": dia, "aboutTransaction": {"description": DESC}}}


def _corpo(*detalhes):
    return {"transactions": {"data": [{"bankStatements": [
        {"transactions": [{"detail": d} for d in detalhes]}]}]}}


def test_extrato_completo_nao_repete_pix_nem_a_2via():
    from tela_do_dia import autenticar as au
    da_2via = [au.Movimento("C", date(2026, 10, 28), D("10.00"), "", DESC)]
    corpo = _corpo(_detalhe("PIX"), _detalhe("PAGAMENTO"), _detalhe("CONVENIO", valor="7.00"),
                   _detalhe("CONVENIO", op="C", valor="8.00"))
    movs = ai.do_extrato_sem_repetir(corpo, "C", da_2via)
    assert [m.valor for m in movs] == [D("7.00")]


class _Pagina:
    def __init__(self, pix=None, via=None, erro=None):
        self.pix, self.via, self.erro = pix or [], via or {}, erro

    def evaluate(self, js, args):
        if "pix/v1/extrato" in js:
            return {"erro": self.erro} if self.erro else {"movimentacoes": self.pix}
        return {"operacoes": self.via.get(args[-1], [])}


def test_listar_na_sessao_junta_as_tres_fontes():
    pix = [{"tipo": "D", "valor": 10, "data": "2026-10-28", "detalhePix": {"campoLivre": DESC}},
           {"tipo": "C", "valor": 99, "data": "2026-10-28", "detalhePix": {}}]
    via = {"PAGAMENTO": [{"valor": "20,00", "dataEfetivacao": "2026-10-28", "descricao": DESC,
                          "pagamento": {"status": "EFETIVADO"}}]}
    movs = ai.listar_na_sessao(_Pagina(pix, via), {"valor": "x"},
                               lambda: _corpo(_detalhe("CONVENIO", valor="7.00")), "C",
                               date(2026, 10, 27), HOJE)
    assert sorted(m.valor for m in movs) == [D("7.00"), D("10.00"), D("20.00")]


def test_listar_na_sessao_levanta_quando_uma_lista_falha():
    with pytest.raises(RuntimeError, match="extrato Pix"):
        ai.listar_na_sessao(_Pagina(erro="HTTP 500"), {"valor": "x"}, lambda: {}, "C",
                            HOJE, HOJE)
    with pytest.raises(RuntimeError, match="extrato completo"):
        ai.listar_na_sessao(_Pagina(), {"valor": "x"}, lambda: None, "C", HOJE, HOJE)
    with pytest.raises(RuntimeError, match="autorização"):
        ai.listar_na_sessao(_Pagina(), {"valor": ""}, lambda: {}, "C", HOJE, HOJE)


def _lido(saldo=D("5.00"), motivo="", extra=None, erro="", imagem=None):
    return NS(saldo=saldo, lido_em=datetime(2026, 10, 29, 8, 5) if saldo is not None else None,
              motivo=motivo, extra=extra, extra_erro=erro, imagem=imagem, via="extrato")


def test_ler_so_marca_lida_a_conta_com_listas():
    contas = {"ALFA": ai.ContaInter("ALFA", "C1"), "BETA": ai.ContaInter("BETA", "C2"),
              "GAMA": ai.ContaInter("GAMA", "C3")}
    respostas = {"ALFA": _lido(extra=["m"]), "BETA": _lido(erro="API mudou"),
                 "GAMA": _lido(saldo=None, motivo="outra conta aberta, não leio")}
    r, lidos = ai.ler(contas, HOJE, HOJE, ".", log=lambda *a: None,
                      ler_conta=lambda apelido, *a, **k: respostas[apelido])
    assert r.lidas == {"C1"} and r.movimentos == ["m"]
    assert "API mudou" in r.falhas["C2"] and "outra conta" in r.falhas["C3"]
    assert set(lidos) == {"ALFA", "BETA", "GAMA"}


def test_saldo_do_dia_ida_e_volta_e_de_outro_dia_nao_vale(tmp_path):
    arq = tmp_path / "s.json"
    img = tmp_path / "p.png"
    img.write_bytes(b"x")
    ai.gravar_saldos({"ALFA": _lido(imagem=img), "BETA": _lido(saldo=None)}, arq, HOJE)
    lido = ai.saldo_do_dia(arq, HOJE, "ALFA")
    assert lido.saldo == D("5.00") and lido.imagem == img and lido.lido_em.hour == 8
    assert ai.saldo_do_dia(arq, HOJE, "BETA") is None
    assert ai.saldo_do_dia(arq, date(2026, 10, 30), "ALFA") is None
    arq.write_text("{estragado", encoding="utf-8")
    assert ai.saldo_do_dia(arq, HOJE, "ALFA") is None


def test_gravar_saldos_junta_com_o_que_ja_havia_hoje(tmp_path):
    arq = tmp_path / "s.json"
    ai.gravar_saldos({"ALFA": _lido()}, arq, HOJE)
    ai.gravar_saldos({"BETA": _lido(saldo=D("7.00"))}, arq, HOJE)
    contas = json.loads(arq.read_text(encoding="utf-8"))["contas"]
    assert set(contas) == {"ALFA", "BETA"}
    assert ai.gravar_saldos({"X": _lido(saldo=None)}, tmp_path / "n.json", HOJE) is None


def test_prova_de_saldos_usa_o_saldo_do_autenticar_de_hoje(monkeypatch, tmp_path):
    import conciliacao.frame as cf
    from tela_do_dia import prova_na_tela as pnt
    monkeypatch.setattr(cf, "RAIZ_SAIDA", tmp_path)
    monkeypatch.setattr(pnt, "_agora", lambda: datetime(2026, 10, 29, 9, 0))
    assert pnt._saldo_do_autenticar("ALFA") is None
    ai.gravar_saldos({"ALFA": _lido()}, ai.caminho_dos_saldos(tmp_path, HOJE), HOJE)
    assert pnt._saldo_do_autenticar("ALFA").saldo == D("5.00")
    monkeypatch.setattr(pnt, "_agora", lambda: datetime(2026, 10, 30, 9, 0))
    assert pnt._saldo_do_autenticar("ALFA") is None
