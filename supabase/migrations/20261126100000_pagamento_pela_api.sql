-- ---------------------------------------------- pagamento pela API do Sicoob
-- Spec de 26/11/2026. O app monta o LOTE do dia, um aprovador aprova (pelo
-- portal), o robô do servidor paga e anota cada passo. Tudo só ACRESCENTA:
-- ninguém altera nem apaga linha (sem grant de update/delete). As regras de
-- dinheiro moram AQUI, no banco, e não na tela: a tela do portal é pública e
-- qualquer um pode chamar a API com o próprio login.
--
--   lote_pagamento / lote_item  -> o app (papel admin|operador) cria; itens só
--                                  entram enquanto o lote não foi aprovado nem
--                                  cancelado, e só por quem o preparou.
--   lote_aprovacao              -> papel aprovador; nunca quem preparou; só no
--                                  dia; soma conferida pelo banco.
--   lote_cancelado              -> quem preparou, antes da aprovação.
--   lote_evento / robo_pulso    -> papel robo (o usuário do servidor).
--   robo_parar                  -> parar: qualquer conta ativa; retomar: aprovador ou admin.
--
-- Idempotente. Tudo numa transação.

begin;
-- O alter do perfil trava a tabela que toda política lê: não esperar mais que isso.
set local lock_timeout = '5s';

-- ----------------------------------------------------------- papel do robô
alter table public.perfil drop constraint if exists perfil_papel_conhecido;
alter table public.perfil add constraint perfil_papel_conhecido
  check (papel in ('admin', 'operador', 'aprovador', 'robo'));

create or replace function privado.tem_papel(p text)
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1 from public.perfil
    where user_id = (select auth.uid()) and situacao = 'ativo' and papel = p
  );
$$;
revoke execute on function privado.tem_papel(text) from public, anon;
grant execute on function privado.tem_papel(text) to authenticated;

create or replace function privado.hoje()
returns date
language sql
stable
set search_path = ''
as $$ select (now() at time zone 'America/Sao_Paulo')::date $$;
revoke execute on function privado.hoje() from public, anon;
grant execute on function privado.hoje() to authenticated;

-- ------------------------------------------------------------------ tabelas
create table if not exists public.lote_pagamento (
  id             bigint generated always as identity primary key,
  dia            date not null,
  total          numeric(14,2) not null,
  preparado_por  uuid not null default auth.uid() references auth.users (id),
  quem_nome      text not null default '',
  quando         timestamptz not null default now(),
  constraint lote_pagamento_total check (total > 0)
);

create table if not exists public.lote_item (
  id                 bigint generated always as identity primary key,
  lote               bigint not null references public.lote_pagamento (id),
  ordem              integer not null,
  titulo             text not null,
  alvo               text not null,
  conta              text not null,
  tipo               text not null,
  dados              text not null,
  valor              numeric(14,2) not null,
  favorecido         text not null default '',
  documento_esperado text not null default '',
  descricao          text not null default '',
  constraint lote_item_ordem unique (lote, ordem),
  constraint lote_item_titulo_no_lote unique (lote, titulo),
  constraint lote_item_ordem_positiva check (ordem > 0),
  constraint lote_item_tipo check (tipo in ('boleto', 'pix_chave', 'pix_qr', 'convenio')),
  constraint lote_item_valor check (valor > 0),
  constraint lote_item_documento check (documento_esperado ~ '^([0-9]{11}|[0-9]{14})?$'),
  constraint lote_item_tamanho check (length(titulo) between 1 and 100 and length(alvo) <= 200
    and length(conta) <= 200 and length(dados) between 1 and 600
    and length(favorecido) <= 200 and length(descricao) <= 100)
);
create index if not exists lote_item_titulo_idx on public.lote_item (titulo);

create table if not exists public.lote_cancelado (
  lote       bigint primary key references public.lote_pagamento (id),
  motivo     text not null,
  quem       uuid not null default auth.uid() references auth.users (id),
  quando     timestamptz not null default now(),
  constraint lote_cancelado_motivo check (length(trim(motivo)) between 3 and 200)
);

create table if not exists public.lote_aprovacao (
  id             bigint generated always as identity primary key,
  lote           bigint not null unique references public.lote_pagamento (id),
  itens          integer[] not null,
  retirados      jsonb not null default '[]'::jsonb,
  total          numeric(14,2) not null,
  aprovado_por   uuid not null default auth.uid() references auth.users (id),
  quem_nome      text not null default '',
  quando         timestamptz not null default now(),
  constraint lote_aprovacao_retirados check (jsonb_typeof(retirados) = 'array'
    and pg_column_size(retirados) <= 16384)
);

