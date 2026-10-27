# -*- coding: utf-8 -*-
"""A regra da Prova de saldos, sem tela nem rede. Contas e valores fictícios."""
import datetime as dt
from dataclasses import replace
from decimal import Decimal as D
from types import SimpleNamespace as NS

from conciliacao.models import ErpAccount, ModelRow
from tela_do_dia import prova_saldos as ps
from tela_do_dia import saldo_sicoob as ss
from tela_do_dia import saldos as sd
from baixar_comprovantes.contas_inter import ContaInter

AGORA = dt.datetime(2026, 10, 27, 14, 5)
ALFA = ps.ContaDaProva(8, "CONTA ALFA", ps.SICOOB, numero="12.345-6")
BETA = ps.ContaDaProva(9, "CONTA BETA", ps.INTER, apelido="BETA")


class _Mapa:
    def __init__(self, rows):
        self.rows = rows

    @property
    def live_rows(self):
        return [r for r in self.rows if r.exists_in_erp]

    def is_ignored(self, nome):
        return False

    def resolve_account(self, conta):
        return next((r for r in self.rows if r.erp_name == conta.name), None)

    def by_row(self, n):
        return next((r for r in self.rows if r.row == n), None)


class _MapaMc:
    def __init__(self, destinos):
        self.destinos = destinos

    def de(self, nome):
        return self.destinos.get(nome)


def _l(valor, motivo=""):
    return ps.Leitura(None if valor is None else D(valor), AGORA if valor else None, motivo)


def test_bate_em_centavos_com_arredondamento():
    assert ps.comparar(ALFA, _l("100.004"), _l("100.00")).situacao == ps.BATE
    assert ps.comparar(ALFA, _l("10.005"), _l("10.01")).situacao == ps.BATE
    linha = ps.comparar(ALFA, _l("10.00"), _l("10.00"))
    assert (linha.diferenca, linha.motivo) == (D("0.00"), "")


def test_nao_bate_mostra_a_diferenca_banco_menos_erp():
    linha = ps.comparar(ALFA, _l("1500.00"), _l("1499.90"))
    assert linha.situacao == ps.NAO_BATE
    assert linha.diferenca == D("-0.10")
    assert linha.motivo == "diferença de -R$ 0,10"


def test_sem_leitura_de_um_lado_e_nao_lida_com_o_motivo():
    sem_banco = ps.comparar(ALFA, _l("1.00"), _l(None, "esta conta não aparece neste login do Sicoob"))
    assert sem_banco.situacao == ps.NAO_LIDA and sem_banco.diferenca is None
    assert sem_banco.motivo == "banco: esta conta não aparece neste login do Sicoob"
    sem_erp = ps.comparar(ALFA, _l(None, "o ERP não trouxe o saldo desta conta"), _l("1.00"))
    assert sem_erp.motivo == "ERP: o ERP não trouxe o saldo desta conta"
    assert ps.comparar(ALFA, _l(None), _l(None)).motivo == "ERP: não lido"


def test_conta_com_motivo_nunca_bate_mesmo_com_valores_iguais():
    conta = ps.ContaDaProva(9, "CONTA BETA", ps.INTER, motivo=ps.INTER_DOIS_LOGINS)
    linha = ps.comparar(conta, _l("5.00"), _l("5.00"))
    assert linha.situacao == ps.NAO_LIDA and linha.motivo == ps.INTER_DOIS_LOGINS


def test_inter_com_outra_conta_aberta_vira_nao_lida():
    linha = ps.comparar(BETA, _l("5.00"), _l(None, "outra conta aberta, não leio"))
    assert linha.situacao == ps.NAO_LIDA and "outra conta aberta" in linha.motivo


def test_montar_ordena_pela_linha_e_preenche_o_que_falta():
    linhas = ps.montar([BETA, ALFA], {8: _l("1.00")}, {8: _l("1.00")})
    assert [l.conta.linha for l in linhas] == [8, 9]
    assert linhas[0].situacao == ps.BATE
    assert linhas[1].situacao == ps.NAO_LIDA and linhas[1].motivo == "ERP: não lido"


