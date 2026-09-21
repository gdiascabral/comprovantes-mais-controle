# Guias do mês: do portal do escritório para o Mais Controle — design

Data: 21/09/2026
Onde: bloco novo na aba Acessórias (`acessorias/frame.py`) + módulo novo `guias/`

Todo mês o escritório de contabilidade publica no portal, empresa por empresa,
o que vence naquele mês: boleto de honorário, guia de FGTS, de INSS/IRRF,
contribuição, boleto de regularização de obra, imposto sobre venda de obra.
Hoje alguém abre o portal, baixa cada PDF, procura no Mais Controle se já
existe recorrência para aquilo, altera a parcela do mês ou cria o título, e
anexa o PDF. Em 14/09/2026 isso foi feito para setembro com scripts soltos em
`ferramentas/acessorias-calendario/` (14 alterações + 5 criações): funcionou,
mas o mês está escrito dentro do script, as categorias e as obras foram
decididas na hora, e no mês seguinte nada disso se repete sozinho.

Este design põe a rotina dentro do app, com regra que persiste e conferência
na tela antes de gravar.

---

## O que já existe (e por isso o marco é menor do que parece)

- `acessorias/portal.py::PortalClient` — sessão do portal já logada, em perfil
  de Chrome próprio (`acessorias/config.PASTA_PERFIL_CHROME`), com
  `SessaoPerdida` e espera de login já tratadas.
- O endereço do escritório e o `vip_id` de cada empresa **já estão no
  cadastro** (`contas_sicoob.json`, chave `vip_url` e campo `vip_id` de
  `Empresa`), fora do repositório público. Nada disso entra em código.
- `erp/pagina.py::TransportePagina` — GET e POST na API do ERP feitos **de
  dentro da página logada**, com os cabeçalhos capturados do próprio tráfego
  (`aportes/erp_sessao.py`). É o caminho que não derruba a sessão de ninguém:
  o ERP aceita uma sessão por usuário e um `POST /users/login` por HTTP
  derruba a do dono.
- `aportes/mc_catalogos.py::Catalogos` — contas, participantes, categorias,
  formas e condições de pagamento resolvidas em id, com `parecidos()` para o
  recado de "não achei".
- `aportes/mc_lancamentos.py::criar_pagamento` — `POST /trade-payables` já
  escrito e em uso (aportes), com a diferença de que lá o pagamento nasce
  **pago**; aqui nasce a pagar.
- `conciliacao/erp/payments_api.py` — a rota e os parâmetros da lista de
  parcelas (`payable-installments/paginated-result`, `size=3000`).
- `anexar/mc_api.py::MCApi.anexar_por_api` — anexo por API com prova, hoje
  apontado ao sub-pagamento (`entityOrigin=PAID`).

Falta, em código que existe: um `PUT` no transporte de página (hoje só GET e
POST) e um anexo com `entityOrigin=TRADE_PAYABLE`.

---

## Decisões do dono (21/09/2026)

1. **Onde**: segundo bloco da aba Acessórias — o perfil do portal e a lista de
   empresas com `vip_id` já estão ali.
2. **Nada é gravado sem conferência**: o robô varre, baixa, lê, casa e mostra;
   quem manda gravar é o dono, linha por linha.
3. **Acesso ao ERP**: pela API, igual aos aportes — chamadas de dentro da
   página logada. Sem login novo, sem derrubar sessão.
4. **Regra em JSON no `_app`**, ao lado do `contas_sicoob.json` (carrega nome
   de fornecedor e de obra; o repositório é público).
5. **Conta bancária nunca é escolhida.** Em todo lançamento, escolher a obra
   já seleciona a conta, e a equipe deixa a que vem. Logo: nenhuma coluna de
   conta no cadastro de regras.
6. **Documento desconhecido** entra numa seção "você decide" e não é lançado;
   a escolha do dono vira regra para o mês seguinte.
7. **Trava dupla contra duplicar**: conferir no ERP antes de gravar E registro
   local do que cada rodada fez.
8. **Escopo da rodada**: mês atual (trocável na tela), todas as empresas que o
   portal listar; empresa do portal sem cadastro aqui entra na lista dizendo o
   que falta, em vez de desaparecer.
9. **Boleto parcelado** ("1/4") nasce com todas as parcelas, como em setembro;
   nos meses seguintes o robô ALTERA a parcela existente.
10. **Obra nos casos de criar**: sugerida pelo texto do documento e confirmada
    pelo dono; a confirmação vira regra.