create table if not exists public.lote_evento (
  id       bigint generated always as identity primary key,
  lote     bigint not null references public.lote_pagamento (id),
  ordem    integer not null,
  estado   text not null,
  detalhe  text not null default '',
  chave    text not null default '',
  quem     uuid not null default auth.uid() references auth.users (id),
  quando   timestamptz not null default now(),
  constraint lote_evento_estado check (estado in
    ('iniciado', 'em_processamento', 'realizado', 'nao_pago', 'falta_anexar', 'concluido')),
  constraint lote_evento_tamanho check (length(detalhe) <= 500 and length(chave) <= 200)
);
create index if not exists lote_evento_lote_idx on public.lote_evento (lote, id);
-- A trava contra pagar duas vezes que vale até para duas máquinas ao mesmo
-- tempo: o robô grava INICIADO ANTES de pagar, e o segundo INICIADO do mesmo
-- item é recusado aqui (o robô para sem pagar).
create unique index if not exists lote_evento_um_iniciado
  on public.lote_evento (lote, ordem) where estado = 'iniciado';

create table if not exists public.robo_pulso (
  id      bigint generated always as identity primary key,
  quem    uuid not null default auth.uid() references auth.users (id),
  quando  timestamptz not null default now()
);
create index if not exists robo_pulso_quando_idx on public.robo_pulso (quando desc);

create table if not exists public.robo_parar (
  id         bigint generated always as identity primary key,
  acao       text not null,
  motivo     text not null default '',
  quem       uuid not null default auth.uid() references auth.users (id),
  quem_nome  text not null default '',
  quando     timestamptz not null default now(),
  constraint robo_parar_acao check (acao in ('parar', 'retomar')),
  constraint robo_parar_motivo check (length(motivo) <= 200)
);

-- ------------------------------------------------- as regras, no banco
create or replace function privado.conferir_lote()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.dia <> privado.hoje() then
    raise exception 'lote só para hoje (%), não para %', privado.hoje(), new.dia;
  end if;
  return new;
end;
$$;
revoke execute on function privado.conferir_lote() from public, anon, authenticated;

create or replace function privado.conferir_item()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  l public.lote_pagamento%rowtype;
begin
  -- Trava a linha do lote: item, aprovação e cancelamento do MESMO lote passam
  -- um de cada vez, e cada um enxerga o que o outro gravou (revisão de SQL, 26/11).
  perform 1 from public.lote_pagamento where id = new.lote for no key update;
  select * into l from public.lote_pagamento where id = new.lote;
  if l.preparado_por is distinct from (select auth.uid()) then
    raise exception 'só quem preparou o lote acrescenta itens';
  end if;
  if exists (select 1 from public.lote_aprovacao a where a.lote = new.lote)
     or exists (select 1 from public.lote_cancelado c where c.lote = new.lote) then
    raise exception 'lote já aprovado ou cancelado';
  end if;
  -- Dois lotes ao mesmo tempo com o mesmo título: um de cada vez.
  perform pg_advisory_xact_lock(hashtextextended('lote_item:' || new.titulo, 0));
  -- O título bloqueia enquanto estiver num lote não cancelado, sem ter sido
  -- retirado na aprovação e sem ter terminado em nao_pago: de hoje, ou de
  -- qualquer dia quando aquele lote foi aprovado (pode ter sido pago).
  if exists (
    select 1 from public.lote_item i
    join public.lote_pagamento p on p.id = i.lote
    left join public.lote_aprovacao a on a.lote = i.lote
    where i.titulo = new.titulo and i.lote <> new.lote
      and not exists (select 1 from public.lote_cancelado c where c.lote = i.lote)
      and (a.lote is null or i.ordem = any (a.itens))
      and coalesce((select e.estado from public.lote_evento e
                    where e.lote = i.lote and e.ordem = i.ordem
                    order by e.id desc limit 1), '') <> 'nao_pago'
      and (p.dia = l.dia or a.lote is not null)
  ) then
    raise exception 'título % já está em outro lote de hoje', new.titulo;
  end if;
  return new;
end;
$$;
revoke execute on function privado.conferir_item() from public, anon, authenticated;

create or replace function privado.conferir_aprovacao()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  l          public.lote_pagamento%rowtype;
  todas      integer[];
  fora       integer[];
  soma_tudo  numeric(14,2);
  soma_itens numeric(14,2);
