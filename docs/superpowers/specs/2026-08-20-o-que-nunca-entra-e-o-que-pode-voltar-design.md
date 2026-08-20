# Remessa: o que nunca entra, e o que pode voltar — design

Data: 20/08/2026
Aba: Pagamentos do Dia

Duas queixas do primeiro dia de uso da marcação lançamento a lançamento. As
duas são sobre a mesma pergunta — *quem decide que uma linha não vai* —, e por
isso vêm juntas:

- **Parte 1 — o que nunca entra.** O marcador de recorrência de R$ 1,00 das
  concessionárias aparece na janela todo dia, e todo dia é desmarcado à mão.
- **Parte 2 — o que pode voltar.** "Já saiu na remessa nº X" barra a linha, e
  não há como reenviar quando o envio anterior falhou.

---

# Parte 1 — R$ 1,00 de concessionária nunca entra

## O problema

As concessionárias de energia e água lançam no ERP uma linha de **exatamente
R$ 1,00** por unidade consumidora. Não é pagamento: é marcador de recorrência,
para o título nascer no mês. Em 20/08/2026 eram três das vinte e uma linhas do
dia, e as três foram desmarcadas à mão na janela da etapa 2 — como em todos os
dias anteriores.

`regras_pagamento.omitir` já conhece o valor simbólico (`MOTIVO_SIMBOLICO`),
mas ele age **depois** da janela: a etapa 2 pergunta antes de o app ler os
anexos, então lista o que a etapa seguinte vai descartar sozinha. A janela
existe para recolher decisão; linha cuja decisão já está tomada só ocupa espaço
e gasta atenção — que é o que ela deveria estar protegendo.

## O que muda

O R$ 1,00 dessas concessionárias deixa de aparecer na janela e deixa de ter a
exceção do documento. Some da vista, não do papel: continua na aba NÃO ENTRARAM
com o motivo escrito.

### A exceção que o dono decidiu remover

`omitir` hoje deixa passar o valor simbólico quando o código de barras do anexo
diz outro valor. A regra nasceu de um caso real de 10/08/2026: uma conta de luz
de verdade, lançada como R$ 1,00, com o boleto anexado dizendo R$ 56,24 —
descartar teria apagado a conta em vez de denunciar o lançamento errado.

Em 20/08/2026 o dono decidiu que, **para os fornecedores marcados**, o R$ 1,00
sai mesmo assim. Fica escrito aqui o que isso custa: se o caso de 10/08 voltar,
a conta real não aparece na janela nem na remessa, e o único lugar onde ela
existe é a aba NÃO ENTRARAM. Quem for procurar precisa ir lá.

A exceção continua valendo para todo fornecedor **sem** a marca — ela não foi
apagada do código, só deixou de valer para três nomes.

## Arquitetura

### A marca mora no cadastro, não no código

Não há lista de concessionária dentro do app. A marca é uma regra por
fornecedor, no `regras_fornecedor.json` que já existe ao lado do exe e já é
alimentado pelo cadastro da nuvem:

```json
"EQUATORIAL": { "so_marcador": true }
```

Casa por pedaço, sem acento e sem caixa, como as outras regras do arquivo —
"EQUATORIAL" acha "EQUATORIAL GOIAS DISTRIBUIDORA". Concessionária nova é uma
linha nova no cadastro, sem versão nova do app.

O alcance por NOME, e não por valor, foi decisão do dono: `so_marcador` diz
"R$ 1,00 **deste** fornecedor é marcador", não "R$ 1,00 nunca é pagamento". Um
dia em que exista um pagamento legítimo de R$ 1,00, ele continua saindo.

| Camada | Mudança |
|---|---|
| `supabase/migrations/` | `so_marcador` entra no check de `tipo` de `regra_fornecedor` |
| `nuvem/cadastro.py` | `_regras_fornecedor` materializa a marca no JSON |
| `pagamentos_dia/regras_pagamento.py` | `so_marcador(favorecido, regras)`; `omitir` pula a exceção do documento quando ela vale |
| `pagamentos_dia/pagamentos_frame.py` | `alvos_para_confirmar` não lista a linha marcada |

### Por que em dois lugares

A janela (etapa 2) e o `omitir` (etapa 3) rodam em momentos diferentes e com
informação diferente — a janela não leu os anexos ainda. Mudar só a janela
deixaria a linha entrar na planilha no dia em que o boleto contradissesse o
valor; mudar só o `omitir` não tiraria a linha da janela, que é a queixa. As
duas leem a MESMA marca, então não podem discordar sobre o mesmo fornecedor.

---

# Parte 2 — reenviar o que já saiu

## O problema

`_ja_enviado` pergunta ao histórico se aquele boleto (pelo código de barras) ou
aquele lançamento (pela referência) já saiu numa remessa viva, e o resultado
vira **impedimento**: a linha perde a caixa e aparece como texto, "não vai: já
saiu na remessa nº 000001 de 17/08/2026".

A trava está certa contra o acidente que a criou — refazer o dia com o título
ainda aberto mandava o mesmo boleto de novo, sem alarme nenhum. Mas ela também
barra o caso legítimo: o envio anterior falhou (arquivo recusado pelo banco,
pagamento que não caiu, remessa que se perdeu) e aquele pagamento **precisa**
ir de novo. Hoje a única saída é `descartar()` a remessa inteira — grosso
demais quando o que falhou foi um pagamento.

## O que muda

"Já saiu" deixa de ser impedimento e vira **aviso**. A linha volta a ter caixa
e nasce **desmarcada**, com o histórico escrito embaixo:

```
[ ] Boleto   R$ 5.055,00   FORNECEDOR
        ↳ já saiu na remessa nº 000001 de 17/08/2026 — marque para enviar de novo
```

Nascer desmarcada é o mesmo critério do reembolso, e pela mesma razão: é a
linha em que marcar significa dinheiro saindo duas vezes. O clique explícito é
o preço.

## Arquitetura

`Candidato` ganha `ja_enviado: str` — o texto do envio anterior, vazio quando
não houve. `_ja_enviado` continua igual; só deixa de alimentar `impedimento`.

Três coisas caem de graça do código que já existe:

1. `pode` volta a ser verdadeiro, então a linha ganha caixa sem tocar na tela;
2. `marcado = apto and not reembolso and not ja_enviado` — nasce desmarcada;
3. o `seu_numero` só é atribuído a quem não tem impedimento, então a linha
   reenviada recebe um **novo** — é por ele que o retorno do banco casa com o
   reenvio, e não com o envio velho.

`descartar()` continua existindo para o caso oposto: a remessa inteira que não
foi. Uma trata o pagamento, a outra trata o arquivo.

---

# Testes

| Teste | O que prova |
|---|---|
| `so_marcador` + R$ 1,00 → fora da janela | a queixa do dia |
| `so_marcador` + R$ 1,00 + boleto divergente → omitido | a exceção deixou de valer para o marcado |
| sem a marca + R$ 1,00 + boleto divergente → mantido | a regra de 10/08 continua de pé para os outros |
| sem a marca + R$ 1,00 → omitido por valor simbólico | o caminho antigo não mudou |
| candidato com envio anterior | `pode` verdadeiro, `marcado` falso, aviso preenchido, `seu_numero` novo |
| cadastro da nuvem | o tipo novo materializa a marca no `regras_fornecedor.json` |
