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
  01 - …` — o nome antigo apagaria o da Caixa; contrato marcado como
  distratado leva ` (Distratado)` antes da extensão (05/10/2026); e o pipeline
  NUNCA grava por
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
  disputas de agosto/2026 era o mesmo PDF subido duas vezes. **Exceção desde
  05/10/2026: casa com distrato guarda UM contrato POR COMPRADOR**, não um
  por casa (ver o parágrafo abaixo); a regra da mais completa vale dentro do
  grupo de cada comprador. (8) O comprador
  é o **Cliente do recebimento** quando ele é pessoa; quando é a própria SPE
  (era assim em 20 das 25 linhas de agosto/2026 — financiamento, FGTS e
  juros nascem com a empresa como cliente) vale o nome da descrição, e o
  ponto COMPRADOR da conferência segura o resto. A leitura é progressiva: três páginas primeiro, o
  resto só se sobrou `?`; página sem texto vai para o `_ocr_em_lote` paralelo
  do Separar/Renomear. `mc_api.listar_recebimentos` traz `saleValue` (valor da
  VENDA) em cada linha; as Condições vistas em 2026 são Sinal, Entrada,
  1ª FINANCIAMENTO, JUROS FINANCIAMENTO, Reembolso Vistoria e FGTS.

  **Casa com distrato (05/10/2026, decisões do dono: só o contrato é salvo —
  o distrato em si não vai para a pasta —, e a sugestão da marca é pelo nome
  do comprador).** Quando a obra tem anexo DISTRATO/RESCIS na casa,
  `pipeline.levantar` (com `abrir_pdf`, o mesmo do `arquivar`) baixa os
  contratos e os distratos, lê o comprador de cada contrato no PDF
  (`distrato.comprador_do_contrato`: o trecho "COMPRADOR: NOME,") e devolve
  uma linha por comprador. A do comprador do recebimento é a linha da casa; as
  demais nascem com `outro_contrato`. Se nenhum contrato é de quem pagou, a
  linha do recebimento fica em revisão ("não achei o contrato de …") e todas
  as outras viram extras — arquivar o contrato alheio calaria o que falta.
  Linha extra cujo comprador não foi lido é recusada no arquivar e nasce sem
  marca. A coluna DISTRATO (☐/☑) vem marcada quando os sobrenomes do comprador
  aparecem no texto de um distrato (`distrato.foi_distratado`), e a pessoa
  alterna no clique; marcada, o arquivo sai com ` (Distratado)`. A trava dos
  irmãos aceita as linhas da mesma casa na mesma rodada. A conferência da
  linha extra ou distratada usa o comprador lido no PDF (sem nome lido, o do
  recebimento); só a linha extra deixa de conferir VALOR da venda (o
  contrato é de outra venda). A marca mudada à mão volta na busca seguinte
  (`reaplicar_distratos`) e não muda em linha já arquivada; o resumo do mês
  conta a casa e os recebimentos uma vez, não por linha. A Acessórias mantém
  a marca na linha de mensagem. Casa sem distrato segue a regra de um contrato por casa, sem ler
  PDF no levantamento.

  **Condomínio: o contrato mora no lançamento da venda (regra do dono,
  09/11/2026).** O robô de venda anexa o PDF no recebimento, com o nome
  `CONTRATO CONDOMÍNIO … CASA 15 - NOME`. Por isso a linha UN lê
  `MCApi.anexos_da_venda` (`GET /sales/<saleId>` dá o `tradeReceivable.id`;
  depois `attachments/v2` com `entityOrigin=TRADE_RECEIVABLE_READJUSTED`) e
  escolhe com `escolha.contrato_do_lancamento`, que só aceita nome com COMPRA E
  VENDA ou CONTRATO + CONDOMINIO antes do primeiro " - " (o lançamento pode ter
  contrato de corretagem). Os anexos da obra (centenas, no condomínio) nunca
  respondem sozinhos: entram na janela de resolver, sem marca de candidato.
  Falha ao ler o lançamento vira revisão dizendo isso, nunca "sem contrato".
  **Duas vendas da mesma unidade no mês e unidade sem comprador vão para
  revisão.** O caminho de distrato não vale para UN: venda distratada de
  condomínio ainda depende da marca à mão na coluna (decisão a tomar quando o
  primeiro caso existir). Na conferência, a casa é a PRIMEIRA `Unidade: Casa nº
  15` do texto, que é a do objeto; `Casa 15` solta não conta, porque pode ser o
  endereço de quem vende. Contrato achado sozinho precisa do ponto TIPO em
  CONFERE no condomínio; escolhido à mão, não.

  **Mesmo nome não é o mesmo arquivo (09/11/2026).** `candidatos_distintos` só
  junta registros de mesmo id. Numa casa revendida, dois anexos de nome idêntico
  eram contratos de compradores diferentes, e o segundo sumia da lista. Sobrando
  mais de um, o pipeline baixa e compara: bytes iguais, ou **texto inteiro e
  imagens por página** iguais na camada de texto (dois PDFs do mesmo envelope
  Clicksign diferem nos bytes), são o mesmo documento (`LeitorPDF.impressao`).
  OCR, página sem texto ou só as primeiras páginas não provam nada: a página de
  assinaturas fica no fim. Entre cópias, fica a que se diz completa. A janela de
  resolver e o "Abrir para olhar" identificam o anexo pelo id
  (`escolha.mesmo_anexo`, `pipeline.anexo_atual`). Escolha à mão cujo nome ficou
  repetido não volta sozinha na busca seguinte (`reaplicar`).

  **O arquivar renova o link (09/11/2026).** O `downloadUrl` vale 30 min
  (`X-Amz-Expires=1800`), e quem confere a tabela antes de arquivar passava do
  prazo: outubro perdeu 15 de 16 downloads assim. `arquivar` relê a lista da obra
  (e do lançamento, no condomínio) uma vez por obra e baixa pelo link novo
  (`_baixar_do_jeito_certo`); falhando a releitura, tenta o link da busca.
