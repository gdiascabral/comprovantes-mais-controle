---
paths:
  - "concessionarias/**"
---

# Arquitetura: concessionarias/

> Criado em 14/10/2026 com a aba. Carrega sozinho quando o Claude lê um arquivo
> dos caminhos acima. Mudou o código? Atualize AQUI.

- `concessionarias/` — aba **Água e energia** (grupo DIÁRIO, chave `agu`):
  dispara a MESMA rodada da tarefa agendada do repositório `agua_energia`
  (`coletor\rodada_diaria.bat`) a qualquer hora, fora do horário, fim de semana
  ou feriado. O app **não importa nada de lá**: roda o `.bat` e lê o que ele
  escreve. Dois arquivos: `rodada.py` (puro, sem tkinter: monta a linha, acha a
  instalação, lê a trava e o log) e `frame.py` (`AguaEnergiaFrame`, a tela).
- **A instalação**: `C:\AUTOMAÇÕES MAIS CONTROLE\agua_energia`, ou a pasta de
  `MC_AGUA_ENERGIA`; `MC_AGUA_ENERGIA=off` desliga (a aba abre com o botão
  apagado e diz por quê). Sem `coletor\rodada_diaria.bat` na pasta, é o mesmo
  que desligada.

## O contrato com o água e energia

Mudar um lado é mudar o outro (`coletor/trava_rodada.py` e
`coletor/rodada_diaria.py` de lá):

- **Código de saída 3** = outra rodada já em andamento (`rodada.CODIGO_OCUPADA`).
  A aba mostra "não começou" e **não** escreve resumo nenhum.
- **Trava**: `relatorios/RODADA_EM_ANDAMENTO.trava` + `.json` (início e origem de
  quem roda). `rodada.em_andamento` **testa a trava de verdade** (tranca e solta
  na hora, `msvcrt.locking`): o `.json` sozinho pode ter sobrado de uma rodada
  que morreu no meio. Retorna `None` só quando comprovadamente livre. Dois "não
  dispare" diferentes: **`{}`** = trancada, mas sem info (o normal nos instantes
  em que uma rodada pega ou solta a trava; a aba diz "espere ela terminar");
  **`{"ilegivel": True}`** = não deu para sondar a trava (erro ao abrir, errno
  inesperado) — só este fala em chamar o suporte. "Livre" dito sem ter
  conferido seria mentira.
- **Linha de resumo**: o log termina com `resumo salvo em <caminho>`;
  `resumo_do_log` pega a última e a aba lê o arquivo.
- **`--forcar --esperar 0 --origem "app: <nome>"`** (e `--so equatorial` na
  rodada parcial; `SO_PERMITIDOS` espelha os `choices` de lá). `--esperar 0`:
  a rodada não fica em fila esperando a outra, devolve 3 na hora.
- **A origem é validada** (`_ORIGEM_OK`) e só nasce de `origem_segura`: o texto
  atravessa o `cmd.exe`, onde `& | % ^ ! < > "` executam ou cortam coisas; o
  acento vira letra simples porque o `cmd` lê os argumentos antes de o `.bat`
  trocar a página de código. A linha de comando recusa origem fora do formato
  com `ValueError`.

## Por que a linha do `cmd` é montada à mão

`linha_de_comando` devolve UMA string, `"<cmd> /d /s /c ".\rodada_diaria.bat ..."`.
Com `/s` o `cmd` tira só o primeiro e o último par de aspas e o resto chega ao
`.bat` como está; a lista do `subprocess` poria aspas onde o `cmd` não espera
(e quebraria a origem, que tem espaço). O `cmd.exe` vai pelo caminho completo
(`COMSPEC`, ou `System32`), porque o nome solto seria procurado primeiro na pasta
do exe do app; e o `.bat` vai com `.\` na frente porque, com
`NoDefaultCurrentDirectoryInExePath` ligado (ambiente endurecido), o `cmd` não
procura na pasta atual.

## O log é um por disparo (`RODADA_LOG`)

O `.bat` anexa (`>>`) ao log da tarefa agendada, e o `cmd` **tranca** o arquivo
enquanto o redirecionamento está aberto: um segundo disparo, com a agendada
rodando, morria sem chegar a chamar o Python (e portanto sem o código 3 e sem a
mensagem "já estava em andamento"). Por isso a rodada do app tem log próprio:
`novo_log` cria `coletor\logs` se faltar e escolhe
`coletor\logs\rodada_app_AAAAMMDD_HHMMSS_<pid>[_n].log`, RESERVANDO o nome com
`open(..., "x")` (duas rodadas no mesmo segundo não pegam o mesmo arquivo);
`frame.rodar` chama `novo_log` dentro do mesmo `try OSError` do `iniciar` (status
"Não consegui iniciar a rodada: ..."). `iniciar(..., log=)` o passa ao `.bat` e `iniciar(..., log=)` o passa ao `.bat` pela variável de ambiente
`RODADA_LOG`. O `Leitor` nasce **antes** do `iniciar` e lê só o que chegar
depois dele (linha inteira por vez; arquivo truncado recomeça).

## Chrome central ligado × desligado

- **Ligado** (`erp.central.ligado()`): a rodada abre a aba dela no Chrome do
  porteiro e nenhuma sessão cai. A aba dispara direto.
- **Desligado**: a rodada abre o próprio Chrome e entra no ERP com o login do
  app — o ERP aceita **uma sessão por usuário**, e a do app cai. Por isso, só na
  rodada completa (a `--so equatorial` não toca no ERP): se o Anexar está
  trabalhando (`anx.ocupado()`), a aba **recusa**; se está livre, **pergunta**
  antes. Quem perguntou "não" não dispara nada.

## Sem `fechar()`, e por quê

A aba não tem navegador nem thread: o trabalho é de outro processo, que segue
mesmo que o app feche, e a trava de lá impede a segunda rodada. Não há o que
fechar — por isso o laço de fechamento do app (`getattr(quadro, "fechar")`) a pula. O que a aba expõe é
`ocupado()` (enquanto `proc` está vivo), que alimenta o ● da barra (`agu`, em
`_quem_trabalha`) e o chip. Ela recebe o `aba_anx` só para a pergunta acima.

## Auditoria

`nuvem.auditoria.registrar` com `aba="agu"`: **"Água e energia: rodada
disparada"** (detalhe = o pedido, `--forcar [--so ...]`) ao iniciar e **"Água e
energia: rodada terminou"** (pedido — veredito; resultado `ok` no código 0,
`aviso` no 1 e no 3, `erro` nos outros) ao acabar. Falha ao registrar só anota no
log do app: nunca prende a aba nem larga a rodada sem acompanhamento. A origem
(`app: <primeiro nome>`) também entra na linha de comando, então a trava de lá
diz quem está rodando.

## Empacotamento

Pasta de código nova no `codigo.zip`: linha `Copy-Item concessionarias/*.py`
no `build.yml`, `"concessionarias"` em `tests/test_imports_do_motor.py` e a aba
em `tests/test_registro_visivel.py` e `ferramentas/galeria.py`. Os testes de
`rodada.py` são puros (`tests/test_concessionarias_rodada.py`); os da tela usam
a fixture `raiz` (abrem janela).
