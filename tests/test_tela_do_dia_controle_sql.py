# -*- coding: utf-8 -*-
"""A migration do Controle de aportes, lida como texto (sem Postgres).

Ler: quem tem conta liberada. Escrever: só administrador ativo — abertura e
proporção decidem quem deve dinheiro a quem."""
import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_SQL = _RAIZ / "supabase" / "migrations" / "20261022130000_controle_de_aportes.sql"
_TABELAS = ("controle_aporte_conta", "controle_aporte_aportador",
            "controle_aporte_atribuicao")


def _comandos() -> list[str]:
    texto = re.sub(r"\$\$.*?\$\$", " CORPO ", _SQL.read_text(encoding="utf-8"), flags=re.S)
    texto = re.sub(r"--[^\n]*", " ", texto)
    return [" ".join(c.split()).lower() for c in texto.split(";") if c.strip()]


def test_as_tres_tabelas_tem_rls():
    cmds = _comandos()
    for t in _TABELAS:
        assert f"alter table public.{t} enable row level security" in cmds


def test_le_quem_esta_liberado_e_escreve_so_o_admin():
    pols = [c for c in _comandos() if c.startswith("create policy")]
    for t in _TABELAS:
        deles = [c for c in pols if f" on public.{t} " in f"{c} "]
        assert any(" for select " in c for c in deles), t
        for c in deles:
            assert "privado.e_ativo()" in c, c
            if " for select " not in c:
                assert "privado.e_admin()" in c, c
        assert {v for v in ("insert", "update")
                if any(f" for {v} " in c for c in deles)} == {"insert", "update"}


def test_a_api_so_ganha_o_que_a_tela_usa():
    cmds = _comandos()
    assert any(c.startswith("revoke all on table public.controle_aporte_conta")
               and "anon" in c and "authenticated" in c for c in cmds)
    for c in cmds:
        if c.startswith("grant "):
            assert " all " not in f" {c} " and "anon" not in c, c
    # A conta não se apaga pelo app (só pelo painel): levaria os apontamentos.
    assert not any(c.startswith("grant") and "delete" in c
                   and "public.controle_aporte_conta to" in c for c in cmds)
    assert "using (true)" not in " ".join(cmds)


def test_estrutura_so_sem_dado():
    """Os nomes reais e a abertura vão pelo arquivo da raiz, fora do repositório."""
    assert "insert into" not in _SQL.read_text(encoding="utf-8").lower()
