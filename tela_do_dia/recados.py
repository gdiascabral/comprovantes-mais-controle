"""Recados da tela do dia para erros que têm causa conhecida e conserto na mão
do dono. Módulo puro: sem tela, sem rede."""
from __future__ import annotations

import errno
import ntpath

EXCEL_ABERTO = "O Excel do dia está aberto no Excel; feche-o e clique de novo."


def _mesmo_caminho(a, b) -> bool:
    """Comparação de caminho do Windows (barra e caixa não contam), com a
    mesma régua em qualquer máquina — o app só roda no Windows."""
    def norm(c):
        return ntpath.normcase(ntpath.normpath(str(c)))
    return bool(a) and bool(b) and norm(a) == norm(b)


def excel_aberto(e: BaseException, destino) -> str:
    """O recado quando o Excel do dia não pôde ser gravado porque o arquivo
    está aberto no Excel (no Windows: `PermissionError`, errno 13 — pedido
    do dono 22/10/2026, o Registro mostrava "[Errno 13] Permission denied").

    Só quando o erro é sobre o PRÓPRIO `destino` (o .xlsx do dia): pasta sem
    permissão, o modelo travado ou o OneDrive segurando outro arquivo dão o
    mesmo errno, e ali "feche o Excel" manda consertar a coisa errada (revisão
    geral de 22/10/2026). Vazio para qualquer outro erro (a tela mostra o
    erro de verdade)."""
    vistos = set()
    while e is not None and id(e) not in vistos:
        vistos.add(id(e))
        if ((isinstance(e, PermissionError) or getattr(e, "errno", None) == errno.EACCES)
                and _mesmo_caminho(getattr(e, "filename", None), destino)):
            return EXCEL_ABERTO
        e = e.__cause__ or e.__context__
    return ""
