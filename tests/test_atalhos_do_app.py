# -*- coding: utf-8 -*-
"""Toda sequencia de tecla que o app registra tem de existir no Tk do exe.

Em 03/09/2026 a v2.0.161 nao abriu na maquina do dono: comprovantes_app.py
fazia `root.bind_all("<Control-ISO_Left_Tab>", ...)`, e ISO_Left_Tab e keysym
do X11 — o Tk 8.6 do Python 3.11 (o do exe, e o do CI) recusa com
`bad event type or keysym`. O Tk da maquina de desenvolvimento aceita, e
nenhum teste executa o main() do app, entao a linha so rodou na maquina de
quem usa. Este teste le as sequencias do fonte e as registra num widget
descartavel do Tk da suite: o CI roda no mesmo Python 3.11 do exe, e e la
que isto tem de falhar.
"""
import re
import tkinter as tk
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent

#: `bind("<X>")`, `bind_all("<X>")` e `bind_class("Classe", "<X>")`.
_PADRAO = re.compile('bind(?:_all|_class)?[(][ ]*(?:"[A-Za-z]+"[ ]*,[ ]*)?"(<[^"]+>)"')


def _arquivos_do_app():
    for arq in [*sorted(_RAIZ.glob("*.py")), *sorted(_RAIZ.glob("*/*.py"))]:
        partes = set(arq.relative_to(_RAIZ).parts)
        if partes & {"tests", "ferramentas"}:
            continue
        yield arq


def _sequencias():
    achadas = {}
    for arq in _arquivos_do_app():
        for m in _PADRAO.finditer(arq.read_text(encoding="utf-8")):
            achadas.setdefault(m.group(1), arq.relative_to(_RAIZ).as_posix())
    return achadas


def test_toda_sequencia_de_tecla_e_aceita_pelo_tk(raiz):
    seqs = _sequencias()
    assert len(seqs) > 10, f"achei poucas sequencias ({seqs}) — o padrao envelheceu"
    w = tk.Frame(raiz)
    recusadas = {}
    try:
        for seq, onde in seqs.items():
            try:
                w.bind(seq, lambda e: None)
            except tk.TclError as e:
                recusadas[seq] = f"{onde}: {e}"
    finally:
        w.destroy()
    versao = raiz.tk.call("info", "patchlevel")
    assert not recusadas, (
        f"o Tk {versao} recusa estas sequencias — na maquina do usuario o app "
        f"nao abre (foi a v2.0.161): {recusadas}")
