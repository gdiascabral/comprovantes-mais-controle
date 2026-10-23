-- ------------------------------------------------------------------- conta
-- O app pode CORRIGIR o nome da conta no ERP (`nome_erp`) -- e so isso.
--
-- O caso de 23/10/2026: o dono renomeou uma subconta no Mais Controle (pos o
-- ponto do milhar no numero). A janela "Contas novas no Mais Controle"
-- comparava so pelo nome, listou a conta como nova, e o "Incluir" levou
-- `HTTP 409 ... conta_numero_unico`: a conta ja estava no cadastro, com o
-- nome antigo. Agora o app reconhece a conta pelo NUMERO e o "Incluir" faz
-- UPDATE do `nome_erp` dela (PATCH por id), nunca INSERT.
--
-- O que muda em relacao a 21/08 + 24/08 (`conta_corrige` e o
-- `grant insert, update on table public.conta`):
--
--   insert  -> sim (ja era). Conta nova pela janela.
--   update  -> SO a coluna `nome_erp`. O grant de 24/08 era de TABELA: um
--              token vazado de usuario ativo podia reescrever pasta, numero,
--              convenio ou empresa de qualquer conta -- e nenhuma linha do
--              app faz isso (o unico PATCH em `conta` e o do nome). O UPDATE
--              de tabela e revogado e volta so na coluna. `atualizado_em`
--              fica fora: quem o toca e o gatilho `conta_tocar`, e privilegio
--              de coluna e conferido so no que o cliente manda.
--   delete  -> NAO. Continua so pelo painel do Supabase.
--
-- Cada correcao vai para a `auditoria` pelo gatilho abaixo, que roda NO
-- BANCO: um cliente que pule o registro do app nao pula o gatilho.
--
-- Idempotente: pode rodar duas vezes. Tudo numa transacao: politica, grant,
-- funcao e gatilho so fazem sentido juntos.

begin;

-- A mesma porteira de 30/08 (`privado.e_ativo()`), recriada aqui para o
-- arquivo dizer sozinho quem pode corrigir.
drop policy if exists conta_corrige on public.conta;

create policy conta_corrige on public.conta
  for update to authenticated
  using ((select privado.e_ativo()))
  with check ((select privado.e_ativo()));

-- Revogar o de TABELA leva junto os de coluna; o de coluna volta logo abaixo.
revoke update on table public.conta from authenticated;
grant update (nome_erp) on table public.conta to authenticated;

-- ------------------------------------------------- auditoria da correcao
-- Uma linha por UPDATE que mudou o nome, com o antes e o depois.
--
-- `security definer` para nao depender de grants futuros na `auditoria`. O
-- `quem` continua saindo do token de quem fez o UPDATE, pelo default da
-- coluna (`auth.uid()` le o JWT da requisicao, nao o papel). O `search_path`
-- vazio e obrigatorio em funcao `security definer` (ver `privado.e_admin`).
--
-- Correcao pelo painel ou pelo SQL Editor (papel postgres) e pela chave de
-- servico NAO tem usuario no token: `auditoria.quem` e not null e FK para
-- `auth.users`, e sem o desvio abaixo o UPDATE inteiro seria recusado --
-- trancando o caminho oficial de corrigir. Essas correcoes seguem sem
-- auditoria, como sempre foram.
create or replace function privado.auditar_conta_nome()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
  if (select auth.uid()) is null then
    return new;
  end if;
  if old.nome_erp is distinct from new.nome_erp then
    insert into public.auditoria (acao, detalhe)
    values (
      'Nome da conta corrigido (contas novas)',
      left(
        format('conta id %s | antes: %s | depois: %s',
               new.id, coalesce(old.nome_erp, '-'),
               coalesce(new.nome_erp, '-')),
        500));
  end if;
  return new;
end;
$$;

revoke all on function privado.auditar_conta_nome() from public, anon, authenticated;

drop trigger if exists conta_auditar_nome on public.conta;

create trigger conta_auditar_nome after update on public.conta
  for each row execute function privado.auditar_conta_nome();

commit;

notify pgrst, 'reload schema';

-- Reverter (volta ao estado de 24/08, UPDATE de tabela):
--   drop trigger if exists conta_auditar_nome on public.conta;
--   drop function if exists privado.auditar_conta_nome();
--   revoke update (nome_erp) on table public.conta from authenticated;
--   grant update on table public.conta to authenticated;
