---
paths:
  - "relatorios/**"
---

# Arquitetura: relatorios/

> Trecho da seção "Arquitetura", movido do `CLAUDE.md` em 21/09/2026 sem mudar uma palavra.
> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI — este é o lugar deste texto agora.

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
