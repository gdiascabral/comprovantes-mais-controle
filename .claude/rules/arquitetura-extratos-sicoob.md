---
paths:
  - "extratos_sicoob/**"
---

# Arquitetura: extratos_sicoob/

> Trecho da seção "Arquitetura", movido do `CLAUDE.md` em 14/09/2026 sem mudar uma palavra.
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
