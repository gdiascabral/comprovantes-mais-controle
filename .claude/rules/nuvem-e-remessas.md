---
paths:
  - "nuvem/**"
  - "supabase/**"
  - "cnab240/**"
  - "pagamentos_dia/remessa_dia.py"
  - "pagamentos_dia/retorno_dia.py"
  - "docs/PROVENIENCIA.md"
  - "docs/SUPABASE-PAINEL.md"
  - "tests/test_rls_supabase.py"
  - "tests/test_registro_nuvem.py"
---

# Cadastro na nuvem, NSA das remessas e runbooks

> As seções "O cadastro mora na nuvem" e "O NSA das remessas é da nuvem" e o tópico `supabase/runbooks/`, movido do `CLAUDE.md` em 21/09/2026 sem mudar uma palavra.
> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI — este é o lugar deste texto agora.

## O cadastro mora na nuvem (13/08/2026)

**Onde procurar as coisas.** O projeto Supabase é o `mais-controle-app`
(região sa-east-1). Tudo que o define está versionado em `supabase/`:
`config.toml` é a configuração do serviço e `migrations/*.sql` é o schema,
com o porquê de cada coluna no comentário. Nada aqui se configura por clique:
o que não estiver nesses arquivos não existe.

- **O que subiu**: contas, empresas, entidades (o `contas.csv`), subcontas com
  obras e investidores, as regras de fornecedor e as de boleto. O ERP continua
  sendo o banco dos PAGAMENTOS; isto aqui é só cadastro.
- **O que NÃO subiu, de propósito**: `preferencias.json` (tema é de máquina),
  `config.yaml`/`mapping.yaml`/`MODELO.xlsx` (são a estrutura da planilha da
  Conciliação, versionados junto do modelo que descrevem) e o `login.dat` —
  cada pessoa tem o SEU usuário no ERP, e nenhuma credencial de ERP vai para
  a nuvem.

**A decisão central está na tabela `conta`.** A MESMA conta era descrita em
`contas_mc.json` e `contas_sicoob.json`, cada um com a sua pasta de destino;
eles divergiram em três subcontas e partiram julho/2026 ao meio. Agora é uma
linha com uma coluna `pasta`, e a divergência deixou de ser representável.
`relatorios/conferir_mapas.py` continua existindo para quem rodar as abas com
cache antigo, mas o problema que ele vigiava não tem mais como nascer.

**O `convenio` mudou de tabela em 04/09/2026: era da `empresa`, é da `conta`**
(migration `20260904113000_convenio_por_conta.sql`). A coluna de 13/08 nasceu
supondo que o convênio fosse do CNPJ, e para empresa de uma conta só isso dava
no mesmo — a holding com a conta principal e oito subcontas é que mostrou o
desenho de verdade: o Sicoob dá **um convênio por conta corrente**, nove
números diferentes debaixo de um CNPJ. Com o convênio na empresa, as nove
contas sairiam com o mesmo campo 07.0 no header e dividindo UMA sequência de
NSA. **Não há herança**, e isso é decisão: cair no convênio da empresa quando
o da conta está vazio faria uma subconta ainda não aderida sair com o número
da principal. A coluna `empresa.convenio` FICA por enquanto, e o cache
continua escrevendo a chave da empresa — é o que máquina não atualizada lê;
o código novo não a lê, e aposentá-la é uma migration futura. **A ordem de
aplicar não pode inverter**: a migration roda ANTES do merge (coluna nova com
default `''` não muda nada para o código velho; o contrário faz a
sincronização pedir uma coluna que não existe), e só depois o painel recebe os
números — que ficam fora deste repositório, como todo dado real.

**Os JSON/CSV continuam existindo — como CACHE.** `nuvem/cadastro.sincronizar`
roda uma vez, na abertura, e regrava os arquivos de sempre no formato de
sempre. É por isso que `sicoob_contas`, `contas_mc` e `aportes/dados` não
mudaram uma linha: para eles, nada aconteceu. Um formato próprio de cache
teria criado duas verdades sobre a mesma conta — o problema que a nuvem veio
resolver. Três consequências:

- banco mudo não impede o app de abrir: usa a última cópia e escreve
  "⚠ cadastro offline" no rodapé da barra. **Sem esse aviso, "estou com o
  cadastro de ontem" seria indistinguível de "tudo certo"**;
