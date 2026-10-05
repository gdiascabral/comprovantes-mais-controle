# Contratos: vários por casa e o distrato — desenho (05/10/2026)

## O pedido do dono

"Preciso conseguir baixar vários contratos da mesma casa, porque em algumas
recebemos o sinal e depois faz o distrato, porém preciso pagar imposto sobre
esse contrato. Tentar casar os contratos com distratos e me dar a opção de um
botão para selecionar 'Distrato'; os que eu marcar, você salva o contrato e no
nome dele, no final, coloca '(Distratado)'."

## Como é hoje (código lido em 05/10/2026)

- A aba Contratos lê os recebimentos de venda do mês no ERP, agrupa por casa
  (`regras.imoveis_do_mes`) e, para cada casa, procura o contrato nos ANEXOS
  DA OBRA no ERP (não há Clicksign no app).
- `escolha.contrato_de` escolhe UM contrato: ignora todo anexo com
  DISTRATO/RESCIS/ADITIVO etc. no nome; com dois ou mais nomes, fica com o
  "mais completo" (ASSINADO, VENDEDOR...) ou o pipeline baixa e compara os
  bytes; sobrando dois diferentes, a casa vai para revisão.
- `pipeline.arquivar` recusa gravar um segundo contrato da mesma casa na
  pasta (`destino.mesmo_contrato_na_pasta`) e confere o conteúdo contra o
  COMPRADOR do recebimento (contrato de outro comprador é retido).
- Caso real na fixture dos testes (obra de 52 anexos): a casa 01 tem
  `DISTRATO ... C1` e dois `CONTRATO DE COMPRA E VENDA ... CS 01` com nomes
  diferentes. Hoje ela cai em revisão.

## Decisões do dono (05/10/2026)

1. **Salva só o contrato.** O PDF do distrato não é arquivado; o contrato
   marcado sai com " (Distratado)" no fim do nome.
2. **O app sugere pelo nome do comprador.** Quando a casa tem distrato, o app
   lê os PDFs: o contrato cujo comprador aparece no distrato já vem marcado
   como Distrato. O dono confere e desmarca se quiser. Se não der para ler,
   vem desmarcado.

## O desenho

**Casa sem distrato: nada muda.** Toda a regra de hoje (um contrato, o mais
completo, desempate por bytes, revisão) continua igual.

**Casa com distrato** (algum anexo da casa com DISTRATO ou RESCIS no nome):

1. Na BUSCA, o app baixa os contratos de compra e venda da casa (até 6) e os
   distratos (até 3), e lê o texto (o mesmo `leitura.abrir_pdf` do arquivar).
2. De cada contrato tira o comprador do trecho `COMPRADOR: NOME,` (é como os
   contratos assinados na Clicksign qualificam as partes).
3. Agrupa os contratos por comprador. Dentro de cada grupo vale a regra de
   hoje (bytes iguais = o mesmo; um "mais completo" = ele; senão revisão).
4. Cada grupo vira uma LINHA na tabela. A linha cujo comprador é o do
   recebimento é a linha da casa; as outras aparecem como "outro contrato da
   casa".
5. A coluna nova **DISTRATO** (☐/☑) vem marcada quando os sobrenomes do
   comprador daquele contrato aparecem no texto de um distrato da casa. Clicar
   alterna, em qualquer linha que tenha contrato.
6. No arquivar: o contrato com Distrato marcado sai como
   `CONTRATO DE COMPRA E VENDA <obra> CS 01 - <COMPRADOR DO CONTRATO> (Distratado).pdf`.
   A conferência do conteúdo usa o comprador lido do próprio contrato e não
   cobra o valor do recebimento (é outra venda). A trava "já há contrato desta
   casa na pasta" passa a aceitar os outros contratos da mesma casa gravados na
   mesma rodada.
7. A Acessórias lista a linha como `... Casa 01 - Fulano (Distratado)`.

## Fora deste trabalho

- Distrato sem nenhum contrato de compra e venda da casa: continua revisão
  ("nenhum anexo de COMPRA E VENDA").
- Mais de 6 contratos numa casa com distrato: revisão, com o motivo.