11. **Descrição e favorecido** saem do molde por tipo de documento, na regra.
    Ao alterar recorrência a descrição fica intacta, como a equipe faz.
12. **PDFs** na pasta da empresa, ano, mês, subpasta `GUIAS`.

---

## Módulos

| Arquivo | Responsabilidade | Depende de |
|---|---|---|
| `guias/calendario.py` | ler o mês inteiro de uma empresa no portal e baixar os PDFs | `acessorias.portal` |
| `guias/leitura.py` | tirar valor, vencimento e nº do documento de um PDF | `pdfplumber` |
| `guias/regras.py` | ler e gravar `_app/guias_regras.json`; classificar um documento | nada |
| `guias/casamento.py` | decidir, por guia, entre ALTERAR, CRIAR, JÁ LANÇADO e DECIDIR | lista de parcelas do ERP |
| `guias/lancar.py` | executar a alteração ou a criação e anexar o PDF | transporte do ERP, `Catalogos` |
| `guias/registro.py` | `_app/guias_lancadas.jsonl`: o que cada rodada fez | nada |
| `guias/painel.py` | o bloco de tela (Treeview, botões, progresso) | os anteriores |

Cada um se entende sozinho: `casamento` recebe guias lidas e parcelas e devolve
decisões, sem tocar em rede; `lancar` recebe uma decisão e um transporte, sem
saber de portal nem de tkinter. É o que torna o teste possível sem navegador.

`acessorias/frame.py` só ganha a chamada que embute `guias.painel` — o arquivo
já tem cerca de 660 linhas e dois assuntos diferentes; um terceiro dentro dele
não caberia.

---

## A rodada, passo a passo

1. **Mês** — abre no mês atual; dá para trocar mês e ano, como o bloco de
   envio já faz.
2. **Varrer o portal** — para cada empresa do "Trocar empresa":
   `GET /<vip_id>/CLD/<AAAA-MM>`, que traz o mês inteiro num JSON com `desc`,
   `prz` (vencimento), `TemVcto`, `AnxID` e `lnk`. Interessa `TemVcto=S`;
   certidão (`CND`) fica de fora.
3. **Baixar** — o `lnk` devolve um HTML com um iframe apontando para um S3 que
   **expira em 120 s**: o PDF é baixado na mesma passada, para
   `<pasta da empresa>/<ano>/<mês>/GUIAS/`. Baixar marca o documento como lido
   no portal — efeito colateral conhecido e aceito.
4. **Ler** — valor, vencimento e nº do documento de cada PDF. Guia com duas
   cobranças num arquivo (imposto + consignado, por exemplo) é separada por
   página.
5. **Casar** — com as parcelas do mês no ERP (uma leitura só, mês inteiro,
   `size=3000`). Cada guia recebe um dos quatro estados abaixo.
6. **Conferir** — a tela mostra as quatro seções; o dono desmarca, corrige
   obra e categoria, abre o PDF, abre o título no ERP.
7. **Lançar o marcado** — grava, anexa, confere o que gravou e registra.

---

## Os quatro estados de uma guia

**ALTERAR** — a regra diz que este tipo tem recorrência, e a recorrência foi
achada. O casamento **não usa valor** (o valor da guia muda todo mês): na
primeira vez o dono confirma "esta guia é esta recorrência" e o
`tradePayableId` fica gravado na regra, por empresa. Do segundo mês em diante
o casamento é exato, não heurístico. Achando mais de uma candidata, vira
DECIDIR — nunca escolhe sozinho.

**CRIAR** — a regra diz criar (honorário de regularização de obra, imposto
sobre venda de obra), e a trava não achou título igual. Criando um título
**parcelado**, o `tradePayableId` resultante é gravado na regra daquele tipo e
empresa: é isso que faz o mês seguinte cair em ALTERAR (trocar o número do
documento e anexar a guia nova) em vez de criar um segundo título parcelado.

**JÁ LANÇADO** — a trava achou. Não é erro: é o estado normal de uma segunda
rodada no mesmo mês.

**DECIDIR** — tipo de documento que a regra não conhece, ou recorrência não
encontrada onde a regra esperava uma, ou mais de uma candidata. Não é lançado.
O que o dono escolher aqui é gravado na regra.

---

## Trava contra lançar duas vezes

Duas camadas, porque uma sozinha falha em casos diferentes:

- **No ERP, antes de criar**: procura no mês título com o mesmo
  `documentNumber`. Sem número, procura mesmo valor, mesmo vencimento e mesmo
  favorecido. Achou → JÁ LANÇADO. É a única camada que enxerga lançamento
  feito à mão pela tela.
