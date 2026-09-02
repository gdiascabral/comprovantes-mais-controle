# -*- coding: utf-8 -*-
"""Contratos de financiamento: do recebimento do mês ao arquivo na pasta.

Pacote importado como `contratos.frame`. Foi o segundo do app a ser pacote de
verdade, quando as pastas de aba ainda entravam uma a uma num `sys.path` plano
— e a razão era esta: um `conferencia.py` solto lá sequestraria o `import
conferencia` do Anexar, do mesmo jeito que um `config.py` sequestraria o dele.
Desde 02/09/2026 TODAS as pastas são pacotes, então `contratos.conferencia` e
`anexar.conferencia` convivem por construção, e não por sorte de ordem.

As quatro primeiras peças são PURAS: recebem dicionário, devolvem dado, e não
sabem que existe navegador nem interface. É o que permite testá-las contra as
respostas reais capturadas do ERP, sem abrir o Chrome uma vez.
"""
