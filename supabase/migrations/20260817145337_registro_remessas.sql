-- Fase 3: o registro das remessas CNAB, que precisa ser UM para as duas
-- máquinas.
--
-- Hoje o contador vive em `remessas.json` ao lado do exe, com uma trava que é
-- um arquivo `.lock`. Ela protege dois processos na MESMA pasta -- e a prova
-- de que isso não basta já existe nesta máquina: a instalação (`_app`) diz
-- que o próximo NSA é 1 e a pasta de código diz que é 2, porque cada uma tem
-- o seu arquivo. Com duas pessoas, o mesmo acontece entre computadores.
--
-- Repetir NSA pode significar pagamento em dobro. Pular número é inofensivo.
-- Todo o desenho aqui escolhe o lado de pular.

-- ------------------------------------------------------------- contador

create table public.remessa_contador (
  convenio      text primary key,
  ultimo_nsa    integer not null default 0,
  atualizado_em timestamptz not null default now(),
  constraint remessa_contador_nsa_nao_volta check (ultimo_nsa >= 0)
);

comment on table public.remessa_contador is
  'Último NSA usado por convênio. Só a função alocar_nsa() escreve aqui: o '
  'privilégio direto é revogado logo abaixo, porque um UPDATE à mão pode '
  'fazer o contador VOLTAR, e contador que volta repete NSA.';

-- ------------------------------------------------------------- remessas

create table public.remessa (
  id          bigint generated always as identity primary key,
  convenio    text not null,
  nsa         integer not null,
  empresa     text not null default '',
  documento   text not null default '',
  agencia     text not null default '',
  conta       text not null default '',
  gerado_em   timestamptz not null default now(),
  arquivo     text not null default '',
  sha256      text not null default '',
  -- Os mesmos estados do `cnab240.historico`. Não há check aqui de propósito:
  -- a lista vive no código (ESTADOS_VIVOS) e duplicá-la criaria duas verdades
  -- sobre o que é um estado válido, com a do banco envelhecendo calada.
  estado      text not null default 'gerado',
  observacao  text not null default '',
  -- Quem gerou. É o que o login passou a permitir saber, e o que faltava
  -- para responder "quem mandou este arquivo?" sem perguntar às pessoas.
  quem        uuid not null default auth.uid() references auth.users (id),
  criado_em   timestamptz not null default now(),
  constraint remessa_nsa_unico_por_convenio unique (convenio, nsa),
  constraint remessa_nsa_positivo check (nsa > 0)
);

create index remessa_convenio_idx on public.remessa (convenio, nsa desc);

comment on constraint remessa_nsa_unico_por_convenio on public.remessa is
  'A trava que o arquivo local não conseguia dar: duas máquinas gerando no '
  'mesmo dia não conseguem gravar o mesmo NSA.';

-- ---------------------------------------------------------------- itens

create table public.remessa_item (
  id             bigint generated always as identity primary key,
  remessa_id     bigint not null references public.remessa (id) on delete cascade,
  seu_numero     text not null,
  valor          numeric(15, 2) not null,
  favorecido     text not null default '',
  produto        text not null default '',
  -- Código de barras do boleto: chave natural do INSTRUMENTO, e só existe
  -- quando é de fato única. Chave Pix e dados de conta ficam de fora — o
  -- mesmo fornecedor recebe várias vezes por dia, e isso viraria alarme
  -- falso diário.
  identificador  text not null default '',
  -- Id do lançamento no ERP: a chave que responde "este já foi mandado?"
  -- para QUALQUER forma de pagamento, e por onde o retorno acha o caminho
  -- de volta.
  referencia     text not null default '',
  -- O que o banco respondeu, quando o retorno for processado.
  retorno_codigo text not null default '',
  retorno_em     timestamptz,
  criado_em      timestamptz not null default now(),
  constraint remessa_item_seu_numero_unico unique (remessa_id, seu_numero),
  constraint remessa_item_valor_positivo check (valor > 0)
);

create index remessa_item_remessa_idx on public.remessa_item (remessa_id);
-- As duas perguntas que o `_ja_enviado` faz antes de deixar um pagamento
-- entrar na remessa. Sem índice, elas varrem a tabela inteira a cada linha.
create index remessa_item_referencia_idx on public.remessa_item (referencia)
  where referencia <> '';
create index remessa_item_identificador_idx on public.remessa_item (identificador)
  where identificador <> '';

-- -------------------------------------------------------------- ajustes

create table public.remessa_ajuste (
  id        bigint generated always as identity primary key,
  convenio  text not null,
  de_nsa    integer not null,
  para_nsa  integer not null,
  -- Obrigatório: é o que explica o furo na sequência para quem olhar depois.
  motivo    text not null,
  quem      uuid not null default auth.uid() references auth.users (id),
  quando    timestamptz not null default now(),
  constraint remessa_ajuste_tem_motivo check (length(trim(motivo)) > 0)
);

create index remessa_ajuste_convenio_idx on public.remessa_ajuste (convenio);

-- --------------------------------------------- a alocação, que é atômica

