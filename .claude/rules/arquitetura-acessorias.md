---
paths:
  - "acessorias/**"
---

# Arquitetura: acessorias/

> Trecho da seção "Arquitetura", movido do `CLAUDE.md` em 21/09/2026 sem mudar uma palavra.
> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI — este é o lugar deste texto agora.

- `acessorias/` — aba Acessórias: envia o fechamento ao escritório contábil
  pelo portal (uma solicitação por empresa, com o .zip anexado). **Terceiro
  navegador próprio** (perfil `.chrome_profile_acessorias`), pelo mesmo motivo
  do Sicoob: outro site, outro login, e o Playwright síncrono não divide
  thread. O login também é manual, mas aqui não há captcha — o perfil
  persistente + "Manter conectado" fazem a sessão durar de um mês para o outro.
  **A decisão que sustenta o resto: a mensagem é derivada do anexo.** A lista
  de contratos do comentário sai de DENTRO do zip (as entradas
  `.../CONTRATOS/`, gravadas pela aba Contratos), e não do ERP nem da aba
  Contratos em memória: assim ela não custa sessão do ERP — que só aceita uma
  por usuário — e não pode contradizer o que foi enviado. `pacote.py` é puro e
  recebe `nome_do_mes`/`nome_pasta_empresa` por parâmetro, como
  `contratos/destino.py`, e é ele quem casa o zip com a empresa usando a MESMA
  função que gerou aquele nome no `sicoob_zipar`. O portal é HTML puro (sem
  Angular e sem React): toda tela é endereçável por URL
  (`/<escritorio>/<id>/SOL/0` é o formulário em branco), então navegar é
  `goto`. Três armadilhas do formulário, medidas na tela e resolvidas em
  `portal.py`: (1) **`#SolAss` (o assunto) fica FORA do `<form>`** e é
  recolhido por JS no envio — um multipart montado à mão chegaria ao escritório
  sem título e sem erro, o que enterra a ideia de postar direto em
  `/sysvipsolAjax`; (2) **os `value` dos dois selects não seguem a ordem da
  tela** (DPTO_FINANCEIRO é o último item e vale 4; a prioridade é invertida,
  Baixa=3 e Muito Alta=0), então toda escolha é por RÓTULO — por índice, o
  fechamento vai para o departamento errado sem nada denunciar; (3)
  `SolDptoDcvID` é um segundo select, hoje mudo, e ganhando opções o módulo
  PARA em vez de adivinhar sub-departamento. Duplicidade é conferida no
  PORTAL, não em arquivo local (ao contrário dos Aportes): a lista de
  solicitações responde "já enviei esta?", e perguntar não envelhece — mas
  exige abrir também a aba Encerradas, que só carrega ao ser clicada. E nada
  de "enviado" sem prova: depois do Salvar/Enviar, `conferir_envio` relê a
  lista, abre a solicitação e confirma o anexo pelo nome.
  **O Salvar/Enviar é XHR, e a espera é pela RESPOSTA** (14/09/2026). Na
  primeira rodada real as onze empresas saíram "não confirmado": a espera era
  `wait_for_load_state("networkidle")`, que volta na hora porque a página não
  troca, e o `goto` da conferência cancelava o upload ainda subindo. Hoje o
  clique roda dentro de `page.expect_response` (POST para `/sysvipsolAjax`, ou
  qualquer POST multipart), resposta não-2xx ou prazo vencido é
  `EnvioNaoConfirmado`, a lista é relida até três vezes e a mensagem diz
  quantas solicitações o robô leu — zero numa empresa com meses enviados é
  "a tela mudou", não "não chegou". **O lote PARA na primeira não
  confirmada**: é estado desconhecido, e o que derruba uma derruba todas. A
  aba ganhou "Gerar os .zip", que chama o MESMO `sicoob_zipar.zipar_mes` da
  aba Extratos Sicoob e emenda o Preparar. `vip_id`, `vip_nome`
  (por empresa) e `vip_url` (o endereço do escritório) moram no
  `contas_sicoob.json`, FORA do repo — o URL carrega o nome de um fornecedor
  real, e um mapa a mais seria uma divergência a mais.

## O segundo bloco: guias do mês → Mais Controle (22/09/2026)

A aba passou a ter DOIS assuntos, e eles andam em sentidos opostos: o de cima
manda o fechamento ao escritório; o de baixo traz de volta o que o escritório
publicou e lança no ERP. O segundo mora em `guias/`, e não aqui, porque este
arquivo já tinha 660 linhas — `acessorias/frame.py` só o embute.

**Ele entra em `corpo`, como os cartões 1 e 2, e ANTES do `encaixar`.** A
v2.0.208 saiu com ele invisível: era filho da ABA e empacotado DEPOIS, e o
`pack` atende os filhos na ordem em que foram empacotados — a área rolável,
que entra por último com `expand=True`, já tinha levado todo o espaço. O bloco
era construído e ficava com altura zero, sem erro nenhum para denunciar, e
nenhum teste pegou porque todos constroem o painel SOZINHO (`GuiasPainel(raiz,
…)`) e nada exercitava a aba montada. Quem guarda isso agora é
`test_o_bloco_das_guias_mora_na_area_que_rola_e_tem_altura`, que mede a
geometria numa janela própria de tamanho conhecido — a `raiz` do conftest é
compartilhada e pequena, e redimensioná-la mexeria com os testes vizinhos.

A rodada dele é partida em DUAS fases, e a emenda passa pela fila da tela: o
portal roda no executor DESTA aba (Chrome e thread próprios), e tudo que fala
com o Mais Controle vai por `anx.submeter`, o executor dono dos objetos do
Playwright — as outras cinco abas já faziam assim, e tocar `anx.mc.page` de
fora dele dá erro de greenlet.
