# -*- coding: utf-8 -*-
"""A rodada do Baixar OFX (Sicoob → Inter → ERP), sem tela: os três motores
são dublês. Aqui se prova que só OFX que confere chega ao ERP, que nenhuma
conta some do resultado, que o Parar deixa o que já importou e que nada é
importado duas vezes (revisão de dinheiro de 16/11/2026). Fictício."""
import datetime as dt
from pathlib import Path

from baixar_comprovantes.inter_ofx import OfxInter
from conciliacao_dia import importados as imp
from conciliacao_dia import ofx_regras as r
from conciliacao_dia import rodada as m
from extratos_sicoob import saldo

INI, FIM = dt.date(2026, 10, 28), dt.date(2026, 10, 29)
U1, U2, U3, U4 = "aaaaaaaa-0001", "bbbbbbbb-0002", "cccccccc-0003", "dddddddd-0004"


def _trn(fitid, valor="-1.00"):
    return f"<STMTTRN><FITID>{fitid}</FITID><TRNAMT>{valor}</TRNAMT></STMTTRN>"


def _ofx(conta, ini="20261028", fim="20261029", n=2, base="F"):
    return (f"<OFX><ACCTID>{conta}</ACCTID><DTSTART>{ini}</DTSTART><DTEND>{fim}</DTEND>"
            "<BANKTRANLIST>" + "".join(_trn(f"{base}{i}") for i in range(n))
            + "</BANKTRANLIST></OFX>")


def _contas():
    return [r.ContaOfx(U1, "ALFA - SICOOB", r.SICOOB, numero="12.345-6", do_dia=True),
            r.ContaOfx(U2, "BETA - SICOOB", r.SICOOB, numero="23.456-7"),
            r.ContaOfx(U3, "GAMA - INTER", r.INTER, numero="", apelido="G"),
            r.ContaOfx(U4, "DELTA - INTER", r.INTER, apelido="", motivo=r.INTER_SEM_LOGIN)]


class _Motores:
    def __init__(self, tmp_path, sicoob_textos=None, inter_resp=None, erp_estado=m.ENVIO_OK,
                 fora=(), outro_acesso=False, sicoob_quebra=None):
        self.tmp, self.chamadas, self.pedidos_erp, self.perguntas = tmp_path, [], [], []
        self.sicoob_textos = sicoob_textos or {"123456": _ofx("0012345-6", base="A"),
                                               "234567": _ofx("23456-7", n=3, base="B")}
        self.inter_resp, self.erp_estado, self.fora = inter_resp, erp_estado, set(fora)
        self.outro_acesso, self.sicoob_quebra = outro_acesso, sicoob_quebra
        self.registro = []

    def sicoob(self, contas, pasta):
        self.chamadas.append(("sicoob", [c.numero for c in contas]))
        if self.sicoob_quebra:
            raise RuntimeError(self.sicoob_quebra)
        saida = {}
        Path(pasta).mkdir(parents=True, exist_ok=True)
        for c in contas:
            d = r.ps.digitos(c.numero)
            if d in self.fora and len([x for x in self.chamadas if x[0] == "sicoob"]) == 1:
                saida[d] = (None, saldo.FORA_DESTE_LOGIN)
                continue
            arq = Path(pasta) / f"{d}.ofx"
            arq.write_text(self.sicoob_textos[d], encoding="cp1252")
            saida[d] = (arq, "")
        return saida

    def inter(self, conta, arquivo):
        self.chamadas.append(("inter", conta.apelido))
        if self.inter_resp is not None:
            return self.inter_resp
        Path(arquivo).write_text(_ofx("362674043", n=9, base="I"), encoding="cp1252")
        return OfxInter(Path(arquivo), "362674043", "")

    def erp(self, pedidos):
        self.chamadas.append(("erp", [p[0] for p in pedidos]))
        self.pedidos_erp = list(pedidos)
        motivo = "" if self.erp_estado == m.ENVIO_OK else "o ERP não confirmou"
        return {p[0]: (self.erp_estado, motivo) for p in pedidos}

    def perguntar(self, faltam):
        self.perguntas.append(faltam)
        return self.outro_acesso

    def registrar(self, erp_id, chaves, incerto):
        self.registro.append((erp_id, sorted(chaves), incerto))


