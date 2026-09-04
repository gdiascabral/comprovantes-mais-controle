-- O "seu numero" do dia deixa de depender de quem leu primeiro.
--
-- O "seu numero" de cada pagamento e `yymmdd-NNNN[-OC...]`, 20 posicoes que
-- NOS definimos e que o banco devolve IDENTICAS no arquivo de retorno. E por
-- elas que cada resposta do banco reencontra o lancamento de origem. A ordem
-- do dia (`NNNN`) precisa ser unica entre TODAS as remessas daquele dia, de
-- todas as contas e de todas as maquinas: repetida, o retorno casa com o
-- pagamento errado.
--
-- O que existia ate hoje: `remessa_item_seu_numero_unico unique (remessa_id,
-- seu_numero)`, da migration `20260817145337`. Ela vale so DENTRO da mesma
-- remessa -- e o defeito de 20/08/2026 foi entre remessas DIFERENTES do mesmo
-- dia. Fora do banco havia uma conferencia em Python que lia o maior numero ja
-- usado, e ler nao trava nada: duas maquinas gerando no mesmo instante leem o
-- mesmo maior e escrevem os mesmos numeros.
--
-- Daqui em diante quem decide e o banco, na hora do INSERT. O app continua
-- consultando antes -- e o consulta em UMA linha, o que este primeiro indice
-- torna possivel -- para que a recusa seja rara; a recusa e a trava, a consulta
-- e a cortesia.

-- O like por prefixo do dia precisa disto para nao varrer a tabela.
create index remessa_item_seu_numero_dia_idx
  on public.remessa_item (seu_numero text_pattern_ops);

-- Parcial pela data porque o historico e append-only e JA tem repeticao de
-- antes desta trava (as remessas 2, 3 e 4 de 20/08/2026 repetiram
-- 260820-0004...0010). Reescrever o passado para caber numa regra nova seria
-- mentir sobre ele; a trava vale para o que nascer daqui.
create unique index remessa_item_seu_numero_unico_no_dia
  on public.remessa_item (seu_numero)
  where criado_em >= '2026-09-05T00:00:00+00'::timestamptz;

comment on index public.remessa_item_seu_numero_unico_no_dia is
  'Duas maquinas que leram a mesma "maior ordem do dia" montam arquivos com os '
  'mesmos "seus numeros"; a segunda a gravar e recusada aqui. A data no WHERE e '
  'o comeco da regra, nao um filtro de negocio: o que foi gravado antes dela '
  'descreve arquivos que ja sairam, e nao se reescreve.';

-- ------------------------------------------------- o que NAO muda aqui
-- Nenhum `grant` e nenhuma politica: indice nao tem RLS, e `remessa_item` ja
-- tem as suas desde 17/08 (`remessa_item_le`, `remessa_item_grava`,
-- `remessa_item_retorno`), todas atras da porteira `privado.e_ativo()` de
-- 30/08. Um indice novo nao abre nem fecha porta nenhuma -- so decide o que o
-- INSERT aceita.
--
-- Nada de `on conflict` tambem: a recusa TEM de subir. Engoli-la aqui
-- devolveria a remessa como se tivesse sido gravada, sem os itens que o
-- retorno do banco vai procurar.
