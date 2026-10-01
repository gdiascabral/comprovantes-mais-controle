-- ------------------------------------------- % por centro de custo no rateio
-- O rateio de uma subconta dividia o aporte em partes IGUAIS entre os
-- centros de custo. A partir de 01/10/2026 cada CC pode ter o seu %:
-- `percentual` vazio em todos = partes iguais (como sempre foi); preenchido,
-- tem de estar em TODOS e somar 100 — quem confere a soma e o app
-- (`aportes/regras.problema_dos_percentuais`), que recusa lancar com rateio
-- incompleto. Aqui o banco so garante que cada numero e um % possivel.
--
-- Escrita, sempre com a porteira `privado.e_ativo()`: o insert ganha a
-- coluna nova, e o app passa a poder ALTERAR so o `percentual` de um CC que
-- ja existe (trocar 50/50 por 70/30 sem apagar e recriar as linhas).
--
-- Idempotente; numa transacao.

begin;

alter table public.subconta_obra
  add column if not exists percentual numeric(6, 2);

alter table public.subconta_obra
  drop constraint if exists subconta_obra_percentual_possivel;
alter table public.subconta_obra
  add constraint subconta_obra_percentual_possivel
  check (percentual is null or (percentual > 0 and percentual <= 100));

comment on column public.subconta_obra.percentual is
  'Parte do aporte que vai para este centro de custo, em %. Vazio em todos '
  'os CCs da subconta = partes iguais.';

grant insert (percentual) on table public.subconta_obra to authenticated;
grant update (percentual) on table public.subconta_obra to authenticated;

drop policy if exists subconta_obra_corrige on public.subconta_obra;
create policy subconta_obra_corrige on public.subconta_obra
  for update to authenticated
  using ((select privado.e_ativo()))
  with check ((select privado.e_ativo()));

commit;

-- Reverter:
--   drop policy if exists subconta_obra_corrige on public.subconta_obra;
--   revoke update (percentual) on table public.subconta_obra from authenticated;
--   revoke insert (percentual) on table public.subconta_obra from authenticated;
--   alter table public.subconta_obra drop constraint if exists subconta_obra_percentual_possivel;
--   alter table public.subconta_obra drop column if exists percentual;
