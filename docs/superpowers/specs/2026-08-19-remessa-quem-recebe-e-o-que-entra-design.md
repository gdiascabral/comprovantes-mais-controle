# Remessa: quem recebe, e o que entra — design

Data: 19/08/2026
Aba: Pagamentos do Dia

Duas mudanças que se encontram na mesma tela e por isso vêm juntas:

- **Parte 1 — quem recebe.** O reembolso (`PAGAR PARA <pessoa>`) passa a poder
  entrar na remessa declarando a PESSOA, em vez de ser barrado sempre.
- **Parte 2 — o que entra.** Passa a existir marcação lançamento a lançamento,
  antes da planilha e antes do arquivo, e nada mais sai em silêncio.

---

# Parte 1 — Reembolso com favorecido próprio

## O problema

O aviso anexado `PAGAR PARA <pessoa>` manda o dinheiro para quem **não** é o
favorecido do lançamento. O segmento B do CNAB 240 carrega **um** par
nome/documento (campos 07.3B e 08.3B, obrigatórios), e hoje os dois lados do
par vêm de origens diferentes:

- nome e CPF/CNPJ do **fornecedor**, tirados do cadastro de Contatos do ERP
  casando pelo `paidTo` do lançamento;
- chave Pix **da pessoa**, tirada do próprio aviso.

O arquivo passaria a contradizer a si mesmo: ou o banco recusa o registro, ou
paga sob documento de terceiro. Por isso `remessa_dia.MOTIVO_REEMBOLSO` barra a
linha inteira desde 17/08/2026.

A trava está certa, mas é grossa demais: ela barra **todo** reembolso, inclusive
aquele em que a pessoa está cadastrada no ERP e o CPF dela é conhecido. Na tela
de conferência a linha ainda aparece com o nome do FORNECEDOR, então nem para
pagar à mão ela ajuda — quem for pagar precisa abrir o anexo para descobrir de
quem se trata.

## O que muda

O reembolso passa a poder entrar na remessa, **declarando a pessoa** — nome e
documento dela no segmento B, coerentes com a chave Pix dela. Só entra quando a
identidade for resolvida com certeza; sem isso, continua fora, agora com um
motivo que diz o que falta.

## Arquitetura

### Módulo novo: `pagamentos_dia/reembolso.py`

Um só assunto: *quem recebe o reembolso*. Passa a ser o dono do que hoje está
espalhado pelas 1.400 linhas do `relatorio.py`:

| Função | Origem |
|---|---|
| `nome_do_aviso(files)` | move de `relatorio.nome_do_reembolso` |
| `janelas_do_aviso(files, textos)` | **novo** — o recorte que os dois leitores dividem |
| `documento_do_aviso(files, textos)` | **novo** |
| `carregar(pasta)` / `chaves(cadastro)` | **novo** — lê o `pix_reembolso.json` |
| `identificar(...) -> Pessoa` | **novo** — a decisão |

`relatorio.py` importa `reembolso`; `nome_do_reembolso` e `_PAGAR_PARA` viram
apelidos, e os testes existentes e o uso de `relatorio._PAGAR_PARA` no
`pagamentos_frame.py` continuam valendo.

A dependência é de mão única — `relatorio` → `reembolso`, nunca o contrário —,
e é ela que decide o corte. `chave_pix_do_aviso`, `_chave_confiavel` e
`pix_do_reembolso` **ficam** no `relatorio`: eles dependem dos padrões de chave
Pix (`_PADROES_PIX`), que são do vocabulário de lá; arrastá-los para cá levaria
junto o módulo inteiro, ou obrigaria a um import circular.

O que os dois lados de fato compartilham é só o **recorte** — a janela de 300
caracteres depois do "PAGAR PARA" —, e é ela que mora aqui, em
`janelas_do_aviso`. Fossem dois recortes, bastaria um mudar de tamanho para a
chave e o documento passarem a falar de pedaços diferentes do mesmo papel.

`pagamentos_dia/*.py` já entra no `codigo.zip` por glob (`build.yml`,
`Copy-Item pagamentos_dia/*.py`). Arquivo novo nessa pasta **não** exige mexer
no workflow nem publicar exe novo.

### Onde a identidade é resolvida

Dentro do `relatorio.montar_registros`, no ramo `cls == "PAGAR_PARA"` que já
existe — é o único ponto do app que tem ao mesmo tempo os anexos, os textos
lidos (PDF ou OCR) e o lançamento. A remessa **não** redescobre nada: lê o
veredito pronto do registro, como já faz com `reembolso` e `valor_diverge`.

Isso obriga uma mudança de assinatura: `montar_registros` passa a receber
`participantes` (o mapa `{nome normalizado: CPF/CNPJ}` de
`mc_api.listar_participantes`). O `pagamentos_frame` já tem os dois — chama
`montar_registros` e guarda `self.participantes` — e só precisa passar o mapa
adiante. Sem o mapa, a função continua funcionando: cai para as outras fontes.

