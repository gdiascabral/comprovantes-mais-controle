# HTML dos pagamentos: três níveis, parcela e leitura de letra de mão

Data: 19/11/2026. Estado: aguardando a revisão do dono.

## Pedido

O dono paga pelo HTML dos pagamentos e pediu, em 19/11/2026:

1. deixar claro, em cada linha, se ela está 100% apta, se o app não conseguiu
   ler alguma coisa ou se algo pede atenção;
2. ler melhor os arquivos, inclusive os escritos à mão;
3. dizer se o título é parcelado, qual parcela está sendo paga e se há
   observação para aquela parcela.

Vale para os dois HTML: o das contas PJ (`pagamentos_dia/html_pagamentos.py`)
e o das PF (`pagamentos_dia/html_pf.py`).

## O que foi medido antes de desenhar

- O app tem cerca de 25 textos de situação (`APTO`, `APTO* (reembolso)`,
  `ATENÇÃO — sem dados de pgto`, `ATENÇÃO — anexo não lido`...). "Não li" e
  "li e não bate" saem os dois como ATENÇÃO.
- Em 60 anexos de dois fornecedores que mandam papel escrito à mão, 38 são só
  imagem, sem texto. São três tipos: recibo de talão; pedido de balcão
  preenchido à mão (empresa ou obra, ordem de compra, endereço com quadra e
  lote, itens com unitário e total, total); e o mesmo pedido fotografado com o
  comprovante do cartão por cima, com o nome de quem pagou escrito à mão (o
  reembolso do sócio).
- Leitura de teste por um modelo com visão, em miniatura: o total bateu com o
  lançamento em 10 de 11. O erro foi um 4 lido como 9, que o comprovante do
  cartão na outra foto do mesmo título desmente.
- Em cerca de 12.400 lançamentos de seis meses, uns 240 (2%) são de título
  com mais de uma parcela. A lista de a pagar traz o total de parcelas
  (`numberOfFinancingInstallments`) e não traz o número da parcela.

## Parte 1 — três níveis por linha

### Regra

Módulo puro novo, `pagamentos_dia/nivel.py`, com teste sem janela:

```
nivel_da_linha(registro) -> Nivel(nome, motivos, conferido)
```

- `nome`: `PODE_PAGAR`, `OLHE` ou `NAO_LI`.
- `motivos`: frases curtas, em português simples, na ordem de gravidade.
- `conferido`: a lista do que foi conferido e o resultado de cada item
  (valor, quem recebe, ordem de compra, endereço, parcela), com três
  estados: bate, diverge, não conferido.

A regra não inventa conferência: ela só classifica o que `montar_registros`
já decidiu (`status`, `conferencia`, `obs`, `valor_diverge`) e o que as duas
partes seguintes acrescentam.

| Nível | Quando |
|---|---|
| Não li | o app não conseguiu ler algo de que a linha depende: anexo que não baixou, anexo sem texto que nem o OCR leu, título cuja lista de anexos não veio, QR ou linha digitável ilegível, parcela cujo número não foi lido |
| Olhe | o app leu e algo pede julgamento: valor ou documento que diverge, boleto de outra empresa, vários boletos no título, pagar à mão, reembolso não confirmado, alterado durante a leitura, liberado, editado ou à mão na tela do dia, mesma cobrança em dois lançamentos, vencido, leitura feita por IA (fase 1) |
| Pode pagar | nenhum dos dois acima e todos os itens de `conferido` que se aplicam à linha batem |

"Não li" ganha de "Olhe" quando os dois valem: o que não foi lido é o que
impede de julgar o resto.

### O que NÃO muda

- **O bloqueio do Copiar continua o de hoje** (`html_pagamentos._motivo_do_bloqueio`,
  `html_pf.bloqueio_duro`). O nível é o que a linha MOSTRA; não libera nem
  trava nada sozinho.
- Planilha, remessa e tela do dia não mudam. O `status` continua existindo e
  aparecendo: a remessa e a conferência dependem do texto dele.

### Tela

- Em cada linha, uma etiqueta do nível (verde, amarela, vermelha) no lugar em
  que hoje fica o `status`, com os motivos embaixo e a lista do que foi
  conferido.
- No topo, ao lado do quadro-resumo, três contadores clicáveis que filtram as
  linhas por nível.
