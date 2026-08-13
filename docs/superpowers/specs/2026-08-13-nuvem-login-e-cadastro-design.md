# Nuvem: login por pessoa e cadastro compartilhado

Data: 13/08/2026

## O problema

O app não tem banco de dados. O que faz esse papel são arquivos soltos ao lado
do executável — `contas.csv`, `subcontas.json`, `contas_mc.json`,
`contas_sicoob.json`, `regras_fornecedor.json`, `confirmar_antes.json`,
`pix_reembolso.json`, `preferencias.json` — mais o ERP, que é o banco de
verdade dos pagamentos e não é nosso.

Cada máquina tem a **sua** cópia desses arquivos, e nada as reconcilia. Isso
já custou caro três vezes:

- **Os dois mapas divergiram.** `contas_mc.json` e `contas_sicoob.json`
  descrevem a MESMA conta e discordaram da pasta em três subcontas;
  julho/2026 ficou partido, com o PDF do ERP numa pasta e o OFX na outra.
  `relatorios/conferir_mapas.py` existe só para avisar disso — ele detecta a
  divergência, não a impede.
- **Editar é às cegas.** Os `contas_sicoob.json.bak`,
  `contas_sicoob.backup-20260812-154043.json` e
  `contas_sicoob.backup-antes-convenio-20260813.json` na pasta do exe são o
  sintoma: a única rede de proteção é copiar o arquivo antes de mexer.
- **Corrigir num lugar não chega no outro.** São 2 a 5 pessoas em máquinas
  diferentes. Conta nova cadastrada aqui não existe lá até alguém copiar o
  arquivo à mão.

E há um dado que nem chega a ter arquivo: a lista de lançamentos de aporte já
criados no ERP vive em `self.criados`, memória do processo
(`aportes/aportes_frame.py`). Falha parcial seguida de reabrir o app apaga a
proteção contra duplicar dinheiro.

## O que este documento cobre

As **Fases 1 e 2**: login por pessoa e cadastro compartilhado.

A **Fase 3** (registro central: aportes lançados, NSA, retorno CNAB, envios da
Acessórias) ganha documento próprio, e de propósito: a biblioteca `cnab240`
ainda está sendo fechada, e o retorno do banco define estado que hoje não
existe em lugar nenhum. Desenhar essas tabelas antes de o formato existir é
desenhar no escuro, e schema errado que já entrou em uso é o caro de corrigir.

## O que NÃO muda

- **A senha do ERP continua local.** Cada pessoa tem o seu usuário no Mais
  Controle; `login.dat` segue cifrado pela DPAPI na máquina de cada um. Nenhuma
  credencial de ERP vai para a nuvem.
- **O ERP continua sendo o banco dos pagamentos.** Nada de espelhar título,
  saldo ou lançamento aqui.
- **`preferencias.json` fica local.** Tema e grupos abertos são preferência de
  máquina, não cadastro compartilhado. Sincronizá-los só criaria briga entre
  dois monitores diferentes.
- **`config.yaml`, `mapping.yaml` e `MODELO.xlsx` ficam locais.** São a
  estrutura da planilha da Conciliação, versionados junto do modelo do Excel
  que descrevem. Separar os dois é criar a chance de o mapa apontar para uma
  célula que o modelo não tem mais.

## A restrição que manda no faseamento

Todo arquivo novo — pasta de módulo ou arquivo na raiz — obriga a acrescentar
uma linha no `build.yml`, e o job `motor` recusa qualquer push que toque nesse
arquivo sem subir o `motor_minimo.txt` junto (`.github/workflows/build.yml`,
lista de gatilhos). A trava é mecânica: olha o nome do arquivo alterado, não o
que mudou dentro dele.

Consequência: **arquivo novo = download de ~150 MB para cada usuário.**

Por isso a Fase 1 cria o pacote `nuvem/` **inteiro**, com todos os módulos que
as três fases vão usar, mesmo os que nascem quase vazios. Paga-se um exe novo
uma vez; as Fases 2 e 3 chegam pelo `codigo.zip` em segundos.

Pelo mesmo motivo, se a aba CNAB entrar no app, ela deve subir **no mesmo
push** que o pacote `nuvem/` — dois pedágios de 150 MB onde cabia um.

## Arquitetura

### Por que Supabase, e por que sem biblioteca

Supabase é Postgres gerenciado com autenticação por e-mail e senha já pronta,
Row Level Security e plano gratuito folgado para este volume.

