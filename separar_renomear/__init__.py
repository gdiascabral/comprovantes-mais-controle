# -*- coding: utf-8 -*-
"""Aba Separar e Renomear: separa páginas de PDF e renomeia pelo conteúdo.

O pacote e o módulo têm o MESMO nome, e isso é de propósito: renomear o
módulo mexeria em `campos()`, `processar()` e `_ocr_pagina`, que quatro outras
abas chamam. O preço é o `from separar_renomear.separar_renomear import ...`
nos consumidores, que é feio e é honesto — o `__init__.py` fica vazio para
`import separar_renomear` não arrastar `pdfplumber` e `tkinter` para quem só
queria o nome do pacote.
"""
