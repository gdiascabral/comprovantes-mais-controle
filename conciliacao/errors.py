"""Excecoes do programa.

Vivem num modulo sem dependencias para que o CLI possa trata-las sem precisar
importar o Playwright.
"""

from __future__ import annotations


class ErpError(Exception):
    """Falha na coleta de dados do ERP."""


class SessaoExpirada(ErpError):
    """A sessao caiu e nao ha como logar sem interacao humana."""