O ponto decisivo é outro: **o Supabase fala REST puro** (PostgREST para dados,
GoTrue para login), e `requests` já está embutido no motor
(`motor.py`, `_garantir_dependencias`). Falar com ele por `requests` significa
**zero dependência nova**, e portanto correções que chegam pelo `codigo.zip`
em segundos. A biblioteca oficial `supabase-py` obrigaria exe novo a cada
ajuste — inaceitável num app que se atualiza sozinho na mão de outras pessoas.

### O pacote `nuvem/`

Pacote de verdade, com `__init__.py`, como `conciliacao/`.

| Módulo | Faz | Não faz |
|---|---|---|
| `rest.py` | URL, cabeçalhos, timeout, retentativa, tradução de erro HTTP | não conhece conta, aporte nem tkinter |
| `sessao.py` | entrar, sair, renovar; guarda o refresh token cifrado | não desenha janela |
| `login_dialogo.py` | a janela de login; substitui `ativacao.pedir_ativacao` | não fala HTTP direto |
| `cache.py` | lê e grava a cópia local (os JSON/CSV de hoje) | não decide quando usar |
| `cadastro.py` | contas, mapas de pasta, entidades e regras; puxa do banco, cai no cache | não escreve no banco |
| `registro.py` | escritas de estado (Fase 3). **Sem cache**: sem banco, falha | não lê cadastro |

Cada módulo responde sozinho o que faz, como se usa e de que depende. Um
consumidor que hoje chama `cadastro.carregar_contas()` passa a chamar
`nuvem.cadastro.entidades()` e não muda em mais nada.

### Uma mudança fora do pacote

As funções DPAPI moram em `anexar/credenciais.py`. O `nuvem/sessao.py` precisa
da mesma coisa para guardar o refresh token, e `nuvem` importar de `anexar`
acoplaria o login ao módulo de anexos.

`util.py` ganha `proteger_bytes(dados)` e `revelar_bytes(dados)` — DPAPI cru,
sem saber o que cifra — e `credenciais.py` passa a usá-las. Mesmo motivo pelo
qual `util.norm_espaco` virou a única comparação de nome de conta: duas cópias
de uma regra é uma divergência esperando acontecer. `util.py` continua sem
importar tkinter.

### Segredos e quem pode entrar

- Só a **anon key** vai ao código. Ela é pública por projeto e não dá acesso a
  nada sozinha; quem protege é a RLS.
- A **service_role key** nunca entra no repositório, no exe, nem em variável de
  ambiente do CI.
- **Signup público desligado.** Sem isso, qualquer um que clone o repositório
  cria conta e a RLS o trata como usuário legítimo. Contas são criadas por
  convite, pelo painel.
- Toda tabela nasce com RLS ligada e política `authenticated`. Tabela sem
  política é tabela que nega tudo — o lado seguro.

## Fase 1 — Login por pessoa

### O que sai

`ativacao.py` some, com o `ativacao.dat` e o hash no código. Ele resolvia
"esta máquina pode abrir o app?" com uma senha única compartilhada: quem sai da
equipe continua sabendo a senha, e trocá-la obriga a publicar release nova e
perguntar de novo a todo mundo.

### O que entra

Na abertura, antes da janela principal, `nuvem/login_dialogo.py` pede e-mail e
senha. Acertou, `sessao.py` guarda o refresh token cifrado pela DPAPI em
`sessao.dat`, ao lado do exe, e nas próximas vezes o app renova sozinho, sem
perguntar nada.

A janela segue o que o resto do app já faz: modal (isto EXIGE resposta),
`widgets.barra_de_titulo`, Enter confirma, Esc desiste, X é o mesmo que
desistir. Reaproveita a estrutura da atual `pedir_ativacao`, que já resolveu
esses detalhes.

### Quando não dá para renovar

Três desfechos distintos, e a diferença importa:

- **Token vencido, rede de pé** → pede a senha de novo. Normal.
- **Sem rede ou Supabase mudo, token dentro da validade** → abre. O app já não
  faz nada sem internet (ERP, Sicoob e portal são todos web), então travar aqui
  só transformaria uma queda do Supabase em app parado com o ERP de pé.

  **Sem servidor, o app confere a validade, não a assinatura** — e é preciso
  ser exato sobre o que isso garante. O token do Supabase é assinado com um
  segredo do projeto, que não pode viajar dentro de um exe público; sem ele,
  só dá para ler a data de expiração de dentro do token. Quem sustenta a
  garantia aqui é a **DPAPI**: o `sessao.dat` só é decifrável pelo mesmo
  usuário do Windows na mesma máquina que o gravou. Forjar um token exigiria
  já estar logado naquela conta do Windows — quem chegou lá tem o app, os
  arquivos e o `login.dat` de qualquer jeito.

  Isso vale só para o modo offline. Havendo rede, quem julga é o servidor: a
  renovação é recusada se o usuário foi removido ou teve a senha trocada, e o
  acesso acaba na expiração seguinte.
