"""O Início sabe dar nome ao que a aba Pagamentos do dia anota. Sem janela."""
import ast
from pathlib import Path

from inicio.inicio_frame import OUTRAS_ORIGENS, ROTINAS

_RAIZ = Path(__file__).resolve().parents[1]


def _abas_anotadas(arquivo: str) -> set[str]:
    arvore = ast.parse((_RAIZ / arquivo).read_text(encoding="utf-8"))
    return {no.args[0].value for no in ast.walk(arvore)
            if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute)
            and no.func.attr == "registrar_atividade" and no.args
            and isinstance(no.args[0], ast.Constant)}


def test_toda_atividade_da_tela_do_dia_tem_nome_no_inicio():
    anotadas = _abas_anotadas("tela_do_dia/frame.py")
    assert anotadas, "a tela do dia deixou de anotar atividade: o teste não mede nada"
    conhecidas = {c for c, _n, _r in ROTINAS} | set(OUTRAS_ORIGENS)
    assert anotadas <= conhecidas


def test_pagamentos_do_dia_nao_vira_pendencia_diaria_do_inicio():
    """Em ROTINAS ela viraria "não rodou hoje" enquanto convive com as abas
    antigas; em OUTRAS_ORIGENS só ganha nome na atividade recente."""
    assert OUTRAS_ORIGENS.get("dia") == "Pagamentos do dia"
    assert "dia" not in {c for c, _n, _r in ROTINAS}
