# -*- coding: utf-8 -*-
"""Aba Extratos Sicoob: monta a árvore do fechamento e baixa OFX e PDF.

Único módulo com navegador PRÓPRIO (executor de 1 worker e perfil
`.chrome_profile_sicoob`): é outro site e outro login.

Pacote desde 02/09/2026. O prefixo `sicoob_` de todos os módulos daqui nasceu
da falta dele — no `sys.path` plano, um `config.py` nesta pasta sequestraria o
`import config` do Anexar. O prefixo fica: renomear sete módulos para ganhar
sete caracteres mexe em quem usa sem melhorar nada para quem lê.
"""
