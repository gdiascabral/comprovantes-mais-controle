# CNAB 240 — Pagamentos Sicoob

Gerador, validador e leitor de retorno para os arquivos de pagamento CNAB 240 do
Sicoobnet Empresarial, conforme o **Guia de Importação de Arquivos CNAB 240 —
Pagamentos e Transferências, v3.3 (19/05/2025)**. Escrito contra a v3.1 e
conferido contra a v3.3, que não trouxe mudança técnica — ver `REFERENCIA.md`.
Os PDFs ficam em `banco/sicoob/`.

Sem dependências de runtime — só a biblioteca padrão do Python (3.11+).
`pytest` só é necessário para rodar os testes.

## Estrutura

```
spec/                     parametrização em JSON — a fonte da verdade
  layouts.json            todos os registros, campo a campo, com o id do manual
  dominios.json           domínios da seção 13 (G005, G029, G059, P011, …)
  produtos.json           combinações válidas por produto + regras de totalização
cnab240/                  o pacote
  spec.py                 carrega e valida a parametrização
  campos.py               formatação Num/Alfa, datas, valores, sanitização
  registros.py            monta/desmonta registros de 240 posições
  dominios.py             enums e decodificação de ocorrências
  modelos.py              dataclasses de entrada (Empresa, Favorecido, pagamentos)
  remessa.py              ArquivoRemessa — geração
  validador.py            validação estrutural, de domínio e de totais
  retorno.py              leitura do arquivo de retorno
  historico.py            contador do NSA, histórico e de-para (estado em disco)
  __main__.py             CLI
tests/                    82 testes
exemplos/                 scripts executáveis
REFERENCIA.md             o estudo consolidado dos manuais
```

A parametrização vive em JSON, não em código: cada campo carrega o **id do
manual** (`20.3A`) e o **código da seção 13** (`P010`), então auditar contra o
PDF é uma busca textual direta.

## Uso

### Gerar uma remessa

```python
from datetime import date
from decimal import Decimal
from cnab240 import *

empresa = Empresa(
    nome="ACME COMERCIO LTDA", documento="12.345.678/0001-95",
    convenio="123456",                      # número exibido após a adesão
    agencia="4321", dv_agencia="0",
    conta="000000123456", dv_conta="7", dv_ag_conta="8",
)

arquivo = ArquivoRemessa(empresa, nsa=1)

arquivo.novo_lote("TED", forma_lancamento=FormaLancamento.TED_OUTRA_TITULARIDADE).adicionar(
    TransferenciaConta(
        valor=Decimal("8750.40"),
        data_pagamento=date(2026, 8, 12),
        seu_numero="NF-2026-0002",
        finalidade_ted="5",                 # pagamento de fornecedores
        favorecido=Favorecido(
            nome="FORNECEDOR SA", documento="98.765.432/0001-98",
            banco="341", agencia="0910", conta="000000045678", dv_conta="1",
        ),
    )
)

arquivo.salvar("REM0001.REM")
```

O gerador cuida sozinho de: numeração de lotes, NSR por lote, câmara
centralizadora, versão do layout de lote, totalizações dos trailers e
preenchimento de brancos/zeros.

### O NSA, e a memória entre arquivos

Três das quatro numerações do CNAB se resolvem dentro do próprio arquivo. A
quarta não: o **NSA** (header, posições 158‑163) tem de ser **crescente** entre
arquivos, e o manual é explícito em que quem controla é *quem gera* — o banco
não guarda isso por você. `historico.py` é essa memória.

```python
from cnab240 import ArquivoRemessa, Historico

historico = Historico("remessas.json")

arquivo = ArquivoRemessa(empresa, nsa=historico.proximo_nsa("123456"))
...
caminho = arquivo.salvar("REM0007.REM")
historico.registrar(arquivo, caminho_arquivo=caminho,
                    referencias={"260813-0001": "<id do lançamento no ERP>"})
```

`proximo_nsa` só consulta; quem consome o número é `registrar`, e ele recusa
qualquer NSA que não seja maior que o último gravado naquele convênio. Se o
arquivo foi gerado e não enviado, `descartar` devolve o número — desde que
nenhuma remessa tenha saído depois.

O mesmo arquivo é o de‑para que o retorno usa para voltar ao lançamento de
origem, e é o que responde **"já mandei este boleto?"**:

```python
historico.envio_de(codigo_barras)         # chave natural: só o código de barras
historico.envio_da_referencia(id_erp)     # "este lançamento já foi mandado?"
historico.remessa_dos_seus_numeros(seus)  # de que remessa este retorno fala?
```

A última recebe a lista inteira dos "seus números" que vieram no arquivo de
retorno e só responde quando **todos** os que ela achou caem na mesma remessa:
um número que aponta para duas não é empate a desempatar, é a prova de que não
dá para saber de qual delas o arquivo fala.

Chave Pix e dados de conta **não** viram identificador de propósito: o mesmo
fornecedor recebe várias vezes no mesmo dia, e isso viraria alarme falso
diário.

