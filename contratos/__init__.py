# -*- coding: utf-8 -*-
"""Contratos de financiamento: do recebimento do mês ao arquivo na pasta.

Pacote de VERDADE (com `__init__.py`), importado como `contratos.frame`, e de
propósito FORA do laço de `sys.path` do `comprovantes_app.py`. As pastas
daquele laço dividem um espaço de nomes global: um `conferencia.py` solto ali
sequestraria o `import conferencia` do Anexar, do mesmo jeito que um
`config.py` sequestraria o dele. Sendo pacote, o nome vive em
`contratos.conferencia` e não disputa com ninguém — é a mesma decisão de
`conciliacao/`.

As quatro primeiras peças são PURAS: recebem dicionário, devolvem dado, e não
sabem que existe navegador nem interface. É o que permite testá-las contra as
respostas reais capturadas do ERP, sem abrir o Chrome uma vez.
"""
