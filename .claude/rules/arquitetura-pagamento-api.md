---
paths:
  - "pagamento_api/**"
  - "tests/test_pagamento_api*.py"
  - "supabase/migrations/20261126100000_pagamento_pela_api.sql"
---

# Arquitetura: pagamento_api/

> Criado em 26/11/2026 (plano 1 do pagamento pela API do Sicoob).
> Spec: `docs/superpowers/specs/2026-11-26-pagamento-pela-api-sicoob-design.md`.
> Mudou o código? Atualize AQUI.

## O que cada arquivo faz

- `__init__.py` — pagamento pela API do Sicoob com aprovação do diretor.
- `lote.py` — o lote do dia que vai para aprovação: o que pode ir pela API e o que fica fora. Puro, sem tela e sem rede; dinheiro em Decimal.
- `sicoob.py` — cliente das APIs de pagamento do Sicoob (Pix, boleto, convênio). Só fala HTTP, não decide nada; sessão injetada.
- `executor.py` — o que o robô faz com um lote aprovado: paga item a item, retoma depois de queda sem pagar duas vezes, anexa e dá baixa só com o pagamento realizado. Sicoob, ERP e livro entram como portas.
- `comprovante.py` — o comprovante em PDF montado do JSON do Sicoob, sem biblioteca nova; o JSON cru do convênio fica ao lado.
- `nuvem_lote.py` — o lado do robô na nuvem: lê o lote aprovado de hoje, anota cada passo, pulso e botão Parar. Entra com usuário próprio (papel `robo`), nunca com a chave de serviço.
- `robo.py` — o robô do servidor: uma rodada por chamada do Agendador, com trava contra rodada dupla; `--ensaio-sandbox` roda contra o Sandbox sem nuvem e sem ERP.

## Regras de dinheiro

- Depois de INICIADO, só o banco dizendo NAO_REALIZADO (Pix) vira NAO_PAGO. Todo o resto fica EM_PROCESSAMENTO ("conferir no banco"), conta no total e é consultado a cada rodada. Pagar nunca se repete às cegas.
- A chave do pagamento vai para o livro ANTES da chamada que paga. Gravar sem a linha voltar levanta `NaoGravou`.
- Boleto só é pago com comprovante EFETIVADO, PAGO ou REALIZADO.
- Anexo e baixa só com o ERP respondendo, e nunca baixa em título fechado.
- A soma do que saiu nunca passa do total aprovado.
- O banco (Supabase) recusa o segundo INICIADO do mesmo item e o INICIADO de item não aprovado, de outro dia ou com o robô parado. Tudo só acrescenta: sem update/delete.

## Desvio da spec: hash x imutabilidade

A spec previa conferir um hash SHA-256 do lote. Foi trocado pela imutabilidade no banco: itens só entram antes da aprovação, ninguém altera nem apaga linha, e a aprovação confere a soma. Mudar o lote depois de aprovado deixou de ser possível, e não só detectável.

## Achado do firewall

O Sicoob responde HTTP 200 com HTML ("Request Rejected") ao User-Agent padrão do `requests`. O cliente usa `USER_AGENT` fixo e trata resposta que não é JSON como erro. No ensaio, `Request Rejected` ou "não é JSON" significa firewall: parar e avisar, sem disfarçar a identificação.

## Os três planos

1. Núcleo (este): regras puras, cliente, executor, comprovante, migration, robô com ERP de ensaio e Sandbox.
2. Portal: preparar o lote e a aprovação pelo aprovador, botão Parar.
3. Produção: token OAuth e certificado, ERP de verdade, app importando o pacote, botão "resolver à mão" para itens presos em EM_PROCESSAMENTO.

## Limites conhecidos (revisão das Tasks 7 e 8, 27/11/2026)

- **Pasta por lote.** Os comprovantes e o JSON cru do convênio ficam em `<pasta_comprovantes>/lote-<id>`: a retomada acha o bruto sem risco de pegar o de outro lote com o mesmo título.
- **Uma rodada por vez.** `trava_da_rodada` usa trava do sistema sobre `robo.trava` (`msvcrt.locking` no Windows): ela some sozinha quando o processo morre, então não existe trava velha nem rodada apagando a trava da outra. Entre máquinas, quem segura é o índice `lote_evento_um_iniciado`.
- **Neste plano o ERP é o de ensaio.** `--config` contra a nuvem de verdade só roda com `"nuvem_de_ensaio": true`; sem isso, sai com erro. Rodar com o ERP de ensaio num lote real gravaria "concluído" sem nada no ERP, e o banco nunca mais libera o título pela API. O Agendador do servidor não é ligado antes do plano 3.
- **Só o dia de hoje (São Paulo).** O robô lê os lotes de `hoje_sp()`, o mesmo dia de `privado.hoje()`. Item que ficou EM_PROCESSAMENTO num lote de ontem não é mais consultado: fica para o botão "resolver à mão" do plano 3.
- **Leitura no teto do PostgREST** (1000 linhas) falha fechado (`LeituraCortada`): o robô não decide com livro incompleto.

## Travas obrigatórias antes do primeiro pagamento real (plano 3)

Achadas na revisão final do branch (27/11/2026); neste plano o robô só roda contra o Sandbox (`robo.rodada` sai com erro), então nenhuma delas tira dinheiro hoje.

- **O HTML e a remessa não enxergam o robô.** Item que chegou a INICIADO e não terminou em CONCLUIDO (ou em NAO_PAGO dito pelo banco) tem de sair do HTML/remessa do dia seguinte — senão alguém paga à mão o que o banco ainda vai liquidar. E o robô tem de continuar consultando os EM_PROCESSAMENTO de lotes passados (hoje só lê os de hoje).
- **Conta de débito do Pix e do convênio.** Esses pedidos não levam a conta: sai da conta da credencial. Neste plano o executor recusa Pix/convênio de conta diferente de `Portas.conta_da_credencial`; no plano 3, um cliente (token + certificado) por conta, ou `origem` no pedido, conforme o Sicoob responder.
- **Reconhecer o anexo do próprio robô.** Título que o robô pagou e já está baixado ou com comprovante vira `ALERTA_DOBRO` em FALTA_ANEXAR (não conclui). Inclui o caso de uma rodada que anexou e caiu antes de gravar: o adaptador do ERP do plano 3 deve dizer se o anexo é o PDF do robô (o nome é único) para concluir sozinho.
- **Confirmar com o Sicoob na fase 2:** valor do Pix com vírgula ("1,99") × ponto no QR; se `origem` é obrigatória no confirmar; se o DICT devolve o CPF da pessoa física inteiro (mascarado, todo Pix de PF cai em "chave de outra pessoa"); o significado de `transacao` no convênio (hoje um número único por pagamento) e o vocabulário da situação do comprovante (EFETIVADO/PAGO/REALIZADO).
- **Pix a 1 requisição por segundo:** o cliente espera entre chamadas de Pix (`Sicoob._vez_do_pix`). Um 429 no confirmar ainda fica EM_PROCESSAMENTO, que é o lado seguro.
- **Um erro de nuvem num lote derruba a rodada inteira** (`LeituraCortada`, recusa do INICIADO, robô parado): falha fechada, os outros lotes esperam a próxima rodada.
- **O mesmo código em lotes diferentes** (boleto, convênio, QR) é recusado no banco (`conferir_item`), como o título: é a cobrança duplicada do ERP.
- **Sem documento, fora do lote:** boleto e QR também exigem o CPF/CNPJ do cadastro, para conferir quem recebe.
