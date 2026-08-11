"""Automacao da conciliacao financeira diaria.

Fluxo: coleta no ERP -> snapshot bruto (JSON) -> regras -> planilha + resumo.
Tudo depois do snapshot roda offline, sem browser.
"""

__version__ = "0.1.0"
