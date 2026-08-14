# -*- coding: utf-8 -*-
"""
Motor do "Comprovantes — Mais Controle".

O executável é dividido em duas partes:

  MOTOR  = este arquivo + Python + bibliotecas pesadas (OCR, Playwright...).
           Muda raramente; é o exe grande.
  CÓDIGO = a lógica do app (comprovantes_app, separar_renomear, anexar/...),
           publicada como "codigo.zip" (~100 KB) em cada release.

Ao abrir, o motor confere se há código novo no GitHub e baixa só o zip
(segundos). O exe traz uma cópia do código embutida de fábrica, então
funciona offline e no primeiro uso. Se uma release exigir motor mais novo
(motor_minimo.txt), o app oferece o download completo.
"""
import sys
from pathlib import Path


# A armadilha desta lista: o código das abas viaja no `codigo.zip`, e o
# PyInstaller NUNCA o analisa — ele só segue os imports a partir deste arquivo.
# Então tudo que as abas importam da biblioteca padrão precisa estar declarado
# AQUI, ainda que o motor não use nada disso. O que ninguém declara não entra no
# exe, e o erro aparece no `import` da aba, antes de existir janela para
# mostrá-lo: o que a pessoa vê é o app não abrir (foi assim na v1.0.71, com o
# `tkinter.font`). Quem vigia isto é `tests/test_imports_do_motor.py`.
def _garantir_dependencias():        # nunca é chamada: só faz o PyInstaller
    import tkinter                    # noqa  enxergar e embutir estes módulos
    from tkinter import ttk, filedialog, messagebox   # noqa
    import queue, csv, unicodedata, threading         # noqa
    import tempfile, subprocess, zipfile, shutil      # noqa
    from concurrent.futures import ThreadPoolExecutor  # noqa
    import requests, pdfplumber, pypdf, openpyxl      # noqa
    import pytesseract                                # noqa
    import sv_ttk                                     # noqa
    import yaml                                       # noqa  (config da Conciliação)
    import decimal, json, urllib.request              # noqa  (conciliação: API + regras)
    import hashlib, time                              # noqa  (cnab240: histórico das remessas)
    import webbrowser, calendar, base64              # noqa  stdlib usados só pelo app
    import difflib                                    # noqa  (aportes/mc_catalogos: os "nomes parecidos" do erro)
    import ctypes.wintypes                            # noqa  (login cifrado DPAPI)
    from playwright.sync_api import sync_playwright   # noqa


def principal():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)   # nitidez em telas HiDPI
    except Exception:
        pass

    if getattr(sys, "frozen", False):
        import atualizador
        fonte = atualizador.preparar_codigo()
    else:
        fonte = Path(__file__).resolve().parent   # modo script: usa o repositório

    for sub in ("separar_renomear", "anexar", ""):
        p = str(fonte / sub) if sub else str(fonte)
        if p not in sys.path:
            sys.path.insert(0, p)

    import comprovantes_app
    comprovantes_app.main()


if __name__ == "__main__":
    principal()
