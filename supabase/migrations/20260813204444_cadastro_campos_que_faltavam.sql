-- O que a leitura dos arquivos REAIS mostrou que faltava.
--
-- A migracao anterior foi desenhada a partir dos dataclasses do app. Ler os
-- JSON de verdade antes de migrar achou tres coisas que teriam quebrado -- e
-- uma delas em silencio:
--
-- 1. `banco` quer dizer COISAS DIFERENTES nos dois arquivos. No contas_mc e o
--    NOME que entra no nome do arquivo ("SICOOB", "CAIXA", "INTER"); no
--    contas_sicoob e o CODIGO ("756"). Uma coluna so guardaria um dos dois, e
--    o extrato sairia arquivado como "202607 756.pdf" -- ninguem notaria ate
--    procurar o arquivo do mes.
-- 2. `cnpj`, `razao_social` e `convenio` existem no contas_sicoob e nao
--    estavam no modelo. O `convenio` e o que o gerador CNAB 240 usa: sem ele
--    nao ha remessa.
-- 3. `agencia` existe nas 13 contas do Sicoob e tambem faltava.
--
-- Mais dois cadastros inteiros fora do modelo: as OBRAS de cada subconta e as
-- regras de boleto por e-mail (regras_boletos.json).

-- ------------------------------------------------------------------ empresa

alter table public.empresa
  add column cnpj         text not null default '',
  add column razao_social text not null default '',
  -- Convenio do CNAB 240. Vazio = esta empresa nao gera remessa, e e o estado
  -- normal de quem ainda nao aderiu: 9 das 10 estao assim de proposito.
  add column convenio     text not null default '';

-- Dois convenios iguais gerariam NSA em sequencias que se atropelam.
create unique index empresa_convenio_unico on public.empresa (convenio)
  where convenio <> '';

-- -------------------------------------------------------------------- conta

alter table public.conta
  add column agencia      text not null default '',
  -- Codigo do banco ("756"). O `banco` continua sendo o NOME, porque e ele
  -- que entra no nome do arquivo arquivado.
  add column banco_codigo text not null default '';

comment on column public.conta.banco is
  'Nome do banco como entra no nome do arquivo: SICOOB, CAIXA, INTER.';
comment on column public.conta.banco_codigo is
  'Codigo do banco (756 = Sicoob). Vazio quando nao se sabe.';

-- --------------------------------------------------------- regra_fornecedor

-- `confirmar_sempre` e `confirmar_antes` NAO sao a mesma coisa, e tratar as
-- duas como uma so mandaria pagamento a maquina que devia ir a mao:
--   pagar_a_mao     (era `confirmar_sempre` no regras_fornecedor.json)
--                   a linha nunca e paga automaticamente, ganha "PAGAR A MAO"
--                   e fica FORA da remessa CNAB;
--   confirmar_antes (era a lista `nomes` do confirmar_antes.json)
--                   abre janela de confirmacao ao gerar a planilha; quem for
--                   desmarcado vai para a aba NAO ENTRARAM.
alter table public.regra_fornecedor
  drop constraint regra_fornecedor_tipo_conhecido;

alter table public.regra_fornecedor
  add constraint regra_fornecedor_tipo_conhecido
  check (tipo in ('so_reembolso', 'pagar_a_mao', 'confirmar_antes',
                  'pix_reembolso'));

-- O nome casa por PEDACO, sem acento e sem caixa ("VIDRO ALVES" acha "VIDRO
-- ALVES COMERCIO LTDA"), e quem faz isso e o app. O banco guarda o pedaco.
comment on column public.regra_fornecedor.nome is
  'Pedaco do nome do fornecedor. O casamento por substring, sem acento e sem '
  'caixa, e feito no app.';

-- ------------------------------------------------------------ subconta_obra

-- Cada subconta tem obras alem de investidores. Sem elas, o rateio sabe entre
-- quem dividir e nao sabe o que esta dividindo.
create table public.subconta_obra (
  id          bigint generated always as identity primary key,
  subconta_id bigint not null references public.subconta (id) on delete cascade,
  nome        text not null,
  criado_em   timestamptz not null default now(),
  constraint subconta_obra_unica unique (subconta_id, nome)
);

create index subconta_obra_subconta_idx on public.subconta_obra (subconta_id);

-- A subconta e identificada pelo NUMERO da conta (no formato "00000-0"), e
-- nao por um nome livre.
comment on column public.subconta.nome is
  'Numero da subconta, como no subcontas.json.';

-- ------------------------------------------------------------- regra_boleto

-- regras_boletos.json: como o robo reconhece um boleto que chega por e-mail e
-- a qual fornecedor do ERP ele pertence.
create table public.regra_boleto (
  id               bigint generated always as identity primary key,
  remetente        text not null,
  assunto_contem   text not null default '',
  fornecedor_erp   text not null,
  descricao_contem text not null default '',
  -- Conta de consumo (agua, luz) muda de valor todo mes; mensalidade nao.
  valor_varia      boolean not null default false,
  -- Quantos dias antes do vencimento o boleto costuma chegar.
  janela_dias      integer not null default 0,
  -- Regra ainda nao confirmada por gente nao anexa sozinha.
  automatico       boolean not null default false,
  confirmado_em    date,
  nota             text not null default '',
  criado_em        timestamptz not null default now(),
  atualizado_em    timestamptz not null default now(),
  constraint regra_boleto_unica unique (remetente, assunto_contem, fornecedor_erp),
  constraint regra_boleto_janela_sensata check (janela_dias between 0 and 365),
  -- Automatica sem ninguem ter conferido e o pior dos dois mundos: anexa
  -- sozinha uma regra que nunca foi validada.
  constraint regra_boleto_automatica_foi_conferida
    check (not automatico or confirmado_em is not null)
);

create trigger regra_boleto_tocar before update on public.regra_boleto
  for each row execute function public.tocar_atualizado_em();

-- ----------------------------------------------------------------- acesso

grant select, insert, update, delete on table
  public.subconta_obra,
  public.regra_boleto
to authenticated;

alter table public.subconta_obra enable row level security;
alter table public.regra_boleto  enable row level security;

create policy subconta_obra_autenticado on public.subconta_obra
  for all to authenticated using (true) with check (true);
create policy regra_boleto_autenticado on public.regra_boleto
  for all to authenticated using (true) with check (true);
