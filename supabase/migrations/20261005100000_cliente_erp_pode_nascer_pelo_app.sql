-- ------------------------------------------------------------- cliente_erp
-- O app passa a poder CADASTRAR "este cliente do ERP e desta empresa" -- e
-- so isso.
--
-- A aba Contratos pergunta, na hora de arquivar, de qual empresa e o cliente
-- de uma obra. A resposta ia so para o `contas_sicoob.json`, que e CACHE: a
-- abertura seguinte o regrava a partir desta tabela, a escolha sumia e a casa
-- voltava a pedir resolucao no mes seguinte. Agora `nuvem/clientes_erp.py`
-- grava aqui primeiro.
--
-- Mesmo recorte da `entidade_pode_nascer_pelo_app` (01/10), ja com a
-- porteira de 30/08 (`privado.e_ativo()`):
--
--   insert  -> sim, para quem tem conta liberada.
--   update  -> NAO. Mudar um cliente de empresa continua pelo painel.
--   delete  -> NAO. Idem.
--
-- O que isso troca: um token vazado de usuario ATIVO pode acrescentar nomes
-- de cliente a uma empresa -- chato e reversivel. Nao pode tirar cliente de
-- uma empresa nem move-lo para outra: o indice unico `cliente_erp_nome_unico`
-- (lower(nome)) recusa o mesmo nome numa segunda empresa.
--
-- Idempotente: pode rodar duas vezes.

drop policy if exists cliente_erp_cadastra on public.cliente_erp;

create policy cliente_erp_cadastra on public.cliente_erp
  for insert to authenticated
  with check ((select privado.e_ativo()));

-- So as duas colunas que o app grava: `criado_em`/`atualizado_em` ficam com
-- o default, e um token nao forja data.
grant insert (empresa_id, nome) on table public.cliente_erp to authenticated;

-- `id` e identity: o Postgres nao confere privilegio na sequencia ao gerar o
-- valor; e `authenticated` ja tem usage em todas desde 13/08.

-- Reverter:
--   drop policy if exists cliente_erp_cadastra on public.cliente_erp;
--   revoke insert on table public.cliente_erp from authenticated;
