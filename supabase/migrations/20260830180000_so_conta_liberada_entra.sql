-- Fase 3 de "Contas de usuário": o que muda no banco quando QUALQUER UM pode
-- criar conta.
--
-- Até hoje a conta nascia à mão no painel, e o auto-cadastro estava DESLIGADO
-- no projeto. Era ele quem segurava a porta: a chave `anon` está no código, e
-- o código está num repositório público — quem quisesse um token de
-- `authenticated` só não conseguia porque não havia como se cadastrar.
--
-- A fase 3 liga o auto-cadastro. Sem esta migration, ligá-lo daria a qualquer
-- pessoa do mundo, em três cliques:
--
--   ler empresa, conta, cliente_erp, entidade, subconta, as regras e a
--   configuração — o cadastro inteiro da empresa e de quem ela paga;
--   ler remessa, remessa_item e remessa_ajuste — o que foi pago, a quem e
--   quanto;
--   ESCREVER em `conta` (insert e update);
--   gravar remessa e item, e marcar remessa como enviada;
--   e chamar `alocar_nsa`, que queima números de remessa de verdade.
--
-- Esconder as abas no app não resolveria nada disso: a API responde a quem
-- tem token, e o app é só um dos jeitos de falar com ela.
--
-- O que esta migration faz: troca "está autenticado" por "TEM PERFIL ATIVO"
-- em toda política e nas duas funções de NSA. Conta recém-criada nasce
-- pendente (fase 1), então ela loga, lê o próprio perfil, descobre que está
-- esperando — e não alcança mais nada.
--
-- Quem já trabalha aqui não sente diferença: o backfill da fase 1 pôs todo
-- mundo como ativo.

-- ------------------------------------------------------------- é ativo?
-- Irmã da `privado.e_admin()`, e pelos mesmos motivos: mora no schema não
-- exposto para o PostgREST não a publicar como endpoint, é `security definer`
-- para atravessar a RLS do `perfil` sem cair na recursão de uma política que
-- consulta a tabela que ela protege, e leva `set search_path = ''` para que
-- quem chama não possa plantar um `perfil` próprio noutro schema.
--
-- Não recebe parâmetro: responde sobre QUEM CHAMA e mais ninguém.
create or replace function privado.e_ativo()
returns boolean
language sql
stable
security definer
set search_path = ''
as $$
  select exists (
    select 1
    from public.perfil
    where user_id = (select auth.uid())
      and situacao = 'ativo'
  );
$$;

comment on function privado.e_ativo() is
  'Quem chama tem perfil ATIVO? É a porta de entrada de todo dado do app. '
  'Pendente e desativado respondem false: os dois logam, e nenhum dos dois '
  'lê nada além do próprio perfil.';

revoke execute on function privado.e_ativo() from public, anon;
grant execute on function privado.e_ativo() to authenticated;

-- ------------------------------------------------------------- o cadastro
-- `alter policy` em vez de derrubar e recriar: assim o `to authenticated` e o
-- nome de cada uma ficam onde estão, e a migration não pode errar a metade
-- que não era para mudar.
--
-- `(select privado.e_ativo())` e não a chamada direta: envolvida em subquery,
-- o Postgres avalia uma vez e reaproveita, em vez de chamar a função por
-- linha lida. Numa tabela de cadastro com milhares de linhas, a diferença
-- entre as duas formas é a tela demorar a abrir.
alter policy empresa_le             on public.empresa             using ((select privado.e_ativo()));
alter policy cliente_erp_le         on public.cliente_erp         using ((select privado.e_ativo()));
alter policy conta_le               on public.conta               using ((select privado.e_ativo()));
alter policy pasta_vazia_le         on public.pasta_vazia         using ((select privado.e_ativo()));
alter policy entidade_le            on public.entidade            using ((select privado.e_ativo()));
alter policy subconta_le            on public.subconta            using ((select privado.e_ativo()));
alter policy subconta_obra_le       on public.subconta_obra       using ((select privado.e_ativo()));
alter policy subconta_investidor_le on public.subconta_investidor using ((select privado.e_ativo()));
alter policy regra_fornecedor_le    on public.regra_fornecedor    using ((select privado.e_ativo()));
alter policy regra_boleto_le        on public.regra_boleto        using ((select privado.e_ativo()));
alter policy configuracao_le        on public.configuracao        using ((select privado.e_ativo()));

-- A conta pode nascer pelo app (21/08). Continua podendo — por quem trabalha.
alter policy conta_cadastra on public.conta
  with check ((select privado.e_ativo()));
alter policy conta_corrige on public.conta
  using ((select privado.e_ativo()))
  with check ((select privado.e_ativo()));

-- ------------------------------------------------------------- as remessas
-- Aqui não é cadastro: é o registro do que já saiu do banco. Ler quanto se
-- pagou a quem é tão sensível quanto escrever.
alter policy remessa_contador_le on public.remessa_contador
  using ((select privado.e_ativo()));

alter policy remessa_le on public.remessa
  using ((select privado.e_ativo()));
-- O `= quem` continua: ninguém grava remessa em nome de outro. O que se
-- acrescenta é que quem grava precisa estar liberado.
alter policy remessa_grava on public.remessa
  with check ((select auth.uid()) = quem and (select privado.e_ativo()));
alter policy remessa_marca on public.remessa
  using ((select privado.e_ativo()))
  with check ((select privado.e_ativo()));

alter policy remessa_item_le on public.remessa_item
  using ((select privado.e_ativo()));
alter policy remessa_item_grava on public.remessa_item
  with check ((select privado.e_ativo()));
alter policy remessa_item_retorno on public.remessa_item
  using ((select privado.e_ativo()))
  with check ((select privado.e_ativo()));

alter policy remessa_ajuste_le on public.remessa_ajuste
  using ((select privado.e_ativo()));
alter policy remessa_ajuste_grava on public.remessa_ajuste
  with check ((select auth.uid()) = quem and (select privado.e_ativo()));

-- ------------------------------------------------------------ o contador
-- As duas funções são `security definer` e por isso a RLS não as alcança: a
-- checagem de quem pode chamar mora DENTRO delas, e era `auth.uid() is not
-- null`. Com auto-cadastro ligado, "está autenticado" deixou de significar
-- "trabalha aqui" — e queimar NSA de um convênio de verdade é estrago que
-- não se desfaz sozinho: o número pulado só reaparece por `ajustar_nsa`, com
-- motivo escrito.
--
-- Recriadas inteiras porque `create or replace function` não aceita remendo.
-- Fora a linha da checagem, são as mesmas de 17/08.
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
  if not privado.e_ativo() then
    raise exception 'só quem tem conta liberada aloca NSA';
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
  if not privado.e_ativo() then
    raise exception 'só quem tem conta liberada ajusta o contador';
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

-- ------------------------------------------------- o que NÃO passa por aqui
-- `perfil` e `auditoria` continuam como estavam, de propósito:
--
--   quem está pendente PRECISA ler o próprio perfil — é assim que o app
--   descobre que a conta espera liberação, e sem isso a tela de espera não
--   teria o que dizer;
--   e precisa poder gravar a própria linha de auditoria, porque "fulano
--   entrou e ficou esperando" é justamente o que o admin quer ver na fila.
--
-- Nenhuma das duas dá acesso a dado da empresa: cada um só alcança as
-- próprias linhas.
