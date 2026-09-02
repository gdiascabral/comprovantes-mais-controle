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
  fosse; quem consertar faz em PR próprio. A busca da barra NÃO busca:
  `Ctrl+K` (`bind_all` → `barra.focar_busca`) leva o foco ao campo, e
  `barra.ao_buscar` está ligado ao `_focar_primeiro`, então o Enter ali só
  devolve o cursor ao primeiro campo da aba aberta. Ela está na tela porque o
  LUGAR dela é decisão de layout, e deixá-la para depois obrigaria a mexer de
  novo em tudo o que fica à direita e à esquerda dela; o que ela vai procurar é
  assunto de quem tiver um índice. O `ItemMenu` é `tk.Frame` e só escuta
  `<Button-1>`, `<Enter>` e `<Leave>`: ele não entra no Tab nem responde ao
  Espaço, o contrário da regra escrita neste mesmo arquivo para os cabeçalhos
  de grupo — quem só usa teclado alcança DIÁRIO e MENSAL e não alcança nenhuma
  das doze telas. Sete dos doze ícones do menu estão fora do BMP (📎 💰 🗓 📊 🏦
  📑 📤) e o Windows os desenha pela Segoe UI Emoji, colorida: o `foreground`
  que o `_pintar` do `ItemMenu` passa não alcança glifo colorido, e esses sete
  ficam idênticos nos dois temas. Os outros cinco (▦ ⬇ ✂ ✅ ⚖) são
  monocromáticos e seguem a cor — é por isso que o ● do pulso (U+25CF)
  consegue ser azul. E o `ComprovantesFrame` (Baixar Comprovantes) não expõe
  `ocupado()`, então o trabalho dele não acende o ● nem o chip; `_quem_trabalha`
  engole a falta do método de propósito ("aba sem o método: só não sinaliza"),
  então isso não dá erro — só não aparece.
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
  ser par.
  **O `atividade.jsonl` é o que permite ao Início não abrir o navegador.** Cada
  rotina, ao terminar, chama `registrar_atividade` com os números que ACABOU de
  apurar; o Início lê o arquivo e mostra. Arquivo e não banco: é histórico de
  UMA máquina, tem de continuar legível com a nuvem fora, e ninguém decide
  dinheiro por ele. JSONL porque escrever é sempre `append` — uma linha
  corrompida custa uma linha, não o arquivo — e `MAX_ATIVIDADE` = 400 põe teto,
  já que o Início o lê inteiro na abertura. `registrar_atividade` NUNCA levanta:
  o pior caso é o Início mostrar um evento a menos, e isso não pode parar
  trabalho nenhum.
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
  **O `Tk()` dessa fixture nasce dentro de `tcl_com_handles_proprios`.** No
  Windows o Tcl embrulha os handles padrão do processo, a captura de saída do
  pytest os fecha por fora a cada fase de teste, e o valor reaproveitado pelo
  Windows faz o `open` do `tclIndex` do Tk falhar em silêncio — daí
  `invalid command name "tk_focusNext"` numa rodada a cada cinco da suíte
  (02/09/2026). Parecia disputa de foco com o `focus_force`, e não era: o
  docstring da função e `tests/test_raiz.py` contam o resto. Teste de
  interface que morre com `invalid command name` num proc do Tk, ou num
  `source` de `.tcl`, é para desconfiar da captura antes do teste.
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
