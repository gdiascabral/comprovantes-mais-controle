-- O app só LÊ cadastro. Então é só isso que ele pode fazer.
--
-- As políticas nasceram `for all`, e isso dava a qualquer pessoa logada o
-- poder de apagar o cadastro inteiro por uma chamada de API -- um poder que
-- nenhuma linha do app exerce. A edição acontece no painel do Supabase, que
-- entra com a chave de serviço e ignora a RLS, então tirar a escrita daqui
-- não tira função de ninguém: tira só o estrago possível.
--
-- O que isto impede, concretamente: token de alguém vazado (ou pessoa que
-- saiu e ainda tem sessão válida) passa a poder ler o cadastro -- ruim -- em
-- vez de poder esvaziá-lo -- irreversível sem backup.

drop policy empresa_autenticado             on public.empresa;
drop policy cliente_erp_autenticado         on public.cliente_erp;
drop policy conta_autenticado               on public.conta;
drop policy pasta_vazia_autenticado         on public.pasta_vazia;
drop policy entidade_autenticado            on public.entidade;
drop policy subconta_autenticado            on public.subconta;
drop policy subconta_obra_autenticado       on public.subconta_obra;
drop policy subconta_investidor_autenticado on public.subconta_investidor;
drop policy regra_fornecedor_autenticado    on public.regra_fornecedor;
drop policy regra_boleto_autenticado        on public.regra_boleto;
drop policy configuracao_autenticado        on public.configuracao;

create policy empresa_le on public.empresa
  for select to authenticated using (true);
create policy cliente_erp_le on public.cliente_erp
  for select to authenticated using (true);
create policy conta_le on public.conta
  for select to authenticated using (true);
create policy pasta_vazia_le on public.pasta_vazia
  for select to authenticated using (true);
create policy entidade_le on public.entidade
  for select to authenticated using (true);
create policy subconta_le on public.subconta
  for select to authenticated using (true);
create policy subconta_obra_le on public.subconta_obra
  for select to authenticated using (true);
create policy subconta_investidor_le on public.subconta_investidor
  for select to authenticated using (true);
create policy regra_fornecedor_le on public.regra_fornecedor
  for select to authenticated using (true);
create policy regra_boleto_le on public.regra_boleto
  for select to authenticated using (true);
create policy configuracao_le on public.configuracao
  for select to authenticated using (true);

-- O privilégio de tabela acompanha a política: sem isto, `authenticated`
-- continuaria com o GRANT de insert/update/delete concedido na primeira
-- migração, e um dia alguém escreveria uma política de escrita sem perceber
-- que o privilégio já estava lá esperando.
revoke insert, update, delete on table
  public.empresa,
  public.cliente_erp,
  public.conta,
  public.pasta_vazia,
  public.entidade,
  public.subconta,
  public.subconta_obra,
  public.subconta_investidor,
  public.regra_fornecedor,
  public.regra_boleto,
  public.configuracao
from authenticated;

-- Quem ESCREVE é a administração: o painel e o `nuvem/migrar.py`, os dois
-- com a chave de serviço. Ela tem BYPASSRLS, mas privilégio de TABELA é
-- outra coisa e precisa ser concedido -- o projeto foi criado sem expor
-- tabela automaticamente, e sem isto a migração falha com "permission
-- denied", que soa como problema de RLS e não é.
grant select, insert, update, delete on table
  public.empresa,
  public.cliente_erp,
  public.conta,
  public.pasta_vazia,
  public.entidade,
  public.subconta,
  public.subconta_obra,
  public.subconta_investidor,
  public.regra_fornecedor,
  public.regra_boleto,
  public.configuracao
to service_role;

grant usage on all sequences in schema public to service_role;
