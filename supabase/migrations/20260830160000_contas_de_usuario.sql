-- Fase 1 de "Contas de usuário": quem é cada um, e o que cada um pode.
--
-- Hoje a conta nasce à mão no painel do Supabase e TODA conta que loga vê o
-- app inteiro. Isso funcionava com duas pessoas que fazem a mesma coisa; deixa
-- de funcionar quando entra alguém que só aprova — e principalmente quando
-- "quem liberou este pagamento?" precisa de resposta.
--
-- Esta migration não muda nada do que já existe. Ela cria as duas tabelas e as
-- travas; o login e a interface entram nas fases seguintes, e até lá o app
-- continua abrindo e funcionando igual.

-- ------------------------------------------------------------- o esconderijo
-- Um schema NÃO exposto na API, para as funções que a RLS usa por dentro.
--
-- Elas precisam existir fora do `public` por um motivo específico: são
-- `security definer` (rodam com o privilégio de quem as criou e atravessam a
-- RLS), e no `public` o PostgREST as publicaria como endpoint. Uma função que
-- atravessa RLS não deve ser chamável de fora.
create schema if not exists privado;

revoke all on schema privado from public;
-- `authenticated` PRECISA de usage: a expressão de uma política RLS roda com o
-- privilégio de quem consulta, não de quem a escreveu. Sem isto, toda leitura
-- da tabela falharia com "permission denied for schema privado" — que soa como
-- defeito da política e não é.
grant usage on schema privado to authenticated;

-- ------------------------------------------------------------------ perfil
-- Singular, como as outras onze tabelas deste banco (`empresa`, `conta`,
-- `remessa`...). O plano escreve "perfis"; se preferir o plural, é renomear
-- aqui e nos dois lugares do `nuvem/`.
create table public.perfil (
  user_id       uuid primary key references auth.users (id) on delete cascade,
  -- Nome e e-mail moram AQUI, copiados do `auth.users` pelo gatilho abaixo.
  -- Não é desnormalização por descuido: o schema `auth` não é exposto na API,
  -- então a tela de Usuários (fase 4) não tem como lê-lo. A alternativa seria
  -- mais uma função `security definer` para listar gente — mais superfície
  -- para menos.
  nome          text not null default '',
  email         text not null default '',
  papel         text not null default 'operador',
  situacao      text not null default 'pendente',
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  -- A lista fechada mora no banco, e não só no código: papel escrito errado
  -- ("aprovadaor") viraria uma pessoa que não vê aba nenhuma, e o defeito
  -- apareceria como "o app não abre para o fulano".
  constraint perfil_papel_conhecido
    check (papel in ('admin', 'operador', 'aprovador')),
  constraint perfil_situacao_conhecida
    check (situacao in ('pendente', 'ativo', 'desativado'))
);

comment on table public.perfil is
  'Quem é cada usuário e o que ele pode. Uma linha por conta do auth.users, '
  'criada pelo gatilho privado.criar_perfil() quando a conta nasce.';

comment on column public.perfil.situacao is
  'pendente = confirmou o e-mail e espera o admin; ativo = trabalha; '
  'desativado = não entra mais. Quem barra é a SITUAÇÃO, não o papel: conta '
  'nova nasce com papel de operador e situação pendente, e é a segunda que '
  'decide se ela vê alguma aba.';

-- A política de leitura filtra por `user_id`, e ele é a chave primária — o
-- índice já existe. Fica registrado que a dependência é essa: quem um dia
-- trocar a PK precisa saber que a RLS depende dela para não varrer a tabela.

-- ---------------------------------------------------------------- auditoria
-- "Quem liberou este pagamento?" sem perguntar às pessoas.
create table public.auditoria (
  id      bigint generated always as identity primary key,
  quem    uuid not null default auth.uid() references auth.users (id),
  quando  timestamptz not null default now(),
  acao    text not null,
  detalhe text not null default '',
  constraint auditoria_acao_nao_vazia check (length(trim(acao)) > 0)
);

comment on table public.auditoria is
  'Append-only: authenticated tem insert e select, e NÃO tem update nem '
  'delete. Registro que pode ser corrigido depois não serve para responder '
  'quem fez o quê -- é a única tabela do banco em que apagar é pior que '
  'errar.';

-- Os dois jeitos de perguntar: "o que o fulano fez" e "o que aconteceu hoje".
create index auditoria_quem_idx on public.auditoria (quem, quando desc);
create index auditoria_quando_idx on public.auditoria (quando desc);

