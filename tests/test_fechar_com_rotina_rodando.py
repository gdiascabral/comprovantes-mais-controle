"""Fechar a janela com uma rotina rodando pergunta antes (19/11/2026)."""
import ast
from pathlib import Path

import util

RAIZ = Path(__file__).resolve().parents[1]


def test_sem_rotina_rodando_nao_ha_pergunta():
    assert util.pergunta_ao_fechar("") == "" and util.pergunta_ao_fechar(None) == ""


def test_a_pergunta_diz_o_que_esta_rodando_e_manda_conferir_no_erp():
    texto = util.pergunta_ao_fechar("Aportes — lançar")
    assert "Aportes — lançar" in texto and "confira no ERP" in texto
    assert texto.rstrip().endswith("Fechar mesmo assim?")


def _sair():
    arvore = ast.parse((RAIZ / "comprovantes_app.py").read_text(encoding="utf-8"))
    return next(n for n in ast.walk(arvore)
                if isinstance(n, ast.FunctionDef) and n.name == "_sair")


def test_o_sair_pergunta_antes_de_fechar_qualquer_aba():
    sair = _sair()
    linhas = {}
    for no in ast.walk(sair):
        if isinstance(no, ast.Attribute) and no.attr in ("pergunta_ao_fechar", "askyesno",
                                                         "destroy"):
            linhas.setdefault(no.attr, no.lineno)
        if isinstance(no, ast.For):
            linhas.setdefault("laco", no.lineno)
    assert linhas["pergunta_ao_fechar"] < linhas["askyesno"] < linhas["laco"] < linhas["destroy"]


def test_o_padrao_da_pergunta_e_nao():
    chamada = next(n for n in ast.walk(_sair()) if isinstance(n, ast.Call)
                   and isinstance(n.func, ast.Attribute) and n.func.attr == "askyesno")
    padrao = {k.arg: getattr(k.value, "value", None) for k in chamada.keywords}
    assert padrao.get("default") == "no"
