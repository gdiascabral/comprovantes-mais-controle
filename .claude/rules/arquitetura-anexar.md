---
paths:
  - "anexar/**"
  - "tests/test_matcher.py"
---

# Arquitetura: anexar/

> Trecho da seção "Arquitetura", movido do `CLAUDE.md` em 14/09/2026 sem mudar uma palavra.
> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI — este é o lugar deste texto agora.

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
  **A aba da pessoa (08/09/2026).** O ERP aceita uma sessão por usuário, mas
  abas do MESMO Chrome dividem a sessão (o token do Firebase mora no
  IndexedDB do perfil, não na aba). Então a pessoa pode usar o Mais Controle
  numa aba dela, no Chrome do app, enquanto o robô trabalha na dele — e o
  que o app precisa garantir é uma coisa só: **o robô nunca adota uma aba que
  não seja dele**. `_minhas` guarda as abas do robô; `_nova_aba` (evento
  "page" do contexto) classifica cada aba nova pelo `opener()`: aberta a
  partir de uma aba do robô (`stateGoNewTab`) é do robô, qualquer outra
  (Ctrl+T, o botão, o chrome.exe por fora) é da pessoa. `_aba_logada` só
  olha `_abas_do_robo()`. Medido com Playwright 1.61 + Chrome 152: com a
  aba da pessoa na frente, o robô navega, clica, digita e tira print sem
  roubar a frente — mas **`new_page()` traz a aba nova para a frente**, por
  isso o robô só cria aba quando a dele foi fechada (`_garantir_aba_do_robo`).
  Três consequências que não são óbvias: (1) **downloads da aba da pessoa**:
  com `accept_downloads=True` o Playwright toma conta de TODO download do
  contexto — o boleto que ela baixou ia para uma pasta temporária com nome
  aleatório e sumia. `_baixar_para_a_pessoa` salva na Downloads dela
  (`util.pasta_downloads`, que pergunta ao Windows). (2) **No Playwright
  síncrono os eventos só chegam DURANTE uma chamada à API**: com o robô
  parado, o download (e o "fechou a janela") ficariam na fila por horas.
  `AnexarFrame._pulsar_navegador` chama `MCClient.pulsar()` a cada ~1 s com
  o navegador livre — sem contar como trabalho. É também o que mantém
  `mc.fechado` fresco, e `fechado` (evento "close") é o que a thread da
  interface pode consultar, já que `vivo()` fala com o navegador. (3) **O
  botão ↗ Minha aba no ERP** (`AnexarFrame.abrir_minha_aba`, na barra de
  cima, e o "sim" do aviso "Navegador ocupado") entra por caminhos diferentes:
  com o robô trabalhando a thread está tomada, então a aba entra POR FORA —
  `mc_client.abrir_aba_por_fora` chama o chrome.exe com o mesmo
  `--user-data-dir`, e o Chrome já aberto abre a aba e vem para a frente. Só
  com o Chrome do app vivo: sem ele, isso abriria um Chrome comum no perfil do
  app e a abertura seguinte falharia com "perfil em uso".
  **O crash do Chrome 152** (medido no mesmo dia, `tests/test_aba_da_pessoa.py`):
  o Chrome — e o Edge 152 — morrem com violação de acesso no PRIMEIRO download
  de um perfil que já baixou algo numa abertura anterior pelo Playwright.
  Perfil novo baixa; o mesmo perfil reaberto cai (exit 0xC0000005) em qualquer
  forma de download; apagar o `History` (onde vive a tabela de downloads) faz
  voltar; `downloads_path` fixo e desligar a bolha de downloads NÃO resolvem;
  o Chromium embutido do Playwright não tem o defeito, mas custaria ~150 MB
  por máquina. `util.limpar_historico_de_downloads(perfil)` roda ANTES de
  todo `launch_persistent_context` que baixa alguma coisa — ERP, Inter e
  Sicoob. Apaga o arquivo inteiro (ler o SQLite pediria `sqlite3`, que o exe
  não embute), e num perfil que só o app usa o histórico de navegação não faz
  falta.
  Anexa via UI (⋮ → Editar pagamento → arquivo → tag "Comprovante").
  Seletores do ERP estão nos blocos JS deste arquivo. Timeouts generosos
  (45–60 s) + `resetar()` antes de retentar (ERP fica lento em lote).
  **Desde 08/09/2026 o comprovante sobe pela API, e a tela é o plano B.**
  `mc_api.MCApi.anexar_por_api(paidId, pdf)` faz, de dentro da página logada
  e com os cabeçalhos de anexos já capturados: `GET /attachments/v2` do
  sub-pagamento (já tem arquivo de mesmo nome ou mesmo tamanho → `ja_anexado`,
  sem subir), `GET /attachments/tags` (o id de "Comprovante", sem acento nem
  caixa, uma vez por rodada), `POST /attachments/v2/batch` com
  `entityOrigin=PAID` e o `paidId` — o comprovante mora no SUB-pagamento, não
  na parcela —, `PUT` cru do binário na URL S3 pré-assinada (só
  `content-type`; cabeçalho do ERP quebra a assinatura) e o `GET` de prova, que
  tem de listar o arquivo para sair `anexado`. Quem decide o caminho é
  `anexar_comprovantes.anexar_um`, com a chave `config.ANEXAR_POR_API`: a tela
  só entra em `erro:sem_credencial` e `erro:batch:*` — os desfechos em que
  NADA subiu, porque o ERP recusou antes de o arquivo sair. Em
  `erro:upload:*` (o batch criou o registro e o PUT falhou) e em
  `erro:nao_confirmado` (o PUT deu 2xx e a listagem não mostra) a tela NÃO
  entra: o arquivo pode estar lá, e o diálogo anexaria de novo — comprovante
  em dobro se desfaz à mão no ERP, comprovante relatado como erro se confere
  abrindo o lançamento. O POST nunca se repete daqui; a retentativa com
  `resetar()` é só da tela. O modo "Por lista" só traz o link da parcela (sem
  `paidId`) e continua pela tela. Coberto por `tests/test_anexar_por_api.py`.
