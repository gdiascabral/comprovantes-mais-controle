"""A lista do diretor: só o agendado, nome curto, ordinais e a ordem de ontem."""
from decimal import Decimal as D
from types import SimpleNamespace

import pytest

from tela_do_dia import lista_diretor as ld
from tela_do_dia.valores import brl


def _ag(conta, valor):
    return SimpleNamespace(conta=conta, valor=D(valor))


def test_soma_por_conta_com_nome_curto():
    linhas = ld.montar([_ag("ERP A", "10.00"), _ag("ERP A", "5.00"), _ag("ERP B", "7.00")],
                       {"ERP A": "Conta Alfa - Banco", "ERP B": "Conta Beta - Banco"}.get,
                       {"Conta Alfa - Banco": "Alfa - Banco"})
    assert [(l.nome, l.valor, l.sugerido) for l in linhas] == [
        ("Alfa - Banco", D("15.00"), False), ("Conta Beta Banco", D("7.00"), True)]


def test_conta_sem_rotulo_usa_o_proprio_nome():
    linhas = ld.montar([_ag("ERP X", "1.00")], lambda c: None, {})
    assert [(l.rotulo, l.nome) for l in linhas] == [("ERP X", "Erp X")]


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
    """Conta sem nome curto gravado nasce com a SUGESTÃO (marcada), não
    bloqueia a cópia."""
    linhas = ld.montar([_ag("ERP A", "1.00"), _ag("ERP B", "1.00")], lambda c: c, {"ERP A": "Alfa"})
    assert [(l.nome, l.sem_nome_curto, l.sugerido) for l in linhas] == [
        ("Alfa", False, False), ("Erp B", False, True)]
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


def test_empate_de_ordinal_de_ontem_desempata_pela_posicao_de_ontem():
    """Duas contas com o MESMO ordinal ontem: vale quem vinha antes na lista
    de ontem — nem a ordem de hoje, nem o valor."""
    linhas = [ld.LinhaDaLista("A", "A", D("900")), ld.LinhaDaLista("B", "B", D("1"))]
    anterior = [{"conta": "B", "ordinal": 1}, {"conta": "A", "ordinal": 1}]
    sug = ld.sugerir_ordem(linhas, anterior)
    assert [(l.rotulo, l.ordinal) for l in sug] == [("B", 1), ("A", 2)]


def test_conta_cujo_unico_ordinal_de_ontem_e_invalido_fica_sem_ordinal():
    linhas = [ld.LinhaDaLista(r, r, D("1")) for r in ("A", "B", "C", "E")]
    anterior = [{"conta": "A", "ordinal": "x"}, {"conta": "B", "ordinal": 1},
                {"conta": "C", "ordinal": 0}, {"conta": "E", "ordinal": -2}]
    sug = ld.sugerir_ordem(linhas, anterior)
    assert [(l.rotulo, l.ordinal) for l in sug] == [("B", 1), ("A", None), ("C", None),
                                                    ("E", None)]


# ------------------------------------------------- nome curto sugerido (E)
# Nomes FICTÍCIOS, no formato dos rótulos reais do painel.
MESMO_BANCO = [
    "EMPRESA ALFA PARTICIPAÇÕES - SUBCONTA 12345-6 - SICOOB",
    "Obra Beta Sicoob",
    "EMPRESA GAMA SPE LTDA - 20001-1 - SICOOB",
    "EMPRESA ALFA ENGENHARIA - Sicoob",
    "Empresa Alfa Incorporações Delta 20002-2 - Sicoob",
    "Empresa Alfa Participações - MÃE - 20.003-3 - SICOOB",
    "EMPRESA DELTA EMPREENDIMENTOS CIDADE MODELO SPE I LTDA - 20004-4 - SICOOB",
    "Empresa Alfa Part. Subconta 20005-5 TB 7 QD 3 LT 2 Sicoob",
    "Empresa Alfa Participações - SUBCONTA 20006-6 - QRS PARTICIPACOES LTDA - SICOOB",
    "Obra Modelo das Ficções Sicoob",
    "EMPRESA ÉPSILON S/A - SICOOB",
]


