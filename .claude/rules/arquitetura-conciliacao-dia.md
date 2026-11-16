---
paths:
  - "conciliacao_dia/**"
  - "tests/test_conciliacao_dia*.py"
---

# Arquitetura: conciliacao_dia/ (aba "Conciliação", grupo DIÁRIO)

Spec: `docs/superpowers/specs/2026-10-29-conciliacao-ofx-design.md`; plano:
`docs/superpowers/plans/2026-10-29-conciliacao-ofx.md`. Pedido do dono de
27/10/2026: os OFX do dia e a Prova de saldos numa aba só. Não confundir com
`conciliacao/` (a aba "Saldo de pagamentos", que é a Conciliação Diária
antiga): pasta nova de propósito, linha nova no `build.yml`.

Dois ambientes, e "Ler as contas do ERP" é o primeiro passo dos DOIS (a lista
do OFX e a Prova precisam saber quais contas do ERP são Sicoob e Inter):

- **Baixar OFX** — lista das contas Sicoob e Inter (as do pagamento do dia
  em cima, as outras embaixo), **nenhuma marcada de início**, período padrão
  ontem a hoje (até 2 anos, fim ≤ hoje). "Baixar e importar" baixa e importa
  sem parar; o resultado vem numa tabela no fim, uma linha por conta pedida.
- **Provar saldos** — a `tela_do_dia.prova_na_tela.ProvaNaTela`, que mudou de
  hospedeiro (saiu de Pagamentos do dia, que ficou só com o link «Prova de
  saldos → aba Conciliação», `TelaDoDiaFrame.ir_para_conciliacao`, ligado no
  app por `_abrir_se_pode("cdi")`). Liga depois da leitura do ERP. O saldo lido fica para o Pagamentos do dia (`tela_do_dia.saldos_para_o_dia`, 16/11/2026): o Buscar de lá não pede o login do Sicoob de novo e o Inter vem preenchido.

| Módulo | Decide |
|---|---|
| `ofx_regras.py` | puro: quais contas entram (`contas_para_ofx`), período (`periodo_padrao`, `validar_periodo`, `periodo_do_mes`), a conferência de cada OFX (`conferir_ofx`: ACCTID inteiro sem zeros à esquerda, nunca pelo fim; DTSTART/DTEND = o pedido), nomes que conferem a conta no Inter, a linha do resultado |
| `rodada.py` | sem tela: Sicoob (um login + outro acesso se a pessoa disser sim) → cada Inter (um QR por conta) → conferência → ERP só com os que conferem; Parar corta antes da próxima etapa |
| `importar_erp.py` | "Selecionar novo OFX" em `#/transactions/<id>`, numa aba do robô, esperando o NOME da conta antes do arquivo e "Arquivo OFX importado com sucesso" depois. Só importa, não concilia |
| `extratos_inter_mes.py` | o mês inteiro do Inter para o fechamento (aba Acessórias): só vai à pasta da empresa o OFX conferido; nada vai ao ERP |
| `frame.py` | a tela fina; três threads como no resto do app |

**Revisão de dinheiro (16/11/2026), o que impede importar errado:**

- **Nunca o mesmo lançamento duas vezes** (`importados.py`): o registro
  `Pagamentos do dia/OFX/importados.json` guarda, por conta do ERP, a chave de
  cada lançamento enviado (FITID; sem FITID, data + valor + histórico, e dois
  iguais continuam dois). Antes do envio o OFX perde o que já foi —
  confirmado ou sem confirmação —, e o que sobra vai em
  `para o ERP/<banco> <erp_id>.ofx`, conferido pelo hash logo antes do envio.
  Nada novo = "nada novo", sem ir ao ERP. Registro ilegível = nada é
  importado. As contas tratadas saem da marca no fim da rodada. **É por
  máquina**: rodar o Baixar OFX em duas máquinas não se enxerga (a medir se o
  ERP descarta FITID repetido; enquanto isso, uma máquina só).
- **Três desfechos no ERP** (`importar_erp`): `ok`, `falhou` (nada saiu) e
  `incerto` (o arquivo foi entregue e a confirmação não veio) →
  "não verificado", entra no registro, nunca é reenviado; confere-se no
  extrato do ERP.
- **A conta certa**: `about:blank` entre uma conta e outra (o aviso verde da
  anterior não confirma a seguinte), endereço com o `erp_id`, nome EXATO.
- **Um OFX, uma conta**: no Inter a repetida é pelo LOGIN (duas contas do ERP
  no mesmo login: só uma); na rodada, dois OFX com o mesmo ACCTID: só o
  primeiro.
- **A conta ignorada pelo dono** (23/10/2026) vem de `conciliacao_ofx.json`
  na pasta do app (`ofx_periodo.ignoradas`), nunca do código: o repositório é
  público.
- Sicoob que quebra (Chrome, login) não derruba o Inter.

**Threads.** ERP na vaga do Anexar (`anx.submeter(..., dona=self)`, com
`avisar_se_ocupado(aba=self)` antes — o arquivo está nos `_CHAMADORES` de
`tests/test_abas_em_paralelo.py`); Sicoob e Inter na thread `ofx-bancos`
(o `SicoobClient` e o Chrome de cada Inter nascem e morrem nela); a tela só
lê a fila.

**Travas** (`comprovantes_app.py`): a aba pergunta a Extratos, Baixar
comprovantes, Reler Sicoob, Conferir agendamentos, Autenticar no banco, a
Remessa e os extratos do Inter da Acessórias antes de abrir um banco; e todos
esses perguntam a ela (`sicoob_ocupado` = o Baixar OFX OU a Prova). A Prova e
o Baixar OFX perguntam um ao outro.

**Inter**: o celular decide a conta no QR (medido em 29/10/2026), por isso o
aviso "confira a empresa no celular" e a conferência da conta na tela ANTES
de pedir o OFX (`inter_saldo.conferir_conta`); o pedido sai de dentro da
página com os três cabeçalhos da sessão (`inter_saldo.escutar_sessao`), a
resposta é um `fileUrl` S3 baixado como download do próprio Chrome.

**Menu**: chave `cdi`, depois de "Saldo de pagamentos" e antes do Controle de
aportes — depois do 9º item, para os Ctrl+1..9 de antes não mudarem
(`tests/test_tela_do_dia_controle_menu.py`). Ícone 🔁 = RepeatAll nas duas
tabelas do `widgets.py`. O aprovador não a vê (`ABAS_DO_PAPEL`).

**Testes de janela** em `tests/test_conciliacao_dia_frame.py` (fixture
`raiz`): só com a tela livre.
