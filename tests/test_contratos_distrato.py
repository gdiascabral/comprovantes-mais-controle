# -*- coding: utf-8 -*-
"""Comprador do contrato, grupos por comprador e a sugestao do distrato."""
from contratos import distrato as d

TEXTO_A = ("DAS PARTES ... doravante denominado VENDEDOR.\n"
           "COMPRADOR: PRIMEIRO COMPRADOR EXEMPLO, brasileiro, portador da "
           "carteira ... TB 21 QD 46 LT 18 CS 01 " + "x" * 60)
TEXTO_B = TEXTO_A.replace("PRIMEIRO", "SEGUNDO")
DISTRATO = ("TERMO DE DISTRATO entre a vendedora e PRIMEIRO COMPRADOR "
            "EXEMPLO referente a casa 01 " + "y" * 60)


def _v(nome, texto, dados=b"1"):
    return d.Versao({"filename": nome}, dados, texto)


def test_comprador_sai_do_trecho_das_partes():
    assert d.comprador_do_contrato(TEXTO_A) == "PRIMEIRO COMPRADOR EXEMPLO"
    assert d.comprador_do_contrato(
        "COMPRADORA:  Segunda   Compradora Exemplo , casada") == \
        "SEGUNDA COMPRADORA EXEMPLO"
    assert d.comprador_do_contrato("COMPRADOR(A): FULANO EXEMPLO, solteiro") \
        == "FULANO EXEMPLO"
    assert d.comprador_do_contrato("sem qualificação nenhuma") == ""


def test_agrupa_por_comprador_e_o_do_recebimento_vem_primeiro():
    a1 = _v("CCV CS 01.pdf", TEXTO_A, b"1")
    a2 = _v("CCV CS 01 ASSINADO.pdf", TEXTO_A, b"2")
    b = _v("CCV CS01.pdf", TEXTO_B, b"3")
    grupos = d.agrupar([a1, b, a2], "SEGUNDO COMPRADOR EXEMPLO")
    assert [[v.anexo["filename"] for v in g] for g in grupos] == [
        ["CCV CS01.pdf"], ["CCV CS 01.pdf", "CCV CS 01 ASSINADO.pdf"]]


def test_mesmo_comprador_fica_com_a_versao_mais_completa():
    a1 = _v("CCV CS 01.pdf", TEXTO_A, b"1")
    a2 = _v("CCV CS 01 ASSINADO.pdf", TEXTO_A, b"2")
    escolhida, _m = d.escolher([a1, a2])
    assert escolhida is a2


def test_duas_versoes_sem_marca_vao_para_revisao():
    escolhida, motivo = d.escolher([_v("X.pdf", TEXTO_A, b"1"),
                                    _v("Y.pdf", TEXTO_A, b"2")])
    assert escolhida is None
    assert "2 versões diferentes" in motivo


def test_bytes_iguais_sao_o_mesmo_contrato():
    escolhida, _m = d.escolher([_v("X.pdf", TEXTO_A, b"1"),
                                _v("Y.pdf", TEXTO_A, b"1")])
    assert escolhida.anexo["filename"] == "X.pdf"


def test_distratado_e_quem_aparece_no_distrato():
    assert d.foi_distratado("PRIMEIRO COMPRADOR EXEMPLO", [DISTRATO])
    assert not d.foi_distratado("SEGUNDO COMPRADOR EXEMPLO", [DISTRATO])
    assert not d.foi_distratado("", [DISTRATO])
    assert not d.foi_distratado("PRIMEIRO COMPRADOR EXEMPLO", [""])


def test_sem_comprador_lido_e_sem_conferir_fica_sozinho():
    sem = _v("ESCANEADO.pdf", "", b"9")
    a = _v("CCV.pdf", TEXTO_A, b"1")
    grupos = d.agrupar([sem, a], "PRIMEIRO COMPRADOR EXEMPLO")
    assert [len(g) for g in grupos] == [1, 1]
    assert grupos[0][0] is a
