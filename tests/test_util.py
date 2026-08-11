# -*- coding: utf-8 -*-
"""Utilitários compartilhados: formatos e a busca das listas."""

import util


# --------------------------------------------------------------- normalização
def test_norm_espaco_ignora_acento_caixa_e_espaco_duplo():
    assert util.norm_espaco("Morais  Participações") == "MORAIS PARTICIPACOES"
    assert util.norm_espaco("morais participacoes") == "MORAIS PARTICIPACOES"


def test_norm_espaco_e_a_mesma_dos_dois_mapas():
    """A função que escolhe a PASTA do extrato e a que julga sua VALIDADE
    precisam ser a MESMA — eram duas cópias."""
    import contas_mc
    import extrato_mc
    assert contas_mc._chave is extrato_mc._chave is util.norm_espaco


# ---------------------------------------------------------------- formatos
def test_data_api():
    assert util.data_api("05/08/2026") == "2026-08-05"
    assert util.data_api("05-08-2026") == "2026-08-05"
    assert util.data_api("5/8/2026") is None
    assert util.data_api("") is None


def test_fmt_val():
    assert util.fmt_val(7000) == "70,00"
    assert util.fmt_val(1) == "0,01"
    assert util.fmt_val(123456) == "1234,56"


def test_fmt_dur():
    assert util.fmt_dur(45) == "45 s"
    assert util.fmt_dur(187) == "3 min 07 s"
    assert util.fmt_dur(3720) == "1 h 02 min"


# ------------------------------------------------------------------ busca
def test_filtrar_acha_no_meio_do_texto():
    contas = ["MORAIS PARTICIPACOES - SUBCONTA 55696-3 - SICOOB",
              "BURITIS - INTER", "Livian Vieira"]
    assert util.filtrar(contas, "696") == [contas[0]]
    assert util.filtrar(contas, "livia") == [contas[2]]
    assert util.filtrar(contas, "inter") == [contas[1]]


def test_filtrar_ignora_acento_e_caixa():
    assert util.filtrar(["Morais Participações"], "PARTICIPACOES")
    assert util.filtrar(["MORAIS PARTICIPACOES"], "participações")


def test_filtrar_vazio_devolve_tudo():
    itens = ["a", "b"]
    assert util.filtrar(itens, "") == itens
    assert util.filtrar(itens, "   ") == itens


def test_filtrar_sem_resultado_devolve_lista_vazia():
    assert util.filtrar(["BURITIS"], "zzz") == []
