# -*- coding: utf-8 -*-
"""A estrutura das tabelas do dia de trabalho na nuvem, lida da migration
(sem Postgres — o mesmo jeito de `test_rls_supabase.py`)."""
import re
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
_SQL = _RAIZ / "supabase" / "migrations" / "20261022100000_pagamentos_do_dia_na_nuvem.sql"
TABELAS = ("pagamento_decisao", "pagamento_a_mao", "pagamento_agendado",
           "agendado_resposta", "lista_diretor_nome", "lista_diretor")


def _texto() -> str:
    sql = re.sub(r"--[^\n]*", " ", _SQL.read_text(encoding="utf-8"))
    return " ".join(sql.split()).lower()


def test_cria_as_seis_tabelas():
    t = _texto()
    for nome in TABELAS:
        assert f"create table if not exists public.{nome} (" in t


def test_toda_tabela_tem_rls_e_as_duas_politicas_com_a_porteira():
    t = _texto()
    for nome in TABELAS:
        assert f"alter table public.{nome} enable row level security" in t
        assert (f"create policy {nome}_le on public.{nome} for select to authenticated "
                "using ((select privado.e_ativo()))") in t
        assert (f"create policy {nome}_grava on public.{nome} for insert to authenticated "
                "with check ((select privado.e_ativo()) and quem = (select auth.uid()) "
                "and quem_nome = coalesce((select p.nome from public.perfil p "
                "where p.user_id = (select auth.uid())), ''))") in t


def test_o_app_so_le_e_acrescenta():
    t = _texto()
    for nome in TABELAS:
        assert f"revoke all on table public.{nome} from anon, authenticated" in t
        assert f"grant select, insert on table public.{nome} to authenticated" in t
    assert " for update " not in t and " for delete " not in t
    assert not re.search(r"grant [^;]*(update|delete)[^;]*to authenticated", t)


def test_quem_e_carimbado_pelo_servidor():
    assert _texto().count(
        "quem uuid not null default auth.uid() references auth.users (id)") == len(TABELAS)


def test_agendado_nao_se_repete_no_dia_e_as_respostas_sao_fechadas():
    t = _texto()
    assert ("create unique index if not exists pagamento_agendado_um_por_dia "
            "on public.pagamento_agendado (dia, alvo)") in t
    assert "check (resposta in ('pago', 'nao_saiu', 'reagendado'))" in t
    assert "check (valor > 0)" in t
    assert "check (valor_em_aberto is null or valor <= valor_em_aberto)" in t


def test_a_lista_de_abertos_respeita_a_rls():
    t = _texto()
    assert ("create or replace view public.agendado_em_aberto "
            "with (security_invoker = true)") in t
    assert "revoke all on table public.agendado_em_aberto from anon, authenticated" in t
    assert "grant select on table public.agendado_em_aberto to authenticated" in t


def test_a_api_recarrega_o_esquema_antes_de_fechar_a_transacao():
    # Achado 17: sem isto as tabelas novas demoram a aparecer na API e a tela
    # fica em "nao li a nuvem" (falha fechada).
    t = _texto()
    assert "notify pgrst, 'reload schema'; commit;" in t


def test_o_indice_do_a_mao_id_existe():
    assert ("create index if not exists pagamento_agendado_a_mao_idx "
            "on public.pagamento_agendado (a_mao_id) where a_mao_id is not null") in _texto()


def test_toda_tabela_tem_teto_de_tamanho():
    t = _texto()
    for nome in TABELAS:
        m = re.search(rf"constraint {nome}_tamanho check \((.*?)\)\s*\);", t)
        assert m, nome
        assert "length(quem_nome) <= 200" in m.group(1), nome
    for coluna in ("campos", "antes", "foto", "ordem"):
        assert f"pg_column_size({coluna}) <= 16384" in t
    for coluna in ("dados", "prova"):
        assert f"length({coluna}) <= 500" in t