### Precedência do documento

Da fonte mais declarada para a menos:

1. **`pix_reembolso.json`** — cadastro local, ao lado do exe, fora do
   repositório (é CPF de gente). O formato novo aceita nome oficial, documento
   e chave; o formato antigo (`{nome: chave}`) continua sendo lido.
2. **Contatos do ERP** — casa o nome do rótulo `PAGAR PARA <nome>` contra o
   mapa de participantes. O papel `EMPLOYEE` já entra em
   `listar_participantes`, e reembolso costuma ser para funcionário: esta deve
   ser a fonte que resolve a maioria dos casos sem ninguém cadastrar nada.

   O casamento é por **igualdade, ou por começo ÚNICO** — e não pelo "casa por
   pedaço" que o app usa para nome de empresa. Nome de gente não aceita aquilo:
   "FULANO SOUZA" está dentro de "FULANO SOUZA LIMA" e de "FULANO SOUZA COSTA",
   que são duas pessoas com dois CPFs. Havendo mais de um começo possível, a
   fonte não responde. Nome ambíguo já sai do mapa na origem — dois
   participantes com o mesmo nome normalizado e documentos diferentes somem de
   lá —, então dos dois lados a ambiguidade chega como "não encontrado", que é
   o desfecho certo.
3. **Texto do aviso** — CPF/CNPJ que fecha o dígito verificador, procurado na
   MESMA janela de 300 caracteres depois do `PAGAR PARA` que a leitura da chave
   já usa. A janela existe porque o aviso costuma trazer também o CNPJ da
   empresa e o valor; varrer o texto inteiro pegaria o primeiro número
   parecido, não o certo.

   Achando **mais de um** documento válido na janela, o rótulo (`CPF:`,
   `CNPJ:`) desempata **pelo tipo que ele nomeia** — 11 dígitos para CPF, 14
   para CNPJ —, e não por proximidade: em `CPF: <cpf> <cnpj>` os dois estão a
   poucos caracteres do rótulo. Sem rótulo que resolva, a fonte não responde.

**O nome do segmento B sai da mesma fonte que o documento.** As fontes 1 e 2
dão o nome oficial do cadastro; só na fonte 3 o nome vem do rótulo do arquivo.
É o que impede o par nome/documento de se contradizer — o defeito que originou
esta trava.

A chave Pix **não** é fonte de documento, mesmo quando ela é um CPF que fecha.
Foi decisão do dono, e ela evita que a chave confirme a si mesma.

### As travas

O reembolso continua fora da remessa, com motivo escrito na tela e no
"ficou de fora", quando:

- **nenhuma fonte deu documento** — `MOTIVO_REEMBOLSO_SEM_DOCUMENTO`: o CPF de
  quem recebe não foi encontrado; cadastrar no `pix_reembolso.json` ou pagar à
  mão;
- **duas fontes discordam** — `MOTIVO_REEMBOLSO_DOCUMENTO_DIVERGENTE`. Escolher
  uma das duas é escolher para quem o dinheiro vai;
- **a chave do aviso é um CPF/CNPJ que não é o documento resolvido** —
  `MOTIVO_REEMBOLSO_CHAVE_DE_OUTRO`. A chave não vale como fonte, mas vale como
  conferente: o dinheiro vai para o dono dela, e o arquivo estaria declarando
  outra pessoa;
- **o rótulo não trouxe nome** — `MOTIVO_REEMBOLSO_SEM_NOME`. Sem nome não há
  favorecido a declarar.

Sem chave Pix nenhuma a linha já cai antes, em `MOTIVO_SEM_CHAVE`, sem mudança.

`MOTIVO_REEMBOLSO` deixa de ser o impedimento automático de todo reembolso e
some; os quatro motivos acima o substituem, cada um dizendo o que falta.

### Efeito na forma de iniciação do Pix

`forma_de_iniciacao(chave, documento_do_cadastro)` desempata os onze dígitos
crus (CPF e celular têm os dois onze) comparando-os com o documento do
cadastro. Para o reembolso, o segundo argumento passa a ser o documento **da
pessoa**, não o do fornecedor — que era a comparação errada, e que hoje nem
chega a acontecer porque a linha já caiu antes.

### Dados que atravessam

`relatorio.montar_registros` acrescenta ao registro:

- `reembolso_nome` — o nome que vai para o segmento B (vazio = não resolvido);
- `reembolso_documento` — o CPF/CNPJ da pessoa (vazio = não resolvido);
- `reembolso_origem` — de qual das três fontes veio, em texto para a tela;
- `reembolso_impedimento` — qual das quatro travas pegou, ou vazio.

