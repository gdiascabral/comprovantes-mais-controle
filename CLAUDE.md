# Comprovantes — Mais Controle

App Windows (Python/tkinter, distribuído como .exe via PyInstaller) que separa,
renomeia e anexa comprovantes bancários nos pagamentos do Mais Controle ERP.
Usuários finais são leigos: praticidade acima de tudo. Repo público:
https://github.com/gdiascabral/comprovantes-mais-controle

## Regra de ouro: como uma mudança chega ao usuário

TODO push na `main` dispara o GitHub Actions (`.github/workflows/build.yml`), que:
1. gera `versao.txt` = `v1.0.<run_number>` (NÃO é commitado; criado na build);
2. monta `codigo.zip` (comprovantes_app.py + util.py + widgets.py +
   ativacao.py + separar_renomear/*.py + anexar/*.py + aportes/*.py +
   relatorios/*.py + pagamentos_dia/*.py + extratos_sicoob/*.py +
   conciliacao/*.py + conciliacao/erp/*.py + versao.txt + motor_minimo.txt +
   icone.ico) — ~50 KB.
   **Pasta nova de aba OU arquivo novo na raiz = linha nova aqui**, senão o
   import falha no usuário e o app não abre. Vale para os dois: `widgets.py` e
   `ativacao.py` são de raiz e precisaram entrar um a um;
3. builda **um** exe — `Comprovantes Mais Controle.exe` (PyInstaller onefile,
   com Tesseract OCR embutido) — e publica a Release `v1.0.<run_number>` com
   o exe + codigo.zip. Os exes avulsos de Separar e de Anexar foram removidos:
   tudo vive em abas no app principal;
4. apaga releases antigas mantendo as **4 mais novas** (política de rollback).

O exe do usuário é dividido em **motor** (Python + libs + OCR + `motor.py` +
`atualizador.py`) e **código** (o resto). Ao abrir, o app baixa só o
`codigo.zip` novo (segundos, sem perguntar) e roda com ele. Portanto:

- Mudanças em `comprovantes_app.py`, `separar_renomear/`, `anexar/`,
  `aportes/`, `relatorios/`, `pagamentos_dia/`, `extratos_sicoob/` →
  chegam sozinhas ao usuário no próximo abrir. Só commitar e esperar a build.
- Mudanças em `motor.py`, `atualizador.py`, dependências novas no
  `requirements.txt` ou `--collect-all` no workflow → exigem exe novo.
  **Obrigatório**: subir `motor_minimo.txt` para a versão da release que sai
  (v1.0.<run_number+1>), senão o código novo roda em motor velho e quebra.
  O app então oferece o download completo (~150 MB) com progresso.
- Build leva ~8–10 min. Commits só de README/LICENSE não disparam build
  (paths-ignore).

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
  MENSAL (Relatório Mensal, Extratos Sicoob). O estado de cada grupo fica em
  `preferencias.json`, e selecionar uma aba de grupo fechado o abre — senão a
  aba ficaria destacada e invisível. Tema
  Automático (lê o registro do
  Windows)/Claro/Escuro salvo em `preferencias.json`, versão no título e
  no rodapé da barra. Tema sv-ttk; frames expõem `aplicar_cores(escuro)`.
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
- `pagamentos_dia/pagamentos_frame.py` — aba Pagamentos do Dia, em 2 passos
  (Buscar / Gerar). Compartilha navegador e thread do Anexar. O passo separado
  existe porque quem confere quer VER a lista de contas antes de gerar, e cada
  rodada custa uma sessão do ERP (que só aceita uma por usuário). Contas
  "APENAS LANÇAMENTO/AJUSTE" aparecem desmarcadas, não escondidas. As chaves
  Pix dos avisos "PAGAR PARA" ficam em `pix_reembolso.json` ao lado do exe —
  é CPF de gente, não entra no repositório.
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
- Endurecer a senha de ativação com PBKDF2 no lugar do SHA-256 puro (sal
  público + senha adivinhável é fraco contra dicionário; hoje o custo de
  atacar não compensa, porque o marcador só libera o app nesta máquina).

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
- **Senha de primeira utilização** (`ativacao.py`): só o SHA-256 de
  (sal + senha) fica no código — o repositório é público. O marcador
  `ativacao.dat` é por máquina; trocar a senha é trocar o hash, e todo mundo é
  perguntado de novo.
