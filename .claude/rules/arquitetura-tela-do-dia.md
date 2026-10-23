---
paths:
  - "tela_do_dia/**"
  - "pagamentos_dia/leitura_do_dia.py"
  - "tests/test_tela_do_dia*.py"
  - "tests/test_leitura_do_dia.py"
---

# Arquitetura: tela_do_dia/ (aba "Pagamentos do dia")

> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI.

A aba nova do grupo DIÁRIO (entrega 1 da especificação de 21/10/2026, passos 1
a 4): saldos, o que vai sair, os aportes e o Excel do dia numa tela só. As
abas "Remessa/Retorno" e "Saldo de pagamentos" continuam no menu, sem mudança,
até esta estar provada. O papel `aprovador` NÃO a vê (`nuvem/usuarios.py`,
`ABAS_DO_PAPEL`).

**Nada desta aba escreve no Mais Controle.** O único caminho até o ERP é a aba
Aportes: as operações entram na lista "A lançar" dela e o dono confere e clica
"Lançar no Mais Controle" lá.

## Quem decide o quê

Toda regra mora num módulo puro, com teste sem janela; `frame.py` é a tela
fina (lê o ERP na thread do navegador, mostra, pergunta, grava o dia). A
máquina do dono não roda teste de tela sem liberação, então **regra nova vai
para um módulo puro, nunca para o frame** — a tela só tem a guarda por AST de
`tests/test_abas_em_paralelo.py` (`avisar_se_ocupado(aba=)` = `submeter(dona=)`).

| Módulo | Decide |
|---|---|
| `valores.py` | dinheiro digitado e mostrado; o float da Remessa vira Decimal na entrada (`de_float`); "1500.50" ambíguo é recusado pela régua de `aportes.regras` |
| `saldos.py` | passo 1: sistema × banco por conta; o ajuste guarda o original e acusa quando o ERP mudou depois dele; saldo do dia = banco (digitado, senão lido do Sicoob), senão sistema; `nota_banco` diz por que o Sicoob não foi lido e `banco_mudou` acusa o lido que mudou depois do ajuste |
| `saldo_sicoob.py` | passo 1: qual conta do Sicoob é cada linha (`agendamentos_sicoob.conta_sicoob`, o caminho da Remessa), o lido, a hora, o recado de falha, o JSON `DD MM - saldos do sicoob.json` |
| `sicoob_na_tela.py` | o "Reler Sicoob" e a frase da hora: thread própria daemon, fila, botão pela regra dos botões da tela |
| `pagamentos.py` | passo 2: por linha do painel, o que VAI SAIR, o JÁ ENVIADO (soma no a pagar) e o que está BLOQUEADO; conta sem linha no painel vai para `fora`, com o motivo, em vez de sumir |
| `aportes.py` | passo 3: mínimo, sugestão da aba Regras, conta-mãe primeiro com alerta forte, movimentos «À MÃO» no M (entra) e no E (sai) |
| `para_aportes.py` | os aportes definidos viram `Operacao` da aba Aportes, com pendências (não foram) e avisos (foram, confira) |
| `excel_do_dia.py` | passo 4: o MODELO.xlsx com os números da tela |
| `erp_do_dia.py` | os saldos do ERP, sempre pelo Chrome do app |
| `dia_de_trabalho.py` | o JSON do dia |
| `decisoes.py` | o que a tela faria com `if`: "—" de conta sem saldo, movimento à mão válido, quando o Excel e os geradores recusam, quais operações seguram |
| `conferencia.py` | passo 2 editável: eventos da nuvem → decisão por alvo (`dobrar`); liberar, desmarcar, editar, desfazer, remover à mão; validações (motivo, forma de pagar, reembolso, à mão); o "tem certeza?" (`pede_certeza`); o aviso de casamento do Anexar |
| `geracao.py` | o `Resultado` que planilha, HTML e remessa leem: o da Remessa + liberados, editados e à mão (status LIBERADO / EDITADO / À MÃO); `para_a_remessa` tira o à mão |
| `lancamento_do_erp.py` | o link do lançamento (só leitura, pelo Chrome do app): fornecedor, CC, NF, OC, conta, valor em aberto, se já está pago |
| `agendados.py` | passo 6 e "a confirmar": a foto de cada pagamento, a situação (o que se prova e o que espera resposta), quando reler, validação da resposta |
| `lista_diretor.py` | passo 7: nome curto por conta, ordinais, ordem de ontem como sugestão, o texto do WhatsApp |
| `nuvem_do_dia.py` | a leitura orquestrada: nuvem + releitura do ERP + retorno do banco, sem tela (dublês nos testes) |
| `passo2.py` | regras puras do passo 2: que botão vale em cada linha, edição, a pergunta ao gerar com a nuvem em erro, gravar-e-reler |
| `passo67.py` | regras puras de "Agendados a confirmar", "Marcar agendados" e "Lista do diretor": marcas, confirmação do "Pago", `reler_tudo` |
| `janelas.py` | os diálogos finos (motivo, edição, à mão, resposta, nome curto); a regra que valida mora nos módulos acima |

## "Vai sair" = entra e nasce marcada

Quem sabe o que vai sair é a apuração da Remessa, não esta aba: vai sair é a
linha que ENTRA na confirmação e nasce marcada
(`confirmacao.marcada_de_inicio` — o já enviado nasce desmarcado, o rejeitado
volta marcado). Bloqueado = não apto. Planilha, HTML e Remessa saem do
`confirmacao.remontar(entradas, ids_que_nao_saem)` — os mesmos que a janela da
Remessa desmarcaria sozinha.

