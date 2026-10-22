"""A lista do diretor: só o agendado, nome curto, ordinais e a ordem de ontem."""
from decimal import Decimal as D
from types import SimpleNamespace

from tela_do_dia import lista_diretor as ld
from tela_do_dia.valores import brl


def _ag(conta, valor):
    return SimpleNamespace(conta=conta, valor=D(valor))


def test_soma_por_conta_com_nome_curto():
    linhas = ld.montar([_ag("ERP A", "10.00"), _ag("ERP A", "5.00"), _ag("ERP B", "7.00")],
                       {"ERP A": "Conta Alfa - Banco", "ERP B": "Conta Beta - Banco"}.get,
                       {"Conta Alfa - Banco": "Alfa - Banco"})
    assert [(l.nome, l.valor) for l in linhas] == [("Alfa - Banco", D("15.00")),
                                                   ("Conta Beta - Banco", D("7.00"))]


def test_conta_sem_rotulo_usa_o_proprio_nome():
    linhas = ld.montar([_ag("ERP X", "1.00")], lambda c: None, {})
    assert [(l.rotulo, l.nome) for l in linhas] == [("ERP X", "ERP X")]


def test_ordem_de_ontem_sugere_ordinais_e_demais():
    linhas = [ld.LinhaDaLista(r, r, D(v)) for r, v in (("A", "1"), ("B", "9"), ("C", "5"), ("D", "3"))]
    anterior = [{"conta": "C", "ordinal": 1}, {"conta": "A", "ordinal": 2}, {"conta": "D", "ordinal": None}]
    sug = ld.sugerir_ordem(linhas, anterior)
    assert [(l.rotulo, l.ordinal) for l in sug] == [("C", 1), ("A", 2), ("D", None), ("B", None)]


def test_sem_ordem_de_ontem_nada_e_numerado():
    linhas = [ld.LinhaDaLista("A", "A", D("1")), ld.LinhaDaLista("B", "B", D("9"))]
    sug = ld.sugerir_ordem(linhas, [])
    assert [(l.rotulo, l.ordinal) for l in sug] == [("B", None), ("A", None)]


def test_texto_do_whatsapp():
    linhas = [ld.LinhaDaLista("A", "Alfa - Banco", D("30500"), 1),
              ld.LinhaDaLista("B", "Beta - Banco", D("3760.36"), 2),
              ld.LinhaDaLista("C", "Gama - Banco", D("5028.84"))]
    assert ld.texto_whatsapp(linhas) == (f"1º Alfa - Banco — {brl(D('30500'))}\n"
                                         f"2º Beta - Banco — {brl(D('3760.36'))}\n"
                                         f"Demais:\nGama - Banco — {brl(D('5028.84'))}")
    assert ld.texto_whatsapp(linhas[2:]) == f"Gama - Banco — {brl(D('5028.84'))}"


def test_mover_e_alternar_renumeram():
    linhas = [ld.LinhaDaLista("A", "A", D("1"), 1), ld.LinhaDaLista("B", "B", D("1"), 2),
              ld.LinhaDaLista("C", "C", D("1"))]
    linhas = ld.mover(linhas, 1, -1)
    assert [(l.rotulo, l.ordinal) for l in linhas] == [("B", 1), ("A", 2), ("C", None)]
    linhas = ld.alternar_ordinal(linhas, 2)
    assert [(l.rotulo, l.ordinal) for l in linhas] == [("B", 1), ("A", 2), ("C", 3)]
    assert ld.para_nuvem(linhas)[0] == {"conta": "B", "ordinal": 1}
    assert ld.validar_nome_curto("") and ld.validar_nome_curto("x" * 61) and not ld.validar_nome_curto("Alfa")