- **Registro local**: `_app/guias_lancadas.jsonl`, uma linha por ação, com
  chave `(vip_id, AnxID, ano-mês)`. O `AnxID` é o id do anexo no portal e não
  muda quando o número do documento é corrigido depois.

Ao ALTERAR há uma terceira guarda, herdada do executor de setembro: parcela
que já tem baixa (`paid` ou `paids`) não é tocada, é erro de linha.

---

## Contratos da API do ERP

Já verificados em produção em 14/09/2026 pelo executor de setembro. O
transporte é sempre o da página logada.

**Alterar a parcela do mês**

    GET  {legacy}/trade-payables/{tpid}
    PUT  {legacy}/trade-payables/{tpid}
         ?removeAllEntryItems=false&userApprovesSaleCreation=true&updateNext=false
    GET  {legacy}/trade-payables/{tpid}          -> conferência do que gravou

O objeto original vai para backup antes do PUT. Muda-se: `plannedDate` e
`plannedValue` da parcela, `value`, `documentNumber`, `category` (para a
categoria específica — a recorrência nasce genérica) e, quando existe,
`recurring.plannedDate`; `costCentreDetails[].value` acompanha o valor novo.
`updateNext=false` é o que faz valer **somente esta parcela**: conferido em
14/09, não sobrou parcela na data antiga e o mês seguinte ficou intacto. A
descrição não é tocada.

**Criar**

    POST {legacy}/trade-payables?userApprovesSaleCreation=true
    GET  {legacy}/trade-payables/{tpid}          -> conferência

`markedAsPaid: false` (é conta a pagar, não baixa), `whoPays: "CLIENT"`,
`costCentreType: "WORK"` com a obra a 100%. Uma parcela usa condição
`IN_CASH`; parcelado usa `FINANCING`, com `numberOfFinancingInstallments` e
`order` em cada parcela.

**Anexar ao título**

    POST {prod}/attachments/v2/batch     entityOrigin=TRADE_PAYABLE, entityId=tpid
    PUT  <URL S3 pré-assinada>           binário cru, só Content-Type
    GET  {prod}/attachments/v2?entityIds={tpid}&entityOrigin=TRADE_PAYABLE

O GET final é prova, não enfeite: sem ele o app relataria anexo que talvez não
exista. O POST do batch nunca é repetido — batch reenviado é um segundo
registro de anexo no mesmo título.

Depois de cada gravação, o app relê e compara campo a campo (data, valor,
número do documento, categoria; na criação também parcelas, conta e obra). Não
batendo, a linha fica **DIVERGE** — gravou, mas não como pedido —, que é
diferente de erro e diferente de feito.

---

## Conta e obra: de onde saem

Isto vale **só para CRIAR**. Ao ALTERAR, o robô manda de volta o objeto que
acabou de ler do ERP: a conta e a obra do título já estão lá e não são tocadas.

A obra vem da regra (quando fixa por empresa) ou da sugestão confirmada pelo
dono. A conta **não é escolhida por ninguém**: é a que o ERP põe depois da
obra. Pela API ela é campo obrigatório do corpo do POST, então o robô precisa
mandar a mesma que a tela mandaria.

Em setembro isso foi resolvido copiando conta e obra de um título que já
existia daquele tipo, naquela empresa. É a hipótese a confirmar antes de
escrever `lancar.py`: **ler** (só leitura, com aviso ao dono, autorizado em
21/09) títulos já existentes de duas ou três obras e verificar se a conta é
sempre a mesma por obra. Confirmado, a regra do robô é "a conta do título de
referência daquela obra", e o título de referência fica anotado na regra.

Se a leitura mostrar que a conta varia dentro da mesma obra, a hipótese cai, e
a linha de criação passa a exigir a conta escolhida na tela de conferência —
sem inventar. Este é o único ponto do design que depende de uma medição.

---

## O arquivo de regras

`_app/guias_regras.json`, fora do repositório público. Formato:

    {
      "versao": 1,
      "tipos": [
        {
          "nome": "honorario contabil",
          "quando": {"desc_contem": ["HONORARIO"]},
          "acao": "alterar",
          "categoria": "<categoria do ERP>",
          "recorrencia": {"<vip_id>": {"trade_payable_id": "<id>", "obra": "<id>"}}
        },
        {
          "nome": "regularizacao de obra",
          "quando": {"desc_contem": ["RET", "REGULARIZACAO"]},
          "acao": "criar",
          "categoria": "<categoria do ERP>",
          "favorecido": "<participante do ERP>",
          "descricao": "{documento} - competencia {competencia}",
          "parcelas": 4,
          "obra": {"<vip_id>": "<id da obra>"}
        }
      ]
    }

