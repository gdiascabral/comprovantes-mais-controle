# `cnab240/ferramentas/` — a conversa com o banco

Quatro scripts que se roda **à mão**, na máquina que tem o cadastro, para
fazer ao Sicoob uma pergunta de cada vez: *este layout você aceita?*

Nenhum deles transmite nada. Cada um gera um `.REM` inofensivo — centavos,
títulos que não existem — para o botão **Validar** do SicoobNet
(Empresarial → Arquivos CNAB 240 → Envio de Arquivos). Quem clica em *Enviar*
é uma pessoa, depois de ler a saída.

## Não fazem parte do exe

O `build.yml` copia `cnab240/*.py` e `cnab240/spec/*.json` para o `codigo.zip`;
esta subpasta fica de fora, e de propósito. O app nunca a importa, e ferramenta
de operador não tem por que viajar para a máquina de quem usa — é o mesmo
tratamento do `nuvem/migrar.py`, escrito em `tests/test_empacotamento.py`
(`_PASTAS_SO_DO_REPO`), com um teste que confere que ela continua de fora.

## Por que moram aqui dentro

Até 02/09/2026 estes scripts viviam fora do repositório e importavam uma
**segunda cópia** do pacote `cnab240`, que parou no tempo em 14/08/2026. Essa
cópia não tinha `dv_cpf`, `dv_cnpj` nem `documento_valido` — acrescentados em
20/08, depois de o banco devolver uma remessa por CPF inválido vindo do
cadastro. Uma ferramenta cujo trabalho é dizer *"pode enviar"* apontando para
código velho aprova o arquivo que o banco recusa: é o pior resultado possível.

Agora só existe uma fonte, e o `_ambiente.py` **confere isso em tempo de
execução**: se o `cnab240` importado não for o deste repositório, o script para
antes de responder qualquer coisa. Os testes que guardam a regra estão em
`tests/test_cnab240.py`.

## Os quatro

Rode da **raiz do repositório**:

| script | o que pergunta ao banco | consome NSA? |
|---|---|---|
| `gerar_teste` | O layout básico passa? Header + boleto (J + J-52) + Pix (A + B), R$ 0,01 cada. Não passa pelo `remessa_dia`: mede só a biblioteca. | não (NSA 1 fixo) |
| `gerar_teste_2` | O **caminho real do app** produz arquivo válido? `resolver_pagador` → `preparar` → `montar_arquivo`, com um Pix de R$ 1,00 que pode de fato ser enviado. | **SIM, o de produção** |
| `gerar_teste_3_arrecadacao` | O lote de **arrecadação** passa? Serviço 22, forma 11, segmento O — o produto que faltava quando duas guias viajaram como título de cobrança em 17/08/2026. Junto de um boleto, para provar os dois produtos no mesmo arquivo. | não (NSA 990001 fixo) |
| `conferir_segmento_o` | Cada campo do segmento O bate com o **guia**? Mede posição e largura contra a tabela transcrita do PDF (seções 9.1 e 9.2) — de propósito **não** contra o `cnab240/spec`, que é a mesma fonte que gerou o arquivo. | não (NSA 990002 fixo) |

```
python -m cnab240.ferramentas.gerar_teste [--app PASTA] [--empresa NOME]
python -m cnab240.ferramentas.gerar_teste_2 --chave-pix CPF_OU_CNPJ [--app PASTA]
python -m cnab240.ferramentas.gerar_teste_3_arrecadacao [--app PASTA]
python -m cnab240.ferramentas.conferir_segmento_o [--app PASTA]
```

`--app` é a pasta da instalação, onde moram `contas_sicoob.json`,
`contas_mc.json` e `remessas.json`. Sem ela vale a regra do app inteiro
(`util.pasta_base()`): a raiz do projeto quando se roda do código-fonte. Esses
arquivos ficam **fora do repositório** — nome de empresa e número de conta —,
então sem eles a ferramenta recusa e diz onde os procurou.

## O que este repositório é

Público. Aqui não entra nome real de empresa, de pessoa ou de fornecedor, CPF,
CNPJ, agência, conta nem convênio — nem em código, nem em comentário. Por isso:

- a empresa **nunca é escrita no código**: sai do cadastro, e sem `--empresa`
  vale a primeira que tiver convênio;
- as linhas digitáveis são **fabricadas** pelo `_ambiente.py`
  (`boleto_sintetico`, `ficha_sintetica`): dígitos verificadores fechando —
  senão o `preparar` as barra — e conteúdo que não aponta para conta nenhuma;
- o `gerar_teste_2` **exige** `--chave-pix` na linha de comando e não tem
  padrão. É para onde R$ 1,00 vai de verdade; quem roda decide, e a decisão não
  fica escrita num arquivo público. A chave é conferida por DV antes de
  qualquer outra coisa — foi um documento de preenchimento, com onze dígitos e
  DV que não fecha, que fez o Sicoob devolver a remessa 000002 em 20/08/2026.