def test_contagem_e_registro():
    linhas = [ps.comparar(ALFA, _l("1.00"), _l("1.00")),
              ps.comparar(BETA, _l("1.00"), _l("2.00"))]
    assert ps.contagem(linhas) == {ps.BATE: 1, ps.NAO_BATE: 1, ps.NAO_LIDA: 0}
    assert ps.texto_da_contagem(linhas) == "1 batem, 1 não batem, 0 não lidas"
    assert ps.texto_do_registro(linhas[1]) == (
        "  ❌ CONTA BETA: ERP R$ 1,00 · banco R$ 2,00 — diferença de R$ 1,00")


def test_celulas_na_ordem_das_colunas():
    linha = ps.comparar(ALFA, _l("1500.00"), _l("1499.90"))
    assert ps.celulas(linha) == ("CONTA ALFA", "R$ 1.500,00", "R$ 1.499,90", "-R$ 0,10",
                                 "❌ não bate", "14:05", "14:05")
    assert ps.celulas(linha, com_marca=False)[4] == "não bate"
    vazia = ps.comparar(BETA, _l(None), _l(None))
    assert ps.celulas(vazia)[1:4] == ("—", "—", "—") and ps.celulas(vazia)[5:] == ("—", "—")


def test_nomes_de_arquivo():
    assert ps.nome_base(AGORA) == "Prova de saldos 2026-10-27 14h05"
    assert ps.nome_do_print(8, "erp") == "08 erp.png"


def test_banco_por_linha_casa_sicoob_pelos_digitos_e_inter_pelo_apelido():
    contas = [ALFA, BETA, ps.ContaDaProva(10, "X", ps.INTER, motivo="m")]
    lidas = ps.banco_por_linha(contas, {"123456": _l("1.00")}, {"BETA": _l("2.00")})
    assert lidas == {8: _l("1.00"), 9: _l("2.00")}


def _cenario():
    rows = [ModelRow(8, "ALFA SICOOB", erp_name="ALFA SICOOB"),
            ModelRow(9, "BETA INTER", erp_name="BETA INTER"),
            ModelRow(10, "GAMA CAIXA", erp_name="GAMA CAIXA"),
            ModelRow(11, "DELTA INTER", erp_name="DELTA INTER")]
    contas_erp = [ErpAccount("u-8", "ALFA SICOOB", balance=D("1")),
                  ErpAccount("u-9", "BETA INTER", account_number="12345-67", balance=D("2")),
                  ErpAccount("u-10", "GAMA CAIXA", balance=D("3")),
                  ErpAccount("u-11", "DELTA INTER", balance=D("4"))]
    mapa = _Mapa(rows)
    linhas = sd.montar_saldos(contas_erp, mapa)
    mapa_mc = _MapaMc({"ALFA SICOOB": NS(banco="SICOOB", empresa="ALFA"),
                       "BETA INTER": NS(banco="077", empresa="EMPRESA BETA"),
                       "GAMA CAIXA": NS(banco="CAIXA", empresa="GAMA"),
                       "DELTA INTER": NS(banco="INTER", empresa="EMPRESA DELTA")})
    empresas = [NS(nome="EMPRESA BETA", razao_social="EMPRESA BETA FICTICIA LTDA")]
    return linhas, contas_erp, mapa, mapa_mc, empresas


def _sicoob_do_painel(monkeypatch, *contas):
    """Como o de verdade: UMA `ContaDoPainel` por linha, na ordem (as que o
    teste não deu entram como "não é do Sicoob")."""
    def do_painel(linhas, *a):
        linhas = list(linhas)
        return list(contas) + [ss.ContaDoPainel(ln.rotulo) for ln in linhas[len(contas):]]
    monkeypatch.setattr(ps.ss, "contas_do_painel", do_painel)


