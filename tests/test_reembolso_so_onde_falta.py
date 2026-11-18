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
        cf.Conferencia(), grupos, ["FULANO"], so_nas_contas={"Conta A"},
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
                                  so_nas_contas=set(), rotulo_da_conta=ROTULOS.get)
    assert set(c.decisoes) == {"9"}


def test_nenhuma_conta_precisando_nada_sai():
    grupos = [_grupo("ERP A", _linha("1", "FULANO", True))]
    base = cf.Conferencia()
    c, tirados = geracao.sem_reembolsos(base, grupos, ["FULANO"], so_nas_contas=set(),
                                        rotulo_da_conta=ROTULOS.get)
    assert c is base and tirados == []


def _painel(*contas):
    return ap.PainelDeAportes(contas=list(contas), mae=None, alertas=[], definidos_validos={})


def test_precisa_de_aporte_e_o_minimo_do_cartao_3():
    cobre = ap.AporteDaConta("Cobre", saldo=D("1000"), a_pagar=D("900"))
    falta = ap.AporteDaConta("Falta", saldo=D("100"), a_pagar=D("900"))
    justo = ap.AporteDaConta("Justo", saldo=D("900"), a_pagar=D("900"))
    aporta = ap.AporteDaConta("Aporta", saldo=D("1000"), a_pagar=D("900"), sai=D("200"))
    recebe = ap.AporteDaConta("Recebe", saldo=D("100"), a_pagar=D("900"),
                              entra_a_mao=D("800"))
    sem = ap.AporteDaConta("Sem saldo", saldo=None, a_pagar=D("10"))
    assert geracao.contas_que_precisam_de_aporte(
        _painel(cobre, falta, justo, aporta, recebe, sem)) == {"Falta", "Aporta", "Sem saldo"}


def test_contas_que_precisam_com_reembolso_conta_o_reembolso_no_a_pagar(monkeypatch):
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
    precisam = geracao.contas_que_precisam_com_reembolso(
        [], object(), nuvem, saldos, [], dia)
    assert precisam == {"Conta A"}
    assert vistos["conferencia"] is nuvem


def test_a_tela_passa_a_regra_para_a_caixa():
    """A caixa do cartão 2 usa as contas que precisam (frame fino, sem regra)."""
    import inspect

    from tela_do_dia import frame
    fonte = inspect.getsource(frame.TelaDoDiaFrame._sem_reembolsos)
    assert "so_nas_contas=precisam" in fonte
    assert "contas_que_precisam_com_reembolso" in inspect.getsource(
        frame.TelaDoDiaFrame._contas_que_precisam_com_reembolso)
