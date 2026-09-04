-- O retorno do banco deixa de caber numa coluna só.
--
-- Desde 17/08 o item guarda `retorno_codigo` e `retorno_em`, e a auditoria de
-- 04/09/2026 mediu três coisas que essas duas não conseguem dizer:
--
--   1. **o segundo retorno APAGA o primeiro.** No fluxo desta empresa quem
--      gera não é quem assina: o retorno do mesmo dia vem `PD` (pendente de
--      assinatura) e o desfecho só aparece depois que o master libera. Gravar
--      `00` por cima do `PD` é o desfecho certo para "qual é a resposta
--      AGORA" e a perda da única prova de que o arquivo foi ACEITO antes;
--   2. **o banco manda mais de uma ocorrência por pagamento**, e só a
--      primeira sobrava;
--   3. **quem quiser contar pago/pendente/rejeitado** tinha de traduzir
--      código de ocorrência de novo, fora do `retorno_dia`, que é onde essa
--      classificação já é feita uma vez.
--
-- Duas colunas resolvem as três, e nenhuma delas apaga o que já está gravado:
-- `retorno_codigo` continua sendo A RESPOSTA DE AGORA (agora com todas as
-- ocorrências, separadas por `;`), e o passado passa a caber em
-- `retorno_historico`.
--
-- `text not null default ''` como todo o resto da tabela: item antigo nasce
-- com string vazia e o app lê com `.get(..., "")`, então a ordem entre aplicar
-- isto e subir o código não trava nada — antes da migration o app grava as
-- duas colunas de sempre; depois, as quatro.

alter table public.remessa_item
  -- A classificação que o `pagamentos_dia/retorno_dia.py` já faz ao ler o
  -- arquivo: "ok" | "pendente" | "rejeitado" | "?". Gravá-la é o que permite
  -- ao painel do dia contar pago/pendente/rejeitado por item SEM reabrir o
  -- arquivo de retorno e sem uma segunda tabela de códigos de ocorrência —
  -- que seria a segunda verdade sobre o que "AG" quer dizer.
  --
  -- Sem `check`, pelo mesmo motivo da coluna `estado` da `remessa`: a lista
  -- vive no código e duplicá-la aqui criaria duas respostas para "o que é um
  -- estado válido", com a do banco envelhecendo calada.
  add column retorno_estado    text not null default '',
  -- Tudo que o banco já disse sobre este item, em ordem, uma entrada por
  -- retorno lido: `AAAA-MM-DD HH:MM codigo=estado`, separadas por `;`. É
  -- append-only por convenção do app (o `aplicar_retorno` concatena, nunca
  -- substitui) — a mesma regra que já vale para a tabela inteira, onde não há
  -- `delete` para ninguém.
  --
  -- Uma coluna de texto e não uma tabela `remessa_item_retorno`: o que se
  -- pergunta dela é "o que o banco disse antes?", lido por gente, junto do
  -- item, e nunca agregado nem filtrado. Uma tabela a mais custaria um join
  -- em todo lugar que hoje pede `remessa_item(*)` para pagar por uma consulta
  -- que ninguém faz.
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

-- O privilégio é de COLUNA, como o de 17/08: `update` na tabela inteira
-- deixaria reescrever valor, favorecido e referência, que descrevem um
-- arquivo que já saiu do banco. A política de update do item
-- (`remessa_item_retorno`) já existe e já exige `privado.e_ativo()` desde
-- 30/08 — não nasce política nova aqui, e não pode nascer: uma política a
-- mais para a mesma operação é um OU, e afrouxaria a porteira.
--
-- `retorno_codigo` e `retorno_em` são repetidos de propósito, ainda que o
-- `grant` do Postgres seja acumulativo e as duas já estejam concedidas desde
-- 17/08: assim esta linha diz, sozinha, o conjunto INTEIRO de colunas que o
-- app pode escrever no item — que é a pergunta que se faz a ela.
grant update (retorno_codigo, retorno_em, retorno_estado, retorno_historico)
  on table public.remessa_item to authenticated;