def test_contas_da_prova_so_sicoob_e_inter_com_o_que_cada_uma_precisa(monkeypatch):
    linhas, contas_erp, mapa, mapa_mc, empresas = _cenario()
    _sicoob_do_painel(monkeypatch, ss.ContaDoPainel("ALFA SICOOB", numero="12.345-6"),
                      ss.ContaDoPainel("BETA INTER"), ss.ContaDoPainel("GAMA CAIXA"),
                      ss.ContaDoPainel("DELTA INTER"))
    contas = ps.contas_da_prova(linhas, contas_erp, mapa, mapa_mc, empresas,
                                [ContaInter("BETA", "EMPRESA BETA")])
    assert contas == [
        ps.ContaDaProva(8, "ALFA SICOOB", ps.SICOOB, numero="12.345-6", erp_id="u-8"),
        ps.ContaDaProva(9, "BETA INTER", ps.INTER, numero="1234567", apelido="BETA",
                        nomes=("EMPRESA BETA", "EMPRESA BETA FICTICIA LTDA"),
                        razoes=("EMPRESA BETA FICTICIA LTDA",), erp_id="u-9"),
        ps.ContaDaProva(11, "DELTA INTER", ps.INTER, nomes=("EMPRESA DELTA",),
                        erp_id="u-11", motivo=ps.INTER_FORA_DA_LISTA)]


def test_sicoob_que_o_cadastro_nao_resolve_entra_com_o_motivo(monkeypatch):
    linhas, contas_erp, mapa, mapa_mc, empresas = _cenario()
    _sicoob_do_painel(monkeypatch, ss.ContaDoPainel("ALFA SICOOB", motivo="sem convênio"))
    [alfa] = [c for c in ps.contas_da_prova(linhas, contas_erp, mapa, mapa_mc, empresas, [])
              if c.banco == ps.SICOOB]
    assert alfa.motivo == ss.PREFIXO + "sem convênio" and alfa.numero == ""


def test_inter_com_dois_logins_da_mesma_empresa_nao_escolhe(monkeypatch):
    linhas, contas_erp, mapa, mapa_mc, empresas = _cenario()
    _sicoob_do_painel(monkeypatch)
    contas = ps.contas_da_prova(linhas, contas_erp, mapa, mapa_mc, empresas,
                                [ContaInter("BETA", "EMPRESA BETA"),
                                 ContaInter("BETA 2", "EMPRESA BETA")])
    beta = next(c for c in contas if c.linha == 9)
    assert beta.motivo == ps.INTER_DOIS_LOGINS and beta.apelido == ""


def test_duas_linhas_no_mesmo_login_do_inter_nao_sao_lidas(monkeypatch):
    linhas, contas_erp, mapa, mapa_mc, empresas = _cenario()
    mapa_mc.destinos["DELTA INTER"] = NS(banco="INTER", empresa="EMPRESA BETA")
    _sicoob_do_painel(monkeypatch)
    contas = ps.contas_da_prova(linhas, contas_erp, mapa, mapa_mc, empresas,
                                [ContaInter("BETA", "EMPRESA BETA")])
    assert [c.motivo for c in contas] == [ps.INTER_REPETIDA.format(apelido="BETA")] * 2


def test_sicoob_casa_pela_linha_e_nao_pelo_rotulo(monkeypatch):
    """Revisão de dinheiro (27/10): dois rótulos iguais no painel não podem
    trocar (nem repetir) o número da conta do Sicoob de uma linha na outra."""
    linhas, contas_erp, mapa, mapa_mc, empresas = _cenario()
    linhas = [replace(ln, rotulo="MESMO NOME") if ln.linha in (8, 10) else ln
              for ln in linhas]
    _sicoob_do_painel(monkeypatch, ss.ContaDoPainel("MESMO NOME", numero="11.111-1"),
                      ss.ContaDoPainel("BETA INTER"),
                      ss.ContaDoPainel("MESMO NOME", numero="22.222-2"),
                      ss.ContaDoPainel("DELTA INTER"))
    contas = ps.contas_da_prova(linhas, contas_erp, mapa, mapa_mc, empresas, [])
    sicoob = {c.linha: c.numero for c in contas if c.banco == ps.SICOOB}
    assert sicoob == {8: "11.111-1", 10: "22.222-2"}


def test_e_inter():
    assert ps.e_inter("077") and ps.e_inter("77") and ps.e_inter("Banco Inter")
    assert not ps.e_inter("SICOOB") and not ps.e_inter("756") and not ps.e_inter("")
