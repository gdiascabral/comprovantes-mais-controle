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
