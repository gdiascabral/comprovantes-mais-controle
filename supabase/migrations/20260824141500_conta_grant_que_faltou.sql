-- ------------------------------------------------------------------- conta
-- O GRANT que faltou na migration de 21/08.
--
-- Aquela criou as POLITICAS (`conta_cadastra`, `conta_corrige`) e parou ai. Mas
-- a migration de 14/08 (`app_so_le`) tinha feito `revoke insert, update,
-- delete`, e no Postgres o privilegio vem ANTES da politica: sem o grant, a
-- politica nem chega a ser consultada.
--
-- O sintoma foi um cadastro de conta recusado com "permission denied for table
-- conta" -- que e a frase do GRANT, nao a do RLS (essa diria "new row violates
-- row-level security policy"). As duas so ficaram distinguiveis depois que o
-- `rest.py` parou de transformar 401 e 403 na mesma frase.
--
-- `delete` continua revogado, como em 14/08: apagar cadastro segue sendo
-- assunto do painel do Supabase.

grant insert, update on table public.conta to authenticated;