def _rodar(mot, contas=None, parar=lambda: False, ja=None):
    return m.rodar(contas or _contas(), INI, FIM, mot.tmp, sicoob=mot.sicoob, inter=mot.inter,
                   erp=mot.erp, perguntar_outro_acesso=mot.perguntar, avisar=lambda s: None,
                   ja_importados=ja, registrar=mot.registrar, parar=parar, log=lambda s: None)


def test_ordem_sicoob_inter_erp_e_uma_linha_por_conta(tmp_path):
    mot = _Motores(tmp_path)
    res = _rodar(mot)
    assert [c[0] for c in mot.chamadas] == ["sicoob", "inter", "erp"]
    assert [x.conta.erp_id for x in res] == [U1, U2, U3, U4]
    assert [(x.situacao, x.lancamentos) for x in res[:3]] == [
        (r.IMPORTADO, 2), (r.IMPORTADO, 3), (r.IMPORTADO, 9)]
    assert res[3].situacao == r.NAO_IMPORTADO and res[3].motivo == r.INTER_SEM_LOGIN
    assert ("inter", "") not in mot.chamadas                 # a sem login nem abre
    assert [x[0] for x in mot.registro] == [U1, U2, U3] and not any(x[2] for x in mot.registro)


def test_cada_conta_vai_num_arquivo_seu(tmp_path):
    mot = _Motores(tmp_path)
    _rodar(mot)
    nomes = [p[2].name for p in mot.pedidos_erp]
    assert nomes == [f"sicoob {U1}.ofx", f"sicoob {U2}.ofx", f"inter {U3}.ofx"]


def test_ofx_de_outra_conta_nao_chega_ao_erp(tmp_path):
    mot = _Motores(tmp_path, sicoob_textos={"123456": _ofx("99999-9"),
                                            "234567": _ofx("23456-7")})
    res = _rodar(mot)
    assert res[0].situacao == r.NAO_IMPORTADO and "99999-9" in res[0].motivo
    assert U1 not in [p[0] for p in mot.pedidos_erp]
    assert res[1].situacao == r.IMPORTADO


def test_ofx_de_outro_periodo_nao_chega_ao_erp(tmp_path):
    mot = _Motores(tmp_path, sicoob_textos={"123456": _ofx("12345-6", ini="20261001"),
                                            "234567": _ofx("23456-7")})
    res = _rodar(mot)
    assert res[0].situacao == r.NAO_IMPORTADO and "período" in res[0].motivo
    assert U1 not in [p[0] for p in mot.pedidos_erp]


def test_ja_importado_sai_do_arquivo_e_so_o_novo_vai(tmp_path):
    """O "ontem a hoje" de amanhã repete o "hoje" de hoje: o que já entrou
    sai do OFX antes do envio."""
    mot = _Motores(tmp_path)
    ja = {U1: {"fitid:A0"}, U2: {"fitid:B0", "fitid:B1", "fitid:B2"}}
    res = _rodar(mot, contas=_contas()[:2], ja=ja)
    assert (res[0].situacao, res[0].lancamentos) == (r.IMPORTADO, 1)
    assert "1 já importado" in res[0].motivo
    enviado = mot.pedidos_erp[0][2].read_text(encoding="cp1252")
    assert "A0" not in enviado and "A1" in enviado and "<ACCTID>0012345-6" in enviado
    assert (res[1].situacao, res[1].motivo) == (r.NADA_NOVO, m.NADA_NOVO)
    assert [p[0] for p in mot.pedidos_erp] == [U1]
    assert mot.registro == [(U1, ["fitid:A1"], False)]


def test_ofx_sem_lancamento_nao_vai_e_diz_que_nao_havia_nada(tmp_path):
    """Fim de semana (medido em 16/11/2026: 21 de 23 contas sem lançamento):
    não é "já importado", é "sem lançamentos"."""
    mot = _Motores(tmp_path, sicoob_textos={"123456": _ofx("12345-6", n=0),
                                            "234567": _ofx("23456-7")})
    res = _rodar(mot, contas=_contas()[:2])
    assert (res[0].situacao, res[0].motivo) == (r.NADA_NOVO, m.SEM_LANCAMENTOS)
    assert [p[0] for p in mot.pedidos_erp] == [U2]


