# Pagamento pela API do Sicoob com aprovação do diretor — design

Data: 26/11/2026 · Estado: aguardando revisão do Gustavo · Dono da decisão final de produção: os diretores.

## 1. Objetivo

Num dia normal ninguém abre o banco: o app monta o lote do que está apto, um
diretor aprova pelo portal no celular, um robô no servidor do escritório paga
pelas APIs do Sicoob, busca o comprovante pelo código do próprio pagamento,
anexa no título certo do Mais Controle com a descrição do HTML e dá a baixa.
Nenhum pagamento em dobro, nenhum comprovante no título errado.

## 2. Decisões tomadas no brainstorming (26/11/2026)

| # | Decisão | Origem |
|---|---|---|
| D1 | Aprovação numa aba "Aprovar pagamentos" do portal, com login da nuvem (Supabase Auth); o servidor carimba quem aprovou. Apps Script/Notion fora do caminho da aprovação. | Gustavo |
| D2 | Um aprovador basta; quem preparou o lote nunca aprova. | Gustavo |
| D3 | 1ª entrega: boleto, Pix (chave e copia-e-cola) e convênios. TED fica para depois (exige `id_token` extra, ainda não entendido). | Gustavo |
| D4 | Teto = o total aprovado; sem teto por item ou por dia. | Gustavo |
| D5 | O robô paga logo após a aprovação (consulta a cada 1–2 min). | Gustavo |
| D6 | Anexo e baixa no ERP automáticos só com estado REALIZADO, pelo código do próprio pagamento. A regra de 29/10 ("prova do banco só pré-marca") continua para o que for pago fora da API. | Gustavo |
| D7 | Robô no servidor do escritório (não GitHub, não nuvem): certificado só lá, app do Sicoob travado no IP do escritório. | Gustavo |
| D8 | Boleto não é agendado para outro dia: paga-se no dia. | Gustavo |
| D9 | Só Sicoob. Inter, TED e outros bancos seguem pelo HTML/remessa. | suposição aceita |
| D10 | Regras de "apto" = as que já existem no HTML/planilha do Pagamentos do dia. | suposição aceita |

## 3. Peças

```
App (aba Pagamentos do dia) → monta e envia o LOTE congelado à nuvem
Nuvem (Supabase)            → guarda lote, aprovação e o livro de execução; RLS decide quem pode o quê
Portal (GitHub Pages)       → só a TELA: aprovador vê, tira itens, aprova, acompanha, para
Servidor do escritório      → o ROBÔ: lê a aprovação, paga no Sicoob, comprovante, anexo e baixa no ERP
```

### 3.1 Lote congelado (app)
Passo novo "Enviar para aprovação" depois da conferência. Cada item:
título do ERP, conta pagadora, tipo (`boleto` | `pix_chave` | `pix_qr` | `convenio`),
código de barras / chave / copia-e-cola, valor, CPF/CNPJ esperado de quem recebe,
descrição (mesma regra do HTML: centro de custo na frente, limite 100 caracteres),
link do anexo, resultado da conferência (✓/⚠).
O lote recebe um hash (SHA-256 do conteúdo canônico dos itens). Mudou qualquer
campo → outro lote, outra aprovação. Itens fora da API (Inter, TED, outros
bancos) não entram e são listados à parte.

### 3.2 Nuvem (tabelas novas, só acrescentar)
- `lote_pagamento` (dia, hash, total, preparado_por = auth.uid(), quando).
- `lote_item` (lote, ordem, título, conta, tipo, dados, valor, documento_esperado, descricao, anexo, conferencia).
- `lote_aprovacao` (lote, hash, aprovado_por = auth.uid(), quando). Recusada pelo banco se: papel ≠ `aprovador`, aprovado_por = preparado_por, hash diferente do lote, dia ≠ hoje, ou já existe aprovação.
- `lote_retirada` (lote, item, motivo ≥ 3 caracteres, quem): tirar item gera o lote restante, com hash novo.
- `lote_evento` (lote, item, passo, estado, detalhe, chave_pagamento, quando): livro de execução gravado pelo robô (service role, só no servidor).
- `robo_pulso` (quando): "estou vivo" a cada minuto.
- `robo_parar` (quem, quando, motivo): botão Parar; vale até uma linha "retomar".
Sem `update` e sem `delete` para ninguém além do service role; RLS com `privado.e_ativo()` e o papel `aprovador` que já existe em `perfil`.
Um título só pode estar em um lote ativo (não concluído) por dia.

### 3.3 Portal — aba "Aprovar pagamentos"
Login separado do portal: e-mail e senha da nuvem (o login de hoje do portal vem do Notion e não serve para a nuvem confiar). Tela por conta com favorecido, valor, tipo, descrição, anexo e conferência; "Tirar item" (motivo obrigatório) e "Aprovar lote" (confirma mostrando o total). Depois de aprovar vira acompanhamento item a item, com "Parar pagamentos" e o aviso de robô parado. Testada a 375 px.

### 3.4 Robô (servidor)
A cada 1–2 min, se não houver `robo_parar` ativo: pega lote aprovado de hoje com hash conferido e, item por item (Pix respeitando 1 requisição/s):
1. Relê o título no ERP: em aberto, mesmo valor, sem comprovante. Senão: `nao_pago:erp_mudou`.
2. Paga:
   - `pix_chave`: `POST /pix-pagamentos/v2/pagamentos` → documento do dono da chave ≠ esperado ⇒ `nao_pago:chave_de_outro`; igual ⇒ grava o endToEndId e `POST /pagamentos/confirmacao` com a descrição.
   - `pix_qr`: `POST /pagamentos/qrcode` (o banco confere valor e CNPJ).
   - `boleto`: `GET /pagamentos/v3/boletos/{codigo}` (beneficiário e valor batem? senão `nao_pago:boleto_diferente`) → grava a `x-idempotency-key` (`coop-conta-UUID`) ANTES → `POST /boletos/pagamentos/{codigo}` com `descricaoObservacao`.
   - `convenio`: `GET /arrecadacao/codigo-barras/{codigo}` → `POST .../pagamentos`; o comprovante vem na resposta.
