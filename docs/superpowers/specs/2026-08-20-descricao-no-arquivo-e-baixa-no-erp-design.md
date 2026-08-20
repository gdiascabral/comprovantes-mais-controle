# A descrição no arquivo, e a baixa no ERP — design

Data: 20/08/2026
Aba: Pagamentos do Dia

Duas coisas que a primeira remessa reenviada (nº 000003, aceita pelo banco)
deixou à vista:

- **Parte 1 — a descrição.** Na tela de pendências do SicoobNet, o boleto
  mostra o nome do fornecedor e o Pix não mostra nada. O dono quer ler ali a
  descrição da planilha, que é como ele reconhece o pagamento.
- **Parte 2 — a baixa.** O retorno diz quem foi pago. Isso hoje morre na tela:
  a baixa no Mais Controle continua sendo feita à mão, lançamento por
  lançamento.

---

# Parte 1 — a descrição vai no arquivo

## O que foi medido

Conferido byte a byte contra a remessa 000003 e o retorno do dia 17:

| Campo | Tamanho | Hoje | O banco mostra |
|---|---|---|---|
| `09.3J` Nome do Cedente (boleto) | 30 | nome do fornecedor | como "Observação" |
| `24.3A` Informação 2 (Pix) | 40 | 38 brancos + tipo de conta | nada (está vazio) |

E o teste decisivo: no par remessa/retorno de 17/08, **o banco devolveu
`09.3J` idêntico nos doze pagamentos**. Ele não valida o campo contra o
título, não o reescreve com o cedente de verdade — trata como etiqueta nossa.

## O que muda

**Pix:** a descrição entra nas 38 posições livres de `24.3A`. Não há troca: o
espaço estava vazio. O tipo da conta de destino continua nas duas últimas.

**Boleto:** a descrição entra nas 30 posições de `09.3J`, no lugar do nome.
O dinheiro é roteado pelo código de barras, não por esse campo.

Descrição vazia cai para o nome do fornecedor: em branco, aquela coluna não
identificaria nada, e a linha ficaria pior do que está hoje.

## A identidade não se perde

Este é o ponto que faz a troca ser aceitável, e não uma perda:

- **no arquivo**, o J-52 continua levando `cedente_nome` e `cedente_documento`
  de verdade — é lá que mora "quem recebe", e foi ele que a primeira remessa
  real ensinou a preencher;
- **no nosso registro**, `Historico._favorecido` passa a ler o nome do J-52
  antes do `nome_cedente`. Assim a tela de retorno continua mostrando o
  fornecedor, mesmo com o arquivo levando a descrição;
- **no Pix**, nada muda: `15.3A` (Nome do Favorecido) já leva o nome, e o
  `_favorecido` já o lê do objeto `Favorecido`.

## O que isso custa

O comprovante do boleto no banco passa a exibir a descrição onde exibia o nome
do cedente. Decisão do dono em 20/08/2026, com o custo declarado: quem usar
aquele comprovante para identificar o fornecedor vai ler a descrição.

Risco em aberto: o manual do Sicoob pede brancos nas 38 posições do Pix. Encher
é desvio, e só o banco dirá se aceita — testável com um Pix pequeno.

---

# Parte 2 — a baixa no Mais Controle

## O caminho encontrado

Os endpoints saíram do bundle público do próprio ERP
(`acessar.maiscontroleerp.com.br/react-app/mc-react-app.js`), lendo o cliente
de API — não de captura de tráfego, que falhou duas vezes porque a janela
automatizada é indistinguível da janela do usuário.

```
GET   /payable-installments/{id}/default-paid   -> o corpo pré-preenchido
POST  /payables/{id}/paids                      -> cria a baixa
DELETE /payables/{id}/paids/{paidId}            -> desfaz
```

É o par simétrico de `POST /receipt-installments/{id}/receipts`, que
`aportes/mc_lancamentos.py` já usa.

**O corpo vem do ERP.** Pedimos o `default-paid` daquela parcela, trocamos a
data pela data real do pagamento (a que o banco devolveu no retorno) e
devolvemos. Montar o corpo à mão seria adivinhar o formato de hoje e quebrar
calado quando ele mudar.

## Fluxo

1. Você lê o retorno, como já faz.
2. O app separa quem voltou com ocorrência `00` (pago) e acha o lançamento de
   origem pelo `seu número` — o de-para já é gravado na geração (`referencia`).
3. Uma janela lista os pagos: quem, quanto, e o que será baixado. Nasce tudo
   marcado; o que você desmarcar não é baixado.
4. Confirmando, o app baixa um a um e relata o resultado de cada um.

Ocorrência que não é `00` nem recusa conhecida **não entra na lista** — fica
visível com o código do banco escrito, para você decidir à mão. Pagamento sem
`referencia` gravada também fica de fora, dizendo por quê.

## Onde o host se decide

Não se sabe se `/payables` mora no `legacy-api` (onde o recebimento mora) ou no
`prod-erp-api`. O `default-paid` é leitura: o app tenta o legado, e só troca de
host se ele responder 404. O host que funcionou vai para o log.

## Erros

Cada baixa é independente: uma que falhe não impede as outras, e o relatório
diz qual falhou e com que HTTP. Baixa duplicada é o risco real — por isso o
app pergunta ao `default-paid` antes, e um lançamento já baixado aparece na
lista já marcado como tal, fora da seleção.

---

# Testes

| Teste | O que prova |
|---|---|
| Pix com descrição | os 38 primeiros de `24.3A` levam o texto; os 2 últimos, o tipo de conta |
| Pix sem descrição | volta a 38 brancos — o layout não quebra |
| Boleto com descrição | `09.3J` leva a descrição; o J-52 continua com o nome real |
| Boleto sem descrição | `09.3J` cai para o nome do fornecedor |
| `Historico._favorecido` | com J-52 preenchido, devolve o nome, não a descrição |
| retorno → pagos | só ocorrência `00` entra; sem `referencia` fica de fora com motivo |
| baixa | usa o corpo do `default-paid`, com a data trocada pela do banco |
| baixa que falha | não derruba as outras; o relatório diz qual e por quê |