begin
  perform 1 from public.lote_pagamento where id = new.lote for no key update;
  select * into l from public.lote_pagamento where id = new.lote;
  if l.id is null then
    raise exception 'lote inexistente';
  end if;
  if l.dia <> privado.hoje() then
    raise exception 'aprovação vale só no dia do lote';
  end if;
  if l.preparado_por = (select auth.uid()) then
    raise exception 'quem preparou o lote não aprova';
  end if;
  if exists (select 1 from public.lote_cancelado c where c.lote = new.lote) then
    raise exception 'lote cancelado';
  end if;
  select array_agg(ordem order by ordem), coalesce(sum(valor), 0)
    into todas, soma_tudo from public.lote_item where lote = new.lote;
  if soma_tudo <> l.total then
    raise exception 'lote incompleto: itens somam % e o lote diz %', soma_tudo, l.total;
  end if;
  if coalesce(array_length(new.itens, 1), 0) = 0 then
    raise exception 'aprovação sem itens';
  end if;
  if (select count(distinct x) from unnest(new.itens) x) <> array_length(new.itens, 1)
     or not (new.itens <@ todas) then
    raise exception 'itens aprovados não conferem com o lote';
  end if;
  select coalesce(array_agg((r ->> 'ordem')::integer order by (r ->> 'ordem')::integer), '{}')
    into fora from jsonb_array_elements(new.retirados) r;
  if exists (select 1 from jsonb_array_elements(new.retirados) r
             where length(trim(coalesce(r ->> 'motivo', ''))) < 3) then
    raise exception 'item retirado sem motivo';
  end if;
  if (select array_agg(x order by x) from unnest(new.itens || fora) x) is distinct from todas then
    raise exception 'todo item do lote tem de estar aprovado ou retirado, uma vez só';
  end if;
  select coalesce(sum(valor), 0) into soma_itens
    from public.lote_item where lote = new.lote and ordem = any (new.itens);
  if new.total <> soma_itens then
    raise exception 'total aprovado % não é a soma dos itens %', new.total, soma_itens;
  end if;
  return new;
end;
$$;
revoke execute on function privado.conferir_aprovacao() from public, anon, authenticated;

create or replace function privado.conferir_cancelamento()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  perform 1 from public.lote_pagamento where id = new.lote for no key update;
  if (select preparado_por from public.lote_pagamento where id = new.lote)
       is distinct from (select auth.uid()) then
    raise exception 'só quem preparou cancela';
  end if;
  if exists (select 1 from public.lote_aprovacao a where a.lote = new.lote) then
    raise exception 'lote aprovado não se cancela: use Parar pagamentos';
  end if;
  return new;
end;
$$;
revoke execute on function privado.conferir_cancelamento() from public, anon, authenticated;

-- O banco amarra o robô: INICIADO (o passo antes de pagar) só para item
-- aprovado, de lote de hoje, com o robô ligado.
create or replace function privado.conferir_evento()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if new.estado = 'iniciado' then
    if not exists (select 1 from public.lote_aprovacao a
                   where a.lote = new.lote and new.ordem = any (a.itens)) then
      raise exception 'item % do lote % não está aprovado', new.ordem, new.lote;
    end if;
    if (select dia from public.lote_pagamento where id = new.lote) <> privado.hoje() then
      raise exception 'lote não é de hoje';
    end if;
    if coalesce((select acao from public.robo_parar order by id desc limit 1), '') = 'parar' then
      raise exception 'robô parado pelo botão';
    end if;
  end if;
  return new;
end;
$$;
revoke execute on function privado.conferir_evento() from public, anon, authenticated;

drop trigger if exists lote_evento_confere on public.lote_evento;
create trigger lote_evento_confere before insert on public.lote_evento
  for each row execute function privado.conferir_evento();
drop trigger if exists lote_pagamento_confere on public.lote_pagamento;
create trigger lote_pagamento_confere before insert on public.lote_pagamento
  for each row execute function privado.conferir_lote();
drop trigger if exists lote_item_confere on public.lote_item;
create trigger lote_item_confere before insert on public.lote_item
  for each row execute function privado.conferir_item();
drop trigger if exists lote_aprovacao_confere on public.lote_aprovacao;
create trigger lote_aprovacao_confere before insert on public.lote_aprovacao
  for each row execute function privado.conferir_aprovacao();
drop trigger if exists lote_cancelado_confere on public.lote_cancelado;
create trigger lote_cancelado_confere before insert on public.lote_cancelado
  for each row execute function privado.conferir_cancelamento();

