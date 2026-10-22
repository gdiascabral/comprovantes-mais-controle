-- ---------------------------------------------------- controle de aportes
-- Entrega 3 da aba "Pagamentos do dia" (22/10/2026): a aba "Controle de
-- aportes" mostra, por conta e por aportador, quanto cada um aportou desde a
-- abertura, quanto deveria pela proporcao e quem deve quanto para igualar.
--
-- O DINHEIRO vem do ERP (recebimentos de aporte, lidos e nunca escritos).
-- Aqui moram so tres coisas: a ABERTURA de cada conta, a PROPORCAO de cada
-- aportador (com o "ja aportado antes da abertura") e os recebimentos "sem
-- dono" que o dono APONTOU (de quem sao, ou "nao e aporte desta conta").
--
-- Ler: quem tem conta liberada (privado.e_ativo()). Escrever: so
-- administrador ativo (privado.e_admin()) -- abertura e proporcao decidem
-- quem deve dinheiro a quem. A porteira e_ativo() vai junto em toda
-- politica para a regra de tests/test_rls_supabase.py valer a vista.
--
-- `aportador_id` com ON DELETE NO ACTION (e nao RESTRICT): apagar um
-- aportador que tem apontamento falha; apagar a CONTA (so pelo painel) leva
-- aportadores e apontamentos juntos, e NO ACTION confere no fim do comando,
-- depois das duas cascatas.
--
-- `alterado_por` aceita nulo: o arquivo da raiz grava pelo SQL Editor, onde
-- auth.uid() e nulo. Pelo app, o default (insert) e o gatilho (update)
-- gravam quem chamou; update sem usuario (painel) deixa nulo, nunca o
-- nome do autor anterior.
--
-- Nada de nome real aqui: os dados de abertura vao pelo arquivo da raiz.
-- ORDEM: aplicar ANTES de liberar o app (app novo com banco velho = a aba
-- mostra erro; as outras abas nao usam estas tabelas).
-- Idempotente; numa transacao.

begin;

create table if not exists public.controle_aporte_conta (
  id            bigint generated always as identity primary key,
  conta_erp     text not null,
  abertura      date not null,
  ativa         boolean not null default true,
  observacao    text not null default '',
  alterado_por  uuid default auth.uid() references auth.users (id),
  alterado_em   timestamptz not null default now(),
  constraint controle_aporte_conta_tem_nome check (length(trim(conta_erp)) > 0),
  constraint controle_aporte_conta_unica unique (conta_erp)
);

comment on table public.controle_aporte_conta is
  'Contas acompanhadas pela aba Controle de aportes. conta_erp = nome da conta '
  'bancaria no Mais Controle, letra por letra. abertura = primeiro dia contado.';

create table if not exists public.controle_aporte_aportador (
  id            bigint generated always as identity primary key,
  conta_id      bigint not null
                references public.controle_aporte_conta (id) on delete cascade,
  nome_erp      text not null,
  peso          numeric not null,
  abertura      numeric(15, 2) not null default 0,
  alterado_por  uuid default auth.uid() references auth.users (id),
  alterado_em   timestamptz not null default now(),
  constraint controle_aporte_aportador_tem_nome check (length(trim(nome_erp)) > 0),
  -- `< 'Infinity'`: scale('NaN') e scale('Infinity') sao NULL (ver a
  -- migration 20261002100000).
  constraint controle_aporte_aportador_peso_possivel
    check (peso > 0 and peso < 'Infinity' and scale(peso) <= 4),
  constraint controle_aporte_aportador_abertura_possivel check (abertura >= 0),
  constraint controle_aporte_aportador_unico unique (conta_id, nome_erp),
  -- alvo da chave composta de controle_aporte_atribuicao
  constraint controle_aporte_aportador_conta_id_unico unique (conta_id, id)
);

comment on column public.controle_aporte_aportador.nome_erp is
  'O Cliente dos recebimentos de aporte deste aportador no Mais Controle, '
  'nome COMPLETO. Nunca primeiro nome: dois aportadores com o mesmo primeiro '
  'nome sao pessoas diferentes.';
comment on column public.controle_aporte_aportador.abertura is
  'Ja aportado ANTES da data de abertura (credito de partida, >= 0).';

create index if not exists controle_aporte_aportador_conta_idx
  on public.controle_aporte_aportador (conta_id);

create table if not exists public.controle_aporte_atribuicao (
  id               bigint generated always as identity primary key,
  conta_id         bigint not null
                   references public.controle_aporte_conta (id) on delete cascade,
  recebimento_erp  text not null,
  aportador_id     bigint,
  valor            numeric(15, 2) not null,
  motivo           text not null,
  alterado_por     uuid default auth.uid() references auth.users (id),
  alterado_em      timestamptz not null default now(),
  constraint controle_aporte_atribuicao_valor_positivo check (valor > 0),
  constraint controle_aporte_atribuicao_tem_motivo check (length(trim(motivo)) > 0),
  constraint controle_aporte_atribuicao_unica unique (conta_id, recebimento_erp),
  -- chave composta: o aportador apontado tem de ser DESTA conta. Com
  -- aportador_id nulo (MATCH SIMPLE) a chave nao se aplica.
  constraint controle_aporte_atribuicao_aportador_da_conta
    foreign key (conta_id, aportador_id)
    references public.controle_aporte_aportador (conta_id, id) on delete no action
);

comment on table public.controle_aporte_atribuicao is
  'Recebimento "sem dono" que o dono apontou. aportador_id nulo = nao e '
  'aporte desta conta. valor = o do recebimento quando foi apontado: se o '
  'ERP mudar, o app devolve a linha para "sem dono" (nunca se resolve sozinho).';

