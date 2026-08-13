# CNAB 240 Sicoob — Pagamentos: parametrização consolidada

Estudo consolidado dos manuais, guardados em `banco/sicoob/`. Fonte normativa:
**"Guia de Importação de Arquivos CNAB 240 — Pagamentos e Transferências",
versão 3.3, de 19/05/2025**, baixado do site do Sicoob em 13/08/2026.

### Sobre as versões

Este estudo foi escrito em 11/08/2026 contra a **v3.1** (26/03/2025). Em
13/08/2026 a v3.3 foi obtida direto do Sicoob e **conferida contra este
documento: nada de técnico mudou.** As duas revisões seguintes são editoriais,
segundo o próprio histórico do guia:

- **v3.2** (23/04/2025) — "alteração dos termos do guia de 'manual' para 'guia'";
- **v3.3** (19/05/2025) — desmembramento em dois guias: *Pagamentos e
  Transferências* e *Folha de pagamento*.

Consequência prática: a parametrização em `spec/` continua válida. Só o produto
`FOLHA_PAGAMENTO` passou a ser regido por **outro documento**, que não temos —
se algum dia a folha entrar em uso, é ele que manda, não este.

A **v2.11** (30/12/2024) está guardada só como histórico; ela não tem, no
domínio G059 da folha, os códigos `BF` e `68` que a v3.1 acrescentou.

Os dois PDFs de "Telas do IB" são manuais de navegação do Internet Banking, sem
conteúdo de layout — resumidos no fim deste documento.

---

## 1. Estrutura do arquivo

```
Header de Arquivo             (tipo 0)   ← 1 por arquivo, primeira linha
  Header de Lote              (tipo 1)
    [Registros Iniciais]      (tipo 2)   ← opcional, não usado nos pagamentos
    Detalhes / segmentos      (tipo 3)   ← 1..N
    [Registros Finais]        (tipo 4)   ← opcional, não usado nos pagamentos
  Trailer de Lote             (tipo 5)
  ... (outros lotes)
Trailer de Arquivo            (tipo 9)   ← 1 por arquivo, última linha
```

- **Todo registro tem exatamente 240 caracteres.**
- **Um lote só pode conter um único tipo de transação.** Produtos diferentes → lotes diferentes.
- Numeração de lote: `0000` no header de arquivo, `0001`, `0002`… nos lotes, `9999` no trailer de arquivo. Não repetir número dentro do arquivo.
- NSR (nº sequencial do registro no lote) **reinicia em 1 a cada lote** e conta os registros tipo 3.
- Nº Sequencial do Arquivo (NSA) deve ser **crescente** entre arquivos.

### Formatação de campos

| Tipo | Alinhamento | Preenchimento | Observações |
|---|---|---|---|
| **Num** | direita | zeros à esquerda | sem vírgula/ponto; a parte fracionária ocupa as últimas N posições (coluna `dec`) |
| **Alfa** | esquerda | brancos à direita | preferencialmente MAIÚSCULAS, **sem acentuação e sem caracteres especiais** (`Ç`, `Á`, `?`, etc.) |

---

## 2. Produtos suportados na importação

| Produto | Header de lote (versão) | G029 Forma Lançamento | Segmentos (envio) | Câmara P001 |
|---|---|---|---|---|
| Transferência entre contas Sicoob | `045` | `01` CC, `05` poupança | A + B | — |
| TED (outros bancos) | `045` | `41` outra titul., `43` mesma titul. | A + B | `018` |
| Pix Transferência | `045` | `45` | A + B | `009` |
| Pagamento de Títulos (boleto) | `040` | `30` próprio banco, `31` outros bancos | J + J‑52 | — |
| Pix QR Code | `040` | `47` | J + J‑52‑Pix | — |
| Convênios/Tributos **com** cód. barras | `012` | `11` | O (+ W opcional) | — |
| Tributos **sem** cód. barras | `012` | `16` DARF, `17` GPS, `18` DARF Simples | N (+ W opcional) | — |
| Folha de Pagamento | `045` | `01` (G025 = `30`) | A + B (layout clássico) | — |

> **DOC foi removido do manual** na versão 2.5 (14/06/2024). Não implementar.

Layout do arquivo (header de arquivo, campo 20.0): **`087`**.

---

## 3. Armadilhas do layout — o que mais causa rejeição

1. **Existem dois Segmentos B diferentes.**
   - Transferência/TED/Pix: posições 15‑17 = *Forma de Iniciação* (G100), e os dados vão em **Informação 10 / 11 / 12** (33‑67, 68‑127, 128‑226).
   - Folha de Pagamento: posições 15‑17 = brancos, e o endereço vem **explodido** (logradouro 33‑62, número 63‑67, complemento 68‑82, bairro 83‑97, cidade 98‑117, CEP 118‑122…).
   - Os dois layouts coincidem em conteúdo quando não é Pix, mas **as posições do endereço são diferentes**. Não reaproveitar o mesmo código sem distinguir o produto.

