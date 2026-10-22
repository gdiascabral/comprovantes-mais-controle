-- ------------------------------------------------ pagamentos do dia na nuvem
-- Entrega 2 da aba "Pagamentos do dia" (especificacao v3, 21/10/2026): o que
-- o dono LIBERA, EDITA e paga A MAO, o que ele marca como AGENDADO e o que
-- responde depois, e a lista do diretor. Tudo com quem/quando/motivo.
--
-- Recorte (o mesmo da `remessa` e da `auditoria`): o app so ACRESCENTA e LE.
--   insert -> sim, para conta liberada (`privado.e_ativo()`), e o `quem` e
--             carimbado pelo servidor (default auth.uid() + with check).
--   update -> NAO. Mudar de ideia e uma linha nova (desfazer, resposta nova).
--   delete -> NAO. Historico de dinheiro nao se apaga.
-- O estado de cada linha e a ULTIMA linha de evento; quem dobra e o app.
--
-- Os ajustes de saldo (simulacao) continuam no JSON local do dia: sao
-- rascunho que vale so para o dia e nao decidem o que e pago.
--
-- Idempotente. Tudo numa transacao.

begin;

create table if not exists public.pagamento_decisao (
  id              bigint generated always as identity primary key,
  dia             date not null,
  alvo            text not null,
  conta           text not null default '',
  acao            text not null,
  motivo          text not null default '',
  campos          jsonb not null default '{}'::jsonb,
  antes           jsonb not null default '{}'::jsonb,
  corrigir_no_erp boolean not null default false,
  quem            uuid not null default auth.uid() references auth.users (id),
  quem_nome       text not null default '',
  quando          timestamptz not null default now(),
  constraint pagamento_decisao_alvo check (length(trim(alvo)) > 0),
  constraint pagamento_decisao_acao check (acao in ('liberar', 'desmarcar', 'editar', 'desfazer', 'remover_a_mao')),
  constraint pagamento_decisao_motivo check (length(motivo) <= 200
    and (acao not in ('liberar', 'editar', 'remover_a_mao') or length(trim(motivo)) >= 3)),
  constraint pagamento_decisao_json check (jsonb_typeof(campos) = 'object' and jsonb_typeof(antes) = 'object')
);
create index if not exists pagamento_decisao_dia_idx on public.pagamento_decisao (dia, id);

create table if not exists public.pagamento_a_mao (
  id              bigint generated always as identity primary key,
  dia             date not null,
  conta           text not null,
  valor           numeric(14,2) not null,
  favorecido      text not null default '',
  tipo            text not null default '',
  dados           text not null default '',
  descricao       text not null,
  lancamento_id   text not null default '',
  centro_custo    text not null default '',
  nf              text not null default '',
  oc              text not null default '',
  valor_em_aberto numeric(14,2),
  motivo          text not null,
  quem            uuid not null default auth.uid() references auth.users (id),
  quem_nome       text not null default '',
  quando          timestamptz not null default now(),
  constraint pagamento_a_mao_valor check (valor > 0),
  constraint pagamento_a_mao_em_aberto check (valor_em_aberto is null or valor <= valor_em_aberto),
  constraint pagamento_a_mao_conta check (length(trim(conta)) > 0),
  constraint pagamento_a_mao_descricao check (length(trim(descricao)) >= 3 and length(descricao) <= 200),
  constraint pagamento_a_mao_motivo check (length(trim(motivo)) >= 3 and length(motivo) <= 200),
  constraint pagamento_a_mao_tipo check (tipo in ('', 'Pix', 'Boleto', 'Transferência'))
);
create index if not exists pagamento_a_mao_dia_idx on public.pagamento_a_mao (dia, id);

create table if not exists public.pagamento_agendado (
  id            bigint generated always as identity primary key,
  dia           date not null,
  conta         text not null,
  alvo          text not null,
  lancamento_id text not null default '',
  a_mao_id      bigint references public.pagamento_a_mao (id),
  favorecido    text not null default '',
  valor         numeric(14,2) not null,
  descricao     text not null default '',
  tipo          text not null default '',
  foto          jsonb not null default '{}'::jsonb,
  quem          uuid not null default auth.uid() references auth.users (id),
  quem_nome     text not null default '',
  quando        timestamptz not null default now(),
  constraint pagamento_agendado_valor check (valor > 0),
  constraint pagamento_agendado_alvo check (length(trim(alvo)) > 0),
  constraint pagamento_agendado_foto check (jsonb_typeof(foto) = 'object')
);
-- Duas maquinas marcando o mesmo pagamento no mesmo dia: o banco recusa a
-- segunda (a trava e o indice, como o `seu_numero_unico_no_dia`).
create unique index if not exists pagamento_agendado_um_por_dia on public.pagamento_agendado (dia, alvo);
create index if not exists pagamento_agendado_dia_idx on public.pagamento_agendado (dia desc);

create table if not exists public.agendado_resposta (
  id          bigint generated always as identity primary key,
  agendado_id bigint not null references public.pagamento_agendado (id),
  resposta    text not null,
  motivo      text not null default '',
  nova_data   date,
  prova       text not null default '',
  quem        uuid not null default auth.uid() references auth.users (id),
  quem_nome   text not null default '',
  quando      timestamptz not null default now(),
  constraint agendado_resposta_tipo check (resposta in ('pago', 'nao_saiu', 'reagendado')),
  constraint agendado_resposta_motivo check (length(motivo) <= 200
    and (resposta <> 'nao_saiu' or length(trim(motivo)) >= 3)),
  constraint agendado_resposta_data check (resposta <> 'reagendado' or nova_data is not null)
);
create index if not exists agendado_resposta_agendado_idx on public.agendado_resposta (agendado_id, id);

