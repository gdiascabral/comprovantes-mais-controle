# -*- coding: utf-8 -*-
"""A estrutura do pagamento pela API, lida da migration (sem Postgres — o mesmo
jeito de `test_pagamentos_do_dia_sql.py`). Quem prova o COMPORTAMENTO é o
roteiro de prova no banco (begin; ...; rollback;), rodado depois de aplicar."""
import re
from pathlib import Path

_SQL = (Path(__file__).resolve().parent.parent / "supabase" / "migrations"
        / "20261126100000_pagamento_pela_api.sql")
TABELAS = ("lote_pagamento", "lote_item", "lote_cancelado", "lote_aprovacao",
           "lote_evento", "robo_pulso", "robo_parar")


def _texto() -> str:
    sql = re.sub(r"--[^\n]*", " ", _SQL.read_text(encoding="utf-8"))
    return " ".join(sql.split()).lower()


def test_cria_as_tabelas_com_rls():
    t = _texto()
    for nome in TABELAS:
        assert f"create table if not exists public.{nome} (" in t
        assert f"alter table public.{nome} enable row level security" in t
        assert f"create policy {nome}_le on public.{nome} for select to authenticated" in t
        assert f"create policy {nome}_grava on public.{nome} for insert to authenticated" in t


def test_ninguem_altera_nem_apaga():
    t = _texto()
    assert "grant select, insert on table public.lote_pagamento, public.lote_item" in t
    assert not re.search(r"grant[^;]*\b(update|delete|truncate)\b[^;]*to authenticated", t)
    assert "for update" not in t and "for delete" not in t


def test_cada_papel_so_no_que_e_dele():
    t = _texto()
    assert ("create policy lote_aprovacao_grava on public.lote_aprovacao for insert to authenticated "
            "with check ( (select privado.e_ativo()) and (select privado.tem_papel('aprovador')) "
            "and aprovado_por = (select auth.uid()))") in t
    for nome in ("lote_evento", "robo_pulso"):
        assert (f"create policy {nome}_grava on public.{nome} for insert to authenticated with check ( "
                "(select privado.e_ativo()) and (select privado.tem_papel('robo')) "
                "and quem = (select auth.uid()))") in t
    assert "check (papel in ('admin', 'operador', 'aprovador', 'robo'))" in t


def test_as_regras_de_dinheiro_estao_no_banco():
    t = _texto()
    assert "quem preparou o lote não aprova" in t
    assert "aprovação vale só no dia do lote" in t
    assert "total aprovado % não é a soma dos itens %" in t
    assert "já está em outro lote de hoje" in t
    assert "lote já aprovado ou cancelado" in t
    assert "constraint lote_item_titulo_no_lote unique (lote, titulo)" in t
    assert "item % do lote % não está aprovado" in t and "robô parado pelo botão" in t
    assert t.count("for no key update") == 3
    assert "pg_advisory_xact_lock(hashtextextended('lote_item:' || new.titulo, 0))" in t
    for gatilho in ("lote_pagamento_confere", "lote_item_confere", "lote_aprovacao_confere",
                    "lote_cancelado_confere", "lote_evento_confere"):
        assert f"create trigger {gatilho} before insert" in t


def test_funcao_security_definer_tem_search_path_vazio():
    t = _texto()
    for m in re.finditer(r"create or replace function (privado\.\w+)\([^)]*\)(.*?)\$\$", t):
        if "security definer" in m.group(2):
            assert "set search_path = ''" in m.group(2), m.group(1)


def test_um_iniciado_por_item_no_banco():
    assert ("create unique index if not exists lote_evento_um_iniciado on public.lote_evento "
            "(lote, ordem) where estado = 'iniciado'") in _texto()


def test_item_que_iniciou_nunca_libera_o_titulo_e_lote_velho_recusa_item():
    t = _texto()
    assert "e.lote = i.lote and e.ordem = i.ordem and e.estado = 'iniciado'" in t
    assert t.count("raise exception 'lote não é de hoje'") == 2


def test_mesmo_codigo_em_lotes_diferentes_e_barrado():
    t = _texto()
    assert "raise exception 'o mesmo código de pagamento já está em outro lote'" in t
    assert ("create unique index if not exists lote_item_dados_no_lote on public.lote_item "
            "(lote, dados) where tipo <> 'pix_chave'") in t
