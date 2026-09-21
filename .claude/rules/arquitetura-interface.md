---
paths:
  - "comprovantes_app.py"
  - "widgets.py"
  - "**/*_frame.py"
  - "ferramentas/galeria.py"
---

# Arquitetura: janela e widgets

> Trecho da seção "Arquitetura", movido do `CLAUDE.md` em 21/09/2026 sem mudar uma palavra.
> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI — este é o lugar deste texto agora.

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
  versão aparece INTEIRA ("v2.0.201") em três lugares — título da janela,
  canto direito da barra e rodapé do menu. Até 14/09/2026 aparecia curta
  ("v2.0") com o número de build escondido numa `widgets.Dica`; o dono pediu
  o número inteiro de volta, porque é ele que diz de relance se a máquina já
  pegou a versão liberada (`_versao_na_tela`).
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
  **O meio da aba ROLA, e as pontas não** (`AreaRolavel`, 11/09/2026). No
  Anexar a 1920x1080 com a escala a 125%, os três cartões numerados já
  passavam da janela: a barra de ação saía cortada e o Registro sumia — o
  `_reservar_o_pe` de 03/09 não alcançava o caso, porque ali não há lista
  para ceder espaço. Hoje toda aba é: cabeçalho fixo; `corpo =
  widgets.AreaRolavel(self)` com os cartões numerados dentro (`Cartao(corpo,
  …)`); e a DOCA presa no pé por `corpo.encaixar(acao, self.reg)`, chamado
  UMA vez, no fim do `_build`, depois do `registro_elastico`. Início e
  Usuários rolam inteiros (`corpo.encaixar()`), e o menu lateral também rola.
  Quatro regras: (1) cartão novo de passo nasce em `corpo`, nunca em `self` —
  em `self` ele entraria no `pack` depois da doca e seria o primeiro a sumir;
  (2) como o `Cartao`, a área tem DOIS objetos (`self` é o interior, filho do
  Canvas; `moldura` é o que vai ao `pack` da aba), porque widget só é
  recortado pela janela-PAI; (3) a área só pede a sobra da tela quando tem um
  filho com `expand` (a lista que cresce) — sem ele, a sobra é do Registro;
  (4) a barra aparece por cima da margem direita dos cartões, sem tomar
  largura: tomando, o texto requebraria ao aparecer e ela podia piscar em
  laço. O Tk não avisa quando o tamanho PEDIDO do interior muda (ele tem
  altura fixa dentro do Canvas), então a área escuta o `<Configure>` dos
  filhos e confere a cada `VIGIA_MS` enquanto está na tela. Roda e Tab chegam
  por `bind_all` (`_roda_na_area`, `_foco_na_area`): Text e Treeview com o
  que rolar ficam com a roda; campo que recebe foco é trazido à vista — menos
  o foco que volta ao mesmo widget, que é o Alt+Tab e não pode puxar a lista
  de volta ao topo. **A roda não troca mais valor de `ttk.Combobox` em lugar
  nenhum do app**: `_instalar_roda` desfaz a ligação da classe, porque com a
  página rolando, passar o ponteiro por "Tipo" ou "Forma" trocava o valor em
  silêncio (a janela de contas novas já tinha o conserto local, pelo mesmo
  motivo). O Registro ganhou, no cabeçalho do cartão, "Copiar" e
  "Ampliar/Recolher" (60% da aba), e uma alça no alto que se arrasta; os três
  mexem só no piso em linhas. A Aportes passou a ter cartão de Registro, como
  as outras. Testes: `tests/test_rolagem.py`, e em
  `tests/test_registro_visivel.py` a barra de ação inteira nas onze abas e o
  Anexar com 36 contas carregadas — a tela do defeito.
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