- **vazio nunca substitui cheio**, em dois níveis. O grosso: banco sem
  empresas ou sem contas faz `sincronizar` recusar tudo (projeto novo ou
  migração não rodada zerariam o cadastro de todo mundo). O fino, mais
  provável: cada arquivo é comparado sozinho, então alguém apagar as
  entidades pelo painel não zera o `contas.csv` de todas as máquinas na
  próxima abertura. A regra não é "nunca escreva vazio" — máquina nova
  precisa receber os arquivos —, é "não troque cheio por vazio";
- o cache preserva as chaves `_leia_me`/`_ajuda`, que explicam o arquivo para
  quem o abre e não vêm do banco. É o que mantém vivo o `_nao_sao_boleto`,
  que nenhum código lê e ninguém saberia reescrever;
- **quem lê o cache tem de usar `util.pasta_base()`.** `aportes/dados.py`,
  `relatorios/contas_mc.py` e `extratos_sicoob/sicoob_config.py` calculavam a
  pasta sozinhos e, rodando como SCRIPT, procuravam dentro da própria
  subpasta enquanto o cache regravava na raiz — o cadastro baixado chegava e
  ninguém o via. Congelado dava no mesmo, então o desencontro só aparecia em
  desenvolvimento, que é justamente onde se testa.

**Editar cadastro é no painel do Supabase**, que é uma planilha no navegador.
Não há tela no app, de propósito: esses cadastros mudam raras vezes, e a
validação mora no BANCO (`unique`, `check`, FK), onde vale independentemente
de por onde a edição entrou. Depois de editar, o app pega na próxima abertura.

**Segurança, e o que já está provado por teste.** Só a `anon key` está no
código (`nuvem/rest.py`) — ela é pública por desenho e não abre nada sozinha;
a `service_role` ignora a RLS inteira e não pode aparecer no repositório, no
exe nem no CI. Toda tabela tem RLS ligada.

**O app só LÊ, então as políticas são `for select`** e o privilégio de
escrita foi revogado de `authenticated`. As políticas nasceram `for all`, o
que dava a qualquer pessoa logada o poder de esvaziar o cadastro por uma
chamada de API — poder que nenhuma linha do app exerce. O que isso muda na
prática: token vazado (ou pessoa que saiu e ainda tem sessão válida) passa a
poder LER o cadastro, ruim, em vez de poder APAGÁ-LO, irreversível sem
backup. Quem escreve é a administração — o painel e o `nuvem/migrar.py`, os
dois com a chave de serviço.

Medido contra o projeto de verdade: sem login, ler `conta` ou
`regra_fornecedor` responde **401**; criar conta responde **422
signup_disabled**; com login, ler responde 200 e criar, apagar ou reescrever
respondem **403**. O cadastro público está desligado porque, com ele aberto,
qualquer um que clonasse o repositório viraria gente da casa.

**Duas armadilhas do Supabase CLI que já custaram tempo:**

- **`supabase config push` aplica direto, sem mostrar diff para confirmar.**
  Rodá-lo com o `config.toml` recém-criado pelo `init` empurra os DEFAULTS do
  CLI por cima do projeto — aqui desligou o MFA e a confirmação de e-mail e
  afrouxou o limite de envio. Edite o arquivo ANTES, e rode de novo até dizer
  "up to date".
- **`enable_signup = false` dentro de `[auth.email]` desliga o PROVEDOR de
  e-mail**, e o login morre com `email_provider_disabled`. Quem tranca o
  cadastro é só o `enable_signup` de `[auth]`; o de `[auth.email]` fica
  `true`.

**O login** (`nuvem/login_dialogo.py`) substituiu a senha de ativação, que era
uma só para todo mundo e valia para sempre naquela máquina — quem saía da
equipe continuava sabendo dela. A sessão fica em `sessao.dat`, cifrada pela
DPAPI (`util.proteger_bytes`, a mesma do `login.dat`).
**Sem servidor, o app confere a VALIDADE do token, não a assinatura**: o
segredo que assina é do projeto e não pode viajar num exe público. Quem
sustenta a garantia é a DPAPI — o arquivo só é decifrável pelo mesmo usuário
do Windows na mesma máquina. Havendo rede, quem julga é o servidor. São três
desfechos, e a diferença importa: vencido com rede pede a senha; **sem rede e
dentro do prazo, ABRE** (travar aqui transformaria uma queda do Supabase em
app parado com o ERP de pé); sem rede e vencido, não abre e diz isso.

### O NSA das remessas é da nuvem (`nuvem/registro.py`)

**O `remessas.json` continua existindo e continua sendo escrito** — é backup
legível, e some junto com o computador se for a única cópia. O que ele deixou
de ser é a autoridade do NSA.