`reembolso` (booleano) continua como está.

`remessa_dia.Candidato` ganha:

- `reembolso: bool` — para a tela saber que esta linha trocou de favorecido;
- `reembolso_origem: str` — mostrado na conferência.

Em `remessa_dia.preparar`, para a linha de reembolso resolvida, `favorecido` e
`documento_favorecido` passam a ser os da pessoa. O resto do fluxo (seu número,
histórico de já enviado, montagem do segmento B) não muda: ele já trabalha com
esses dois campos.

### Na tela de conferência

A linha deixa de mostrar só o fornecedor:

```
☐ ⚠ APTO* (reembolso)  Pix   R$ 0.000,00  <NOME DA PESSOA>
      reembolso de <fornecedor> · CPF 000.000.000-00 (Contatos do ERP) · chave ...
```

E **nasce desmarcada**, ainda que o status comece com "APTO". Hoje
`candidato.marcado = candidato.apto`, e `"APTO* (reembolso)"` passa nesse teste.
Reembolso é a única linha em que o app troca o favorecido por conta própria;
isso vale um clique explícito, sempre. A regra vira
`marcado = apto and not reembolso`.

A linha impedida continua sem caixa, com o motivo — e agora o motivo diz o que
falta, em vez de "a remessa só sabe declarar um favorecido".

## Testes da parte 1

Novo `tests/test_reembolso.py`, sobre o módulo isolado (sem rede, sem tkinter):

- nome sai do rótulo, com e sem separador, com e sem extensão;
- documento pela fonte 1, pela 2 e pela 3, e a precedência entre elas;
- CPF fora da janela de 300 caracteres não entra;
- CPF que não fecha o dígito verificador não entra;
- nome ausente no mapa de participantes → não resolvido;
- as quatro travas, uma a uma.

Em `tests/test_remessa_dia.py`:

- reembolso resolvido entra, e o segmento B sai com nome e documento **da
  pessoa** — nunca os do fornecedor;
- reembolso resolvido nasce desmarcado;
- cada trava mantém a linha fora e a faz aparecer em `fora()`.

Em `tests/test_pagamentos_dia.py`: `montar_registros` devolve os quatro campos
novos, e o registro sem aviso não os ganha.

**Nada de dado real nos testes.** O repositório é público: nome de fornecedor,
nome de pessoa, CPF e CNPJ não entram nem em fixture nem em comentário. Os
documentos usados nos testes são gerados para fechar o dígito verificador, não
copiados da vida.

## Risco que fica

O caminho da fonte 3 lê um CPF de uma FOTO, por OCR. O dígito verificador é a
única defesa, e ele pega troca de um dígito e transposição — mas não é prova.
As fontes 1 e 2 não têm esse risco, e a linha nasce desmarcada justamente para
que a conferência humana continue no caminho. Quem quiser eliminar o risco
cadastra a pessoa uma vez, e a fonte 1 passa à frente.

---

# Parte 2 — Marcar lançamento a lançamento

## O problema

O app tem três momentos de escolha, e nenhum deles deixa escolher lançamento a
lançamento sobre o dia inteiro:

| Etapa | O que se marca | Limite |
|---|---|---|
| 1 — aba | a **conta** | conta inteira, tudo ou nada |
| 2 — `_janela_confirmar` | lançamento a lançamento | **só abre para fornecedor listado no `confirmar_antes.json`**; sem o arquivo, nem aparece |
| 3 — conferência da remessa | lançamento a lançamento | só o que vai ao arquivo CNAB, e só linha sem impedimento; a planilha já saiu antes |

A peça central já existe e funciona: a janela da etapa 2 devolve os ids não
confirmados, `montar_registros` os recebe em `ids_nao_confirmados`, e eles saem
na aba NÃO ENTRARAM com `MOTIVO_NAO_CONFIRMADO`. O que falta é ela poder falar
de todos os lançamentos, e não só dos pré-cadastrados.

