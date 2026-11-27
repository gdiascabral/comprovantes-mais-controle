# -*- coding: utf-8 -*-
"""A estrutura da leitura das 07:30, lida da migration (sem Postgres — o mesmo
jeito de `test_pagamento_api_sql.py`). O comportamento se prova no banco com o
roteiro begin; ...; rollback; da Task 7, depois de aplicar."""
import re
from pathlib import Path

_SQL = (Path(__file__).resolve().parent.parent / "supabase" / "migrations"
        / "20261127100000_leitura_da_manha.sql")
TABELAS = ("saldo_lido", "extrato_lido", "pre_marca_banco", "leitura_rodada")


def _texto() -> str:
    sql = re.sub(r"--[^\n]*", " ", _SQL.read_text(encoding="utf-8"))
    return " ".join(sql.split()).lower()


def test_cria_as_tabelas_com_rls_e_so_o_robo_grava():
    t = _texto()
    for nome in TABELAS:
        assert f"create table if not exists public.{nome} (" in t
        assert f"alter table public.{nome} enable row level security" in t
        assert (f"create policy {nome}_le on public.{nome} for select to authenticated "
                "using ((select privado.e_ativo()))") in t
        assert (f"create policy {nome}_grava on public.{nome} for insert to authenticated with check ( "
                "(select privado.e_ativo()) and (select privado.tem_papel('robo')) "
                "and quem = (select auth.uid()))") in t


def test_ninguem_altera_nem_apaga():
    t = _texto()
    assert ("grant select, insert on table public.saldo_lido, public.extrato_lido, "
            "public.pre_marca_banco, public.leitura_rodada to authenticated") in t
    assert ("revoke all on table public.saldo_lido, public.extrato_lido, public.pre_marca_banco, "
            "public.leitura_rodada from anon, authenticated") in t
    assert not re.search(r"grant[^;]*\b(update|delete|truncate)\b", t)
    assert "for update" not in t and "for delete" not in t


def test_saldo_nao_lido_nunca_vira_zero_no_banco():
    t = _texto()
    assert "valor numeric(14,2)," in t           # sem not null e sem default 0
    assert "constraint saldo_lido_nao_lido_tem_motivo check ((valor is null) = (length(trim(motivo)) > 0))" in t
    assert "default 0" not in t.split("create table if not exists public.saldo_lido")[1].split(");")[0]


def test_pre_marca_nao_e_resposta():
    t = _texto()
    assert "agendado_id bigint not null references public.pagamento_agendado (id)" in t
    assert "agendado_resposta" not in t


def test_linha_ilegivel_tem_motivo_e_fonte_conhecida():
    t = _texto()
    assert "check (coalesce(ilegiveis,0) = 0 or length(trim(motivo)) > 0)" in t
    assert "check (fonte in ('sicoob', 'inter', 'erp'))" in t


def test_transacao_e_recarga_do_esquema():
    t = _texto()
    assert t.startswith("begin;") and t.rstrip().endswith("commit;")
    assert "notify pgrst, 'reload schema'" in t


def test_extrato_nao_lido_nunca_vira_zero_no_banco():
    t = _texto()
    ex = t.split("create table if not exists public.extrato_lido")[1].split(");")[0]
    assert "lido boolean not null," in ex
    for coluna in ("saidas", "entradas", "ilegiveis", "fora_do_dia"):
        assert f"{coluna} integer," in ex           # anulável, sem default 0
    assert "default 0" not in ex
    assert ("constraint extrato_lido_nao_lido check ((lido and saidas is not null "
            "and entradas is not null and ilegiveis is not null and fora_do_dia is not null) "
            "or (not lido and saidas is null and entradas is null and ilegiveis is null "
            "and fora_do_dia is null and length(trim(motivo)) > 0))") in t
    assert "check (coalesce(ilegiveis,0) = 0 or length(trim(motivo)) > 0)" in t


def test_uma_linha_por_rodada_e_indices():
    t = _texto()
    for ddl in (
        "create unique index if not exists saldo_lido_uma_por_rodada on public.saldo_lido (rodada, conta, fonte);",
        "create unique index if not exists extrato_lido_um_por_rodada on public.extrato_lido (rodada, conta, fonte, dia_extrato);",
        "create unique index if not exists pre_marca_banco_uma_por_rodada on public.pre_marca_banco (rodada, agendado_id);",
        "create index if not exists extrato_lido_conta_idx on public.extrato_lido (conta, fonte, dia_extrato desc);",
    ):
        assert ddl in t
    assert "ignore-duplicates" not in t


def test_leitura_rodada_marca_a_rodada_completa():
    t = _texto()
    rd = t.split("create table if not exists public.leitura_rodada (")[1].split(");")[0]
    for coluna in ("rodada uuid primary key", "dia date not null", "dia_extrato date not null",
                   "completa boolean not null", "marcas_puladas boolean not null",
                   "contas integer not null",
                   "quem uuid not null default auth.uid() references auth.users (id)",
                   "quando timestamptz not null default now()"):
        assert coluna in rd
    assert "default privado.hoje()" not in rd      # o app manda o dia (F7)


def test_comentario_manda_ler_a_ultima_rodada_completa():
    bruto = _SQL.read_text(encoding="utf-8").lower()
    assert "última rodada completa" in bruto and "leitura_rodada.completa" in bruto
