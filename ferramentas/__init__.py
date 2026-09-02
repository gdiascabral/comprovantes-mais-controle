# -*- coding: utf-8 -*-
"""Ferramentas locais do repositório. Nada daqui viaja no `codigo.zip`.

A `galeria` fotografa as doze telas do app para comparar o visual antes e
depois de mexer nele; a `sonda` pergunta todo dia se o ERP, o Inter e o Sicoob
ainda respondem. As duas rodam FORA do exe — uma à mão, a outra pelo Agendador
de Tarefas do Windows — e o app nunca as importa. Quem guarda isso é o
`_PASTAS_SO_DO_REPO` do `tests/test_empacotamento.py`.

É pacote (e não uma pasta solta) pelo mesmo motivo das pastas de aba: os
módulos daqui se importam pelo caminho inteiro, e ninguém precisa pôr esta
pasta no `sys.path` para alcançá-los. Rode-as da RAIZ, com
`python -m ferramentas.sonda` e `python -m ferramentas.galeria`.
"""
