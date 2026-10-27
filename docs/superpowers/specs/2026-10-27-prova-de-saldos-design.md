# Prova de saldos (ERP × banco) — desenho

Data: 27/10/2026. Aprovado pelo dono em conversa no mesmo dia.

## Por quê

Todo dia uma pessoa do financeiro tira, à mão, o print do saldo de cada conta no
ERP e no banco e manda no grupo de conferência do WhatsApp, só para mostrar que
os saldos batem. São duas telas por conta, todas as contas do painel, todo dia.
O app já lê o saldo do ERP e o do Sicoob; falta o Inter e falta juntar tudo numa
prova pronta para mandar.

## O que o dono decidiu

| Pergunta | Resposta |
|---|---|
| O que o grupo recebe | Um **resumo** (todas as contas lado a lado) **mais os prints** de cada conta |
| Como chega ao grupo | O app **gera um PDF** e abre a pasta; a pessoa arrasta para o grupo. O app **não** mexe no WhatsApp |
| Quando roda | **Botão** no app |
| Que saldo | O **saldo atual** do banco (e o atual do ERP, para comparar o mesmo instante) |
| Que contas | Todas as contas **Sicoob e Inter do painel do Saldo** |
| Inter | Só as contas da lista do app (hoje 3); a de outra empresa que só tem perfil **não entra** |

## O que é

Um botão **"📸 Prova de saldos"** no cartão "Saldos" da aba **Pagamentos do dia**.
Ao clicar:

1. **ERP**: o saldo atual de cada conta do painel (o mesmo que a tela já usa
   como "sistema") e um **print** da tela da conta no Mais Controle — numa aba
   PRÓPRIA do Chrome do app (porteiro / `AbaCentral`), fechada no fim.
2. **Sicoob**: o saldo atual de cada conta (o mesmo caminho do saldo que a tela
   já lê — `extratos_sicoob/saldo.py`, rota do widget da tela inicial) e um
   **print** da área de saldo daquela conta. As contas do 2º acesso (QR das
   contas de outro login) seguem a pergunta que a tela já faz.
3. **Inter**: para cada conta da lista (`contas_inter.json`), abre o Chrome no
   perfil DELA (`inter_baixar.pasta_do_perfil`). Se a sessão venceu, o app diz
   **qual conta** está pedindo QR ("Leia o QR da VXZ") e espera, como o Baixar
   Comprovantes já faz (`esperar_login`). Com a sessão aberta:
   - **confere a conta**: o número e o nome da empresa que a tela inicial mostra
     têm de ser os da conta pedida (a do painel). Outra conta aberta = linha
     "não lida" com o motivo — nunca anota o saldo de uma conta em outra;
   - **saldo**: o valor `disponivel` da resposta de
     `GET https://cdpj-api.bancointer.com.br/cc/saldo/v3/` que a própria tela
     inicial pede (medido em 27/10/2026, com QR do dono; é o "Saldo em conta"
     da tela). Lido OUVINDO a resposta que a tela faz, ou repetindo o pedido de
     dentro da página — nunca por fora do navegador;
   - **print** da área do saldo da tela inicial.
4. **Compara** ERP × banco em **centavos** (`Decimal`), conta a conta:
   ✅ bate · ❌ não bate (mostra a diferença) · ⚠ não lida (com o motivo).
   **Nunca** se lê o número de dentro de uma imagem: o print é só prova.
5. **PDF** em `Pagamentos do dia/Prova de saldos AAAA-MM-DD HHhMM.pdf`:
   - página 1: título com data e hora, a tabela (conta, saldo ERP, saldo banco,
     diferença, situação, hora de cada leitura) e a contagem (N batem, N não
     batem, N não lidas);
   - uma página por conta: o print do ERP e o print do banco lado a lado, com
     o nome da conta e os dois valores escritos embaixo.
   O app abre a pasta no fim.

