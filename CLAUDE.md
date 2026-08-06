# Comprovantes — Mais Controle

App Windows (Python/tkinter, distribuído como .exe via PyInstaller) que separa,
renomeia e anexa comprovantes bancários nos pagamentos do Mais Controle ERP.
Usuários finais são leigos: praticidade acima de tudo. Repo público:
https://github.com/gdiascabral/comprovantes-mais-controle

## Regra de ouro: como uma mudança chega ao usuário

TODO push na `main` dispara o GitHub Actions (`.github/workflows/build.yml`), que:
1. gera `versao.txt` = `v1.0.<run_number>` (NÃO é commitado; criado na build);
2. monta `codigo.zip` (comprovantes_app.py + separar_renomear/*.py + anexar/*.py
   + versao.txt + motor_minimo.txt + icone.ico) — ~50 KB;
3. builda **um** exe — `Comprovantes Mais Controle.exe` (PyInstaller onefile,
   com Tesseract OCR embutido) — e publica a Release `v1.0.<run_number>` com
   o exe + codigo.zip. Os exes avulsos de Separar e de Anexar foram removidos:
   tudo vive em abas no app principal;
4. apaga releases antigas mantendo as **4 mais novas** (política de rollback).

O exe do usuário é dividido em **motor** (Python + libs + OCR + `motor.py` +
`atualizador.py`) e **código** (o resto). Ao abrir, o app baixa só o
`codigo.zip` novo (segundos, sem perguntar) e roda com ele. Portanto:

- Mudanças em `comprovantes_app.py`, `separar_renomear/`, `anexar/` →
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
- `comprovantes_app.py` — janela única: barra lateral (Separar e Renomear /
  Anexar Comprovantes / Conferência), tema Automático (lê o registro do
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
- `anexar/config.py` — URLs, tag, listas IGNORAR_TARIFAS/IGNORAR_APORTES;
  usa a pasta do exe quando congelado (sys.frozen). Tem também `diag()`, o
  registro em `diagnostico.log` usado por quem precisa degradar sem quebrar
  (captura de credenciais, login salvo, download de anexo, OCR da
  conferência) — engole o erro, mas deixa o motivo gravado.

## Restrições importantes (aprendidas a caminhadas)

- **Playwright sync = uma única thread.** Todo trabalho com o navegador roda
  em `AnexarFrame.exec` (ThreadPoolExecutor de 1 worker). Nunca tocar em
  `page`/`mc` fora dela (erro greenlet "cannot switch to a different thread").
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
- Testes de unidade com fixtures de texto (campos, parse_pdf, casar).
- Deduplicar utilitários (_fmt_dur, _norm/_sem_acento, LINK) num util.py.
- Centralizar seletores do ERP (mc_client.py) em constantes/config.
- Pinar versões-teto no requirements.txt.
- OCR em lote cruzando ARQUIVOS (hoje o pool é por arquivo; entrada com
  muitos PDFs de página única não aproveita o paralelismo).
