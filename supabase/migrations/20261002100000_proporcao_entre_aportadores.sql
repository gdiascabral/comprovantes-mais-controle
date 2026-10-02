-- --------------------------------- proporção entre aportadores de subconta
-- Decisão do dono (01/10/2026, revendo o mesmo dia): numa subconta de
-- investidor, quem tem PROPORÇÃO são os aportadores ("2:1", "60 e 40"); as
-- obras (centros de custo) dividem sempre IGUAL. O `percentual` por obra da
-- migração 20261001180000 nasceu e foi abandonado no mesmo dia: o app não o
-- lê nem o grava mais, e ele fica vazio (nenhuma linha chegou a usá-lo).
--
-- `peso` é um PESO, não um %: 2 e 1 dão 2:1; 60 e 40 dão 60%/40%. Por isso
-- não há soma a fechar. Vazio em todos os aportadores = partes iguais. Quem
-- confere "em todos ou em nenhum" é o app (`regras.problema_dos_pesos`).
--
-- Escrita com a porteira `privado.e_ativo()`: o insert ganha a coluna, e o
-- app pode ALTERAR só o `peso` de um aportador que já existe.
--
-- ORDEM: aplicar ANTES de liberar o app que lê `peso` — o app novo com o
-- banco velho recebe 400 ao ler o rateio. O app velho com o banco novo
-- funciona (ignora o peso).
--
-- Idempotente; numa transação.

begin;

alter table public.subconta_investidor
  add column if not exists peso numeric;

alter table public.subconta_investidor
  drop constraint if exists subconta_investidor_peso_possivel;
alter table public.subconta_investidor
  add constraint subconta_investidor_peso_possivel
  -- `< 'Infinity'`: scale('NaN') e scale('Infinity') sao NULL, e sem esta
  -- parte os dois passavam pelo check (NaN ordena acima de Infinity).
  check (peso is null
         or (peso > 0 and peso < 'Infinity' and scale(peso) <= 4));

comment on column public.subconta_investidor.peso is
  'Parte deste aportador no aporte da subconta (peso: 2 e 1 = 2:1). Vazio '
  'em todos = partes iguais. As obras dividem sempre igual.';

comment on column public.subconta_obra.percentual is
  'ABANDONADO em 01/10/2026: as obras dividem sempre igual. O app nao le '
  'nem grava; a proporcao e entre os aportadores (subconta_investidor.peso).';

grant insert (peso) on table public.subconta_investidor to authenticated;
grant update (peso) on table public.subconta_investidor to authenticated;

drop policy if exists subconta_investidor_corrige on public.subconta_investidor;
create policy subconta_investidor_corrige on public.subconta_investidor
  for update to authenticated
  using ((select privado.e_ativo()))
  with check ((select privado.e_ativo()));

notify pgrst, 'reload schema';

commit;

-- Reverter (primeiro volte o app para a versão anterior; e GUARDE antes):
--   select id, subconta_id, nome, peso from public.subconta_investidor
--    where peso is not null order by subconta_id, nome;
--   drop policy if exists subconta_investidor_corrige on public.subconta_investidor;
--   revoke update (peso) on table public.subconta_investidor from authenticated;
--   revoke insert (peso) on table public.subconta_investidor from authenticated;
--   alter table public.subconta_investidor drop constraint if exists subconta_investidor_peso_possivel;
--   alter table public.subconta_investidor drop column if exists peso;
