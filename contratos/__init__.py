# -*- coding: utf-8 -*-
"""Contratos de compra e venda: do recebimento do mês ao arquivo na pasta.

Pacote importado como `contratos.frame`. Foi o segundo do app a ser pacote de
verdade, quando as pastas de aba ainda entravam uma a uma num `sys.path` plano
— e a razão era esta: um `conferencia.py` solto lá sequestraria o `import
conferencia` do Anexar, do mesmo jeito que um `config.py` sequestraria o dele.
Desde 02/09/2026 TODAS as pastas são pacotes, então `contratos.conferencia` e
`anexar.conferencia` convivem por construção, e não por sorte de ordem.

Nasceu em 11/08/2026 arquivando o contrato de FINANCIAMENTO (o da Caixa) das
casas que financiaram no mês. Em 09/09/2026 a apuração dos impostos passou a
ser sobre todo recebimento, e o alvo virou o contrato de COMPRA E VENDA entre
a SPE e o comprador, de toda casa que recebeu qualquer coisa no mês.

As cinco primeiras peças são PURAS: recebem dicionário, devolvem dado, e não
sabem que existe navegador nem interface. É o que permite testá-las contra as
respostas reais capturadas do ERP, sem abrir o Chrome uma vez. `leitura.py`
é a única que toca PDF e OCR, e o pipeline a recebe por parâmetro.
"""
