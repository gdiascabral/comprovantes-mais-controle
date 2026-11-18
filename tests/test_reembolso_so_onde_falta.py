"""Reembolso dos sócios só sai das contas que precisam de aporte (dono,
18/11/2026): "na hora que eu desmarcar a caixa de seleção, tirar somente das
contas em que precisam de aporte. As que tiverem dinheiro suficiente para
pagar as contas do dia e os reembolsos, essas não precisam tirar."

Nomes fictícios: o repositório é público.
"""
from decimal import Decimal
from types import SimpleNamespace

from tela_do_dia import aportes as ap
from tela_do_dia import conferencia as cf
from tela_do_dia import geracao

D = Decimal


def _linha(ident, nome="", reembolso=False, valor=10.0):
    return SimpleNamespace(id=ident, reembolso=reembolso, reembolso_nome=nome,
                           favorecido="LOJA", valor=valor)


def _grupo(conta, *linhas):
    return SimpleNamespace(conta=conta, entram=list(linhas), nao_aptos=[])


ROTULOS = {"ERP A": "Conta A", "ERP B": "Conta B"}


def test_so_sai_da_conta_que_precisa_de_aporte():
    grupos = [_grupo("ERP A", _linha("1", "FULANO DE TAL", True)),
              _grupo("ERP B", _linha("2", "FULANO DE TAL", True))]
    ficam = []
    c, tirados = geracao.sem_reembolsos(
        cf.Conferencia(), grupos, ["FULANO"], ficam_nas_contas={"Conta B"},
        rotulo_da_conta=ROTULOS.get, ficam=ficam)
    assert set(c.decisoes) == {"1"}                     # só a da conta sem dinheiro
    assert c.decisoes["1"].motivo_desmarcar == geracao.MOTIVO_SEM_REEMBOLSO
    assert len(tirados) == 1
    assert len(ficam) == 1 and "Conta B tem saldo" in ficam[0]


def test_sem_a_regra_sai_de_todas_como_antes():
    grupos = [_grupo("ERP A", _linha("1", "FULANO", True)),
              _grupo("ERP B", _linha("2", "FULANO", True))]
    c, tirados = geracao.sem_reembolsos(cf.Conferencia(), grupos, ["FULANO"])
    assert set(c.decisoes) == {"1", "2"} and len(tirados) == 2


def test_conta_fora_do_painel_sai_como_antes():
    grupos = [_grupo("ERP X", _linha("9", "FULANO", True))]
    c, _ = geracao.sem_reembolsos(cf.Conferencia(), grupos, ["FULANO"],
                                  ficam_nas_contas={"Conta A", "Conta B"},
                                  rotulo_da_conta=ROTULOS.get)
    assert set(c.decisoes) == {"9"}


def test_nenhuma_conta_precisando_nada_sai():
    grupos = [_grupo("ERP A", _linha("1", "FULANO", True))]
    base = cf.Conferencia()
    c, tirados = geracao.sem_reembolsos(base, grupos, ["FULANO"], ficam_nas_contas={"Conta A"},
                                        rotulo_da_conta=ROTULOS.get)
    assert c is base and tirados == []


def _painel(*contas):
    return ap.PainelDeAportes(contas=list(contas), mae=None, alertas=[], definidos_validos={})


def test_cobre_e_o_minimo_do_cartao_3_igual_a_zero():
    cobre = ap.AporteDaConta("Cobre", saldo=D("1000"), a_pagar=D("900"))
    falta = ap.AporteDaConta("Falta", saldo=D("100"), a_pagar=D("900"))
    justo = ap.AporteDaConta("Justo", saldo=D("900"), a_pagar=D("900"))
    aporta = ap.AporteDaConta("Aporta", saldo=D("1000"), a_pagar=D("900"), sai=D("200"))
    recebe = ap.AporteDaConta("Recebe", saldo=D("100"), a_pagar=D("900"),
                              entra_a_mao=D("800"))
    sem = ap.AporteDaConta("Sem saldo", saldo=None, a_pagar=D("10"))
    saldos = [SimpleNamespace(rotulo=c.rotulo, saldo_do_dia=c.saldo)
              for c in (cobre, falta, justo, aporta, recebe, sem)]
    saldos.append(SimpleNamespace(rotulo="Fora do cartao 3", saldo_do_dia=D("1")))
    assert geracao.contas_que_cobrem(
        _painel(falta, aporta, recebe, sem), saldos) == {
            "Cobre", "Justo", "Recebe", "Fora do cartao 3"}


