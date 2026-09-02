# -*- coding: utf-8 -*-
"""Aba Remessa/Retorno: a planilha do dia e o arquivo CNAB 240 do Sicoob.

Pacote desde 02/09/2026. Dois nomes daqui contam a história do `sys.path`
plano: `relatorio.py`, que já dividia o espaço global com `relatorios/`, e
`regras_pagamento.py`, que só se chama assim porque `aportes/regras.py` existe
e esta pasta entrava ANTES no caminho de import — um `regras.py` aqui teria
sequestrado o import da aba Aportes, sem erro nenhum. Hoje o caminho inteiro
diz de quem é cada módulo.
"""