- Cor nunca é o único sinal: a etiqueta traz o texto do nível.

### Medição antes de ligar (feita em 19/11/2026)

Medido em 62 HTML já gerados (3.946 linhas, de setembro a novembro de 2026),
lendo `status`, `conferencia` e `bloqueio` de cada linha:

- 3.499 linhas saíram APTO (com as variantes); só 734 delas (19% do total)
  não têm nenhum "?" na conferência. Exigir "nenhum ?" para "Pode pagar"
  deixaria quatro em cada cinco linhas fora dele. **Regra descartada.**
- Os "?" mais comuns: endereço (1.606), NF (1.401), valor (1.119, mais 494
  de "valor/fornecedor ?") e fornecedor (1.046).
- **O valor não foi conferido contra documento nenhum em cerca de 4 de cada
  10 linhas**, quase todas Pix: 1.352 de 2.266 linhas de Pix. Nos boletos o
  código de barras prova o valor, e 84% sairiam "Pode pagar".

Regra que vale: os itens ESSENCIAIS são dois, **valor** e **quem recebe**.

- "Pode pagar": os dois conferidos e nenhum motivo de "Olhe" ou "Não li".
  Endereço, NF e ordem de compra não conferidos aparecem na lista do que foi
  conferido, como "não conferido", e não derrubam o nível.
- "Não li": algum essencial não conferido, além dos casos da tabela.

Com essa regra, nas mesmas 3.946 linhas (classificador aproximado, pelo
texto da conferência): 50% "Pode pagar", 38% "Não li" (34% só por valor não
conferido), 7% "Olhe" e 4% com o valor conferido e quem recebe não.

Duas consequências:

1. A primeira tarefa do plano é descobrir POR QUE o valor fica sem conferir
   nas linhas de Pix (anexo em foto, nota cujo texto não traz o valor da
   parcela, título sem documento de valor): amostra de 50 linhas, causa por
   causa. Se parte for leitura local que dá para consertar, isso vem antes
   da IA.
2. A Parte 3 deixa de ser acessório: é ela que tira linhas de "Não li".

## Parte 2 — parcela

- Título com `numberOfFinancingInstallments` maior que 1: a leitura do dia
  pede o título inteiro (`leitura_do_dia.titulo_no_erp`, que já existe para
  os boletos somados) e acha a posição da parcela em `installments[]`, pela
  ordem de vencimento.
- O registro ganha `parcela = {"numero": k, "total": n}` e `obs_parcela`
  (a observação do detalhe da parcela, que o app já lê).
- Tela: "Parcela 3 de 10" na linha, com a observação logo abaixo. Em parcela
  única nada aparece.
