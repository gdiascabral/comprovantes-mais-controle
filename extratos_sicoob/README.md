# Extratos Sicoob

Cria as pastas do fechamento mensal e baixa o extrato de cada conta do Sicoob
em **OFX** e **PDF**, já nomeado e no lugar certo.

Substitui o trabalho de entrar conta por conta no internet banking, ajustar
período e ordenação, exportar dois arquivos e arrastá-los até a pasta da
empresa — vezes o número de contas, todo mês.

## Como usar

Pela aba **Extratos Sicoob** do app, na ordem dos cartões:

1. **Mês do fechamento** — vem preenchido com o mês anterior. Só mude para
   refazer um fechamento antigo.
2. **Conferir e criar pastas** — mostra a árvore inteira, marcando com `NOVA`
   o que ainda não existe, e pede confirmação antes de criar.
3. **Baixar extratos do Sicoob** — abre o Chrome. **Você faz o login** (a tela
   do Sicoob tem reCAPTCHA); assim que a lista de contas aparecer, o robô
   assume e percorre as contas sozinho.
4. **Gerar os .zip por empresa** — rode só depois que os outros bancos
   entrarem, senão o zip sai com o mês pela metade.

O ⏹ Parar interrompe depois da conta atual, sem perder o que já foi baixado.

## O arquivo de contas

O mapa conta→pasta fica em `contas_sicoob.json`, ao lado do executável.
**Ele não vai para o repositório** — tem número de conta e razão social, e o
repo é público. Se o arquivo não existir, o app cria um modelo com contas
fictícias e avisa onde preencher.

```json
{
  "raiz": "C:/Arquivos Morais/EXTRATOS",
  "empresas": [
    {
      "nome": "BURITIS",
      "pastas_vazias": ["CAIXA", "CONTRATOS", "INTER"],
      "contas": [{"numero": "50.019-4", "pasta": "SICOOB"}]
    }
  ]
}
```

- `pastas_vazias` — pastas criadas mas **não** preenchidas por esta automação
  (bancos que você baixa por fora). Empresa sem conta Sicoob entra só aqui.
- `contas` — as contas do Sicoob; `pasta` é o destino dos arquivos.

Empresa com subcontas declara uma entrada por conta, cada uma com sua pasta.
O padrão dos nomes é `SUBCONTA - <número sem ponto> - <descrição> - SICOOB`.

## Onde os arquivos vão parar

```
<raiz>/<ANO>/<MÊS>/<MÊS ANO - EMPRESA>/<PASTA>/AAAAMM SICOOB.ofx
                                                AAAAMM SICOOB.pdf
```

Exemplo: `C:/Arquivos Morais/EXTRATOS/2026/JULHO/JULHO 2026 - BURITIS/SICOOB/202607 SICOOB.ofx`

## A trava de segurança

Antes de gravar, o OFX é lido e conferido: o `ACCTID` precisa ser a conta
esperada e o período precisa cobrir o mês pedido. Não batendo, **o arquivo não
é gravado** e a conta aparece como pendência no relatório final.

Isso existe porque o pior erro possível aqui não é falhar — é o extrato de uma
empresa ser gravado, com o nome certo, dentro da pasta de outra. Ninguém
percebe isso olhando a pasta.

## Quando algo dá errado

Uma conta que falha **não derruba o lote**: vira linha no relatório e o robô
segue. Ao final, o resumo diz o que entrou e o que faltou. Basta rodar de novo
— o que já está no disco é sobrescrito sem problema.

| Mensagem | O que fazer |
|---|---|
| "o arquivo de contas não existe" | Preencha o `contas_sicoob.json` que foi criado |
| "conta não encontrada na lista do Sicoob" | Confira o número no JSON, ou se o acesso enxerga essa conta |
| "o OFX é da conta X, esperava Y" | O mapa está trocado — não mexa nos arquivos, corrija o JSON |
| "o período não ficou como pedido" | Layout do datepicker mudou; ver *Manutenção* |
| "as pastas do mês ainda não existem" | Rode o passo 2 antes do 3 |

## Manutenção

O Sicoob é uma SPA Angular e muda de layout sem aviso. Os seletores estão todos
em `sicoob_client.py`, com comentário explicando o porquê de cada um. Três
armadilhas já resolvidas, que provavelmente voltam a morder:

- **Nunca clique no formato "PDF".** Ele chama `window.print()` e abre o
  preview do Chrome, que é modal, trava o navegador e não fecha nem por CDP.
  O PDF é gerado a partir do formato **HTML**.
- **O formato só marca pelo `span.checkmark`.** Clicar no texto ou no card não
  dá erro e não marca nada.
- **O painel é um drawer com overlay.** Deixá-lo aberto trava a conta seguinte,
  porque o overlay intercepta todo clique.

Nunca ancore seletor em classe `ng-tns-*`: são geradas por build e mudam.

Testes: `python -m pytest tests -q` (as fixtures são fictícias, nunca extrato
real — o repositório é público).