**"Não gera de novo" não é "não sai da conta".** O já enviado em remessa viva
(ainda em aberto no ERP) fica em `ja_enviados`: fora de planilha, HTML e
remessa, mas SOMANDO no "a pagar" (coluna D do Painel, D do Excel e o aporte
mínimo), porque o banco ainda vai debitá-lo. A tela o mostra como "já enviado
(soma no a pagar)", separado dos bloqueados. Revisão final de 21/10/2026: fora
do a pagar, o mínimo saía baixo e a conta podia fechar negativa.

## Saldo do Sicoob (entrega 4, 22/10/2026)

A coluna BANCO das contas do Sicoob vem lida do SicoobNet, só leitura
(`extratos_sicoob/saldo.py`); no alto do passo 1, "Sicoob lido às HH:MM" e o
botão "Reler Sicoob" (`sicoob_na_tela.LeitorSicoob`). O frame só cria o
leitor no cartão 1 e o chama em quatro pontos: `_recalcular` (`aplicar`),
fim do `_receber_leitura` (`ler_se_faltar`), `_ligar_botoes`/`_limpar`
(`ligar`) e `fechar`.

- **O digitado vale sobre o lido.** A spec trata o saldo do banco como valor
  editável "inclusive para simular", com o original visível: o lido é o
  original, o digitado é o ajuste do dia (`banco_usado`). Se o Sicoob ler um
  valor DIFERENTE do que havia quando o ajuste foi feito, a linha fica em
  âmbar: "vale o digitado; o banco leu R$ X depois do seu ajuste".
- **O Buscar lê o Sicoob só sem leitura de hoje** (`ler_se_faltar`, ao fim do
  Buscar, quando já se sabe quais linhas são do Sicoob); com leitura do dia,
  vale a hora mostrada e o "Reler Sicoob" refaz.
- **Reler substitui a leitura inteira**: conta que falha fica "Sicoob não
  lido: motivo" com o banco VAZIO, nunca o valor velho calado nem R$ 0,00.
  A hora é a da conta lida há mais tempo; parcial diz "N de M contas".
- **Dois acessos do Sicoob** (prova ao vivo 22/10/2026: 19 lidas, 4 de
  OUTRO acesso, com outro QR Code). Sobrou conta "não aparece neste login"
  no fim da leitura: a tela pergunta (`askyesno`, padrão sim, pela fila —
  `_perguntar_outro_acesso`; a thread espera, e fechar o app responde não)
  "N contas são de outro acesso do Sicoob (…). Entrar com o outro acesso
  agora?". Sim: o Chrome do Sicoob do app (o MESMO perfil) fecha e abre de
  novo, espera o login do dono e lê SÓ as que faltaram
  (`saldo.ler_em_dois_acessos`). É o caminho já provado de
  `baixar_em_varios_logins`: o app não tem um "sair" do SicoobNet, e nada
  digita senha nem clica em aceite/2FA. As duas leituras viram UMA, cada
  conta com `acesso` (1 ou 2, guardado no JSON); a hora continua a da conta
  lida há mais tempo. Não: ficam "não lido", como antes. Segundo login que
  falha não perde o primeiro (as que faltavam levam o porquê); a que não está
  em nenhum dos dois diz isso. **Chrome que volta no MESMO acesso** (a
  sessão ficou no perfil; a lista de contas do 2º login é igual à do 1º, pelos
  dígitos): não lê de novo; as que faltavam ficam "não lido" com "o Chrome
  voltou no mesmo acesso do Sicoob: saia do SicoobNet (botão Sair) e clique em
  Reler Sicoob para entrar com o outro acesso" (`saldo.MESMO_ACESSO`). A
  lista de contas é lida UMA vez por login.
- **Outro banco fica digitado** (spec: "só Sicoob"). Duas linhas na mesma
  conta do Sicoob, ou linha que diz SICOOB e o cadastro não resolve, não são
  preenchidas e dizem por quê.
- **A leitura do dia é guardada** em `<RAIZ_SAIDA>/<ano>/<MÊS>/DD MM - saldos
  do sicoob.json`, arquivo PRÓPRIO (não disputa o dia de trabalho); de outro
  dia é ignorado, estragado vira aviso.
- **`ROTA_SALDO = ""` desliga tudo sem abrir o Chrome**: o rótulo diz
  "leitura ainda não ligada — digite o saldo do banco" e o Reler explica.
  Desde 22/10/2026 o endereço está medido e ligado.
- **Thread própria, nunca a do ERP**: o `SicoobClient` nasce e morre em
  `LeitorSicoob._t_ler` (`Thread` daemon, nome `sicoob-saldo`), e a tela só
  recebe pela fila. O perfil do banco é o da instalação, aberto só como o app
  abre.
- **Botão**: apagado sem leitura do ERP, lendo o ERP ou gravando na nuvem
  (`ligar(b.dia)`, a mesma regra de `passo2.botoes`) e enquanto lê o Sicoob;
  `reler` também recusa durante a gravação.
- **Um perfil do banco, uma sessão**: a leitura recusa com os Extratos ou o
  "Conferir agendamentos" da Remessa rodando (`outros_no_sicoob`, ligado no
  `comprovantes_app.py`), e o "Conferir agendamentos" passa a recusar
  enquanto esta aba lê, com o nome dela na mensagem
  (`LeitorSicoob.OCUPADO`). É a única mudança de comportamento da Remessa. A
  barra lateral mostra o ● em "dia" durante a leitura. O contrário também
  vale: "Baixar extratos" (Extratos Sicoob) e "Começar" (Baixar comprovantes,
  só quando há conta do Sicoob marcada) recusam enquanto esta aba lê, com o
  mesmo nome na mensagem — o `sicoob_ocupado` de cada uma é ligado no
  `comprovantes_app.py` e conferido antes de mexer em qualquer botão; sem ele
  (testes antigos), nada muda (`tests/test_sicoob_disputado.py`).

