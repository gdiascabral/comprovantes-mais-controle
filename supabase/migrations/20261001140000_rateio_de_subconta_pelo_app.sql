-- ------------------------------------------------------- rateio de subconta
-- O app passa a poder parametrizar o rateio de uma subconta: criar a
-- subconta e acrescentar/tirar investidores e centros de custo.
--
-- Ate 01/10/2026 isso era SQL no painel. O botao "Rateio de subconta" da
-- aba Aportes grava o que a pessoa escolheu nas listas do proprio Mais
-- Controle (`aportes/rateio_subconta.py`).
--
-- Recorte, sempre com a porteira `privado.e_ativo()`:
--
--   subconta             insert            (nasce pelo numero; renomear e
--                                            apagar continuam no painel)
--   subconta_obra        insert, delete    (editar o rateio = trocar linhas)
--   subconta_investidor  insert, delete
--
-- O que isso troca: um token vazado de usuario ATIVO pode mexer no rateio de
-- uma subconta. Rateio vazio nao perde dinheiro (`regras.validar` barra o
-- lancamento e diz por que); rateio trocado aparece no log da aba e nos
-- lancamentos, e se desfaz pela mesma janela. A subconta em si nao some:
-- delete nela continua so pelo painel, e e ele que levaria os filhos junto
-- (`on delete cascade`).
--
-- Idempotente: pode rodar duas vezes. Tudo numa transacao: colado a mao
-- no SQL Editor, um erro no meio nao deixa politica sem grant.

begin;

drop policy if exists subconta_cadastra on public.subconta;
create policy subconta_cadastra on public.subconta
  for insert to authenticated
  with check ((select privado.e_ativo()));
grant insert (nome) on table public.subconta to authenticated;

drop policy if exists subconta_obra_cadastra on public.subconta_obra;
create policy subconta_obra_cadastra on public.subconta_obra
  for insert to authenticated
  with check ((select privado.e_ativo()));
drop policy if exists subconta_obra_tira on public.subconta_obra;
create policy subconta_obra_tira on public.subconta_obra
  for delete to authenticated
  using ((select privado.e_ativo()));
grant insert (subconta_id, nome), delete
  on table public.subconta_obra to authenticated;

drop policy if exists subconta_investidor_cadastra on public.subconta_investidor;
create policy subconta_investidor_cadastra on public.subconta_investidor
  for insert to authenticated
  with check ((select privado.e_ativo()));
drop policy if exists subconta_investidor_tira on public.subconta_investidor;
create policy subconta_investidor_tira on public.subconta_investidor
  for delete to authenticated
  using ((select privado.e_ativo()));
grant insert (subconta_id, nome), delete
  on table public.subconta_investidor to authenticated;

commit;

-- Reverter:
--   drop policy if exists subconta_cadastra on public.subconta;
--   drop policy if exists subconta_obra_cadastra on public.subconta_obra;
--   drop policy if exists subconta_obra_tira on public.subconta_obra;
--   drop policy if exists subconta_investidor_cadastra on public.subconta_investidor;
--   drop policy if exists subconta_investidor_tira on public.subconta_investidor;
--   revoke insert on table public.subconta from authenticated;
--   revoke insert, delete on table public.subconta_obra from authenticated;
--   revoke insert, delete on table public.subconta_investidor from authenticated;
