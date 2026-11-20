# Plano: leitura por IA dos recibos escritos à mão — 1ª metade (20/11/2026)

Spec: `docs/superpowers/specs/2026-11-19-html-tres-niveis-parcela-e-letra-de-mao-design.md`, parte 3.

**Objetivo desta metade:** provar, com números, se a IA lê os recibos à mão bem o
bastante para servir de prova de valor — ANTES de mexer no app. Nada aqui chega à
máquina de ninguém: o módulo é puro e nenhuma tela o chama ainda.

**A 2ª metade** (ligar no app: chave guardada com DPAPI, cache ao lado do exe,
limite de 60 por geração, o nível "Olhe — lido por IA" no HTML, decidir se o pacote
`anthropic` entra no exe) ganha plano próprio depois da medição, porque depende dela:
qual modelo, quanto custa por dia, se acerta.

## Já feito e conferido (neste ramo, `codigo/leitura-ia-recibos`)

- `pagamentos_dia/leitura_ia.py` — o módulo puro, sem rede e sem pacote de
  terceiros (quem chama entrega o cliente da API):
  - `pedir_leitura(cliente, dados, media_type)` manda a imagem ou o PDF com uma
    instrução e um esquema JSON (saída estruturada), pede `effort: low` e a
    reserva por recusa (`fallbacks="default"`); recusa, resposta cortada ou JSON
    fora do esquema levantam `LeituraFalhou` — nunca devolve leitura pela metade.
  - `conferir(leitura, valor)` em `Decimal`, quatro estados: **bate** (total =
    lançamento E uma segunda prova no mesmo papel: valor por extenso, soma dos
    itens ou comprovante do cartão), **sem segunda prova**, **diverge** (o total
    ou alguma prova diz outro valor) e **ilegível**.
  - `dinheiro()` lê "1.234,56", "#4.700#", "4.700"; `extenso_para_valor()` lê
    "quatro mil e setecentos reais" e centavos; palavra estranha devolve None.
  - `CacheLeituras`: chave id + tamanho + data de alteração (nunca a URL),
    gravação atômica, arquivo estragado vira `.estragado` e o cache recomeça.
- `tests/test_leitura_ia.py` — 38 testes, todos passando, com dublê no lugar da
  API. Inclui o caso real de 19/11 (um 4 lido como 9, desmentido pelo
  comprovante do cartão → **diverge**) e um teste que garante que o esquema só
  usa o que a API aceita.
- `ruff --select E9,F` limpo; `vermin --target=3.11` limpo.
- Fora do repositório (os anexos são reais):
  `conferencia-pagamentos/2026-11-19-recibos-a-mao/medir_ia.py`. Rodado com
  `--sem-api`: acha os **38 anexos sem texto** (26 PDF, 12 fotos) de 26 títulos,
  com o valor de cada lançamento.

## Tarefa 1 — o dono (≈5 min, uma vez)

1. Aprovar a instalação do pacote oficial na máquina desta conversa
   (`python -m pip install anthropic`, no Python 3.14 do usuário; NÃO no exe).
2. Criar a chave em console.anthropic.com → API Keys, e gravá-la ele mesmo como
   variável do usuário (a chave nunca passa pelo chat):

   ```powershell
   [Environment]::SetEnvironmentVariable("ANTHROPIC_API_KEY", "<cole aqui>", "User")
   ```

   e fechar/abrir o app do Claude para a variável valer.
3. Aprovar o gasto: estimativa **US$ 1 a 3** para os 38 arquivos (preço do
   claude-opus-5-5: US$ 4 por milhão de tokens de entrada, 20 de saída; uma
   página ≈ 1.500–3.000 tokens de entrada).

## Tarefa 2 — primeiro arquivo (1 chamada, centavos)

```powershell
python medir_ia.py --limite 1
```

Confere: a chamada volta, o JSON passa no esquema, o custo impresso faz sentido.
Se falhar, para aqui e conserta o módulo (com teste) antes de gastar mais.

## Tarefa 3 — os 38

```powershell
python medir_ia.py --limite 38
```

Grava `medicao_ia.csv` (estado, total lido, provas, dúvidas, segundos) e imprime
a contagem por estado e o custo. O cache garante que rodar de novo não paga de novo.

## Tarefa 4 — conferir à mão e relatar

Abrir as folhas (`folha_1..5.jpg`) e, para cada **bate**, confirmar no papel. A
régua para seguir à 2ª metade:

| Medida | Para seguir |
|---|---|
| **bate** errado (IA e prova concordando num valor que o papel não tem) | **zero** |
| **diverge** que é erro da IA (o papel bate com o lançamento) | dito um a um, com o porquê |
| Títulos com pelo menos um anexo **bate** | relatado (é o ganho real) |
| Custo por arquivo e tempo por arquivo | relatado (vira o limite e o custo do dia) |

Relatório curto ao dono, com os números e as decisões abaixo.

## Decisões que ficam para depois da medição (spec, decisões 2–5)

2. Pacote oficial `anthropic` no exe (exige exe novo, ~152 MB para todos) **ou**
   chamada por `requests`, que já está no exe (só o `codigo.zip`). Recomendação
   atual: decidir pelo custo de manutenção depois de ver a medição; o módulo já
   aceita os dois, porque recebe o cliente de fora.
3. Modelo: `claude-opus-5-5` (padrão). Se a medição mostrar acerto igual com um
   modelo menor, trocar só a constante `MODELO`.
4. Chave só na máquina que gera o HTML.
5. Quando uma linha lida por IA pode ir a "Pode pagar": a spec diz que nunca na
   fase 1 ("Olhe — lido por IA" mesmo com **bate**). A medição dirá se vale rever.

## O que este plano NÃO faz

- Não chama a API sem o sim do dono (Tarefa 1).
- Não liga nada no app, não muda tela nem HTML, não mexe no exe nem no
  `motor_minimo.txt`.
- Não manda à API nada além do arquivo do anexo (nada do lançamento, nome ou CNPJ).