Por quê: a trava dele é um arquivo `.lock` na mesma pasta, e protege dois
processos, não dois computadores. Cada máquina tem o seu arquivo, as duas leem
"último = 5" antes de qualquer uma gravar 6. A prova apareceu sem precisar de
duas pessoas — nesta máquina, a instalação (`_app`) dizia que o próximo NSA
era 1 e a pasta de código dizia 2.

**Reservar e espiar são coisas diferentes**, e a separação não é preciosismo:

- `proximo_nsa()` só OLHA, e é o que a janela de conferência usa. Reservar ao
  mostrar queimaria um número cada vez que alguém abrisse a tela e desistisse.
  O número exibido é **previsão**: se a outra máquina gerar nesse meio-tempo,
  o arquivo sai com um mais alto;
- `alocar_nsa()` RESERVA, e é chamado **antes de montar o arquivo** — o NSA
  entra no conteúdo, e reservá-lo depois deixaria a janela em que a outra
  máquina pega o mesmo. Se a geração falhar em seguida, o número é queimado, e
  esse é o lado certo de errar: **pular número é inofensivo, repetir não**.

Quem garante a atomicidade é o Postgres, na função `alocar_nsa` (um
`insert … on conflict do update … returning`, uma instrução só). Medido contra
o projeto de verdade: 12 pedidos simultâneos, 12 números distintos.

**A ordem do dia do "seu número" (04/09/2026).** O NSA não é o único número
disputado: o "seu número" de cada pagamento é `yymmdd-NNNN[-OC…]`, 20 posições
que **nós** definimos e o banco devolve idênticas no retorno — é por elas que
cada resposta reencontra o lançamento. A ordem `NNNN` tem de ser única entre
TODAS as remessas do dia, de todas as contas e de todas as máquinas: repetida,
o retorno casa com o pagamento errado (foi o defeito de 20/08/2026, em que a
segunda remessa do dia repetiu `260820-0004`…`0010`).

Ela seguia o caminho oposto ao do NSA, e por isso mudou:

- **a consulta virou UMA linha.** `sequencia_ja_usada` varria
  `historico.remessas()` — todas as remessas com todos os itens dentro, a cada
  geração (0,44 s com sete; 18 contas vezes os dias não cabe nisso). Hoje ela
  pergunta `historico.maior_ordem_do_dia(quando)`, que a nuvem resolve com
  `seu_numero=like.260904-*&order=seu_numero.desc&limit=1`. O formato ordena
  lexicograficamente igual ao numérico porque a ordem tem quatro dígitos com
  zero à esquerda e o sufixo `-OC…` vem depois dela. Quem sabe ler o formato é
  `cnab240.historico.ordem_do_dia`, um dono só para três leitores;
- **a consulta não é a trava — o índice é.** Ler não impede nada: duas máquinas
  leem o mesmo maior e escrevem os mesmos números. Quem recusa agora é
  `remessa_item_seu_numero_unico_no_dia`, índice único **parcial pela data**
  (`criado_em >= 2026-09-05`). Parcial porque o histórico é append-only e já
  tem a repetição de 20/08 dentro: reescrever o passado para caber numa regra
  nova seria mentir sobre ele. A consulta existe para a recusa ser rara;
- **a consulta não filtra convênio nem estado**, porque o índice também não. A
  ordem é do DIA, e perguntá-la por conta daria dois pagamentos com o mesmo
  número. O espelho local (`Historico.maior_ordem_do_dia`) filtra só o estado,
  de propósito e coerente com `_conferir_seus_numeros`: lá descartar devolve os
  números. Quem o app usa é sempre o da nuvem, pelo `Espelhado`;
- **registro que não responde PARA a remessa** (`remessa_dia.RegistroMudo`, um
  `messagebox` no passo 3). Antes devolvia 0 e a numeração recomeçava — era
  inofensivo enquanto ninguém conferia. Com o índice, o mesmo silêncio vira
  arquivo recusado DEPOIS de a lista inteira ter sido conferida, e com o NSA já
  queimado. `historico=None` continua valendo 0: é "não perguntei", que é como
  os testes de regra chamam `preparar`;
- **a corrida perdida vira recusa limpa.** `Registro.registrar` são dois
  INSERTs, e desde o índice o segundo pode ser recusado com a linha da
  `remessa` já dentro. Sem tratar isso ficava na nuvem uma remessa `gerado` sem
  item nenhum — contando como envio vivo e sem de-para para o retorno. Agora
  ela é marcada `descartado` com `observacao="itens recusados pelo banco: …"`
  (best-effort) e a exceção ORIGINAL sobe, porque é ela que impede o `.tmp` de
  virar `.REM`.

