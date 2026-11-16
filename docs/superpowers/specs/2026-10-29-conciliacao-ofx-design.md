# Aba Conciliação: Baixar OFX e Provar saldos — desenho

Data: 29/10/2026. Perguntas respondidas pelo dono na conversa do mesmo dia;
caminhos do Inter medidos ao vivo com ele (QR lido por ele).

## Por quê

Todo dia o financeiro baixa o OFX de cada conta no banco e importa um por um
no Mais Controle ("Selecionar novo OFX"), para depois conciliar. A ferramenta
solta `ferramentas/ofx-periodo` provou o caminho do Sicoob em 23/10/2026, mas
fora do app, sem o porteiro do ERP e sem o Inter. E a Prova de saldos, que é a
outra metade da conciliação do dia, mora hoje no meio de Pagamentos do dia.

## O que o dono decidiu

| Pergunta | Resposta |
|---|---|
| Onde fica | Aba nova **"Conciliação"**, grupo DIÁRIO, com dois ambientes: **"Baixar OFX"** e **"Provar saldos"** |
| Que contas | As do pagamento do dia primeiro e as demais embaixo; **nenhuma marcada** de início |
| Que período | Padrão **ontem a hoje**, editável |
| Importar | **Sem parar**: baixa e importa em seguida; o resultado aparece no fim ("importar não causa nada no app; se errado, corrige depois") |
| Prova de saldos | **Muda de lugar** para a aba Conciliação; em Pagamentos do dia fica um link "Prova de saldos → aba Conciliação" |
| conta ignorada pelo dono | Sempre ignorada (regra de 23/10/2026) |
| Mensal | Depois de aprender, a opção de baixar os extratos do Inter entra na rotina mensal da aba Acessórias |

## O que é

### Ambiente "Baixar OFX"

1. **A lista** — uma linha por conta do ERP que é do Sicoob ou do Inter
   (cadastro: `contas_mc` diz o banco e a empresa; Sicoob tem o número no
   cadastro, Inter tem o login em `contas_inter.json`). Dois grupos: "Do
   pagamento do dia" (as linhas Sicoob/Inter do painel, a mesma régua da
   Prova de saldos — `prova_saldos.contas_da_prova`) e "Outras". Tudo
   desmarcado; "Marcar todas" por grupo. A conta ignorada pelo dono não aparece.
2. **O período** — duas datas (padrão ontem e hoje), validadas: início ≤
   fim, fim ≤ hoje, no máximo 2 anos (limite do Inter).
3. **"Baixar e importar"** — na ordem:
   - **Sicoob** (as marcadas): o Chrome do Sicoob do app (`SicoobClient`,
     login do dono), conta por conta pelo caminho já provado
     (`acessar_conta` → extrato → período → `exportar_ofx`); conta que não
     está neste login entra na pergunta do outro acesso, como o "Reler
     Sicoob" (`saldo.ler_em_dois_acessos` é o modelo).
   - **Inter** (as marcadas), uma conta por vez, no perfil dela: "Leia o QR
     da X — confira a empresa no celular" (medido: **o celular decide a
     conta**, não o perfil). Com a sessão aberta, CONFERE a conta (número e
     nome da tela, `inter_saldo.conferir_conta`) e pede o OFX de dentro da
     página: `GET cd.web.bancointer.com.br/ib-pfj/cc/extrato/exportar/v2?
     formato=OFX&data-inicio=DD-MM-AAAA&data-fim=DD-MM-AAAA` com os três
     cabeçalhos da sessão que a página usa (`inter_saldo.escutar_sessao`);
     a resposta é `{fileUrl}` (S3 assinado, que não aceita fetch) e o
     arquivo vem como download do próprio Chrome (`<a href=fileUrl>` +
     `expect_download`). Medido em 29/10/2026: 9 lançamentos de 28 a 29/10.
   - **Conferência de cada OFX antes de importar** (módulo puro): `ACCTID`
     = número da conta (do cadastro no Sicoob, da tela no Inter),
     `DTSTART`/`DTEND` = o período pedido. OFX que não confere **não é
     importado** e vai ao resultado com o porquê.
   - **ERP**: numa aba do robô no Chrome do app (porteiro, vaga do Anexar),
     uma aba só para todas: `#/transactions/<id da conta>` → espera o nome
     da conta → "Selecionar novo OFX" (`input[type=file]` pelo
     `expect_file_chooser`) → espera "Arquivo OFX importado com sucesso".
     Só importa; não concilia nada. O id vem da conta marcada na lista
     (nunca de um casamento por nome).
