-- O convenio de remessa passa a morar na CONTA. Antes morava na EMPRESA.
--
-- A coluna `empresa.convenio` nasceu em 13/08/2026 (migration
-- `20260813204444_cadastro_campos_que_faltavam.sql`) sobre uma suposicao que o
-- banco nao confirma: a de que o convenio fosse do CNPJ. Em 04/09/2026 o dono
-- leu os numeros no SicoobNet e o desenho apareceu inteiro: o Sicoob da **um
-- convenio por CONTA CORRENTE**. Uma holding do cadastro tem a conta principal
-- e oito subcontas, e cada uma delas tem o SEU convenio -- nove numeros
-- diferentes debaixo de um CNPJ so. Empresa de uma conta so tem um, e por isso
-- o defeito nunca apareceu na primeira remessa.
--
-- Por que isso nao e detalhe de cadastro. O convenio e o campo 07.0 do header
-- do CNAB 240 e e ele que da NOME a sequencia do NSA (`alocar_nsa(convenio)`,
-- migration `20260817145337`). Com o convenio na empresa, as nove contas dessa
-- holding sairiam com o MESMO numero no header e dividindo UMA sequencia de
-- NSA. O desfecho bom e o banco recusar o arquivo -- e ainda assim o NSA ja
-- foi queimado, porque ele entra no CONTEUDO antes de o arquivo existir. O
-- desfecho ruim e o banco aceitar em nome de uma conta que ninguem escolheu.
--
-- **Sem heranca, de proposito.** Quem le o convenio le o da CONTA e mais nada.
-- Cair no da empresa quando o da conta esta vazio e exatamente o caminho para
-- uma subconta ainda NAO ADERIDA sair com o convenio da principal -- e "nao
-- aderida" e o estado normal de quase toda conta daqui. Vazio continua sendo
-- a trava: conta sem convenio nao gera remessa, e e assim que quem ainda nao
-- aderiu fica de fora sem precisar de lista negra.
--
-- **A coluna `empresa.convenio` FICA**, com o indice unico dela. Maquina que
-- ainda nao baixou o codigo novo continua lendo de la, e derrubar a coluna
-- hoje quebraria o app de quem nao abriu o programa nesta semana. O codigo
-- novo nao a le. Aposenta-la e assunto de uma migration futura, depois de
-- todo mundo ter atualizado.

-- -------------------------------------------------------------------- conta

alter table public.conta
  add column convenio text not null default '';

comment on column public.conta.convenio is
  'Codigo do convenio de pagamentos DESTA conta, como sai no comprovante de '
  'adesao do SicoobNet. O Sicoob da um convenio por conta corrente, entao '
  'duas contas do mesmo CNPJ tem numeros diferentes. Vazio = esta conta nao '
  'aderiu e nao gera remessa. Nao ha heranca da empresa: o app le daqui e '
  'recusa quando esta vazio.';

-- Dois convenios iguais gerariam NSA em sequencias que se atropelam -- a
-- mesma razao do `empresa_convenio_unico` de 13/08, agora no lugar certo.
create unique index conta_convenio_unico on public.conta (convenio)
  where convenio <> '';

-- O campo 07.0 do header tem 20 posicoes alfanumericas. Espaco, ponto ou
-- hifen digitados sem querer no painel viram header invalido, e a recusa
-- chega do banco -- depois de o NSA ter sido queimado.
alter table public.conta
  add constraint conta_convenio_formato
  check (convenio = '' or convenio ~ '^[0-9A-Za-z]{1,20}$');

-- --------------------------------------------------------------- o dado
-- O convenio que ja existia na EMPRESA desce para a UNICA conta Sicoob dela.
-- E o caso em que empresa e conta querem dizer a mesma coisa, e o unico em
-- que a copia nao pode errar de conta.
--
-- Empresa com MAIS DE UMA conta Sicoob nao recebe copia nenhuma: cada conta
-- tem o seu numero, e escolher uma aqui seria adivinhar. Essas o dono
-- preenche no painel, lendo os numeros no SicoobNet -- eles nao entram neste
-- repositorio, que e publico.
--
-- Conta Sicoob e a que tem numero E se identifica como Sicoob por um dos dois
-- lados do cadastro: `banco_codigo = '756'` (que vem do contas_sicoob.json) ou
-- `banco = 'SICOOB'` (o NOME, que vem do contas_mc.json). Casar por um so
-- deixaria metade de fora -- a mesma armadilha que `nuvem/cadastro._e_inter`
-- ja descreve.
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

-- ------------------------------------------------- o que NAO muda aqui
-- Nenhum `grant` e nenhuma politica nova: `conta` ja tem as suas desde
-- 21/08 (`conta_cadastra`, `conta_corrige`) e o `grant insert, update on
-- table public.conta to authenticated` de 24/08 e de TABELA -- coluna nova
-- entra debaixo dele sem precisar de linha. A porteira continua sendo a
-- `privado.e_ativo()` de 30/08, em toda politica desta tabela.
