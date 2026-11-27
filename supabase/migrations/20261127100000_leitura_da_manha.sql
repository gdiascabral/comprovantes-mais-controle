-- ---------------------------------------------- leitura das 07:30 (E1a)
-- Spec 2026-11-27-aba-pagamentos-no-portal-design.md, D2/D3. O servidor lê
-- saldo e extrato de ontem pela API (Sicoob e Inter), o saldo do ERP pelo
-- porteiro, e casa o extrato com os agendados em aberto (só PRÉ-MARCA). Grava
-- aqui com o usuário de papel `robo`. Tudo só ACRESCENTA: sem update/delete.
--
--   saldo_lido      -> um saldo por conta e fonte (sicoob|inter|erp) por rodada;
--                      valor NULL = não lido, e então o motivo é obrigatório.
--   extrato_lido    -> o resumo do extrato de ontem de cada conta (contagens).
--   pre_marca_banco -> o que o banco provou de cada agendado em aberto. NÃO é
--                      resposta: "Pago" continua em agendado_resposta, pela pessoa.
--
-- Depende de 20261126100000_pagamento_pela_api.sql (papel robo,
-- privado.tem_papel, privado.hoje) e de 20261022100000 (pagamento_agendado).
-- Idempotente. Tudo numa transação.

begin;
set local lock_timeout = '5s';

create table if not exists public.saldo_lido (
  id        bigint generated always as identity primary key,
  rodada    uuid not null,
  dia       date not null default privado.hoje(),
  conta     text not null,
  fonte     text not null,
  empresa   text not null default '',
  valor     numeric(14,2),
  motivo    text not null default '',
  lido_em   timestamptz not null,
  quem      uuid not null default auth.uid() references auth.users (id),
  quando    timestamptz not null default now(),
  constraint saldo_lido_fonte check (fonte in ('sicoob', 'inter', 'erp')),
  -- não lido nunca vira zero: ou tem valor e nenhum motivo, ou não tem valor e diz por quê
  constraint saldo_lido_nao_lido_tem_motivo check ((valor is null) = (length(trim(motivo)) > 0)),
  constraint saldo_lido_tamanho check (length(conta) between 1 and 200
    and length(empresa) <= 200 and length(motivo) <= 200)
);
create index if not exists saldo_lido_conta_idx on public.saldo_lido (conta, fonte, lido_em desc);
create index if not exists saldo_lido_dia_idx on public.saldo_lido (dia);

create table if not exists public.extrato_lido (
  id           bigint generated always as identity primary key,
  rodada       uuid not null,
  dia          date not null default privado.hoje(),
  conta        text not null,
  fonte        text not null,
  empresa      text not null default '',
  dia_extrato  date not null,
  saidas       integer not null default 0,
  entradas     integer not null default 0,
  ilegiveis    integer not null default 0,
  fora_do_dia  integer not null default 0,
  motivo       text not null default '',
  quem         uuid not null default auth.uid() references auth.users (id),
  quando       timestamptz not null default now(),
  constraint extrato_lido_fonte check (fonte in ('sicoob', 'inter')),
  constraint extrato_lido_contagens check (saidas >= 0 and entradas >= 0
    and ilegiveis >= 0 and fora_do_dia >= 0),
  -- linha ilegível tira a conta do casamento, e o motivo diz isso
  constraint extrato_lido_ilegivel_tem_motivo check (ilegiveis = 0 or length(trim(motivo)) > 0),
  constraint extrato_lido_tamanho check (length(conta) between 1 and 200
    and length(empresa) <= 200 and length(motivo) <= 200)
);
create index if not exists extrato_lido_dia_idx on public.extrato_lido (dia);

create table if not exists public.pre_marca_banco (
  id           bigint generated always as identity primary key,
  rodada       uuid not null,
  dia          date not null default privado.hoje(),
  dia_extrato  date not null,
  agendado_id  bigint not null references public.pagamento_agendado (id),
  conta        text not null,
  prova        text not null default '',
  nota         text not null default '',
  quem         uuid not null default auth.uid() references auth.users (id),
  quando       timestamptz not null default now(),
  constraint pre_marca_banco_diz_algo check (length(prova) > 0 or length(nota) > 0),
  constraint pre_marca_banco_tamanho check (length(conta) between 1 and 200
    and length(prova) <= 300 and length(nota) <= 300)
);
create index if not exists pre_marca_banco_agendado_idx on public.pre_marca_banco (agendado_id, id desc);

-- ------------------------------------------------------- permissões e RLS
revoke all on table public.saldo_lido, public.extrato_lido, public.pre_marca_banco
  from anon, authenticated;
grant select, insert on table public.saldo_lido, public.extrato_lido, public.pre_marca_banco
  to authenticated;

alter table public.saldo_lido      enable row level security;
alter table public.extrato_lido    enable row level security;
alter table public.pre_marca_banco enable row level security;

drop policy if exists saldo_lido_le on public.saldo_lido;
create policy saldo_lido_le on public.saldo_lido for select to authenticated using ((select privado.e_ativo()));
drop policy if exists saldo_lido_grava on public.saldo_lido;
create policy saldo_lido_grava on public.saldo_lido for insert to authenticated with check (
  (select privado.e_ativo()) and (select privado.tem_papel('robo'))
  and quem = (select auth.uid()));

drop policy if exists extrato_lido_le on public.extrato_lido;
create policy extrato_lido_le on public.extrato_lido for select to authenticated using ((select privado.e_ativo()));
drop policy if exists extrato_lido_grava on public.extrato_lido;
create policy extrato_lido_grava on public.extrato_lido for insert to authenticated with check (
  (select privado.e_ativo()) and (select privado.tem_papel('robo'))
  and quem = (select auth.uid()));

drop policy if exists pre_marca_banco_le on public.pre_marca_banco;
create policy pre_marca_banco_le on public.pre_marca_banco for select to authenticated using ((select privado.e_ativo()));
drop policy if exists pre_marca_banco_grava on public.pre_marca_banco;
create policy pre_marca_banco_grava on public.pre_marca_banco for insert to authenticated with check (
  (select privado.e_ativo()) and (select privado.tem_papel('robo'))
  and quem = (select auth.uid()));

notify pgrst, 'reload schema';

commit;

-- Reversão (só com autorização do dono):
--   drop table if exists public.pre_marca_banco, public.extrato_lido, public.saldo_lido;