O contador é **por convênio** — a escolha grosseira, porque o guia não diz em
que nível o Sicoob confere. Contar mais grosso que o banco só pula números;
contar mais fino repetiria, e repetir é o que não pode acontecer.

```
python -m cnab240 historico remessas.json -d
python -m cnab240 nsa remessas.json -c 123456
python -m cnab240 nsa remessas.json -c 123456 --ajustar 30 --motivo "ja enviava pelo SicoobNet"
```

O ajuste é o "campo editável": existe para a conta que já enviava por fora, para
o arquivo descartado e para a reinstalação do app. Exige motivo e fica gravado
em `ajustes` — e nunca desce para aquém de um NSA que já saiu.

### Validar

```python
from cnab240 import validar_arquivo, relatorio
print(relatorio(validar_arquivo("REM0001.REM")))
```

```
$ python -m cnab240 validar REM0001.REM
```

Os problemas vêm classificados como no manual: `ARQUIVO` (rejeita tudo) ou
`REGISTRO` (rejeita só aquela linha).

### Ler o retorno

```python
from cnab240 import ler_arquivo_retorno

retorno = ler_arquivo_retorno("RET0001.RET")
for p in retorno.pagamentos():
    if p.rejeitado:
        print(p.seu_numero, p.valor, p.ocorrencias)

print(retorno.resumo())
```

```
$ python -m cnab240 retorno RET0001.RET --detalhes
```

Cada pagamento é classificado em quatro estados: **confirmado** (`00`, `BD`,
`68`), **pendente** (`PD` — aguardando assinatura), **rejeitado** (demais
códigos) e **sem ocorrência**.

### Outros comandos

```
python -m cnab240 layouts               lista os layouts
python -m cnab240 layout segmento_a     imprime um layout campo a campo
python -m cnab240 ocorrencia PJ         descreve um código de retorno
```

## Produtos suportados

| `novo_lote(...)` | Pagamento | Segmentos |
|---|---|---|
| `TRANSFERENCIA_SICOOB` | `TransferenciaConta` | A + B |
| `TED` | `TransferenciaConta` | A + B |
| `PIX_TRANSFERENCIA` | `PixTransferencia` | A + B (sub-layout Pix) |
| `TITULOS_COBRANCA` | `PagamentoTitulo` | J + J‑52 |
| `PIX_QRCODE` | `PixQRCode` | J + J‑52‑Pix |
| `CONVENIOS_COM_CODIGO_BARRAS` | `PagamentoConvenio` | O (+ W) |
| `TRIBUTOS_SEM_CODIGO_BARRAS` | `TributoDARF`, `TributoGPS`, `TributoDARFSimples` | N (+ W) |
| `FOLHA_PAGAMENTO` | `PagamentoFolha` | A + B (layout clássico) |

## Rodar

```
python -m pytest -q                     # 82 testes
python exemplos/gerar_remessa.py        # arquivo com os 8 produtos
python exemplos/ler_retorno.py          # simula e lê um retorno
```

## Decisões que precisam de confirmação com a cooperativa

O manual não é explícito nestes pontos; a escolha adotada está no código e
é sobrescrevível:

0. **Campo 12.0 (DV Ag/Conta) do header** — parecia um buraco, e a descrição do
   campo (G012) responde: é a **2ª posição do DV da conta**, "para os Bancos que
   se utilizam de duas posições para o Dígito Verificador". Conta com DV de uma
   posição só (como as do Sicoob: `12.345-6`) não tem segunda, e o campo fica
   **branco** — é por isso que ele é `Alfa` e não `Num`. Confirmar no `Validar`
   assim mesmo; se reclamar, tentar `0` e depois o próprio DV da conta.

1. **Pix QR Code, campo 08.3J (Código de Barras)** — o manual mantém o campo
   obrigatório mesmo sem boleto. Adotado **zeros**. Sobrescreva com
   `PixQRCode(codigo_barras=...)` se a cooperativa exigir outro preenchimento.
2. **Campo 26.3A (Código de Finalidade da TED)** — o manual tipa `Num` no item
   7.2 e `Alfa` no item 10.2. Adotado **`num`** (os códigos P011 são numéricos).
3. **Campo 11.3W** — o manual diz "48 dígitos", mas as posições 179‑228 dão
   **50**. As posições foram adotadas como autoritativas.
4. **Caixa de chaves Pix e URLs** — o manual pede maiúsculas, mas uppercase
   quebraria uma URL de QR Code dinâmico. Chave de endereçamento, URL e TXID
   preservam a caixa original (`campos.CAMPOS_PRESERVAM_CASO`); todo o resto vai
   em maiúsculas sem acento.

> Antes do primeiro envio real, use o botão **Validar** do Sicoobnet Empresarial
> (`Empresarial` → `Arquivos CNAB 240` → `Envio de Arquivos`): é o ciclo de
> feedback mais rápido e confirma esses quatro pontos de uma vez.
