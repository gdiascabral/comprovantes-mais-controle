# -*- coding: utf-8 -*-
"""Coloca a raiz do projeto e as subpastas de código no sys.path para que os
testes possam importar os módulos do mesmo jeito que o app faz em runtime."""
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
for _p in (_RAIZ, _RAIZ / "separar_renomear", _RAIZ / "anexar"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))