@pytest.mark.parametrize("conta, esperado", [
    ("EMPRESA ALFA PARTICIPAÇÕES - SUBCONTA 12345-6 - SICOOB", "Empresa Alfa Part. Sub. 12345"),
    ("Obra Beta Sicoob", "Obra Beta"),
    ("EMPRESA GAMA SPE LTDA - 20001-1 - SICOOB", "Empresa Gama"),
    ("EMPRESA ALFA ENGENHARIA - Sicoob", "Empresa Alfa Eng."),
    ("Empresa Alfa Incorporações Delta 20002-2 - Sicoob", "Empresa Alfa Incorp. Delta"),
    ("Empresa Alfa Participações - MÃE - 20.003-3 - SICOOB", "Empresa Alfa Part. Mãe"),
    ("EMPRESA DELTA EMPREENDIMENTOS CIDADE MODELO SPE I LTDA - 20004-4 - SICOOB",
     "Empresa Delta Empreend. Cidade Modelo"),
    ("Empresa Alfa Part. Subconta 20005-5 TB 7 QD 3 LT 2 Sicoob",
     "Empresa Alfa Part. Sub. 20005 TB 7 QD 3 LT 2"),
    ("Empresa Alfa Participações - SUBCONTA 20006-6 - QRS PARTICIPACOES LTDA - SICOOB",
     "Empresa Alfa Part. Sub. 20006 QRS Part."),
    ("Obra Modelo das Ficções Sicoob", "Obra Modelo das Ficções"),
    ("EMPRESA ÉPSILON S/A - SICOOB", "Empresa Épsilon"),
])
def test_sugere_nome_curto_com_a_lista_toda_do_mesmo_banco(conta, esperado):
    assert ld.sugerir_nome_curto(conta, MESMO_BANCO) == esperado


def test_bancos_misturados_deixam_o_banco_curto_no_fim():
    todas = ["Obra Beta - Inter", "Obra Beta Sicoob", "OBRA ZETA - SICOOB - 30001-1"]
    assert [ld.sugerir_nome_curto(c, todas) for c in todas] == [
        "Obra Beta - Inter", "Obra Beta - Sicoob", "Obra Zeta - Sicoob"]


def test_mesmo_nome_desempata_pelo_numero_da_conta():
    todas = ["Familia Teta 30001-1 - Sicoob", "Familia Teta 30002-2 - Sicoob",
             "Familia Teta 30003-3 - Sicoob", "Obra Beta Sicoob"]
    assert [ld.sugerir_nome_curto(c, todas) for c in todas] == [
        "Familia Teta 30001", "Familia Teta 30002", "Familia Teta 30003", "Obra Beta"]


def test_sugestoes_sao_unicas_mesmo_sem_numero_para_desempatar():
    todas = ["Obra Beta Sicoob", "OBRA BETA - SICOOB", "obra beta  sicoob", "Obra Zeta Sicoob"]
    sug = ld.sugerir_nomes(todas)
    nomes = [sug[c].casefold() for c in todas]
    assert len(set(nomes)) == len(nomes)
    assert sug["Obra Zeta Sicoob"] == "Obra Zeta"
    # Determinística: a ordem da lista não muda o que cada conta recebe.
    assert ld.sugerir_nomes(list(reversed(todas))) == sug


def test_sugestao_nao_repete_nome_curto_ja_gravado_de_outra_conta():
    todas = ["Obra Beta 30001-1 Sicoob", "Obra Zeta Sicoob"]
    sug = ld.sugerir_nomes(todas, ocupados={"OBRA BETA"})
    assert sug["Obra Beta 30001-1 Sicoob"] == "Obra Beta 30001"


def test_sugestao_sempre_valida_para_gravar():
    for conta in MESMO_BANCO + ["Sicoob", "  ", "X" * 90 + " Sicoob", "- 12345-6 -"]:
        nome = ld.sugerir_nome_curto(conta, [conta])
        assert ld.validar_nome_curto(nome) == "", (conta, nome)


