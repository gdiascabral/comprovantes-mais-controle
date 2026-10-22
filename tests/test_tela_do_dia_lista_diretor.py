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


def test_sem_nome_curto_e_conta_sem_rotulo():
    linhas = ld.montar([_ag("ERP A", "1.00"), _ag("ERP B", "1.00")], lambda c: c, {"ERP A": "Alfa"})
    assert [(l.nome, l.sem_nome_curto) for l in linhas] == [("Alfa", False), ("ERP B", True)]
    import pytest
    with pytest.raises(ValueError):
        ld.montar([_ag(None, "1.00")], lambda c: None, {})


def test_valor_zero_ou_none_nao_vira_linha_e_soma_exata():
    ags = [_ag("A", "0.10"), _ag("A", "0.20"), _ag("B", "0"), SimpleNamespace(conta="C", valor=None)]
    linhas = ld.montar(ags, lambda c: c, {})
    assert [(l.rotulo, l.valor) for l in linhas] == [("A", D("0.30"))]
    assert ld.texto_whatsapp(linhas) == "A — R$ 0,30"


def test_mesmo_rotulo_soma_numa_linha():
    linhas = ld.montar([_ag("E1", "1.00"), _ag("E2", "2.00")], lambda c: "X", {})
    assert [(l.rotulo, l.valor) for l in linhas] == [("X", D("3.00"))]


def test_texto_literal():
    l = [ld.LinhaDaLista("A", "Alfa - Banco", D("30500"), 1)]
    assert ld.texto_whatsapp(l) == "1º Alfa - Banco — R$ 30.500,00"


def test_nada_muda_no_lugar():
    orig = [ld.LinhaDaLista("A", "A", D("1"), 2), ld.LinhaDaLista("B", "B", D("2"), 1), ld.LinhaDaLista("C", "C", D("3"))]
    copia = [(l.rotulo, l.ordinal) for l in orig]
    ld.renumerar(orig)
    ld.sugerir_ordem(orig, [{"conta": "C", "ordinal": 1}])
    ld.alternar_ordinal(orig, 2)
    ld.mover(orig, 0, 1)
    assert [(l.rotulo, l.ordinal) for l in orig] == copia


def test_alternar_poe_no_fim_de_qualquer_ordem():
    linhas = [ld.LinhaDaLista("A", "A", D("1"), 1), ld.LinhaDaLista("B", "B", D("1")),
              ld.LinhaDaLista("C", "C", D("1"), 2)]
    r = ld.alternar_ordinal(linhas, 1)
    assert [(l.rotulo, l.ordinal) for l in r] == [("A", 1), ("C", 2), ("B", 3)]


def test_anterior_com_string_duplicado_e_conta_nova():
    linhas = [ld.LinhaDaLista(r, r, D("1")) for r in ("A", "B", "N")]
    anterior = [{"conta": "B", "ordinal": "1"}, {"conta": "A", "ordinal": "2"},
                {"conta": "A", "ordinal": "1"}, {"conta": "B", "ordinal": "x"}]
    sug = ld.sugerir_ordem(linhas, anterior)
    assert [(l.rotulo, l.ordinal) for l in sug] == [("B", 1), ("A", 2), ("N", None)]


def test_mover_nos_limites():
    linhas = [ld.LinhaDaLista("A", "A", D("1"), 1), ld.LinhaDaLista("B", "B", D("1"))]
    assert [l.rotulo for l in ld.mover(linhas, 0, -1)] == ["A", "B"]
    assert [l.rotulo for l in ld.mover(linhas, 1, 1)] == ["A", "B"]
