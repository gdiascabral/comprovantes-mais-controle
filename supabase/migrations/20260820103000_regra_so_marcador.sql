-- ------------------------------------------------------- regra_fornecedor
-- Tipo novo: so_marcador.
--
-- A concessionaria de energia ou agua lanca no ERP uma linha de exatamente
-- R$ 1,00 por unidade consumidora, so para o titulo nascer no mes. Nao e
-- pagamento: e marcador de recorrencia. Ate 20/08/2026 ele aparecia na janela
-- "2. Confirmar o que entra" e era desmarcado a mao, todo dia.
--
-- A marca e por NOME, e nao por valor: ela diz "R$ 1,00 DESTE fornecedor nao e
-- pagamento", e nao "R$ 1,00 nunca e pagamento" — que descartaria calado a taxa
-- de um real que um dia exista de verdade.
--
-- Precisa morar aqui, e nao no regras_fornecedor.json ao lado do exe: aquele
-- arquivo e reescrito a cada abertura a partir deste cadastro, e uma marca
-- posta a mao la sumiria na sincronizacao seguinte.
alter table public.regra_fornecedor
  drop constraint regra_fornecedor_tipo_conhecido;

alter table public.regra_fornecedor
  add constraint regra_fornecedor_tipo_conhecido
  check (tipo in ('so_reembolso', 'pagar_a_mao', 'confirmar_antes',
                  'pix_reembolso', 'so_marcador'));

-- As concessionarias em si NAO entram aqui: nome de fornecedor e cadastro do
-- escritorio, nao esquema. Elas se cadastram pela tela, como as demais regras.
