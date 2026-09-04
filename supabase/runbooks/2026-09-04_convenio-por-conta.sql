-- =========================================================================
-- Cole TUDO isto no SQL Editor do Supabase e rode uma vez so.
-- 04/09/2026 -- o convenio de remessa passa a morar na CONTA.
--
-- A ORDEM IMPORTA, e sao dois atos:
--
--   1. RODAR ISTO **ANTES** DO MERGE do PR "convenio por conta".
--      O codigo novo le `conta.convenio`. Se o merge sair primeiro, a
--      sincronizacao da abertura pede uma coluna que o banco nao tem e o
--      cadastro inteiro volta como recusa -- o app abre com a copia de
--      ontem, sem dizer o que aconteceu de verdade.
--      O caminho contrario e seguro: coluna nova com default '' nao muda
--      nada para o codigo velho, que continua lendo `empresa.convenio`.
--
--   2. DEPOIS, no painel (Table Editor -> `conta`), preencher o `convenio`
--      de cada conta da holding, um por um, lendo os numeros no SicoobNet
--      (Adesao a cobranca / pagamentos -> o comprovante de cada conta).
--      Sao nove contas: a principal e as oito subcontas, cada uma com o SEU
--      numero. **Os numeros nao entram neste repositorio, que e publico.**
--      A copia automatica do bloco 2 abaixo NAO alcanca essa holding de
--      proposito: ela tem mais de uma conta Sicoob, e escolher uma aqui
--      seria adivinhar de qual conta o dinheiro sai.
--
-- Conferir depois: o `select` do fim devolve, por empresa, quantas contas
-- Sicoob existem e quantas ja tem convenio. Enquanto os dois numeros nao
-- baterem, aquelas contas nao geram remessa -- e o app diz isso na tela,
-- conta por conta.
--
-- Byte a byte igual a migration `20260904113000_convenio_por_conta.sql`,
-- fora este cabecalho e o `select` de conferencia do fim.
-- =========================================================================


-- -------------------------------------------------------------- 1 de 2 --
-- A coluna, o unico e o formato.
--
-- O Sicoob da um convenio por CONTA CORRENTE: uma holding daqui tem nove
-- numeros diferentes debaixo de um CNPJ so. Com o convenio na empresa, as
-- nove contas sairiam com o MESMO numero no header (campo 07.0) e dividindo
-- UMA sequencia de NSA. O desfecho bom e o banco recusar o arquivo -- e o NSA
-- ja foi queimado, porque ele entra no conteudo antes de o arquivo existir.
--
-- `empresa.convenio` FICA: maquina que ainda nao atualizou le de la.

alter table public.conta
  add column convenio text not null default '';

comment on column public.conta.convenio is
  'Codigo do convenio de pagamentos DESTA conta, como sai no comprovante de '
  'adesao do SicoobNet. O Sicoob da um convenio por conta corrente, entao '
  'duas contas do mesmo CNPJ tem numeros diferentes. Vazio = esta conta nao '
  'aderiu e nao gera remessa. Nao ha heranca da empresa: o app le daqui e '
  'recusa quando esta vazio.';

create unique index conta_convenio_unico on public.conta (convenio)
  where convenio <> '';

alter table public.conta
  add constraint conta_convenio_formato
  check (convenio = '' or convenio ~ '^[0-9A-Za-z]{1,20}$');


-- -------------------------------------------------------------- 2 de 2 --
-- O convenio que ja existia na EMPRESA desce para a UNICA conta Sicoob dela.
-- Empresa com mais de uma conta Sicoob NAO recebe copia (ver o passo 2 do
-- cabecalho).

update public.conta c
   set convenio = e.convenio
  from public.empresa e
 where c.empresa_id = e.id
   and e.convenio <> ''
   and c.convenio = ''
   and c.numero is not null
   and (c.banco_codigo = '756' or upper(c.banco) = 'SICOOB')
   and (select count(*)
          from public.conta c2
         where c2.empresa_id = c.empresa_id
           and c2.numero is not null
           and (c2.banco_codigo = '756' or upper(c2.banco) = 'SICOOB')) = 1;


-- ------------------------------------------------------------ conferencia --
-- Quantas contas Sicoob cada empresa tem, e quantas ja tem convenio.
-- Nao imprime numero de convenio nenhum: so a contagem.

select e.nome_pasta                                as empresa,
       count(*)                                    as contas_sicoob,
       count(*) filter (where c.convenio <> '')    as ja_com_convenio
  from public.conta c
  join public.empresa e on e.id = c.empresa_id
 where c.numero is not null
   and (c.banco_codigo = '756' or upper(c.banco) = 'SICOOB')
 group by e.nome_pasta
 order by e.nome_pasta;