2. **Existem três Trailers de Lote diferentes.**
   - Transferência/TED/Pix/Folha: qtd registros (18‑23), somatória (24‑41), qtd moedas (42‑59), aviso débito (60‑65), brancos (66‑230).
   - Títulos: idêntico ao acima, muda só a semântica da somatória (L001).
   - **Tributos: diferente a partir da posição 42** — qtd registros (18‑23), somatória (24‑41), *complemento de registro* (42‑230). Não tem campo de qtd de moedas nem aviso de débito.

3. **J‑52 vs J‑52‑Pix são mutuamente exclusivos.** Boleto → J‑52. Pix QR Code → J‑52‑Pix. Nunca os dois, nunca nenhum.

4. **Campo `Quantidade da Moeda` (19.3A, 105‑119)** tem **5 casas decimais** (10 inteiros + 5 decimais), enquanto `Valor do Pagamento` (20.3A, 120‑134) tem **2**. Confundir as escalas é erro silencioso.

5. **Somatória dos valores no trailer de lote (24‑41)** tem 18 posições com 2 decimais (16 + 2), não 15.

6. **Pix Transferência exige três coisas juntas:**
   - `G100` (Forma de Iniciação) no Segmento B, posições 15‑17;
   - `G031` (Informação 2) no Segmento A, posições 178‑217 → **38 brancos + 2 dígitos** do tipo de conta destino (`01` corrente, `02` pagamento, `03` poupança);
   - a chave Pix na **Informação 12** (128‑226). O manual descreve o campo para `G100` ∈ {01, 02, 04} e para `G100 = 05` (tipo de conta), e **omite o `03` (CPF/CNPJ)** — omissão que se lia naturalmente como "a chave já está em 07.3B/08.3B, não repita". **Não é isso.** O SicoobNet recusou o arquivo com o campo em branco: *"Erro estruturante no registro. A linha 8 posição 128 até 226, campo Informação 12, possui valor inválido"* (validação de 13/08/2026). Para `G100 = 03`, repetir o CPF/CNPJ ali.
   - Se `G100 = 05` (dados bancários), a Informação 12 leva o tipo de conta e os dados vão no Segmento A.

7. **Código de barras**: 44 posições. No Segmento J é **Num**; no Segmento O é **Alfa**. Usar o código de barras, não a linha digitável (47/48 dígitos).

8. **TED exige** `G005` (Tipo de Inscrição) preenchido e `P011` (Código de Finalidade da TED). TED para poupança exige `P013 = 'PP'`.

9. **Folha de Pagamento**: a *Mensagem* do header do lote (18.1, posições 103‑142) é **obrigatória** e é o **nome da folha**.

10. **Segmento W é obrigatório** (apesar de marcado "Opcional") quando o FGTS pago pertence aos convênios `0181` (Recolhimento Recursal 418 / Filantrópico 604) ou `0182` (Parcelamento sem Multa 327, 337, 345).

### Divergências internas do manual (decisões tomadas na spec)

| Onde | Divergência | Decisão |
|---|---|---|
| `26.3A` Código Finalidade TED | Tipado `Num` no item 7.2 e `Alfa` no item 10.2 | adotado `num` (os códigos P011 são numéricos) |
| `11.3W` Informação Complementar Tributo | Manual diz "48 dígitos", mas posições 179‑228 dão **50** | posições são autoritativas → 50 |
| Segmento A | Dois campos numerados `29.3A` | o último foi renomeado para `30.3A` |
| Header lote tributos, campo 08.1 | Coluna "Descrição" veio como "Obrigatório" (erro de diagramação) | é `G004` — Uso Exclusivo FEBRABAN |

---

## 4. Totalizações

| Campo | Cálculo |
|---|---|
| Trailer de lote — Qtd de Registros (G057) | header de lote + todos os detalhes + trailer de lote |
| Trailer de lote — Somatória dos Valores | soma dos valores de pagamento dos detalhes do lote |
| Trailer de lote — Somatória Qtd de Moedas (G058) | soma das quantidades de moeda dos segmentos A / J |
| Trailer de arquivo — Qtd de Lotes (G049) | contagem dos registros tipo 1 |
| Trailer de arquivo — Qtd de Registros (G056) | **todos** os registros: tipos 0, 1, 3, 5 e 9 |
| Trailer de arquivo — Qtd de Contas p/ Conciliação (G037) | registros tipo 1 com Tipo de Operação = `E`; em arquivo só de pagamentos → zeros |

---

## 5. Validação do Sicoob (item 12 do manual)

**Rejeitam o arquivo inteiro** — erro de formatação/domínio em: header de arquivo, trailer de arquivo, header de lote, trailer de lote, campos de *controle* dos segmentos (banco/lote/registro), campos de *serviço* dos segmentos (NSR/segmento/movimento).

**Rejeitam só o registro**: campo obrigatório vazio; campo `Num` com letra ou caractere especial; campo com domínio diferente do especificado.

---

## 6. Arquivo de retorno

