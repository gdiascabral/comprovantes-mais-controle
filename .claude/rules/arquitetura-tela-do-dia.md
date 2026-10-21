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
| `saldos.py` | passo 1: sistema × banco por conta; o ajuste guarda o original e acusa quando o ERP mudou depois dele; saldo do dia = banco se digitado, senão sistema |
| `pagamentos.py` | passo 2: por linha do painel, o que VAI SAIR, o JÁ ENVIADO (soma no a pagar) e o que está BLOQUEADO; conta sem linha no painel vai para `fora`, com o motivo, em vez de sumir |
| `aportes.py` | passo 3: mínimo, sugestão da aba Regras, conta-mãe primeiro com alerta forte, movimentos «À MÃO» no M (entra) e no E (sai) |
| `para_aportes.py` | os aportes definidos viram `Operacao` da aba Aportes, com pendências (não foram) e avisos (foram, confira) |
| `excel_do_dia.py` | passo 4: o MODELO.xlsx com os números da tela |
| `erp_do_dia.py` | os saldos do ERP, sempre pelo Chrome do app |
| `dia_de_trabalho.py` | o JSON do dia |
| `decisoes.py` | o que a tela faria com `if`: "—" de conta sem saldo, movimento à mão válido, quando o Excel e os geradores recusam, quais operações seguram |

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

**Sem campo de data** (decisão do dono, 21/10/2026): o período é o de
`sugerir_periodo(hoje)`, e a tela mostra o período lido ("Pagamentos de DD/MM
a DD/MM", `decisoes.periodo_na_tela`). Sem calendário de feriados, ela NÃO
avisa nada sobre o dia anterior: "o dia útil anterior ficou fora" vale em todo
dia útil e viraria ruído. **No dia seguinte a um feriado, os vencidos do
feriado se buscam pela aba Remessa/Retorno** (que tem o campo de data).

## Saldos pelo Chrome do app

Regra do dono (14/10/2026): nada de `POST /users/login` por HTTP, que derruba a
sessão do Chrome. Central ligado: a sessão do porteiro (`Sessao.logar("", "")`,
que, se o central sumiu no meio, levanta em vez de cair no login). Central
desligado: a MESMA aba do robô que leu os pagamentos (`mc_api._fetch_json`).
Erro do ERP vira `ErpError`, nunca saldo zero; `acessos.json` estragado falha
FECHADO. Conta sem saldo mostra "—" no mínimo e no saldo final, com situação
"erro"; o Excel recusa quando `validacao.exigir_todos_os_saldos` está ligado
(saldo do banco digitado supre o do sistema) e pergunta quando não está.

## O JSON do dia

`<RAIZ_SAIDA>/<ano>/<MÊS>/DD MM - dia de trabalho.json`, ao lado do Excel do
dia. Guarda os ajustes de saldo, o valor por aportador, os movimentos à mão e o
que já foi mandado para a aba Aportes (chave `destino|aportador` → VALOR
mandado, em Decimal). Arquivo ausente = dia vazio; ilegível ou de outra data
LEVANTA, e aí a tela não grava nada (sobrescrever apagaria o que a pessoa fez)
e **não manda nada para a aba Aportes** (sem o arquivo não se sabe o que já
foi mandado hoje). Sem SQL nesta entrega; a nuvem é a entrega 2.

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
