---
paths:
  - "erp/**"
  - "conciliacao/erp/**"
  - "anexar/mc_api.py"
  - "aportes/mc_catalogos.py"
  - "pagamentos_dia/baixa_erp.py"
  - "nuvem/contas_novas.py"
  - "ferramentas/sonda.py"
  - "docs/ERP-CLIENTES.md"
  - "tests/test_erp*.py"
---

# Arquitetura: erp/ (falar com o Mais Controle)

> Trecho da seção "Arquitetura", movido do `CLAUDE.md` em 21/09/2026 sem mudar uma palavra.
> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI — este é o lugar deste texto agora.

- `erp/` — um lugar só para falar com o Mais Controle, com **a regra dos dois
  tokens escrita UMA vez**. Oito lugares do app tinham redescoberto por conta
  própria qual token pedir, quais cabeçalhos copiar e qual `user-agent` passa
  pelo WAF, e o conhecimento se contradizia POR ESCRITO — um arquivo dizia "o
  token é o `jwtToken`, NÃO o `accessToken`" e outro dizia o contrário, os dois
  certos para back-ends diferentes, e nenhum dizendo isso inteiro. O inventário
  que levantou tudo, com `arquivo:linha` para cada afirmação, é
  `docs/ERP-CLIENTES.md` (PR #22); o pacote é o PR #24. Três módulos, uma frase
  cada: `hosts.py` é ONDE (só endereços, não fala com ninguém — as mesmas
  quatro URLs estavam escritas em sete arquivos), `sessao.py` é QUEM (o login,
  os dois tokens, os cabeçalhos por host, o `user-agent` e o transporte HTTP
  direto) e `pagina.py` é COMO, quando é pelo navegador (o
  `page.evaluate(fetch)` que estava duplicado em `anexar/mc_api.py` e
  `aportes/mc_catalogos.py`, com espaçamento diferente).
  **A regra, em `sessao.token_para`**: o login é UM só
  (`POST {legacy}/users/login`) e devolve DOIS tokens — `jwtToken` (~348 chars,
  JWT, vale 24 h) é o do `prod-erp-api`; `accessToken` (27 chars, nem é JWT,
  vive SEGUNDOS) é o do `legacy-api`. Trocar um pelo outro devolve 401, e vale
  igual para o token capturado do navegador: foi assim que o token da
  telemetria acabou usado contra o `prod-erp-api`. Os cabeçalhos também são
  conjuntos diferentes (`cabecalhos_para`), e **só o legado manda `user-id`** —
  sem ele o ERP recusa o lançamento com "não achei o usuário responsável", que
  não aponta para lugar nenhum.
  **O 401 do legado é rotina; o do `prod-erp-api` é notícia.** No legado o
  token venceu entre uma chamada e a seguinte, então `Sessao.pedir` relogia
  **uma vez** e repete — e **só em GET**, ou em PUT/POST que o CHAMADOR marcar
  com `idempotente=True`, porque um POST que criou lançamento e perdeu a
  resposta duplica o que criou (ver "Aporte não se repete"). O padrão é o
  seguro: esquecer a marca custa uma exceção, pôr a marca onde não cabe custa
  uma segunda baixa. No `prod-erp-api` um token de 24 h recusado é sessão
  derrubada de verdade — o ERP aceita UMA sessão por usuário, e relogar ali
  seria tomá-la de volta, em silêncio, de quem estiver com ela; sobe
  `SessaoRecusada` e quem chamou decide. Quem separa os dois casos é
  `ErpErro.codigo`, o status HTTP, e **não o TEXTO da mensagem** — decidir por
  `str` quebra na primeira vez que alguém melhora a frase. Sessão nascida de
  `de_login` fica sem a credencial em memória e por isso não relogia: ninguém
  relogia em nome de quem não entregou a senha.
  **A migração é uma aba por PR, e três já entraram.**
  `conciliacao/erp/api.py` virou casca sobre `erp.Sessao` (PR #31) — mesma
  classe, mesmo construtor, mesmos retornos e as mesmas exceções, e por isso
  `nuvem/contas_novas.py` e `ferramentas/sonda.py`, que emprestam o `SessaoApi`,
  migraram de graça, sem serem tocados; o laço de 3 tentativas escrito à mão
  saiu, porque falando por `requests` o `Retry` vem pronto.
  `pagamentos_dia/baixa_erp.py` (PR #33) foi o mais barato porque **nunca soube
  se havia navegador**: exige do transporte só `_buscar`/`postar` e lê
  `{"__erro": status}`, que é exatamente o que `erp.TransportePagina` expõe — e
  a baixa dele **não é marcável como idempotente**, porque o `POST .../paids`
  CRIA um pagamento. `conciliacao/erp/payments.py` (08/09/2026) ganhou o par
  `payments_api.py`, que lê a lista pela mesma `SessaoApi` dos saldos — o
  token sai do host da URL, então um login serve aos dois back-ends. Faltam os
  consumidores 4, 6, 7 e 8 da ordem escrita no fim do
  `docs/ERP-CLIENTES.md`, e **`anexar/mc_api.py` é o último de propósito**: é
  ele que tira o token do cabeçalho da página logada e monta a consulta
  reaproveitando a URL que a TELA mandou, e dele dependem Anexar, Conferência,
  Pagamentos do Dia e Contratos — migrar isso é trocar a fundação com a casa em
  cima. Enquanto ele não migra os dois convivem, o que é aceitável: o `erp/`
  nasce sabendo a regra dos tokens, e ele nasceu adivinhando-a.
