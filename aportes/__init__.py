# -*- coding: utf-8 -*-
"""Aba Aportes: lança no ERP o aporte do investidor e o reembolso dele.

Pacote desde 02/09/2026. O `regras.py` daqui é o motivo de o módulo de regras
do `pagamentos_dia/` ter nascido `regras_pagamento.py`: no `sys.path` plano os
dois eram só `regras`, `pagamentos_dia` entrava ANTES no caminho, e um
`regras.py` de lá teria sequestrado o import desta aba. Hoje são
`aportes.regras` e `pagamentos_dia.regras_pagamento`, e o sufixo virou
história em vez de exigência.
"""