- É **o mesmo arquivo enviado**, acrescido dos códigos de ocorrência nas posições **231‑240** de cada registro (até 5 ocorrências de 2 dígitos).
- Nos casos processados com sucesso, vem também um **Segmento Z** com a autenticação (Transferências/TED com A+B, Títulos com O/N/W, Folha com A+B).
- Código Remessa/Retorno (header de arquivo, posição 143) = `2`.

**Códigos de ocorrência mais relevantes:**

| Código | Significado |
|---|---|
| `00` | Crédito/débito efetivado — pagamento confirmado |
| `BD` | Inclusão efetuada com sucesso (agendada) |
| `PD` | Transação pendente de assinatura |
| `BF` | Rejeitada por assinatura de pendência / agendamento cancelado pelo usuário |
| `AJ` | Rejeição CNAB — estrutura do registro/lote rejeitada |
| `01` | Conta da empresa com saldo insuficiente |
| `68` | Agendamento em andamento (folha) |
| `HF` | Saldo insuficiente, em tentativa de reprocessamento (folha) |
| `PA` `PC` `PE` `PG` `PH` `PI` `PJ` `PK` | Rejeições específicas de Pix (ver `spec/dominios.json`) |

---

## 7. Fluxo operacional no Sicoobnet Empresarial

**Pré-requisito — adesão ao convênio:** Internet Banking → `Empresarial` → `Adesão e cancelamento` → `+Adesão` → ler e aceitar o termo → informar código de efetivação em dois passos (gerado no App Sicoob) → `CONFIRMAR`. **A tela exibe o Número do Convênio** — é ele que vai no campo `Código do Convênio no Banco` (posições 33‑52 do header de arquivo e do header de lote).

**Validação (o caminho real, conferido em 13/08/2026):**
`Empresarial` → `Gestão em Lote` → `IntegraLote` → `Gestão de arquivos CNAB` →
**`Validação de estrutura de arquivos`** → escolher o arquivo → `Validar`.
O menu dos manuais de tela (`Arquivos CNAB 240` → `Envio de Arquivos`) é de uma
versão anterior do Internet Banking e não existe mais com esse nome.

A tela devolve `Válido` / `Inválido`, o **tipo reconhecido** (`CNAB 240 -
Pagamentos e transferências`) e o status **`Pronto para envio`**. Atenção: um
arquivo validado **fica na fila do IntegraLote** — validar não é inócuo, o
arquivo passa a estar a um clique do envio.

**Envio:** a partir do IntegraLote → `Enviar` → confirmar → senha de efetivação
de 6 dígitos (operador) ou código de liberação em dois passos (preposto) →
selecionar as transações → `Processar`.

**Retorno:** `Gerenciamento de Arquivos` → filtrar por `Situação` e `Período` → `Consultar` → em `Ações`: **`Obter Retorno`** (gera o arquivo CNAB 240 de retorno) ou **`Consultar Erros`** (quando a situação é *Processado com erro*). Permite download individual ou compactado.

**Comprovantes:** `Emissão de Comprovantes`.

> O botão **Validar** da tela é o ciclo de feedback mais rápido durante o desenvolvimento — vale usá-lo antes de qualquer envio real.

---

## 8. Arquivos desta pasta

| Arquivo | Conteúdo |
|---|---|
| `spec/layouts.json` | Todos os registros campo a campo: posições, tamanho, decimais, tipo, default, obrigatoriedade e referência ao manual |
| `spec/dominios.json` | Todos os domínios (G005, G025, G028, G029, G040, G059, G060, G061, G065, G067, G100‑G102, N003, N005, N024, N027, P001, P006, P011, P013, P014) |
| `spec/produtos.json` | Combinações válidas por produto: header, segmentos, domínios, regras de totalização e de validação |
| `cnab240/` | Pacote Python: gerador de remessa, validador e leitor de retorno — ver [README.md](README.md) |
| `tests/` | 41 testes cobrindo os 8 produtos, as totalizações e a leitura de retorno |
| `exemplos/` | `gerar_remessa.py` (arquivo com os 8 produtos) e `ler_retorno.py` |
| `REFERENCIA.md` | Este documento |

Os PDFs não moram aqui: ficam em `banco/sicoob/`, junto com o comprovante de
adesão de cada empresa. Esta pasta é código, e é candidata a entrar no
repositório público — **nenhum dado de empresa pode ser gravado nela.**

## 9. O que esta biblioteca ainda não faz

Ela gera, valida e lê retorno — mas **não tem memória**. Em particular o
**NSA é parâmetro de entrada** (`ArquivoRemessa(empresa, nsa=1)`): quem chama
é que precisa saber qual foi o último número usado, guardá-lo por
empresa/convênio e mantê-lo crescente entre execuções, como exige o G018.

Isso é decisão de quem integra, não da biblioteca — e é o que falta para o app
gerar remessa de verdade, junto com o de‑para "seu número → lançamento no ERP"
que amarra o arquivo de retorno de volta.
