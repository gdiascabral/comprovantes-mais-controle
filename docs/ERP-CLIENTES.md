# Quem fala com o ERP, e como

Oito lugares do app conversam com o Mais Controle, e mais três fora dele. Cada
um descobriu por conta própria qual token pedir, quais cabeçalhos copiar, qual
`user-agent` passa pelo WAF e como paginar. O conhecimento se contradiz entre
eles, e a contradição está por escrito:

- `conciliacao/erp/api.py:33` — "O TOKEN E O `jwtToken` (~348 chars), NAO o
  `accessToken` (27 chars, que nem e JWT)";
- `fontes/vigia-boletos/mc_sessao.py:9` — "accessToken (27 chars) -> API
  legada. E o que este modulo usa".

Os dois estão certos, para back-ends diferentes — e **nenhum arquivo diz isso
inteiro**. Este documento é o inventário que faltava, e a base do pacote `erp/`.

A conta que justifica escrevê-lo: a tela do ERP já foi reescrita duas vezes
(AngularJS → React, `#/accounts` em 10/08/2026, `conciliacao/erp/api.py:5-8`),
e cada reescrita derrubou a raspagem. Na próxima são oito lugares para
consertar em vez de um.

## A tabela

Uma linha por consumidor. "Transporte" é como a requisição sai: **HTTP direto**
(urllib/requests, sem navegador), **fetch na página** (`page.evaluate` de dentro
da aba logada) ou **raspagem** (ler o DOM / falar com o scope do Angular).

### Dentro do app

