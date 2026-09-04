# Comprovantes — Mais Controle

App Windows (Python/tkinter, distribuído como .exe via PyInstaller) que separa,
renomeia e anexa comprovantes bancários nos pagamentos do Mais Controle ERP.
Usuários finais são leigos: praticidade acima de tudo. Repo público:
https://github.com/gdiascabral/comprovantes-mais-controle

## Regra de ouro: como uma mudança chega ao usuário

**Gerar e liberar são dois atos, e desde 02/09/2026 há um portão entre eles.**
Antes eram um só: o push publicava a release e o `atualizador.py` a instalava
na abertura seguinte — do commit à máquina de quem paga contas davam 4 a 9
minutos, sem ninguém decidir nada. Num app que movimenta dinheiro, é uma
decisão que ninguém tomou (PR #1).

A `main` é **protegida**: não se empurra nada nela direto, toda mudança entra
por PR, e a trava vale **também para quem é admin** (`enforce_admins` ligado,
sem force-push e sem apagar a branch). O merge dispara o GitHub Actions
(`.github/workflows/build.yml`), que:

1. gera `versao.txt` = `v2.0.<run_number>` (NÃO é commitado; criado na build).
   Era `v1.0.<run_number>` até o commit `4be2c3d`, de 30/08/2026 — a numeração
   velha ainda aparece nos incidentes contados aqui embaixo (a v1.0.71, a
   run #76) e no `motor_minimo.txt`, e é a mesma esteira;
2. monta `codigo.zip` (comprovantes_app.py + util.py + widgets.py +
   inicio/*.py + separar_renomear/*.py + anexar/*.py +
   baixar_comprovantes/*.py + aportes/*.py + relatorios/*.py +
   pagamentos_dia/*.py + extratos_sicoob/*.py + conciliacao/*.py +
   conciliacao/erp/*.py + contratos/*.py + acessorias/*.py + **erp/*.py** +
   cnab240/*.py + **cnab240/spec/*.json** + **nuvem/*.py exceto migrar.py** +
   versao.txt + motor_minimo.txt + icone.ico).
   **Pasta nova de aba OU arquivo novo na raiz = linha nova aqui**, senão o
   import falha no usuário e o app não abre. Vale para os dois: `widgets.py` é
   de raiz e precisou entrar um a um;
   **`cnab240/spec/*.json` é a exceção que confirma a regra**: é o único pacote
   com DADOS, e copiar só os `.py` dele não quebra o import — quebra a primeira
   remessa, na máquina do usuário. Guardado por `tests/test_cnab240_pacote.py`;
   **`nuvem/migrar.py` é a exceção oposta**: fica de fora porque é ferramenta
   de uma vez só, rodada à mão no repositório, e o app nunca a importa;
   **`erp/` entrou sem consumidor nenhum** (PR #24) porque é biblioteca, como o
   `cnab240/`: o zip tem de conhecê-la ANTES de a primeira aba importá-la —
   código que chega depois de quem o importa é o app não abrindo na máquina de
   quem usa. Quem vigia a lista inteira é `tests/test_empacotamento.py`;
3. builda **um** exe — `Comprovantes Mais Controle.exe` (PyInstaller onefile,
   com Tesseract OCR embutido) — e publica a Release `v2.0.<run_number>`
   **como PRÉVIA** (`prerelease: true`), com o exe + codigo.zip, nos **dois**
   repositórios: o de código e o de artefatos
   (`gdiascabral/comprovantes-releases`, a constante `REPO` do
   `atualizador.py`). São dois passos porque é no de ARTEFATOS que o app
   procura, e fechar o portão só no de código o deixaria aberto exatamente
   onde os usuários olham. Os exes avulsos de Separar e de Anexar foram
   removidos: tudo vive em abas no app principal;
4. poda releases antigas — **por categoria**, mantendo as 4 mais novas e os 30
   dias de CADA uma. Piso único deixou de servir quando as duas categorias
   passaram a conviver, e o caso que ele quebra é o pior possível: uma semana
   de pushes sem liberar põe 4 prévias no topo, a última LIBERADA (a que está
   rodando na máquina de todo mundo) cai para a 5ª posição e some com o prazo,
   levando junto o caminho de volta que é o motivo de a poda ter piso. Prévia
   tem uma regra a mais: só entra na poda depois de **ultrapassada** por uma
   liberada mais nova — aí é prévia morta, porque ninguém libera versão
   anterior à que já está em produção; prévia que ainda pode virar a próxima
   versão fica, tenha a idade que tiver.

**O portão não é código nosso: é a semântica da API do GitHub.**
`/releases/latest` devolve, por definição, a release mais nova que não é
`prerelease` nem `draft` — e é o ÚNICO endereço por onde o `atualizador.py`
escolhe versão (`API_LATEST`, nas duas pontas: o `codigo.zip` da abertura e o
exe de ~152 MB). Por isso o PR #1 não mudou uma linha dele. A contrapartida é
que a dependência ficou invisível no código, e dependência que não aparece é
dependência que alguém apaga sem saber: quem a segura é
`tests/test_atualizador.py`, cujo dublê guarda a lista de releases e responde a
cada endereço como o GitHub responde (404 no `latest` quando não há liberada) —
trocando `API_LATEST` pela lista `/releases`, seis dos sete testes quebram.

**Quem entrega é gente, à mão.** Actions → **"Liberar uma versão para os
usuários"** (`.github/workflows/liberar.yml`) → Run workflow → a tag da prévia
(está no título dela, na aba Releases) → Run workflow. Leva segundos, e a
partir daí os apps a baixam sozinhos na próxima abertura. O workflow não gera
nada: o exe e o `codigo.zip` que vão ao usuário são os bytes que a build já
publicou — **liberar não pode ser uma segunda chance de mudar o que sai**. Ele
vira a chave nos dois repositórios, artefatos primeiro, e confere quatro coisas
antes de escrever: o formato da tag, o `TOKEN_ARTEFATOS`, que a release existe
e está inteira, e que a tag não é mais velha que a que já está em produção.
Duas armadilhas medidas contra as releases reais: o GitHub troca os espaços do
nome do asset por pontos, então a conferência procura o exe pela EXTENSÃO,
exatamente como `_url_do_exe()` faz; e `created_at` não é a data da publicação,
é a do commit que a tag aponta — no repositório de artefatos, que não recebe
commits, TODAS empatam, então a comparação de idade usa `publishedAt`, porque
um comparador que sempre empata nunca protege.

**`travar_versao.txt` enxerga prévia, e isso é o desenho, não um furo.** Com a
trava, o app busca `/releases/tags/<tag>`, que devolve prerelease igual. É
assim que se experimenta uma prévia numa máquina ANTES de entregá-la às
outras, e é a mesma porta por onde se volta de uma release ruim; exige um ato
humano (criar o arquivo ao lado do exe) e está coberto por teste. Sem rede, o
caminho de volta é renomear `codigo_velha` para `codigo`.
**O que essa porta cobrou em 03/09/2026**: travado na prévia v2.0.161, que
exigia motor novo, o app pegava o código na prévia e o exe no
`/releases/latest` — a última LIBERADA, a v2.0.120 —, trocava por um motor
que continuava abaixo do mínimo e baixava os mesmos 152 MB na abertura
seguinte, em laço, até a segunda troca cair sobre o onefile da primeira
("Failed to load Python DLL"). Antes do portão isso não existia, porque
`latest` era sempre a mais nova. Desde o PR do atualizador, o exe vem da MESMA
release do código e um motor que não satisfaz o mínimo não chega a ser baixado.

O exe do usuário é dividido em **motor** (Python + libs + OCR + `motor.py` +
`atualizador.py`) e **código** (o resto). Ao abrir, o app baixa só o
`codigo.zip` novo (segundos, sem perguntar) e roda com ele — o da release
**liberada**. Portanto:

- Mudanças em `comprovantes_app.py`, `util.py`, `widgets.py`, `inicio/`,
  `separar_renomear/`, `anexar/`, `baixar_comprovantes/`, `aportes/`,
  `relatorios/`, `pagamentos_dia/`, `extratos_sicoob/`, `contratos/`,
  `conciliacao/`, `acessorias/`, `cnab240/`, `nuvem/` e `erp/` → chegam
  sozinhas ao usuário no próximo abrir, **depois de liberadas**. Commitar e
  esperar a build deixou de bastar: falta virar a chave.
- Mudanças em `motor.py`, `atualizador.py`, dependências novas no
  `requirements.txt`/`requirements.lock` ou `--collect-all` no workflow →
  exigem exe novo. **Obrigatório**: subir `motor_minimo.txt` para a versão da
  release que sai (`v2.0.<run_number>`), senão o código novo roda em motor
  velho e quebra. O app então oferece o download completo (~152 MB) com
  progresso. **Chutar para CIMA é o erro caro**, e a build o barra antes de
  publicar: um mínimo acima da release que está saindo pede um motor que nunca
  vai existir, e o app entra em laço — oferece os 152 MB, baixa o exe mais novo
  que há, continua abaixo do mínimo e pergunta de novo na abertura seguinte, em
  todas as máquinas.
- **O `motor_minimo.txt` sobe UMA unidade quando só a esteira muda.** A trava
  do job `motor` é MECÂNICA: vigia cinco NOMES de arquivo — `motor.py`,
  `atualizador.py`, `requirements.txt`, **`requirements.lock`** e o próprio
  `.github/workflows/build.yml` — e recusa todo push que toque num deles sem
  subir o mínimo junto, sem olhar o que mudou dentro. Quando a mudança é de
  esteira (ruff, cobertura, uma pasta nova no zip), escrever ali a versão da
  release forçaria ~152 MB de download em toda máquina por nada; escrever uma
  unidade a mais (`v1.0.108` → `v1.0.109`) paga a trava sem cobrar pedágio de
  ninguém. Foi a decisão dos PRs #1, #7, #12 e #24 — este último começou em
  `v2.0.135` e voltou atrás no commit `6fc70dc`. O `requirements.lock` entrou
  nessa lista com o PR #12, e não é redundância com o `.txt`: quem manda no que
  vai dentro do exe é o LOCK, e trocar a versão de uma biblioteca por um
  recompile (uma correção de segurança dentro da mesma faixa) não toca no
  `.txt` — sem essa linha, o exe sairia com biblioteca nova e o `motor_minimo`
  apontando para o exe velho.
- **Import novo de SUBMÓDULO da biblioteca padrão também exige exe novo** —
  é a armadilha menos óbvia daqui, e ela derrubou a v1.0.71 nas duas máquinas.
  O PyInstaller não embute a stdlib inteira: ele segue os imports a partir do
  `motor.py`, e o que ninguém importa não entra no exe. `from tkinter import
  font` no `widgets.py` passou nos testes (aqui a stdlib está completa), passou
  no CI, saiu na release — e explodiu em `import widgets`, antes de existir
  janela para mostrar o erro, com o app simplesmente não abrindo. **Passar nos
  testes não prova que roda no exe.** O arrasto conta: `urllib.request` traz
  `parse` e `error` junto, mas `tkinter.ttk`/`filedialog`/`messagebox` NÃO
  trazem o `font`. Quem guarda isso é `tests/test_imports_do_motor.py`, que
  mede o que o exe de fato contém em vez do que o motor escreve. Até 03/09/2026 ele só olhava `tkinter` e `urllib`, os dois que já tinham mordido — e a v2.0.159 saiu com `from logging.handlers import RotatingFileHandler` no `util.py` (PR #8): `logging` chegava ao exe arrastado pelo `requests`, o teste de topo o dava como presente, e `logging.handlers` é outro arquivo, que ninguém importava. O app não abriu na máquina do dono, com a trava apontando para a prévia — que é exatamente o momento em que isso tem de aparecer. Hoje o teste olha qualquer `a.b` da biblioteca padrão que o app importe (`test_o_exe_tem_os_submodulos_da_stdlib_que_o_app_usa`). Precisando de
  um submódulo novo: acrescente ao `_garantir_dependencias()` do motor.py e
  suba o `motor_minimo.txt` no MESMO push. Preferir o caminho sem import novo
  quando existir — foi o que salvou este caso (o `_garantir_fontes` fala com o
  Tcl direto, e a correção chegou pelo codigo.zip em segundos, em vez de 152 MB
  para todo mundo baixar). É a mesma razão pela qual a fonte de ícones do menu
  (PR #28) é criada por `font create` e a lista de famílias sai do `font
  families` do Tcl.
- **Aba nova continua obrigando a mexer no `build.yml`** (item 2 acima), e por
  isso cai na trava mecânica do parágrafo anterior mesmo quando o código novo
  roda perfeitamente no motor velho. Foi o caso da aba Acessórias (v1.0.75):
  nenhum import novo, e mesmo assim todo mundo baixou o exe completo, porque o
  mínimo subiu para a versão da release. Hoje o pedágio é opcional — sobe-se
  uma unidade —, mas a trava dispara igual, então **vale agrupar abas novas num
  push só**.
- **O exe roda Python 3.11, e a sua máquina provavelmente não.** O CI usa 3.11
  e o PyInstaller embute essa versão; escrever contra um interpretador mais
  novo passa aqui e falha lá. Aconteceu na run #76: `Path.read_text(newline=…)`
  existe desde o 3.13 e o teste do CNAB 240 quebrou no CI, com o `build`
  pulado. É a mesma família do `tkinter.font` da v1.0.71 — código que a sua
  stdlib tem e a do usuário não. Antes de subir, `vermin --target=3.11
  --violations` sobre o que mudou (está no `requirements-dev.txt`), que hoje o
  job `test` também roda. É pela mesma razão que o `requirements.lock` é
  resolvido para 3.11/Windows e não para o interpretador desta máquina.
- **Build que falha CONSOME o número da release.** A versão é
  `v2.0.<run_number>`, e o contador anda mesmo quando o job quebra: depois da
  #76 falhar, a próxima release passou a ser a v1.0.77. Quem for corrigir e
  subir de novo tem de **subir o `motor_minimo.txt` junto**, senão ele aponta
  para uma versão que nunca existiu.
- Build leva ~8–10 min. Commits só de README/LICENSE/CLAUDE.md não disparam
  build (paths-ignore). **`docs/`, `supabase/` e `tests/` NÃO estão lá**: os
  dois primeiros porque documento novo é barato de construir e sai como prévia,
  que ninguém baixa; `tests/**` e `requirements-dev.txt` de propósito, porque é
  deles que sai a régua que o job `test` roda — ignorá-los seria dizer que
  mexer na régua não muda nada.

## Arquitetura

- `motor.py` — entrada do exe: escolhe a fonte de código (pasta `codigo/` ao
  lado do exe, ou `codigo_embutido` de fábrica), injeta em sys.path e chama
  `comprovantes_app.main()`. Contém `_garantir_dependencias()` (imports nunca
  chamados, só para o PyInstaller enxergar as libs).
- `atualizador.py` — motor-side: baixa codigo.zip, troca de pasta atômica,
  download do exe completo com janela de progresso, troca via .bat com 30
  retentativas (OneDrive trava arquivos). Loga em `atualizacao.log`.
- `util.py` — o que não é de aba nenhuma, e por isso é de todas: `pasta_base()`,
  `pasta_do_perfil()`, `log()`, `norm_espaco`, `filtrar`, `proteger_bytes`
  (DPAPI). **Não importa tkinter** (ver "Restrições"): o par visual dele é o
  `widgets.py`.
  **`util.log(nome)` é o diagnóstico do app, e é UM handler só.** Um
  `RotatingFileHandler` (1 MB, 3 cópias, utf-8) em
  `pasta_base()/diagnostico.log`, compartilhado por TODO nome que passar por
  aqui — handler por módulo seria trocar o diagnóstico espalhado de hoje por
  outro igualmente espalhado, só que com nomes de arquivo em vez de formatos
  diferentes. `nome` entra no FORMATO da linha, nunca no caminho do arquivo, e
  o prefixo `dd/mm/aaaa hh:mm:ss` é o mesmo que o `diagnostico.log` já gravava
  à mão, para quem abre o arquivo não estranhar a parte que olha primeiro. Três
  escolhas que não são detalhe: `delay=True`, então o arquivo abre no primeiro
  `emit` e uma pasta sem permissão de escrita não derruba a ABERTURA do app;
  **nenhum handler de console**, porque o exe é `--noconsole` e um
  `StreamHandler` apontado para um `stdout` que não existe é a mesma armadilha
  do `print()` — derruba o app, não só engasga o log; e `propagate=False`, para
  que o logger raiz, ganhando handler um dia, não duplique cada linha.
  **A regra de adoção**, aplicada módulo a módulo (PRs #8, #11, #13, #14, #17,
  #19 e #20): `except Exception` que engole **sem comentário que justifique**
  vira `log.warning("o que eu estava fazendo", exc_info=True)` e continua
  engolindo — nenhum `except` foi estreitado nem removido, e nenhum
  comportamento mudou. **A exceção é o laço de espera**: dentro de um
  `while … < limite`, ou de uma escada de seletor/rótulo/tamanho, a exceção não
  é falha, é o "ainda não" da próxima volta; um traceback a cada 0,5 s enche
  1 MB numa rodada só e rotaciona para fora justamente o que interessa. Ali o
  `pass`/`continue` fica, com uma linha dizendo por quê, e quem avisa é o
  **desfecho** do laço — uma vez, e sem `exc_info`, porque ali não há exceção
  viva. Nenhuma mensagem carrega favorecido, valor, número de conta ou token: o
  `diagnostico.log` é arquivo comum na pasta do exe. E cuidado com o nome
  `log`: em `conciliacao/erp/`, `baixar_comprovantes/` e `aportes/` quase toda
  função já recebe um parâmetro `log`, que é o recado do Registro da aba e
  SOMBREIA o logger do módulo — ali o diagnóstico sai por `_diag`, o mesmo
  objeto com outro nome. O Registro conta o que a rotina está fazendo; o
  arquivo guarda o traceback do que não deu.
  **`cnab240/` é a exceção que confirma a regra.** Ele é stdlib pura — nem
  `util` pode importar, e `tests/test_cnab240_pacote.py` cobra isso por AST —,
  então emite em `logging.getLogger(__name__)`, como biblioteca faz, e deixa a
  APLICAÇÃO dizer para onde vai. Quem liga os dois é UMA linha na abertura,
  `util.log("cnab240")` em `main()`, que pendura o handler no logger pai e
  recebe os filhos por propagação. **Nunca pendurar um `NullHandler` no logger
  `cnab240`**: o `util.log()` só instala o handler `if not logger.handlers`, e
  um NullHandler ali silenciaria a ligação para sempre, e em silêncio.
  **`util.pasta_do_perfil(nome)` é o único lugar que sabe onde mora o perfil do
  Chrome.** Ele era calculado de DOIS jeitos: ao lado do MÓDULO
  (`_AQUI = Path(__file__)…`, que muda conforme quem executa é o script ou o
  exe) e na pasta BASE. Rodando como script, o primeiro fazia nascer um SEGUNDO
  conjunto de perfis dentro do repositório — medido em **219 MB** de sessão de
  banco duplicada. Congelado o lugar nunca mudou, então o desencontro só
  aparecia em desenvolvimento, que é justamente onde se testa: é a mesma
  família do defeito do cache do cadastro ("quem lê o cache tem de usar
  `util.pasta_base()`"). Nenhum nome de pasta mudou, e há teste conferindo byte
  a byte os que já estavam instalados. Pelo mesmo caminho vieram depois o
  `ARQUIVO_DIAG` (PR #8) e o `login.dat` (PR #26), que também nasciam dentro de
  `anexar/` em modo script — e era por isso que a sonda, rodando da raiz, não
  achava a senha do ERP. Falta um: o `ARQUIVO_LOG` (`log_anexos.csv`) do
  `anexar/config.py` ainda sai do `_AQUI`.
- `erp/` — um lugar só para falar com o Mais Controle, com **a regra dos dois
  tokens escrita UMA vez**. Oito lugares do app tinham redescoberto por conta
  própria qual token pedir, quais cabeçalhos copiar e qual `user-agent` passa
  pelo WAF, e o conhecimento se contradizia POR ESCRITO — um arquivo dizia "o
  token é o `jwtToken`, NÃO o `accessToken`" e outro dizia o contrário, os dois
  certos para back-ends diferentes, e nenhum dizendo isso inteiro. O inventário
  que levantou tudo, com `arquivo:linha` para cada afirmação, é
  `docs/ERP-CLIENTES.md` (PR #22); o pacote é o PR #24. Três módulos, uma frase
  cada: `hosts.py` é ONDE (só endereços, não fala com ninguém — as mesmas
  quatro URLs estavam escritas em sete arquivos), `sessao.py` é QUEM (o login,
  os dois tokens, os cabeçalhos por host, o `user-agent` e o transporte HTTP
  direto) e `pagina.py` é COMO, quando é pelo navegador (o
  `page.evaluate(fetch)` que estava duplicado em `anexar/mc_api.py` e
  `aportes/mc_catalogos.py`, com espaçamento diferente).
  **A regra, em `sessao.token_para`**: o login é UM só
  (`POST {legacy}/users/login`) e devolve DOIS tokens — `jwtToken` (~348 chars,
  JWT, vale 24 h) é o do `prod-erp-api`; `accessToken` (27 chars, nem é JWT,
  vive SEGUNDOS) é o do `legacy-api`. Trocar um pelo outro devolve 401, e vale
  igual para o token capturado do navegador: foi assim que o token da
  telemetria acabou usado contra o `prod-erp-api`. Os cabeçalhos também são
  conjuntos diferentes (`cabecalhos_para`), e **só o legado manda `user-id`** —
  sem ele o ERP recusa o lançamento com "não achei o usuário responsável", que
  não aponta para lugar nenhum.
  **O 401 do legado é rotina; o do `prod-erp-api` é notícia.** No legado o
  token venceu entre uma chamada e a seguinte, então `Sessao.pedir` relogia
  **uma vez** e repete — e **só em GET**, ou em PUT/POST que o CHAMADOR marcar
  com `idempotente=True`, porque um POST que criou lançamento e perdeu a
  resposta duplica o que criou (ver "Aporte não se repete"). O padrão é o
  seguro: esquecer a marca custa uma exceção, pôr a marca onde não cabe custa
  uma segunda baixa. No `prod-erp-api` um token de 24 h recusado é sessão
  derrubada de verdade — o ERP aceita UMA sessão por usuário, e relogar ali
  seria tomá-la de volta, em silêncio, de quem estiver com ela; sobe
  `SessaoRecusada` e quem chamou decide. Quem separa os dois casos é
  `ErpErro.codigo`, o status HTTP, e **não o TEXTO da mensagem** — decidir por
  `str` quebra na primeira vez que alguém melhora a frase. Sessão nascida de
  `de_login` fica sem a credencial em memória e por isso não relogia: ninguém
  relogia em nome de quem não entregou a senha.
  **A migração é uma aba por PR, e três já entraram.**
  `conciliacao/erp/api.py` virou casca sobre `erp.Sessao` (PR #31) — mesma
  classe, mesmo construtor, mesmos retornos e as mesmas exceções, e por isso
  `nuvem/contas_novas.py` e `ferramentas/sonda.py`, que emprestam o `SessaoApi`,
  migraram de graça, sem serem tocados; o laço de 3 tentativas escrito à mão
  saiu, porque falando por `requests` o `Retry` vem pronto.
  `pagamentos_dia/baixa_erp.py` (PR #33) foi o mais barato porque **nunca soube
  se havia navegador**: exige do transporte só `_buscar`/`postar` e lê
  `{"__erro": status}`, que é exatamente o que `erp.TransportePagina` expõe — e
  a baixa dele **não é marcável como idempotente**, porque o `POST .../paids`
  CRIA um pagamento. Faltam os consumidores 4 a 8 da ordem escrita no fim do
  `docs/ERP-CLIENTES.md`, e **`anexar/mc_api.py` é o último de propósito**: é
  ele que tira o token do cabeçalho da página logada e monta a consulta
  reaproveitando a URL que a TELA mandou, e dele dependem Anexar, Conferência,
  Pagamentos do Dia e Contratos — migrar isso é trocar a fundação com a casa em
  cima. Enquanto ele não migra os dois convivem, o que é aceitável: o `erp/`
  nasce sabendo a regra dos tokens, e ele nasceu adivinhando-a.
- `conciliacao/` — aba Conciliação Diária: lê saldos e pagamentos a vencer e
  gera o painel do dia sobre o `MODELO.xlsx`, com o aporte mínimo por conta.
  **Foi o primeiro pacote de verdade do app, e desde 02/09/2026 todas as
  pastas são** (PR #38): as sete que faltavam ganharam `__init__.py`, os 105
  `sys.path.insert` viraram 3 — os três põem a RAIZ e nada mais (`motor.py`,
  `tests/conftest.py`, `cnab240/ferramentas/_ambiente.py`) — e todo import diz
  o caminho inteiro (`from conciliacao.frame import ...`, `from
  anexar.conferencia import ...`). O que isso desfez: com as pastas entrando
  planas no `sys.path`, nome de módulo era global, e havia `config.py` em três
  pastas, `frame.py` em três, e `conferencia.py`, `regras.py`, `pipeline.py` e
  `sicoob_baixar.py` em duas cada — `from conferencia import ConferenciaFrame`
  acertava a aba certa só porque `contratos/` não estava na lista de
  inserções. O prefixo `sicoob_` do `extratos_sicoob/` e o sufixo `_pagamento`
  de `pagamentos_dia/regras_pagamento.py` são as cicatrizes dessa época:
  continuam (renomear mexe em quem usa sem melhorar quem lê), mas deixaram de
  ser exigência. Quem guarda a regra é `tests/test_nomes_de_modulo.py`, que
  descobre as pastas em vez de listá-las e falha se alguma subpasta voltar ao
  `sys.path`. Módulo isolado roda `python -m pacote.modulo` da raiz — o
  `try/except ImportError` que cada arquivo carregava não existe mais; a sonda
  agendada é `python -m ferramentas.sonda`.
  Veio de um projeto separado que rodava por `.bat`, e os `.bat` continuam lá
  como plano B — **não rodar os dois ao mesmo tempo**, porque o ERP aceita uma
  sessão por usuário. É essa regra que explica o desenho: `coletar_com_pagina()`
  usa a página do Anexar em vez de abrir Chrome próprio, e a credencial da API
  sai do `login.dat` (DPAPI) em vez do keyring — duas senhas em cofres
  diferentes só criam a chance de uma envelhecer e o erro virar "login
  inválido" sem motivo aparente. `pipeline.py` não toca em navegador: recebe um
  `Snapshot` e devolve o resultado, e é por isso que os 9 arquivos de teste
  vieram junto sem alteração. A coleta usa DOIS caminhos: saldos pela API REST
  (a raspagem da tela de contas quebrou duas vezes) e pagamentos pela grade,
  que ainda depende do layout. `config.yaml`, `mapping.yaml` e `MODELO.xlsx`
  ficam FORA do repo (nome de empresa, estrutura do painel, rateios); as
  fixtures dos testes pulam quando faltam, então o CI passa sem os dados reais
  e a máquina de quem usa valida de verdade. Saída em
  `C:/Arquivos Morais/CONCILIACAO DIARIA/<ANO>/<MÊS>/`.
- `comprovantes_app.py` — janela única, em TRÊS faixas desde o redesenho de
  agosto/2026, e cada faixa responde a uma pergunta diferente: a barra azul do
  topo (`widgets.BarraTopo`) diz onde estou, o que procuro e se o app está
  livre; o menu branco de 232 px à esquerda (`widgets.painel_menu`, que devolve
  um `widgets.PainelMenu`) diz para onde vou; e o painel cinza no meio
  (`style="Fundo.TFrame"`) é o que estou fazendo agora. Antes eram duas faixas,
  e a coluna da esquerda acumulava navegação, tema, versão, usuário e estado do
  navegador. **O estado do navegador era o pior deles**: é a informação que se
  procura ANTES de clicar noutra aba, e ficava no ponto mais baixo da tela,
  longe dos itens do menu.
  As doze telas em quatro seções: VISÃO GERAL (Início), COMPROVANTES (Baixar
  Comprovantes, Separar e Renomear, Anexar, Conferência, Aportes) e os dois
  grupos que abrem e fecham — DIÁRIO (Remessa/Retorno, Saldo de pagamentos) e
  MENSAL (Relatório Mensal, Extratos Sicoob, Contratos, Acessorias). "Baixar"
  vem antes de "Separar" e "Anexar" porque é a ordem do dia. Os rótulos
  encurtaram junto com a coluna ("Anexar Comprovantes" dentro de um menu
  chamado COMPROVANTES repetia a palavra em duas alturas) e dizem o que a aba
  FAZ hoje, não o que ela fazia quando nasceu. No rodapé do menu, fora da lista
  de rotinas: Usuários (só admin), o TEMA, a `Pilula` de cadastro
  sincronizado/offline e a versão — administrar quem entra não é rotina do dia.
  Quem decide o que aparece é `usuarios.abas_do_papel`, mas as abas são TODAS
  construídas: metade delas divide o navegador e a thread do Anexar, e deixar
  de criar umas e não outras mexeria nessa fiação por um motivo que é só de
  menu. Esconder também não é o que protege — quem nega o dado é a RLS.
  **O item ativo do menu não é `Accent.TButton`.** É `widgets.ItemMenu`: fundo
  azul-claro (`marca_fundo`), texto azul (`marca`) e um filete de 3 px na borda
  esquerda. O botão de destaque do sv-ttk é azul CHEIO, e com doze itens numa
  coluna o aberto virava o objeto mais pesado da janela inteira — mais forte
  que o botão verde de executar da tela que ele acabara de abrir. Os três
  sinais juntos porque o filete sozinho some em tela pequena e o fundo sozinho
  não distingue "aberto" de "o cursor está em cima".
  DIÁRIO e MENSAL continuam `Grupo.Toolbutton` (chapado e miúdo, para
  parecerem os rótulos de seção que estão logo acima deles, e não itens
  clicáveis do mesmo nível das abas que agrupam), e os itens do grupo entram
  com recuo — sem ele, fechar o grupo era a única pista de que existia um
  grupo. O cabeçalho continua sendo `ttk.Button`, e não Label com bind de
  clique, para não sair do Tab e do Espaço. O estado de cada grupo fica em
  `preferencias.json`, e selecionar uma aba de grupo fechado o abre — senão a
  aba ficaria destacada e invisível.
  **O pulso de 600 ms (`_pulso`) pergunta a TRÊS navegadores, não a um**: o do
  ERP (via `aba_anx.dona_ocupada()` e `aba_anx.ocupado()`) e os de
  `extratos_sicoob/` e `acessorias/`, que são processo e login à parte. A
  Separar entra na mesma varredura sem ter navegador nenhum — o trabalho dela é
  OCR e disco, mas um PDF de 107 páginas leva minutos e a aba que não responde
  parece parada; vem por último para nunca disputar o sinal com quem está com
  um Chrome na mão, que é a informação mais cara. A aba que trabalha troca o
  ícone por ● (`ItemMenu.trabalhando`) e a frase sobe para o chip da barra
  (`widgets.ChipStatus.definir`), com bolinha verde parada quando está livre e
  âmbar quando está ocupado, mais as reticências que andam. Antes disso, as
  abas que dividem um navegador só se manifestavam DEPOIS do clique, no aviso
  "Navegador ocupado".
  Mais duas coisas que a moldura faz e não são óbvias no código: (1) trocar de
  aba põe o foco no primeiro `Entry` (`widgets.focar_primeiro_campo`, num
  `after_idle` porque a aba recém-empacotada ainda não tem geometria, e é a
  geometria que decide qual campo é o de cima — Combobox `readonly` é pulada de
  propósito, porque aceita foco sem aceitar digitação); (2) trocar de aba chama
  o `ao_abrir()` dela, quando existe. É assim que o Início relê o
  `atividade.jsonl` em vez de mostrar o número de quando o app abriu — recontar
  é barato porque é arquivo local, e número velho na primeira tela é justamente
  onde ele mais parece verdade.
  **Enter num campo de texto aciona o passo principal da aba**, procurado em
  `acao_enter`, `b1`, `btn` (nessa ordem). O bind é global (`bind_all`), então
  o handler confere pelo caminho do widget se o foco está DENTRO da aba — senão
  o Enter de um diálogo dispararia a aba atrás dele. Nunca a partir de um
  `Text`: ali Enter é quebra de linha, não ordem para começar meia hora de ERP.
  Tema Automático (lê o registro do Windows)/Claro/Escuro salvo em
  `preferencias.json`. `aplicar_tema` chama, nesta ordem, `sv_ttk.set_theme`,
  `widgets.aplicar_estilos`, `widgets.barra_de_titulo` e o
  `aplicar_cores(escuro)` de cada aba — que hoje só trata `tk.Text` e
  `tk.Canvas`, porque o resto segue os estilos nomeados de `widgets.py`. A
  versão aparece CURTA ("v2.0", o que se fala em voz alta) em três lugares —
  título da janela, canto direito da barra e rodapé do menu —, e o número de
  build inteiro fica na `widgets.Dica` dos dois rótulos: ele muda a cada push e
  entre a v2.0.108 e a v2.0.109 pode não haver diferença nenhuma na tela.
  Fechar a janela (`_sair`) percorre TODAS as abas atrás de um `fechar()`, e
  não uma tupla escrita à mão: a lista fixa citava dois navegadores e o Chrome
  da Acessórias sobrevivia ao fechar do app, esperando o Gerenciador de
  Tarefas — que é justamente o que deixa Chrome órfão.
  **Estado em 02/09/2026.** O que está assim hoje, e não o que se decidiu que
  fosse; quem consertar faz em PR próprio. Três dos quatro itens que moravam
  aqui foram resolvidos no mesmo dia e viraram parágrafo na entrada do
  `widgets.py`: a busca da barra passou a levar a alguma tela (PR #32), o
  `ItemMenu` passou a entrar no Tab e a responder ao Espaço (PR #28), e os
  ícones do menu saíram do sorteio de fontes e passaram a seguir o tema
  (PR #28) — este último estava aqui não só desatualizado, mas **contado ao
  contrário**: o `font actual` mostrou que ✂, ✅ e ⚖ também caíam em fonte
  colorida, e não apenas os sete de fora do BMP. Continua valendo o quarto: o
  `ComprovantesFrame` (Baixar Comprovantes) não expõe `ocupado()`, então o
  trabalho dele não acende o ● nem o chip; `_quem_trabalha` engole a falta do
  método de propósito ("aba sem o método: só não sinaliza"), então isso não dá
  erro — só não aparece. E o `_sair` engole com um `except Exception: pass`
  mudo o que cada `fechar()` levantar: a razão está escrita ali (um `fechar()`
  que estoura não pode impedir o outro nem o `destroy()`, senão o jeito de sair
  vira o Gerenciador de Tarefas, que é o que deixa Chrome órfão), mas hoje
  ninguém fica sabendo que estourou.
- `widgets.py` — o par visual do `util.py` (mora na raiz e vai junto no
  codigo.zip, um a um). Depois do redesenho de agosto/2026 ele é a única forma
  de o app ganhar uma cor: nenhuma aba escreve `#` seguido de seis dígitos. Ali
  dentro moram a `PALETA` nos dois temas, as onze fontes nomeadas e os blocos
  que toda tela monta — `Botao`, `Cartao`, `Cabecalho`, `Campo`, `Pilula`,
  `BarraFina`, `BarraExecucao`, `RodapeTabela`, `Dica`, `ComboBusca`,
  `CampoData` —, a moldura da janela (`BarraTopo`, `PainelMenu`/`painel_menu`,
  `ItemMenu`, `ChipStatus`, `Avatar`), as tabelas (`estilo_tabela`,
  `linha_zebrada`, `estado_de`, `ESTADOS`, `MARCAS_ESTADO`), o registro
  (`estilo_log`, `registro_elastico`, `cartao_elastico`, `colorir_registro`,
  `tem_conteudo_real`, `estilo_campo_texto`, `estilo_canvas`), o
  `focar_primeiro_campo`, o `barra_de_titulo` e os helpers do
  `atividade.jsonl` (`registrar_atividade`, `atividades`, `ultima_atividade`,
  `quando_humano`).
  **A cor é estilo nomeado e o tamanho sai do `TkDefaultFont`.** Existia o
  oposto disso — 51 cores e 17 tuplas de fonte espalhadas por 12 arquivos —, e
  as duas consequências eram visíveis: cor escrita na criação do widget não
  segue o tema (`#6b6b6b` tem 3,2:1 no escuro, `#8a8a8a` tem 3,4:1 no claro:
  cada cinza falhava em UM dos dois), e tamanho de fonte em número fixo ignora
  a escala de exibição do Windows — quem usa 150% via os títulos miúdos, e é
  justamente quem aumentou a escala que precisava deles maiores. Hoje a cor é
  estilo nomeado (`Apoio.TLabel`) e as onze fontes (`FONTE_TITULO` a
  `FONTE_MARCA`) são DERIVADAS do `TkDefaultFont` por um fator, em
  `_garantir_fontes`: ele já vem na família e no tamanho que a pessoa escolheu
  no Windows, então a escala é respeitada sem o app precisar consultá-la. A
  mesma régua vale para o `rowheight` do Treeview, que sai da MÉTRICA da fonte
  e não de um número fixo — a 150% uma linha de 26 px corta o texto pela
  metade. Toda cor de TEXTO da paleta passa de 4,5:1 sobre o fundo em que
  aparece, medida (não estimada) e anotada ao lado do valor; as quatro cores do
  mockup que não passavam entraram um tom mais escuras, e as duas originais que
  ainda serviam viraram `linha` e `acao_viva`, usadas só onde não há texto por
  cima. O registro é escuro NOS DOIS TEMAS (`LOG_CORES`), de propósito: é um
  terminal embutido, e um terminal claro no meio de um painel claro deixa de se
  distinguir do formulário logo acima.
  **`marca_solida` é o azul que leva branco por cima**, e nasceu de uma medida
  que faltava. A `marca` do tema escuro (`#6F9BFF`) entrega 6,3:1 como TEXTO, e
  o comentário ao lado dela estava certo — só que o app a usava também como
  FUNDO SÓLIDO, nos botões de passo e nos círculos numerados dos cartões, e
  branco sobre ela dá **2,69:1**: abaixo até dos 3:1 que a WCAG pede de
  componente, em ~29 pontos presentes em quase toda tela, e só para quem usa o
  escuro. Os testes não pegaram porque mediam cor de TEXTO contra o fundo do
  painel, **numa direção só**. A correção não foi escurecer a `marca` — ela é
  texto no KPI, no item aberto do menu e na linha selecionada da tabela, e
  escurecê-la estragaria os três — e sim SEPARAR o papel, como o projeto já
  fizera com `acao`/`acao_viva` e `tenue`/`linha`: `marca_solida` é a mesma cor
  no tema claro (que não muda um pixel) e `#3B6FE0` no escuro, onde o branco
  por cima passa a **4,63:1**. A ordem dos dois commits também é parte da
  decisão: o teste veio ANTES da cor (`b040c19`, depois `c9a9085`) e falhou em
  exatamente um par, que é como se prova que ele media o defeito. Junto veio um
  teste que CONSTRÓI o botão e o cartão e confere que a cor que eles pintam é a
  mesma que a tabela mede — tabela escrita à mão envelhece, e sem isso trocar a
  cor do botão passaria verde medindo a cor antiga.
  **`aplicar_estilos(escuro)` tem de ser chamado DEPOIS de `sv_ttk.set_theme`**:
  o sv-ttk recria o tema do ttk e apaga todo estilo nomeado, e a ordem errada
  não dá erro — as legendas só voltam à cor padrão. Duas armadilhas do Tk que
  o `tests/test_visual.py` cobre: `tkinter.font.Font.__del__` executa
  `font delete`, então a fonte precisa de referência viva (sem isso o Tk lê
  "AppTitulo" como nome de FAMÍLIA e cai no padrão, em silêncio) — e é por isso
  que `_garantir_fontes` fala com o Tcl direto (`font create`/`font configure`)
  em vez de importar `tkinter.font`, que além do `__del__` não está no exe (ver
  v1.0.71 na regra de ouro); e tamanho negativo é medida em pixels, então
  `_escalar` tem de preservar o sinal.
  **O botão e o cartão são widgets CLÁSSICOS do Tk, e isso não é regressão.**
  O sv-ttk desenha botão e moldura a partir de IMAGENS, com a cor assada dentro
  de cada canto arredondado: `style.configure(background=…)` não muda uma
  imagem, e copiar o layout do `Accent.TButton` significaria gerar um jogo de
  imagens novo por cor e por tema. O `Botao` é `tk.Button` e aceita a cor
  direto (papéis: `acao` verde, `passo` azul, `neutro`, `link`, `perigo`); o que
  ele não sabe é seguir o tema, e por isso todo widget clássico se inscreve na
  `WeakSet` `_repintaveis`, que `aplicar_estilos` percorre. `WeakSet` e não
  lista: aba fechada, diálogo destruído e calendário que sumiu não podem
  continuar vivos só porque a paleta os conhece. Canto RETO e não arredondado
  pelo mesmo motivo — o Tk não tem canto arredondado em widget de verdade, e
  desenhar um num Canvas tiraria do `Cartao` a única coisa que as catorze
  telas que o usam fazem com ele, que é empacotar `ttk.Label` e `ttk.Entry`
  dentro.
  **O `Cartao` tem DOIS frames**: `self` é o CONTEÚDO e `self.moldura` é a
  borda com o título, e é a moldura que entra no `pack` do pai — todas as
  chamadas de geometria são redirecionadas para ela, inclusive traduzindo
  `after=outro_cartao` para a moldura dele. O motivo é uma regra do Tk, não
  gosto: um mesmo pai não pode ter filhos no `pack` e filhos no `grid`. Com o
  título empacotado dentro do próprio cartão, as quatro abas que montam
  formulário em `grid` estouravam com "cannot use geometry manager grid inside
  … which already has slaves managed by pack". O `destroy` tem uma trava contra
  `RecursionError` pelo mesmo desenho: `moldura.destroy()` percorre os filhos
  DELA, e um deles é o próprio cartão.
  **Quem numera é o CARTÃO, e só ele.** Numerar os dois punha duas contagens na
  mesma tela: em Remessa/Retorno "2. Contas" era um campo para preencher e
  "2. Gerar a planilha" era uma ação, nenhuma das duas ia até o fim sozinha, e
  as contagens nem batiam. Hoje o número é o círculo azul do
  `Cartao(titulo, numero=…)` — desenhado num Canvas porque `Label` no Tk é
  sempre retângulo — e os botões vão sem número. A `widgets.Passos`, a trilha
  ①→✓ que numerava as AÇÕES no cabeçalho, foi REMOVIDA no redesenho junto com
  os três testes que a cobriam: mantê-la seria exatamente a contagem em dobro
  que o docstring dela existia para descrever. Ficou um comentário no lugar, em
  `tests/test_visual.py`, para o próximo que procurar por ela.
  **A barra de título é do Windows, não do sv-ttk.** O tema pinta o conteúdo
  da janela; a moldura vem do DWM, com quem o Tk não fala — daí a faixa clara
  em cima do app escuro, bem onde o olho bate primeiro.
  `barra_de_titulo(janela, escuro)` resolve por `DwmSetWindowAttribute`, e
  **toda janela nova precisa chamá-la** (a principal, a de ativação, o
  calendário, o login, as dúvidas, o confirmar do Pagamentos, o resolver dos
  Contratos). Dois detalhes: o HWND de verdade é o PAI do `winfo_id()` (aquele
  é a janela filha que o Tk desenha por dentro, e pintá-la não muda moldura
  nenhuma); e o atributo é 20 do Windows 10 20H1 em diante, 19 antes — a
  função tenta os dois e engole qualquer falha, porque moldura na cor do
  sistema é o comportamento antigo, não um defeito novo.
  **O calendário do `CampoData` NÃO é modal.** Ele já teve `grab_set`, herdado
  do "modal como o resto dos diálogos", e grab entrega TODO clique e TODA
  tecla do app àquela janela: o resto ficava surdo e nem o X da principal
  fechava o programa — quem abrisse o calendário sem querer ficava preso.
  Escolher data é oferta, não pergunta. Sem grab (e sem fechar por
  `<FocusOut>`, que matava o popup ao abrir), sobra uma janela comum, com três
  saídas: a data, `Esc` e o clique fora. Como nada mais impede abrir dois, o
  módulo guarda em `_calendario_aberto` qual campo está com o seu — abrir um
  fecha o outro. Regra geral: modal é para o que EXIGE resposta (o login, o
  confirmar dos sócios); o resto não prende ninguém.
  **O clique SIMPLES abre o calendário, e esse contrato já inverteu uma vez.**
  Em 11/08/2026 abrir no clique tornou o campo impossível de editar em todas as
  abas de uma vez, porque o popup pegava o foco, e o conserto de então foi
  exigir duplo clique. O redesenho pediu o clique simples de volta, e o
  conserto agora é outro: o popup não pega foco NENHUM. Daí as duas regras que
  não são estilo — os dias são `tk.Label` com bind de clique, e não botões
  (botão aceita foco, e aceitar foco é o que tiraria o cursor do campo), e o
  fechamento nunca é por `<FocusOut>` (o popup nasce sem foco por construção, e
  o evento o matava antes de ele aparecer). Abrir sem deixar de ser digitável é
  o contrato INTEIRO, e `tests/test_widgets.py` guarda as duas metades
  (`test_clique_simples_abre_o_calendario` e
  `test_com_o_calendario_aberto_o_campo_continua_editavel`): testar só a que
  abre deixaria a regressão de 11/08 passar de novo.
  **O Registro cresce com o que tem dentro** (`registro_elastico`): parado ele
  era metade da janela em branco com uma frase cinza no meio, enquanto o
  formulário ficava espremido em cima. Quem dispara é o `<<Modified>>` do
  próprio campo, e não a aba — as onze telas que têm registro escrevem nele de
  lugares diferentes (`_drain`, `_log`, placeholder), e pedir que cada uma
  avisasse daria dezenas de pontos de chamada para esquecer um. É pelo mesmo
  `<<Modified>>` que passa a pintura das linhas (`colorir_registro`, que guarda
  até onde já passou porque repintar milhares de linhas a cada mensagem trava a
  janela). A tela vazia não conta como
  trabalho porque entra toda com a tag "ph". Duas armadilhas: `pack_configure`
  e nunca `pack` (reempacotar joga o widget para o FIM da ordem, e em cinco
  abas o Registro nasceria embaixo da barra de ação — vale igual para o
  `cartao_elastico`); e a altura do campo vazio é MEDIDA a cada mudança, porque
  `height` conta linhas enquanto `spacing1` cobra pixels — com altura fixa o
  Anexar cortava ao meio justamente a frase que diz o que fazer.
  **Nas tabelas, só `atencao` e `erro` se pintam.** A tag do Treeview pinta a
  LINHA inteira (o Tk não tem cor por célula), e pintando os quatro estados uma
  tabela de dez rotinas virava faixas verdes, azuis e vermelhas alternadas — e
  aí nada se destaca, que é o oposto do que a cor está ali para fazer. Os
  quatro continuam distinguíveis pelo SÍMBOLO que vai junto do texto
  (`MARCAS_ESTADO`: ✓ ⚠ ✖ ·), porque cor sozinha não distingue nada para quem
  não a vê. A ORDEM importa e não é a da leitura: no Treeview ganha a tag
  configurada PRIMEIRO, não a última da lista do item, então os estados são
  configurados antes da zebra — uma linha rejeitada não pode ficar cinza só por
  ser par. **Ressalva de 02/09**: isto descreve o desenho, e não o que se vê
  hoje — `estado_de` está devolvendo `"info"` para tudo, então nenhuma linha se
  pinta. Ver a seção "02/09/2026 — a consolidação".
  **O `atividade.jsonl` é o que permite ao Início não abrir o navegador.** Cada
  rotina, ao terminar, chama `registrar_atividade` com os números que ACABOU de
  apurar; o Início lê o arquivo e mostra. Arquivo e não banco: é histórico de
  UMA máquina, tem de continuar legível com a nuvem fora, e ninguém decide
  dinheiro por ele. JSONL porque escrever é sempre `append` — uma linha
  corrompida custa uma linha, não o arquivo — e `MAX_ATIVIDADE` = 400 põe teto,
  já que o Início o lê inteiro na abertura. `registrar_atividade` NUNCA levanta:
  o pior caso é o Início mostrar um evento a menos, e isso não pode parar
  trabalho nenhum.
  **O `ItemMenu` entra no Tab** (PR #28). Ele era `tk.Frame` e só escutava
  `<Button-1>`, `<Enter>` e `<Leave>`: quem usa só o teclado alcançava DIÁRIO e
  MENSAL — que são `ttk.Button` — e não alcançava NENHUMA das doze telas que
  eles agrupam, o contrário da regra escrita dois parágrafos acima do código
  que a desmentia. Hoje tem `takefocus=1`, e `<Return>` e `<space>` disparam o
  **mesmo** `_comando` do clique: um caminho só, senão existiria a chance de o
  teclado abrir uma aba e o mouse abrir outra. Mais `Ctrl+1`..`Ctrl+9` e
  `Ctrl+Tab`/`Ctrl+Shift+Tab` no `bind_all`, como o `Ctrl+K` já estava, com a
  ordem saindo do próprio dicionário de itens — uma segunda lista escrita à mão
  divergiria em silêncio, com o `Ctrl+3` abrindo a quarta tela. Duas
  armadilhas: o handler do `Ctrl+Tab` **recusa quando o foco está num
  `tk.Text`**, porque a classe `Text` do Tk já liga essa tecla à navegação de
  foco e a ligação dela roda antes da nossa — sem a pergunta, um `Ctrl+Tab`
  dentro do Registro moveria o foco *e* trocaria de aba; e a espessura do anel
  de foco **nunca muda** (o Tk troca sozinho `highlightbackground` por
  `highlightcolor`), porque 1 px entrando e saindo do layout empurraria a
  coluna inteira a cada tecla. Quem carrega o sinal do foco é o ANEL na cor
  `marca` (7,67:1 contra a coluna no claro, 6,28:1 no escuro, e 5,23:1 sobre o
  item já aberto), e não o fundo, que sozinho não distingue nada (1,16:1).
  **Os ícones do menu vêm de UMA família** (`FONTE_ICONES`, "AppIcones"), e
  antes não vinham. Medido nesta máquina com `font actual`, os doze caíam em
  pelo menos quatro tipografias diferentes numa coluna de doze linhas — sem
  dividir espessura de traço, tamanho nem linha de base —, e os que caíam na
  Segoe UI Emoji são glifos COLORIDOS, que o `foreground` do `_pintar` não
  alcança: ficavam idênticos nos dois temas, inclusive quando todo o resto do
  item virava azul. Hoje é **Segoe Fluent Icons** (Windows 11) com queda para
  **Segoe MDL2 Assets** (Windows 10), monocromáticas por construção, e o emoji
  continua no código como CHAVE da tabela — é ao mesmo tempo o nome lógico do
  ícone e o último fallback, e por isso nem o `comprovantes_app.py` nem a
  `ferramentas/galeria.py` mudaram uma linha. **Duas tabelas, uma por família**,
  ainda que os treze codepoints coincidam hoje: lendo o `cmap` dos dois
  arquivos, a Fluent mapeia 2.030 codepoints da área de uso privado contra
  1.830 da MDL2, e 201 só existem nela — os treze coincidem porque a Fluent
  preservou os herdados, e é aí que a divergência vai morar no dia em que um
  ícone novo só existir numa delas. A armadilha é a de sempre nesta casa:
  **pedir uma família que a máquina não tem NÃO dá erro** — o Tk cai na fonte
  padrão e os codepoints saem como quadradinhos —, por isso `_familia_de_icones`
  é função PURA e o teste exercita os três desfechos; e a lista de famílias sai
  do `font families` do **Tcl**, não de `tkinter.font.families()`, porque o que
  derrubou a v1.0.71 foi o import do submódulo, não a função. O ● do pulso
  (U+25CF) volta à fonte de TEXTO de propósito: ele não existe na fonte de
  ícones, e pedi-lo a ela daria o quadradinho justamente no sinal que diz onde
  o trabalho está.
  **A busca da barra promete uma coisa, e cumpre essa** (PR #32). O campo dizia
  "Buscar lançamento, empresa ou conta…" e o Enter ali só devolvia o cursor ao
  primeiro campo da aba aberta — procurar lançamento pede um índice do ERP que
  ninguém tem, e um campo que promete três coisas e não faz nenhuma ensina a
  pessoa a não usar campo nenhum. Hoje a `BarraTopo.DICA` é "Ir para uma
  tela…  (Ctrl+K)", digitar filtra os nomes das doze telas por `util.filtrar`
  (sem acento, sem caixa, pedaço em qualquer posição), ↑/↓ andam pela lista e
  Enter pula para a realçada; texto sem par **não move o foco** e a lista diz
  que não achou, porque campo que não responde a nada parece travado. Duas
  decisões: a lista é um `Toplevel` **sem foco nenhum**, como o calendário do
  `CampoData`, para quem está digitando continuar digitando; e cada linha chama
  o `ItemMenu.acionar` — **um caminho só até a tela**, porque o `mostrar` do app
  faz mais do que trocar de quadro (abre o grupo fechado, chama o `ao_abrir`,
  põe o foco no primeiro campo) e uma segunda porta seria uma segunda chance de
  esquecer um desses passos. De graça: a lista sai do menu JÁ MONTADO
  (`definir_telas`), então vem filtrada pelo PAPEL de quem entrou, e a busca não
  leva ninguém a uma tela que o menu daquela pessoa não mostra.
  **Entrou em 02/09 (PR #30)**: "nenhuma aba escreve `#` seguido de seis
  dígitos" deixa de ser conferência a olho e vira teste — varredura por AST dos
  `.py` **rastreados pelo git**, fora do `widgets.py` e de `tests/`, atrás de
  constante de cor em qualquer posição e de cor com NOME em
  `fg`/`bg`/`fill`/`outline`. Quem decide o segundo caso é o VALOR e não o nome
  do argumento: o `fill` do `pack()` é direção, e são 211 ocorrências de
  `fill="x"` que uma checagem pelo nome acusaria à toa. Hoje ele não acha nada
  — é guarda para a próxima pessoa distraída, e vem com um segundo teste que
  roda a MESMA varredura sobre o `widgets.py` e exige que ela ache mais de 50
  cores, porque guarda que deixou de morder fica verde para sempre.
  **Entrou em 02/09 (PR #34)**: `widgets.explicar_erro(exc)` devolve o
  que houve, **de quem é** e o próximo passo, no lugar da exceção crua que dez
  diálogos mostravam — e é a segunda parte que decide tudo, porque "tente de
  novo", "conecte-se" e "avise quem cuida do cadastro" são conselhos opostos. A
  tradução já existia, presa numa função privada de uma tela só, e passa a ser
  uma. A família sai do NOME da classe, percorrendo a MRO, e **não** de
  `isinstance`: importar aqui `nuvem.rest`, `erp.sessao`, `conciliacao.errors` e
  o `playwright` arrastaria rede e navegador para dentro do módulo visual, e
  import novo custa exe novo (ver a v1.0.71 na regra de ouro).
  **Entrou em 02/09 (PR #35)**: as catorze tabelas passam a ordenar pelo
  cabeçalho. O caso que dá o motivo inteiro é a coluna de dinheiro, que
  ordenada como TEXTO põe "R$ 987,00" depois de "R$ 1.234,56" — e é justamente
  ela que se ordena, para achar o maior pagamento do dia. O tipo sai do
  CONTEÚDO da coluna e não de uma declaração por tela (catorze tabelas seriam
  catorze chances de a declaração divergir da célula), a zebra é **reaplicada**
  depois de mover as linhas (as tags `par`/`impar` viajam com o item, e sem
  reaplicar as listras saem embaralhadas), e célula sem valor não vira zero —
  "não tem valor" e "vale R$ 0,00" são coisas diferentes numa tabela de
  pagamento.
  **Entrou em 02/09 (PR #37): `widgets.px(n)` — "os `n` pixels de quem desenhou
  esta tela a 100%", ditos na escala de hoje.** As fontes já acompanhavam a
  escala do Windows desde o redesenho; as MEDIDAS de layout não, e era o
  desencontro entre as duas que quebrava a tela — a 150%, "ÚLTIMA EXECUÇÃO"
  saía "ÚLTIMA EXECU" numa coluna de 130 px fixos, a coluna SITUAÇÃO era
  empurrada para fora da tabela e o logotipo encostava no campo de busca dentro
  de uma faixa de 52 px que o texto já não cabia. Foram **333 medidas em 12
  arquivos**, 93 delas no próprio `widgets.py` — que são as que pagam pelo
  resto, porque a altura da barra, a coluna do menu, o filete do `ItemMenu` e a
  folga do `Cartao` valem para todas as telas. **A régua é a FONTE, não o
  DPI**, e a diferença importa: quem aumenta só o tamanho da fonte no Windows,
  sem mexer na escala de exibição, tem exatamente o mesmo problema — é a mesma
  decisão que fez as fontes nomeadas saírem do `TkDefaultFont`. Três ressalvas
  viraram teste: o **degrau de 5%** (nesta máquina o `tk scaling` a 100%
  devolve 1,3346 e não os 1,3333 da teoria, e sem o degrau `px(820)` daria 821
  — um pixel a mais em toda tela de quem não mudou escala nenhuma, e a promessa
  "a 100% nada muda" deixaria de ser verdade); **nunca menos que 1,0**, porque
  fonte menor não corta nada e apertar as margens só estragaria uma tela que
  estava boa; e **`px(0)` é 0**, senão todo `padx=(0, 8)` ganharia um pixel de
  folga onde o desenho pedia encostado. O que NÃO escala, de propósito:
  `width=` de `Entry`/`Combobox`/`Label` (conta CARACTERE) e `height=` de
  `Treeview`/`Text` (conta LINHA) — os dois já seguem a fonte sozinhos, e
  multiplicá-los daria campo com o dobro das letras. Duas escolhas de lugar
  encolheram muito o diff: a largura das colunas de Treeview escala dentro do
  `estilo_tabela`, num lugar só, **guardando a largura de origem no widget** —
  o Início e a Acessórias chamam a função DE NOVO ao remontar a lista, e sem a
  memória a segunda passada escalaria o que já estava escalado; e cada frame
  ganhou `px = widgets.px` logo abaixo do import. A promessa "a 100% nada muda"
  é provada por teste determinístico, que não depende de tela nenhuma.
- `inicio/inicio_frame.py` — aba Início, a primeira tela: os KPIs do dia
  (`CartaoKPI`), a situação de cada rotina (`ROTINAS`, onde o `ritmo` decide
  quando "não rodou hoje" vira pendência — para uma rotina diária é aviso; para
  uma mensal, no dia 3, não é) e a atividade recente. **Ela não abre navegador
  e não coleta nada.** O app abre em cima de UMA sessão do ERP, e uma tela de
  resumo que buscasse os pagamentos do dia na abertura consumiria essa sessão
  antes de a pessoa clicar em coisa alguma — a aba que ela abrisse em seguida
  teria de refazer o login. Então o Início LÊ o que as rotinas já contaram no
  `atividade.jsonl`, e relê a cada troca de aba pelo `ao_abrir()`. A
  consequência aparece na tela e é de propósito: número que ninguém apurou hoje
  sai como "—", com "rode a rotina para atualizar" embaixo — **zero seria pior
  que um traço**, porque zero é uma afirmação sobre o dia que o app não tem como
  fazer sem falar com o ERP. Uma coisa pendente: construí-la custa **~670 ms**,
  mais da metade do ~1,2 s que as doze abas somam na abertura, contra menos de
  100 ms de qualquer outra (medido no PR #29) — e o custo é trabalho feito na
  CONSTRUÇÃO, não import, então adiar import não resolve.
- `separar_renomear/separar_renomear.py` — separa páginas de PDF e renomeia.
  Dois parsers, escolhidos pelo **layout** (`campos()`), NUNCA pelo banco:
  `_campos_rotulado` quando o rótulo traz o valor na mesma linha
  ("Descrição CENTRO DE CUSTO QD 26A LT 10 OC 1234"), `_campos_impresso` quando
  rótulos e valores vêm em blocos separados (Sicoob Internet Banking; PDFs
  SEM camada de texto → **OCR** via Tesseract embutido,
  `_ocr_pagina`/`_configurar_ocr`). Detectar o banco não serve para escolher:
  o Inter escreve "Sobre a transação"/"Banco Inter" nos DOIS layouts — foi
  isso que fez metade dos comprovantes sair como "VALOR - Instituição Banco
  Inter", sem descrição nem data. `_lixo`/`_sem_rotulo` impedem que rótulo
  técnico (Instituição, CPF/CNPJ, Autenticação) vire nome ou descrição.
  Modelo de nome padrão "VALOR - DESCRIÇÃO - DATA" ou personalizado (tokens
  VALOR, DESCRIÇÃO, DATA, PAGADOR, RECEBEDOR). Boleto: usa o valor PAGO
  (último R$ não-zero). Regex de valor/data são case-insensitive por causa
  do comprovante de tributo ("VALOR TOTAL:", "DATA DE PAGAMENTO:").
  OCR em lote por arquivo (`_textos_das_paginas`): renderiza em SÉRIE
  (pypdfium2 não é thread-safe) e reconhece em PARALELO — o Tesseract roda em
  subprocesso e solta o GIL. Medido: 0,96s→0,29s por página no OCR puro, e
  1,7x no processar inteiro de um PDF de 107 páginas. `OMP_THREAD_LIMIT=1`
  para o pool não brigar com as threads internas do Tesseract. Ressalva: o
  lote é por ARQUIVO, então entrada com muitos PDFs de 1 página só não ganha.
  OCR: 300 dpi e, **só quando não sai descrição**, 2ª tentativa a 400 dpi
  — medido nos comprovantes reais, nenhuma das duas
  resoluções ganha sempre, e 400 dpi em tudo é ~2x mais lento. O OCR come os
  espaços do centro de custo ("TB 21 QD 51..." vira "TB21QD51..."):
  `RE_DESC_COLADO` reconhece a descrição mesmo colada e `_espacar_codigo`
  devolve os espaços, senão o matcher não enxerga QD/LT. Nome repetido não
  vira "(2)": `_nomes_finais` decide os nomes com o LOTE INTEIRO na mão e põe
  quem recebeu em TODOS do grupo (não só no segundo) — por isso `processar`
  tem 2 passadas: lê tudo (OCR, demorado) e só então grava. Sobra "(2)" só
  quando o recebedor também é o mesmo, aí não há o que distinguir.
  No fim, `processar` lista quem ficou sem descrição.
- `anexar/mc_api.py` — o favorecido É `paidTo` (confirmado contra a API de
  produção); `_CHAVES_FAVORECIDO` tentava 20 nomes e nenhum era esse, então o
  campo saía vazio. Além de `listar_pagos`, expõe para a aba Pagamentos do
  Dia: `listar_a_pagar` (dateField=PLANNED, type=ALL — o `paid` de cada item
  é quem separa), `anexos_de_titulos` (entityOrigin=**TRADE_PAYABLE**, o
  boleto/NF ficam no título, não no sub-pagamento) e `listar_overviews`.
  **`/payable-installments/<id>/overview` é indispensável**: é o único lugar
  com `purchaseOrder.number` (o NÚMERO da OC — a lista só tem o booleano
  `hasPurchaseOrder`) e com `comment`, o campo de observação do lançamento,
  que às vezes carrega a própria forma de pagar (já veio Pix copia-e-cola
  inteiro). O endpoint `/comments` responde 200 mas devolve `items: []` —
  não perca tempo lá. `page` começa em **0**: pedir page=1 traz a SEGUNDA
  página, vazia e sem erro.
- `anexar/mc_api.py` — leitura dos pagos e anexos pela MESMA API da tela de
  Pagamentos, com chamadas feitas DE DENTRO da página logada (page.evaluate
  + fetch) — chamadas via requests de fora recebem 403 do ERP. Captura
  headers de auth observando as requisições da página (token só em memória).
  `montar_pagos` guarda `valores` = {nominal, valor pago com juros/desconto},
  `favorecido` e `ocs`. O favorecido NÃO tem campo fixo conhecido na API:
  `_CHAVES_FAVORECIDO` tenta os nomes prováveis (string, dict ou lista) e, se
  nenhum servir, o diagnostico.log grava quais campos vieram — só os NOMES,
  sem valores — para acertar a lista sem chutar de novo.
  Também baixa anexos (fetch → base64) para a Conferência.
  **São DOIS back-ends e dois cabeçalhos**: `capturar_credenciais` ouve a tela
  de Pagamentos (títulos, recebimentos) e `capturar_credenciais_anexos` ouve a
  tela de UM lançamento (anexos, obras — `_base_erp`). Quem tem um lançamento
  na mão passa o id; quem não tem (a aba Contratos parte de recebimento e
  obra) chama `garantir_credenciais_anexos`, que procura a isca sozinho — um
  pagamento qualquer do último ano — e garante os dois de uma vez. Sem isso,
  a primeira chamada ao ERP morre em "Credenciais de anexos ainda não
  capturadas", que parece erro de login e não é.
- `anexar/matcher.py` — casamento PDF↔pagamento. Filtro de entrada: valor
  (qualquer um de `valores`). Critérios: OC/NF > centro de custo > data.
  NUNCA chuta: só casa por data se não há outro pagamento de valor igual;
  ambíguo vira DÚVIDA. `parse_pdf` reconhece valor/data em qualquer posição
  do nome (modelos personalizados) e ignora sufixo " (2)".
- `anexar/mc_client.py` — Playwright controla o Chrome instalado
  (channel="chrome", perfil persistente `.chrome_profile` ao lado do exe).
  **Login**: a tela do ERP é AngularJS. Preencher o input (mesmo com setter
  nativo + eventos) não garante propagação para o `ng-model`, e o ENTRAR fica
  habilitado assim mesmo (o `ng-disabled` aceita `$ctrl.getAutoFill()`) — o
  clique chamava `login()` com credencial VAZIA e falhava em silêncio. Por
  isso `_login_pelo_controller` escreve no scope e chama `ctrl.login()`;
  o preenchimento do DOM é só fallback. Erro de rede/DNS vira `SemRede`
  (3 tentativas em `_ir_para`), que a UI mostra como recado, sem traceback.
  `MCClient(log=...)`: no exe `--noconsole` não há stdout, então as mensagens
  do login precisam do log da janela para existirem.
  Anexa via UI (⋮ → Editar pagamento → arquivo → tag "Comprovante").
  Seletores do ERP estão nos blocos JS deste arquivo. Timeouts generosos
  (45–60 s) + `resetar()` antes de retentar (ERP fica lento em lote).
- `anexar/anexar_comprovantes.py` — tela Anexar: 2 passos (Carregar contas /
  Casar e anexar) — "Abrir o Mais Controle" saiu do fluxo e virou botão
  auxiliar, porque com a senha guardada o app entra sozinho.
  Pausar/Parar, cronômetros ⏱, janela de
  resolver DÚVIDAS (`_janela_duvidas`): por pagamento mostra favorecido,
  descrição inteira, centro de custo, nº doc + OC/NF, categoria e conta;
  os candidatos vêm
  numa tabela ordenada pelo score, com o que bateu em cada um (OC/NF,
  centro de custo, data) e botões de abrir o PDF e o lançamento. O mesmo
  detalhe vai para a aba DUVIDA do relatório (`_resumo_cands`).
  Botão Abrir relatório, modo "Por lista" (.csv/.xlsx; completa
  ".pdf" ausente). Relatório Excel: ANEXADOS/DUVIDA/SEM PAR.
- `anexar/conferencia.py` — auditoria pós-anexo: lista pagos SEM anexo no
  período e, opcionalmente, baixa cada PDF anexado e confere se o VALOR
  (e data) aparecem no texto (OCR se preciso) → aba DIVERGENTES.
  Compartilha sessão/thread da tela Anexar (`anx.garantir_sessao()`).
- `relatorios/extrato_mc.py` — extrato do fluxo de caixa por conta, em PDF.
  Roda sobre a página logada do Anexar (`anx.mc.page`), na thread do navegador.
  **O ERP está migrando para React/MUI, uma tela por vez** — o cabeçalho e
  `#/accounts` já são React; `#/cash-flow` ainda é Angular. Antes de mexer numa
  tela, confira em qual mundo ela está: contar `[ng-model],[ng-click],.ng-scope`
  contra `[class*="Mui"]` dentro do conteúdo resolve em um comando. Foi essa
  migração que quebrou a leitura antiga da lista de contas, que raspava
  `tr[ng-repeat]` de `#/accounts` e vencia a paginação escrevendo `pageSize` no
  scope dono da propriedade. Hoje a lista sai de `allAccounts`, no escopo do
  `ng-multiple-select[ng-model="selectedAccounts"]` do próprio fluxo de caixa:
  vem inteira, sem paginação, com id/nome/proprietário/situação — e é a MESMA
  lista que a pessoa vê ao escolher as contas, então não há divergência entre o
  que se marca e o que se processa. Armadilhas que seguem valendo: (1) não é
  preciso clicar conta por conta: o botão Extrato chama
  `stateGoNewTab('base.cashFlow')`, então vale ir direto a
  `#/cash-flow?accountId=`; (2) o período mora em `fromDate`/
  `toDate` (moment) do controller, não nos inputs; (3) o "carregar mais" tem
  fim conhecido em `pageInfo.hasNextPage` — o botão some do DOM, o campo não, e
  ele fica DEPOIS do "Saldo final": o extrato exibe totais como se estivesse
  completo enquanto faltam lançamentos, então PDF gerado com `hasNextPage`
  ainda `true` é recusado por `conferir_antes_de_salvar`, que também confere se
  `summary.accounts` é a conta esperada — extrato certo na pasta errada não se
  denuncia sozinho; (4) "Imprimir" só chama `window.print()`: neutralizamos e geramos o PDF por
  `Page.printToPDF` do CDP (o `page.pdf()` do Playwright recusa navegador com
  janela). O CSS de impressão do ERP não esconde o fluxo de caixa atrás do
  modal — ele vazava para o PDF —, então o modal vira único filho do `body`
  (`visibility:hidden` + `position:absolute` não serve: zera a paginação e sai
  PDF em branco). Isso deixa o SPA quebrado: cada conta recarrega a página, e
  `restaurar_pagina()` devolve o navegador às outras abas no fim.
- `pagamentos_dia/relatorio.py` — regra de negócio + Excel do relatório dos
  pagamentos do dia (uma aba por conta). Sem navegador e sem tkinter, então
  roda inteiro em teste. Cinco coisas aprendidas lendo a API de produção:
  (1) **boleto ganha de Pix** sempre que houver boleto anexado — o
  `tradePayablePaymentMethod` diz "Pix" só porque o fornecedor tem chave no
  cadastro, e pagar por pix um título que veio com boleto duplica o pagamento;
  (2) `remainingValue` vem **0.0** em título quitado (o valor está em
  `sumOfPaidValues`) — usar só ele zerava o total; (3) `extension` vem COM
  ponto (".pdf"); (4) contas de água/luz se identificam pela **UC e pelo
  endereço**, não pelo "número da NF" (que ali é o número da fatura), e a UC
  aparece no NOME do anexo — dá para conferir sem baixar; (5) o cruzamento
  distingue **DIVERGE** (o documento contradiz o lançamento → ATENÇÃO) de
  **?** (não deu para verificar → não alarma). Alarme falso ensina a ignorar
  alarme. A chave de acesso de 44 dígitos no nome do anexo entrega número da
  NF e CNPJ do emitente de graça.
  `montar_registros` devolve um `Resultado(contas, omitidos)`: **omitir não é
  apagar**. Enquanto "não entrou" era um `continue` mudo, descobrir que uma
  regra errou dependia de sentir falta de um pagamento — o que só acontece
  depois do vencimento. Os omitidos viram a aba "NÃO ENTRARAM", com o motivo
  de cada um, e não somam no TOTAL de conta nenhuma. Três consequências que
  não são óbvias: (a) linha **JÁ PAGA escapa das regras de omissão** — ali
  "sem forma de pagar" é o normal, não defeito; (b) "sem forma de pagar" só
  vale quando NÃO HÁ documento anexado: boleto que virou foto e o OCR não
  fechou continua na planilha, porque alguém abre o anexo e digita; (c) sem
  boleto anexado a regra "boleto ganha de Pix" não tem premissa — não existe
  boleto para ganhar —, então havendo NF ou OC a linha vira Pix com a chave
  do cadastro, e o aviso "pagar o boleto" só é montado DEPOIS de resolver a
  forma de pagar, senão mandaria pagar um documento que não existe.
- `pagamentos_dia/regras_pagamento.py` — quem NÃO entra na planilha, e por quê.
  Os CRITÉRIOS moram aqui; os NOMES (fornecedor que só recebe por reembolso,
  pessoa cujo pagamento é confirmado antes) ficam em `regras_fornecedor.json` e
  `confirmar_antes.json`, ao lado do exe e fora do repo — como o
  `pix_reembolso.json`. Cadastro ausente ou ilegível não vira erro: o app roda
  igual, só sem as regras. O sufixo `_pagamento` no nome do módulo é
  obrigatório: `aportes/regras.py` já existe, nome de módulo é global no
  sys.path e `pagamentos_dia` entra ANTES de `aportes` — um `regras.py` aqui
  sequestraria o import da aba Aportes (a mesma armadilha do `extratos_sicoob`).
  **O boleto manda no valor.** "R$ 1,00 é marcador de recorrência" vale só
  enquanto nada prova o contrário: havendo código de barras anexado (que é
  conferido por DV e carrega o valor em centavos), quem erra é o LANÇAMENTO, e
  a linha entra com "ATENÇÃO — valor do boleto diverge" em vez de sumir. Sem
  essa ressalva a regra apagava, no arquivo de 08 a 10/08/2026, exatamente uma
  linha — uma conta da Equatorial lançada como R$ 1,00 cujo boleto dizia
  R$ 56,24 — e ninguém sentiria falta antes do vencimento.
  **O tipo da chave Pix não se chuta** (`tipo_de_chave_pix`). O ERP não tem o
  campo: a chave chega dentro de texto livre (`paidToBankAccount`, e o mesmo
  texto no `bankAccount` do cadastro). Medido nos 116 lançamentos com o campo
  preenchido no período, 75 DECLARAM o tipo por escrito ("PIX CNPJ" 65 vezes,
  "PIX CELULAR" 7, "PIX CPF" 3) — é dali que ele sai, e só depois do formato
  inequívoco (o "@", o UUID, a pontuação de CNPJ ou de CPF). **Onze dígitos
  crus devolvem ""**: CPF e celular têm os dois onze, e a planilha prefere
  perguntar a escolher para quem o dinheiro vai. É também o dado que falta
  para montar o segmento B de uma remessa CNAB.
- `pagamentos_dia/ocr_boleto.py` — linha digitável de boleto que veio como
  IMAGEM, e a desconfiança que ela exige. **Texto de OCR nunca passa pelo
  extrator solto**: um `8` lido como `B` paga a conta de outra pessoa sem erro
  na tela e sem volta, então a linha só é aceita depois de (1) fechar os
  dígitos verificadores e (2) codificar o MESMO valor do lançamento. Reprovou,
  volta a ser "preencher manual" — recusar leitura duvidosa é a única falha
  aceitável aqui. Módulo 11 da ficha de arrecadação: só resto 0 e 1 zeram o
  DV; **resto 10 dá DV 1**, e não 0 (conferido contra guias reais de IPTU/ISS
  de Goiânia, onde dois de oito blocos caem nesse resto — zerar os dois casos,
  como o DV geral do boleto bancário faz, reprovava guia legítima).
- `pagamentos_dia/remessa_dia.py` — a regra do passo 3, **sem tela**: quem pode
  sair na remessa e como o arquivo é montado. **Impedimento ≠ desmarcado.**
  Desmarcar é escolha de quem confere; impedido é o que não *pode* sair, e nem
  aparece marcável: observação que manda pagar outra pessoa, pagamento parcial
  como boleto, linha digitável que não fecha nos DVs, e Pix sem o CPF/CNPJ do
  favorecido. **O Pix vale para qualquer tipo de chave**, e quem paga isso é o
  **cadastro de Contatos** (`mc_api.listar_participantes`): os campos
  07.3B/08.3B do segmento B exigem o documento de quem recebe, o lançamento só
  traz o nome (`paidTo`) e nem o id do participante. A ligação é pelo NOME —
  medido em 13/08/2026 sobre 300 lançamentos e 455 participantes: 296 casaram
  e **todos tinham documento**; as 4 sobras eram `paidTo` = "-".
  Duas travas nasceram daí: **nome ambíguo** (dois participantes, documentos
  diferentes) sai do mapa, porque escolher um é pagar com o documento de
  outro; e **onze dígitos crus** só viram chave CPF quando batem com o
  documento DO CADASTRO — se o desempate aceitasse o documento já resolvido,
  ele viria da própria chave e confirmaria a si mesmo.
  O mapa conta-do-ERP → empresa vem do `contas_mc.json` que já existia; um mapa
  a mais seria uma divergência a mais esperando acontecer.
  **`ocr_boleto.codigo_de_barras`** converte a linha digitável (47/48) no código
  de barras (44) que o segmento J exige — e devolve "" para linha cujos DVs não
  fecham, porque a linha pode ter vindo de OCR.
  **`resolver_pagador` lê o convênio da CONTA, e recusa sem herdar.** A
  checagem vem DEPOIS de a conta estar escolhida — antes dela não há conta
  para perguntar —, e não existe `or empresa.convenio`: herdar faria uma
  subconta ainda não aderida sair com o número da principal, que é o campo
  07.0 do header e o nome da sequência do NSA. Conta sem convênio para
  sozinha, com `MOTIVO_SEM_CONVENIO`, e a irmã que já aderiu segue.
  **`_e_sicoob(banco)` aceita `SICOOB`, `756` e `0756`** — o precedente é o
  `nuvem/cadastro._e_inter`, que aceita nome ou código "porque o cadastro tem
  os dois jeitos". Enquanto a comparação era `!= "SICOOB"`, a conta cadastrada
  por código levava `MOTIVO_FORA_SICOOB`: "esta conta é de outro banco" para
  uma conta que É do Sicoob, que é a pior espécie de recado — manda conferir a
  coisa errada. Ela passa a gerar, e o dado torto continua sendo AVISO na
  prontidão, porque é esse campo cru que nomeia o extrato do Relatório Mensal
  (`202607 756 MAIS CONTROLE.pdf`).
  **A prontidão do cadastro (`Conferencia`, `conferir_conta`, `prontidao`)
  mora aqui, e não em `sicoob_contas.impedimentos()`.** Duas razões, e as duas
  são de escopo: aquela função barra o LOTE da aba Extratos — parar 17 contas
  em 12 empresas porque uma está sem convênio é exatamente o dia que este
  código veio devolver —, e ela não conhece o `contas_mc.json`, que é onde
  começa a pergunta ("de que empresa é esta conta do ERP?"). O que ela julga é
  o cadastro do Sicoob sozinho; o que a remessa precisa é dos dois mapas de uma
  vez.
  **`conferir_conta` junta TODOS os problemas; `resolver_pagador` para no
  primeiro** — e a diferença é o motivo de as duas existirem. Quem GERA precisa
  de um veredito ("sai ou não sai"); quem CORRIGE precisa da lista, porque
  descobrir a agência hoje, o convênio amanhã e o CNPJ depois de amanhã é o
  mesmo dia parado três vezes. São dez conferências, na ordem em que o ARQUIVO
  precisaria: banco vazio (falta) ou escrito por código (aviso), a empresa no
  `contas_sicoob.json`, a conta na pasta (com o `sufixo` desempatando), agência
  de 4–5 dígitos, conta COM dígito verificador, **o CNPJ do pagador conferido
  por DV** (`regras_pagamento.documento_valido`, que reexporta o
  `cnab240.dominios` — ninguém conferia o documento de quem PAGA antes do
  validador, e foi um CPF de preenchimento do favorecido que devolveu a remessa
  de 20/08/2026), razão social vazia (aviso: o header cai para o nome de pasta,
  cortado nas 30 posições do campo 13.0), o convênio, e a duplicidade entre
  contas — mesmo convênio, ou mesma agência+conta, é falta nas DUAS, porque não
  há como saber qual delas está errada. Conta de OUTRO banco não entra na
  lista: não é pendência, é conta que não faz remessa CNAB, e uma lista que
  carrega dez contas do Inter para sempre é uma lista que ninguém lê.
  **As duas concordam POR TESTE, e não por disciplina.** `resolver_pagador`
  não tem régua própria: depois das duas perguntas que decidem se a conta
  ENTRA na prontidão (banco vazio, banco de outro banco) ele devolve a PRIMEIRA
  falta da `Conferencia` daquela conta. Duas listas de checagens se separam sem
  ninguém perceber — a tabela diria "pronta" e o botão recusaria, ou, pior, a
  tabela diria "falta" e o arquivo sairia assim mesmo —, e quem impede a volta
  é `test_a_prontidao_e_o_resolver_pagador_concordam`, que roda um cadastro com
  uma conta de cada defeito e exige `c.pronta ⟺ resolver_pagador(...)` devolver
  pagador.
  **`contas_sem_remessa(preparado, gerados)`** é a aritmética do cartão
  "Contas sem remessa" do Início, tirada de dentro do frame para poder ser
  testada — ver o achado K em `pagamentos_frame.py`.
  **`diagnostico_documentos`** existe para fechar a lacuna do Pix: varre o
  `overview` que o "1. Buscar" já trouxe e diz ONDE há CPF/CNPJ válido, sem
  imprimir documento nenhum — só caminho, contagem e **valores distintos**. É o
  "distintos" que separa o fornecedor (um por lançamento) da própria empresa (o
  mesmo em todos). Os DVs são conferidos: sem eles todo celular de onze dígitos
  viraria "CPF encontrado", a mesma armadilha do `tipo_de_chave_pix`. Um campo
  que aparece em 1% dos lançamentos é acaso (dois DVs fechando por sorte), não
  achado — daí a contagem estar no relatório.
  **`nome_do_arquivo` leva agência-conta desde 04/09/2026** (`REM_<EMPRESA>_
  <AG>-<CONTA>_<NSA>.REM`): o convênio do Sicoob é POR CONTA CORRENTE, o NSA
  recomeça em cada uma, e sem a agência-conta no nome uma holding com várias
  subcontas gerava o mesmo nome em pastas diferentes — a pasta separa, mas o
  arrasto para o SicoobNet mostra só o nome.
- `pagamentos_dia/pagamentos_frame.py` — aba Pagamentos do Dia, em 3 passos
  (Buscar / Gerar planilha / Gerar remessa). **O passo 3 não passa pelo
  `anx.submeter`**: não há navegador nem ERP nele — a remessa sai do
  `self.resultado` que o passo 2 deixou em memória, e escrever texto local não
  justifica ocupar a sessão que só aceita um por vez. **Reserva o NSA, valida,
  grava e registra — nessa ordem.** Arquivo reprovado não é escrito, mas o NSA
  já foi reservado e fica **queimado**: o número entra no CONTEÚDO do arquivo
  (o G018 do header, que é o que o validador confere), então não há como
  validar antes sem validar um arquivo sem número, e espiar aqui para reservar
  depois abriria a janela em que a outra máquina pega o mesmo. É o lado certo
  de errar — pular número é inofensivo, repetir pode ser pagamento em dobro.
  O número queimado **não deixa rastro**: `alocar_nsa` só empurra o
  `remessa_contador` da nuvem, o `remessas.json` só aprende um NSA quando
  `registrar` é chamado, e `remessa_ajuste`/`ajustes` guardam só a correção
  manual do contador (`ajustar_nsa`, que exige motivo por escrito). O furo
  aparece como número faltando na sequência, e ninguém o explica por escrito.
  Compartilha navegador e thread do Anexar. O passo separado
  existe porque quem confere quer VER a lista de contas antes de gerar, e cada
  rodada custa uma sessão do ERP (que só aceita uma por usuário). Contas
  "APENAS LANÇAMENTO/AJUSTE" aparecem desmarcadas, não escondidas. As chaves
  Pix dos avisos "PAGAR PARA" ficam em `pix_reembolso.json` ao lado do exe —
  é CPF de gente, não entra no repositório. A janela de confirmação dos
  pagamentos aos sócios abre em `gerar()`, na thread da INTERFACE e **antes**
  de `submeter()`: quem cancela ali não pode ter consumido a sessão do ERP.
  Anexo que é foto só é baixado quando é aviso "PAGAR PARA" — baixar toda
  imagem de todo título seria pagar OCR por nada.
  **O cartão "Contas prontas para remessa" é montado quando a aba é MOSTRADA,
  não na construção.** O esqueleto (o `Treeview` e o rodapé) nasce no `_build`,
  porque custa microssegundos; quem custa é LER os dois JSON, e isso acontece
  no `ao_abrir()` — o mesmo gancho que o Início usa, chamado por
  `comprovantes_app.mostrar` a cada troca de aba. As doze abas somam ~1,2 s na
  abertura do app (a Início sozinha ~670 ms), e pagar disco adiantado por uma
  tabela que ninguém está olhando é o oposto do que se quer. De graça: quem
  corrigiu o cadastro no painel não precisa reabrir a aba de propósito — sair
  dela e voltar já relê —, e há um "Conferir de novo" no rodapé. **Custo real:
  dois arquivos locais.** Sem rede, sem ERP e sem navegador, então roda na
  thread da interface.
  Cinco colunas — `CONTA (ERP) · EMPRESA · AG-CONTA · CONVÊNIO · SITUAÇÃO` —,
  e a situação é `✓ pronta`, `⚠ falta: agência, convênio` ou `· aviso: …`: o
  símbolo vem de `widgets.MARCAS_ESTADO` e a cor da tag do `widgets`, nenhuma
  escrita aqui. **Falta é `atencao` e não `erro`** porque nada falhou — o
  cadastro está incompleto e ninguém tentou gerar nada ainda. O rodapé diz
  "corrija no painel do Supabase e reabra o app", e o "reabra" não é zelo: o
  cache só é regravado na abertura (`nuvem.cadastro.sincronizar`).
  A MESMA lista aparece no lugar dos dois recados genéricos do `gerar_remessa`:
  quando os `carregar()` levantam (aí sem tabela, porque não há cadastro para
  conferir — o que o recado ganhou foi o `contas_mc.carregar` dizendo QUAL
  linha está torta) e quando `pagadores` sai vazio, onde "Nenhuma conta marcada
  gera remessa" passa a listar `conta: faltas` — todas as faltas, e não só o
  primeiro motivo, porque quem lê ali vai consertar.
  **Achado K: o dia em que NENHUM arquivo sai também é um dia em que alguém
  rodou.** `_gravar_remessas` só chamava `auditoria.registrar` no caminho em
  que houve arquivo, e o cartão "Contas sem remessa" do Início mostrava "—" —
  exatamente o que ele mostra quando ninguém rodou nada. O pior dia do mês
  ficava indistinguível de um dia comum. Hoje registra nos dois desfechos, com
  `resultado="atencao"` quando nada saiu, e a aritmética é a mesma função pura
  nos dois (`remessa_dia.contas_sem_remessa`): escrita duas vezes, seria o
  mesmo cartão dizendo duas coisas.
- `cnab240/` — gerador, validador e leitor de retorno do arquivo CNAB 240 do
  Sicoob (Guia v3.3), **stdlib pura** e sem tela nenhuma: é biblioteca, não aba.
  Quem a usa é o passo 3 da aba Pagamentos do Dia (`pagamentos_dia/remessa_dia.py`).
  **O único pacote do app com arquivo de DADOS**: os layouts vivem em
  `cnab240/spec/*.json`, campo a campo com o id do manual, para auditar contra
  o PDF sem abrir código — daí a linha extra no `build.yml` e o
  `tests/test_cnab240_pacote.py` que a vigia.
  **`historico.py` é a parte que o layout não resolve**: o NSA (nº sequencial
  do arquivo) tem de ser CRESCENTE por convênio — **e o convênio é POR CONTA
  (04/09/2026)**, não por empresa: o Sicoob dá um por conta corrente, e uma
  holding do cadastro tem nove, a principal e oito subcontas. Uma sequência de
  NSA por conta corrente, portanto — quem o controla é quem gera,
  o banco não guarda isso. Ele mora em `remessas.json` ao lado do exe, longe
  do cadastro de propósito: `contas_sicoob.json` é restaurado de backup, e um
  contador que volta no tempo é a única falha inaceitável aqui. Repetir NSA
  pode significar pagamento em dobro; pular número é inofensivo. O mesmo
  arquivo guarda o de-para "seu número → id do lançamento", que é o que o
  retorno usa para achar o caminho de volta.
  **Validado contra o banco em 13/08/2026** (`Válido`): header,
  boleto J+J-52, Pix por chave A+B e dois lotes no mesmo arquivo. Fora dali —
  TED, Pix QR Code, tributos e folha — a biblioteca gera, mas ninguém provou.
  Um achado dessa validação: o guia OMITE a forma de iniciação `03` (CPF/CNPJ)
  na descrição da Informação 12 do segmento B, e o banco recusa o campo em
  branco. Manual incompleto; a correção está comentada em `remessa.py`.
  **Existe UMA cópia deste pacote, e é esta.** Até 02/09/2026 havia uma
  segunda, no repositório das automações avulsas (`fontes/cnab240`), com CLI e
  testes próprios. Ela parou em 14/08 e nunca soube que `dv_cpf`, `dv_cnpj` e
  `documento_valido` passaram a existir em `dominios.py` em 20/08 — depois de
  o Sicoob devolver a remessa 000002 por um CPF de preenchimento vindo do
  cadastro. Os 84 testes dela passavam verdes justamente por não saberem que a
  validação existia, e o exemplo dela, rodado contra este código, produz 16
  problemas de dígito verificador. Quem a importava eram os quatro scripts de
  validação com o banco, por caminho absoluto escrito à mão; eles agora moram
  em `cnab240/ferramentas/`, importam o pacote daqui e **conferem em tempo de
  execução** que foi daqui que ele veio. A pasta fica fora do `codigo.zip` de
  propósito (o app nunca a importa), pelo `_PASTAS_SO_DO_REPO` do
  `test_empacotamento.py` — o mesmo tratamento do `nuvem/migrar.py`. Quatro
  testes em `test_cnab240.py` impedem a volta: um `dominios.py` só no
  repositório, as ferramentas importando `cnab240` e sem caminho externo no
  `sys.path` (por AST), e as três funções de DV existindo **e recusando**. A
  regra geral: uma biblioteca que move dinheiro não tem cópia de trabalho — a
  cópia envelhece em silêncio, e o silêncio dela é uma aprovação falsa.
- `relatorios/relatorio_frame.py` — aba Relatório Mensal: mês/ano (ou intervalo
  de datas), lista de contas com marcação, ⏹ Parar e progresso. Um PDF por
  conta, arquivado na árvore do fechamento junto do extrato do banco:
  `<raiz>/2026/JULHO/JULHO 2026 - BURITIS/SICOOB/202607 SICOOB MAIS CONTROLE.pdf`.
  O destino não é mais escolhido à mão — cada conta tem o seu, em
  `relatorios/contas_mc.py`.
- `relatorios/contas_mc.py` — mapa conta do ERP → pasta de destino, lido de
  `contas_mc.json` ao lado do exe, **fora do repositório** (nome de empresa e
  número de conta), como o `contas_sicoob.json`. A LISTA de contas não sai
  dali: é lida do ERP a cada execução, para que conta nova apareça sozinha; o
  mapa só responde "onde salvo esta?" e admite não saber — conta sem destino
  nasce desmarcada e trava o lote **antes** do primeiro download, porque
  decidir destino com o lote pela metade vira improviso. Quatro contas da mesma
  empresa dividem uma pasta (Moura Dantas), daí o campo `sufixo` com o número
  da conta no fim do nome.
  **O `sufixo` é o MESMO campo dos dois lados** — `contas_mc.Destino` e
  `sicoob_contas.Conta` —, e por um bom tempo só desceu para um: o PDF do ERP
  saía desempatado e o OFX do banco não. As duas contas gravavam
  `202607 SICOOB.ofx` no mesmo lugar e a segunda passava por cima da primeira
  **sem nada denunciar**: a pasta é escolhida pela conta, cada OFX é conferido
  contra a SUA conta (a trava do ACCTID aprova os dois), o `shutil.move`
  sobrescreve calado e o relatório fecha com "13 de 13 contas completas".
  Por isso `sicoob_contas.impedimentos()` BARRA o lote, em vez de avisar
  depois — aqui o estrago já aconteceu quando alguém percebe, e o arquivo
  perdido não volta. No banco, quem sustenta a regra é
  `unique (empresa_id, pasta, sufixo)`, e `nuvem/migrar.py` recusa migrar se
  os dois arquivos trouxerem sufixos diferentes para a mesma conta.
  `pasta` aceita subnível (`CAIXA/APLICAÇÃO`). A
  comparação de nomes ignora acento, caixa e espaço duplo: o nome vem do
  cadastro do ERP, digitado por gente. `caminhos_longos()` existe porque os
  caminhos aqui são longos (empresa + subconta com descrição + o `.zip` do
  fechamento por cima) e estourar os 260 do Windows aparece como falha de
  escrita no meio do lote, com causa nada óbvia.
  **`carregar()` ACEITA `banco` vazio; quem usa o banco é quem barra a conta.**
  Obrigatórios são só `erp`, `empresa` e `pasta` — sem eles a linha não
  identifica nada. Em 04/09/2026 UMA conta sem `banco` levantava `MapaInvalido`
  e, com ele, a aba Pagamentos do Dia parava para TODAS as empresas e o
  Relatório Mensal inteiro: um dado ruim custava o dia de todo mundo. Agora
  cada consumidor decide — `contas_mc.impedimentos()` faz a conta nascer
  desmarcada e travar o lote do Relatório Mensal **antes** do primeiro download
  (o PDF sairia `202607  MAIS CONTROLE.pdf`, sem dizer de que banco é), e a
  remessa recusa só aquela conta, com `MOTIVO_SEM_BANCO` em vez do enganoso
  "esta conta é de outro banco". Como em `caminhos_longos()`, `impedimentos()`
  só olha as contas marcadas: barrar por causa de conta que ninguém marcou
  seria repetir o erro em escala menor.
  **A linha ruim é identificada pelo que a PESSOA reconhece, não pelo número
  de ordem.** "A conta nº 2 está sem: pasta" mandava contar linhas num JSON —
  e contar não resolve, porque desde 13/08/2026 o arquivo é CACHE do painel: a
  linha nº 2 daqui não é a 2ª linha de nada que se possa editar. Hoje o recado
  cita `empresa`, `pasta` e `erp` (os que estiverem preenchidos — sempre sobra
  algum, porque a linha só chega ali faltando um ou dois dos três) e diz onde
  se conserta: "o cadastro é editado no painel do Supabase; depois feche e
  abra o app".
- `extratos_sicoob/` — aba Extratos Sicoob: cria a árvore do fechamento
  mensal e baixa OFX + PDF de cada conta do SicoobNet Empresarial.
  **Único módulo com navegador PRÓPRIO** (executor de 1 worker e perfil
  `.chrome_profile_sicoob`): é outro site e outro login, então pendurar na
  thread do Anexar só acoplaria. Os módulos têm prefixo `sicoob_` porque nome
  de módulo é global no sys.path — um `config.py` aqui sequestraria o
  `import config` do Anexar. **O login é manual, por decisão de projeto**: a
  tela do Sicoob tem reCAPTCHA, e nada aqui tenta contorná-lo; o robô espera
  a lista de contas aparecer e assume dali. O mapa conta→pasta vive em
  `contas_sicoob.json` FORA do repo (número de conta e razão social), como o
  `pix_reembolso.json`. Armadilhas resolvidas: (1) **o botão "PDF" é
  inutilizável** — chama `window.print()` e abre o preview do Chrome, que é
  MODAL, trava o navegador e não fecha nem por `Target.closeTarget`;
  diferente do ERP, trocar `window.print` NÃO adianta (o site guarda a
  referência antes), e imprimir a SPA sai com a tela do IB e o painel
  sobreposto. O PDF vem do formato **HTML**, que é download comum, aberto numa
  aba e convertido por `Page.printToPDF`; (2) o formato de
  exportação só marca clicando no `span.checkmark` do `ib-sicoob-input-radio`
  — no texto ou no card não dá erro e não marca nada, e a falha só apareceria
  no passo seguinte, por isso conferimos o botão antes de clicar; (3) o painel
  é um drawer com `div.overlay.visivel` que intercepta TODO clique, inclusive
  o "Trocar conta" — fechá-lo é obrigatório entre contas, e clicar no próprio
  overlay resolve; (4) no datepicker os dias do mês são `<a>` e os vizinhos em
  cinza são `<span>` em `td.ui-datepicker-other-month`, então mirar
  `td:not(.ui-datepicker-other-month) > a` acerta elemento e mês de uma vez;
  há `select` de mês e ano (mês 0-indexed), dispensando as setas. Antes de
  arquivar, o OFX é conferido contra `ACCTID` e período — o pior erro possível
  é o extrato de uma empresa cair na pasta de outra, e nada no disco denuncia.
- `acessorias/` — aba Acessórias: envia o fechamento ao escritório contábil
  pelo portal (uma solicitação por empresa, com o .zip anexado). **Terceiro
  navegador próprio** (perfil `.chrome_profile_acessorias`), pelo mesmo motivo
  do Sicoob: outro site, outro login, e o Playwright síncrono não divide
  thread. O login também é manual, mas aqui não há captcha — o perfil
  persistente + "Manter conectado" fazem a sessão durar de um mês para o outro.
  **A decisão que sustenta o resto: a mensagem é derivada do anexo.** A lista
  de contratos do comentário sai de DENTRO do zip (as entradas
  `.../CONTRATOS/`, gravadas pela aba Contratos), e não do ERP nem da aba
  Contratos em memória: assim ela não custa sessão do ERP — que só aceita uma
  por usuário — e não pode contradizer o que foi enviado. `pacote.py` é puro e
  recebe `nome_do_mes`/`nome_pasta_empresa` por parâmetro, como
  `contratos/destino.py`, e é ele quem casa o zip com a empresa usando a MESMA
  função que gerou aquele nome no `sicoob_zipar`. O portal é HTML puro (sem
  Angular e sem React): toda tela é endereçável por URL
  (`/<escritorio>/<id>/SOL/0` é o formulário em branco), então navegar é
  `goto`. Três armadilhas do formulário, medidas na tela e resolvidas em
  `portal.py`: (1) **`#SolAss` (o assunto) fica FORA do `<form>`** e é
  recolhido por JS no envio — um multipart montado à mão chegaria ao escritório
  sem título e sem erro, o que enterra a ideia de postar direto em
  `/sysvipsolAjax`; (2) **os `value` dos dois selects não seguem a ordem da
  tela** (DPTO_FINANCEIRO é o último item e vale 4; a prioridade é invertida,
  Baixa=3 e Muito Alta=0), então toda escolha é por RÓTULO — por índice, o
  fechamento vai para o departamento errado sem nada denunciar; (3)
  `SolDptoDcvID` é um segundo select, hoje mudo, e ganhando opções o módulo
  PARA em vez de adivinhar sub-departamento. Duplicidade é conferida no
  PORTAL, não em arquivo local (ao contrário dos Aportes): a lista de
  solicitações responde "já enviei esta?", e perguntar não envelhece — mas
  exige abrir também a aba Encerradas, que só carrega ao ser clicada. E nada
  de "enviado" sem prova: depois do Salvar/Enviar, `conferir_envio` relê a
  lista, abre a solicitação e confirma o anexo pelo nome. `vip_id`, `vip_nome`
  (por empresa) e `vip_url` (o endereço do escritório) moram no
  `contas_sicoob.json`, FORA do repo — o URL carrega o nome de um fornecedor
  real, e um mapa a mais seria uma divergência a mais.
- `anexar/config.py` — URLs, tag, listas IGNORAR_TARIFAS/IGNORAR_APORTES;
  usa a pasta do exe quando congelado (sys.frozen). Tem também `diag()`, o
  registro em `diagnostico.log` usado por quem precisa degradar sem quebrar
  (captura de credenciais, login salvo, download de anexo, OCR da
  conferência) — engole o erro, mas deixa o motivo gravado. Desde o PR #8 ele
  **delega para `util.log()`** em vez de abrir o arquivo à mão: mesma
  assinatura, mesmos chamadores, e o `ARQUIVO_DIAG` passou a sair de
  `util.pasta_base()`. O `ARQUIVO_LOG` (`log_anexos.csv`) ainda não — é o
  último caminho aqui calculado pela pasta do módulo.
- `ferramentas/` — as duas ferramentas locais, **fora do `codigo.zip`** por
  `_PASTAS_SO_DO_REPO` (`tests/test_empacotamento.py`), o mesmo tratamento do
  `cnab240/ferramentas/` e do `nuvem/migrar.py`: o app nunca as importa.
  **`galeria.py`** monta as 12 telas num esqueleto FIEL — a mesma
  `widgets.BarraTopo`, o mesmo `widgets.painel_menu` e as mesmas classes de
  aba, construídas direto dentro de um `Tk()`, sem login, sem cadastro e sem
  rede — e fotografa cada uma nos dois temas, com `--escala` para simular a
  escala de exibição do Windows. Não é teste: não compara nada e não falha
  sozinho; a comparação é o olho de quem mexeu. Baseline de pixel no CI foi
  considerada e recusada — o runner é headless e não renderiza Tk de forma
  confiável, e uma baseline envelhece a cada ajuste de 1 px em qualquer cartão.
  Duas armadilhas já morderam: ela fotografa a **TELA**, então precisa de
  `-topmost` antes de cada captura (é pedido de empilhamento, que o Windows
  concede a processo sem interação — ao contrário de `SetForegroundWindow`,
  que ele recusa, e a primeira rodada fotografou a janela errada); e **monitor
  que apaga no meio da rodada não dá erro** — o grab devolve o retângulo preto,
  o `save()` grava um PNG de 3 KB e o console anuncia sucesso, que foi como a
  pasta "depois" inteira do PR #15 saiu preta e só se descobriu ao abrir os
  arquivos. Hoje a imagem é medida antes de ir ao disco (`getextrema()`) e uma
  cor só de canto a canto vira `CapturaInutil`: nada é gravado, a linha sai
  como erro e a rodada termina em código 1. `_tela_acordada()` segura o monitor
  pelo tempo da rodada, e janela minimizada é recusada antes do grab (o Windows
  a estaciona fora da tela).
  **`sonda.py`** pergunta às 07:00, por tarefa agendada do Windows, se os três
  sistemas de fora ainda respondem — o ERP, o Inter e o Sicoob, nenhum com
  contrato de interface conosco, e os três já tendo quebrado no meio de um
  pagamento, que é o pior momento possível para descobrir. Ela **não corrige e
  não decide nada**: uma linha por sistema no `sonda.log` e, falhando algo, um
  `sonda.ALERTA.txt` com o resumo — que é **apagado** quando tudo volta a
  passar, porque alarme que fica para trás depois de resolvido é a forma mais
  rápida de ensinar alguém a ignorar alarme. **Nenhum navegador é aberto**, e
  isso não é economia: o ERP aceita uma sessão de navegador por usuário, e um
  Chrome às 07:00 derrubaria o de quem estivesse trabalhando — o login dela é
  por API, HTTP puro, o mesmo que o app já faz a cada abertura. E ela prova
  coisas diferentes sobre cada portal, porque eles respondem coisas diferentes:
  o **Sicoob não responde a cliente HTTP que não seja navegador** (medido em
  02/09/2026 — o TLS fecha em ~180 ms e a conexão trava na LEITURA, com os dois
  métodos e o jogo completo de cabeçalhos), então ali a sonda cai no aperto de
  mão TLS, que prova que o nome resolve, que a porta atende e que o certificado
  vale, e a linha do log diz exatamente isso. Dizer menos e dizer verdade, em
  vez de alarmar todo dia sobre um sistema que está de pé.
- `docs/` — o que não cabe neste arquivo, um documento por assunto.
  **`ERP-CLIENTES.md`**: o inventário de quem fala com o ERP, uma linha por
  consumidor com transporte, host, token, cabeçalhos, paginação e o que já
  quebrou ali, cada afirmação com `arquivo:linha` — mais a ordem de migração
  para o `erp/`. **`DEPENDENCIAS.md`**: a intenção e o fato, e os três passos
  para trocar de versão de biblioteca sem destravar nada. **`RECUPERACAO.md`**:
  de um Windows recém-instalado até uma remessa gerada e uma conferência de
  saldos feita, montado SÓ com o que os arquivos do repositório já dizem — onde
  eles não dizem, está escrito "NÃO DOCUMENTADO — dono preenche", porque
  palpite em runbook de recuperação é pior que lacuna: parece resposta. Ele
  também lista o que se perde se esta máquina morrer. **`SUPABASE-PAINEL.md`**:
  conferir campo do painel contra campo do `config.toml`, à mão — o
  `config push` aplica sem mostrar diff, e a lista é a alternativa segura.
  **`PROVENIENCIA.md`**: para cada runbook, qual migration corresponde e onde
  os dois divergem, por diff normalizado. E `confirmado.html`, a página
  estática que serve de destino ao `site_url` do Supabase.
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

## Restrições importantes (aprendidas a caminhadas)

- **Playwright sync = uma única thread.** Todo trabalho com o navegador do ERP
  roda em `AnexarFrame.exec` (ThreadPoolExecutor de 1 worker). Nunca tocar em
  `page`/`mc` fora dela (erro greenlet "cannot switch to a different thread").
  O `extratos_sicoob/` é a exceção deliberada: tem executor e navegador
  próprios porque fala com outro site, sob outro login — a regra continua
  valendo dentro de cada um.
- **Sicoob/Inter 2026**: comprovantes "impressos" sem camada de texto (texto
  vira curvas vetoriais). Sem OCR, extração retorna vazio.
- **O ERP não bloqueia HTTP de fora do navegador — ele recusa quem se
  identifica como robô.** A regra antiga ("chamada HTTP feita fora do navegador
  leva 403; sempre via página logada") estava escrita aqui, no
  `anexar/mc_api.py` e no `aportes/mc_catalogos.py`, e virou lenda antes de a
  causa ser conhecida. O que o WAF confere é o `user-agent`, medido em
  `conciliacao/erp/api.py:23-29`: com o de Chrome, **200**; sem ele
  (Python-urllib), **403** e a página HTML do WAF. É o mesmo guarda que recusa o
  navegador em modo headless. **Três clientes já rodam por HTTP puro**, um deles
  fazendo PUT de lançamento no `legacy-api`. Sobram três consumidores que
  precisam mesmo do navegador, e o motivo de nenhum é o WAF: o upload do
  comprovante é diálogo de tela, o PDF do extrato é gerado pela própria página,
  e o host GraphQL das obras só aparece nos cabeçalhos quando o ERP carrega o
  FORMULÁRIO de lançamento. O inventário, com uma linha por consumidor, está em
  `docs/ERP-CLIENTES.md`; o `user-agent` mora em `erp.sessao.USER_AGENT`. Duas
  ressalvas que valem para qualquer migração: **MFA encerra o assunto** (o login
  automático não passa por segundo fator, e aí o navegador deixa de ser plano B
  e vira o único caminho), e o `POST /users/login` do HTTP direto **derruba** a
  sessão do navegador — o ERP aceita uma por usuário, e é isso que define a
  ordem da coleta da Conciliação (navegador primeiro, API depois) e faz o
  `nuvem/contas_novas.py` rodar na ABERTURA, antes de existir Chrome.
- PyInstaller onefile: caminhos persistentes usam a pasta do EXE
  (sys.executable), nunca __file__ (que aponta para pasta temporária).
- pdfminer precisa de `--collect-all pdfminer`/`pdfplumber` no PyInstaller
  (sem isso, extração de texto silenciosamente vazia nos exes).
- Exibir caminhos ao usuário com "/" (preferência do dono do projeto).

## Desenvolvimento

- **Branch + PR, sempre.** A `main` é protegida e a trava vale para o admin:
  nada entra por push direto, e não há force-push. Para trabalhar em duas
  frentes ao mesmo tempo, `git worktree` em `_worktrees/`, **fora** do
  repositório — assim a segunda frente não disputa o checkout principal, que
  costuma estar com alteração de outra pessoa por commitar.
- Rodar como script: `python comprovantes_app.py` (tkinter;
  `pip install -r requirements.txt` + `python -m playwright install chrome`;
  OCR local requer Tesseract instalado com idioma por). O alvo é **Python
  3.11** — é o que o CI usa, o que o PyInstaller embute e para o que o
  `requirements.lock` é resolvido; escrever contra um interpretador mais novo
  passa aqui e falha no usuário (ver a regra de ouro).
- **`requirements.lock` é o FATO; `requirements.txt` é a INTENÇÃO.** O `.txt`
  guarda as faixas (`pdfplumber>=0.11,<1`), o `.lock` guarda a versão exata e o
  hash das 23 distribuições — as 8 diretas e as 15 que elas arrastam, e que
  antes entravam no exe sem ninguém saber quais eram. É o `.lock` que o CI
  instala (`pip install --require-hashes`). Enquanto só havia faixas, o mesmo
  commit construído em dias diferentes gerava executáveis diferentes: versão
  nova de terceiro quebrava a entrega sem uma linha de código mudar, e defeito
  de produção não se reproduzia aqui. Quem recompila é o **`uv`**, e não o
  `pip-compile`: o `pip-compile` resolve com o interpretador que o roda, e nesta
  máquina não há um 3.11 real — o `uv` resolve para o alvo sem precisar dele
  (`--python-version 3.11 --python-platform windows`) e a saída é um
  requirements comum, que o CI lê sem uv nenhum. O comando está no cabeçalho do
  próprio arquivo, e o passo a passo em `docs/DEPENDENCIAS.md`. O job `test`
  recompila e compara: fica vermelho só quando alguém mexeu na faixa e esqueceu
  de recompilar. **Recompilar não é atualizar** — com o arquivo de saída no
  lugar, o uv o lê como preferência e mantém o que já estava lá.
  `requirements-dev.txt` continua na faixa, de propósito: pytest, ruff, vermin,
  pytest-cov e uv são régua de CI e não entram no exe.
- Testes: `python -m pytest tests -q` (PYTHONPATH com a raiz +
  `separar_renomear` + `anexar`). As fixtures em `tests/fixtures/*.txt` são o
  texto que sai do pdfplumber/OCR, **anonimizado** — o repo é público, nunca
  colocar comprovante real. Cobrir um layout novo = salvar o texto dele ali.
- **O job `test` roda quatro coisas, nesta ordem**: `ruff check --select E9,F .`
  (só erro de verdade — sintaxe e o pyflakes inteiro: nome indefinido, import
  não usado, f-string sem placeholder; zero opinião de estilo), a conferência
  do `requirements.lock`, `vermin --target=3.11` e `pytest --cov`. A cobertura
  vai para o resumo do job e o `coverage.xml` sobe como artefato, **sem piso e
  sem quebrar a build**: em 02/09/2026 são **51%**, e o número está ali para ser
  acompanhado, não para ser cumprido. O `.coveragerc` omite `tests/` (que
  mediria a si mesmo, sempre 100%, e inflaria a média), `codigo_embutido/`,
  `codigo/`, `build/` e `dist/`. Localmente valem os mesmos comandos, mais
  `python -m py_compile <arquivos>` e `pyflakes`.
- **Teste de interface usa a fixture `raiz` do conftest**, que é UM `Tk()` para
  a sessão inteira. Módulo que abrir e destruir o próprio faz os módulos
  SEGUINTES pularem com "sem display" numa máquina que tem display — e teste
  que pula não aparece em vermelho. Foi assim que os 9 do `test_widgets.py`
  sumiram por um momento. Já o contraste da paleta (`test_visual.py`) é
  aritmética sobre constantes: roda no CI sem tela nenhuma.
  **O `Tk()` dessa fixture nasce dentro de `tcl_com_handles_proprios`.** No
  Windows o Tcl embrulha os handles padrão do processo, a captura de saída do
  pytest os fecha por fora a cada fase de teste, e o valor reaproveitado pelo
  Windows faz o `open` do `tclIndex` do Tk falhar em silêncio — daí
  `invalid command name "tk_focusNext"` numa rodada a cada cinco da suíte
  (02/09/2026). Parecia disputa de foco com o `focus_force`, e não era: o
  docstring da função e `tests/test_raiz.py` contam o resto. Teste de
  interface que morre com `invalid command name` num proc do Tk, ou num
  `source` de `.tcl`, é para desconfiar da captura antes do teste.
  **Tecla gerada em teste passa por `teclar`, nunca por `event_generate`
  cru.** O Tk entrega tecla gerada a quem tem o foco, e "quem tem o foco" é o
  `focus`, que fica VAZIO sempre que o Windows leva o foco para outra janela
  — a Tk da suíte vizinha, um clique de quem usa a máquina. Aí a tecla é
  descartada em silêncio (é contrato do Tk, `event(n)`), e era a segunda
  família de intermitência da suíte, a que o PR #41 deixou explicitamente de
  fora: `test_as_setas_andam_pela_lista…`, `test_digitar_do_zero…`. Três
  coisas medidas antes de escolher o conserto, e que o bloco "teclas e foco"
  do conftest guarda: `focus_set` só ANOTA o foco para quando o app o
  recuperar (é o `focus -lastfor`) e não o escreve enquanto o Windows o tem —
  é o caminho de `focar_busca()`; `event_generate("<FocusIn>")` não engana o
  Tk 8.6.15, que marca o evento como gerado e não mexe no foco; e
  `focus_force` seguido de `update` ANTES da tecla reabre a janela, porque é
  no `update` que o FocusOut do Windows é processado — e `update` DEPOIS da
  tecla, antes do assert, é a mesma armadilha do outro lado: a tecla chega,
  mas o `<FocusOut>` do próprio widget desfaz o que ela fez (`_ao_sair` do
  `ComboBusca` devolve a lista inteira, `_completar_ano` do `CampoData`
  completa o ano). `teclar` confere (ou
  toma, com `focus_force`) o foco, deixa as bindings de foco rodarem ANTES
  da tecla — só o que já está na fila do Tcl, até uma sentinela posta no fim
  dela, porque o `<FocusIn>` da busca rodando DEPOIS do Enter apagava a dica
  que o Enter tinha posto, e porque `update` ou `dooneevent` solto leem
  mensagens novas do Windows (medido: com três suítes roubando o foco umas
  das outras, o `dooneevent` solto virou tempestade, 3 a 12 falhas por
  rodada) — e confere o foco de novo imediatamente antes do `event
  generate`; a tecla continua seguindo o caminho normal do Tk (bindtags,
  bindings de classe, `break`), então o que o teste prova não muda. `focar`
  sozinho é o que os testes de APARÊNCIA do foco (o anel do `ItemMenu`)
  usam: devolve com o widget focado e já reagindo a isso. Asserção sobre
  "quem ficou com o foco" é por
  `focus_lastfor` (o que a janela guarda) e não `focus_get` (o foco do
  Windows agora), como o `test_visual.py` já fazia. Quem reencena o roubo,
  sem outro processo, é `tests/test_teclar.py`, com `SetFocus(NULL)`: a tecla
  crua some, a de `teclar` chega. **E o `_realce` 7 da evidência não era o
  foco, era o mouse**: a lista da busca é uma janela visível que nasce colada
  à janela invisível da suíte, e com o ponteiro parado em cima dela o
  `<Enter>` da linha realça a linha — por isso a `raiz` nasce, e a fixture
  `barra` a leva de novo, para a metade da tela em que o ponteiro não está
  (`longe_do_ponteiro`). Ninguém move o ponteiro de ninguém; move-se a
  janela. Para reproduzir a família de propósito: três `pytest` ao mesmo
  tempo não bastam (12 rodadas, zero), porque o Windows recusa
  `SetForegroundWindow` a processo que não recebeu a última entrada — é
  preciso um processo à parte tomando o primeiro plano com uma entrada
  sintética e devolvendo a permissão (`AllowSetForegroundWindow`), que é o
  vaivém real entre quem usa a máquina e uma suíte lançada do terminal em
  primeiro plano.
- **Mudança visual passa pela galeria, antes e depois**:
  `python -m ferramentas.galeria`, as 12 telas nos dois temas, e a comparação é
  o olho de quem mexeu. **Os PNG não vão para o PR** — a tela pode carregar nome
  de empresa vindo do cache, e o repositório é público; o que vai é a diferença
  MEDIDA (o PR #15 relatou 6.605 px trocados no Anexar e 0 px no Início, e o
  zero era o resultado certo, porque o Início não tem botão de passo nem cartão
  numerado). **Duas coisas a saber antes de rodar**: ela fotografa o MONITOR, e
  por isso só roda com a máquina livre — com alguém usando a tela, a rodada é
  interrompida ou sai suja; e **`--escala` MULTIPLICA a escala atual do
  Windows**, não a de 100%. Nesta máquina, que está a **125%**, `--escala 1.0`
  já desenha a 125%: para ver o app a 100% é `--escala 0.8`, e para vê-lo a
  150% é `--escala 1.2`.
- **"Nenhuma cor fixa fora do `widgets.py`" deixou de ser conferência a olho**
  e virou teste — entrou em 02/09 (PR #30), e hoje não acha nada.
- **Nunca commitar dados da empresa**: PDFs de comprovantes, relatórios
  xlsx, `.chrome_profile`, logs, a pasta `galeria/` (print de janela pode
  trazer nome de empresa vindo do cache) e o `sonda.ALERTA.txt`, que é estado da
  máquina e não código — tudo já no `.gitignore`; a pasta local `debug/` é só
  diagnóstico local e nunca foi para o repo. E **nome real de fornecedor ou de
  pessoa, CPF e CNPJ não entram** — nem em teste, nem em comentário, nem em
  runbook.
  **Regra de dado tem de mirar o DADO, e o `.gitignore` já engoliu um módulo.**
  Uma linha escrita para proteger um `.json` de cadastro ficou sem âncora e sem
  extensão, e o padrão casou também com o `.py` de mesmo nome, que é CÓDIGO: o
  módulo nunca foi commitado, a suíte passava aqui (o arquivo existe no disco de
  quem escreveu) e quebrou no CI, que só tem o que o git carrega. Escapando, o
  app não abriria na máquina de quem usa, com o import estourando antes de
  existir janela — a mesma família do `tkinter.font` da v1.0.71. O buraco maior
  estava aberto o tempo todo: os testes de empacotamento perguntam ao GIT o que
  existe (`git ls-files`), então arquivo de código ignorado é invisível para
  eles. Quem fecha isso é `test_todo_py_de_codigo_esta_no_git`, que olha o DISCO
  e cobra o git — o único ângulo em que esse buraco aparece.
- Ícone: `icone.ico` (gerado por script PIL; documento com check verde).
- SmartScreen/Smart App Control: exe não assinado. Solução definitiva
  pendente: assinatura de código (Azure Trusted Signing) integrada ao CI.

## Histórico resumido (jul/2026)

Criação do repo e CI → exes PyInstaller → app unificado com abas →
correção OCR/layout impresso Sicoob-Inter → travas do matcher (não casar só
por data com valores repetidos; aceitar valor pago com juros) → timeouts/reset
do ERP → arquitetura motor+código (auto-update leve) → visual: navegação
lateral + tema auto/claro/escuro + sv-ttk + HiDPI → janela de dúvidas
interativa, botão abrir relatório, conferência pós-anexo com checagem de
conteúdo. Releases antigas são podadas pelo CI (mantém 4).

## Ideias pendentes

- Assinatura digital do exe no CI (elimina SmartScreen/Smart App Control).
- Centralizar seletores do ERP (mc_client.py) em constantes/config.
- OCR em lote cruzando ARQUIVOS (hoje o pool é por arquivo; entrada com
  muitos PDFs de página única não aproveita o paralelismo).
- Aba de cadastro dentro do app, se editar pelo painel do Supabase incomodar.
- Fase 3 da nuvem: o registro central (aportes lançados, NSA, retorno CNAB,
  envios da Acessórias). Ver `nuvem/registro.py`, que já existe vazio.

## Auditoria de 11/08/2026 — o que mudou

Um lote grande de correções, agrupado por bloco. O que vale guardar como
DECISÃO (o resto está nos commits):

- **Nada de "anexado" sem prova.** `mc_client.anexar` espera o arquivo aparecer
  na lista do diálogo e relê a grade depois de confirmar; sem isso retorna
  `erro:nao_confirmado`. O `wait_for_timeout(3000)` fixo era menor que o upload
  em lote e o Confirmar ia sem arquivo.
- **-1 não é 0.** `mc_api.verificar_anexos` devolve -1 quando o fetch falha, e
  os dois consumidores tratavam isso como "tem anexo" — a aba Anexar pulava o
  pagamento e a Conferência omitia a linha. Use `mc_api.estado_anexo()`: são
  TRÊS estados, e "não verificado" nunca pode ser lido como "está certo".
- **Aporte não se repete.** A aba Aportes guarda quais lançamentos de cada
  operação já entraram no ERP; relançar depois de falha parcial pula o que deu
  certo. Dinheiro duplicado se desfaz à mão, lançamento por lançamento.
- **Dinheiro em Decimal**, inclusive nos Aportes (era a última ilha de float, e
  logo no módulo que ESCREVE valores). A conversão para float mora só na
  fronteira do JSON (`mc_lancamentos._num`).
- **Um navegador, seis abas.** `AnexarFrame.submeter()` registra o dono e
  `avisar_se_ocupado()` recusa começar enquanto outra aba trabalha. Antes o
  clique só entrava na fila, mudo, e o trabalho começava minutos depois.
  A checagem vem **antes** de desabilitar botão, marcar `_parar` ou pôr
  qualquer coisa na fila: quem sai pelo `return` não passa mais pelo `_drain`,
  e cinco abas (Pagamentos do Dia ×2, Relatório Mensal ×2, Conciliação)
  desabilitavam primeiro — recusar o começo deixava a aba morta, com os botões
  apagados e nada rodando, até reiniciar o app.
- **Tkinter só na thread da interface.** Toda aba usa `queue` + `after`; quem
  escrever no Text direto da thread do navegador trava a aba. A Conferência e
  os Aportes ainda faziam isso.
- **Os dois mapas de pasta têm de concordar.** `contas_mc.json` (Relatório
  Mensal) e `contas_sicoob.json` (Extratos Sicoob) escolhem a pasta da MESMA
  conta. Divergiram em três subcontas e julho/2026 ficou partido, com o PDF do
  ERP numa pasta e o OFX na outra. `relatorios/conferir_mapas.py` compara e
  avisa antes do primeiro download.
- **`util.py` não importa tkinter.** Ele é usado por módulos de regra que
  rodam sem interface (`pagamentos_dia/relatorio.py`,
  `relatorios/contas_mc.py`, `conciliacao/parsing.py`). Widget compartilhado
  vai em `widgets.py`, que é o par visual dele.
- **`util.norm_espaco` é a ÚNICA comparação de nome de conta.** Era `_chave`
  em duas cópias: uma escolhia a pasta do extrato, a outra julgava se o
  extrato era da conta certa. Duas cópias de uma comparação é uma divergência
  esperando acontecer.
- **O CI agora barra release quebrada.** `build` depende dos jobs `test` e
  `motor`; o segundo falha se o push mexer no motor sem subir
  `motor_minimo.txt`. E `tests/**` saiu do `paths-ignore`, senão o job de
  teste não rodaria no push que altera um teste.
- **Senha de primeira utilização** (`ativacao.py`): substituída em 13/08/2026
  pelo login por pessoa — ver a seção "O cadastro mora na nuvem" abaixo.

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
código de barras/referência do item), e reenviá-lo hoje exige `descartar` a
remessa, o que ainda não tem tela; o reenvio por item, lendo o `retorno_codigo`
de cada um, é outro PR. **`ESTADOS_VIVOS` é UMA tupla**, importada de
`cnab240.historico` no topo do `registro.py` — enquanto foram duas listas
escritas à mão elas divergiram em silêncio, com "aceito" só de um lado e
"rejeitado" só do outro.

**O que ainda NÃO está na nuvem** (e continua como estava): os aportes já
lançados, que seguem em `self.criados`, memória do processo em
`aportes/aportes_frame.py` — falha parcial seguida de reabrir o app ainda
apaga a proteção contra duplicar; e os envios da Acessórias, hoje conferidos
relendo o portal, que funciona. As colunas `retorno_codigo`/`retorno_em`
existem em `remessa_item` esperando quem processe o retorno do banco.

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


## 02/09/2026 — a consolidação

Cinco análises (a esteira, o ERP, o front-end, os dados e o código morto)
viraram uma ordem de trabalho, e cerca de trinta PRs entraram no mesmo dia. O
porquê de cada um está no corpo dele; aqui fica o mapa e, principalmente, o que
NÃO foi feito.

**O que entrou, por tema.** *Entrega*: o portão de release (#1), o
`requirements.lock` (#12), o ruff e a cobertura no CI (#6), o `motor_minimo` de
uma unidade (#7, #24). *Diagnóstico*: o `util.log()` e a adoção módulo a módulo
(#8, #11, #13, #14, #17, #19, #20). *ERP*: o inventário (#22), o pacote `erp/`
(#24), o relogin do legado (#27) e as duas primeiras migrações (#31, #33).
*Interface*: o contraste do azul sólido (#15), o teclado e os ícones do menu
(#28), a abertura mais rápida (#29), a busca que leva a uma tela (#32).
*Ferramentas e documento*: a galeria (#10, #23), a sonda (#25), os runbooks e a
proveniência (#18), a recuperação (#21), o painel do Supabase e o `config.toml`
(#16), os caminhos num lugar só (#3, #26), uma cópia só do `cnab240` (#2).
Uma quarta leva de interface fechou o dia, empilhada nesta ordem e toda em
`widgets.py`: a cor fixa que virou teste (#30), os erros com nome (#34), as
tabelas que ordenam pelo cabeçalho (#35) e o layout que escala junto com a
fonte (#37, `widgets.px()`) — o que cada um decidiu está na entrada do
`widgets.py`.

**O que ficou pendente, e por quê.** Está escrito porque pendência que só mora
na cabeça de alguém não é pendência, é esquecimento:

- **`widgets.estado_de` sempre devolve `"info"`, e por isso nenhuma linha de
  tabela se pinta hoje.** `util.norm` devolve MAIÚSCULAS e as chaves de
  `ESTADOS` são minúsculas, então `"apto" in "APTO (AUTORIZADO)"` é falso e a
  varredura inteira passa reto — inclusive o resgate do fim, que procura
  `"atencao"`, `"conferir"` e `"divergen"`, também minúsculos. Conferido
  rodando: `APTO (autorizado)`, `ATENÇÃO — sem anexo`, `JÁ PAGO em 12/08/2026`
  e `SEM PAR` devolvem os quatro `"info"`. É a armadilha de sempre desta casa —
  falha em silêncio, e o que se vê é uma tabela sem cor nenhuma, que parece
  escolha de design. **Correção em andamento em sessão do dono.**
- **a galeria de DEPOIS do PR #37 ainda não foi tirada**: a rodada foi
  interrompida porque o dono estava usando a tela, e a galeria fotografa o
  monitor. O ANTES a 1,5 confirmou os quatro defeitos, e uma primeira rodada do
  DEPOIS já mostrava "ÚLTIMA EXECUÇÃO" por extenso e o logotipo inteiro — mas
  essa captura pegou uma notificação do Windows por cima, e captura suja é
  justamente o que a ferramenta existe para recusar. Falta a rodada limpa, nos
  dois temas, mais a conferência de 0 px na escala de referência. Ao refazer,
  lembrar que **`--escala` multiplica a escala ATUAL** e que esta máquina está a
  125%: 100% é `--escala 0.8` e 150% é `--escala 1.2`;
- **a intermitência dos testes de interface teve DUAS causas, e as duas estão
  fechadas.** O Tab do menu (`test_o_tab_passa_por_cada_item_do_menu`) morria
  com `invalid command name "tk_focusNext"`, e era a captura de saída do
  pytest fechando handles do Tcl — `tcl_com_handles_proprios` no conftest,
  PR #41. Sobrava a família das TECLAS: `event_generate` de tecla descartado
  quando o Windows leva o foco entre uma chamada e outra, mais o ponteiro do
  mouse parado sobre a lista da busca — `teclar`/`focar`/`longe_do_ponteiro`
  no conftest e `tests/test_teclar.py` (ver "Teste de interface usa a fixture
  `raiz`", em Desenvolvimento). O que fica: o `focus_force` de `teclar` ainda
  chama `SetForegroundWindow`, então a suíte continua disputando o primeiro
  plano com quem usa a máquina (e quem digita nesse instante digita na janela
  invisível da suíte) — é o único jeito que o Tk 8.6 dá de escrever o foco
  sem o consentimento do Windows, e trocá-lo exigiria um Tk que aceitasse
  `<FocusIn>` gerado;
- **os consumidores 4 a 8 do ERP** — `aportes/mc_catalogos.py` +
  `aportes/erp_sessao.py`; `conciliacao/erp/payments.py`, cuja grade raspada
  tem endpoint REST equivalente (`payable-installments/paginated-result`, que
  dois outros clientes já consomem) e é a linha que paga o documento inteiro,
  porque com ela some a raspagem, some o login por navegador da Conciliação e
  some a exigência de janela visível — e é também a mais cara de conferir,
  porque o resultado é dinheiro no painel do dia; `relatorios/extrato_mc.py` e
  `anexar/mc_client.py`, em que só as constantes de host mudam; e
  `anexar/mc_api.py` por último. A ordem e o motivo de cada posição estão no fim
  do `docs/ERP-CLIENTES.md`;
- **as esperas fixas**: ~124 s somados em 83 pontos com o número escrito no
  código (de 90 chamadas de `wait_for_timeout`/`sleep`), concentrados em
  `baixar_comprovantes/inter_baixar.py` (20), `conciliacao/erp/payments.py`
  (16) e `anexar/mc_client.py` (11). Trocá-las por espera por CONDIÇÃO é a
  mudança de melhor relação ganho/risco que sobrou, e é a única que **só se
  testa contra o portal real** — o que se mede ali é o tempo que o site de
  terceiro leva, e nenhum dublê sabe isso;
- **fixtures sintéticas para os 74 testes que pulam.** Eles pulam por falta dos
  arquivos que não entram no repositório (`config.yaml`, `mapping.yaml`,
  `MODELO.xlsx`, os cadastros), e teste que pula não aparece em vermelho — é a
  mesma armadilha dos 9 do `test_widgets.py`, num tamanho maior;
- **o `_sair` de `comprovantes_app.py`**, cujo `except Exception: pass` em
  volta do `fechar()` de cada aba continua mudo. É o que o PR #20 deixou
  explicitamente de fora;
- **a aba Início custa ~670 ms** para construir, contra menos de 100 ms das
  outras, e o custo é trabalho de construção, não import (PR #29);
- **`conciliacao/workbook.py` e `pagamentos_dia/relatorio.py` importam
  `openpyxl`/`pdfplumber` sem condição** no topo, e por isso o ganho do PR #29
  ficou pela metade: ~0,27 s de openpyxl e ~0,08 s de pdfplumber continuam
  entrando antes de existir janela. No segundo, o `try: import pdfplumber` não
  evita o custo — só evita o erro se a biblioteca faltar;
- **o `ARQUIVO_LOG` (`log_anexos.csv`) do `anexar/config.py` ainda sai do
  `_AQUI`**, e é o último caminho calculado pela pasta do MÓDULO depois que o
  perfil do Chrome, o `diagnostico.log` e o `login.dat` migraram para
  `util.pasta_base()`;
- **o `grant insert, update on table public.conta to authenticated`** da
  migration `20260824141500` não aparece em runbook nenhum: o runbook de 21/08
  criou as políticas `conta_cadastra` e `conta_corrige` e parou aí, e o
  privilégio veio três dias depois, só na migration. Sem ele a política nem
  chega a ser consultada, e não há registro de por onde ele chegou ao projeto de
  verdade — é o primeiro item do `docs/PROVENIENCIA.md`, e a conferência é um
  `db diff` que só lê;
- **nomes de fornecedor que já estão na `main` pública** — em
  `conciliacao/rules.py`, `pagamentos_dia/remessa_dia.py`,
  `conciliacao/parsing.py` e `nuvem/contas_novas.py` —, contra a regra da casa
  de que nome real de fornecedor ou de pessoa não entra no repositório. Foi por
  causa deles que um runbook entrou e depois saiu (commit `25ae569`): o critério
  aplicado ao arquivo novo não estava sendo aplicado ao que já estava
  publicado. Tirá-los mexe em regra de negócio e em histórico já público, então
  **é decisão do dono**, e não de quem estiver com o arquivo aberto.