Há ainda um buraco na etapa 3: `remessa_dia.fora()` devolve apenas linhas com
`impedimento`. **A linha desmarcada à mão na conferência sai em silêncio** — o
mesmo defeito que o código já corrigiu para os impedidos ("omitir não é
apagar"), e que ficou de pé para a escolha manual.

## O que muda

### Etapa 2: a janela lista tudo

`_confirmacoes_pendentes` deixa de filtrar por `confirmar_antes.json` e passa a
devolver **todos** os lançamentos a pagar das contas marcadas. Já pago continua
fora da lista: não há o que decidir sobre ele.

A escolha de quem entra na lista sai da classe e vira
`alvos_para_confirmar(lancamentos, escolhidas)`, no nível do módulo: é decisão,
não tela, e assim tem teste sem precisar de janela.

`_janela_confirmar` muda de forma:

- **agrupada por conta**, com contagem e total no cabeçalho de cada uma — o
  mesmo formato da conferência da remessa, para as duas telas se lerem igual;
- todos nascem **marcados**. Desmarcar é a exceção, e "Confirmar e gerar"
  segue como botão em foco: quem não quer mexer aperta Enter, como hoje;
- o `confirmar_antes.json` deixa de ser porteiro e vira **destaque**: quem está
  nele aparece com ⚠ e ordenado à frente dentro da conta. A regra já cadastrada
  não se perde — muda de função, de "quem faz a janela abrir" para "quem o olho
  precisa ver primeiro";
- ganha **rolagem** (canvas + scrollbar, como a conferência) e **"Marcar todas
  / Desmarcar todas"**. Hoje ela é `resizable(False, False)` e sem canvas; num
  dia de ~300 lançamentos, sairia da tela;
- rodapé com **"N de M · R$ …"**, atualizando a cada clique. É o número que se
  confere antes de gerar, e é o que as outras ações irreversíveis do app
  (Aportes, Acessórias) já mostram antes de perguntar.

A janela roda na thread da interface, antes de ocupar o navegador — isso não
muda, e é o que permite abrir e esperar resposta à vontade.

O que for desmarcado fica fora **da planilha e da remessa**, porque as duas
descendem do mesmo `montar_registros`.

**Consequência aceita:** hoje, sem `confirmar_antes.json`, gerar são dois
cliques; passa a haver sempre uma janela no caminho. É o controle pedido, e o
Enter continua atravessando.

### Etapa 3: nada mais sai em silêncio

`remessa_dia.fora()` passa a devolver duas categorias em vez de uma:

- linha com `impedimento` — como hoje, com o motivo;
- linha **sem** impedimento e **não marcada** — motivo
  `MOTIVO_DESMARCADO = "você desmarcou na conferência"`.

`_registrar_o_que_ficou_de_fora` já agrupa por motivo e soma valores; ele passa
a mostrar as duas famílias sem mudar de forma.

A assinatura de `fora()` não muda: ela já recebe o `preparado` inteiro, e
`marcado` já está no `Candidato`. O que muda é o filtro — hoje `if
c.impedimento`, passa a `if c.impedimento or not c.marcado`.

## Testes da parte 2

Em `tests/test_remessa_dia.py`:

- `fora()` devolve a linha desmarcada sem impedimento, com o motivo novo;
- `fora()` não devolve a linha marcada e sem impedimento;
- linha impedida continua saindo com o motivo do impedimento, e não com o de
  desmarcada — impedido não vira escolha sua.

Em `tests/test_pagamentos_dia.py`, sobre `alvos_para_confirmar`:

- lista todo lançamento das contas marcadas, sem consultar o
  `confirmar_antes.json` — é a inversão que esta parte faz, e é o teste que a
  guarda;
- já pago não entra na pergunta;
- lançamento de conta não marcada não entra.

Os ids desmarcados chegando a `montar_registros` e saindo em `omitidos` com
`MOTIVO_NAO_CONFIRMADO` já tinham teste, e ele segue valendo sem alteração — é
justamente por o efeito já ser esse que esta parte é pequena.

A janela em si não é testada (tkinter); o que se testa é a seleção dos alvos e
o efeito dos ids no resultado. É a limitação conhecida desta parte: a rolagem,
o agrupamento e o contador do rodapé só se conferem abrindo o app.

---

# Fora de escopo

- Transmitir a remessa. O envio ao SicoobNet segue seu, à mão.
- Cadastrar a pessoa do reembolso pela interface. O `pix_reembolso.json` é
  editado à mão, como hoje.
- Reembolso com mais de uma pessoa no mesmo lançamento. Não apareceu ainda; se
  o rótulo trouxer dois nomes, a leitura pega o primeiro e as travas seguram o
  resto.
- Forçar a entrada de linha impedida na remessa. As travas de dinheiro (linha
  digitável que não fecha, já pago, já enviado) continuam sem caixa para
  marcar: desmarcado é escolha sua, impedido é outra coisa.
- Guardar a seleção de lançamentos entre execuções. Cada geração começa com
  tudo marcado.

# Entrega

As duas partes tocam só `pagamentos_dia/*.py` e `tests/`. Esse caminho já é
copiado por glob no `build.yml`, então:

- **não** exige mexer no workflow;
- **não** exige exe novo nem `motor_minimo.txt`;
- chega ao usuário pelo `codigo.zip`, no próximo abrir do app.

Nenhum import novo de submódulo da biblioteca padrão — a armadilha que derrubou
a v1.0.71. Se algum aparecer durante a implementação, a regra do `CLAUDE.md`
volta a valer e a entrega passa a custar uma release com exe.