def test_rodada_parada_e_clicada_de_novo_nao_reenvia(tmp_path):
    mot = _Motores(tmp_path)
    _rodar(mot, contas=_contas()[:2])
    ja: dict = {}
    for erp_id, chaves, _inc in mot.registro:
        ja.setdefault(erp_id, set()).update(chaves)
    mot2 = _Motores(tmp_path)
    res = _rodar(mot2, contas=_contas()[:2], ja=ja)
    assert [x.situacao for x in res] == [r.NADA_NOVO, r.NADA_NOVO]
    assert not any(c[0] == "erp" for c in mot2.chamadas)


def test_sem_confirmacao_e_nao_verificado_e_entra_no_registro(tmp_path):
    mot = _Motores(tmp_path, erp_estado=m.ENVIO_INCERTO)
    res = _rodar(mot)
    assert [x.situacao for x in res[:3]] == [r.NAO_VERIFICADO] * 3
    assert "confira no extrato do ERP" in res[0].motivo and res[0].lancamentos == 2
    assert all(inc for _e, _c, inc in mot.registro) and len(mot.registro) == 3


def test_falha_antes_do_envio_nao_entra_no_registro(tmp_path):
    mot = _Motores(tmp_path, erp_estado=m.ENVIO_FALHOU)
    res = _rodar(mot)
    assert [x.situacao for x in res[:3]] == [r.NAO_IMPORTADO] * 3
    assert res[0].motivo == "o ERP não confirmou" and mot.registro == []


def test_dois_ofx_da_mesma_conta_so_o_primeiro_vai(tmp_path):
    textos = {"123456": _ofx("12345-6"), "234567": _ofx("12345-6")}
    mot = _Motores(tmp_path, sicoob_textos=textos)
    contas = [_contas()[0], r.ContaOfx(U2, "BETA - SICOOB", r.SICOOB, numero="23.456-7")]
    # o 2º arquivo diz ser da 12.345-6 e a conta pedida é a 23.456-7: já recusa
    res = _rodar(mot, contas=contas)
    assert res[1].situacao == r.NAO_IMPORTADO
    inter2 = [_contas()[2], r.ContaOfx(U4, "DELTA - INTER", r.INTER, apelido="D")]
    mot2 = _Motores(tmp_path)
    res2 = _rodar(mot2, contas=inter2)
    assert res2[0].situacao == r.IMPORTADO
    assert res2[1].situacao == r.NAO_IMPORTADO and "já vai por outra linha" in res2[1].motivo
    assert [p[0] for p in mot2.pedidos_erp] == [U3]


def test_arquivo_que_muda_depois_de_conferido_nao_vai(tmp_path, monkeypatch):
    mot = _Motores(tmp_path)
    reais = m._hash
    vezes = {"n": 0}

    def hash_que_muda(arq):
        vezes["n"] += 1
        return reais(arq) + ("x" if vezes["n"] > 3 and "sicoob " + U1 in str(arq) else "")
    monkeypatch.setattr(m, "_hash", hash_que_muda)
    res = _rodar(mot)
    assert (res[0].situacao, res[0].motivo) == (r.NAO_IMPORTADO, m.MUDOU)
    assert U1 not in [p[0] for p in mot.pedidos_erp]


def test_sicoob_que_quebra_nao_derruba_o_inter(tmp_path):
    mot = _Motores(tmp_path, sicoob_quebra="Timeout esperando o login")
    res = _rodar(mot)
    assert [x.situacao for x in res[:2]] == [r.NAO_IMPORTADO] * 2
    assert "o Sicoob parou" in res[0].motivo and "login" in res[0].motivo
    assert res[2].situacao == r.IMPORTADO


