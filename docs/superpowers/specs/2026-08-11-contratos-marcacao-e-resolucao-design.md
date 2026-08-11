# Aba Contratos: escolher o que arquivar e resolver o que ficou em dúvida

Data: 11/08/2026

## O problema

A aba Contratos arquiva, no passo 2, **tudo** que a busca conseguiu resolver
sozinha, e nada do que ficou em revisão. Quem confere não tem como dizer "esta
não, agora" nem "esta sim, o contrato é aquele ali".

Julho/2026 mostrou os dois motivos de revisão que aparecem de verdade:

- **cliente sem empresa** — as duas casas de FERROVIARIOS QD 01 LT 12: o
  cliente `FULANO DE TAL DA SILVA` não está em `clientes_erp` de
  nenhuma empresa do `contas_sicoob.json`;
- **anexos disputando a casa** — RPB 24 QD 26A LT 14 CS 02: os anexos
  `CONTRATO DE COMRPA E VENDA … CS 02` e `CONTRATO … CS 02`. O filtro de
  qualificadores (`escolha.QUALIFICADORES`) descarta compra-e-venda, mas o
  nome no ERP está com "COMRPA"; o erro de digitação de quem subiu o arquivo
  virou ambiguidade, e a casa caiu em revisão — que é o desfecho certo do
  código atual, e ainda assim deixa a pessoa sem saída pela tela.

## O que vai ser feito

### 1. Coluna de marcação na tabela

Coluna `✔` (`☑`/`☐`) como primeira coluna do `Treeview`. Alterna com clique na
coluna ou com a tecla Espaço na linha selecionada. Rodapé com "N de M
marcada(s)" e os botões *Marcar todas* / *Desmarcar todas*, no vocabulário que
a aba Pagamentos do Dia já usa.

O passo 2 arquiva **só as marcadas**; nenhuma marcada, ele avisa e não roda.

Nasce marcado o que está pronto (com contrato e com empresa). Linha em revisão
nasce desmarcada e **não aceita marca enquanto o motivo existir**: sem contrato
escolhido não há o que baixar, sem empresa não há para onde. A tentativa mostra
o motivo no status e aponta o *Resolver*.

A marca serve para TIRAR da rodada o que está pronto e para INCLUIR o que foi
resolvido. Nunca para mandar gravar às cegas.

### 2. Janela Resolver (uma casa por vez)

Abre por duplo clique na linha ou pelo botão *Resolver*. Cabeçalho com obra,
unidade, comprador, valor e o cliente que o ERP tem na obra.

- **Contrato** — todos os anexos da obra, com os candidatos no topo e marcados
  como tal, mais um campo de busca. *Abrir para olhar* baixa e abre no
  visualizador padrão do Windows. Antes de baixar, o app **relista os anexos
  daquela obra**: o `downloadUrl` é URL pré-assinada do S3 com `Expires` curto,
  e "rode a busca de novo" é resposta ruim para quem só quer ver o arquivo.
- **Empresa** — só aparece quando o cliente não está mapeado. Combo com as
  empresas do `contas_sicoob.json` e a caixa *gravar este cliente na empresa
  escolhida* (marcada por padrão). Recusa gravar cliente que já pertence a
  outra empresa — a mesma regra do `sicoob_contas.validar()`, porque contrato
  arquivado na empresa errada não se denuncia sozinho.
- *Confirmar* aplica na linha, recalcula a situação e marca a linha.
  *Cancelar* não mexe em nada.

A janela mora em `contratos/resolver.py`, e não dentro do `frame.py`: a aba já
tem 390 linhas e as duas coisas mudam por motivos diferentes.

### 3. Onde o dado mora

`Achado` ganha:

| campo | para quê |
| --- | --- |
| `anexos_da_obra` | a lista que o `levantar` já busca e hoje joga fora; é o que a janela mostra |
| `marcado` | entra nesta rodada de arquivamento |
| `contrato_manual` | o contrato foi escolhido à mão |
| `empresa_manual` | a empresa foi definida à mão |

`pipeline.arquivar` passa a filtrar `marcado and not revisao and anexo`: a
decisão vira dado, e não estado escondido na tela — é o que deixa a regra sob
teste.

Funções puras novas no `pipeline`:

- `pode_resolver(achado)` — falso quando nem obra existe (`obra_id` vazio):
  sem obra não há anexos para escolher, e a janela não deve abrir;
- `aplicar_resolucao(achado, anexo, empresa_nome)` — aplica, recalcula o que
  ainda falta, devolve o motivo restante ("" quando resolvido);
- `reaplicar(achados, escolhas)` — depois de uma nova busca, devolve as
  escolhas do contrato pelo NOME do arquivo; se o arquivo sumiu da obra,
  a casa volta a perguntar.

A escolha do contrato vale para a sessão (`{(obra, unidade): nome do arquivo}`
na aba). A escolha da empresa vira cadastro, então vale para sempre e para as
outras abas: `sicoob_contas.adicionar_cliente_erp(empresa, cliente)` grava por
arquivo temporário + troca atômica, preservando o resto do JSON — é o cadastro
do fechamento inteiro, não pode ficar pela metade.

O resumo `.txt` do mês registra *contrato escolhido à mão* e *empresa definida
à mão*. Daqui a seis meses, essa linha é a diferença entre auditar e adivinhar.

### 4. O que a marca NÃO desliga

- a **conferência de conteúdo** continua valendo, inclusive no contrato
  escolhido à mão: PDF que fala de outra casa, outro comprador ou outro valor
  é retido com o motivo;
- o limite de **260 caracteres** do caminho continua barrando antes de gravar;
- casa sem contrato ou sem empresa continua sem poder ser marcada.

## Fora do escopo

- "arquivar mesmo divergindo": combinação rara (escolha manual + divergência) e
  cara de errar. Se aparecer na prática, entra depois, com registro no resumo.
- lembrar a escolha do contrato entre execuções do app: cada mês tem casas
  diferentes, e o cadastro de cliente→empresa (esse sim permanente) já resolve
  o motivo que se repete.
- corrigir o nome do anexo no ERP a partir do app.

## Testes

Puros, sem tkinter e sem ERP:

- `adicionar_cliente_erp`: grava; é idempotente; recusa cliente que já é de
  outra empresa; preserva o resto do JSON (raiz, contas, pastas_vazias);
- `escolha.ordenar_para_escolha`: candidatos primeiro, resto em ordem;
- `pipeline`: `marcado` nasce certo, `arquivar` respeita a marca,
  `aplicar_resolucao` limpa a revisão só quando há contrato E empresa,
  `pode_resolver` é falso sem obra, `reaplicar` devolve a escolha e desiste
  quando o arquivo sumiu.

A janela em si não entra em teste: é tkinter, e o que ela tem de decisivo mora
nas funções acima.
