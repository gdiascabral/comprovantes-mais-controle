# Aporte de fora dividido entre os sócios + Autenticar no banco — design

Aba "Pagamentos do dia" (`tela_do_dia/`). Decisões do dono de 28 e 29/10/2026,
tiradas uma a uma na conversa. Duas entregas, cada uma com o seu PR, nesta
ordem: **PR 1 (aporte)** e depois **PR 2 (autenticar)**.

## A ordem do dia na tela (dono, 29/10/2026)

1. Conferir no banco o que foi pago antes, inclusive os aportes ("Autenticar
   no banco", PR 2).
2. Saldos bancários (Reler Sicoob, Prova de saldos).
3. Aportes, com o aviso de igualar do Controle de aportes (PR 1).

---

## PR 1 — Aporte de fora dividido + aviso de igualar

### Regras do negócio (dono)

- Os dois sócios (os nomes do `confirmar_antes.json`, os mesmos da caixa de
  reembolso do cartão 2) aportam **só** na Morais Engenharia (conta-mãe,
  Inter ou Sicoob), sempre meio a meio; num dia um pode aportar mais ou
  sozinho, e o outro iguala depois.
- Na aba Regras do MODELO eles **não** são aportadores da conta-mãe (só das
  próprias participações). O caso "mesmo sócio, mesma conta, na Regras e de
  fora" não acontece na prática; se acontecer, vira **pendência**, nunca soma
  calada (ver "Travas").

### O que muda na tela

**Janela "Dividir aporte entre os sócios"** (`janelas.py`, fina). Abre no
"Mandar para a aba Aportes", ANTES do envio, quando há movimento à mão com
origem `decisoes.DE_FORA` e destino na conta-mãe (`aportes.mae`) ainda não
mandado hoje. Uma linha por movimento: destino, valor, campo do sócio 1 e
campo do sócio 2.

- Nasce **meio a meio**; centavo ímpar vai para o primeiro nome (regra fixa,
  escrita na tela: "R$ 0,01 a mais para <nome 1>").
- A soma de cada linha tem de bater ao centavo com o valor; linha que não
  bate fica vermelha com a diferença, e o "Mandar" apaga.
- Parte zero é permitida (um aporta sozinho) e não vira operação; as duas
  zero é recusado.
- Cancelar: **nada** vai, nem as outras operações do clique (a decisão é
  refeita no próximo clique).
- Ao lado de cada sócio, o aviso de igualar daquela conta (abaixo).

Movimento de fora com destino que **não** é a conta-mãe continua como hoje
(não vai para a aba Aportes) e ganha linha no Registro: "aporte de fora em
<conta>: não é da conta-mãe — lance na aba Aportes à mão".

**Aviso de igualar** (dono: "fulano tem que aportar R$ X para igualar
beltrano", "fulana precisa igualar os aportes"). Vem da apuração da aba
**Controle de aportes** (`controle_aportes.apurar` —
`LinhaAportador.diferenca`, "quanto falta para igualar"), nunca de conta
nova feita aqui. Aparece:

- no cartão 3 (Aportes), numa faixa de avisos, uma frase por aportador com
  `diferenca > 0`: "<nome> precisa aportar R$ X para igualar <líder> em
  <conta>"; contas igualadas não aparecem; conta com leitura duvidosa diz
  "Controle de aportes: <conta> não fechou (<motivo>) — veja a aba";
- na janela de divisão, para a conta-mãe.

**O Controle roda junto com o Buscar** (dono: "toda vez que rodar os pgtos
do dia, automaticamente tem que rodar a rotina do controle"). No fim do
Buscar (depois dos saldos, como na ordem do dia), a tela pede ao
`ControleAportesFrame` a mesma leitura do botão dele (`atualizar`), pela vaga
dele no navegador (`submeter(dona=)`), e recebe a apuração por um gancho. Se
a vaga estiver ocupada, o `_reler_quando_livre` que já existe espera. Falha
do Controle não derruba o Buscar: vira a frase "Controle de aportes não
lido: <motivo>" no cartão 3.

### Regra nova (módulo puro, com teste)

`tela_do_dia/aporte_dos_socios.py`:

- `meio_a_meio(valor, nomes) -> dict` — a divisão inicial em Decimal.
- `validar_divisao(valor, partes) -> str` — "" ou o recado.
- `operacoes_dos_socios(movimentos, divisoes, mae, entidades, subcontas,
  data, enviados) -> Envio` — cada parte > 0 vira `Operacao` "Aporte de
  Capital" sócio → conta-mãe (`_modo` do cadastro), chave própria
  `defora:<sócio>|<conta>` em `enviados_aportes`; já mandado vira pendência
  `_ja_mandado` (como hoje, nunca "mandar de novo").
- `avisos_de_igualar(apuracoes) -> list[str]` — as frases do cartão.

`para_aportes.operacoes` ganha o parâmetro `socios_de_fora` (o `Envio`
acima é somado ao dela, com as mesmas pendências, avisos e o mesmo
`enviados_apos`). A gravação antes de entregar e a recusa por arquivo do dia
ilegível continuam valendo, sem mudança.

### Travas

- Sócio que não casa (um só) no cadastro da aba Aportes
  (`casar_no_cadastro`): pendência "cadastre <nome> na aba Aportes".
- `confirmar_antes.json` sem exatamente dois nomes: a janela não abre e o
  Registro diz por quê; os movimentos de fora ficam como hoje.
- Conta-mãe que é subconta de investidor no cadastro: pendência.
- Par sócio → conta-mãe que **também** está na aba Regras com valor no dia:
  pendência "esse sócio já aporta nesta conta pela aba Regras (R$ X) — tire
  um dos dois", nos dois lados (mesma família da "Distribuição em dobro").
- Aporte não se repete: a chave `defora:` segura o segundo clique, mesmo com
  valor corrigido.

### Testes (sem janela)

Meio a meio com centavo ímpar; soma que não bate; parte zero; as duas zero;
já mandado (com valor igual e diferente); sócio fora do cadastro; arquivo do
dia com a chave antiga e a nova; destino que não é a mãe; par também na
Regras; `avisos_de_igualar` com conta igualada, devedor, leitura duvidosa;
guarda por AST de que o frame chama a leitura do Controle no fim do Buscar.

---

## PR 2 — Autenticar no banco

### O que muda na tela

O cartão "Agendados a confirmar" fica **sempre no topo**, ao abrir a aba
(lê os pendentes na nuvem; não espera o Buscar), com o botão **"🔎
Autenticar no banco"**. Uma rodada:

1. relê no ERP, pelo Chrome do app, os títulos dos pendentes (o caminho do
   Buscar, `nuvem_do_dia`) — sem isso nada se diz de "sumiu"/"mudou";
2. Sicoob: por conta com pendente, a lista de comprovantes **EFETIVADOS**
   (`GET /api/comprovantes/pagamentos`, `so_efetivados`, `sem_pix`) e a
   lista de Pix (`/api/pix/lancamentos`), do dia anterior ao pendente mais
   antigo até hoje; contraprova: `extratos_sicoob/pendencias.py`;
3. Inter: **o QR por conta é lido aqui** (dono, 29/10/2026): na mesma
   sessão, saldo (`inter_saldo`), 2ª via (PAGAMENTO/DARF) e extrato Pix pela
   API da página. O saldo é guardado em `DD MM - saldos do inter.json`, e a
   Prova de saldos o reaproveita no mesmo dia em vez de pedir QR de novo;
4. o resultado vira `prova_extra` de cada pendente (`agendados.situacao`) e
   a pré-marca ☑; o "Pago" continua perguntando.

A foto do agendado (`foto_do_lancamento` / `para_marcar`) passa a guardar a
**linha digitável** e a **descrição colada** (a do HTML). Agendado antigo,
sem esses campos, casa só por valor + descrição do ERP.

### Casamento (módulo puro `tela_do_dia/autenticar.py`, com teste)

Sempre na **mesma conta**, um comprovante prova um agendado só, data entre
o dia anterior ao agendado e hoje.

1. Linha digitável / código de barras (normalizados para os 44 dígitos).
2. Valor ao centavo + descrição colada pela régua de prefixo de
   `agendamentos_sicoob.mesma_descricao`.
3. Favorecido só desempata.

- Lista sem linha nem descrição (a medir, tarefa 0): o comprovante é aberto
  em HTML **só** quando há candidato de mesmo valor (`detalhar`, sem gerar
  PDF nem salvar arquivo) — dono, 29/10/2026.
- Ambíguo = "responda". N agendados iguais × N comprovantes iguais:
  pré-marcam todos; N × menos de N: nenhum.
- Pix: só da lista de Pix; o espelho TRANSF.PIX da lista comum é tirado
  (`sem_pix`).
- Comprovante de agendamento (não EFETIVADO) não prova.
- Pendência de assinatura que casa com o agendado derruba a prova ("ainda
  pendente de assinatura no Sicoob").
- Lançamento dividido em N boletos: só pré-marca com as N partes achadas,
  cada uma pela sua linha.
- Prova do banco nunca vence "sumiu" nem "mudou" (regra de hoje).

**Aportes do dia anterior** (dono: "inclusive os aportes"). Fonte: as
operações que a aba Aportes lançou (pagamento e recebimento de Aporte de
Capital/Investidor/Distribuição) com data entre o último dia útil e hoje,
lidas pelo Chrome do app. Prova: a SAÍDA na conta de origem quando ela é
Sicoob/Inter (transferência ou Pix efetivado, mesmo valor); entrada vinda de
fora (sócio) só se prova pelo extrato — a medir na tarefa 0. Nesta entrega o
aporte **só mostra** "✓ banco: …" ou "responda": não há resposta gravada na
nuvem para aporte (tabela nova seria outro pedido).

### Sessões e travas

- Thread própria `sicoob-autenticar` / `inter-autenticar`, nunca a do ERP;
  só leitura, sem PDF, sem assinar, sem aceite.
- Conta aberta no Sicoob conferida (`conta_aberta` + `mesma_conta`) antes de
  cada lista; outra conta = "não lida" com o porquê.
- Entra em `sicoob_ocupado` desta aba e em `ComprovantesFrame.inter_ocupado`;
  recusa com `outros_no_sicoob` (Extratos, Baixar comprovantes, Reler
  Sicoob, Conferir agendamentos, Prova de saldos).
- Outro acesso do Sicoob: pergunta e lê só as que faltaram
  (`baixar_em_varios_logins`), como o Reler Sicoob.
- Parar corta a espera do QR e do login.

### Tarefa 0 (medição, antes do código do PR 2)

Com o login do dono no Sicoob e "tela livre" dele: listar comprovantes e
Pix de 2–3 contas e anotar SÓ os nomes dos campos (nunca valores) — se há
linha digitável, observação/descrição, favorecido; e os campos do extrato de
entrada. Nada vai ao repositório além dos nomes de campo.

### Testes (sem janela)

Pix contado duas vezes; dois pagamentos iguais (2×2 e 2×1); comprovante de
agendamento; conta aberta errada; dividido em N boletos (todas × faltando
uma); pendência de assinatura derrubando; travas `sicoob_ocupado` /
`outros_no_sicoob` / `inter_ocupado`; agendado antigo sem linha na foto;
Prova de saldos reaproveitando o saldo do Inter do dia (e recusando o de
outro dia).

---

## Processo

Plano por PR, aprovado pelo dono. `revisor-dinheiro` antes de juntar; todos
os testes sem janela (`ls tests/test_*.py | xargs grep -L "raiz\|Tk()\|tk.Tk\|barra\b"`);
teste com janela só com "tela livre". Juntar e liberar só com pedido do
dono. Nada de nome real, CPF, conta ou saldo no repositório.