| Arquivo | O que faz | Transporte | Host | Token, e de onde sai | Cabeçalhos obrigatórios | Paginação | O que já quebrou ali |
|---|---|---|---|---|---|---|---|
| `conciliacao/erp/api.py` | lista contas bancárias e lê saldos (`SessaoApi`) | HTTP direto (`urllib.request`, `:287`) | login em `legacy-api` (`:115`); consultas em `prod-erp-api` (`:175`, `:200`) | `jwtToken` da resposta de `POST /users/login` (`:120`) | `company-id` (`:157`), `user-agent` de Chrome (`:55`, `:287`), `origin`/`referer` de `acessar.` (`:280`) | `pageIndex` (base **1**) + `pageSize=200`, fim por `hasNextPage` (`:172`, `:179`); trava em 50 páginas (`:65`) | a raspagem de `#/accounts` morreu no redesenho de 10/08/2026 (`:5-8`); sem `user-agent` de navegador o WAF devolve 403 (`:23-29`); um 504 real do `prod-erp-api` custou a rodada, daí as 3 tentativas só em GET (`:69-81`) |
| `conciliacao/erp/payments.py` | lê a grade de pagamentos a vencer | raspagem (MUI DataGrid, `:55`) | `acessar.` (tela) | cookie/sessão da aba, via `conciliacao/erp/auth.py` | — (o navegador manda tudo) | paginação da própria grade, até 400 páginas (`:98`); o total do rodapé confere a cobertura (`:25`) | ler cedo devolvia ZERO pagamentos sem erro (`:10-12`); com 10 linhas por página a coleta parava no meio do mês **sem erro** (`:96-97`); deduplicar por texto apagava tarifas legítimas iguais (`:34-36`) |
| `conciliacao/erp/auth.py` + `browser.py` | login no navegador para a grade | raspagem + `page.evaluate` no scope do AngularJS (`auth.py:58`) | `acessar.` | nenhum token nosso: a sessão vive só na memória da aba (`auth.py:5-9`) | — | — | preencher o input não propaga para o `ng-model` e o ENTRAR chamava `login()` com credencial vazia, em silêncio (`auth.py:47-57`); **headless é recusado pelo WAF** (`browser.py:5-8`) |
| `anexar/mc_api.py` | pagos, a pagar, anexos, `overview`, recebimentos, participantes, obras | fetch na página (`:55`, `:282`) | `legacy-api` (lista de pagamentos, `_base_legacy` `:507`) e `prod-erp-api` (anexos e obras, `_base_erp` `:515`) | **cabeçalhos capturados do tráfego da própria página** — dois conjuntos, um por tela (`:144-158`) | pagos: `accept`, `authorization`, `organization-unit-id`, `user-id`, `company-id` (`:52`); anexos: `accept`, `authorization`, `company-id` (`:53`) | pagos/recebimentos: `page` (base **0**) + `size`, fim por `hasNextPage`/`last` (`:316`, `:326`, `:559`); obras: `pageIndex` (base **1**) + `pageSize`, fim por `hasNextPage` (`:627-635`) | `pageIndex`/`pageSize` são **aceitos e ignorados em silêncio** na lista de recebimentos, e a resposta volta com 20 registros parecendo completa (`:537-540`); `page=1` traz a SEGUNDA página, vazia e sem erro (`:402-403`); `goto` para a rota em que a página já está não dispara requisição, e a captura esperava 30 s por uma chamada que nunca sairia (`:172-178`) |
| `anexar/mc_client.py` | login e **anexar o arquivo** pela tela (⋮ → Editar pagamento) | raspagem + `page.evaluate` (`:95`, `:690`) | `acessar.` (`config.py:70`) | sessão da aba; sem token nosso | — | — | o mesmo buraco do `ng-disabled`/`getAutoFill` (`:246-255`); "anexado" sem prova: o `wait_for_timeout(3000)` era menor que o upload em lote e o Confirmar ia sem arquivo (`:130-132`, `:723-731`) |
| `aportes/mc_catalogos.py` (+ `erp_sessao.py`) | catálogos nome→UUID (contas, participantes, categorias, formas, condições, naturezas) e o POST dos lançamentos | fetch na página (`:42`, `:48`, `:158`) | `prod-erp-api` (`:36`) e `legacy-api` (`:37`); obras por GraphQL em `execute-api` (`:213`) | cabeçalhos capturados, **indexados por host** (`:141-155`) | `authorization`, `company-id`, `user-id`, `organization-unit-id` (`erp_sessao.py:19`) — e o `user-id` só vem do `legacy-api` (`:171-172`) | `pageIndex` (base **1**) + `pageSize=100`, fim por `hasNextPage`; se o ERP recusar o `pageSize`, refaz sem ele (`:286-326`); trava em 60 páginas (`:40`) | ler só a primeira página escondia as contas em M e T (`:289-292`); reaproveitar cabeçalho de um host noutro dá **401** — foi assim que o token da telemetria (`api-data-event`) acabou usado contra o `prod-erp-api` (`:124-127`); o host `execute-api` só aparece quando o ERP carrega o FORMULÁRIO de lançamento, e por isso `obras: 0` (`:255-261`) |
| `aportes/mc_lancamentos.py` | cria pagamento e recebimento (POST), e a baixa do recebimento | fetch na página (usa `Catalogos.postar`) | `legacy-api` (`:21`) | herdado do `Catalogos` | idem `mc_catalogos` | — | chamar a baixa quando ela já veio feita lançava R$ 2,00 no lugar de R$ 1,00 — daí os TRÊS estados de `estado_da_baixa` (`:287-315`) |
| `pagamentos_dia/baixa_erp.py` | dá baixa no ERP do que o banco pagou | **transporte injetado** (`_buscar`/`postar`, `:208-214`) — hoje o `Catalogos`, que fala pela página | tenta `legacy-api` e depois `prod-erp-api` (`:32-38`) | herdado do transporte | idem | — | `POST {legado}/payables/{id}/paids` → **404**; `/payable-installments/{id}/paids` → 400 por falta de `isWorkFilterApplied` (`:59-74`); o corpo do `default-paid` não traz campo de valor, e mandá-lo intacto gravou uma baixa de **R$ 0,00 com HTTP 200** (`:47-57`) |
| `relatorios/extrato_mc.py` | extrato do fluxo de caixa em PDF | raspagem + scope do AngularJS + `Page.printToPDF` do CDP (`:103`, `:324`) | `acessar.` (`:39-41`) | sessão da aba | — | "carregar mais" até `pageInfo.hasNextPage` ficar falso (`:257-270`) | `#/accounts` virou React e a leitura antiga da lista de contas morreu (`:51-57`); o "carregar mais" fica DEPOIS do "Saldo final", então o extrato mostra totais completos faltando lançamentos (`:279-282`) |
| `nuvem/contas_novas.py` | conta nova no ERP, na abertura do app | HTTP direto — **reusa o `SessaoApi`** (`:223-224`) | `prod-erp-api` + `legacy-api` (`:45-46`) | `jwtToken`, via `SessaoApi` | idem `conciliacao/erp/api.py` | idem | comparar o formato já convertido casava zero e o app abria sem perguntar nada (`:174-180`) |

