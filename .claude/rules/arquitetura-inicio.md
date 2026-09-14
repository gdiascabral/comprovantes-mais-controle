---
paths:
  - "inicio/**"
---

# Arquitetura: inicio/

> Trecho da seção "Arquitetura", movido do `CLAUDE.md` em 14/09/2026 sem mudar uma palavra.
> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI — este é o lugar deste texto agora.

- `inicio/inicio_frame.py` — aba Início, a primeira tela: os KPIs do dia
  (`CartaoKPI`), a situação de cada rotina (`ROTINAS`, onde o `ritmo` decide
  quando "não rodou hoje" vira pendência — para uma rotina diária é aviso; para
  uma mensal, no dia 3, não é) e a atividade recente. **Ela não abre navegador
  e não coleta nada.** O app abre em cima de UMA sessão do ERP, e uma tela de
  resumo que buscasse os pagamentos do dia na abertura consumiria essa sessão
  antes de a pessoa clicar em coisa alguma — a aba que ela abrisse em seguida
  teria de refazer o login. Então o Início LÊ o que as rotinas já contaram no
  `atividade.jsonl`, e relê a cada troca de aba pelo `ao_abrir()`. A
  consequência aparece na tela e é de propósito: número que ninguém apurou hoje
  sai como "—", com "rode a rotina para atualizar" embaixo — **zero seria pior
  que um traço**, porque zero é uma afirmação sobre o dia que o app não tem como
  fazer sem falar com o ERP. Uma coisa pendente: construí-la custa **~670 ms**,
  mais da metade do ~1,2 s que as doze abas somam na abertura, contra menos de
  100 ms de qualquer outra (medido no PR #29) — e o custo é trabalho feito na
  CONSTRUÇÃO, não import, então adiar import não resolve.
