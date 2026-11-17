-- ------------------------------------------- arquivos do painel na nuvem
-- Pedido do dono (17/11/2026): outra pessoa da equipe abriu a aba Conciliacao e o app
-- quebrou por falta do config.yaml. Os arquivos do painel do Saldo
-- (config.yaml, mapping.yaml, MODELO.xlsx) e a lista de contas que o Baixar
-- OFX ignora (conciliacao_ofx.json) existiam SO na maquina do dono: em
-- 13/08 ficaram fora da nuvem porque so a aba Saldo de pagamentos os lia.
-- Desde entao o Pagamentos do dia e a Conciliacao tambem leem, e toda
-- maquina precisa deles.
--
-- Uma linha por arquivo, o conteudo em base64 (o MODELO.xlsx e binario) e
-- o sha256 dos bytes, conferido pelo proprio banco. Cada troca guarda a
-- versao anterior em `arquivo_do_painel_versao` (so acrescenta): o painel
-- errado se desfaz copiando a versao de volta pelo painel do Supabase.
--
-- Ler: quem tem conta liberada (privado.e_ativo()). Escrever: so
-- administrador ativo (privado.e_admin()) -- o mapping decide em que linha
-- do painel cai o saldo de cada conta, e o MODELO calcula o aporte minimo.
-- Nada de DELETE pela API. Nao ha dado real aqui: o conteudo sobe pelo app.
--
-- ORDEM: aplicar ANTES de liberar o app (app novo com banco velho = o aviso
-- "arquivos do painel: a nuvem recusou" no Registro; nada mais muda).
-- Idempotente; numa transacao.

begin;

create table if not exists public.arquivo_do_painel (
  nome          text primary key,
  conteudo      text not null,
  sha256        text not null,
  alterado_por  uuid default auth.uid() references auth.users (id) on delete set null,
  alterado_em   timestamptz not null default now(),
  constraint arquivo_do_painel_nome_conhecido check (
    nome in ('config.yaml', 'mapping.yaml', 'MODELO.xlsx', 'conciliacao_ofx.json')),
  -- 4 MB de base64 (~3 MB de arquivo): o MODELO tem ~20 KB.
  constraint arquivo_do_painel_tamanho check (length(conteudo) between 1 and 4000000),
  constraint arquivo_do_painel_sha_confere check (
    sha256 = encode(sha256(decode(conteudo, 'base64')), 'hex'))
);

comment on table public.arquivo_do_painel is
  'Arquivos do painel do Saldo que toda maquina do app precisa (config.yaml, '
  'mapping.yaml, MODELO.xlsx, conciliacao_ofx.json). conteudo = base64 dos '
  'bytes; sha256 = dos bytes, conferido pelo banco. O app baixa ao abrir.';

create table if not exists public.arquivo_do_painel_versao (
  id            bigint generated always as identity primary key,
  nome          text not null,
  conteudo      text not null,
  sha256        text not null,
  alterado_por  uuid,
  alterado_em   timestamptz not null,
  guardado_em   timestamptz not null default now()
);

comment on table public.arquivo_do_painel_versao is
  'Cada versao substituida de arquivo_do_painel (so acrescenta). Para voltar: '
  'copiar conteudo e sha256 de volta para arquivo_do_painel pelo painel.';

create index if not exists arquivo_do_painel_versao_nome_idx
  on public.arquivo_do_painel_versao (nome, guardado_em desc);

-- Quem e quando: o servidor carimba, o app nao manda.
create or replace function privado.arquivo_do_painel_carimbo()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if tg_op = 'UPDATE' and old.sha256 is distinct from new.sha256 then
    insert into public.arquivo_do_painel_versao
      (nome, conteudo, sha256, alterado_por, alterado_em)
    values (old.nome, old.conteudo, old.sha256, old.alterado_por, old.alterado_em);
  end if;
  new.alterado_em := now();
  new.alterado_por := (select auth.uid());
  return new;
end;
$$;

revoke all on function privado.arquivo_do_painel_carimbo() from public, anon, authenticated;

drop trigger if exists arquivo_do_painel_carimbo on public.arquivo_do_painel;
create trigger arquivo_do_painel_carimbo
  before insert or update on public.arquivo_do_painel
  for each row execute function privado.arquivo_do_painel_carimbo();

alter table public.arquivo_do_painel enable row level security;
alter table public.arquivo_do_painel_versao enable row level security;

revoke all on table public.arquivo_do_painel, public.arquivo_do_painel_versao
  from anon, authenticated;

grant select on table public.arquivo_do_painel, public.arquivo_do_painel_versao
  to authenticated;
grant insert (nome, conteudo, sha256), update (conteudo, sha256)
  on table public.arquivo_do_painel to authenticated;

drop policy if exists arquivo_do_painel_le on public.arquivo_do_painel;
create policy arquivo_do_painel_le on public.arquivo_do_painel
  for select to authenticated using ((select privado.e_ativo()));
drop policy if exists arquivo_do_painel_cadastra on public.arquivo_do_painel;
create policy arquivo_do_painel_cadastra on public.arquivo_do_painel
  for insert to authenticated
  with check ((select privado.e_ativo()) and (select privado.e_admin()));
drop policy if exists arquivo_do_painel_troca on public.arquivo_do_painel;
create policy arquivo_do_painel_troca on public.arquivo_do_painel
  for update to authenticated
  using ((select privado.e_ativo()) and (select privado.e_admin()))
  with check ((select privado.e_ativo()) and (select privado.e_admin()));

drop policy if exists arquivo_do_painel_versao_le on public.arquivo_do_painel_versao;
create policy arquivo_do_painel_versao_le on public.arquivo_do_painel_versao
  for select to authenticated
  using ((select privado.e_ativo()) and (select privado.e_admin()));

commit;

notify pgrst, 'reload schema';