`aportes/conferir_contas.py` e `aportes/teste_lancamento.py` repetem a captura
de cabeçalhos do `aportes_frame.py`; os três já foram unificados em
`aportes/erp_sessao.py` (`erp_sessao.py:6-12`) — é o precedente mais próximo do
que este documento propõe, um nível acima.

### Fora do app (só para o inventário)

| Arquivo | O que faz | Transporte | Host | Token | Cabeçalhos | Paginação |
|---|---|---|---|---|---|---|
| `fontes/acesso-mais-controle/mais_controle_api.py` | contas com saldo | HTTP direto (`:302`) | login em `legacy-api`, consultas em `prod-erp-api` (`:67-68`) | `jwtToken` (`:184`) | `company-id` (`:214`), `user-agent` de Chrome (`:72`) | `pageIndex` base 1 + `pageSize=200`, `hasNextPage` (`:231-239`) |
| `fontes/vigia-boletos/mc_sessao.py` | parcelas a pagar e **PUT** do lançamento | HTTP direto (`:259`) | `legacy-api` (`:37`) | **`accessToken`** (`:111-114`) | `authorization`, `company-id`, `user-id`, `organization-unit-id` (`:125-129`) | **não pagina**: parte a janela de datas ao meio quando a resposta satura em 200 (`:15-26`, `:167-178`) |
| `agua_energia/coletor/lancar_mc.py` | lança as faturas de água/luz | fetch na página (`:79`) | `legacy-api` e `prod-erp-api` (`:59-60`) | cabeçalhos capturados, por host (`:216-231`) | `legacy`: os quatro; `prod`: `authorization` + `company-id` (`:76-77`) | usa a URL da lista capturada da tela |

## 1. Qual token para qual host

Escrito uma vez, e é isto:

> O login é **um só** e devolve **dois** tokens.
> `POST https://legacy-api.maiscontroleerp.com.br/maiscontrole/services/users/login`
> responde com `jwtToken` **e** `accessToken`, mais a identidade
> (`companies[0].id`, `id`, `organizationUnitId`).
>
> - **`prod-erp-api.maiscontroleerp.com.br` → `Bearer <jwtToken>`** (~348
>   chars, é JWT de verdade, vale 24 h).
> - **`legacy-api.maiscontroleerp.com.br` → `Bearer <accessToken>`** (27 chars,
>   não é JWT, expira em segundos).
>
> Trocar um pelo outro devolve **401**. E o token é do HOST, não da sessão:
> vale igual para o token capturado do navegador.

As evidências, cada uma no arquivo que a sustenta:

- `conciliacao/erp/api.py:120` pega `jwtToken` do login e o usa **só** contra o
  `prod-erp-api` (`:175` lista contas, `:200` lê saldos). O docstring `:33-35`
  registra a descoberta: "O TOKEN E O `jwtToken` (~348 chars), NAO o
  `accessToken` (27 chars, que nem e JWT)". Ele fala com o `legacy-api` uma vez
  só — no próprio login (`:115`), que não leva token nenhum.
- `fontes/vigia-boletos/mc_sessao.py:8-9` diz o oposto porque fala com o outro
  lado: "jwtToken (348 chars) -> API nova. **Na legada da 401 invalid_token.**
  accessToken (27 chars) -> API legada." E o código faz exatamente isso
  (`:111-114` guarda `accessToken`; `:37` e `:142` chamam só o `legacy-api`).
- `fontes/acesso-mais-controle/mais_controle_api.py:46-47` repete a mesma
  regra pelo lado do `prod-erp-api`, com o mesmo par de tamanhos.
