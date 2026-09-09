# -*- coding: utf-8 -*-
"""Ferramentas locais do repositório. Nada daqui viaja no `codigo.zip`.

A `galeria` fotografa as doze telas do app para comparar o visual antes e
depois de mexer nele; a `sonda` pergunta todo dia se o ERP, o Inter e o Sicoob
ainda respondem; a `sentinela_erp` fotografa todo dia o inventário de rotas e
telas do front do ERP e alarma quando algo sumiu ou apareceu — a sonda prova
que o ERP responde, a sentinela prova que o contrato não mudou. As três rodam
FORA do exe — a galeria à mão, as outras duas pelo Agendador de Tarefas do
Windows — e o app nunca as importa. Quem guarda isso é o `_PASTAS_SO_DO_REPO`
do `tests/test_empacotamento.py`.

É pacote (e não uma pasta solta) pelo mesmo motivo das pastas de aba: os
módulos daqui se importam pelo caminho inteiro, e ninguém precisa pôr esta
pasta no `sys.path` para alcançá-los. Rode-as da RAIZ, com
`python -m ferramentas.sonda`, `python -m ferramentas.sentinela_erp` e
`python -m ferramentas.galeria`.
"""
