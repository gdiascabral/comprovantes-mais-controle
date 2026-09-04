-- =========================================================================
-- Cole isto no SQL Editor do Supabase e rode.
-- 04/09/2026 -- o painel do dia ganha o indice que a pergunta dele pede.
--
-- SAO DOIS BLOCOS, e nenhum deles trava nada.
--
--   1. RODAR O BLOCO 1 (`create index`). E um indice comum: nao cria coluna,
--      nao muda politica, nao recusa INSERT nenhum e nao pede cadastro
--      depois. A tabela `remessa` desta empresa tem dezenas a centenas de
--      linhas, entao ele nasce em menos de um segundo -- num dia em que ela
--      estiver grande, `create index concurrently` faria o mesmo sem
--      bloquear escrita, mas ai teria de rodar FORA de transacao.
--
--   2. A ORDEM EM RELACAO AO MERGE NAO IMPORTA -- e este e o unico arquivo
--      de hoje de que isso vale. Os outros tres (convenio por conta, retorno
--      estado e historico, seu numero unico no dia) tinham de rodar ANTES do
--      merge: os dois primeiros porque o codigo novo cita coluna que o banco
--      nao tinha, o terceiro porque sem o indice unico a corrida entre duas
--      maquinas continua sem juiz. Aqui nao ha nada disso. O codigo do painel
--      do dia funciona sem este indice: ele so faz o Postgres varrer a tabela
--      `remessa` inteira em vez de saltar direto para a faixa do dia.
--      Mergeado primeiro, o painel abre e responde certo, so mais devagar.
--
-- POR QUE ELE E PRECISO. Toda consulta de remessa que existia ate hoje comeca
-- pelo CONVENIO, e o indice `remessa_convenio_idx (convenio, nsa desc)`, de
-- 17/08/2026, atende as duas (`remessas(convenio=)` e a busca do
-- `_ja_enviado`). O painel do dia pergunta pelo outro eixo -- `gerado_em`
-- dentro do dia LOCAL, de TODAS as contas de uma vez -- e um indice cuja
-- PRIMEIRA coluna e o convenio nao responde a isso.
--
-- Conferir depois: o `select` do fim lista o indice pelo nome. Ele tem de
-- aparecer, e nao imprime remessa, valor nem convenio nenhum.
--
-- O bloco 1 e byte a byte igual a migration
-- `20260904181500_remessa_gerado_em_idx.sql`, fora este cabecalho e o
-- `select` de conferencia do fim.
-- =========================================================================


-- -------------------------------------------------------------- 1 de 2 --
-- O indice.
--
-- `desc` porque a pergunta e sempre sobre o passado recente: hoje, ontem, a
-- semana. As linhas mais novas ficam na ponta que o indice le primeiro, e a
-- consulta do painel (`order=gerado_em.asc` dentro de uma faixa de 24 h) e
-- atendida igual -- ordem de indice se percorre nos dois sentidos.

create index remessa_gerado_em_idx on public.remessa (gerado_em desc);

comment on index public.remessa_gerado_em_idx is
  'O painel do dia pergunta por FAIXA DE INSTANTE, sem convenio: '
  '"gerado_em >= inicio do dia local and gerado_em < inicio do dia seguinte". '
  'O indice remessa_convenio_idx (convenio, nsa desc) nao alcanca essa '
  'pergunta, porque o convenio e a primeira coluna dele.';


-- ------------------------------------------------------------ 2 de 2 --
-- Conferencia. O indice tem de aparecer aqui.
--
-- Nao imprime dado de remessa nenhum: so o nome e a definicao do indice.

select indexname, indexdef
  from pg_indexes
 where schemaname = 'public'
   and tablename  = 'remessa'
   and indexname  = 'remessa_gerado_em_idx';