**Sem nuvem, a aba se recusa a gerar remessa** — e é a única operação do app
que faz isso. Um contador local diria um número que a outra pessoa já pode ter
usado, e o app não teria como saber. Todo o resto (cadastro, extratos,
relatório) roda com a última cópia.

O histórico é **append-only** no banco: não há DELETE em lugar nenhum, e o
UPDATE alcança só `estado`/`observacao` da remessa e o retorno do item. O que
está gravado descreve um arquivo que já saiu, e reescrevê-lo seria mentir
sobre o passado. Corrigir o contador é `ajustar_nsa`, que **exige motivo por
escrito** e deixa rastro em `remessa_ajuste`.

`registro.Espelhado` grava nos dois lugares, e o local **não tem voto**: a
nuvem registra primeiro (é ela que pode recusar por NSA repetido, e essa
recusa tem de impedir o `.tmp` de virar `.REM`), o espelho vem depois e, se
falhar, só avisa. Recusar a remessa porque o BACKUP falhou seria trocar o
problema pequeno pelo grande.

**O estado que o RETORNO grava é sempre um estado VIVO**, e isso é regra de
dinheiro. `remessa_dia._ja_enviado` só enxerga item de remessa viva, então um
estado fora de `ESTADOS_VIVOS` tira a remessa INTEIRA da pergunta "isto já foi
mandado?" — e os pagamentos que o banco pagou voltam marcáveis na geração
seguinte, com NSA novo e nenhum alarme. Era o que fazia o `"com_erro"` que o
`retorno_dia` gravava, e que não existia em lista nenhuma: a coluna `estado` do
banco não tem `check`, de propósito, então a marcação era aceita em silêncio.
Hoje um item rejeitado marca a remessa como **"rejeitado"**, que continua viva —
rejeição de UM não devolve aos outros o direito de sair de novo. A contrapartida
é o lado seguro: o item rejeitado também fica bloqueado (a pergunta casa por
código de barras/referência do item), e reenviá-lo exige `descartar` a remessa;
o reenvio por item, lendo o `retorno_codigo` de cada um, é outro PR.
**`ESTADOS_VIVOS` é UMA tupla**, importada de
`cnab240.historico` no topo do `registro.py` — enquanto foram duas listas
escritas à mão elas divergiram em silêncio, com "aceito" só de um lado e
"rejeitado" só do outro.

**Marcar e descartar ganharam tela em 04/09/2026, e até então NINGUÉM as
chamava.** `marcar` existia desde 17/08 sem um único chamador no app: toda
remessa ficava `gerado` até alguém ler o retorno, o que fazia a remessa que
NUNCA subiu ao SicoobNet ser indistinguível da que subiu — e deixava o
pagamento de uma remessa jamais enviada bloqueado para sempre, porque só
`descartado` sai de `ESTADOS_VIVOS`. Quem as expõe é o "Painel do dia"
(`pagamentos_dia/pagamentos_frame._janela_painel_do_dia`), e as regras são
puras, em `pagamentos_dia/painel_dia`. O `Registro` ganhou três métodos:

- **`remessas_do_dia(quando)`** — UMA consulta por FAIXA DE INSTANTE, sem
  convênio e sem estado, com os itens dentro. O dia é o LOCAL: os limites saem
  de `datetime.combine(dia, 00:00).astimezone()` e viajam em ISO com offset,
  com o `+` virando `%2B` (um `+` cru numa query string é decodificado como
  espaço do outro lado). Filtrar por texto sobre o UTC que o banco guarda
  perderia toda remessa gerada depois das 21h e traria as da noite anterior. É
  a pergunta que o índice `remessa_convenio_idx` **não** responde — daí a
  migration `20260904181500_remessa_gerado_em_idx.sql`, que é só índice: o
  código funciona sem ela, só mais lento, e é o único par runbook/migration
  deste projeto em que a ordem não trava;
- **`marcar_enviada` e `descartar`** — cascas sobre `marcar` que **releem a
  remessa antes de decidir**, porque a regra do "tem item pago" precisa dos
  ITENS e a tela pode estar aberta desde antes de outra máquina guardar um
  retorno. `marcar_enviada` só de `gerado`; `descartar` recusa com item `ok`
  (devolveria à fila um pagamento que já saiu) e recusa sem motivo escrito,
  que vai para a `observacao` pela mesma frase nos dois lados
  (`painel_dia.observacao_do_descarte`).

O `Espelhado` repassa as três, e o espelho local continua sem voto: recebe o
`marcar` de sempre e, falhando, só avisa.