create or replace function public.alocar_nsa(p_convenio text)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  novo integer;
begin
  -- `security definer` para poder escrever num contador que ninguém escreve
  -- à mão. Por isso a checagem de identidade tem de estar AQUI dentro: sem
  -- ela, a função rodaria com privilégio de dono para qualquer chamador.
  if auth.uid() is null then
    raise exception 'é preciso estar autenticado para alocar NSA';
  end if;
  if p_convenio is null or length(trim(p_convenio)) = 0 then
    raise exception 'convênio vazio';
  end if;

  -- Uma instrução só: o `on conflict do update` trava a linha e o
  -- incremento acontece dentro da trava. Duas máquinas pedindo ao mesmo
  -- tempo recebem números diferentes -- que é a coisa inteira que este
  -- arquivo existe para garantir.
  insert into public.remessa_contador (convenio, ultimo_nsa)
       values (trim(p_convenio), 1)
  on conflict (convenio)
    do update set ultimo_nsa = public.remessa_contador.ultimo_nsa + 1,
                  atualizado_em = now()
    returning ultimo_nsa into novo;

  return novo;
end;
$$;

comment on function public.alocar_nsa(text) is
  'Reserva o próximo NSA do convênio e o devolve. RESERVA, não espia: cada '
  'chamada consome um número. Para só mostrar na tela, leia o '
  'remessa_contador. Pular número é inofensivo; repetir não.';

create or replace function public.ajustar_nsa(p_convenio text, p_novo integer,
                                              p_motivo text)
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
  anterior integer;
begin
  if auth.uid() is null then
    raise exception 'é preciso estar autenticado para ajustar NSA';
  end if;
  if p_motivo is null or length(trim(p_motivo)) = 0 then
    raise exception 'ajustar o contador exige motivo: é o que explica o furo';
  end if;

  select ultimo_nsa into anterior
    from public.remessa_contador where convenio = trim(p_convenio);
  anterior := coalesce(anterior, 0);

  insert into public.remessa_contador (convenio, ultimo_nsa)
       values (trim(p_convenio), p_novo)
  on conflict (convenio)
    do update set ultimo_nsa = p_novo, atualizado_em = now();

  insert into public.remessa_ajuste (convenio, de_nsa, para_nsa, motivo)
       values (trim(p_convenio), anterior, p_novo, trim(p_motivo));

  return anterior;
end;
$$;

comment on function public.ajustar_nsa(text, integer, text) is
  'Corrige o contador à mão, deixando rastro em remessa_ajuste. Aceita '
  'ABAIXAR o valor, porque às vezes é o certo (uma remessa descartada que '
  'nunca foi enviada) — mas nunca sem motivo escrito.';

-- ------------------------------------------------------------- acesso

-- Este é o primeiro lugar onde o app ESCREVE. O cadastro ele só lê; aqui ele
-- registra o que fez, e por isso o privilégio é maior. Ainda assim, o mínimo:
--
--   sem DELETE em lugar nenhum -- histórico não se apaga, se marca;
--   UPDATE só em `estado`/`observacao` da remessa (a marcação de enviada,
--   aceita, descartada) e no retorno do item. O resto do que foi gravado
--   descreve um arquivo que já saiu, e reescrevê-lo seria mentir sobre o
--   passado;
--   nada direto no contador: só pelas duas funções acima.
grant select, insert on table public.remessa, public.remessa_item,
                              public.remessa_ajuste to authenticated;
grant update (estado, observacao) on table public.remessa to authenticated;
grant update (retorno_codigo, retorno_em) on table public.remessa_item to authenticated;
grant select on table public.remessa_contador to authenticated;
grant usage on all sequences in schema public to authenticated;

grant execute on function public.alocar_nsa(text) to authenticated;
grant execute on function public.ajustar_nsa(text, integer, text) to authenticated;

grant select, insert, update, delete on table
  public.remessa, public.remessa_item, public.remessa_ajuste,
  public.remessa_contador to service_role;

alter table public.remessa_contador enable row level security;
alter table public.remessa          enable row level security;
alter table public.remessa_item     enable row level security;
alter table public.remessa_ajuste   enable row level security;

-- Todo mundo vê tudo: são 2 a 5 pessoas cuidando do mesmo fechamento, e
-- esconder a remessa de uma da outra só criaria pagamento duplicado por
-- desconhecimento.
create policy remessa_contador_le on public.remessa_contador
  for select to authenticated using (true);

create policy remessa_le on public.remessa
  for select to authenticated using (true);
create policy remessa_grava on public.remessa
  for insert to authenticated with check ((select auth.uid()) = quem);
create policy remessa_marca on public.remessa
  for update to authenticated using (true) with check (true);

create policy remessa_item_le on public.remessa_item
  for select to authenticated using (true);
create policy remessa_item_grava on public.remessa_item
  for insert to authenticated with check (true);
create policy remessa_item_retorno on public.remessa_item
  for update to authenticated using (true) with check (true);

create policy remessa_ajuste_le on public.remessa_ajuste
  for select to authenticated using (true);
create policy remessa_ajuste_grava on public.remessa_ajuste
  for insert to authenticated with check ((select auth.uid()) = quem);
