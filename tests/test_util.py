# -*- coding: utf-8 -*-
"""Utilitários compartilhados: formatos e a busca das listas."""

import logging
import re
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
    from relatorios import contas_mc
    from relatorios import extrato_mc
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
    p = util.pasta_do_perfil(r"EMPRESA X / 12345 \ PIX")
    assert "/" not in p.name and "\\" not in p.name
    assert p.name == ".chrome_profile_EMPRESA_X_12345_PIX"

    nome_longo = "A" * 60
    cortado = util.pasta_do_perfil(nome_longo).name
    # ".chrome_profile_" (17) + 40 caracteres limpos.
    assert cortado == ".chrome_profile_" + "A" * 40


# --------------------------------------------------------- diagnóstico (log)
#
# `util.log()` é a BASE: um `RotatingFileHandler` só, compartilhado por todo
# `nome` que passar por `log()`. Estes testes isolam esse compartilhado num
# `tmp_path` a cada chamada — sem isso, o handler da PRIMEIRA chamada (de
# QUALQUER teste, na ordem em que o pytest os rodar) ficaria preso ao
# `pasta_base()` de então, e as chamadas seguintes o herdariam calado, em vez
# de abrir um novo no `tmp_path` do teste atual. E cada teste usa um nome de
# logger PRÓPRIO — `logging.getLogger` guarda os loggers pelo nome para o
# processo inteiro, então reaproveitar um nome herdaria o handler (já
# fechado) de um teste anterior.

def _log_isolado(monkeypatch, tmp_path):
    """Aponta `pasta_base()` para o `tmp_path` do teste e esquece o handler
    compartilhado, para a próxima chamada a `util.log()` abrir um novo ali —
    e não continuar escrevendo em qualquer lugar que um teste anterior (ou a
    própria raiz do projeto) tenha aberto primeiro."""
    monkeypatch.setattr(util, "pasta_base", lambda: tmp_path)
    monkeypatch.setattr(util, "_handler", None)


def test_log_mesmo_nome_devolve_o_mesmo_logger_com_um_so_handler(
        monkeypatch, tmp_path):
    _log_isolado(monkeypatch, tmp_path)
    a = util.log("teste_util_log_a")
    b = util.log("teste_util_log_a")
    assert a is b
    assert len(a.handlers) == 1        # a 2a chamada não acrescentou outro
    a.handlers[0].close()


def test_log_nomes_diferentes_compartilham_o_mesmo_handler(
        monkeypatch, tmp_path):
    _log_isolado(monkeypatch, tmp_path)
    a = util.log("teste_util_log_b1")
    b = util.log("teste_util_log_b2")
    assert a is not b                  # loggers diferentes, um por nome
    assert a.handlers[0] is b.handlers[0]      # mas o MESMO handler
    a.handlers[0].close()


def test_log_grava_no_diagnostico_log_com_o_prefixo_de_data_e_hora(
        monkeypatch, tmp_path):
    _log_isolado(monkeypatch, tmp_path)
    logger = util.log("teste_util_log_c")
    logger.info("mensagem de teste")
    for h in logger.handlers:
        h.flush()
        h.close()                      # senão o arquivo fica preso no Windows

    conteudo = (tmp_path / "diagnostico.log").read_text(encoding="utf-8")
    # O MESMO prefixo dd/mm/aaaa hh:mm:ss que o diagnostico.log de hoje já
    # usa — quem lê o arquivo depois desta troca não estranha essa parte.
    assert re.match(r"^\d{2}/\d{2}/\d{4} \d{2}:\d{2}:\d{2}  ", conteudo)
    assert "teste_util_log_c" in conteudo
    assert "INFO" in conteudo
    assert "mensagem de teste" in conteudo


def test_log_nao_tem_handler_de_console(monkeypatch, tmp_path):
    """O exe é `--noconsole`: um `StreamHandler` escrevendo num
    stdout/stderr que não existe derruba o app — a mesma armadilha do
    `print()` que este PR está começando a substituir."""
    _log_isolado(monkeypatch, tmp_path)
    logger = util.log("teste_util_log_d")
    assert logger.handlers                 # tem handler, e é de arquivo
    for h in logger.handlers:
        assert isinstance(h, logging.FileHandler)
        assert getattr(h, "stream", None) not in (sys.stdout, sys.stderr)
    logger.handlers[0].close()
