-- Cole no SQL Editor do Supabase (projeto do cadastro) e rode.
-- Fora do repositorio de proposito: as duas ultimas partes sao CADASTRO do
-- escritorio (nome de fornecedor), e o repositorio e publico.

-- 1) o tipo novo passa a ser aceito pela tabela ------------------------------
alter table public.regra_fornecedor
  drop constraint regra_fornecedor_tipo_conhecido;

alter table public.regra_fornecedor
  add constraint regra_fornecedor_tipo_conhecido
  check (tipo in ('so_reembolso', 'pagar_a_mao', 'confirmar_antes',
                  'pix_reembolso', 'so_marcador'));

-- 2) as tres concessionarias -------------------------------------------------
-- O nome casa por PEDACO, sem acento e sem caixa: 'EQUATORIAL' acha
-- 'Equatorial Goias Distribuidora S/A'. Concessionaria nova e uma linha aqui.
insert into public.regra_fornecedor (tipo, nome) values
  ('so_marcador', 'EQUATORIAL'),
  ('so_marcador', 'SANEAGO'),
  ('so_marcador', 'SANESC')
on conflict (tipo, nome) do nothing;

-- 3) conferir ----------------------------------------------------------------
select tipo, nome from public.regra_fornecedor
 where tipo = 'so_marcador' order by nome;


-- =========================================================================
-- 21/08/2026 - contas que a aba Aportes acusou como NAO ENCONTRADA
-- =========================================================================

-- 1) Vincular a subconta 56173-8 ao nome EXATO que existe no ERP.
--    O que estava cadastrado era o nome curto; o ERP tem o endereco no fim.
update public.entidade
   set conta = 'Morais Participações - SUBCONTA 56173-8 - TB 19 QD 50 LT 11 E 14 - SICOOB'
 where nome_exibicao = 'PARTICIPAÇÕES SUBCONTA 56173-8 - SICOOB';

-- 2) IPANEMA - INTER: decisao do dono e desconsiderar por enquanto.
--    ATENCAO: enquanto a linha existir, a conferencia vai continuar
--    acusando "NAO ENCONTRADA" toda vez. Para calar o aviso, ou a conta e
--    criada no ERP e o nome dela vai na coluna `conta`, ou a linha sai daqui.
--    Descomente a linha abaixo SO se decidir tirar do cadastro:
-- delete from public.entidade where nome_exibicao = 'IPANEMA - INTER';

-- 3) conferir
select nome_exibicao, conta from public.entidade
 where nome_exibicao in ('PARTICIPAÇÕES SUBCONTA 56173-8 - SICOOB',
                         'IPANEMA - INTER');
