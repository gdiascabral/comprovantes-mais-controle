# Comprovantes — Mais Controle

App Windows (Python/tkinter, distribuído como .exe via PyInstaller) que separa,
renomeia e anexa comprovantes bancários nos pagamentos do Mais Controle ERP.
Usuários finais são leigos: praticidade acima de tudo. Repo público:
https://github.com/gdiascabral/comprovantes-mais-controle

## Regra de ouro: como uma mudança chega ao usuário

TODO push na `main` dispara o GitHub Actions (`.github/workflows/build.yml`), que:
1. gera `versao.txt` = `v1.0.<run_number>` (NÃO é commitado; criado na build);
2. monta `codigo.zip` (comprovantes_app.py + util.py + widgets.py +
   separar_renomear/*.py + anexar/*.py + aportes/*.py +
   relatorios/*.py + pagamentos_dia/*.py + extratos_sicoob/*.py +
   conciliacao/*.py + conciliacao/erp/*.py + contratos/*.py +
   acessorias/*.py + cnab240/*.py + **cnab240/spec/*.json** +
   **nuvem/*.py exceto migrar.py** + versao.txt +
   motor_minimo.txt + icone.ico) — ~100 KB.
   **Pasta nova de aba OU arquivo novo na raiz = linha nova aqui**, senão o
   import falha no usuário e o app não abre. Vale para os dois: `widgets.py` é
   de raiz e precisou entrar um a um;
   **`cnab240/spec/*.json` é a exceção que confirma a regra**: é o único pacote
   com DADOS, e copiar só os `.py` dele não quebra o import — quebra a primeira
   remessa, na máquina do usuário. Guardado por `tests/test_cnab240_pacote.py`;
   **`nuvem/migrar.py` é a exceção oposta**: fica de fora porque é ferramenta
   de uma vez só, rodada à mão no repositório, e o app nunca a importa;
3. builda **um** exe — `Comprovantes Mais Controle.exe` (PyInstaller onefile,
   com Tesseract OCR embutido) — e publica a Release `v1.0.<run_number>` com
   o exe + codigo.zip. Os exes avulsos de Separar e de Anexar foram removidos:
   tudo vive em abas no app principal;
4. apaga releases antigas mantendo as **4 mais novas** (política de rollback).

O exe do usuário é dividido em **motor** (Python + libs + OCR + `motor.py` +
`atualizador.py`) e **código** (o resto). Ao abrir, o app baixa só o
`codigo.zip` novo (segundos, sem perguntar) e roda com ele. Portanto:

- Mudanças em `comprovantes_app.py`, `separar_renomear/`, `anexar/`,
  `aportes/`, `relatorios/`, `pagamentos_dia/`, `extratos_sicoob/`,
  `contratos/`, `conciliacao/`, `acessorias/` →
  chegam sozinhas ao usuário no próximo abrir. Só commitar e esperar a build.
- Mudanças em `motor.py`, `atualizador.py`, dependências novas no
  `requirements.txt` ou `--collect-all` no workflow → exigem exe novo.
  **Obrigatório**: subir `motor_minimo.txt` para a versão da release que sai
  (v1.0.<run_number+1>), senão o código novo roda em motor velho e quebra.
  O app então oferece o download completo (~150 MB) com progresso.
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
  mede o que o exe de fato contém em vez do que o motor escreve. Precisando de
  um submódulo novo: acrescente ao `_garantir_dependencias()` do motor.py e
  suba o `motor_minimo.txt` no MESMO push. Preferir o caminho sem import novo
  quando existir — foi o que salvou este caso (o `_garantir_fontes` fala com o
  Tcl direto, e a correção chegou pelo codigo.zip em segundos, em vez de 152 MB
  para todo mundo baixar).
- **Aba nova custa uma release com exe novo, mesmo sem precisar.** Pasta nova
  obriga a mexer no `build.yml` (item 2 acima), e o job `motor` recusa todo
  push que toque nesse arquivo sem subir o `motor_minimo.txt` junto. A trava é
  MECÂNICA — olha o nome do arquivo alterado, não o que mudou dentro dele —,
  então adicionar uma aba dispara o download de ~150 MB em quem estiver com exe
  anterior, ainda que o código novo rode perfeitamente no motor velho. Foi o
  caso da aba Acessórias (v1.0.75): nenhum import novo, e mesmo assim a baixa
  completa. Consequência prática: **vale agrupar abas novas num push só**, e
  não pagar o pedágio uma vez por aba.
- **O exe roda Python 3.11, e a sua máquina provavelmente não.** O CI usa 3.11
  e o PyInstaller embute essa versão; escrever contra um interpretador mais
  novo passa aqui e falha lá. Aconteceu na run #76: `Path.read_text(newline=…)`
  existe desde o 3.13 e o teste do CNAB 240 quebrou no CI, com o `build`
  pulado. É a mesma família do `tkinter.font` da v1.0.71 — código que a sua
  stdlib tem e a do usuário não. Antes de subir, `vermin --target=3.11
  --violations` sobre o que mudou (está no `requirements-dev.txt`).
- **Build que falha CONSOME o número da release.** A versão é
  `v1.0.<run_number>`, e o contador anda mesmo quando o job quebra: depois da
  #76 falhar, a próxima release passou a ser a v1.0.77. Quem for corrigir e
  subir de novo tem de **subir o `motor_minimo.txt` junto**, senão ele aponta
  para uma versão que nunca existiu.
- Build leva ~8–10 min. Commits só de README/LICENSE/CLAUDE.md não disparam
  build (paths-ignore).

## Arquitetura

- `motor.py` — entrada do exe: escolhe a fonte de código (pasta `codigo/` ao
  lado do exe, ou `codigo_embutido` de fábrica), injeta em sys.path e chama
  `comprovantes_app.main()`. Contém `_garantir_dependencias()` (imports nunca
  chamados, só para o PyInstaller enxergar as libs).
- `atualizador.py` — motor-side: baixa codigo.zip, troca de pasta atômica,
  download do exe completo com janela de progresso, troca via .bat com 30
  retentativas (OneDrive trava arquivos). Loga em `atualizacao.log`.
- `conciliacao/` — aba Conciliação Diária: lê saldos e pagamentos a vencer e
  gera o painel do dia sobre o `MODELO.xlsx`, com o aporte mínimo por conta.
  **Único pacote de verdade** (tem `__init__.py`, importa-se
  `from conciliacao.frame import ...`): nome de módulo é global no sys.path do
  app, e um pacote dispensa o prefixo que `extratos_sicoob/` precisou usar.
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
- `comprovantes_app.py` — janela única: barra lateral com quatro itens soltos
  (Separar e Renomear / Anexar Comprovantes / Conferência / Aportes) e dois
  grupos que abrem e fecham — DIÁRIO (Pagamentos do Dia, Conciliação Diária) e
  MENSAL (Relatório Mensal, Extratos Sicoob, Contratos, Acessórias). O pulso da
  barra pergunta a TRÊS navegadores, não a um: o do ERP (via
  `aba_anx.dona_ocupada()`) e os de `extratos_sicoob/` e `acessorias/`, que são
  processo e login à parte. O estado de cada grupo fica em
  `preferencias.json`, e selecionar uma aba de grupo fechado o abre — senão a
  aba ficaria destacada e invisível. DIÁRIO e MENSAL são `Grupo.Toolbutton`
  (chapado e miúdo) e os itens do grupo entram com recuo: como botões do mesmo
  tamanho dos itens, eles pareciam irmãos do que agrupavam, e fechar o grupo
  era a única pista de que existia um grupo. Continuam sendo Button, e não
  Label com bind de clique, para não sair do Tab e do Espaço. Tema
  Automático (lê o registro do
  Windows)/Claro/Escuro salvo em `preferencias.json`, versão no título e
  no rodapé da barra. Tema sv-ttk; frames expõem `aplicar_cores(escuro)`, que
  hoje só trata `tk.Text` e `tk.Canvas` — o resto segue os estilos nomeados de
  `widgets.py`. Três coisas que a barra faz e não são óbvias no código:
  (1) **ela diz onde o trabalho está**. Um pulso de 600 ms pergunta
  `anx.dona_ocupada()` e `ext.ocupado()`; a aba que está com um navegador troca
  o ícone por ● e o rodapé escreve a tarefa. Antes disso, nove abas dividindo
  um navegador só se manifestavam DEPOIS do clique, no aviso "Navegador
  ocupado"; (2) trocar de aba põe o foco no primeiro `Entry` — Combobox
  `readonly` é pulada de propósito, porque aceita foco sem aceitar digitação;
  (3) Enter num campo de texto aciona o passo principal da aba, procurado em
  `acao_enter`, `b1`, `btn` (nessa ordem). O bind é global, então o handler
  confere pelo caminho do widget se o foco está DENTRO da aba — senão o Enter
  de um diálogo dispararia a aba atrás dele. Nunca a partir de um `Text`: ali
  Enter é quebra de linha, não ordem para começar meia hora de ERP.
- `widgets.py` — o par visual do `util.py` (mora na raiz e vai junto no
  codigo.zip). Além do `CampoData`, é onde vivem a PALETA, as fontes e os
  blocos que toda aba monta: `Cabecalho`, `Cartao`, `Passos`, `estilo_log`,
  `estilo_canvas`, `registro_elastico`, `focar_primeiro_campo`,
  `barra_de_titulo`.
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
  saídas: a data, `Esc` e o X. Como nada mais impede abrir dois, o módulo
  guarda em `_calendario_aberto` qual campo está com o seu — abrir um fecha o
  outro. Regra geral: modal é para o que EXIGE resposta (o login, o confirmar
  dos sócios); o resto não prende ninguém.
  **Quem numera é a AÇÃO, não o cartão.** Numerar os dois punha duas contagens
  na mesma tela: em Pagamentos do Dia, "2. Contas" era um campo para preencher
  e "2. Gerar a planilha" era uma ação, e nenhuma das duas ia até o fim
  sozinha. Hoje os cartões são títulos sem número e o `Passos` desenha a
  trilha no cabeçalho (①→✓), nas quatro abas de dois passos. O estado dela sai
  do `state` dos próprios botões — a aba já libera o passo seguinte quando o
  anterior termina, e guardar isso de novo criaria duas verdades sobre onde a
  pessoa está. Enquanto o trabalho roda TODOS os botões ficam desabilitados,
  e aí a trilha segura o último estado em vez de zerar. Aportes NÃO tem
  trilha, de propósito: seus dois botões nascem os dois habilitados, então não
  há progressão para mostrar.
  **O Registro cresce com o que tem dentro** (`registro_elastico`): parado ele
  era metade da janela em branco com uma frase cinza no meio, enquanto o
  formulário ficava espremido em cima. Quem dispara é o `<<Modified>>` do
  próprio campo, e não a aba — as nove escrevem no registro de lugares
  diferentes, e pedir que cada uma avisasse daria dezoito pontos de chamada
  para esquecer um. A tela vazia não conta como trabalho porque entra toda com
  a tag "ph". Duas armadilhas: `pack_configure` e nunca `pack` (reempacotar
  joga o widget para o FIM da ordem, e em cinco abas o Registro nasceria
  embaixo da barra de ação); e a altura do campo vazio é MEDIDA a cada
  mudança, porque `height` conta linhas enquanto `spacing1` cobra pixels — com
  altura fixa o Anexar cortava ao meio justamente a frase que diz o que fazer. Existia o oposto disso — 51 cores e 17 tuplas de fonte
  espalhadas por 12 arquivos —, e as duas consequências eram visíveis: cor
  escrita na criação do widget não segue o tema (`#6b6b6b` tem 3,2:1 no escuro,
  `#8a8a8a` tem 3,4:1 no claro: cada cinza falhava em UM dos dois), e tamanho
  de fonte em número fixo ignora a escala de exibição do Windows. Hoje a cor é
  estilo nomeado (`Apoio.TLabel`) e o tamanho sai do `TkDefaultFont`.
  **`aplicar_estilos(escuro)` tem de ser chamado DEPOIS de `sv_ttk.set_theme`**:
  o sv-ttk recria o tema do ttk e apaga todo estilo nomeado, e a ordem errada
  não dá erro — as legendas só voltam à cor padrão. Duas armadilhas do Tk que
  o `tests/test_visual.py` cobre: `tkinter.font.Font.__del__` executa
  `font delete`, então a fonte precisa de referência viva (sem isso o Tk lê
  "AppTitulo" como nome de FAMÍLIA e cai no padrão, em silêncio); e tamanho
  negativo é medida em pixels, então escalar tem de preservar o sinal.
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
  **`diagnostico_documentos`** existe para fechar a lacuna do Pix: varre o
  `overview` que o "1. Buscar" já trouxe e diz ONDE há CPF/CNPJ válido, sem
  imprimir documento nenhum — só caminho, contagem e **valores distintos**. É o
  "distintos" que separa o fornecedor (um por lançamento) da própria empresa (o
  mesmo em todos). Os DVs são conferidos: sem eles todo celular de onze dígitos
  viraria "CPF encontrado", a mesma armadilha do `tipo_de_chave_pix`. Um campo
  que aparece em 1% dos lançamentos é acaso (dois DVs fechando por sorte), não
  achado — daí a contagem estar no relatório.
- `pagamentos_dia/pagamentos_frame.py` — aba Pagamentos do Dia, em 3 passos
  (Buscar / Gerar planilha / Gerar remessa). **O passo 3 não passa pelo
  `anx.submeter`**: não há navegador nem ERP nele — a remessa sai do
  `self.resultado` que o passo 2 deixou em memória, e escrever texto local não
  justifica ocupar a sessão que só aceita um por vez. Valida ANTES de gravar:
  arquivo reprovado não é escrito **e não consome o NSA**, senão o histórico
  fica com furo que ele mesmo não sabe explicar. Compartilha navegador e thread do Anexar. O passo separado
  existe porque quem confere quer VER a lista de contas antes de gerar, e cada
  rodada custa uma sessão do ERP (que só aceita uma por usuário). Contas
  "APENAS LANÇAMENTO/AJUSTE" aparecem desmarcadas, não escondidas. As chaves
  Pix dos avisos "PAGAR PARA" ficam em `pix_reembolso.json` ao lado do exe —
  é CPF de gente, não entra no repositório. A janela de confirmação dos
  pagamentos aos sócios abre em `gerar()`, na thread da INTERFACE e **antes**
  de `submeter()`: quem cancela ali não pode ter consumido a sessão do ERP.
  Anexo que é foto só é baixado quando é aviso "PAGAR PARA" — baixar toda
  imagem de todo título seria pagar OCR por nada.
- `cnab240/` — gerador, validador e leitor de retorno do arquivo CNAB 240 do
  Sicoob (Guia v3.3), **stdlib pura** e sem tela nenhuma: é biblioteca, não aba.
  Quem a usa é o passo 3 da aba Pagamentos do Dia (`pagamentos_dia/remessa_dia.py`).
  **O único pacote do app com arquivo de DADOS**: os layouts vivem em
  `cnab240/spec/*.json`, campo a campo com o id do manual, para auditar contra
  o PDF sem abrir código — daí a linha extra no `build.yml` e o
  `tests/test_cnab240_pacote.py` que a vigia.
  **`historico.py` é a parte que o layout não resolve**: o NSA (nº sequencial
  do arquivo) tem de ser CRESCENTE por convênio e quem o controla é quem gera
  — o banco não guarda isso. Ele mora em `remessas.json` ao lado do exe, longe
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
  da conta no fim do nome. `pasta` aceita subnível (`CAIXA/APLICAÇÃO`). A
  comparação de nomes ignora acento, caixa e espaço duplo: o nome vem do
  cadastro do ERP, digitado por gente. `caminhos_longos()` existe porque os
  caminhos aqui são longos (empresa + subconta com descrição + o `.zip` do
  fechamento por cima) e estourar os 260 do Windows aparece como falha de
  escrita no meio do lote, com causa nada óbvia.
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
  conferência) — engole o erro, mas deixa o motivo gravado.

## Restrições importantes (aprendidas a caminhadas)

- **Playwright sync = uma única thread.** Todo trabalho com o navegador do ERP
  roda em `AnexarFrame.exec` (ThreadPoolExecutor de 1 worker). Nunca tocar em
  `page`/`mc` fora dela (erro greenlet "cannot switch to a different thread").
  O `extratos_sicoob/` é a exceção deliberada: tem executor e navegador
  próprios porque fala com outro site, sob outro login — a regra continua
  valendo dentro de cada um.
- **Sicoob/Inter 2026**: comprovantes "impressos" sem camada de texto (texto
  vira curvas vetoriais). Sem OCR, extração retorna vazio.
- ERP bloqueia chamadas HTTP feitas fora do navegador (403) — sempre via
  página logada.
- PyInstaller onefile: caminhos persistentes usam a pasta do EXE
  (sys.executable), nunca __file__ (que aponta para pasta temporária).
- pdfminer precisa de `--collect-all pdfminer`/`pdfplumber` no PyInstaller
  (sem isso, extração de texto silenciosamente vazia nos exes).
- Exibir caminhos ao usuário com "/" (preferência do dono do projeto).

## Desenvolvimento

- Rodar como script: `python comprovantes_app.py` (Python 3.10+, tkinter;
  `pip install -r requirements.txt` + `python -m playwright install chrome`;
  OCR local requer Tesseract instalado com idioma por).
- Testes: `python -m pytest tests -q` (PYTHONPATH com a raiz +
  `separar_renomear` + `anexar`). As fixtures em `tests/fixtures/*.txt` são o
  texto que sai do pdfplumber/OCR, **anonimizado** — o repo é público, nunca
  colocar comprovante real. Cobrir um layout novo = salvar o texto dele ali.
  Checagens extras: `python -m py_compile <arquivos>` e `pyflakes`.
- **Teste de interface usa a fixture `raiz` do conftest**, que é UM `Tk()` para
  a sessão inteira. Módulo que abrir e destruir o próprio faz os módulos
  SEGUINTES pularem com "sem display" numa máquina que tem display — e teste
  que pula não aparece em vermelho. Foi assim que os 9 do `test_widgets.py`
  sumiram por um momento. Já o contraste da paleta (`test_visual.py`) é
  aritmética sobre constantes: roda no CI sem tela nenhuma.
- **Nunca commitar dados da empresa**: PDFs de comprovantes, relatórios
  xlsx, `.chrome_profile`, logs (tudo já no .gitignore; a pasta local
  `debug/` é só diagnóstico local e nunca foi para o repo).
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

**Os JSON/CSV continuam existindo — como CACHE.** `nuvem/cadastro.sincronizar`
roda uma vez, na abertura, e regrava os arquivos de sempre no formato de
sempre. É por isso que `sicoob_contas`, `contas_mc` e `aportes/dados` não
mudaram uma linha: para eles, nada aconteceu. Um formato próprio de cache
teria criado duas verdades sobre a mesma conta — o problema que a nuvem veio
resolver. Três consequências:

- banco mudo não impede o app de abrir: usa a última cópia e escreve
  "⚠ cadastro offline" no rodapé da barra. **Sem esse aviso, "estou com o
  cadastro de ontem" seria indistinguível de "tudo certo"**;
- banco que responde VAZIO não apaga nada (`sincronizar` recusa e mantém os
  arquivos) — projeto novo ou migração não rodada zerariam o cadastro de todo
  mundo, e o cache é justamente a última cópia que sobraria;
- o cache preserva as chaves `_leia_me`/`_ajuda`, que explicam o arquivo para
  quem o abre e não vêm do banco.

**Editar cadastro é no painel do Supabase**, que é uma planilha no navegador.
Não há tela no app, de propósito: esses cadastros mudam raras vezes, e a
validação mora no BANCO (`unique`, `check`, FK), onde vale independentemente
de por onde a edição entrou. Depois de editar, o app pega na próxima abertura.

**Segurança, e o que já está provado por teste.** Só a `anon key` está no
código (`nuvem/rest.py`) — ela é pública por desenho e não abre nada sozinha;
a `service_role` ignora a RLS inteira e não pode aparecer no repositório, no
exe nem no CI. Toda tabela tem RLS ligada e política só para `authenticated`.
Medido contra o projeto de verdade: sem login, ler `conta` ou
`regra_fornecedor` responde **401**; criar conta responde **422
signup_disabled**; com login, 200. O cadastro público está desligado porque,
com ele aberto, qualquer um que clonasse o repositório viraria gente da casa.

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

**`nuvem/registro.py` está vazio de propósito.** Arquivo novo custa uma
release com exe novo, então o pacote inteiro nasceu de uma vez; o conteúdo da
Fase 3 (aportes lançados, NSA, retorno CNAB, envios) chega depois pelo
`codigo.zip`. **Lá não haverá cache**, e é a diferença dele para o
`cadastro.py`: o valor de gravar "isto já foi feito" é a resposta ser a mesma
nas duas máquinas no mesmo instante.

**Migrar de novo** (máquina nova, ou recomeçar): `python nuvem/migrar.py
--conferir` critica sem escrever; `--subir --email <você>` escreve e depois
relê para comparar campo a campo. Ele entra com LOGIN DE PESSOA e não com a
chave de serviço — um script que usasse a chave de serviço ignoraria a RLS e
não provaria nada sobre o caminho que o app percorre.