- No caminho do navegador a regra é a mesma, e já custou um 401:
  `aportes/mc_catalogos.py:124-127` — "cada serviço do ERP emite o seu token.
  Reaproveitar o cabeçalho de um host em outro devolve 401 — foi assim que o
  token da telemetria (`api-data-event...`) acabou sendo usado contra o
  `prod-erp-api`". É por isso que `_headers_para(url)` (`:141`) escolhe pelo
  host e `aportes/erp_sessao.py:21-23` exclui os hosts de telemetria.

Duas consequências que não são óbvias:

1. **Só o `legacy-api` manda `user-id`** (`aportes/mc_catalogos.py:171-172`), e
   é ele o responsável pelo lançamento. Esperar só pelo `prod-erp-api` dava 401
   nas categorias e, logo depois, "não achei o usuário responsável" — dois
   sintomas de uma causa só (`aportes/erp_sessao.py:25-30`).
2. **O `accessToken` expira em segundos** (`mc_sessao.py:18`, `:132`). Quem
   fala com o `legacy-api` por HTTP direto precisa relogar no meio do trabalho;
   quem fala pela página não percebe, porque o próprio ERP renova.

## 2. Quem pode virar HTTP direto, e quem precisa mesmo do navegador

Há uma regra escrita em três lugares do app que **está desatualizada**:

- `CLAUDE.md`, Restrições: "ERP bloqueia chamadas HTTP feitas fora do navegador
  (403) — sempre via página logada";