> **Ajustes da revisão final (27/10/2026)**: o PDF vai para
> `Pagamentos do dia/Prova de saldos/` (prints em `prints/<data hora>/`) e
> abre com o arquivo selecionado; a página da conta empilha ERP em cima e
> banco embaixo, a 1:1, continuando na página seguinte se não couber; o
> print do ERP leva o cabeçalho da grade; o Inter confere a conta antes do
> print, e sem número no ERP só aceita a razão social inteira.

## Regras de segurança

- **Só leitura** no ERP e nos bancos: nenhum clique que mexa em dinheiro, nada
  de assinar, cancelar, aprovar ou transferir.
- **Conta incerta não bate**: falha de leitura, QR não lido a tempo, conta
  diferente na tela, valor que não chegou — tudo vira ⚠ com o motivo, e as
  outras contas seguem.
- **Um Chrome do Sicoob por vez**: a prova entra na mesma trava "quem espera
  quem" que a tela já usa (saldo do Sicoob, Conferir agendamentos, Extratos,
  Baixar comprovantes, Remessa). O Inter tem um perfil por conta e não disputa
  com o Sicoob; mas não roda junto com o Baixar Comprovantes do Inter (mesmo
  perfil).
- **ERP sempre pelo Chrome do app**: aba própria no Chrome central; nunca login
  HTTP por fora (derrubaria a sessão).
- **Thread**: navegador e Playwright fora da thread da interface; a tela recebe
  progresso pela fila (`queue` + `after`), com "Parar".
- **Dado real fora do repositório**: prints e PDF ficam só na pasta do app;
  testes usam contas e valores fictícios.

## Peças (uma responsabilidade cada)

| Peça | Faz | Depende de |
|---|---|---|
| `tela_do_dia/prova_saldos.py` (regra pura) | junta leituras ERP/banco por conta, compara em centavos, decide ✅/❌/⚠ e monta as linhas da tabela | nada de tela/rede |
| `tela_do_dia/prova_pdf.py` | gera o PDF (página-resumo + uma página por conta com as duas imagens) | **Pillow**, que já vai no exe (arrastado pelo pdfplumber, `requirements.lock`): a página-resumo é desenhada como imagem e o PDF sai de `Image.save(..., save_all=True)` — **sem dependência nova, sem exe novo**. Fonte: a do Windows (`arial.ttf`/`segoeui.ttf`) com recuo para a padrão do Pillow |
| `baixar_comprovantes/inter_saldo.py` | abre a conta do Inter no perfil dela, espera QR, confere conta, lê `disponivel` e tira o print | `inter_baixar` (perfil, `esperar_login`) |
| leitura do Sicoob com print | reaproveita `extratos_sicoob/saldo.py` + tira o print da área de saldo da conta aberta | `sicoob_na_tela` / `LeitorSicoob` |
| print do ERP | abre a tela da conta no ERP numa aba própria do Chrome central e fotografa | `erp/central.AbaCentral` |
| botão e progresso | cartão "Saldos" da aba Pagamentos do dia; janela de progresso com "Parar"; abre a pasta no fim | `tela_do_dia/frame.py` |

## Testes

- Regra pura (`prova_saldos`): bate / não bate / não lida, centavos,
  arredondamento, conta sem leitura de um lado, conta errada no Inter vira ⚠.
- PDF: gera com imagens fictícias, confere páginas e textos.
- Inter: dublê de página — conta da tela diferente da pedida vira ⚠; resposta
  do saldo sem `disponivel` vira ⚠.
- Trava: a prova não abre o Sicoob se outro dono estiver com ele.
- Nenhum teste abre Chrome, banco ou ERP de verdade; testes de tela com dublê
  autouse de `messagebox`.
- Prova ao vivo: uma rodada com o dono lendo os QR do Inter.

## Fora do escopo

- Mandar no WhatsApp pelo app.
- Saldo de uma data passada.
- Contas fora do painel do Saldo, contas de outros bancos e a conta Inter que
  não está na lista do app.
