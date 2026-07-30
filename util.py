# -*- coding: utf-8 -*-
"""Utilitários compartilhados pelos módulos do app (sem dependências pesadas).

Fica na RAIZ do pacote de código; é copiado para o codigo.zip do auto-update
e para os exes. Módulos em subpastas o importam com um fallback de sys.path
(ver o topo de cada arquivo) para funcionarem também rodados isoladamente.
"""
import re
import unicodedata


def fmt_dur(seg: float) -> str:
    """Formata uma duração em segundos: '45 s', '3 min 07 s', '1 h 02 min'."""
    seg = int(round(seg))
    m, s = divmod(seg, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h} h {m:02d} min"
    if m:
        return f"{m} min {s:02d} s"
    return f"{s} s"


def sem_acento(s: str) -> str:
    """Remove acentos, preservando maiúsculas/minúsculas."""
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def norm(s: str) -> str:
    """Sem acento, em MAIÚSCULAS (para comparações)."""
    return sem_acento(s).upper()


def norm_espaco(s: str) -> str:
    """Como norm(), mas também colapsa espaços repetidos e apara as pontas."""
    return re.sub(r"\s+", " ", norm(s)).strip()


def cor_escura(cor_hex) -> bool:
    """True se a cor de fundo '#rrggbb' for escura. Usado para já criar os
    campos de log na cor certa do tema e evitar o 'flash' branco no escuro."""
    cor = (cor_hex or "").lstrip("#")
    if len(cor) != 6:
        return False
    try:
        r, g, b = (int(cor[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return False
    return (r + g + b) / 3 < 128
