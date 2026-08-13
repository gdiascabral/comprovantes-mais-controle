-- Cadastro compartilhado: o que hoje mora em JSON/CSV ao lado do executavel.
--
-- A decisao central esta na tabela `conta`: hoje a MESMA conta e descrita em
-- dois arquivos (contas_mc.json e contas_sicoob.json), cada um com a sua pasta
-- de destino. Eles ja divergiram em tres subcontas e partiram julho/2026 ao
-- meio, com o PDF do ERP numa pasta e o OFX na outra. Aqui ha UMA linha por
-- conta e UMA coluna `pasta`: a divergencia deixa de ser detectavel porque
-- deixa de ser representavel.
--
-- Acesso: as 2 a 5 pessoas veem tudo. Nao ha separacao por usuario, entao as
-- politicas sao `to authenticated using (true)`. O que protege e a fronteira
-- entre "logado" e "nao logado" -- `anon` nao recebe grant nenhum e nao tem
-- politica, logo nao le nada. Com o cadastro publico desligado no projeto,
-- nao existe como virar `authenticated` sem convite.

-- ---------------------------------------------------------------- utilitario

-- Toda tabela carrega `atualizado_em`, e nao por enfeite: e por ele que o
-- cache local decide se precisa baixar de novo em vez de puxar tudo sempre.
create or replace function public.tocar_atualizado_em()
returns trigger
language plpgsql
set search_path = ''
as $$
begin
  new.atualizado_em = now();
  return new;
end;
$$;

-- ------------------------------------------------------------------ empresa

create table public.empresa (
  id            bigint generated always as identity primary key,
  nome_pasta    text not null,
  -- Id desta empresa na URL do portal contabil. Nao se deriva do nome nem do
  -- CNPJ: e cadastro. Vazio = a aba Acessorias nao envia esta empresa.
  vip_id        text not null default '',
  -- Como o nome entra no ASSUNTO da solicitacao (razao social por extenso).
  -- Vazio = usa `nome_pasta`.
  vip_nome      text not null default '',
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  constraint empresa_nome_pasta_unico unique (nome_pasta),
  constraint empresa_nome_pasta_nao_vazio check (length(trim(nome_pasta)) > 0)
);

create trigger empresa_tocar before update on public.empresa
  for each row execute function public.tocar_atualizado_em();

-- -------------------------------------------------------------- cliente_erp

