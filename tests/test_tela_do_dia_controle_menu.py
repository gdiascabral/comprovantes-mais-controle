# -*- coding: utf-8 -*-
"""A aba Controle de aportes no menu: fim do DIÁRIO, sem o aprovador. Por AST."""
import ast
from pathlib import Path

from nuvem import usuarios

_APP = Path(__file__).resolve().parents[1] / "comprovantes_app.py"


def _grupos() -> dict:
    saida = {}
    for no in ast.walk(ast.parse(_APP.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Call) and getattr(no.func, "id", "") == "_grupo":
            saida[ast.literal_eval(no.args[0])] = ast.literal_eval(no.args[2])
    return saida


def test_controle_de_aportes_fica_no_fim_do_diario():
    assert [c for c, _i, _t in _grupos()["diario"]] == ["dia", "pag", "con", "cap"]
    assert ("cap", "🤝", "Controle de aportes") in _grupos()["diario"]


def test_o_app_monta_liga_e_libera_so_para_admin():
    fonte = _APP.read_text(encoding="utf-8")
    assert "aba_cap = ControleAportesFrame(conteudo, aba_anx)" in fonte
    assert "aba_cap.liberar_edicao(_eu.admin)" in fonte
    assert '"cap": aba_cap' in fonte


def test_aprovador_nao_ve_e_operador_ve():
    assert "cap" not in usuarios.abas_do_papel("aprovador", ["ini", "pag", "cap"])
    assert "cap" in usuarios.abas_do_papel("operador", ["cap"])


def test_nenhum_atalho_ctrl_1_a_9_existente_muda():
    """A ordem do menu é a ordem dos atalhos: a nova tela é a 10ª (só Ctrl+Tab)."""
    antes = ["ini", "bxc", "sep", "anx", "conf", "apt", "dia", "pag", "con"]
    ordem = ["ini", "bxc", "sep", "anx", "conf", "apt"] + [
        c for c, _i, _t in _grupos()["diario"]]
    assert ordem[:9] == antes
    assert ordem[9] == "cap"


def test_icone_novo_esta_nas_duas_tabelas_com_codepoint_unico():
    import widgets
    for tabela in (widgets.ICONES_FLUENT, widgets.ICONES_MDL2):
        assert tabela["🤝"] == "\uE716"
        assert list(tabela.values()).count("\uE716") == 1
