---
paths:
  - "ferramentas/**"
  - "cnab240/ferramentas/**"
---

# Arquitetura: ferramentas/

> Trecho da seção "Arquitetura", movido do `CLAUDE.md` em 14/09/2026 sem mudar uma palavra.
> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI — este é o lugar deste texto agora.

- `ferramentas/` — as três ferramentas locais, **fora do `codigo.zip`** por
  `_PASTAS_SO_DO_REPO` (`tests/test_empacotamento.py`), o mesmo tratamento do
  `cnab240/ferramentas/` e do `nuvem/migrar.py`: o app nunca as importa.
  **`galeria.py`** monta as 12 telas num esqueleto FIEL — a mesma
  `widgets.BarraTopo`, o mesmo `widgets.painel_menu` e as mesmas classes de
  aba, construídas direto dentro de um `Tk()`, sem login, sem cadastro e sem
  rede — e fotografa cada uma nos dois temas, com `--escala` para simular a
  escala de exibição do Windows. Não é teste: não compara nada e não falha
  sozinho; a comparação é o olho de quem mexeu. Baseline de pixel no CI foi
  considerada e recusada — o runner é headless e não renderiza Tk de forma
  confiável, e uma baseline envelhece a cada ajuste de 1 px em qualquer cartão.
  Duas armadilhas já morderam: ela fotografa a **TELA**, então precisa de
  `-topmost` antes de cada captura (é pedido de empilhamento, que o Windows
  concede a processo sem interação — ao contrário de `SetForegroundWindow`,
  que ele recusa, e a primeira rodada fotografou a janela errada); e **monitor
  que apaga no meio da rodada não dá erro** — o grab devolve o retângulo preto,
  o `save()` grava um PNG de 3 KB e o console anuncia sucesso, que foi como a
  pasta "depois" inteira do PR #15 saiu preta e só se descobriu ao abrir os
  arquivos. Hoje a imagem é medida antes de ir ao disco (`getextrema()`) e uma
  cor só de canto a canto vira `CapturaInutil`: nada é gravado, a linha sai
  como erro e a rodada termina em código 1. `_tela_acordada()` segura o monitor
  pelo tempo da rodada, e janela minimizada é recusada antes do grab (o Windows
  a estaciona fora da tela).
  **`sonda.py`** pergunta às 07:00, por tarefa agendada do Windows, se os três
  sistemas de fora ainda respondem — o ERP, o Inter e o Sicoob, nenhum com
  contrato de interface conosco, e os três já tendo quebrado no meio de um
  pagamento, que é o pior momento possível para descobrir. Ela **não corrige e
  não decide nada**: uma linha por sistema no `sonda.log` e, falhando algo, um
  `sonda.ALERTA.txt` com o resumo — que é **apagado** quando tudo volta a
  passar, porque alarme que fica para trás depois de resolvido é a forma mais
  rápida de ensinar alguém a ignorar alarme. **Nenhum navegador é aberto**, e
  isso não é economia: o ERP aceita uma sessão de navegador por usuário, e um
  Chrome às 07:00 derrubaria o de quem estivesse trabalhando — o login dela é
  por API, HTTP puro, o mesmo que o app já faz a cada abertura. E ela prova
  coisas diferentes sobre cada portal, porque eles respondem coisas diferentes:
  o **Sicoob não responde a cliente HTTP que não seja navegador** (medido em
  02/09/2026 — o TLS fecha em ~180 ms e a conexão trava na LEITURA, com os dois
  métodos e o jogo completo de cabeçalhos), então ali a sonda cai no aperto de
  mão TLS, que prova que o nome resolve, que a porta atende e que o certificado
  vale, e a linha do log diz exatamente isso. Dizer menos e dizer verdade, em
  vez de alarmar todo dia sobre um sistema que está de pé.
  **`sentinela_erp.py`** é a irmã da sonda e faz a pergunta que a sonda não
  faz: a sonda prova que o ERP **responde**; a sentinela prova que o
  **contrato não mudou**. Em 10/08/2026 o ERP respondeu 200 o dia inteiro
  enquanto a tela `#/accounts` virava React — a sonda teria passado, e a
  leitura de saldos quebrou num pagamento. O front do Mais Controle publica
  esse contrato sem querer, em dois bundles JavaScript PÚBLICOS (o legado
  AngularJS, com hash no nome que muda a cada build, e o React, de nome fixo):
  dentro deles estão as rotas de API (`"baseUrl","/payable-installments"`), os
  métodos que as chamam com verbo e caminho, as telas (`path:"/accounts"`), os
  hosts de cada back-end, os comandos de pré-lançamento e o `buildNumber`.
  Todo dia às 07:05 ela baixa os dois — GET público com o `user-agent` de
  Chrome, **sem login, sem sessão e sem navegador**, e é por isso que pode
  rodar com o dono trabalhando —, extrai esse inventário por expressão
  regular, grava `sentinela/ultimo.json` mais uma cópia datada e compara com o
  de ontem. O que SUMIU vem primeiro no `sentinela.ALERTA.txt`, porque rota
  que sumiu é o que quebra o app; o que apareceu vem depois; hash ou
  `buildNumber` que mudou sem o inventário mudar é build novo sem mudança de
  contrato, e o alerta diz isso com essas palavras. Mesmas regras da sonda:
  uma linha por rodada no `sentinela.log`, ALERTA apagado quando a rodada é
  igual, código de saída 1 quando mudou ou não baixou, e a primeira rodada só
  grava ("primeira fotografia"). Quando alarma, ela SUGERE rodar a sonda e
  nunca a roda: logar no ERP é decisão de quem sabe se há alguém com sessão
  aberta. A armadilha do desenho: extrator que deixa de casar não dá erro,
  devolve lista vazia — e quem grita é a comparação, porque tudo o que havia
  ontem terá "sumido". Por isso `tests/test_sentinela_erp.py` testa cada
  expressão contra um trecho fictício no FORMATO do bundle: o formato é a
  coisa medida.