3. Nunca soma pagamentos acima do total aprovado.
4. REALIZADO → comprovante pelo código do pagamento (boleto pela chave de idempotência, Pix pelo endToEndId, convênio pelo NSU) → PDF com a descrição dentro e no nome → anexa no título → baixa → relê o título para confirmar → `concluido`.

## 4. Erros

| Situação | Resultado |
|---|---|
| ERP mudou | `nao_pago:erp_mudou` |
| Dono da chave Pix diferente | `nao_pago:chave_de_outro` |
| Boleto com beneficiário/valor diferente na consulta | `nao_pago:boleto_diferente` |
| Pix EM_PROCESSAMENTO | consulta até REALIZADO/NAO_REALIZADO; nada é anexado antes |
| Recusa do banco (saldo, horário, erro) | `nao_pago:<motivo do banco>` |
| Queda no meio de um pagamento | ao voltar, primeiro consulta pelo código gravado; nunca paga de novo às cegas |
| Robô parado | portal e app mostram "robô parado há X min" (pelo `robo_pulso`) |
| API fora do ar | `nao_pago`; segue o HTML/remessa de hoje |
| Falha no anexo ou na baixa | `pago:falta_anexar`; só essa parte é repetida, com aviso se não conseguir |

Pagar nunca é repetido sozinho; buscar comprovante e anexar podem ser repetidos.
A aprovação vale só no dia; o que não foi pago volta naturalmente na lista de amanhã.

## 5. App — telas
- Passo "Enviar para aprovação": resumo por conta e lista do que não entra pela API.
- Texto do WhatsApp com o link da aprovação (substitui a "Lista do diretor").
- Painel "Acompanhar": estado de cada item, aviso de robô parado, "Parar pagamentos".
- Item `nao_pago` ganha "Mandar para o HTML".

## 6. Credenciais
Só no servidor, em pasta de chaves fora do repo: client_id e certificado (parte privada). Nunca no GitHub, na nuvem, em log ou no chat. App do Sicoob de produção com as permissões estritamente necessárias e restrição ao IP público do escritório.

## 7. Testes
- Regras puras (sem rede): montagem do lote, hash, retirada, soma ≤ aprovado, título em dois lotes, cada linha da tabela de erros, retomada depois de queda.
- Nuvem: só aprovador aprova; quem preparou não aprova; hash e dia conferidos; sem update/delete.
- Robô contra o Sandbox do Sicoob (mocks: provam formato e cabeçalhos, não regra), incluindo queda no meio.
- Portal a 375 px com print antes do merge.

## 8. Fases
1. Sandbox — tudo montado e testado sem dinheiro.
2. Leitura em produção — app de produção só leitura: saldo, extrato, consulta de boleto reais.
3. Piloto — uma conta, poucos pagamentos reais por alguns dias, conferidos no banco; HTML/remessa em paralelo.
4. Liberação — demais contas Sicoob, uma por vez.

## 9. Depende de fora (antes da fase 3)
- Sicoob: habilitar as contas para pagamento via API; confirmar se é um app por conta; limite por operação.
- Diretores: aprovar a troca da assinatura do master no banco pela aprovação no portal.
- Gustavo: criar o app de produção, subir a parte pública do certificado, informar o IP do servidor; criar o usuário da nuvem com papel `aprovador` para cada diretor.
- Portal: o repositório é de outra conta; a aba entra por pull request revisado.

## 10. Fora da 1ª entrega
TED, Inter, WhatsApp automático, notificação no celular, aprovação item a item, teto por item/dia.

## 11. Desvios aprovados na execução do plano 1 (26–27/11/2026)

Decididos pelo coordenador durante a execução, com revisão independente; o dono revisa no PR.

- **Hash → imutabilidade no banco.** Em vez do SHA-256 do lote, `lote_item` não aceita update/delete, item novo é recusado depois da aprovação, e a aprovação grava os itens e o total, conferidos por gatilho. Retirada de item vai em `lote_aprovacao.retirados` (jsonb), não numa tabela `lote_retirada`.
- **Papel `robo` em vez de service role.** O robô entra com usuário próprio; a RLS só o deixa ler e acrescentar evento e pulso.
- **Erros depois de iniciar (substitui a tabela da seção 4 nesses casos).** Depois de INICIADO, só o banco dizendo "não realizado" (Pix) vira `nao_pago`. Recusa do banco, queda, API fora do ar ou resposta estranha viram `em_processamento` "conferir no banco", contam no total e são consultados de novo — o item fica preso até alguém conferir ("resolver à mão" no plano 3). Antes de iniciar, continua `nao_pago`.
- **Título que chegou a iniciar nunca volta para a API**, mesmo que termine `nao_pago`: vai pelo HTML. O mesmo código de pagamento (boleto, convênio, QR) também não entra em dois lotes vivos.
- **Boleto só é dado como pago com o comprovante EFETIVADO/PAGO/REALIZADO.** Convênio só com NSU e valor pago igual ao do item.
- **Título já baixado ou com comprovante no ERP** quando o robô pagou vira alerta de possível pagamento em dobro, não "concluído".
- **Boleto e QR sem CPF/CNPJ no cadastro ficam fora do lote** (como o Pix por chave já ficava).
- **Pix e convênio só da conta da credencial** até o plano 3 resolver a conta de débito.
