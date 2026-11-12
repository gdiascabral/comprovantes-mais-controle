-- ------------------------------------------------ controle de aportes
-- Contas do ERP SOMADAS a uma conta do controle (12/11/2026).
--
-- O caso: os socios da conta-mae aportam "na Inter ou no Sicoob" da mesma
-- empresa (regra do dono de 29/10/2026). O controle lia so a conta cadastrada
-- e um aporte feito no outro banco ficou de fora do "quem deve quanto para
-- igualar". `contas_somadas` lista as outras
-- contas do ERP (nome letra por letra, como `conta_erp`) cujos aportes contam
-- NESTA, como um caixa so. O app le cada uma e confere o filtro de conta a
-- parte antes de somar; uma que nao casa no ERP derruba a conta inteira.
--
-- Escrita so pelo painel do Supabase, como o `ativa`: nenhum grant novo para
-- `authenticated` (o `grant select` de TABELA de 22/10 ja cobre a leitura;
-- os grants de insert/update sao de COLUNA e nao incluem esta).
--
-- ORDEM: aplicar ANTES do merge. O app novo pede a coluna no select e, sem
-- ela, a leitura do controle falha (o PostgREST recusa coluna que nao existe).
-- O app velho nao a pede e nao muda nada.
--
-- Idempotente; numa transacao. So estrutura: o dado real (quais contas) vai
-- pelo arquivo da raiz, fora deste repositorio publico.

begin;

alter table public.controle_aporte_conta
  add column if not exists contas_somadas text[] not null default '{}';

alter table public.controle_aporte_conta
  drop constraint if exists controle_aporte_conta_somadas_validas;
-- Sem nulo dentro do array e sem nome vazio (CHECK nao aceita subconsulta,
-- entao "so espacos" fica com o app). Repetida, so espacos ou igual a propria
-- conta o app recusa (`problemas_da_conta`), com o recado em portugues.
alter table public.controle_aporte_conta
  add constraint controle_aporte_conta_somadas_validas
  check (coalesce(array_ndims(contas_somadas), 1) = 1
         and array_position(contas_somadas, null) is null
         and '' <> all (contas_somadas));

comment on column public.controle_aporte_conta.contas_somadas is
  'Outras contas do ERP (nome letra por letra) cujos aportes somam nesta, '
  'como um caixa so. Editada so pelo painel do Supabase.';

commit;

notify pgrst, 'reload schema';

-- Reverter (PRIMEIRO volte o app: o novo pede a coluna e quebra sem ela;
-- GUARDE antes: select id, conta_erp, contas_somadas from public.controle_aporte_conta;):
--   alter table public.controle_aporte_conta drop constraint if exists controle_aporte_conta_somadas_validas;
--   alter table public.controle_aporte_conta drop column if exists contas_somadas;