- `anexar/mc_api.py:6-10` e `aportes/mc_catalogos.py:17-19` ("Restrição
  herdada (ver anexar/mc_api.py): requisição feita de fora do navegador leva
  403").

O que o WAF recusa é outra coisa, e está medido em
`conciliacao/erp/api.py:23-29`:

```
COM user-agent de Chrome ......... 200
SEM user-agent (Python-urllib) ... 403, pagina HTML do WAF
```

> "O WAF nunca implicou com HTTP puro — implica com quem se identifica como
> robô. (É o mesmo guarda que recusa o navegador em modo headless.)"

Três clientes provam isso rodando: `conciliacao/erp/api.py` (leitura no
`prod-erp-api`), `fontes/acesso-mais-controle/mais_controle_api.py` (idem) e
`fontes/vigia-boletos/mc_sessao.py`, que faz **PUT de lançamento** no
`legacy-api` por `urllib` puro (`:187-190`). O 403 de 2025 era o `user-agent`, e a
frase virou lenda antes de a causa ser conhecida.

Com isso, o motivo de cada consumidor precisar (ou não) do navegador:

**Podem virar HTTP direto — nada os prende (6):**

| Consumidor | Por que dá |
|---|---|
| `nuvem/contas_novas.py` | **já é** (`:223`), só empresta o `SessaoApi` |
| `conciliacao/erp/api.py` | **já é** (`:287`) |
| `pagamentos_dia/baixa_erp.py` | o transporte é parâmetro (`:208-214`); ele nunca soube se havia navegador |
| `aportes/mc_catalogos.py` (a parte REST) | os quatro cabeçalhos que ele captura saem inteiros da resposta do login — é o que `mc_sessao.py:114-117` monta sem navegador nenhum |
| `aportes/mc_lancamentos.py` | só usa `Catalogos.postar`; segue o de cima |
| `conciliacao/erp/payments.py` | a MESMA lista tem endpoint REST: `legacy .../payable-installments/paginated-result`, que `anexar/mc_api.py:147` e `mc_sessao.py:167` já consomem. O próprio `collect.py:10-11` registra a intenção: "A grade de pagamentos nao foi investigada ainda — quando for, o navegador sai de cena por completo" |

**Precisam do navegador (3), e o motivo de cada um NÃO é o WAF:**

| Consumidor | Motivo real |
|---|---|
| `anexar/mc_client.py` (anexar arquivo) | é upload por diálogo da tela — `input[type=file]` + etiqueta + Confirmar (`:719-735`), com prova relendo a grade (`:751`). Existe caminho de API (`POST /attachments/v2/batch` → PUT no S3 pré-assinado → GET, documentado em `agua_energia/coletor/lancar_mc.py:15-18`), mas é escrita e mexe em comprovante: não é conversão de transporte, é projeto próprio |
| `relatorios/extrato_mc.py` | o produto é um **PDF gerado pela página** (`Page.printToPDF` via CDP, `:324-332`), depois de mexer no CSS e no DOM (`:205-215`). Não há endpoint que devolva isso |
| `aportes/mc_catalogos.carregar_obras` (GraphQL) | o host `execute-api` só entra nos cabeçalhos quando o ERP carrega o FORMULÁRIO de lançamento (`:255-259`) — o token dele não sai do login. **Já está fora do caminho crítico**: `definir_obras` (`:252`) usa o REST da aba Contratos, e é esse que roda em produção |

**Caso à parte — `anexar/mc_api.py`:** tecnicamente pode virar HTTP direto (os
cabeçalhos que ele captura em `:52-53` são os do login), mas ele é a porta por
onde Anexar, Conferência, Pagamentos do Dia e Contratos falam com o ERP, e é o
único que monta a URL de consulta **reaproveitando a que a tela mandou**
(`:285-302`) em vez de escrevê-la. Migrar isso é trocar a fundação com a casa
em cima; por isso é o último.

Duas ressalvas que valem para qualquer migração:

- **MFA encerra o assunto.** `conciliacao/erp/api.py:129` para com recado
  próprio quando `mfaEnabled` vem verdadeiro: o login automático não passa por
  segundo fator. Se um dia a conta exigir MFA, o HTTP direto morre — e o
  navegador continua, porque `auth.py:247-268` sabe esperar a pessoa entrar na
  janela. O navegador é o plano B, não o padrão.
- **Uma sessão por usuário.** O `POST /users/login` do HTTP direto **derruba**
  a sessão do navegador (`conciliacao/erp/collect.py:98-108`). Não é detalhe:
  é o que define a ordem da coleta da Conciliação (navegador primeiro, API
  depois) e o que faz o `nuvem/contas_novas.py` rodar na ABERTURA, antes de
  existir Chrome (`:17-19`).

## 3. A forma proposta do pacote `erp/`

Quatro módulos, e cada um sabe uma coisa só.

```
erp/
  __init__.py    o que os consumidores importam
  hosts.py       ONDE. As URLs, os hosts de telemetria a ignorar, e nada mais
  sessao.py      QUEM. Login, os dois tokens, os cabeçalhos por host,
                 o user-agent — e o transporte HTTP direto
  pagina.py      COMO, pelo navegador. O `page.evaluate(fetch)` que hoje
                 está duplicado em anexar/ e aportes/
  paginacao.py   (depois) os dois dialetos de página, num lugar só
```

**`erp/hosts.py`** recolhe o que hoje está espalhado por sete arquivos:
`acessar.` (`anexar/config.py:70`, `relatorios/extrato_mc.py:39`,
`aportes/aportes_frame.py:37`, `conciliacao/erp/api.py:280`), `prod-erp-api`
(`aportes/mc_catalogos.py:36`, `pagamentos_dia/baixa_erp.py:33`,
`nuvem/contas_novas.py:45`), `legacy-api` (`aportes/mc_catalogos.py:37`,
`aportes/mc_lancamentos.py:21`, `pagamentos_dia/baixa_erp.py:32`,
`nuvem/contas_novas.py:46`) e os hosts de telemetria de
`aportes/erp_sessao.py:23`, que carregam token PRÓPRIO e cuja mistura já
produziu 401.

**`erp/sessao.py`** é o lugar onde a regra da seção 1 vira código —
`token_para(host)` e `cabecalhos_para(host)` —, junto do `user-agent` de
navegador (`conciliacao/erp/api.py:55`) e da política de novas tentativas: **só
GET repete**, 3 tentativas, 502/503/504, `raise_on_status=False`, copiada de
`nuvem/rest.py:55-76`. O motivo de só GET repetir é o mesmo dos dois lados:
reenviar um POST que criou algo e perdeu a resposta duplica o que foi criado.

**`erp/pagina.py`** existe porque a seção 2 mostrou que três consumidores
continuam no navegador, e porque o JS já está duplicado: `_JS_FETCH_JSON` em
`anexar/mc_api.py:55-59` e `_JS_FETCH` em `aportes/mc_catalogos.py:42-46` são o
mesmo bloco escrito duas vezes. Ele embrulha esse padrão e o POST
(`mc_catalogos.py:48-58`), com a mesma assinatura do transporte que o
`baixa_erp.py:208-214` já espera (`_buscar` / `postar`) — o que faz o
consumidor mais fácil de migrar não precisar de adaptador nenhum.

**`erp/paginacao.py`** fica para depois, mas o motivo já está inventariado: são
**dois dialetos**, e confundi-los falha em silêncio.

| Dialeto | Onde | Começa em | Fim | Armadilha |
|---|---|---|---|---|
| `pageIndex`/`pageSize` | `prod-erp-api` (contas, participantes, obras) | **1** | `hasNextPage` | trocar por `page`/`size` devolve sempre a primeira página, sem erro (`anexar/mc_api.py:627-629`) |
| `page`/`size` | `legacy-api` (parcelas, recebimentos, contatos) | **0** | `hasNextPage` ou `last` | `pageIndex`/`pageSize` são aceitos e **ignorados**, e a resposta volta com o padrão de 20 registros parecendo completa (`anexar/mc_api.py:537-540`); `page=1` traz a segunda página, vazia (`:402-403`) |

### Ordem de migração

Do que não tem como quebrar ao que quebra tudo. Um PR por linha.

1. **`nuvem/contas_novas.py`** — já é HTTP direto e já empresta o `SessaoApi`
   (`:223`). Trocar `_ConfigMinimo` + `SessaoApi` por `erp.Sessao` é
   substituição pura, e o `_ConfigMinimo` (`:56-59`) — que só existe para
   satisfazer uma assinatura — desaparece.
2. **`pagamentos_dia/baixa_erp.py`** — o transporte já é parâmetro (`:208`), e
   os dois métodos que ele exige são os que `erp/pagina.py` expõe. Nenhuma
   linha da regra muda; o `HOSTS` dele (`:38`) passa a sair do `erp/hosts.py`.
3. **`conciliacao/erp/api.py`** — o `SessaoApi` vira casca sobre `erp.Sessao`,
   e as 3 tentativas escritas à mão (`:69-81`) somem, porque o transporte novo
   fala por `requests` e ganha o `Retry` pronto. **Cuidado:**
   `nuvem/contas_novas.py` importa daqui, então esta linha vem depois da 1.
4. **`aportes/mc_catalogos.py` + `erp_sessao.py`** — `_headers_para` (`:141`) e
   `cabecalho` (`:168`) viram `Sessao.cabecalhos_para`; `_JS_FETCH`/`_JS_POST`
   saem para o `erp/pagina.py`. O `carregar_obras` (GraphQL) fica como está —
   é o único pedaço que o login não alcança.
5. **`conciliacao/erp/payments.py`** (+ `auth.py`, `browser.py`) — a grade vira
   `payable-installments/paginated-result`. É a linha que paga o documento
   inteiro: some a raspagem, some o login por navegador da Conciliação e some a
   exigência de janela visível (`browser.py:5-8`). Também é a mais cara de
   conferir, porque o resultado é dinheiro no painel do dia — vale comparar
   total a total contra uma coleta antiga antes de trocar.
6. **`relatorios/extrato_mc.py`** — só as constantes de host mudam (`:39-41`).
   O PDF continua saindo do navegador.
7. **`anexar/mc_client.py`** — só as constantes de host (via
   `anexar/config.py:70`). O anexo continua pela tela.
8. **`anexar/mc_api.py`** — **por último**. É ele que tira o token do cabeçalho
   da página logada (`:144-158`) e o que monta a consulta a partir da URL que a
   tela mandou (`:285-302`); e é dele que dependem Anexar, Conferência,
   Pagamentos do Dia e Contratos. Enquanto ele não migrar, `erp/` e ele
   convivem — o que é aceitável, porque o `erp/` nasce sabendo a regra dos
   tokens e ele nasceu adivinhando-a.

Uma observação de empacotamento, para quem for mexer: `erp/` é código do app e
precisa de linha própria no `codigo.zip` (`.github/workflows/build.yml`) e de
entrada em `_PASTAS` no `tests/test_imports_do_motor.py`. Pasta nova obriga a
mexer no `build.yml`, e o job `motor` recusa push que toque nesse arquivo sem
subir o `motor_minimo.txt` junto — ver a regra de ouro do `CLAUDE.md`.