- `anexar/anexar_comprovantes.py` — tela Anexar: 2 passos (Carregar contas /
  Casar e anexar) — "Abrir o Mais Controle" saiu do fluxo e virou botão
  auxiliar, porque com a senha guardada o app entra sozinho.
  Pausar/Parar, cronômetros ⏱, janela de
  resolver DÚVIDAS (`_janela_duvidas`), em LISTA + DETALHE: em cima, uma
  linha por pagamento em dúvida (situação, valor, data, conta, favorecido,
  nº de PDFs); embaixo, o detalhe de UM — favorecido, descrição inteira,
  centro de custo, nº doc + OC/NF, categoria e conta — e os candidatos
  numa tabela ordenada pelo score, com o que bateu em cada um (OC/NF,
  centro de custo, data) e botões de abrir o PDF e o lançamento. Enter (ou
  "Próxima em dúvida") pula para o próximo sem escolha; escolher um PDF que
  já estava em outro pagamento o MUDA de lugar, com aviso; sair com
  escolhas feitas pergunta antes de descartá-las. Quem grava é
  `_aplicar_escolhas`, função pura (um PDF, um pagamento). **Até 11/09/2026
  era um bloco de widgets por dúvida num Canvas rolável, e isso não
  escala**: cada bloco que entra faz o Canvas recalcular a geometria dos
  anteriores — 184 dúvidas davam 2.032 widgets e 86 s só de geometria
  (medido com a janela fora da tela), o "Não está respondendo" do Windows.
  Lista que cresce com o dado é UMA Treeview, nunca N widgets num Canvas;
  `tests/test_duvidas_anexar.py` confere que a janela tem os mesmos
  widgets com 3 ou 300 dúvidas. O mesmo detalhe vai para a aba DUVIDA do
  relatório (`_resumo_cands`).
  Botão Abrir relatório, modo "Por lista" (.csv/.xlsx; completa
  ".pdf" ausente). Relatório Excel: ANEXADOS/DUVIDA/SEM PAR.
- `anexar/conferencia.py` — auditoria pós-anexo: lista pagos SEM anexo no
  período e, opcionalmente, baixa cada PDF anexado e confere se o VALOR
  (e data) aparecem no texto (OCR se preciso) → aba DIVERGENTES.
  Compartilha sessão/thread da tela Anexar (`anx.garantir_sessao()`).
- `anexar/config.py` — URLs, tag, listas IGNORAR_TARIFAS/IGNORAR_APORTES;
  usa a pasta do exe quando congelado (sys.frozen). Tem também `diag()`, o
  registro em `diagnostico.log` usado por quem precisa degradar sem quebrar
  (captura de credenciais, login salvo, download de anexo, OCR da
  conferência) — engole o erro, mas deixa o motivo gravado. Desde o PR #8 ele
  **delega para `util.log()`** em vez de abrir o arquivo à mão: mesma
  assinatura, mesmos chamadores, e o `ARQUIVO_DIAG` passou a sair de
  `util.pasta_base()`. O `ARQUIVO_LOG` (`log_anexos.csv`) ainda não — é o
  último caminho aqui calculado pela pasta do módulo.