drop trigger if exists lote_pagamento_quem_nome on public.lote_pagamento;
create trigger lote_pagamento_quem_nome before insert on public.lote_pagamento
  for each row execute function privado.carimbar_quem_nome();
drop trigger if exists lote_aprovacao_quem_nome on public.lote_aprovacao;
create trigger lote_aprovacao_quem_nome before insert on public.lote_aprovacao
  for each row execute function privado.carimbar_quem_nome();
drop trigger if exists robo_parar_quem_nome on public.robo_parar;
create trigger robo_parar_quem_nome before insert on public.robo_parar
  for each row execute function privado.carimbar_quem_nome();

-- ------------------------------------------------------- permissões e RLS
revoke all on table public.lote_pagamento, public.lote_item, public.lote_cancelado,
  public.lote_aprovacao, public.lote_evento, public.robo_pulso, public.robo_parar
  from anon, authenticated;
grant select, insert on table public.lote_pagamento, public.lote_item, public.lote_cancelado,
  public.lote_aprovacao, public.lote_evento, public.robo_pulso, public.robo_parar
  to authenticated;

alter table public.lote_pagamento enable row level security;
alter table public.lote_item      enable row level security;
alter table public.lote_cancelado enable row level security;
alter table public.lote_aprovacao enable row level security;
alter table public.lote_evento    enable row level security;
alter table public.robo_pulso     enable row level security;
alter table public.robo_parar     enable row level security;

drop policy if exists lote_pagamento_le on public.lote_pagamento;
create policy lote_pagamento_le on public.lote_pagamento for select to authenticated using ((select privado.e_ativo()));
drop policy if exists lote_pagamento_grava on public.lote_pagamento;
create policy lote_pagamento_grava on public.lote_pagamento for insert to authenticated with check (
  (select privado.e_ativo())
  and ((select privado.tem_papel('operador')) or (select privado.tem_papel('admin')))
  and preparado_por = (select auth.uid()));

drop policy if exists lote_item_le on public.lote_item;
create policy lote_item_le on public.lote_item for select to authenticated using ((select privado.e_ativo()));
drop policy if exists lote_item_grava on public.lote_item;
create policy lote_item_grava on public.lote_item for insert to authenticated with check (
  (select privado.e_ativo())
  and ((select privado.tem_papel('operador')) or (select privado.tem_papel('admin'))));

drop policy if exists lote_cancelado_le on public.lote_cancelado;
create policy lote_cancelado_le on public.lote_cancelado for select to authenticated using ((select privado.e_ativo()));
drop policy if exists lote_cancelado_grava on public.lote_cancelado;
create policy lote_cancelado_grava on public.lote_cancelado for insert to authenticated with check (
  (select privado.e_ativo()) and quem = (select auth.uid()));

drop policy if exists lote_aprovacao_le on public.lote_aprovacao;
create policy lote_aprovacao_le on public.lote_aprovacao for select to authenticated using ((select privado.e_ativo()));
drop policy if exists lote_aprovacao_grava on public.lote_aprovacao;
create policy lote_aprovacao_grava on public.lote_aprovacao for insert to authenticated with check (
  (select privado.e_ativo()) and (select privado.tem_papel('aprovador'))
  and aprovado_por = (select auth.uid()));

drop policy if exists lote_evento_le on public.lote_evento;
create policy lote_evento_le on public.lote_evento for select to authenticated using ((select privado.e_ativo()));
drop policy if exists lote_evento_grava on public.lote_evento;
create policy lote_evento_grava on public.lote_evento for insert to authenticated with check (
  (select privado.e_ativo()) and (select privado.tem_papel('robo'))
  and quem = (select auth.uid()));

drop policy if exists robo_pulso_le on public.robo_pulso;
create policy robo_pulso_le on public.robo_pulso for select to authenticated using ((select privado.e_ativo()));
drop policy if exists robo_pulso_grava on public.robo_pulso;
create policy robo_pulso_grava on public.robo_pulso for insert to authenticated with check (
  (select privado.e_ativo()) and (select privado.tem_papel('robo'))
  and quem = (select auth.uid()));

drop policy if exists robo_parar_le on public.robo_parar;
create policy robo_parar_le on public.robo_parar for select to authenticated using ((select privado.e_ativo()));
drop policy if exists robo_parar_grava on public.robo_parar;
create policy robo_parar_grava on public.robo_parar for insert to authenticated with check (
  (select privado.e_ativo()) and quem = (select auth.uid())
  and (acao = 'parar' or (select privado.tem_papel('aprovador')) or (select privado.e_admin())));

notify pgrst, 'reload schema';

commit;
