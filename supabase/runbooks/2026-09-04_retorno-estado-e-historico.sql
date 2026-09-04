-- =========================================================================
-- Cole TUDO isto no SQL Editor do Supabase e rode uma vez so.
-- E um assunto so: as duas colunas novas do retorno, mais o grant.
-- Rodar ANTES de dar merge no PR que le essas colunas.
-- 04/09/2026
-- =========================================================================
--
-- Por que: o segundo retorno (o de depois da assinatura do master) gravava
-- por cima do primeiro, e o primeiro era a prova de que o arquivo tinha sido
-- ACEITO. Agora `retorno_codigo` continua sendo a resposta de agora e
-- `retorno_historico` guarda o que veio antes, sem apagar nada.
--
-- E seguro rodar com o app aberto e com o codigo VELHO em producao: as duas
-- colunas nascem com default '' e ninguem e obrigado a escrever nelas.


-- ------------------------------------------------------------- 1 de 2 --
-- As duas colunas. Sem check em `retorno_estado`, pelo mesmo motivo da
-- coluna `estado` da remessa: a lista vive no codigo, e duplica-la aqui
-- criaria duas respostas para "o que e um estado valido".

alter table public.remessa_item
  add column retorno_estado    text not null default '',
  add column retorno_historico text not null default '';

comment on column public.remessa_item.retorno_estado is
  'Como o retorno classificou este pagamento: ok, pendente, rejeitado ou "?" '
  '(o banco não disse nada). Escrito pelo app, a partir do mesmo julgamento '
  'que a tela mostra.';

comment on column public.remessa_item.retorno_historico is
  'O que o banco disse ANTES, uma entrada por retorno lido, separadas por '
  '";". O `retorno_codigo` é a resposta de agora e é sobrescrito; esta coluna '
  'nunca perde o que já estava nela — é a prova de que a remessa foi aceita '
  'antes de o master assinar.';


-- ------------------------------------------------------------- 2 de 2 --
-- O privilegio e de COLUNA, como o de 17/08: update na tabela inteira
-- deixaria reescrever valor, favorecido e referencia, que descrevem um
-- arquivo que ja saiu do banco.
--
-- NAO nasce politica nova: `remessa_item_retorno` ja existe e ja exige
-- `privado.e_ativo()` desde 30/08. Uma segunda politica para a mesma
-- operacao seria um OU, e afrouxaria a porteira.

grant update (retorno_codigo, retorno_em, retorno_estado, retorno_historico)
  on table public.remessa_item to authenticated;


-- ------------------------------------------------------------ conferir --
-- As duas respostas, na ordem. Nenhuma deve vir vazia.
--
-- A primeira tem de trazer as DUAS colunas novas, as duas `text`, `not null`
-- e com default ''. A segunda tem de trazer QUATRO linhas para
-- `authenticated`: sem as quatro, o app grava metade do retorno e a outra
-- metade volta com "permission denied for table remessa_item".

select 'coluna nova' as o_que,
       column_name || ' ' || data_type
         || ' null=' || is_nullable
         || ' default=' || coalesce(column_default, '(nenhum)') as valor
  from information_schema.columns
 where table_schema = 'public'
   and table_name = 'remessa_item'
   and column_name in ('retorno_estado', 'retorno_historico')
union all
select 'update permitido em', column_name
  from information_schema.column_privileges
 where table_schema = 'public'
   and table_name = 'remessa_item'
   and privilege_type = 'UPDATE'
   and grantee = 'authenticated'
 order by 1, 2;