create index if not exists controle_aporte_atribuicao_aportador_idx
  on public.controle_aporte_atribuicao (conta_id, aportador_id);

-- ------------------------------------------------ carimbo de quem alterou
create or replace function privado.controle_aporte_carimbo()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  new.alterado_em := now();
  new.alterado_por := (select auth.uid());
  return new;
end;
$$;

revoke all on function privado.controle_aporte_carimbo() from public, anon, authenticated;

drop trigger if exists controle_aporte_conta_carimbo on public.controle_aporte_conta;
create trigger controle_aporte_conta_carimbo
  before update on public.controle_aporte_conta
  for each row execute function privado.controle_aporte_carimbo();
drop trigger if exists controle_aporte_aportador_carimbo on public.controle_aporte_aportador;
create trigger controle_aporte_aportador_carimbo
  before update on public.controle_aporte_aportador
  for each row execute function privado.controle_aporte_carimbo();
drop trigger if exists controle_aporte_atribuicao_carimbo on public.controle_aporte_atribuicao;
create trigger controle_aporte_atribuicao_carimbo
  before update on public.controle_aporte_atribuicao
  for each row execute function privado.controle_aporte_carimbo();

-- ------------------------------------------------------------- permissoes
alter table public.controle_aporte_conta enable row level security;
alter table public.controle_aporte_aportador enable row level security;
alter table public.controle_aporte_atribuicao enable row level security;

revoke all on table public.controle_aporte_conta, public.controle_aporte_aportador,
  public.controle_aporte_atribuicao from anon, authenticated;

grant select on table public.controle_aporte_conta, public.controle_aporte_aportador,
  public.controle_aporte_atribuicao to authenticated;
grant insert (conta_erp, abertura, ativa, observacao),
      update (conta_erp, abertura, ativa, observacao)
  on table public.controle_aporte_conta to authenticated;
grant insert (conta_id, nome_erp, peso, abertura),
      update (nome_erp, peso, abertura), delete
  on table public.controle_aporte_aportador to authenticated;
grant insert (conta_id, recebimento_erp, aportador_id, valor, motivo),
      update (aportador_id, valor, motivo), delete
  on table public.controle_aporte_atribuicao to authenticated;

drop policy if exists controle_aporte_conta_le on public.controle_aporte_conta;
create policy controle_aporte_conta_le on public.controle_aporte_conta
  for select to authenticated using ((select privado.e_ativo()));
drop policy if exists controle_aporte_conta_cadastra on public.controle_aporte_conta;
create policy controle_aporte_conta_cadastra on public.controle_aporte_conta
  for insert to authenticated
  with check ((select privado.e_ativo()) and (select privado.e_admin()));
drop policy if exists controle_aporte_conta_corrige on public.controle_aporte_conta;
create policy controle_aporte_conta_corrige on public.controle_aporte_conta
  for update to authenticated
  using ((select privado.e_ativo()) and (select privado.e_admin()))
  with check ((select privado.e_ativo()) and (select privado.e_admin()));

drop policy if exists controle_aporte_aportador_le on public.controle_aporte_aportador;
create policy controle_aporte_aportador_le on public.controle_aporte_aportador
  for select to authenticated using ((select privado.e_ativo()));
drop policy if exists controle_aporte_aportador_cadastra on public.controle_aporte_aportador;
create policy controle_aporte_aportador_cadastra on public.controle_aporte_aportador
  for insert to authenticated
  with check ((select privado.e_ativo()) and (select privado.e_admin()));
drop policy if exists controle_aporte_aportador_corrige on public.controle_aporte_aportador;
create policy controle_aporte_aportador_corrige on public.controle_aporte_aportador
  for update to authenticated
  using ((select privado.e_ativo()) and (select privado.e_admin()))
  with check ((select privado.e_ativo()) and (select privado.e_admin()));
drop policy if exists controle_aporte_aportador_tira on public.controle_aporte_aportador;
create policy controle_aporte_aportador_tira on public.controle_aporte_aportador
  for delete to authenticated
  using ((select privado.e_ativo()) and (select privado.e_admin()));

drop policy if exists controle_aporte_atribuicao_le on public.controle_aporte_atribuicao;
create policy controle_aporte_atribuicao_le on public.controle_aporte_atribuicao
  for select to authenticated using ((select privado.e_ativo()));
drop policy if exists controle_aporte_atribuicao_cadastra on public.controle_aporte_atribuicao;
create policy controle_aporte_atribuicao_cadastra on public.controle_aporte_atribuicao
  for insert to authenticated
  with check ((select privado.e_ativo()) and (select privado.e_admin()));
drop policy if exists controle_aporte_atribuicao_corrige on public.controle_aporte_atribuicao;
create policy controle_aporte_atribuicao_corrige on public.controle_aporte_atribuicao
  for update to authenticated
  using ((select privado.e_ativo()) and (select privado.e_admin()))
  with check ((select privado.e_ativo()) and (select privado.e_admin()));
drop policy if exists controle_aporte_atribuicao_tira on public.controle_aporte_atribuicao;
create policy controle_aporte_atribuicao_tira on public.controle_aporte_atribuicao
  for delete to authenticated
  using ((select privado.e_ativo()) and (select privado.e_admin()));

notify pgrst, 'reload schema';

commit;

-- Reverter (primeiro volte o app; GUARDE antes:
--   select * from public.controle_aporte_conta;
--   select * from public.controle_aporte_aportador;
--   select * from public.controle_aporte_atribuicao;):
--   drop table if exists public.controle_aporte_atribuicao;
--   drop table if exists public.controle_aporte_aportador;
--   drop table if exists public.controle_aporte_conta;
--   drop function if exists privado.controle_aporte_carimbo();