**O retorno do banco são QUATRO colunas do item, e uma delas nunca se apaga**
(migration `20260904121220_retorno_estado_e_historico.sql`). `retorno_codigo` e
`retorno_em` existem desde 17/08; `retorno_estado` e `retorno_historico`
entraram em 04/09 para fechar três defeitos medidos:

- **o segundo retorno APAGAVA o primeiro.** Quem gera não é quem assina: o
  retorno do mesmo dia vem `PD` (pendente de assinatura) e o de depois da
  liberação vem `00`. O `00` é a resposta certa para "e agora?", e escrevê-lo
  por cima do `PD` levava junto a única prova de que o arquivo tinha sido
  ACEITO. A regra nova é essa divisão: **`retorno_codigo` é a resposta de
  AGORA e é sobrescrito; `retorno_historico` só CRESCE** — uma entrada por
  retorno lido, `AAAA-MM-DD HH:MM codigo=estado`, separadas por `;`, no mesmo
  instante que o `retorno_em`;
- **o banco manda mais de uma ocorrência por pagamento**, e só a primeira era
  gravada, porque a janela arrancava o código de volta da frase do `motivos`
  (`split("=")[0]`) em vez de tê-lo na mão. Hoje `retorno_dia.Linha.codigos`
  traz todas, na ordem, e o `retorno_codigo` leva todas separadas por `;`;
- **a classificação (`ok`/`pendente`/`rejeitado`/`?`) não era gravada**, então
  contar pago/pendente/rejeitado por item exigiria traduzir código de
  ocorrência de novo — uma segunda tabela dizendo o que "AG" quer dizer,
  envelhecendo calada ao lado da primeira. Ela é feita UMA vez, ao ler o
  arquivo, e `retorno_dia.respostas_para_registro(resumo)` é quem a entrega ao
  `Registro.aplicar_retorno`.

**A limitação aceita**, escrita para não ser redescoberta: o append é
ler-concatenar-gravar no app, não um `||` do Postgres. Duas pessoas guardando o
MESMO retorno no mesmo instante podem perder uma LINHA de histórico — nunca a
resposta atual, e nada que mexe em dinheiro lê o histórico (`baixa_erp.separar`
decide pelo `Resumo` lido do arquivo). O privilégio continua sendo de COLUNA,
não de tabela, e **não nasceu política nova**: a `remessa_item_retorno` já
existe e já exige `privado.e_ativo()`.

**O que ainda NÃO está na nuvem** (e continua como estava): os aportes já
lançados, que seguem em `self.criados`, memória do processo em
`aportes/aportes_frame.py` — falha parcial seguida de reabrir o app ainda
apaga a proteção contra duplicar; e os envios da Acessórias, hoje conferidos
relendo o portal, que funciona.

**Migrar de novo** (máquina nova, ou recomeçar): `python nuvem/migrar.py
--conferir` critica sem escrever; `--subir` escreve e depois relê para
comparar campo a campo. Precisa do Supabase CLI autenticado
(`npx.cmd supabase login` — com `.cmd`, senão a trava de scripts do
PowerShell barra). Migrar é administração e usa a chave de serviço, que sai
do próprio CLI: não há segredo em arquivo nem em variável de ambiente para
alguém esquecer.

**`vip_nome` é gravado vazio de propósito.** A tentação é preenchê-lo com a
razão social, e `pacote.py` usa `vip_nome or empresa.nome` para montar o
ASSUNTO da solicitação ao escritório contábil — preenchê-lo mudaria, sem
ninguém pedir, o texto que o contador recebe todo mês.


- `supabase/runbooks/` — **o que de fato rodou no banco**, byte a byte. As
  migrations descrevem o schema, mas não foram elas que rodaram: o que rodou
  foram arquivos colados no SQL Editor do painel, que viviam soltos fora do
  repositório — e enquanto ficaram lá, "o que está em produção" e "o que o
  repositório diz" eram duas perguntas com respostas diferentes e nenhuma forma
  de comparar (num dos pares, 182 linhas de diferença). **Nem tudo entra**: um
  dos runbooks foi copiado e depois RETIRADO (commit `25ae569`) porque o
  cabeçalho dele mesmo dizia que ficara fora por trazer nome de fornecedor, e
  este repositório é público; os dois de 30/08 nunca entraram, porque carregam
  um endereço de e-mail real. A proveniência dos três continua no
  `docs/PROVENIENCIA.md`, que não depende do conteúdo — e é lá que está o
  achado da comparação: o `grant` da migration `20260824141500` não aparece em
  runbook nenhum.
