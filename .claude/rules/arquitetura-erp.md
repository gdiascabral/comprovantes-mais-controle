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
  **Login por fora derruba METADE da sessão do Chrome, e isso tem cara própria**
  (06/10/2026). O `POST /users/login` feito por HTTP (o do próprio app na
  abertura, no "⟳ Atualizar contas", na coleta dos saldos) cancela o
  `accessToken` do legacy-api que o Chrome do app está usando, mas o `jwtToken`
  do `prod-erp-api` continua valendo. A página parece logada, o que lê do
  `prod-erp-api` funciona, e só o legado toma 401. Nos Aportes isso trazia
  contas e participantes e parava nas categorias; a leitura pela metade ficava
  guardada e o "Lançar" acusava "Nada parecido no cadastro" para cadastros que
  existiam. Remédio em `aportes/aportes_frame._preparar_sessao`: leitura só é
  guardada inteira; 401 do legado (ou captura que não acontece, porque a página
  recarregada cai no login) leva a UM `garantir_login` e UMA releitura; e a
  captura começa sem o token velho. Provado ao vivo forçando um login por fora
  entre a captura e a leitura (`tests/test_aportes_cadastro_401.py`).

- **O Chrome central e o porteiro** (14/10/2026; manual em `docs/PORTEIRO.md`).
  O ERP aceita uma sessão por usuário, mas abas do MESMO perfil do Chrome
  dividem a sessão. Então um Chrome por acesso, com CDP só em 127.0.0.1, e os
  robôs abrem aba nele em vez de logar. Três módulos:
  `central.py` sabe ONDE está cada acesso (`acessos.json` na pasta central,
  lido com BOM ou sem; formato errado vira `ValueError` com o caminho) e COMO
  subir o Chrome uma vez (`garantir_chrome`, sob trava de arquivo, apagando o
  `History` do perfil antes do `popen`, porque o Chrome 152 cai no 1º download
  de perfil que já baixou). Não importa nada do app: o água e energia o copia
  byte a byte em `coletor/mc_central.py` — mudou aqui, copie lá.
  `sessao_pagina.py` é a `SessaoPelaPagina`, o que `Sessao.logar` devolve com
  o central ligado: uma aba própria numa thread própria, que copia a
  autenticação do tráfego da tela e faz `fetch` de dentro da página; uma por
  (processo, acesso), guardada em `sessao._CENTRAIS` e fechada no `atexit`.
  `esquecer_central(nome, sessao)` descarta a guardada (fecha a aba, quieto)
  SÓ se ela `is` a sessão que falhou — a recriada por outra aba não cai —,
  para o próximo `logar` montar outra — a tela do dia usa depois de um erro do ERP
  (a guardada pode estar `viva` com a autenticação de antes de um login).
  `porteiro.py` (no servidor) entra pela tela: sobe o Chrome, confere o login
  a cada ciclo e fecha a própria aba ao sair (Ctrl+C, SIGTERM/SIGBREAK,
  `atexit`).
  **Regra: robô nunca fecha o Chrome central** — nem `browser.close()` nem
  `ctx.close()`; com `connect_over_cdp` isso derruba os outros e a sessão.
  Cada um fecha só as abas que abriu (`AbaCentral`).
  **A trava de login é comum ao app e ao água e energia**:
  `<perfil>/../.<nome>.login.trava`, pela mesma `central.trava`; quem precisa
  logar no central espera quem já está logando.
  **O LOGIN PRINCIPAL** (28/10/2026, decisão do dono; `login_principal.py` +
  `login_tela.py`). diagnostico.log de 22 a 28/10: "o Chrome central
  'principal' não está logado no ERP — o porteiro precisa entrar" em TODA
  abertura (a conferência de contas novas desistia calada) e no "Buscar
  pagamentos e saldos". No notebook não há porteiro, e a `SessaoPelaPagina`
  nunca entrava: nascia em `#/login` em CORRIDA com o login da aba do Anexar e
  esperava 90 s. Agora há UM caminho de login, sempre primeiro:
  `login_principal.garantir_logado(acesso, caiu=False, log=) -> bool` (True =
  entrou agora). Logado (porteiro de pé no servidor, ou outra aba já entrou):
  ninguém loga. Fora: UMA aba própria, marcada por `window.name =
  "mc-login-principal"` e reaproveitada (não acumula), entra pela tela com o
  login guardado e termina PARADA em `#/app/dashboard` — só desconecta, não
  fecha. Os outros pedidos esperam: no processo, uma `threading.Lock` por
  acesso; entre processos, a trava de arquivo `.<nome>.login.trava` (espera
  `ESPERA_TRAVA` 180 s, `velha` = `login_tela.VELHA_TRAVA` 600 s, a mesma de
  sempre), relendo a tela depois de pegá-la (o outro pode ter acabado de
  entrar). Verificação recente (`VALIDADE`, 30 s) vale para quem não viu a
  queda; `caiu=True` só a aceita se for POSTERIOR ao pedido — três pedidos
  "caiu" juntos fazem UM relogin. Roda numa thread própria, com Playwright
  próprio (quem pede já tem o seu, e sync só serve na thread que o criou).
  `login_tela.py` é o caminho do MCClient num lugar só: `SINAIS_DE_LOGIN`,
  `JS_LOGIN_ANGULAR` + `entrar_pelo_controller` (scope do AngularJS),
  `credencial_do_acesso` (a do `acessos.json`, senão o `login.dat` do app;
  nunca impressa) e `caminho_da_trava`; `MCClient._login_pelo_controller` e
  `_credencial` delegam para ele. Sem login guardado o erro diz "entre no ERP
  pelo app uma vez (Minha aba no ERP) para guardar o login". **Os três
  consumidores**: `SessaoPelaPagina.do_acesso` pede o principal ANTES de abrir
  a aba (a leitura nunca navega antes dele); caindo mesmo assim em `#/login`
  (queda no meio, 401, `relogar`), recarrega a rota de captura a cada
  `_RECARGA_NO_LOGIN` (5 s) — pega o login de outra aba — e só depois de
  `_SO_RECARGA` (15 s) pede o principal com `caiu=True`; NUNCA entra sozinha.
  Tela que não mostra nem área logada nem login dá erro dizendo isso (o recado
  do porteiro saiu). `reentrou()` avisa uma vez que o principal entrou por ela:
  a tela do dia põe no Registro "a sessão do ERP tinha caído; entrei de novo e
  li os saldos" (o erro cru vai ao diagnóstico). O `MCClient` central pede o
  principal, confere a própria aba (`_conferir_sessao`, com reload), e vendo
  a queda pede `caiu=True` antes de cair no login próprio de sempre (sob a
  trava; fica como último recurso, que deixa a pessoa entrar na janela). A
  abertura (contas novas) passa por `SessaoApi.logar` → `Sessao.logar` →
  `SessaoPelaPagina` e ganha o mesmo caminho; o recado da desistência é o
  motivo real. **O porteiro não muda**: abre o `MCClient` com
  `login_principal = False`, porque ele É quem entra. Testes:
  `tests/test_erp_sessao_pagina_login.py` (dublês; o conftest proíbe a aba
  real do principal, `_login_principal_nunca_abre_chrome` — um teste com o
  `garantir_chrome` trocado por 127.0.0.1:9230 encontrou o Chrome central do
  dono vivo nessa porta).
  **`MC_CENTRAL=off`** desliga tudo e o app volta a ser o de antes; renomear o
  `acessos.json` para `acessos.json.off` faz o mesmo na máquina inteira.
  Arquivo de acessos com problema falha FECHADO (`ErpErro`/`RuntimeError`),
  nunca cai no login HTTP — que derrubaria a sessão central.