Sem conta bancária, por decisão do dono. A comparação de `desc_contem` é por
palavra inteira e sem acento — casar por pedaço de palavra já produziu erro
neste projeto (lote 1 casando com lote 10).

O arquivo é escrito pelo app quando o dono decide algo na tela, e é lido na
abertura do bloco. Arquivo ausente = todas as guias caem em DECIDIR, que é o
comportamento correto no primeiro mês.

---

## A tela

Um Treeview com as quatro seções, no padrão que o app já usa: as listas de
conferência em Treeview caíram de 5,4 s para 0,14 s quando deixaram de ser um
bloco por linha, e esta lista tem dezenas de linhas.

Colunas: empresa, documento, vencimento, valor, ação, categoria, obra, estado.
Duplo clique em categoria ou obra abre a escolha (com os nomes vindos do
cadastro do ERP e sugestão por semelhança). Botões: *Varrer o portal*,
*Lançar o marcado*, *Abrir o PDF*, *Abrir no ERP*, *Parar*. O rodapé usa o
Registro da aba, como as outras funções.

O trabalho pesado roda em thread, com fila para a tela — nunca na thread do
tkinter. Enquanto a rodada está em pé, o bloco de envio de conciliações da
mesma aba fica ocupado: são dois usos do mesmo perfil de Chrome, e o
Playwright síncrono não divide thread entre sessões.

---

## Quando dá errado

| Situação | O que acontece |
|---|---|
| link da guia expirou (120 s) | baixa de novo, uma vez; falhando, a linha fica sem PDF e não é lançada |
| portal sem sessão | `SessaoPerdida` (já existe) e a tela pede o login |
| empresa que o portal lista e o cadastro não reconhece | linha informativa: o id vem do portal, mas sem empresa cadastrada com aquele `vip_id` não há pasta para o PDF nem obra para o lançamento |
| ERP recusa (4xx/5xx) | a linha fica em erro com o motivo; a rodada continua nas outras |
| gravou mas não conferiu | estado DIVERGE, com o antes e o depois no Registro |
| título criado e anexo falhou | estado "criado, anexo pendente" — nunca "feito" |
| PDF ilegível | a linha vai para DECIDIR com o motivo, e o PDF fica salvo |

Nenhum caminho relata sucesso sem prova. A regra vale também para o anexo: só
"anexado" depois de a listagem mostrar o arquivo.

---

## O que fica registrado

`_app/guias_lancadas.jsonl`, uma linha por ação: quando, empresa, `AnxID`,
tipo de documento, ação, `tradePayableId`, id da parcela, se conferiu, anexos
listados. Serve à trava, à conferência do mês seguinte e a responder "o que
esta rodada fez" sem abrir o ERP.

---

## Testes

- **Portal falso**, no padrão de `tests/test_acessorias_envio.py`: página
  dublê devolvendo um calendário e um HTML de iframe, sem navegador.
- **ERP falso**: transporte dublê que responde GET, POST e PUT e registra o
  que recebeu. Cobre o casamento, o `updateNext=false`, a trava do
  `documentNumber`, a parcela com baixa, o DIVERGE e o anexo sem prova.
- **PDFs sintéticos**, gerados no teste: guia real tem CNPJ e nome de
  fornecedor, e o repositório é público. Nenhum PDF real entra em `tests/`.
- **Regras**: classificação por palavra inteira, arquivo ausente, arquivo de
  versão desconhecida, decisão do dono virando regra.

O dublê do ERP consome o corpo que recebe, e não só devolve resposta: dublê que
não consome a entrada muda o transporte e produz teste que falha sozinho de vez
em quando.

---

## Fora de escopo

- Rodar sozinho no agendador (contraria a conferência e a sessão única).
- Dar baixa em pagamento: isto aqui só deixa a conta lançada a pagar.
- Alterar mais de uma parcela por vez (`updateNext=true`).
- Criar participante, categoria ou obra no ERP — a API não cria; falta de
  cadastro é recado na tela.
- Trazer documento de mês que não seja o escolhido.

---

## Pendências do dono

- Um momento com a tela livre para a leitura que confirma a conta por obra.
- No primeiro mês, decidir os tipos de documento que a regra ainda não conhece
  (é o que deixa o segundo mês quase inteiro automático).