- Título parcelado COM observação vai para "Olhe" ("a parcela tem
  observação: leia antes de pagar"): o app não interpreta texto livre.
- Falha fechada: título que não leu, ou parcela que não se acha na lista,
  mostra "parcelado em N — número da parcela não lido" e a linha vai para
  "Não li".
- Só leitura, pelo Chrome do app. São 2% dos lançamentos; o custo é uma
  consulta por título parcelado.

**A provar ao vivo:** o formato de `installments[]` na resposta de
`trade-payables/<id>` pela sessão da `mc_api` (o próprio `titulo_no_erp`
declara que o endereço ainda não foi medido por ela).

## Parte 3 — leitura de letra de mão por IA

Decisão do dono (19/11/2026): pode usar serviço externo, e o provedor é a
API da Anthropic.

### Quando um anexo vai para a IA

Só quando todas valem:

- é de um título a pagar que entrou na apuração;
- é imagem, ou PDF sem camada de texto;
- o OCR local não achou linha digitável válida nem texto útil;
- não é comprovante de pagamento nem aviso "PAGAR PARA" gerado (esses têm
  texto);
- há chave de API configurada e o teto de leituras da geração não estourou.

### O que a IA devolve

Resposta estruturada, validada por esquema:

- tipo do papel (recibo, pedido de balcão, comprovante de cartão, outro);
- total em dinheiro e total por extenso;
- número da ordem de compra, número do documento e data;
- itens (descrição, quantidade, unitário, total);
- quadra e lote do endereço da obra;
- nome e valor do comprovante de cartão, quando houver;
- os campos que ela mesma considera duvidosos.

### O que o app faz com isso

Módulo puro `pagamentos_dia/leitura_ia.py`, com o cliente da API entrando
por parâmetro (dublê nos testes):

- `conferir(leitura, lancamento)` compara, em `Decimal`:
  - total lido × valor do lançamento, ao centavo;
  - **segunda prova** do total: o extenso, a soma dos itens ou o comprovante
    do cartão — pelo menos uma tem de concordar;
  - ordem de compra lida × a do lançamento;
  - quadra e lote, pela mesma normalização de `relatorio._conferir_endereco`.
- Leitura de IA **nunca vale sozinha**. Total que bate sem segunda prova
  fica "valor lido por IA, sem segunda prova".
- **Fase 1:** mesmo batendo tudo, a linha fica em "Olhe — lido por IA", com
  os valores lidos ao lado. Subir para "Pode pagar" é decisão do dono,
  depois de medir o acerto.
- Falha fechada: erro, estouro de prazo, recusa ou resposta fora do esquema
  deixam a linha em "Não li (IA não respondeu)". Nunca "sem anexo" e nunca
  apta.

### Guardar a leitura

- `leituras_ia.json` ao lado do exe, fora do repositório.
- Chave: id do anexo + tamanho + data de alteração, vindos da lista de
  anexos. Nunca a URL, que é assinada e muda.
- Cada anexo é lido uma vez; anexo trocado no ERP é anexo novo.
- Guarda o resultado, o modelo e a data, para auditar depois.

### Chave, custo e dados

- A chave fica cifrada pela DPAPI do Windows, como o login do ERP
  (`anexar/credenciais.py`). Nunca em texto, nunca no repositório, nunca no
  Registro.
- Sem chave, a função fica desligada e as linhas continuam em "Não li".
- Vai para a API só a imagem do anexo e a instrução. Nenhum dado do ERP.
- Teto de leituras por geração (60 por padrão) e a contagem de leituras no
  Registro e na atividade.
- Estimativa de custo, não medida: 1 a 2 centavos de dólar por recibo no
  modelo padrão (`claude-opus-5-5`).

### Medir antes de pôr no app

Roteiro fora do app, sobre os 38 anexos de imagem já baixados: manda cada um
à API, compara cada campo com o lançamento e conta acerto por campo e por
tipo de papel. É o primeiro gasto de API. Só depois disso a Parte 3 entra no
app.

## Decisões que são do dono

1. **Reembolso de sócio (`APTO* (reembolso)`):** fica em "Pode pagar", com
   "reembolso para X" visível, ou vai para "Olhe"? Recomendação: "Pode pagar".
2. **Pacote oficial da Anthropic no exe:** exige exe novo (download completo
   em todas as máquinas, uma vez). A alternativa é chamar a API direto com o
   que o exe já tem. Recomendação: pacote oficial.
3. **Modelo:** `claude-opus-5-5` por padrão. Um modelo mais barato é escolha
   do dono, depois da medição.
4. **Onde a chave mora:** só na máquina de quem gera o HTML, ou em todas.
   Recomendação: só em quem gera.
5. **Quando o que bate em tudo sobe para "Pode pagar":** depois de uma ou
   duas semanas de medição.
6. **Observação em título de parcela única:** também leva a linha para
   "Olhe", ou só aparece? Recomendação: só aparece, como hoje, para "Olhe"
   não virar a maioria.

## Ordem de entrega

1. Partes 1 e 2 juntas, num pedido de mudança. Não dependem de nada de fora.
2. Medição da Parte 3 fora do app.
3. Parte 3 no app, noutro pedido de mudança, com revisão de dinheiro própria.

## Testes

- `nivel.py`: uma linha de cada situação de hoje cai no nível esperado;
  "Não li" ganha de "Olhe"; nenhum `status` existente fica sem nível.
- Parcela: título de 1, de N, título que não leu, parcela fora da lista.
- `leitura_ia.py`: total que bate com e sem segunda prova; 4 lido como 9
  desmentido pelo comprovante; resposta fora do esquema; erro da API;
  leitura guardada não é pedida de novo; anexo trocado é pedido de novo.
- HTML: a etiqueta e os contadores saem; o bloqueio do Copiar é o mesmo de
  antes para cada registro dos testes existentes.

## Fora do escopo

- Mudar o que a remessa aceita.
- Ler por IA anexo que já tem texto.
- Qualquer escrita no ERP.