def test_contas_que_cobrem_com_reembolso_conta_o_reembolso_no_a_pagar(monkeypatch):
    """O painel é montado com a conferência da NUVEM: o reembolso entra no a
    pagar. Conta que só cobre SEM o reembolso precisa de aporte."""
    vistos = {}

    def por_conta(grupos, mapping, conferencia, participantes=None):
        vistos["conferencia"] = conferencia
        return ({1: SimpleNamespace(rotulo="Conta A", a_pagar=D("110")),
                 2: SimpleNamespace(rotulo="Conta B", a_pagar=D("50"))}, {})
    monkeypatch.setattr(geracao.pg, "por_conta", por_conta)
    saldos = [SimpleNamespace(rotulo="Conta A", linha=1, saldo_do_dia=D("100")),
              SimpleNamespace(rotulo="Conta B", linha=2, saldo_do_dia=D("500"))]
    dia = SimpleNamespace(aportes={}, a_mao=[], distribuicoes=[])
    nuvem = cf.Conferencia()
    cobrem = geracao.contas_que_cobrem_com_reembolso(
        [], object(), nuvem, saldos, [], dia)
    assert cobrem == {"Conta B"}
    assert vistos["conferencia"] is nuvem


def test_a_tela_passa_a_regra_para_a_caixa():
    """A caixa do cartão 2 usa as contas que precisam (frame fino, sem regra)."""
    import inspect

    from tela_do_dia import frame
    fonte = inspect.getsource(frame.TelaDoDiaFrame._sem_reembolsos)
    assert "ficam_nas_contas=cobrem" in fonte
    assert "contas_que_cobrem_com_reembolso" in inspect.getsource(
        frame.TelaDoDiaFrame._contas_que_cobrem_com_reembolso)


def test_linha_morta_ou_ignorada_no_painel_sai():
    """Revisão de dinheiro, 18/11/2026: o rótulo existe no mapping, mas a
    linha não está no painel (morta ou ignorada) — não está entre as que
    cobrem, então o reembolso sai, como antes."""
    grupos = [_grupo("ERP MORTA", _linha("5", "FULANO", True))]
    c, _ = geracao.sem_reembolsos(cf.Conferencia(), grupos, ["FULANO"],
                                  ficam_nas_contas={"Conta A"},
                                  rotulo_da_conta={"ERP MORTA": "Linha morta"}.get)
    assert set(c.decisoes) == {"5"}


def test_html_da_tela_so_tira_a_pessoa_fisica():
    """O reembolso que a conta com saldo paga continua no HTML: a tela passa
    `so_pessoa_fisica=True`, e as contas PJ do resultado voltam intactas."""
    import inspect

    from pagamentos_dia import html_pagamentos as h
    from pagamentos_dia import relatorio
    from tela_do_dia import frame
    r = relatorio.Resultado(contas={"ERP A": [{"id": "1", "valor": 10.0,
                                               "reembolso_para": "FULANO DE TAL"}]},
                            omitidos=[])
    novo, _lanc, tirados = h.tirar_reembolsos(r, [], ["FULANO"], so_pessoa_fisica=True)
    assert novo is r and tirados == []
    velho, _lanc, tirados = h.tirar_reembolsos(r, [], ["FULANO"])
    assert velho.contas == {} and len(tirados) == 1          # Remessa/Retorno: como antes
    assert "so_pessoa_fisica=True" in inspect.getsource(frame.TelaDoDiaFrame._gerar_html)


def test_mudanca_de_saldo_refaz_o_marcar_agendados():
    """Saldo digitado, Sicoob lido, aporte ou movimento à mão que mudem quem
    sai: o recálculo refaz a lista do «Marcar agendados» (revisão de
    dinheiro, 18/11/2026)."""
    import inspect

    from tela_do_dia import frame
    assert "_acompanhar_reembolsos()" in inspect.getsource(frame.TelaDoDiaFrame._recalcular)
    fonte = inspect.getsource(frame.TelaDoDiaFrame._acompanhar_reembolsos)
    assert "_remontar_para_marcar()" in fonte
    assert "_reembolsos_incluidos" in fonte


def test_desmarcar_incluido_confere_se_saiu():
    import inspect

    from tela_do_dia import frame
    fonte = inspect.getsource(frame.TelaDoDiaFrame._desmarcar)
    assert "d.desmarcado" in fonte


def test_ids_tirados_pela_caixa():
    grupos = [_grupo("ERP A", _linha("1", "FULANO", True)),
              _grupo("ERP B", _linha("2", "FULANO", True))]
    c, _ = geracao.sem_reembolsos(cf.Conferencia(), grupos, ["FULANO"])
    assert geracao.ids_tirados_pela_caixa(c) == {"1", "2"}
    assert geracao.ids_tirados_pela_caixa(cf.Conferencia()) == frozenset()


def test_conta_ignorada_pelo_painel_nao_tem_rotulo_que_cobre():
    import inspect

    from tela_do_dia import frame
    assert "is_ignored" in inspect.getsource(frame.TelaDoDiaFrame._rotulo_que_cobre)
    assert "rotulo_da_conta=self._rotulo_que_cobre" in inspect.getsource(
        frame.TelaDoDiaFrame._sem_reembolsos)
