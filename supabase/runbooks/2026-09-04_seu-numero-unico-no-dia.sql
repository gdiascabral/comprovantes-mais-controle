-- =========================================================================
-- Cole isto no SQL Editor do Supabase e rode -- mas leia o passo 1 antes.
-- 04/09/2026 -- a ordem do dia do "seu numero" ganha trava no banco.
--
-- SAO TRES PASSOS, E O PRIMEIRO E UMA CONFERENCIA QUE PODE MUDAR O RESTO.
--
--   1. RODAR O `select` DE REPETICOES (bloco 1 de 3) e LER a resposta.
--      Se ele devolver alguma linha cujo `max(criado_em)` seja POSTERIOR a
--      '2026-09-05T00:00:00+00', o indice unico do bloco 3 NAO vai ser
--      criado -- o Postgres recusa criar indice unico sobre dado que ja o
--      viola, e a recusa vem no meio do script. Nesse caso, ADIE a data do
--      `where` do bloco 3 para depois da maior repeticao (por exemplo, o
--      inicio do dia seguinte) e rode de novo. Nao apague nem edite linha
--      nenhuma de `remessa_item` para fazer o indice caber: o historico e
--      append-only e descreve arquivos que JA SAIRAM para o banco.
--      Resposta vazia, ou so com repeticoes antigas, e o caso normal: as
--      remessas 2, 3 e 4 de 20/08/2026 repetiram 260820-0004...0010, e e
--      exatamente por causa delas que o indice e PARCIAL pela data.
--
--   2. RODAR OS BLOCOS 2 e 3 **ANTES DO MERGE** do PR "ordem do dia com
--      trava". A ordem e a mesma dos outros dois de hoje, pelo mesmo motivo
--      de sempre: o banco primeiro.
--      Aqui o caminho contrario nao quebra nada visivel, e por isso e mais
--      perigoso, nao menos. O codigo novo funciona sem os indices: ele so
--      consulta e numera, como hoje -- so que a consulta dele
--      (`seu_numero like '260904-%'`) vira varredura de tabela sem o indice
--      do bloco 2, e a corrida entre duas maquinas continua sem juiz sem o
--      indice do bloco 3. Ou seja: mergeado primeiro, o app parece bem e
--      continua podendo repetir "seu numero". Rodar isto antes fecha a
--      janela.
--
--   3. NADA para preencher no painel depois. Este arquivo nao cria coluna,
--      nao mexe em politica e nao pede cadastro nenhum.
--
-- Conferir depois: o `select` do fim lista os dois indices pelo nome. Os dois
-- tem de aparecer.
--
-- Os blocos 2 e 3 sao byte a byte iguais a migration
-- `20260904160000_seu_numero_unico_no_dia.sql`, fora este cabecalho, o
-- `select` de repeticoes do bloco 1 e o `select` de conferencia do fim.
-- =========================================================================


-- -------------------------------------------------------------- 1 de 3 --
-- As repeticoes que JA existem. Nao muda nada: so mostra.
--
-- Nao imprime valor, favorecido nem convenio -- so o "seu numero", quantas
-- vezes ele aparece e quando foi a ultima. E o que decide a data do bloco 3.

select seu_numero,
       count(*)        as vezes,
       max(criado_em)  as ultima_vez
  from public.remessa_item
 group by 1
having count(*) > 1
 order by max(criado_em) desc;


-- -------------------------------------------------------------- 2 de 3 --
-- O like por prefixo do dia precisa disto para nao varrer a tabela.
--
-- `text_pattern_ops` e o que faz `seu_numero like '260904-%'` usar indice: o
-- operador padrao de `text` depende do collation do banco e nao serve para
-- comparacao por prefixo.

create index remessa_item_seu_numero_dia_idx
  on public.remessa_item (seu_numero text_pattern_ops);


-- -------------------------------------------------------------- 3 de 3 --
-- A trava. Se o bloco 1 acusou repeticao com `ultima_vez` posterior a data
-- abaixo, MUDE A DATA aqui antes de rodar (ver o passo 1 do cabecalho).
--
-- Parcial pela data porque o historico e append-only e JA tem repeticao de
-- antes desta trava. Reescrever o passado para caber numa regra nova seria
-- mentir sobre ele; a trava vale para o que nascer daqui.

create unique index remessa_item_seu_numero_unico_no_dia
  on public.remessa_item (seu_numero)
  where criado_em >= '2026-09-05T00:00:00+00'::timestamptz;

comment on index public.remessa_item_seu_numero_unico_no_dia is
  'Duas maquinas que leram a mesma "maior ordem do dia" montam arquivos com os '
  'mesmos "seus numeros"; a segunda a gravar e recusada aqui. A data no WHERE e '
  'o comeco da regra, nao um filtro de negocio: o que foi gravado antes dela '
  'descreve arquivos que ja sairam, e nao se reescreve.';


-- ------------------------------------------------------------ conferencia --
-- Os dois indices tem de aparecer aqui. Nao imprime dado de pagamento nenhum.

select indexname, indexdef
  from pg_indexes
 where schemaname = 'public'
   and tablename  = 'remessa_item'
   and indexname in ('remessa_item_seu_numero_dia_idx',
                     'remessa_item_seu_numero_unico_no_dia')
 order by indexname;
