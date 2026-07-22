# Comprovantes → Mais Controle

Dois aplicativos em Python (com janelinha, sem precisar saber programar) para
organizar comprovantes bancários e anexá-los nos pagamentos do
[Mais Controle ERP](https://maiscontroleerp.com.br):

| App | O que faz |
|---|---|
| **1. Separar e Renomear** | Pega PDFs com várias páginas (extratos de comprovantes), separa cada página em um arquivo próprio e renomeia no padrão `VALOR - DESCRIÇÃO - DATA` lendo o conteúdo do comprovante. |
| **2. Anexar Comprovantes** | Busca os títulos **pagos** do período que você informar, nas contas bancárias que você marcar, descobre quais ainda não têm comprovante e anexa o PDF certo em cada um (com a tag "Comprovante"). |

Bancos suportados na leitura dos comprovantes: **Sicoob** (PIX, boleto, convênio)
e **Inter** (PIX, pagamento, boleto/guia). Outros bancos podem ser adicionados
editando `separar_renomear/separar_renomear.py`.

## Instalação (uma vez)

Requisitos: [Python 3.10+](https://www.python.org/downloads/) instalado
(marque "Add Python to PATH" na instalação) e Google Chrome.

Baixe/clon​e este repositório e dê duplo-clique em **`instalar.bat`**
(ou rode no terminal):

```
pip install -r requirements.txt
python -m playwright install chrome
```

## App 1 — Separar e Renomear

Duplo-clique em `separar_renomear/Separar e Renomear.bat`.

1. Escolha a pasta de **entrada** (PDFs originais, com 1 ou várias páginas).
2. Escolha a pasta de **saída** (sugerida automaticamente: `ENTRADA/RENOMEADOS`).
3. Clique em **Separar e Renomear**.

Cada página vira um arquivo com nome no padrão:

```
70,00 - RPB 24 QD 26A LT 12 OC 5979 - 20-07.pdf
1890,00 - CONDOMÍNIO RESERVA DOS IPÊS OC 5428 - 01-07.pdf
1000,00 - Morais Empreendimentos - 20-07.pdf        (transferência: quem recebeu)
```

- com Descrição/Observação no comprovante → `VALOR - DESCRIÇÃO - DATA`
- aporte/distribuição/transferência → `VALOR - QUEM PAGOU PARA QUEM RECEBEU - DATA`
- PIX sem descrição (fornecedor) → `VALOR - QUEM RECEBEU - DATA`

Dica: coloque o **centro de custo e o nº da OC/NF na descrição do PIX/boleto**
na hora de pagar — é isso que permite o casamento automático no App 2.

## App 2 — Anexar Comprovantes

Duplo-clique em `anexar/Anexar Comprovantes.bat`.

1. Informe o **período** dos pagamentos (datas de pagamento dos comprovantes).
2. Selecione a **pasta dos PDFs renomeados** (a saída do App 1).
3. Clique em **Conectar e carregar contas** — o Chrome abre (tela cheia), você
   faz login no Mais Controle (só na 1ª vez; o perfil fica salvo) e o app busca
   os títulos **pagos** do período.
4. Marque as **contas bancárias** desejadas nas caixas de seleção.
5. (Opcional) Marque **Simular** para só conferir, sem anexar de verdade.
6. Clique em **Casar e anexar**.

O app então:

- verifica, título por título, se o **sub-pagamento** (Histórico de Pagamentos)
  já tem arquivo anexado — quem já tem é **pulado** (não duplica);
- casa cada pagamento pendente com o PDF pelo **valor** + nº de **OC/NF/doc** +
  **centro de custo** + **data** (cada PDF é usado uma vez só);
- anexa os casamentos com certeza, aplicando a tag **Comprovante**;
- gera um **relatório Excel** com 3 abas: `ANEXADOS`, `DUVIDA` (casamentos
  ambíguos, com os candidatos e o link do lançamento) e `SEM PAR`.

Também dá para anexar a partir de uma **lista pronta** (CSV `launchId,valor,arquivo_pdf`
ou o próprio relatório Excel) usando o modo "Por lista" na janela.

## Perguntas comuns

**A senha do Mais Controle passa pelo app?** Não. O login é feito por você na
janela do Chrome; o app só usa a sessão já autenticada. O perfil fica salvo em
`anexar/.chrome_profile` no seu computador.

**E se rodar duas vezes?** Sem problema: pagamentos que já têm anexo são pulados.

**Pagamentos com juros/multa?** O casamento é feito pelo valor **pago** no ERP.
Se o PDF foi renomeado com o valor com juros, confira a aba `SEM PAR` do
relatório e anexe manualmente (ou pelo modo "Por lista").

**Funciona em qualquer conta do Mais Controle?** Sim — o app usa a API que a
própria tela de Pagamentos usa, com o seu login. Não há nada fixo da empresa
no código.

## Estrutura

```
separar_renomear/   App 1 (separar páginas + renomear)
anexar/             App 2 (buscar pagos, casar e anexar)
  ├─ anexar_comprovantes.py   janela principal
  ├─ mc_api.py                leitura dos pagos e dos anexos (API)
  ├─ mc_client.py             automação do Chrome para anexar (Playwright)
  ├─ matcher.py               casamento PDF ↔ pagamento
  ├─ planilha.py              leitura de lista CSV/XLSX
  └─ config.py                ajustes (tag, perfil do Chrome, etc.)
```

## Licença

MIT — use, modifique e distribua à vontade. Este projeto não tem vínculo com o
Mais Controle ERP; é uma automação de uso pessoal sobre a interface web.
