-- -------------------------------------------------- sobras de privilegio
-- Tira TRUNCATE (e as tres sobras da mesma familia: TRIGGER, REFERENCES,
-- MAINTAIN) de `anon` e `authenticated` em TODAS as tabelas do `public`.
--
-- De onde veio: o privilegio PADRAO do projeto para tabela criada pelo papel
-- `postgres` e `anon=Dxtm, authenticated=Dxtm` (D=TRUNCATE, x=REFERENCES,
-- t=TRIGGER, m=MAINTAIN). Toda tabela nasceu com isso, e nenhuma migration
-- revogou -- o comentario de 13/08 ("anon fica de fora em todas") descrevia
-- os DML, nao isto. Conferido ao vivo em 05/10/2026: 17 de 17 tabelas.
--
-- Por que importa: TRUNCATE passa por cima da RLS -- esvazia a tabela inteira
-- sem olhar `privado.e_ativo()`. Hoje nao ha caminho pela API para executa-lo
-- (o PostgREST nao expoe TRUNCATE, e nao existe funcao que rode SQL montado),
-- entao e defesa em profundidade: uma funcao `security invoker` futura com
-- `execute format(...)` bastaria para "qualquer anonimo esvazia `remessa`".
--
-- Nenhum codigo do app usa essas quatro permissoes: o app so faz SELECT,
-- INSERT e UPDATE pela API. Os grants de DML e de coluna NAO sao tocados.
--
-- Parte 2 fecha a porta para tabela NOVA: sem ela, a proxima migration que
-- criar tabela traz as quatro de volta.
--
-- Fica de fora, e por que: o privilegio padrao do `supabase_admin` (que da
-- tudo a anon/authenticated) so pode ser mudado pelo proprio supabase_admin,
-- e nenhuma tabela nossa e criada por ele -- as 17 sao do `postgres`.
--
-- Idempotente: revogar o que ja nao existe nao da erro.

-- 1. As tabelas que ja existem.
revoke truncate, trigger, references, maintain
  on all tables in schema public from anon, authenticated;

-- 2. As tabelas que ainda vao nascer (criadas pelo `postgres`).
alter default privileges for role postgres in schema public
  revoke truncate, trigger, references, maintain on tables
  from anon, authenticated;

-- Aplicado no projeto pelo SQL Editor em 05/10/2026 e conferido no catalogo:
-- nenhuma tabela do public com as quatro para anon/authenticated, padrao do
-- `postgres` = {postgres=arwdDxtm, service_role=Dxtm}, SELECT de
-- authenticated intacto nas 17.
--
-- Reverter:
--   grant truncate, trigger, references, maintain
--     on all tables in schema public to anon, authenticated;
--   alter default privileges for role postgres in schema public
--     grant truncate, trigger, references, maintain on tables
--     to anon, authenticated;
