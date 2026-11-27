# Aba "Pagamentos" no portal — design

Data: 27/11/2026 · Estado: aguardando revisão do Gustavo · Substitui os planos 2 e 3 da spec `2026-11-26-pagamento-pela-api-sicoob-design.md` (o plano 1, o núcleo do servidor, é o PR #203, em rascunho).
Desenho das telas: `2026-11-27-aba-pagamentos-no-portal-telas.html` (mesma pasta).

## 1. Objetivo

Hoje a rotina de pagamentos do dia roda no app do PC. A ideia é que ela passe para uma aba **"Pagamentos"** do portal:
- a equipe prepara pelo navegador;
- o diretor aprova pelo celular, **conta por conta**;
- o servidor do escritório lê, paga, confirma, baixa o comprovante, anexa e dá baixa no Mais Controle, sozinho.

O Mais Controle continua sendo a base dos lançamentos. Num dia normal, ninguém abre o app nem o banco.

## 2. Decisões (Gustavo, 27/11/2026)

| # | Decisão |
|---|---|
| D1 | Arquitetura A. O **servidor** lê e paga, reaproveitando as regras do HTML de hoje (`pagamentos_dia/`) com o porteiro do ERP. A **nuvem** (Supabase) é a ponte. O **portal** é só a tela. |
| D2 | Escopo: pagamentos **e saldos**. O saldo do banco vem pela API (Sicoob e Inter) e o do ERP pelo porteiro do servidor. |
| D3 | Às **07:30** o servidor lê sozinho, pela API do Sicoob e do Inter, o saldo de cada conta e o que entrou e saiu ontem. Confirma os pagamentos de ontem: os da API e os feitos à mão, que ficam pré-marcados (regra de 29/10, a pessoa confirma). Lê também o saldo do ERP. |
| D4 | A leitura do dia (ERP e anexos) roda no botão **Buscar**, quando a equipe quiser. Pode haver vários envios ao diretor no mesmo dia. O filtro é por **período, "de … até …"** (padrão: de hoje até hoje). Quando o período passa de hoje, vale a regra do dono de 13/11 ("Adiantar boletos dos dias seguintes pelo Buscar"): dos dias seguintes só entra o que se paga por código de barras (boleto e convênio), e o que for adiantado entra no dia de hoje. Datas passadas entram inteiras, com os vencidos primeiro, como no HTML. |
| D5 | Na aba Pagamentos, a equipe entra com o **login da nuvem do app**. Cada ação fica carimbada com o nome de quem fez. |
| D6 | Ações de revisão iguais às de hoje: **liberar** (com motivo), **tirar do dia** e **paguei à mão**. Dado errado se corrige no Mais Controle e depois se clica "Buscar" de novo. O portal não edita o ERP. |
| D7 | O que não vai pela API (Inter, outros bancos, TED, item em revisão sem liberar) aparece em **"Pagar à mão"**, com o Copiar e o QR e o código de barras grandes do HTML de hoje (tela cheia ao clicar), mais o botão **Paguei**. |
| D8 | O diretor aprova **conta por conta**. Cada conta aprovada começa a pagar na hora. |
| D9 | **Aporte** é uma demanda criada na tela, com valor, conta de onde sai, quem aporta e como chega. Vira item da conta que **manda** o dinheiro e é aprovado junto com ela. Depois de confirmado, o servidor **lança o aporte no ERP sozinho**, já baixado e com o comprovante. |
| D10 | O Inter, nesta versão, é **só leitura** (saldo e extrato). Pagar pelo Inter continua à mão. |
| D11 | **"Ver anexo"** abre o próprio arquivo (PDF ou imagem) numa janela do portal. O servidor guarda uma cópia, feita durante o "Buscar", numa área **privada** da nuvem (Storage), que só abre com login e por um link de poucos minutos. Ao lado fica o link "abrir no Mais Controle". |
| D12 | **Aportes e transferências** têm um painel próprio, com todas as contas: saldo no banco, a pagar no dia e saldo depois dos pagamentos. Duas ações:<br>• **+ Aporte**: janela com os aportadores possíveis (o cadastro da aba Aportes) e o valor de cada um;<br>• **Transferência entre contas**: só entre contas do **mesmo grupo**, ou seja, da mesma empresa (ex.: Terra Bela Inter ↔ Terra Bela Sicoob, Ipanema Sicoob ↔ Ipanema Inter, Morais Eng Caixa → Morais Eng Inter). O grupo vem da "empresa dona da conta" do cadastro. |
| D13 | O diretor vê, em cada Pix, **a chave**, **o nome e o documento do dono da chave** e **o centro de custo** de cada item. O dono da chave é consultado no Sicoob pelo servidor no "Enviar ao diretor" (`pix_iniciar`, que só consulta o DICT e não paga) e conferido com o cadastro (✓ ou ⚠). |

Continuam valendo as decisões da spec de 26/11: um aprovador basta; quem preparou não aprova; o teto é o total aprovado; o robô fica no servidor; anexo e baixa automáticos só com o pagamento realizado; boleto não é agendado para outro dia. Também valem as regras de dinheiro do plano 1 (seção 11 daquela spec).

## 3. O dia

```
07:30 SERVIDOR: saldos Sicoob/Inter (API) + o que entrou/saiu ontem + saldo do ERP (porteiro)
      → nuvem: "saldos do dia", "o que ontem confirmou" (pagos de ontem pré-marcados)
QUANDO A EQUIPE QUISER: "Buscar" → servidor lê o dia (regras do HTML) → portal mostra
      → revisão → "+ Aporte" se faltar saldo → "Enviar ao diretor" (congela por conta)
DIRETOR: um cartão por conta → tirar item (motivo) → "Aprovar esta conta"
SERVIDOR (1–2 min): paga na ordem → confirma → comprovante → anexa e dá baixa no ERP
O DIA TODO: "Pagar à mão", acompanhamento, alertas, "Parar pagamentos"
```

## 4. Telas (detalhe no HTML)

1. **Preparar (equipe).**
   - Topo: período **de … até …**, **Buscar**, hora da última leitura e progresso ("lendo… 34 de 120").
   - Um bloco por conta: saldo do banco e saldo do ERP (com hora), total apto e **falta R$ X**.
   - Painel **Aportes e transferências** (D12): todas as contas, com saldo no banco, a pagar no dia e saldo depois. Os botões são **+ Aporte** (janela com os aportadores e o valor de cada um) e **Transferência** (só para conta do mesmo grupo).
   - Em cada conta, três grupos:
     - **Pode pagar**;
     - **Precisa de revisão (OLHE / NÃO LI)**, com motivo, conferências e anexo ("ver anexo" abre o arquivo: D11);
     - **Pagar à mão**.
   - No pé: **Enviar ao diretor**, com o resumo por conta.
2. **Pagamentos do dia (diretor, celular).**
   - Um cartão por conta enviada: saldo, a pagar, aporte e itens com anexo.
   - Cada item mostra favorecido, valor, **centro de custo** e descrição. Nos Pix aparece também a **chave** e **de quem ela é** (nome e documento consultados no banco, com ✓ ou ⚠ contra o cadastro). Nos boletos, o beneficiário.
   - **Tirar item** (com motivo) e **Aprovar esta conta** (a confirmação mostra o total).
   - Depois de aprovar, o cartão mostra o andamento.
3. **Acompanhamento (todos).**
   - Estado de cada item: aguardando → pagando → pago ✓ → anexado e baixado ✓.
   - No topo, os itens que pedem atenção: **ALERTA de pagamento em dobro** e **conferir no banco**, com o motivo e o botão **Resolvi** (com nota), que é o "resolver à mão".
   - **Parar** (qualquer pessoa da equipe) e **Retomar** (só o diretor).
   - "Servidor parado há X min".
   - "O que ontem confirmou", para a equipe confirmar o que ficou pré-marcado.

Todas as telas são testadas a 375 px antes do merge.

## 5. Aporte, saldo e ordem

- **Transferência entre contas do mesmo grupo** (D12): sai pela API quando a conta de origem é Sicoob, por transferência entre contas Sicoob ou por Pix pela chave para outro banco. Quando a origem é Inter ou Caixa, não há API de pagamento nesta versão, então ela aparece em **Pagar à mão**, com os dados prontos para copiar. O servidor também lança no ERP a transferência paga, como saída numa conta e entrada na outra, com o comprovante.
- **Como o aporte chega:**
  - de Sicoob para Sicoob: **transferência** pela API da Conta Corrente, sem chave;
  - para outro banco: **Pix por chave**, preenchida do cadastro ou digitada;
  - sem chave e para outro banco: vai para **Pagar à mão**, porque a API de Pix só paga por chave ou QR. TED fica para depois.
- **Quem aporta:** a regra de 29/10 propõe a divisão entre JV e JC e a pessoa ajusta. O lançamento no ERP segue as regras da aba Aportes de hoje (saída e entrada, centro de custo, entidade).
- **Saldo antes de cada item:** antes de **iniciar**, o servidor lê o saldo do banco pela API. Se não cobre, o item fica **aguardando saldo**, sem dinheiro em jogo, e o servidor tenta de novo a cada rodada. No fim do dia, o que sobrou volta para a revisão de amanhã com o aviso "não houve saldo". Saldo do ERP diferente do banco só gera aviso.
- **Ordem dentro da conta aprovada:**
  1. aportes que saem da conta;
  2. boletos e convênios, do maior para o menor;
  3. Pix, do maior para o menor.

  Se o saldo acabar, a fila para no item que não cabe; os seguintes não furam a fila.

## 6. Peças novas

- **Servidor** (Python, no repositório do app, rodado pelo Agendador; o modo nuvem do `pagamento_api.robo` abre aqui):
  - a **leitura das 07:30** (saldo e extrato pela API, saldo do ERP pelo porteiro);
  - o **atendente de pedidos**, que pega um "Buscar" na nuvem e roda a leitura do dia com `pagamentos_dia/`, sem tela, guardando uma cópia dos anexos no Storage privado (D11);
  - no "Enviar ao diretor", a consulta do dono de cada chave Pix no DICT (D13);
  - o **pagador** do plano 1, com o ERP de verdade, o saldo antes de cada item, a ordem e o aporte.
- **Nuvem** (migrations novas, só ler e acrescentar):
  - saldos e extrato do dia;
  - pedido de leitura e o resultado da leitura (as linhas do HTML do dia);
  - decisões da revisão (as tabelas `pagamento_decisao` / `pagamento_a_mao` / `pagamento_agendado` que já existem);
  - aporte do dia;
  - "resolvi" de um item preso.
  - O lote e a aprovação reaproveitam as tabelas do plano 1. A aprovação passa a ser **por conta**: um lote por conta e por envio.
- **Portal** (repositório PORTAL-MORAIS, por PR): a aba Pagamentos com as três telas, falando com a nuvem por `supabase-js` com o login da nuvem.

## 7. Entregas

| # | Entrega | Move dinheiro? |
|---|---|---|
| E1 | Leitura das 07:30 e saldos na tela (Sicoob e Inter pela API, ERP pelo porteiro), mais "o que ontem confirmou" | Não |
| E2 | Preparar no portal: Buscar no servidor, revisão, Pagar à mão e Enviar ao diretor. Substitui o HTML do app | Não |
| E3 | Diretor e pagamento pela API (o plano 1 com o ERP real e as travas pendentes), começando por um piloto de uma conta | Sim |
| E4 | Aportes: transferência ou Pix, e lançamento no ERP | Sim |

Cada entrega tem spec própria, se precisar detalhar mais, além de plano e PR próprios. O app do PC continua funcionando até a E2 estar provada. Durante a transição, cada dia é tocado por um sistema só.

## 8. Depende de fora

- **Gustavo:**
  - criar o app de produção do Sicoob, só de leitura (E1);
  - conseguir a credencial da API do Inter (E1);
  - autorizar cada migration (um "pode" para cada).
- **Sicoob:** habilitar as contas para pagamento via API; dizer se é um app por conta; informar os limites; confirmar os formatos pendentes listados no mapa do `pagamento_api` (E3).
- **João e Júlio:** aprovar a aprovação pelo portal no lugar da assinatura no banco (antes da E3).
- **Portal:** o repositório é de outra conta, então cada entrega entra por PR.

## 9. Fora desta versão

- Pagar pelo Inter, pela API.
- TED.
- Notificação no celular.
- Editar dado no portal.
- Aprovar item por item: o diretor tira itens e aprova a conta.