4. **Rótulo e Parar** — "Sicoob conta 3 de 12", "Leia o QR da VXZ",
   "Importando 5 de 15"; Parar corta a fila (o que já importou fica).
5. **Resultado** — tabela no fim: conta, período, lançamentos, situação
   (importado / não importado: porquê). Os OFX ficam em
   `Pagamentos do dia/OFX/AAAA-MM-DD HHhMM/` (nome = dígitos da conta).

### Ambiente "Provar saldos"

A Prova de saldos de hoje, levada como está (com os ajustes medidos em
29/10/2026), para a aba Conciliação. O botão sai de Pagamentos do dia e fica
lá só o link. As travas continuam (`sicoob_ocupado`, `inter_ocupado`,
`outros_no_sicoob`); a aba Conciliação entra nelas, e o Baixar OFX também
(Sicoob e Inter abertos por duas abas ao mesmo tempo disputariam o mesmo
perfil).

### Rotina mensal (aba Acessórias)

Um passo novo antes de "Gerar os .zip": **"Baixar extratos do Inter"** do mês
escolhido (dia 1 ao último), uma conta por QR, gravando o OFX (e o PDF, se o
dono quiser — a decidir na hora de implementar) na pasta da empresa do mês
(`sicoob_pastas`, a mesma árvore que o Extratos Sicoob cria), conferido pelo
mesmo módulo puro (conta + mês inteiro, como `sicoob_baixar.validar_ofx`).
Assim o .zip do escritório leva o Inter junto. Não importa no ERP.

## Regras de segurança

- **ERP só pelo Chrome do app** (porteiro); nunca login HTTP por fora.
- **Bancos só no Chrome do app**, nos perfis do app; nada digita senha nem
  clica em aceite; os cabeçalhos da sessão do Inter nunca são gravados.
- **Conta incerta não importa**: OFX de outra conta, de outro período, sem
  `ACCTID` ou vazio de cabeçalho → "não importado: porquê".
- **Conta errada aberta no Inter** (QR lido na empresa errada) → nada é
  baixado dessa conta; o resultado diz "leia o QR com a empresa X no
  celular".
- **Nada real no repositório**: números, nomes e endereços de arquivo do
  banco vêm do cadastro (fora do repo); testes com dados fictícios.

## Peças (uma responsabilidade cada)

| Peça | Faz |
|---|---|
| `conciliacao_dia/ofx_regras.py` (puro) | quais contas aparecem e em que grupo, validação do período, conferência do OFX (conta + período), nome do arquivo, linhas do resultado |
| `extratos_sicoob/ofx_periodo.py` | OFX do Sicoob de um período (datepicker de `ofx-periodo/baixar_ofx.py`), por conta |
| `baixar_comprovantes/inter_ofx.py` | OFX do Inter de um período, pela sessão da página |
| `conciliacao_dia/importar_erp.py` | importa um OFX numa conta pela tela, na aba do robô |
| `conciliacao_dia/frame.py` | a aba: os dois ambientes, lista, período, rótulo, Parar, resultado |
| `tela_do_dia/prova_*` | continuam onde estão; só o botão muda de frame |
| `acessorias/` | o passo mensal do Inter |

Pasta nova = linha nova no `build.yml` e no `tests/test_empacotamento.py`.
O nome `conciliacao_dia/` evita confusão com `conciliacao/` (o painel do
Saldo de pagamentos).

## Testes

Puros: grupos e ordem da lista, a conta ignorada pelo dono fora, período (ontem/hoje,
início > fim, futuro, > 2 anos), conferência do OFX (conta errada, período
errado, sem ACCTID, conta com zeros à esquerda), nome do arquivo. Com
dublês: a fila (Sicoob → Inter → ERP), Parar no meio, OFX que não confere
não chega ao ERP, conta Inter errada não baixa. De tela (só com "tela
livre"): a aba monta com altura, o link de Pagamentos do dia leva à aba.
Ao vivo com o dono: uma rodada de ontem a hoje em 2 contas Sicoob + 1 Inter,
importando de verdade.

## Fora do escopo

Conciliar no ERP; OFX de outros bancos; reimportar o mesmo período (o que o
ERP faz com lançamento repetido se mede na primeira rodada ao vivo e vai
para o resultado, sem trava nova agora — decisão do dono).
