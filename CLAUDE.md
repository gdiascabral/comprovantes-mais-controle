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

O mapa módulo a módulo saiu daqui em 14/09/2026 e mora em `.claude/rules/`, um
arquivo por pasta, com o texto intacto. Cada um carrega sozinho quando o Claude
lê um arquivo daquela pasta. Numa sessão aberta fora do repositório (ou se não
carregar), **leia o arquivo da pasta antes de mexer nela**.

| Pasta ou arquivo | Onde está o mapa |
|---|---|
| motor e atualizador | `.claude/rules/arquitetura-motor-e-atualizador.md` |
| util.py | `.claude/rules/arquitetura-util.md` |
| erp/ (falar com o Mais Controle) | `.claude/rules/arquitetura-erp.md` |
| conciliacao/ | `.claude/rules/arquitetura-conciliacao.md` |
| janela e widgets | `.claude/rules/arquitetura-interface.md` |
| inicio/ | `.claude/rules/arquitetura-inicio.md` |
| separar_renomear/ | `.claude/rules/arquitetura-separar-renomear.md` |
| anexar/ | `.claude/rules/arquitetura-anexar.md` |
| relatorios/ | `.claude/rules/arquitetura-relatorios.md` |
| pagamentos_dia/ | `.claude/rules/arquitetura-pagamentos-dia.md` |
| cnab240/ | `.claude/rules/arquitetura-cnab240.md` |
| extratos_sicoob/ | `.claude/rules/arquitetura-extratos-sicoob.md` |
| contratos/ | `.claude/rules/arquitetura-contratos.md` |
| acessorias/ | `.claude/rules/arquitetura-acessorias.md` |
| ferramentas/ | `.claude/rules/arquitetura-ferramentas.md` |
| cadastro na nuvem, NSA e runbooks | `.claude/rules/nuvem-e-remessas.md` |

Comentário de código que diz "ver CLAUDE.md, <trecho>" pode apontar para um
desses arquivos: `grep -rn "<trecho>" CLAUDE.md .claude/rules docs/claude`.
Texto novo sobre uma pasta vai para o arquivo dela, não para cá.

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
## Restrições importantes (aprendidas a caminhadas)

- **Playwright sync = uma única thread.** Todo trabalho com o navegador do ERP
  roda em `AnexarFrame.exec` (ThreadPoolExecutor de 1 worker). Nunca tocar em
  `page`/`mc` fora dela (erro greenlet "cannot switch to a different thread").
  Da thread da interface só se lê `mc.fechado` — e a aba da pessoa, com o
  robô trabalhando, entra pelo chrome.exe e não pelo Playwright.
- **O robô só trabalha nas abas dele** (`MCClient._minhas`). A pessoa pode ter
  abas suas no Chrome do app; código novo que procurar "a aba do ERP" tem de
  passar por `_abas_do_robo()`, nunca por `ctx.pages` — senão volta a navegar
  a aba em que ela está. E nunca `ctx.new_page()` no meio de uma tarefa: o
  Chrome traz a aba nova para a frente, por cima da dela.
- **Todo perfil do Chrome que baixa arquivo passa por
  `util.limpar_historico_de_downloads` antes de abrir** (Chrome 152 cai no
  primeiro download de perfil já usado — ver `anexar/mc_client.py` acima).
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
  comprovante era diálogo de tela (desde 08/09/2026 sobe pela API, de dentro
  da página — `mc_api.anexar_por_api` —, e o diálogo é o plano B), o PDF do
  extrato é gerado pela própria página,
  e o host GraphQL das obras só aparece nos cabeçalhos quando o ERP carrega o
  FORMULÁRIO de lançamento. O inventário, com uma linha por consumidor, está em
  `docs/ERP-CLIENTES.md`; o `user-agent` mora em `erp.sessao.USER_AGENT`. Duas
  ressalvas que valem para qualquer migração: **MFA encerra o assunto** (o login
  automático não passa por segundo fator, e aí o navegador deixa de ser plano B
  e vira o único caminho), e o `POST /users/login` do HTTP direto **derruba** a
  sessão do navegador — o ERP aceita uma por usuário, e é isso que define a
  ordem da coleta da Conciliação pela tela, o plano B (navegador primeiro,
  API depois) e faz o `nuvem/contas_novas.py` rodar na ABERTURA, antes de
  existir Chrome.
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

## Cadastro na nuvem e NSA das remessas

Movido em 14/09/2026 para `.claude/rules/nuvem-e-remessas.md`, que carrega com `nuvem/`,
`supabase/`, `cnab240/` e a remessa/retorno do dia.

## 02/09/2026 — a consolidação (relato)

O relato do dia e a lista do que ficou pendente estão em
`docs/claude/consolidacao-2026-09-02.md`.
