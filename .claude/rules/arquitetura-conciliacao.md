---
paths:
  - "conciliacao/**"
  - "tests/test_conciliacao*.py"
---

# Arquitetura: conciliacao/

> Trecho da seção "Arquitetura", movido do `CLAUDE.md` em 14/09/2026 sem mudar uma palavra.
> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI — este é o lugar deste texto agora.

- `conciliacao/` — aba Conciliação Diária: lê saldos e pagamentos a vencer e
  gera o painel do dia sobre o `MODELO.xlsx`, com o aporte mínimo por conta.
  **Foi o primeiro pacote de verdade do app, e desde 02/09/2026 todas as
  pastas são** (PR #38): as sete que faltavam ganharam `__init__.py`, os 105
  `sys.path.insert` viraram 3 — os três põem a RAIZ e nada mais (`motor.py`,
  `tests/conftest.py`, `cnab240/ferramentas/_ambiente.py`) — e todo import diz
  o caminho inteiro (`from conciliacao.frame import ...`, `from
  anexar.conferencia import ...`). O que isso desfez: com as pastas entrando
  planas no `sys.path`, nome de módulo era global, e havia `config.py` em três
  pastas, `frame.py` em três, e `conferencia.py`, `regras.py`, `pipeline.py` e
  `sicoob_baixar.py` em duas cada — `from conferencia import ConferenciaFrame`
  acertava a aba certa só porque `contratos/` não estava na lista de
  inserções. O prefixo `sicoob_` do `extratos_sicoob/` e o sufixo `_pagamento`
  de `pagamentos_dia/regras_pagamento.py` são as cicatrizes dessa época:
  continuam (renomear mexe em quem usa sem melhorar quem lê), mas deixaram de
  ser exigência. Quem guarda a regra é `tests/test_nomes_de_modulo.py`, que
  descobre as pastas em vez de listá-las e falha se alguma subpasta voltar ao
  `sys.path`. Módulo isolado roda `python -m pacote.modulo` da raiz — o
  `try/except ImportError` que cada arquivo carregava não existe mais; a sonda
  agendada é `python -m ferramentas.sonda`.
  Veio de um projeto separado que rodava por `.bat`, e os `.bat` continuam lá
  como plano B — **não rodar os dois ao mesmo tempo**, porque o ERP aceita uma
  sessão por usuário. É essa regra que explica o desenho: `coletar_com_pagina()`
  usa a página do Anexar em vez de abrir Chrome próprio, e a credencial da API
  sai do `login.dat` (DPAPI) em vez do keyring — duas senhas em cofres
  diferentes só criam a chance de uma envelhecer e o erro virar "login
  inválido" sem motivo aparente. `pipeline.py` não toca em navegador: recebe um
  `Snapshot` e devolve o resultado, e é por isso que os 9 arquivos de teste
  vieram junto sem alteração. **A coleta tem DOIS caminhos e UMA chave**
  (`pagamentos_via_api` na seção `erp` do `config.yaml`, padrão True desde
  08/09/2026): pela API, saldos E pagamentos vêm por HTTP num login só
  (`collect.coletar_pela_api` + `erp/payments_api.py`, que lê a mesma
  `payable-installments/paginated-result` que a tela consome, em janelas de
  15 dias, deduplicando pelo `id` da parcela — `value` vem NULL, o dinheiro é
  `remainingValue`, e o "agregado em aberto" vira a soma da lista do período)
  e a aba não abre Chrome; com a chave desligada vale o plano B de antes, a
  grade raspada (`coletar_pela_tela`/`coletar_com_pagina`, `erp/payments.py`,
  que ainda depende do layout). `conciliacao comparar-coleta --de --ate` roda
  os dois para o mesmo período e imprime, por conta, total e quantidade de
  cada um — abre o Chrome para a raspagem, e **ainda não foi rodado ao
  vivo**. `config.yaml`, `mapping.yaml` e `MODELO.xlsx`
  ficam FORA do repo (nome de empresa, estrutura do painel, rateios); as
  fixtures dos testes pulam quando faltam, então o CI passa sem os dados reais
  e a máquina de quem usa valida de verdade. Saída em
  `C:/Arquivos Morais/CONCILIACAO DIARIA/<ANO>/<MÊS>/`.
  **Conta nova entra no painel pelo app** (botão "Verificar contas novas",
  11/09/2026, `conciliacao/painel_novas.py`). Até então ela só virava o aviso
  "conta nova no ERP fora do painel" no resumo, e incluí-la era mexer à mão
  em TRÊS arquivos combinados — a linha do `MODELO.xlsx` com as fórmulas, a
  entrada do `mapping.yaml` e a faixa do `config.yaml` —, em que errar um não
  dá erro no Excel, dá saldo na linha de outra conta. A lista do botão é a
  MESMA régua do aviso (`rules.resolve_balances`). A linha nova entra no FIM
  (o mapa guarda o número de cada linha, e inserir no meio desceria todas),
  como cópia da última conta pelo `Translator` do openpyxl; as faixas que
  terminam na última conta esticam em todas as abas (totais, VLOOKUP da
  «Movimentações», formatação condicional, área de impressão) e o que está
  abaixo desce. Os dois YAML são editados como TEXTO, porque o comentário é
  metade do valor deles. Nada é trocado sem `_provar`: recarregar os três,
  `check_labels`, toda linha antiga casando com as MESMAS contas do ERP, cada
  nova com a sua e só com ela (nome parecido demais puxaria os pagamentos de
  outra conta) e uma planilha de prova pelo `workbook.build`. Os três de
  antes vão para `copias do painel/<data hora>/`, e troca que falha no meio
  (o Excel com o modelo aberto) devolve o que já tinha trocado. O nome da
  linha recusa `* ? ~` e `= < >` no começo: a coluna B é CRITÉRIO de SUMIF.
  O que continua fora: quem aporta na conta nova (aba «Regras», no Excel) e
  pagamento lançado em conta INATIVA no ERP, que não aparece na lista.
