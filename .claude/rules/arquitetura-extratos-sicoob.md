---
paths:
  - "extratos_sicoob/**"
---

# Arquitetura: extratos_sicoob/

> Trecho da seção "Arquitetura", movido do `CLAUDE.md` em 21/09/2026 sem mudar uma palavra.
> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI — este é o lugar deste texto agora.

- `extratos_sicoob/` — aba Extratos Sicoob: cria a árvore do fechamento
  mensal e baixa OFX + PDF de cada conta do SicoobNet Empresarial.
  **Único módulo com navegador PRÓPRIO** (executor de 1 worker e perfil
  `.chrome_profile_sicoob`): é outro site e outro login, então pendurar na
  thread do Anexar só acoplaria. Os módulos têm prefixo `sicoob_` porque nome
  de módulo é global no sys.path — um `config.py` aqui sequestraria o
  `import config` do Anexar. **O login é manual, por decisão de projeto**: a
  tela do Sicoob tem reCAPTCHA, e nada aqui tenta contorná-lo; o robô espera
  a lista de contas aparecer e assume dali. O mapa conta→pasta vive em
  `contas_sicoob.json` FORA do repo (número de conta e razão social), como o
  `pix_reembolso.json`. Armadilhas resolvidas: (1) **o botão "PDF" é
  inutilizável** — chama `window.print()` e abre o preview do Chrome, que é
  MODAL, trava o navegador e não fecha nem por `Target.closeTarget`;
  diferente do ERP, trocar `window.print` NÃO adianta (o site guarda a
  referência antes), e imprimir a SPA sai com a tela do IB e o painel
  sobreposto. O PDF vem do formato **HTML**, que é download comum, aberto numa
  aba e convertido por `Page.printToPDF`; (2) o formato de
  exportação só marca clicando no `span.checkmark` do `ib-sicoob-input-radio`
  — no texto ou no card não dá erro e não marca nada, e a falha só apareceria
  no passo seguinte, por isso conferimos o botão antes de clicar; (3) o painel
  é um drawer com `div.overlay.visivel` que intercepta TODO clique, inclusive
  o "Trocar conta" — fechá-lo é obrigatório entre contas, e clicar no próprio
  overlay resolve; (4) no datepicker os dias do mês são `<a>` e os vizinhos em
  cinza são `<span>` em `td.ui-datepicker-other-month`, então mirar
  `td:not(.ui-datepicker-other-month) > a` acerta elemento e mês de uma vez;
  há `select` de mês e ano (mês 0-indexed), dispensando as setas. Antes de
  arquivar, o OFX é conferido contra `ACCTID` e período — o pior erro possível
  é o extrato de uma empresa cair na pasta de outra, e nada no disco denuncia.
- **O Chrome do Sicoob abre SEMPRE em pt-BR** (`locale="pt-BR"` e
  `--lang=pt-BR` no `SicoobClient`), 05/10/2026. O Sicoob reconhece o "PC
  cadastrado" — e aceita UM por usuário — por um retrato que a página monta
  antes de criptografar: a extensão (CPU, memória, discos fixos, telas), WebGL,
  `navigator.language`, resolução e núcleos. O perfil do app estava com o
  idioma das páginas vazio, o Chrome caiu em pt-PT e o banco passou a pedir o
  cadastro do PC. Provado ao vivo mudando só o idioma: `POST
  /api/dispositivo-usuario/identificar` respondeu 3 (desconhecido) com pt-PT e
  2 (reconhecido) com pt-BR. Para diagnosticar de novo: o retrato aparece
  interceptando `JSON.stringify` na página, antes da cifra. Guardado por
  `tests/test_sicoob_idioma.py`. NUNCA abrir este perfil num Chrome comum nem
  com porta de depuração — só como o app abre.
- **O aviso do banco (SweetAlert2, `.swal2-container`) cobre o ⇄**, 20/10/2026.
  A 1ª "Conferir agendamentos" pelo app parou antes da 1ª conta: Home às
  17:01:59, Chrome fechado às 17:02:44 — os 45 s da espera pela lista; as seis
  contas saíram "não foi lida". Os scripts da prova de 15/10 fechavam o aviso
  à mão; o app não. Hoje `_abrir_selecao` chama `_fechar_aviso` antes do
  clique — só com OK/FECHAR/ENTENDI quando é o único botão, senão Esc; botão que confirma ("Sim",
  "Assinar") nunca é clicado —, e `ir_para_selecao`, se a lista não abrir,
  confere a sessão, recarrega e tenta UMA vez mais (o cabeçalho com o ⇄
  também some depois de várias trocas). A conta que fica sem ler leva o
  porquê para a tabela (`agendamentos_sicoob.motivo_da_parada`). Guardado
  por `tests/test_sicoob_aviso.py`.
- **`saldo.py` lê o saldo de cada conta do Sicoob** (entrega 4, "Pagamentos
  do dia"), só leitura e par de `pendencias.py`: entra na conta pelo ⇄
  (`acessar_conta`), confere a conta no cabeçalho da tela e só então pede, com
  o mesmo `fetch` da página logada. **Endereço medido em 22/10/2026** com o
  dono logado e os saldos conferidos na tela: `GET /api/home/obter-informacoes-
  widget-movimentacoes-inicio` (o do quadro de movimentações da Home), sem
  conta no endereço nem no pedido — a resposta é da conta SELECIONADA. A
  página chama com `?block-ui=...` e o fetch do app não leva (provado sem ele). O saldo é `contaCorrente.extratoContaCorrente.resumo.
  saldoEmContaCorrente` com o sinal em `naturezaSaldoRes` (C/D; outro valor
  é recusado); `erroServicoMovimentoContaCorrente` true vira "não lido"; e a
  conta da resposta (`cabecalho.numContaCorrente`, número JSON) é conferida
  de novo contra a pedida: o número traz TODOS os dígitos com o DV
  (conferido ao vivo), e a igualdade é exata, ignorando só zeros à esquerda;
  sem número, recusa. A prova ao vivo do coordenador (22/10, só leitura) deu
  HTTP 200 nas 3 contas, sem `block-ui`. Tudo num bloco de constantes; `ROTA_SALDO = ""` desliga a
  leitura. Se a prova ao vivo der 401/403 com a sessão viva, a contingência
  está na docstring (voltar a "" e escutar a resposta da Home, num plano à
  parte). O bloco de constantes é o ÚNICO lugar do endereço e dos campos.
  **Falhas**: sessão caída e endereço mudado (`EnderecoMudou`: 404/405/410,
  resposta que não é JSON) PARAM a fila e marcam as contas que faltavam com o
  porquê; formato estranho numa conta (`FormatoDaConta`) deixa só ela "não
  lida", e duas seguidas param a fila. Nenhuma conta some e nenhuma vira
  R$ 0,00. Quem chama é `tela_do_dia/sicoob_na_tela.py`, numa thread própria
  (o `SicoobClient` nasce e morre nela). Guardado por
  `tests/test_sicoob_saldo.py`.