## Leitura: duplicação conhecida

`pagamentos_dia/leitura_do_dia.py` orquestra as MESMAS regras da Remessa
(`montar_registros`, `analisar_remessa`, `grupos_da_confirmacao`) sem
reescrever nenhuma, mas a sequência de busca (`anexos_a_ler`, `baixar_textos`,
`ler_pagamentos`) é cópia declarada de `PagamentosDiaFrame._t_buscar` /
`_anexos_a_ler` / `_baixar_textos` / `_t_apurar`. Ela se resolve quando o frame
da Remessa passar a chamar estas funções em vez das cópias dele — o frame
estava em uso por outro branch quando esta aba nasceu, e por isso a única
mudança nele foi `receber_apuracao`. Até lá, regra nova de leitura vai nos
DOIS lugares.

A tela passa à leitura os mesmos argumentos da Remessa
(`reembolso.carregar`, `regras_pagamento.carregar_fornecedores` e
`carregar_confirmar`, `_carregar_mapas`, `_historico`). **Leitura interrompida
não monta nada**: não há `por_conta`, nem Excel, nem passagem para a Remessa —
a tela pede para buscar de novo. Sem lançamentos no período (`entradas is
None`), o Excel pode sair (a pagar zero é verdade), mas planilha, HTML e
Remessa recusam.