-- --------------------------------------------------------------- é admin?
-- A função que a RLS chama para saber se quem consulta é administrador.
--
-- Ela existe por causa de uma armadilha: a política "só admin escreve em
-- `perfil`" precisa CONSULTAR `perfil` para saber quem é admin — e consultar a
-- tabela de dentro da política dela mesma é recursão infinita. O Postgres
-- responde com "infinite recursion detected in policy for relation perfil", e
-- a tabela fica ilegível para todo mundo.
--
-- `security definer` atravessa a RLS de `perfil` e corta o laço. É seguro
-- porque ela não recebe parâmetro nenhum: responde sobre QUEM CHAMA e mais
-- ninguém, então nem sendo chamada à mão vaza alguma coisa.
--
-- `set search_path = ''` é obrigatório em toda função `security definer`: sem
-- ele, quem chama escolhe o `search_path` e pode plantar uma tabela `perfil`
-- num schema próprio para a função ler a dele.
create or replace function privado.e_admin()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.perfil
    -- `(select auth.uid())` e não `auth.uid()` direto: assim o Postgres avalia
    -- uma vez e reaproveita, em vez de chamar a função por linha lida.
    where user_id = (select auth.uid())
      and papel = 'admin'
      and situacao = 'ativo'
  );
$$;

revoke execute on function privado.e_admin() from public, anon;
grant execute on function privado.e_admin() to authenticated;

-- ------------------------------------------------- perfil nasce com a conta
create or replace function privado.criar_perfil()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  insert into public.perfil (user_id, nome, email)
  values (
    new.id,
    -- O nome vem do que a tela de "Criar conta" (fase 3) mandar no metadata.
    -- Vazio não impede nada: o admin vê o e-mail e sabe quem é.
    coalesce(nullif(trim(new.raw_user_meta_data ->> 'nome'), ''), ''),
    coalesce(new.email, '')
  )
  -- Idempotente de propósito: o gatilho pode disparar de novo num reenvio de
  -- confirmação, e perder o papel que o admin já deu seria rebaixar alguém em
  -- silêncio.
  on conflict (user_id) do nothing;
  return new;
end;
$$;

create trigger perfil_ao_criar_usuario
  after insert on auth.users
  for each row execute function privado.criar_perfil();

-- ------------------------------------------------------ atualizado_em sozinho
create or replace function privado.marcar_atualizacao()
returns trigger
language plpgsql
as $$
begin
  new.atualizado_em = now();
  return new;
end;
$$;

create trigger perfil_marca_atualizacao
  before update on public.perfil
  for each row execute function privado.marcar_atualizacao();

-- --------------------------------------------------------------------- RLS
alter table public.perfil    enable row level security;
alter table public.auditoria enable row level security;

-- Cada um lê o seu; o admin lê todos (é ele quem aprova, e para aprovar
-- precisa ver a fila).
create policy perfil_le_o_proprio on public.perfil
  for select to authenticated
  using (user_id = (select auth.uid()) or (select privado.e_admin()));

-- Escrita é só do admin, e é por isso que ela não pode passar pela mesma
-- tabela sem a função acima.
create policy perfil_admin_cria on public.perfil
  for insert to authenticated
  with check ((select privado.e_admin()));

create policy perfil_admin_corrige on public.perfil
  for update to authenticated
  using ((select privado.e_admin()))
  with check ((select privado.e_admin()));

-- Sem política de DELETE de propósito: desligar alguém é `situacao =
-- 'desativado'`, que deixa rastro. Apagar a linha levaria junto a resposta de
-- "quem era este user_id na auditoria?".

-- Cada um escreve a PRÓPRIA linha de auditoria. O `with check` é o que impede
-- alguém de registrar uma ação em nome de outro — sem ele, a tabela
-- responderia "quem fez" com o que o cliente quisesse dizer.
create policy auditoria_registra_a_propria on public.auditoria
  for insert to authenticated
  with check (quem = (select auth.uid()));

create policy auditoria_le_a_propria on public.auditoria
  for select to authenticated
  using (quem = (select auth.uid()) or (select privado.e_admin()));

-- ---------------------------------------------------------------- privilégios
-- O privilégio de TABELA vem antes da política: sem ele a política nem chega a
-- ser consultada, e o erro é "permission denied for table", que soa como RLS e
-- não é. Foi o defeito de 21/08 na tabela `conta`, corrigido em 24/08 — está
-- escrito aqui para não acontecer uma terceira vez.
grant select, insert, update on table public.perfil to authenticated;
grant select, insert            on table public.auditoria to authenticated;
-- Sem `delete` em nenhuma das duas, e sem `update` na auditoria: ver os
-- comentários das políticas.

grant select, insert, update, delete on table public.perfil    to service_role;
grant select, insert, update, delete on table public.auditoria to service_role;
grant usage, select on all sequences in schema public to service_role;

-- ------------------------------------------------------------------ backfill
-- Quem já usa o app hoje NÃO pode ser trancado do lado de fora por esta
-- migration. Todos entram como operador ATIVO, que é exatamente o que eles já
-- podiam fazer: todas as abas de trabalho.
--
-- Ninguém nasce admin aqui, de propósito: virar admin é decisão de gente, e
-- adivinhá-la a partir de "quem se cadastrou primeiro" é como se dá poder a
-- quem não devia. A promoção é uma linha rodada no painel — está em
-- `APLICAR NO SUPABASE.sql`.
insert into public.perfil (user_id, nome, email, papel, situacao)
select u.id,
       coalesce(nullif(trim(u.raw_user_meta_data ->> 'nome'), ''), ''),
       coalesce(u.email, ''),
       'operador',
       'ativo'
from auth.users u
on conflict (user_id) do nothing;
