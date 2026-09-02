-- =========================================================================
-- Cole TUDO isto no SQL Editor do Supabase e rode uma vez so.
-- Sao tres assuntos independentes; se um falhar, os outros seguem valendo.
-- 21/08/2026
-- =========================================================================


-- -------------------------------------------------------------- 1 de 3 --
-- O app poder CADASTRAR conta nova (a janela que abre ao iniciar).
-- Sem isto, a janela pergunta e a gravacao volta com erro de permissao.
--
-- insert -> sim. update -> sim. delete -> NAO (continua so pelo painel).
-- Um token vazado passa a poder sujar o cadastro com linhas a mais (chato e
-- reversivel) em vez de esvazia-lo (irreversivel sem backup).

create policy conta_cadastra on public.conta
  for insert to authenticated with check (true);

create policy conta_corrige on public.conta
  for update to authenticated using (true) with check (true);


-- -------------------------------------------------------------- 2 de 3 --
-- O R$ 1,00 das concessionarias parar de aparecer na janela de conferencia.
-- Primeiro o tipo novo passa a ser aceito, depois as tres entram.

alter table public.regra_fornecedor
  drop constraint regra_fornecedor_tipo_conhecido;

alter table public.regra_fornecedor
  add constraint regra_fornecedor_tipo_conhecido
  check (tipo in ('so_reembolso', 'pagar_a_mao', 'confirmar_antes',
                  'pix_reembolso', 'so_marcador'));

insert into public.regra_fornecedor (tipo, nome) values
  ('so_marcador', 'EQUATORIAL'),
  ('so_marcador', 'SANEAGO'),
  ('so_marcador', 'SANESC')
on conflict (tipo, nome) do nothing;


-- -------------------------------------------------------------- 3 de 3 --
-- A subconta 56173-8 apontar para o nome EXATO que existe no ERP.
-- O cadastro tinha o nome curto; o ERP tem o endereco no fim.

update public.entidade
   set conta = 'Morais Participações - SUBCONTA 56173-8 - TB 19 QD 50 LT 11 E 14 - SICOOB'
 where nome_exibicao = 'PARTICIPAÇÕES SUBCONTA 56173-8 - SICOOB';


-- ------------------------------------------------------------ conferir --
-- As tres respostas, na ordem. Nenhuma deve vir vazia.

select 'politicas da conta' as o_que, policyname as valor
  from pg_policies where tablename = 'conta'
union all
select 'concessionarias', nome
  from public.regra_fornecedor where tipo = 'so_marcador'
union all
select 'subconta 56173-8', coalesce(conta, '(vazio)')
  from public.entidade
 where nome_exibicao = 'PARTICIPAÇÕES SUBCONTA 56173-8 - SICOOB';
