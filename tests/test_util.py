# -*- coding: utf-8 -*-
"""Utilitários compartilhados: formatos e a busca das listas."""

import sys
from pathlib import Path

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


# ------------------------------------------------------ perfil do Chrome
#
# `pasta_do_perfil` existia em DOIS jeitos — ao lado do módulo (mudava
# conforme script ou exe) e na pasta base (sempre o mesmo lugar) — e o
# primeiro fazia nascer um segundo conjunto de perfis, 219 MB, dentro do
# repositório. Estes testes fixam a garantia que sobrou: a pasta nunca
# depende de ONDE o módulo que chamou mora, só de `pasta_base()`; e o NOME
# de cada perfil já instalado (ao lado do exe, em toda máquina) não muda —
# mudar um faria o app pedir login de novo.

def test_pasta_do_perfil_segue_pasta_base_congelado(monkeypatch, tmp_path):
    """Congelado, a pasta do perfil é a do .exe — nunca a do módulo que
    chamou (que nem existe mais como pasta própria dentro do exe)."""
    exe = tmp_path / "Comprovantes Mais Controle.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    esperado = Path(str(exe)).resolve().parent
    assert util.pasta_base() == esperado
    assert util.pasta_do_perfil("sicoob") == esperado / ".chrome_profile_sicoob"


def test_pasta_do_perfil_segue_pasta_base_como_script(monkeypatch):
    """Sem `sys.frozen`, a pasta do perfil é a raiz do projeto
    (`pasta_base()`) — nunca a subpasta de quem chamou (`anexar/`,
    `aportes/`...). Era essa divergência que fazia nascer um SEGUNDO
    conjunto de perfis dentro do repositório ao rodar como script."""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert util.pasta_do_perfil("sicoob") == util.pasta_base() / ".chrome_profile_sicoob"
    # Em especial: não é a pasta de nenhuma subpasta de módulo.
    assert util.pasta_do_perfil("sicoob").parent != (
        util.pasta_base() / "extratos_sicoob")


def test_pasta_do_perfil_mantem_os_nomes_ja_instalados():
    """Os nomes que já existem ao lado do exe em produção, byte a byte —
    trocar qualquer um faria o app pedir login de novo em toda máquina."""
    casos = {
        "": ".chrome_profile",                         # anexar/
        "acessorias": ".chrome_profile_acessorias",     # acessorias/
        "sicoob": ".chrome_profile_sicoob",              # extratos_sicoob/
        "conferencia": ".chrome_profile_conferencia",    # aportes/conferir_contas.py
        "teste": ".chrome_profile_teste",                # aportes/teste_lancamento.py
        # o Inter delega f"inter_{conta}" (ou "inter_conta" se a conta vier
        # vazia) — conferido aqui como o nome final bate com o de antes.
        "inter_EMPRESA-X": ".chrome_profile_inter_EMPRESA-X",
        "inter_conta": ".chrome_profile_inter_conta",
    }
    for nome, esperado in casos.items():
        assert util.pasta_do_perfil(nome).name == esperado


def test_pasta_do_perfil_limpa_caracteres_e_corta_em_40():
    p = util.pasta_do_perfil("MORAIS ENG / 50022 \\ PIX")
    assert "/" not in p.name and "\\" not in p.name
    assert p.name == ".chrome_profile_MORAIS_ENG_50022_PIX"

    nome_longo = "A" * 60
    cortado = util.pasta_do_perfil(nome_longo).name
    # ".chrome_profile_" (17) + 40 caracteres limpos.
    assert cortado == ".chrome_profile_" + "A" * 40
