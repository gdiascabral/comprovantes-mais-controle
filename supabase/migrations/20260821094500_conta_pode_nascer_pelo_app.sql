-- ------------------------------------------------------------------- conta
-- O app passa a poder CADASTRAR conta nova -- e so isso.
--
-- Em 20/08/2026 nasceram quatro contas no Mais Controle e o app nao soube. A
-- unica deteccao que existia era a da Conciliacao, que marca o LANCAMENTO em
-- conta desconhecida DEPOIS que alguem ja pagou por ali. A partir de agora o
-- app confere na abertura e pergunta ao dono; para a resposta dele valer, ele
-- precisa poder escrever a linha.
--
-- A decisao de 14/08 ("o app so LE cadastro") muda no MINIMO necessario:
--
--   insert  -> sim. E a resposta do dono virando cadastro.
--   update  -> sim. Renomear conta no ERP muda o `nome_erp`, e sem isto a
--              correcao continuaria sendo trabalho de painel.
--   delete  -> NAO. Continua so pelo painel do Supabase.
--
-- O que isso troca, dito claro: um token vazado passa a poder SUJAR o cadastro
-- com linhas a mais -- chato e reversivel -- em vez de ESVAZIA-LO, que e
-- irreversivel sem backup. Era exatamente esse o estrago que 14/08 tirou de
-- cima da mesa, e ele continua fora.
--
-- O Mais Controle nao e tocado por nada disto: conta nasce la, por gente.

create policy conta_cadastra on public.conta
  for insert to authenticated with check (true);

create policy conta_corrige on public.conta
  for update to authenticated using (true) with check (true);
