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