**Campo de datas DE/ATÉ** (pedido do dono, 22/10/2026, revendo a decisão de
21/10 de não ter): no topo do cartão 1, `widgets.CampoData` como na
Remessa/Retorno, mais o botão "Hoje". Os campos nascem com
`sugerir_periodo(hoje)` (`decisoes.textos_sugeridos`) e o Buscar lê o que
está neles (`decisoes.periodo_da_busca`: invertido troca, data inválida
recusa com recado). **Os campos ainda com a sugestão que o APP pôs, de outro
dia** (app aberto de um dia para o outro), **viram a sugestão de hoje** —
ninguém escolheu ontem; a comparação é pelo TEXTO, e não por `trace` da
variável, porque o `CampoData` reescreve a mesma data ao perder o foco.
**O dia de trabalho é o ATÉ** (`periodo.fim`): o JSON do dia, a nuvem do
dia (liberações, agendados, lista do diretor), a data dos aportes e o Excel
são desse dia, e continuam coerentes com um período escolhido. **O Sicoob só
é lido quando o ATÉ é hoje** (`saldo_sicoob.recusa_pela_data`): o saldo
lido é o de AGORA, e gravá-lo no arquivo de outro dia seria mentir — com o
ATÉ noutro dia, o Reler recusa com o recado, o automático do Buscar só
escreve no Registro, a leitura já guardada daquele dia (se houver) continua
valendo, e o rótulo do período diz "dia de trabalho DD/MM (não é hoje: o
saldo do Sicoob não é lido — digite o do banco)" (`periodo_na_tela(p,
hoje)`). É a mesma regra que já cobria a virada da meia-noite.
**Revisão do pacote (22/10/2026): o saldo do ERP também é o de agora.** O
Buscar recusa ATÉ depois de hoje ("não dá para buscar o futuro") e período
de mais de 31 dias. Com o ATÉ antes do dia em que os saldos foram lidos
(`_lido_no_dia`), o Excel do dia e o "Mandar para a aba Aportes" perguntam
primeiro, padrão NÃO: "O saldo é o de agora, não o de DD/MM. Gerar (Mandar)
mesmo assim?" (`decisoes.pergunta_saldo_de_agora`), e o rótulo do período
diz que os saldos (sistema e Sicoob) são os de agora. Sem
calendário de feriados, a tela NÃO avisa nada sobre o dia anterior; no dia
seguinte a um feriado, o dono escolhe o período.


## Leitura e boletos somados (entrega 5)

A tela liga `Entradas.dividir_boletos`; a Remessa, lendo sozinha, não (teste
por AST). Para dividir, a leitura lê o título no ERP só das linhas "vários
boletos" (`titulos_a_dividir` → `ler_titulos_no_erp`, falha fechada, só GET) e
remonta uma segunda vez. O resultado que a Remessa recebe da tela vai por
`geracao.para_a_remessa(geracao.resultado_da_tela(...))`, com os liberados
preservados: a divisão acontece DEPOIS deles. Regras de dividir, `parte_linha`,
id do HTML e baixa: ver "Lançamento dividido em N boletos" abaixo e
`arquitetura-pagamentos-dia.md` (`boletos_somados.py`).

## Saldos pelo Chrome do app

Regra do dono (14/10/2026): nada de `POST /users/login` por HTTP, que derruba a
sessão do Chrome. Central ligado: a sessão do porteiro (`Sessao.logar("", "")`,
que, se o central sumiu no meio, levanta em vez de cair no login). Central
desligado: a MESMA aba do robô que leu os pagamentos (`mc_api._fetch_json`).
**Central: erro do ERP na 1ª leitura esquece a sessão guardada e lê UMA vez
de novo** (`erp.sessao.esquecer_central`; prova ao vivo 21 e 22/10/2026: com o
Chrome do app logando no ERP na mesma rodada, a `SessaoPelaPagina` guardada em
`_CENTRAIS` ficava com a autenticação velha e o dia não era lido). A 2ª falha
sobe com o motivo dela; erro que não é do ERP não tenta de novo. Só se
esquece a sessão que FALHOU (`SessaoApi._sessao`, ou `erro.sessao` do porteiro
sem token), por identidade: a que a Conciliação acabou de recriar fica.
Erro do ERP vira `ErpError`, nunca saldo zero; `acessos.json` estragado falha
FECHADO. Conta sem saldo mostra "—" no mínimo e no saldo final, com situação
"erro"; o Excel recusa quando `validacao.exigir_todos_os_saldos` está ligado
(saldo do banco digitado supre o do sistema) e pergunta quando não está.

## O JSON do dia

`<RAIZ_SAIDA>/<ano>/<MÊS>/DD MM - dia de trabalho.json`, ao lado do Excel do
dia. Guarda os ajustes de saldo, o valor por aportador, os movimentos à mão e o
que já foi mandado para a aba Aportes (chave `destino|aportador` → VALOR
mandado, em Decimal; a subconta de investidor é `subconta:<número>|<destino>`
com o total — ver abaixo). Arquivo ausente = dia vazio; ilegível ou de outra data
LEVANTA, e aí a tela não grava nada (sobrescrever apagaria o que a pessoa fez)
e **não manda nada para a aba Aportes** (sem o arquivo não se sabe o que já
foi mandado hoje). **Os ajustes de saldo, a simulação e `enviados_aportes` continuam aqui, no JSON, de propósito** (entrega 2, 22/10/2026): o ajuste é rascunho que vale só para o dia, não decide o que é pago nem vai a banco ou ERP, muda várias vezes por dia (seria UPDATE numa base que é só de acrescentar), já guarda o original e o `quando`, e já falha fechado. O que decide o que SAI da conta (liberação, edição, à mão, agendado, lista do diretor) vai para a nuvem — ver "Conferência editável" e as seções seguintes.

## Aporte não se repete

Item já mandado hoje vira pendência, mesmo com o valor corrigido (300 → 350
viraria 650 no ERP se a primeira já estiver lançada). **Nunca** gravar carimbo
de hora em `enviados_aportes` (o JSON passaria a falhar na leitura) e nunca
oferecer "mandar de novo" — corrige-se na aba Aportes. Conta sem saldo do
sistema: a tela pergunta antes e segura as operações se o dono disser não.
`marcar_enviados` marca por IDENTIDADE do objeto, só o que a aba Aportes
aceitou.

**O registro é gravado ANTES de entregar** (`para_aportes.enviados_apos`): a
tela anota todas as mandadas, grava o JSON e só então chama
`receber_operacoes`; as recusadas são desmarcadas e gravadas de novo. Se a
primeira gravação falhar, NADA vai (erro na tela); se a segunda falhar, o
arquivo fica com as recusadas como mandadas — o lado seguro. Nos dois casos a
sessão recusa novos envios (`_dia_bloqueado`) até o próximo Buscar. Antes, a
falha ao gravar depois de mandar era calada, e o próximo Buscar esquecia o
envio (aporte em dobro).

O já mandado que **não está mais na lista da aba Aportes** (app fechado,
"Limpar tudo", já lançado e retirado) muda de recado: "não está mais na aba
Aportes — já lançou? confira no ERP antes de digitar de novo"
(`para_aportes.ainda_na_aba`, por pagador, recebedor e data).
A data das operações é a do dia de trabalho (`periodo.fim`), nunca a do
relógio: tela aberta depois da meia-noite mandaria com outra data e anotaria
no arquivo de outro dia.

## Movimentos à mão, distribuição e investidores numa linha só (item A, 22/10/2026)

O cartão "Movimentos à mão" tem três botões: aporte que entra na mãe,
transferência entre contas e **distribuição de lucros** (conta do painel →
quem recebe, `dia.distribuicoes`, chave `distribuicoes` do JSON do dia).
**A lista "Para"** (`decisoes.socios_do_cadastro`, dono 23/10/2026: a SPE
distribui lucro para a empresa sócia, que é conta do PAINEL, e ela "não
apareceu") tem dois grupos, cada um em ordem alfabética: primeiro as
PESSOAS do cadastro da aba Aportes (sem conta no ERP, ou aportador da aba
Regras; sem cara de empresa), depois as EMPRESAS do cadastro e as contas do
painel, menos a própria origem (a lista muda quando a origem muda). A
"cara de empresa" (LTDA, SPE, HOLDING…) só ORDENA, não tira ninguém — o
filtro de 22/10 (commit e55fdb3) tirava justamente a empresa sócia. A conta
que está no painel E no cadastro (pelo nome, nome oficial ou CONTA do ERP,
`decisoes.cadastro_da_conta`) aparece UMA vez, pelo rótulo do painel: é ele
que a tela e o SUMIF do Excel somam no destino. A subconta de investidor
nunca entra. `nova_distribuicao` recusa a própria origem e troca a conta do
painel escrita com outra caixa pelo rótulo exato (o SUMIF ignora
maiúsculas; a tela não).

A distribuição SAI da origem (`AporteDaConta.distribui`: soma no mínimo e
tira do saldo final); **para outra conta do painel ela também ENTRA no
destino** (`entra_a_mao`, como uma transferência), senão o painel fecharia
errado. Vai para a seção «À MÃO» do Excel DEPOIS dos movimentos (B origem,
C quem recebe, H valor: o E do Painel a soma; o M só acha linha quando quem
recebe é conta do painel — e aí a tela também soma) e conta no limite de 20
linhas. O HTML a mostra de → para como os outros movimentos. O "Mandar para
a aba Aportes" a leva como **Distribuição de Lucro**, com o modo do cadastro
(sócio sem conta → Só pagamento; as duas pontas com conta → Pagamento +
Recebimento). Conta do painel casa no cadastro pelo nome e, se não achar,
pela CONTA do ERP do cadastro (`para_aportes._da_conta_no_cadastro`, um só
candidato). Pendências claras: origem no cadastro SEM conta do ERP (a
distribuição sai dela, e "Só recebimento" lançaria só a entrada) e destino
que é conta do painel (`operacoes(contas_do_painel=)`) SEM conta do ERP no
cadastro (o dinheiro entra nela, e "Só pagamento" lançaria só a saída).
Destino conta do painel sem saldo do sistema ganha o aviso de sem saldo,
como a origem. O mesmo par no dia vira UMA operação somada, com chave
própria de "já mandado" (`para_aportes.chave_da_distribuicao`).

**Aportador composto na aba Regras** ("Fulano/Beltrano"): nunca se casa pelo
primeiro nome (há aportadores diferentes com o mesmo primeiro nome). Destino
que é subconta de investidor no cadastro (número no rótulo ou na conta do
cadastro) vira UMA operação "Aporte de Investidor" daquela subconta,
dividida pelo cadastro, com um aviso listando os investidores de lá — desde
que a quantidade de nomes bata. Senão é pendência que diz o que cadastrar
(Novo cadastro → Subconta de investidor, ou um aportador por linha na aba
Regras com o nome completo). Só vale para regra de tipo **aporte**: composto
com outro tipo é pendência (A5). **O já mandado da subconta é pelo NÚMERO**
(`para_aportes.chave_da_subconta`, revisão de dinheiro de 22/10/2026, A4),
na linha composta e nas linhas por investidor, que são a mesma operação: a
mandada por uma porta segura a outra, com qualquer rótulo de destino. As
chaves antigas do JSON do dia (`destino|Fulano/Beltrano` e
`destino|<investidor>` cujo destino é a subconta) continuam lidas como já
mandado (`_ja_da_subconta`). **Transferência da aba Regras** não vai para a
aba Aportes e não é pendência: `Envio.informativos`, "transferência entre
contas: lance no banco; não é aporte", no Registro sem o "[!]" — também
com destino em subconta (o tipo é olhado antes da subconta).

O HTML dos pagamentos leva TODOS os movimentos definidos do dia que não são
pagamento de conta como linhas só informativas (`decisoes.movimentos_do_dia`
→ `html_pagamentos.gravar(movimentos=)`; ver `arquitetura-pagamentos-dia.md`):
os aportes, transferências e distribuições da aba Regras (`definidos_validos`,
os mesmos do painel e do Excel, tipo pela regra — revisão geral de
22/10/2026, achado 1: a transferência e o composto do print ficavam fora) e
os à mão válidos, sem repetir: à mão com o mesmo de, para e valor de uma
linha da Regras sai (o "de fora" repete a regra cujo aportador não é conta
do painel). A seção fica logo depois do quadro-resumo, com uma linha
no resumo que leva até ela (dono, 23/10/2026).

## Excel do dia: zero, e não vazio

Escreve C (saldo do dia), D (a pagar), J/K, E4, H do Painel (aporte definido)
e H da Movimentações (valor definido por aportador), mais B/C/H das linhas
54–73 (seção «À MÃO»). Só número entra (exceto B/C da seção «À MÃO», o nome
da conta — texto, nunca começando com "="), sem fórmula, e o `workbook.build`
confere célula por célula. **Nome de conta: a tela compara o texto EXATO; o
SUMIF do Excel ignora maiúsculas.** Os dois só contam a mesma coisa se a aba
Regras do MODELO usar o MESMO texto do rótulo do painel — "Conta Alfa - banco"
na Regras passaria no Excel e não casaria na tela. **Participante sem valor leva 0, nunca vazio**:
vazio faria `I = IF(H<>"",H,G)` cair no VALOR SUGERIDO e somar dinheiro que
ninguém definiu. A tela passa só os movimentos válidos (destino conta do
painel, valor > 0) e `definidos_validos` — os mesmos que ela soma; o Excel
recusa o resto, para nunca divergir da tela.

O nome do arquivo ("DD MM - completa.xlsx") é o MESMO do painel da aba "Saldo
de pagamentos": se já existe, a tela pergunta antes de substituir. A
atividade é anotada como "dia", que o Início nomeia por `OUTRAS_ORIGENS` (e
não por `ROTINAS`, onde viraria "não rodou hoje" enquanto as abas convivem).

## Visual (21/10/2026)

As quatro tabelas cabem a 1280x800 com o menu aberto e o Windows a 125%: o
Treeview não encolhe coluna, ele CORTA as da direita, então a soma das
larguras de cada `COLS_*` (mais a #0, `LARGURA_CONTA`) é a medida, e só a
coluna de texto (âncora "w") estica na tela larga. A barra de rolagem é
empacotada antes da tabela. Tabela vazia tem `LINHAS_VAZIA` linhas e cresce
com o que está à vista (`_ajustar_altura`, também ao abrir/fechar conta) até
o teto de cada uma. Texto de ajuda quebra na largura do cartão (`_ajuda`,
`wraplength` no `<Configure>`); período e alertas vazios saem do layout.
`aplicar_cores` repassa o `estilo_tabela` (as cores das linhas são tags da
tabela). **Cada tabela soma no máximo 680 a 100%** (as desta aba e as do
Controle de aportes), conferido por `tests/test_layout_1280.py`. Na tabela de
saldos a célula é CURTA (22/10/2026): o digitado aparece como "R$ 250,00 ✎"
(`saldos.celula`) e a SITUAÇÃO como `situacao_curta()` ("não bate", sem o
valor, que é a coluna DIFERENÇA); a frase inteira e o original com o motivo
(`LinhaSaldo.detalhe()`) ficam no rótulo embaixo da tabela, da linha
selecionada. O "(era …)" na célula cortava a coluna a 1280 px. A `ferramentas/galeria.py` fotografa a aba PREENCHIDA com dados
fictícios (`_preencher_dia` → `mostrar_numeros()`), sem mudar o app.

## Conferência editável (entrega 2, 22/10/2026)

O passo 2 deixa o dono LIBERAR um bloqueado (com motivo), DESMARCAR, EDITAR a
forma de pagar, o dado de reembolso e a descrição, e lançar um pagamento À MÃO.
Cada clique é uma linha nova na nuvem (só acrescenta); o estado de um alvo é a
"dobra" dos eventos dele, na ordem do id do banco; "Desfazer" volta ao que o
ERP diz. Tudo chega ao "a pagar", ao mínimo de aporte, à planilha, ao HTML, à
remessa e ao Excel pelo MESMO `Resultado` (`geracao.resultado_da_tela`): sem
decisão nenhuma ele é idêntico ao da entrega 1.

Regras que viraram lei:

- **LIBERADO, EDITADO e À MÃO nunca começam com "APTO"**, então na conferência
  da Remessa nascem DESMARCADOS: liberar não marca remessa sozinho. ATENÇÃO
  grave (valor diverge, documento não bate, JÁ PAGO) continua na frente do
  status; só cedem à liberação os alarmes de forma de pagar, e à edição da
  forma, só "sem dados de pgto".
- **Liberar "já enviado" ou "fora dos Contatos" pede "tem certeza?"**
  (`default="no"`), depois do motivo. Linha de lançamento dividido (com
  `parte`) não se libera nem tem a forma editada.
- **Reembolso exige tipo + dados**: editar o nome arrasta a forma, e o dado não
  pode ser o do fornecedor quando o registro não era reembolso. Tirar o
  reembolso é pelo "Desfazer".
- **Forma de pagar editada** exige chave com tipo declarado ou linha digitável
  que fecha nos DVs. **Pix de 11 dígitos crus (ambíguo CPF/telefone) é
  recusado.** Editar a descrição roda `aviso_de_casamento` (com as MESMAS
  funções do `anexar/matcher.py`: CC e número do documento no fim); só ela
  pergunta antes de gravar.
- **Chave Pix editada vai como foi digitada, com observação** (dono,
  22/10/2026: "se eu editar manual, tem que ir o que eu coloquei"). A
  `geracao` marca o registro (`remessa_dia.CHAVE_EDITADA`) e escreve na Obs
  (planilha, HTML) e a tela na nota (`pagamentos.por_conta(participantes=)`):
  "chave Pix editada à mão", ou, quando a chave é CPF/CNPJ DIFERENTE do
  documento que a remessa usaria (`remessa_dia.documento_sem_edicao`:
  reembolso, senão cadastro de Contatos), "chave Pix editada: CPF/CNPJ
  diferente do favorecido do ERP (<doc mascarado>)". Com a marca e a chave
  CPF/CNPJ, o `preparar` declara no 08.3B o documento DA CHAVE (a Informação
  12 da forma 03 já leva a chave; os dois discordariam); e-mail, celular e
  aleatória seguem com o do cadastro. Sem a marca (Remessa/Retorno sozinha)
  nada muda.
- **Linha digitável editada confere o valor** (dono, 22/10/2026). O valor
  embutido (`ocr_boleto.valor_embutido`, Decimal, lido dos dígitos; zerado e
  arrecadação de REFERÊNCIA = sem valor) contra o do pagamento, ao centavo
  (`conferencia.conferir_valor_da_linha`). Bate: segue. Sem valor: grava com
  a Obs "linha sem valor embutido — confira". Diverge: a tela pergunta "A
  linha digitável é de R$ X e o pagamento é de R$ Y. Gravar mesmo assim?"
  (`passo2.pergunta_do_valor`, `default="no"`); gravada, a `geracao` põe
  "ATENÇÃO — valor da linha diverge" na frente do status (Copiar bloqueado,
  desmarcada na Remessa) e a Obs "valor da linha R$ X ≠ pagamento R$ Y"; a
  tela mostra a mesma nota em âmbar. Linha que não fecha nos DVs continua
  recusada. A conferência é refeita na geração a partir da edição gravada
  (nada novo na nuvem). **Linha nova que BATE derruba o "valor do boleto
  diverge" do boleto antigo do ERP** (`valor_diverge` vira False e o status
  vira só EDITADO; decisão do coordenador, 22/10/2026); sem valor ou
  divergindo, o alarme antigo continua.
- **À mão: só remover.** Não se edita nem se desmarca: remove-se (com motivo)
  e lança-se de novo. **À mão em conta PF é recusado** (a PF é paga pelo
  celular, fora do HTML). Com link do lançamento: não paga título já pago, de
  outra conta, nem mais que o em aberto (somando o que já está à mão para ele);
  herda CC/NF/OC para o Anexar casar. Sem link, avisa que o Anexar não tem o
  que casar.
- **À mão NUNCA vai na remessa CNAB** (`geracao.para_a_remessa`): sem
  lançamento do dia, não há referência para retorno nem baixa. No HTML o id é
  `<lançamento>#mao:<n>`.