create table if not exists public.lista_diretor_nome (
  id         bigint generated always as identity primary key,
  conta      text not null,
  nome_curto text not null,
  quem       uuid not null default auth.uid() references auth.users (id),
  quem_nome  text not null default '',
  quando     timestamptz not null default now(),
  constraint lista_diretor_nome_conta check (length(trim(conta)) > 0),
  constraint lista_diretor_nome_nome check (length(trim(nome_curto)) between 1 and 60)
);
create index if not exists lista_diretor_nome_conta_idx on public.lista_diretor_nome (conta, id);

create table if not exists public.lista_diretor (
  id        bigint generated always as identity primary key,
  dia       date not null,
  ordem     jsonb not null,
  texto     text not null,
  quem      uuid not null default auth.uid() references auth.users (id),
  quem_nome text not null default '',
  quando    timestamptz not null default now(),
  constraint lista_diretor_ordem check (jsonb_typeof(ordem) = 'array')
);
create index if not exists lista_diretor_dia_idx on public.lista_diretor (dia desc, id desc);

-- "Nada some ate voce responder": o agendado cuja ULTIMA resposta nao e
-- final. `security_invoker` faz a RLS das tabelas valer para quem consulta.
create or replace view public.agendado_em_aberto with (security_invoker = true) as
  select a.*
    from public.pagamento_agendado a
   where coalesce((select r.resposta from public.agendado_resposta r
                    where r.agendado_id = a.id order by r.id desc limit 1), '')
         not in ('pago', 'nao_saiu');

revoke all on table public.pagamento_decisao  from anon, authenticated;
revoke all on table public.pagamento_a_mao    from anon, authenticated;
revoke all on table public.pagamento_agendado from anon, authenticated;
revoke all on table public.agendado_resposta  from anon, authenticated;
revoke all on table public.lista_diretor_nome from anon, authenticated;
revoke all on table public.lista_diretor      from anon, authenticated;
revoke all on table public.agendado_em_aberto from anon, authenticated;

grant select, insert on table public.pagamento_decisao  to authenticated;
grant select, insert on table public.pagamento_a_mao    to authenticated;
grant select, insert on table public.pagamento_agendado to authenticated;
grant select, insert on table public.agendado_resposta  to authenticated;
grant select, insert on table public.lista_diretor_nome to authenticated;
grant select, insert on table public.lista_diretor      to authenticated;
grant select on table public.agendado_em_aberto to authenticated;

grant select, insert, update, delete on table public.pagamento_decisao, public.pagamento_a_mao,
  public.pagamento_agendado, public.agendado_resposta, public.lista_diretor_nome,
  public.lista_diretor to service_role;

alter table public.pagamento_decisao  enable row level security;
alter table public.pagamento_a_mao    enable row level security;
alter table public.pagamento_agendado enable row level security;
alter table public.agendado_resposta  enable row level security;
alter table public.lista_diretor_nome enable row level security;
alter table public.lista_diretor      enable row level security;

drop policy if exists pagamento_decisao_le on public.pagamento_decisao;
create policy pagamento_decisao_le on public.pagamento_decisao for select to authenticated using ((select privado.e_ativo()));
drop policy if exists pagamento_decisao_grava on public.pagamento_decisao;
create policy pagamento_decisao_grava on public.pagamento_decisao for insert to authenticated with check ((select privado.e_ativo()) and quem = (select auth.uid()));
drop policy if exists pagamento_a_mao_le on public.pagamento_a_mao;
create policy pagamento_a_mao_le on public.pagamento_a_mao for select to authenticated using ((select privado.e_ativo()));
drop policy if exists pagamento_a_mao_grava on public.pagamento_a_mao;
create policy pagamento_a_mao_grava on public.pagamento_a_mao for insert to authenticated with check ((select privado.e_ativo()) and quem = (select auth.uid()));
drop policy if exists pagamento_agendado_le on public.pagamento_agendado;
create policy pagamento_agendado_le on public.pagamento_agendado for select to authenticated using ((select privado.e_ativo()));
drop policy if exists pagamento_agendado_grava on public.pagamento_agendado;
create policy pagamento_agendado_grava on public.pagamento_agendado for insert to authenticated with check ((select privado.e_ativo()) and quem = (select auth.uid()));
drop policy if exists agendado_resposta_le on public.agendado_resposta;
create policy agendado_resposta_le on public.agendado_resposta for select to authenticated using ((select privado.e_ativo()));
drop policy if exists agendado_resposta_grava on public.agendado_resposta;
create policy agendado_resposta_grava on public.agendado_resposta for insert to authenticated with check ((select privado.e_ativo()) and quem = (select auth.uid()));
drop policy if exists lista_diretor_nome_le on public.lista_diretor_nome;
create policy lista_diretor_nome_le on public.lista_diretor_nome for select to authenticated using ((select privado.e_ativo()));
drop policy if exists lista_diretor_nome_grava on public.lista_diretor_nome;
create policy lista_diretor_nome_grava on public.lista_diretor_nome for insert to authenticated with check ((select privado.e_ativo()) and quem = (select auth.uid()));
drop policy if exists lista_diretor_le on public.lista_diretor;
create policy lista_diretor_le on public.lista_diretor for select to authenticated using ((select privado.e_ativo()));
drop policy if exists lista_diretor_grava on public.lista_diretor;
create policy lista_diretor_grava on public.lista_diretor for insert to authenticated with check ((select privado.e_ativo()) and quem = (select auth.uid()));

notify pgrst, 'reload schema';

commit;

-- Reverter:
--   drop view if exists public.agendado_em_aberto;
--   drop table if exists public.agendado_resposta, public.pagamento_agendado,
--     public.pagamento_a_mao, public.pagamento_decisao, public.lista_diretor,
--     public.lista_diretor_nome;