- **Sem rede e token vencido** → não abre, e diz exatamente isso. Deixar entrar
  sem nenhuma prova de identidade seria a senha compartilhada de volta, pior.

### Identidade

Cada pessoa tem um usuário. A partir daqui existe "quem fez", que é o que a
Fase 3 vai gravar junto de cada aporte lançado e cada remessa gerada.

## Fase 2 — Cadastro compartilhado

### A divergência que deixa de existir

Hoje a mesma conta é descrita em dois arquivos com estruturas diferentes:

- `contas_mc.json` → `{erp, empresa, pasta, banco, sufixo}`, chaveado pelo nome
  da conta no ERP;
- `contas_sicoob.json` → `{numero, pasta}` dentro de `empresas[]`, chaveado
  pelo número da conta.

Nada liga um ao outro. `conferir_mapas.py` precisa **extrair o número de conta
do nome do ERP com expressão regular** para conseguir comparar os dois — e essa
regex existir já é a prova de que falta uma chave comum.

No banco há **uma** tabela `conta`, com o nome do ERP e o número lado a lado, e
**uma** coluna `pasta`. A divergência deixa de ser detectável porque deixa de
ser representável. `conferir_mapas.py` é removido junto com o problema que ele
vigiava.

### Modelo

```
empresa(id, nome_pasta, vip_id, vip_nome)
  nome_pasta   nome curto, como aparece na árvore do fechamento
  vip_id       id da empresa na URL do portal contábil (não se deriva de nada)
  vip_nome     razão social como entra no assunto da solicitação

cliente_erp(id, empresa_id, nome)
  nomes com que a empresa aparece como CLIENTE das obras no ERP;
  hoje é `clientes_erp[]` dentro da empresa

conta(id, empresa_id, numero, nome_erp, pasta, banco, sufixo, ativa)
  numero    como a pessoa escreve ("00.000-0"); nulo em conta que não é Sicoob
  nome_erp  nome exato no Mais Controle; nulo em conta que o ERP não tem
  pasta     subpasta dentro da empresa; aceita subnível ("BANCO/APLICAÇÃO")
  banco     entra no nome do arquivo
  sufixo    desempate quando várias contas dividem a pasta

pasta_vazia(id, empresa_id, nome)
  pastas que só são criadas, de bancos fora desta automação

entidade(id, nome_exibicao, nome_oficial, conta, nome_descricao)
  o atual contas.csv: pessoas e empresas dos Aportes

subconta(id, nome) + subconta_investidor(subconta_id, entidade_id)
  o atual subcontas.json: grupos de investidores por subconta

regra_fornecedor(id, tipo, nome, valor)
  tipo distingue as três listas de hoje: só-reembolso
  (regras_fornecedor.json), confirmar-antes (confirmar_antes.json) e
  chave-pix-de-reembolso (pix_reembolso.json)

configuracao(chave, valor)
  a raiz do arquivamento e o endereço do portal contábil (`vip_url`), hoje
  campos soltos no topo dos dois JSON
```

Chaves naturais ganham `unique`: `empresa.nome_pasta`, `conta.numero`,
`conta.nome_erp`. Duas contas apontando para a mesma pasta na mesma empresa é
recusado pelo banco, não por código de aplicação.

`conta.numero` guarda o formato que a pessoa escreve e a comparação continua
por dígitos (`so_digitos`), como hoje — o OFX traz o ACCTID sem pontuação e a
pessoa digita com.

### Como se edita

Pelo painel web do Supabase, que é uma planilha no navegador. Nenhuma tela nova
no app.

O motivo é escopo: esses cadastros mudam raras vezes — conta nova, obra nova —,
e uma aba de CRUD para sete cadastros seria muito código para pouco uso.
Ela também só validaria o que passasse por ela, enquanto o painel continuaria
aberto ao lado. **A validação vai para o banco** (`unique`, `not null`, chave
estrangeira), onde vale independentemente de por onde a edição entrou.

Se depois de rodar assim a edição no painel incomodar, a aba entra — mas sobre
um problema já resolvido, não por cima dele.

### O cache

Os arquivos JSON/CSV de hoje continuam existindo, rebaixados a cache:

1. Ao abrir, o app puxa o cadastro e regrava o arquivo local.
2. Banco mudo → usa o arquivo local e escreve na barra de status desde quando
   é a cópia.
3. Arquivo local ausente e banco mudo → a aba que precisa daquele cadastro
   recusa começar, com o motivo. Nunca rodar com cadastro pela metade: conta
   sem destino já trava o lote antes do primeiro download, e essa regra fica.

Efeito colateral bom: o cache é um backup legível. Se o projeto Supabase
sumisse hoje, o cadastro continuaria em cada máquina, em texto.

### Dado pessoal

`pix_reembolso.json` e `regras_fornecedor.json` carregam CPF, chave Pix e nome
de pessoa. Levá-los para um servidor é uma decisão consciente, e a comparação
honesta é com o que existe **hoje**: os mesmos dados, em texto puro, num JSON
dentro de uma pasta sincronizada pelo OneDrive, sem controle de acesso nenhum.

No Supabase eles ficam sob RLS, alcançáveis só por usuário autenticado, e com
backup. É mais proteção do que têm agora, não menos.
O cache local desses dois cadastros continua em texto — é o mesmo arquivo de
hoje, no mesmo lugar, e cifrá-lo sem cifrar os outros seria teatro.

## Migração

Script `nuvem/migrar.py`, rodado uma vez, à mão, na máquina que tem os arquivos
bons:

1. lê os sete arquivos locais;
2. monta as linhas e **confere antes de subir**: recusa se `conferir_mapas`
   ainda acusar divergência entre os dois mapas, porque migrar divergência é
   levar o problema para dentro do banco;
3. sobe tudo numa transação;
4. relê do banco e compara com o que leu do disco, campo a campo.

O passo 4 não é zelo: é a diferença entre "subiu" e "está certo lá". Se a
comparação falhar, nada foi trocado no app e os arquivos continuam mandando.

O script fica no repositório e não entra no `codigo.zip` — é ferramenta de uma
vez só, como `aportes/conferir_contas.py`.

## Testes

O que dá para testar sem rede e sem tela, que é quase tudo:

- `rest.py` com respostas HTTP falsas: 200, 401 (token vencido), 403 (RLS
  negou), 500, timeout, e corpo que não é JSON. Cada um vira um erro nomeado,
  não um traceback.
- `sessao.py`: token válido, vencido, ausente, e `sessao.dat` corrompido —
  o mesmo cuidado que `ativacao.ja_ativado` já tem com marcador truncado.
- `cadastro.py`: banco responde → grava cache; banco mudo + cache presente →
  usa cache; banco mudo + sem cache → erro claro. As três linhas da regra.
- `migrar.py`: arquivos de exemplo **anonimizados** em `tests/fixtures/`,
  incluindo um par de mapas divergentes que a migração precisa recusar.
- O contrato do cache: o arquivo que o `cadastro.py` grava tem que ser lido
  pelos leitores atuais (`sicoob_contas.carregar`, `contas_mc.carregar`,
  `dados.carregar_contas`). Um teste por leitor, senão o cache vira um formato
  paralelo silencioso.

Regra que continua valendo: as fixtures são anonimizadas, porque o repositório
é público.

## Riscos

- **Projeto gratuito pausa por inatividade** (7 dias sem requisição). Com uso
  diário não acontece; depois de férias, despausar é um clique. O cache cobre
  a leitura enquanto isso.
- **Login quebrado tranca todo mundo.** É o mesmo risco que o `ativacao.dat` já
  tem, agora com rede no caminho. Mitigações: o token cifrado local vale sem o
  servidor, o CI roda os testes antes da release, e a política de manter 4
  releases permite voltar.
- **A anon key é pública.** Vale só o que a RLS deixa. Signup desligado é o que
  impede que "público" vire "qualquer um tem conta".
- **Dois cadastros de contas ainda coexistem durante a Fase 2.** Enquanto o
  banco não é a fonte, os arquivos mandam; depois que é, eles são cache. Não
  existe momento em que os dois estejam escrevendo — a troca é de uma vez, por
  release, com a migração já conferida.

## Fora de escopo (Fase 3, documento próprio)

- Aportes já lançados, hoje em `self.criados` na memória do processo.
- NSA do CNAB e histórico de remessas, hoje em `remessas.json` com trava de
  arquivo — que protege duas execuções na mesma máquina, não duas máquinas.
- Retorno CNAB: o que o banco respondeu de cada pagamento.
- Envios da Acessórias, hoje conferidos relendo o portal.
- Aba de cadastro dentro do app, se a edição pelo painel incomodar.