- **Durante a gravação**, geradores, aportes e Buscar ficam apagados
  (`passo2.botoes`); a gravação é seguida de releitura da nuvem, também quando
  falhou, e releitura que falha limpa a tela e pede nova busca (nunca número
  velho).
- **Nuvem com erro: os geradores perguntam** (`passo2.pergunta_ao_gerar`,
  `default="no"`): "as decisões de hoje (liberados, desmarcados, edições, à
  mão) NÃO estão aplicadas". Nuvem ainda não lida (`SEM_NUVEM`) só apaga os
  botões.
- O iid da tabela é a chave **(id, parte_linha)** (`passo2.chave_da_linha`,
  "<id>|<dígitos da linha>"), estável entre recálculos — nunca a posição; a
  chave igual (id vazio) ganha "#2", "#3"… para o Treeview não recusar.

## Lançamento dividido em N boletos (entrega 5, tarefa 3b)

`boletos_somados` faz N linhas com o MESMO id; cada `confirmacao.Linha` e cada
`pagamentos.Pagamento` leva `parte` ("k/N") e `parte_linha`. As decisões do
dono continuam por id:

- **Desmarcar** tira as N partes (o diálogo diz "saem as N partes");
  **editar a descrição** vale para as N.
- **Liberar** e **editar forma de pagar/reembolso** de linha dividida são
  RECUSADOS (`conferencia.recusa_de_dividido`: "lançamento dividido em N
  boletos: edite/libere no ERP ou pague as partes como estão"). Liberação ou
  forma editada que chegue pela nuvem também não vale (`geracao`,
  `pagamentos.por_conta`), e a tela e os arquivos concordam.
- **Já enviado é por id**: uma parte já saída segura TODAS (lado seguro).
- **Agendado**: o índice único é (dia, alvo), então o lançamento vira UM
  agendado com a SOMA das partes que saem e `foto["partes"]` (linha e valor
  de cada uma); a lista do diretor soma igual.
- **Baixa no ERP**: na Remessa/Retorno, pago de lançamento dividido que veio
  da tela nova fica "de fora" (`baixa_erp.MOTIVO_DIVIDIDO`, "baixe no ERP
  quando todos saírem"), pelos `divididos_do_resultado(self.resultado)`.
  Resultado montado pela própria Remessa não tem `parte`: nada muda.

## Agendados (entrega 2)

O passo 6 grava uma FOTO de cada pagamento marcado (valor, em aberto, forma,
favorecido); "Agendados a confirmar", no topo, lista o que ainda não teve
resposta final. **Nada se resolve sozinho.**

- **Pré-marca de "pago" só com prova**: baixa no ERP (`paid` OU `markedAsPaid`,
  inteira, ou parcial batendo ao centavo) ou retorno "ok" do banco numa remessa
  do dia do agendado ou depois (`nuvem_do_dia`: envio sem `gerado_em` ou
  anterior ao agendado não vale). A prova por comprovante baixado fica para
  depois: `prova_extra` é o ponto de extensão e nunca vence "sumiu"/"mudou".
- **Restante 0 sem baixa** = "baixa sem confirmação — responda", sem pré-marca,
  mesmo com retorno "ok". **"Sumiu" e "mudou" só saem com resposta**; sem a
  foto do valor em aberto, ou sem o valor em aberto do ERP, também é
  "responda". Sem releitura do ERP nunca se diz "sumiu".
- Respostas: pago, não saiu (motivo de 3 letras ou mais), reagendado (data de
  hoje em diante; continua pendente). A resposta TIRA a marca ☑
  (`marcas_iniciais`: o id cuja última resposta mudou volta desmarcado, também
  quando a resposta veio de outra máquina).
- **"Pago" SEMPRE pergunta** ("Gravar N como pago?", `default="no"`), listando
  favorecido, valor e a prova com a hora ("baixa no ERP — lida às 08:12", ou
  "da última busca"); o item sem prova aparece como "SEM prova — confira".
- Já marcado hoje não se marca de novo (índice único dia + alvo): remarcar é
  responder "reagendado" com a data de hoje. As repetidas viram recado.
- **A releitura depois de gravar relê a nuvem (`reler_tudo`), NÃO o ERP**:
  pendente antigo guarda a situação da última Buscar, e um pago no ERP durante
  o dia só aparece pré-marcado no próximo Buscar. É o lado seguro.

## Lista do diretor (entrega 2)

Passo 7: uma linha por conta que tem agendado, com NOME CURTO (por conta, na
nuvem, 1 a 60 caracteres, sem quebra de linha nem tab, nunca igual ao de outra
conta), ordinais alternáveis e a ordem de ontem como SUGESTÃO; a ordem que o
dono arrumou hoje vale sobre a de ontem. As setas não cruzam a fronteira
numerados × demais. **"Copiar para o WhatsApp" exige nome curto único em todas
as linhas** (linha sem nome é recusada, com a lista dos rótulos e o aviso para
usar «Nome curto…»); copia primeiro e só então grava a lista (falha ao gravar
só avisa: perde-se a sugestão de amanhã). Dinheiro em `Decimal`; valor zero ou
negativo não entra.

**Nome curto sugerido** (pedido do dono 22/10/2026: "fazer por IA isso e
deixar meio que pronto, não consegui copiar"). Conta sem nome gravado nasce
com a sugestão de `lista_diretor.sugerir_nomes` (regra fixa, sem IA nem
rede): tira o banco do fim quando a lista inteira é do mesmo banco (senão
fica curto, "Obra - Inter"), sufixos jurídicos (LTDA, SPE [I], S/A, ME,
EIRELI, EPP) e números de conta; encurta PARTICIPAÇÕES/SUBCONTA/ENGENHARIA/
INCORPORAÇÕES/EMPREENDIMENTOS; "SUBCONTA 12345-6" vira "Sub. 12345"; Title
Case (sigla sem vogal fica maiúscula). O banco sai também quando é um trecho
só dele no MEIO do rótulo ("EMPRESA - SICOOB - SUBCONTA 30001-1" → "Empresa
Sub. 30001"); rótulo que é só banco e número vira "<Banco> <número curto>"
("SICOOB 40001-1" → "Sicoob 40001"); nunca o banco duas vezes. Sugestões são ÚNICAS entre si e
diferentes dos nomes gravados de outras contas: empate desempata pelo número
da conta (5 dígitos), depois banco, depois contador, em ordem alfabética dos
rótulos (a ordem de chegada não muda nada). A tela mostra "~ nome"
(`sugerido`), o Copiar aceita (só recusa linha sem nome nenhum), «Nome
curto…» abre já com a sugestão e «Gravar sugestões» grava todas num pedido
só (`gravar_nomes_curtos`).

**Ler o lançamento com a aba do ERP fechada** (22/10/2026,
"TargetClosedError"): `lancamento_do_erp.ler_pela_aba` reabre pelo
`garantir_sessao` e lê UMA vez de novo; fechou de novo, o recado é "O Chrome
do app fechou a aba do ERP; clique em Ler de novo". A causa estava em
`MCClient._abas_do_robo`, que punha a `self.page` FECHADA na lista e a
adotava como logada. Excel do dia aberto no Excel (errno 13) vira o recado
de `recados.excel_aberto` só quando o erro é sobre o PRÓPRIO .xlsx do dia
(caminho comparado sem barra nem caixa); outro `PermissionError` (pasta, modelo,
OneDrive) mostra o erro de verdade.

## Sem nuvem, a entrega 2 trava (falha fechada)

Sem nuvem lida (erro ao ler, ou sem login) a tela volta ao comportamento da
entrega 1, com o recado no topo (`lbl_nuvem`): botões do passo 2, de agendados
e da lista apagados e nada grava. A nuvem que falha ao LER devolve
`Conferencia()` vazia e pendentes vazios com `erro`, e os geradores perguntam
antes de gerar (ver acima). A nuvem só acrescenta e só para conta liberada
(`privado.e_ativo()`); quem fez e quando são carimbados pelo servidor.

## Aba "Controle de aportes" (entrega 3, 22/10/2026)

Mora neste pacote (`controle_*.py`) por ser do mesmo projeto e para não
pedir pasta nova no `build.yml`. Grupo DIÁRIO, no FIM (chave `cap`, sem
Ctrl+N), invisível ao aprovador. **Não escreve no Mais Controle.**

| Módulo | Decide |
|---|---|
| `controle_aportes.py` | a conta (aportou = já aportado antes da abertura + recebimentos do ERP; nível = maior aportou÷parte; deveria = nível×parte; para igualar = deveria − aportou), quem é o aportador, sem dono, apontamentos, formulário |
| `controle_erp.py` | `GET receipt-installments` por conta × natureza (Aporte de Capital, Aporte de Investidor), pela aba do robô |
| `controle_nuvem.py` | `controle_aporte_conta`, `_aportador`, `_atribuicao` (ler: e_ativo; escrever: e_admin) |
| `controle_frame.py` | tela fina; nuvem numa thread própria |

**Aportador = Cliente do recebimento pelo nome COMPLETO** (`util.norm_espaco`),
contra os aportadores daquela conta; o resto vai para "Sem dono", fora da conta
até o dono apontar. Apontamento guarda o valor: se o ERP mudar, volta para sem
dono ("apontado com R$ X; agora R$ Y"). **Filtros conferidos**: a mesma parcela
em duas contas, duas naturezas ou na conta de contraprova PARA a leitura. Medido
em 22/10/2026: o LISTAR devolve por item só `customerName` (sem `customerId` e
sem nome de conta), então o caminho pelo id do Cliente está dormente e a defesa
real é duplicidade entre contas + contraprova. Proporção é PRÓPRIA (não a aba
Regras do MODELO, nem viva da `subconta_investidor`, que entra só como sugestão
e aviso de divergência). Distribuição de lucro não abate. Dívida da abertura
cortada no centavo a favor do devedor (o líder nunca passa a dever 0,01).
**Leitura duvidosa derruba a CONTA, com erro e sem número** (onda final,
22/10/2026): parcela repetida, recebimento fora do período pedido (abertura..hoje;
data com fuso vira data de Brasília, `data_do_erp`) e recebimento zero ou
negativo (estorno) — nunca somam nem ficam "sem dono". Apontamento perde para o
Cliente do ERP quando este passa a identificar OUTRO aportador (ou um aportador,
num "não é aporte"): volta para sem dono, sem coluna nova no banco, e
`apontar` recusa a escolha que contradiz o Cliente (`conflito_do_apontamento`:
"o Cliente no ERP aponta para X — corrija o Cliente no ERP ou aponte para ele").
`gravar_conta` em alteração também recusa se o nome, a abertura ou o `ativa` da
conta mudaram desde que o formulário abriu, e nunca manda `ativa`. Recebimento
parcial (`plannedValue` ≠ recebido) só alerta. A nuvem que volta com 1000 linhas
(o `max_rows`) é recusada (`LeituraCortada`), e `gravar_conta` recusa se o banco
mudou nome, parte ou já aportado depois que o formulário abriu.
**Conta desativada (`ativa = false`) some da aba e só se reativa pelo painel do
Supabase — de propósito**: a aba não tem botão de desativar nem de reativar.
