-- ---------------------------------------------------------------- entidade
-- O app passa a poder CORRIGIR quem paga ou recebe aporte -- e nunca apagar.
--
-- Pedido do dono em 21/10/2026: uma janela "Cadastros" na aba Aportes para
-- ver a lista de Pagou/Recebeu e corrigir nome, contato do ERP, conta e
-- apelido sem passar pelo painel. Ele escolheu "corrigir, sem apagar".
--
-- O que muda em relacao a `entidade_pode_nascer_pelo_app` (01/10):
--
--   insert  -> sim (ja era).
--   update  -> SIM, so nas quatro colunas que o app grava, so para quem tem
--              conta liberada (`privado.e_ativo()`).
--   delete  -> NAO. Tirar alguem da lista continua pelo painel.
--
-- O que isso troca: ate aqui um token vazado de usuario ATIVO so podia SUJAR
-- a lista (acrescentar nomes). Agora pode tambem REESCREVER uma linha -- por
-- exemplo trocar o contato do ERP de uma conta. Nao pode esvaziar a lista, e
-- cada alteracao fica na `auditoria` pelo gatilho abaixo, que roda NO BANCO:
-- um cliente que pule o registro do app nao pula o gatilho.
--
-- Idempotente: pode rodar duas vezes.

drop policy if exists entidade_corrige on public.entidade;

create policy entidade_corrige on public.entidade
  for update to authenticated
  using ((select privado.e_ativo()))
  with check ((select privado.e_ativo()));

-- So as quatro colunas que o app corrige: `id`, `criado_em` e
-- `atualizado_em` (este tocado pelo gatilho `entidade_tocar`) ficam fora.
grant update (nome_exibicao, nome_oficial, conta, nome_descricao)
  on table public.entidade to authenticated;

-- ------------------------------------------------- auditoria da correcao
-- Uma linha por UPDATE que mudou alguma coisa, com o antes e o depois.
--
-- `security definer` porque `authenticated` so pode inserir na `auditoria`
-- com `quem = auth.uid()` -- e e exatamente isso que a funcao grava: o
-- `quem` sai do token de quem fez o UPDATE, pelo default da coluna. O
-- `search_path` vazio e obrigatorio em funcao `security definer` (ver
-- `privado.e_admin`, 30/08).
create or replace function privado.auditar_entidade()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if (old.nome_exibicao, old.nome_oficial, old.conta, old.nome_descricao)
     is distinct from
     (new.nome_exibicao, new.nome_oficial, new.conta, new.nome_descricao) then
    insert into public.auditoria (acao, detalhe)
    values (
      'Cadastro corrigido (Aportes)',
      left(
        format('id %s | antes: %s ; %s ; %s ; %s | depois: %s ; %s ; %s ; %s',
               new.id,
               old.nome_exibicao, old.nome_oficial,
               coalesce(old.conta, '-'), coalesce(old.nome_descricao, '-'),
               new.nome_exibicao, new.nome_oficial,
               coalesce(new.conta, '-'), coalesce(new.nome_descricao, '-')),
        500));
  end if;
  return new;
end;
$$;

revoke all on function privado.auditar_entidade() from public;

drop trigger if exists entidade_auditar on public.entidade;

create trigger entidade_auditar after update on public.entidade
  for each row execute function privado.auditar_entidade();

-- Reverter:
--   drop trigger if exists entidade_auditar on public.entidade;
--   drop function if exists privado.auditar_entidade();
--   drop policy if exists entidade_corrige on public.entidade;
--   revoke update on table public.entidade from authenticated;