-- Nomes com que a empresa aparece como CLIENTE das obras no ERP. Um cliente
-- pertence a UMA empresa: contrato arquivado na empresa errada nao se denuncia
-- sozinho, e essa e a mesma regra que `sicoob_contas.validar()` ja aplica.
create table public.cliente_erp (
  id            bigint generated always as identity primary key,
  empresa_id    bigint not null references public.empresa (id) on delete cascade,
  nome          text not null,
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

-- Unico ignorando caixa. O nome vem do cadastro do ERP, digitado por gente.
-- Acento continua sendo normalizado no app (`util.norm_espaco`): `unaccent`
-- nao e imutavel e por isso nao entra em indice sem um embrulho proprio.
create unique index cliente_erp_nome_unico on public.cliente_erp (lower(nome));
create index cliente_erp_empresa_idx on public.cliente_erp (empresa_id);

create trigger cliente_erp_tocar before update on public.cliente_erp
  for each row execute function public.tocar_atualizado_em();

-- -------------------------------------------------------------------- conta

create table public.conta (
  id            bigint generated always as identity primary key,
  empresa_id    bigint not null references public.empresa (id) on delete restrict,
  -- Como a pessoa escreve ("00.000-0"). Nulo em conta que nao e Sicoob.
  numero        text,
  -- Comparacao por digitos: o OFX traz o ACCTID sem pontuacao e a pessoa
  -- digita com. Coluna gerada para o unico valer sobre a forma comparavel.
  numero_digitos text generated always as
                 (nullif(regexp_replace(coalesce(numero, ''), '\D', '', 'g'), '')) stored,
  -- Nome exato da conta no Mais Controle. Nulo em conta que o ERP nao tem.
  nome_erp      text,
  -- Subpasta dentro da empresa. Aceita subnivel ("BANCO/APLICACAO").
  pasta         text not null,
  -- Entra no nome do arquivo arquivado.
  banco         text not null default '',
  -- Desempate quando varias contas da mesma empresa dividem uma pasta.
  sufixo        text not null default '',
  ativa         boolean not null default true,
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  -- Conta que nao tem numero NEM nome no ERP nao e identificavel por lado
  -- nenhum: nao daria para casar o extrato nem para achar no ERP.
  constraint conta_identificavel check (numero is not null or nome_erp is not null),
  constraint conta_pasta_nao_vazia check (length(trim(pasta)) > 0),
  -- Quatro contas da mesma empresa podem dividir a MESMA pasta (e para isso
  -- que existe o sufixo). O que nao pode e duas caindo no mesmo arquivo.
  constraint conta_destino_unico unique (empresa_id, pasta, sufixo)
);

create unique index conta_numero_unico on public.conta (numero_digitos)
  where numero_digitos is not null;
create unique index conta_nome_erp_unico on public.conta (lower(nome_erp))
  where nome_erp is not null;
create index conta_empresa_idx on public.conta (empresa_id);

create trigger conta_tocar before update on public.conta
  for each row execute function public.tocar_atualizado_em();

-- -------------------------------------------------------------- pasta_vazia

-- Pastas que so sao CRIADAS na arvore do fechamento: bancos que estao fora
-- desta automacao, mas cuja pasta precisa existir para alguem por o extrato
-- a mao.
create table public.pasta_vazia (
  id            bigint generated always as identity primary key,
  empresa_id    bigint not null references public.empresa (id) on delete cascade,
  nome          text not null,
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  constraint pasta_vazia_unica unique (empresa_id, nome)
);

create index pasta_vazia_empresa_idx on public.pasta_vazia (empresa_id);

create trigger pasta_vazia_tocar before update on public.pasta_vazia
  for each row execute function public.tocar_atualizado_em();

-- ----------------------------------------------------------------- entidade

-- O atual contas.csv: pessoas e empresas que aportam ou recebem.
create table public.entidade (
  id             bigint generated always as identity primary key,
  nome_exibicao  text not null,
  nome_oficial   text not null default '',
  conta          text,
  -- Apelido usado SO no texto da descricao: existe para conta conjunta, em que
  -- o lancamento sai no nome de uma pessoa mas a descricao cita as duas.
  nome_descricao text,
  criado_em      timestamptz not null default now(),
  atualizado_em  timestamptz not null default now(),
  constraint entidade_nome_exibicao_unico unique (nome_exibicao),
  constraint entidade_nome_nao_vazio check (length(trim(nome_exibicao)) > 0)
);

create trigger entidade_tocar before update on public.entidade
  for each row execute function public.tocar_atualizado_em();

-- ---------------------------------------------------------------- subcontas

-- O atual subcontas.json: grupos de investidores por subconta.
create table public.subconta (
  id            bigint generated always as identity primary key,
  nome          text not null,
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  constraint subconta_nome_unico unique (nome)
);

create trigger subconta_tocar before update on public.subconta
  for each row execute function public.tocar_atualizado_em();

create table public.subconta_investidor (
  subconta_id bigint not null references public.subconta (id) on delete cascade,
  -- `restrict`: apagar uma entidade que ainda rateia dinheiro deixaria o
  -- rateio silenciosamente menor. Tem de doer antes.
  entidade_id bigint not null references public.entidade (id) on delete restrict,
  criado_em   timestamptz not null default now(),
  primary key (subconta_id, entidade_id)
);

create index subconta_investidor_entidade_idx
  on public.subconta_investidor (entidade_id);

-- --------------------------------------------------------- regra_fornecedor

-- As tres listas de hoje numa tabela so, separadas por `tipo`:
--   so_reembolso     quem NAO entra na planilha por so receber via reembolso
--   confirmar_antes  quem tem o pagamento confirmado antes de entrar
--   pix_reembolso    a chave Pix dos avisos "PAGAR PARA"
-- `valor` so e usado por pix_reembolso; nas outras duas fica vazio.
create table public.regra_fornecedor (
  id            bigint generated always as identity primary key,
  tipo          text not null,
  nome          text not null,
  valor         text not null default '',
  criado_em     timestamptz not null default now(),
  atualizado_em timestamptz not null default now(),
  constraint regra_fornecedor_tipo_conhecido
    check (tipo in ('so_reembolso', 'confirmar_antes', 'pix_reembolso')),
  constraint regra_fornecedor_unica unique (tipo, nome),
  -- Chave Pix sem chave nenhuma seria um aviso "PAGAR PARA" sem para quem.
  constraint regra_fornecedor_pix_tem_chave
    check (tipo <> 'pix_reembolso' or length(trim(valor)) > 0)
);

create trigger regra_fornecedor_tocar before update on public.regra_fornecedor
  for each row execute function public.tocar_atualizado_em();

-- ------------------------------------------------------------- configuracao

-- O que hoje sao campos soltos no topo dos dois JSON: a raiz do arquivamento
-- e o endereco do escritorio no portal contabil.
create table public.configuracao (
  chave         text primary key,
  valor         text not null,
  descricao     text not null default '',
  atualizado_em timestamptz not null default now()
);

create trigger configuracao_tocar before update on public.configuracao
  for each row execute function public.tocar_atualizado_em();

-- --------------------------------------------------------- acesso (RLS)

-- O projeto foi criado com "expose new tables" DESLIGADO, entao tabela nova
-- nasce sem privilegio nenhum: e preciso conceder de proposito, uma a uma.
-- `anon` fica de fora em todas -- a chave publica que vai no codigo do app
-- nao pode ler cadastro sozinha.
grant select, insert, update, delete on table
  public.empresa,
  public.cliente_erp,
  public.conta,
  public.pasta_vazia,
  public.entidade,
  public.subconta,
  public.subconta_investidor,
  public.regra_fornecedor,
  public.configuracao
to authenticated;

-- As sequencias das colunas identity precisam do mesmo tratamento, senao o
-- insert falha com "permission denied for sequence" -- erro que aponta para o
-- lugar errado e custa meia hora de procura.
grant usage on all sequences in schema public to authenticated;

-- O gatilho de RLS automatica (ligado na criacao do projeto) ja acendeu a RLS
-- nestas tabelas. O `enable` aqui e explicito de proposito: se um dia o
-- gatilho for removido, a migracao continua descrevendo a verdade inteira.
alter table public.empresa             enable row level security;
alter table public.cliente_erp         enable row level security;
alter table public.conta               enable row level security;
alter table public.pasta_vazia         enable row level security;
alter table public.entidade            enable row level security;
alter table public.subconta            enable row level security;
alter table public.subconta_investidor enable row level security;
alter table public.regra_fornecedor    enable row level security;
alter table public.configuracao        enable row level security;

-- Uma politica por tabela, para todos os verbos. Nao ha divisao por usuario:
-- as 2 a 5 pessoas cuidam do mesmo fechamento e precisam do mesmo cadastro.
-- Se um dia isso mudar, o lugar de mudar e aqui -- e nao no app.
create policy empresa_autenticado on public.empresa
  for all to authenticated using (true) with check (true);
create policy cliente_erp_autenticado on public.cliente_erp
  for all to authenticated using (true) with check (true);
create policy conta_autenticado on public.conta
  for all to authenticated using (true) with check (true);
create policy pasta_vazia_autenticado on public.pasta_vazia
  for all to authenticated using (true) with check (true);
create policy entidade_autenticado on public.entidade
  for all to authenticated using (true) with check (true);
create policy subconta_autenticado on public.subconta
  for all to authenticated using (true) with check (true);
create policy subconta_investidor_autenticado on public.subconta_investidor
  for all to authenticated using (true) with check (true);
create policy regra_fornecedor_autenticado on public.regra_fornecedor
  for all to authenticated using (true) with check (true);
create policy configuracao_autenticado on public.configuracao
  for all to authenticated using (true) with check (true);
