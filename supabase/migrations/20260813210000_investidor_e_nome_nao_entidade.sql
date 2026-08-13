-- O investidor de uma subconta NAO e uma entidade do contas.csv.
--
-- O modelo anterior ligava `subconta_investidor` a `entidade` por chave
-- estrangeira, supondo que investidor e pagador fossem a mesma lista. Nao sao:
-- em `aportes/regras.py`, o investidor entra como `cliente` do lancamento e
-- como texto da descricao -- ele precisa existir como CLIENTE no ERP, e nunca
-- e procurado no contas.csv. Os cinco investidores reais nao tem linha la, e
-- estao certos assim.
--
-- Mantida a FK, a migracao teria duas saidas, ambas ruins: falhar, ou inventar
-- entidades para satisfazer o vinculo -- poluindo o cadastro de quem aporta
-- com nomes que so existem como cliente de obra.

drop table public.subconta_investidor;

create table public.subconta_investidor (
  id          bigint generated always as identity primary key,
  subconta_id bigint not null references public.subconta (id) on delete cascade,
  -- Nome do cliente no ERP, como sai na descricao do lancamento.
  nome        text not null,
  criado_em   timestamptz not null default now(),
  constraint subconta_investidor_unico unique (subconta_id, nome),
  constraint subconta_investidor_nome_nao_vazio check (length(trim(nome)) > 0)
);

create index subconta_investidor_subconta_idx
  on public.subconta_investidor (subconta_id);

comment on table public.subconta_investidor is
  'Entre quem o aporte de uma subconta e rateado. O valor e dividido em '
  '(obras x investidores) partes iguais; subconta sem investidor faria o '
  'rateio sair vazio e o dinheiro sumir sem erro.';

grant select, insert, update, delete
  on table public.subconta_investidor to authenticated;

alter table public.subconta_investidor enable row level security;

create policy subconta_investidor_autenticado on public.subconta_investidor
  for all to authenticated using (true) with check (true);
