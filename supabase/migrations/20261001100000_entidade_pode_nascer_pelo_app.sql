-- ---------------------------------------------------------------- entidade
-- O app passa a poder CADASTRAR quem paga ou recebe aporte -- e so isso.
--
-- Em 01/10/2026 nasceu uma conta nova no Mais Controle; a janela de contas
-- novas a trouxe para `conta`, mas para lancar o primeiro aporte dela era
-- preciso uma linha em `entidade`, e isso so se fazia por SQL no painel. O
-- botao "Novo cadastro" da aba Aportes grava essa linha.
--
-- Mesmo recorte da migracao de 21/08 (`conta_pode_nascer_pelo_app`), ja
-- com a porteira de 30/08 (`privado.e_ativo()`):
--
--   insert  -> sim, para quem tem conta liberada.
--   update  -> NAO. Corrigir nome continua pelo painel.
--   delete  -> NAO. Idem.
--
-- O que isso troca: um token vazado de usuario ATIVO pode acrescentar nomes
-- a lista de Pagou/Recebeu -- chato e reversivel, e o lancamento ainda
-- passaria pela conferencia de nomes contra o ERP. Nao pode esvaziar nem
-- reescrever o cadastro.
--
-- Idempotente: pode rodar duas vezes.

drop policy if exists entidade_cadastra on public.entidade;

create policy entidade_cadastra on public.entidade
  for insert to authenticated
  with check ((select privado.e_ativo()));

-- So as quatro colunas que o app grava: `criado_em`/`atualizado_em` ficam
-- com o default, e um token nao forja data.
grant insert (nome_exibicao, nome_oficial, conta, nome_descricao)
  on table public.entidade to authenticated;

-- `id` e identity: o Postgres nao confere privilegio na sequencia ao gerar o
-- valor; e `authenticated` ja tem usage em todas desde 13/08.

-- Reverter:
--   drop policy if exists entidade_cadastra on public.entidade;
--   revoke insert on table public.entidade from authenticated;
