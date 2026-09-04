-- A pergunta "o que saiu HOJE, de todas as contas" ganha indice.
--
-- Ate hoje toda consulta de remessa comecava pelo CONVENIO: `remessas()`
-- filtra `convenio=eq.…`, `_procurar` casa item e remessa, e o indice
-- `remessa_convenio_idx (convenio, nsa desc)` de 17/08/2026 atende os dois.
-- O painel do dia (`pagamentos_dia/painel_dia.py`) faz a pergunta pelo outro
-- eixo: `gerado_em` entre o inicio e o fim do dia LOCAL, sem convenio nenhum,
-- de todas as contas de uma vez. Um indice por `(convenio, nsa)` nao responde
-- a isso -- o convenio e a primeira coluna, e sem ele o Postgres varre a
-- tabela.
--
-- `desc` porque a pergunta e sempre sobre o passado recente: o dia de hoje,
-- ontem, a semana. As linhas mais novas ficam na ponta que o indice le
-- primeiro, e a consulta do painel (`order=gerado_em.asc` dentro de uma
-- faixa de 24 h) e atendida igual -- ordem de indice se percorre nos dois
-- sentidos.
--
-- ------------------------------------------------- o que NAO muda aqui
-- Nenhum `grant` e nenhuma politica: indice nao tem RLS, e `remessa` ja tem
-- as suas desde 17/08 (`remessa_le`, `remessa_grava`, `remessa_marca`), todas
-- atras da porteira `privado.e_ativo()` de 30/08. Um indice novo nao abre nem
-- fecha porta nenhuma -- so muda o CAMINHO que o banco percorre para
-- responder o que ja respondia.
--
-- Nenhuma coluna nova, nenhum `check` e nenhum `unique`: este indice nao
-- trava nada. E por isso que **a ordem nao trava** -- o codigo do painel
-- funciona sem ele, so mais lento, e o app mergeado antes deste arquivo nao
-- quebra em lugar nenhum. E o unico par runbook/migration deste projeto em
-- que os dois lados podem entrar em qualquer ordem.

create index remessa_gerado_em_idx on public.remessa (gerado_em desc);

comment on index public.remessa_gerado_em_idx is
  'O painel do dia pergunta por FAIXA DE INSTANTE, sem convenio: '
  '"gerado_em >= inicio do dia local and gerado_em < inicio do dia seguinte". '
  'O indice remessa_convenio_idx (convenio, nsa desc) nao alcanca essa '
  'pergunta, porque o convenio e a primeira coluna dele.';
