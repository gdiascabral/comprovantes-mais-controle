"""Recados da tela do dia para erros que têm causa conhecida e conserto na mão
do dono. Módulo puro: sem tela, sem rede."""
from __future__ import annotations

import errno

EXCEL_ABERTO = "O Excel do dia está aberto no Excel; feche-o e clique de novo."


def excel_aberto(e: BaseException) -> str:
    """O recado quando o Excel do dia não pôde ser gravado porque o arquivo
    está aberto no Excel (no Windows: `PermissionError`, errno 13 — pedido
    do dono 22/10/2026, o Registro mostrava "[Errno 13] Permission denied").
    Vazio para qualquer outro erro (a tela mostra o recado de sempre)."""
    vistos = set()
    while e is not None and id(e) not in vistos:
        vistos.add(id(e))
        if isinstance(e, PermissionError) or getattr(e, "errno", None) == errno.EACCES:
            return EXCEL_ABERTO
        e = e.__cause__ or e.__context__
    return ""