def test_inter_sem_numero_no_erp_confere_contra_a_tela(tmp_path):
    mot = _Motores(tmp_path, inter_resp=None)
    res = _rodar(mot, contas=[_contas()[2]])
    assert res[0].situacao == r.IMPORTADO
    mot2 = _Motores(tmp_path)
    mot2.inter = lambda conta, arquivo: (Path(arquivo).write_text(_ofx("111111111"),
                                                                  encoding="cp1252"),
                                         OfxInter(Path(arquivo), "362674043", ""))[1]
    res2 = _rodar(mot2, contas=[_contas()[2]])
    assert res2[0].situacao == r.NAO_IMPORTADO and "111111111" in res2[0].motivo


def test_inter_que_nao_baixa_leva_o_motivo(tmp_path):
    mot = _Motores(tmp_path, inter_resp=OfxInter(None, motivo="leia o QR de novo"))
    res = _rodar(mot, contas=[_contas()[2]])
    assert (res[0].situacao, res[0].motivo) == (r.NAO_IMPORTADO, "leia o QR de novo")
    assert not any(c[0] == "erp" for c in mot.chamadas)


def test_conta_de_outro_acesso_pergunta_e_le_no_segundo_login(tmp_path):
    mot = _Motores(tmp_path, fora={"234567"}, outro_acesso=True)
    res = _rodar(mot, contas=_contas()[:2])
    assert mot.perguntas == [["23.456-7"]]
    assert [c for c in mot.chamadas if c[0] == "sicoob"] == [
        ("sicoob", ["12.345-6", "23.456-7"]), ("sicoob", ["23.456-7"])]
    assert [x.situacao for x in res] == [r.IMPORTADO, r.IMPORTADO]


def test_outro_acesso_recusado_deixa_a_conta_com_o_motivo(tmp_path):
    mot = _Motores(tmp_path, fora={"234567"}, outro_acesso=False)
    res = _rodar(mot, contas=_contas()[:2])
    assert (res[1].situacao, res[1].motivo) == (r.NAO_IMPORTADO, saldo.FORA_DESTE_LOGIN)


def test_parar_antes_do_erp_nao_importa_nada_e_nada_some(tmp_path):
    vezes = []
    mot = _Motores(tmp_path)
    res = _rodar(mot, parar=lambda: vezes.append(1) or len(vezes) > 2)
    assert not any(c[0] == "erp" for c in mot.chamadas)
    assert [x.conta.erp_id for x in res] == [U1, U2, U3, U4]
    assert all(x.situacao == r.NAO_IMPORTADO for x in res)
    assert all(x.motivo for x in res) and mot.registro == []


# --------------------------------------------------------- o registro em disco
def test_chaves_usam_o_fitid_e_sem_ele_nao_juntam_lancamentos_iguais():
    sem = "<STMTTRN><DTPOSTED>20261028</DTPOSTED><TRNAMT>-5.00</TRNAMT><MEMO>PIX</MEMO></STMTTRN>"
    texto = "<BANKTRANLIST>" + _trn("X1") + sem + sem + "</BANKTRANLIST>"
    ks = imp.chaves(texto)
    assert ks[0] == "fitid:X1" and ks[1] != ks[2] and ks[2].endswith("#2")


def test_ofx_sem_tag_de_fechamento_tambem_separa_os_lancamentos():
    texto = ("<BANKTRANLIST><STMTTRN><FITID>1<TRNAMT>-1.00"
             "<STMTTRN><FITID>2<TRNAMT>-2.00</BANKTRANLIST>")
    novo, chaves, tirados = imp.sem_os_ja_importados(texto, {"fitid:1"})
    assert chaves == ["fitid:2"] and tirados == 1
    assert "<FITID>1" not in novo and "<FITID>2" in novo and novo.endswith("</BANKTRANLIST>")


def test_registro_grava_le_e_ilegivel_levanta(tmp_path):
    assert imp.ler(tmp_path) == {}
    imp.registrar(tmp_path, U1, ["fitid:1"], incerto=False)
    imp.registrar(tmp_path, U1, ["fitid:2"], incerto=True)
    assert imp.ler(tmp_path) == {U1: {"fitid:1", "fitid:2"}}
    (tmp_path / imp.ARQUIVO).write_text("torto", encoding="utf-8")
    try:
        imp.ler(tmp_path)
    except imp.RegistroIlegivel:
        pass
    else:
        raise AssertionError("registro ilegível não levantou")
