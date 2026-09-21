---
paths:
  - "contratos/**"
---

# Arquitetura: contratos/

> Trecho da seção "Arquitetura", movido do `CLAUDE.md` em 21/09/2026 sem mudar uma palavra.
> Carrega sozinho quando o Claude lê um arquivo dos caminhos acima.
> Mudou o código? Atualize AQUI — este é o lugar deste texto agora.

- `contratos/` — aba Contratos (Mensal): acha o contrato de **compra e venda**
  de toda casa que recebeu qualquer coisa no mês (sinal, entrada,
  financiamento, intermediação — desde 09/09/2026 a apuração dos impostos é
  sobre todo recebimento; até então a aba arquivava o contrato da Caixa, só do
  financiamento) e grava em `<MÊS ANO - EMPRESA>/CONTRATOS/`. Cinco peças
  puras (`regras`, `escolha`, `conferencia`, `destino`, `pipeline`) testadas
  contra respostas capturadas do ERP; `leitura.py` é a única que toca PDF/OCR
  e entra no pipeline por parâmetro. Decisões que parecem detalhe e não são:
  (1) **o nome do arquivo tem o prefixo `CONTRATO DE COMPRA E VENDA`** porque a
  pasta guarda, à mão desde 2024, o contrato da Caixa como `CONTRATO <obra> CS
  01 - …` — o nome antigo apagaria o da Caixa; e o pipeline NUNCA grava por
  cima (mesmo conteúdo = "já estava"; conteúdo diferente ou a mesma casa com
  outro nome = revisão). (2) O contrato da Caixa também chama a SPE de VENDEDOR
  e traz casa, comprador e valor; só o par "Caixa Econômica Federal" +
  "devedor fiduciante" o denuncia — é o ponto TIPO da conferência. (3) Num lote
  de duas casas o contrato cita a OUTRA casa nas confrontações, e o endereço de
  quem assina pela SPE pode ter "Casa 22": a casa é lida no par `LT n CASA n`
  do objeto. (4) O ponto VENDEDORA (CNPJ ou razão social da empresa de
  destino no PDF) é o que pega contrato anexado na obra errada, o pior defeito
  daqui. (5) VALOR nunca retém: o contábil apura pelo que entrou no banco.
  (6) Recebimento sem casa na descrição fica em revisão sem botão de resolver
  — a correção é no ERP. (7) Entre versões do contrato na obra vale **a mais
  completa** (`… VENDEDOR`, `… ASSINATURA CORRETORA`, `… ASSINADO`; regra do
  dono, 09/09/2026); dois que se dizem completos continuam em revisão, e
  duas grafias sem sufixo são baixadas e comparadas byte a byte — metade das
  disputas de agosto/2026 era o mesmo PDF subido duas vezes. (8) O comprador
  é o **Cliente do recebimento** quando ele é pessoa; quando é a própria SPE
  (era assim em 20 das 25 linhas de agosto/2026 — financiamento, FGTS e
  juros nascem com a empresa como cliente) vale o nome da descrição, e o
  ponto COMPRADOR da conferência segura o resto. A leitura é progressiva: três páginas primeiro, o
  resto só se sobrou `?`; página sem texto vai para o `_ocr_em_lote` paralelo
  do Separar/Renomear. `mc_api.listar_recebimentos` traz `saleValue` (valor da
  VENDA) em cada linha; as Condições vistas em 2026 são Sinal, Entrada,
  1ª FINANCIAMENTO, JUROS FINANCIAMENTO, Reembolso Vistoria e FGTS.