def test_montar_usa_a_sugestao_unica_e_nao_repete_nome_gravado():
    linhas = ld.montar([_ag("a", "1.00"), _ag("b", "2.00"), _ag("c", "3.00")],
                       {"a": "Obra Beta 30001-1 - Sicoob", "b": "Obra Beta 30002-2 - Sicoob",
                        "c": "Obra Zeta - Sicoob"}.get,
                       {"Obra Zeta - Sicoob": "Zeta"})
    assert [(l.nome, l.sugerido, l.sem_nome_curto) for l in linhas] == [
        ("Obra Beta 30001", True, False), ("Obra Beta 30002", True, False), ("Zeta", False, False)]
    assert ld.texto_whatsapp(linhas).splitlines()[0].startswith("Obra Beta 30001 — ")


# --------------- revisão geral de 22/10/2026 (achado 10): nomes feios
def _vezes_do_banco(nome: str, banco: str = "sicoob") -> int:
    return [p.strip("-.").casefold() for p in nome.split()].count(banco)


def test_banco_no_meio_do_rotulo_sai_do_nome():
    sug = ld.sugerir_nomes(["EMPRESA - SICOOB - SUBCONTA 30001-1", "Obra Beta Sicoob"])
    assert sug["EMPRESA - SICOOB - SUBCONTA 30001-1"] == "Empresa Sub. 30001"
    sug = ld.sugerir_nomes(["EMPRESA - SICOOB - SUBCONTA 30001-1", "Obra Beta - Inter"])
    assert sug["EMPRESA - SICOOB - SUBCONTA 30001-1"] == "Empresa Sub. 30001 - Sicoob"


def test_rotulo_so_de_banco_e_numero_vira_banco_e_numero_curto():
    for outras in (["Obra Beta Sicoob"], ["Obra Beta - Inter"], []):
        sug = ld.sugerir_nomes(["SICOOB 40001-1"] + outras)
        assert sug["SICOOB 40001-1"] == "Sicoob 40001", outras
    assert ld.sugerir_nomes(["40001-1 - SICOOB", "OBRA X - INTER"])["40001-1 - SICOOB"] == \
        "Sicoob 40001"


def test_nunca_o_banco_duas_vezes():
    rotulos = ["SICOOB 40001-1", "SICOOB 40002-2", "SICOOB - 40001-1",
               "EMPRESA - SICOOB - SUBCONTA 30001-1", "EMPRESA - SICOOB - SUBCONTA 30002-2",
               "Obra Beta - Inter", "Sicoob"] + MESMO_BANCO
    for nome in ld.sugerir_nomes(rotulos).values():
        assert _vezes_do_banco(nome) <= 1, nome
    for nome in ld.sugerir_nomes(MESMO_BANCO + ["SICOOB 40001-1", "SICOOB - 40001-1"]).values():
        assert _vezes_do_banco(nome) <= 1, nome


# ---- uma mensagem por conta (dono, 28/10/2026)
def test_mensagens_uma_por_conta_com_demais_na_primeira_sem_ordinal():
    from decimal import Decimal
    from tela_do_dia import lista_diretor as ldr
    linhas = [ldr.LinhaDaLista(rotulo="A", nome="Conta A", valor=Decimal("855.41"), ordinal=1),
              ldr.LinhaDaLista(rotulo="B", nome="Conta B", valor=Decimal("10"), ordinal=None),
              ldr.LinhaDaLista(rotulo="C", nome="Conta C", valor=Decimal("20.5"), ordinal=None)]
    msgs = ldr.mensagens_whatsapp(linhas)
    assert msgs == ["1º Conta A — R$ 855,41", "Demais:\nConta B — R$ 10,00",
                    "Conta C — R$ 20,50"]
    assert "\n".join(msgs) == ldr.texto_whatsapp(linhas)
    assert ldr.proxima_a_copiar(linhas, {"A"}) == 1
    assert ldr.proxima_a_copiar(linhas, {"A", "B", "C"}) is None


def test_sem_numeradas_nao_ha_demais():
    from decimal import Decimal
    from tela_do_dia import lista_diretor as ldr
    linhas = [ldr.LinhaDaLista(rotulo="B", nome="Conta B", valor=Decimal("10"), ordinal=None)]
    assert ldr.mensagens_whatsapp(linhas) == ["Conta B — R$ 10,00"]
