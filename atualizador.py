# -*- coding: utf-8 -*-
"""
Atualização automática do executável via GitHub Releases.

Ao abrir o app: consulta a última versão publicada (timeout curto); se for
mais nova que a atual, pergunta ao usuário, baixa o exe novo, troca o
arquivo por um .bat auxiliar e reabre. Qualquer falha (sem internet, API
fora do ar, sem permissão na pasta) é silenciosa: o app abre normalmente.
Rodando como script Python (sem PyInstaller), não faz nada.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "gdiascabral/comprovantes-mais-controle"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"


def _versao_atual():
    base = getattr(sys, "_MEIPASS", None)
    if not base:
        return None                    # rodando como script: sem auto-update
    try:
        return (Path(base) / "versao.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _tupla(tag: str):
    try:
        return tuple(int(x) for x in tag.strip().lstrip("v").split("."))
    except ValueError:
        return ()


def verificar_e_atualizar():
    """Confere se há versão nova; se houver e o usuário aceitar, baixa,
    troca o executável e reinicia (o processo atual encerra)."""
    atual = _versao_atual()
    if not atual or not getattr(sys, "frozen", False):
        return
    try:
        import requests
        r = requests.get(API_LATEST, timeout=5)
        r.raise_for_status()
        ultima = r.json().get("tag_name") or ""
    except Exception:
        return                          # sem internet/API: abre normalmente
    if not _tupla(ultima) or _tupla(ultima) <= _tupla(atual):
        return

    import tkinter as tk
    from tkinter import messagebox
    raiz = tk.Tk()
    raiz.withdraw()
    quer = messagebox.askyesno(
        "Atualização disponível",
        f"Há uma versão nova do app ({ultima} — você está na {atual}).\n\n"
        "Baixar e atualizar agora? Leva cerca de 1 minuto e o app "
        "reabre sozinho.")
    raiz.destroy()
    if not quer:
        return

    exe = Path(sys.executable)
    url = (f"https://github.com/{REPO}/releases/latest/download/"
           + exe.name.replace(" ", "%20"))
    try:
        import requests
        novo = Path(tempfile.gettempdir()) / (exe.stem + " novo.exe")
        with requests.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            with open(novo, "wb") as fh:
                for parte in r.iter_content(1024 * 512):
                    fh.write(parte)
        pid = os.getpid()
        bat = Path(tempfile.gettempdir()) / "atualizar_comprovantes.bat"
        bat.write_text(
            "@echo off\n"
            ":espera\n"
            f"tasklist /FI \"PID eq {pid}\" | find \"{pid}\" >nul "
            "&& (timeout /t 1 >nul & goto espera)\n"
            f"move /y \"{novo}\" \"{exe}\" >nul\n"
            f"start \"\" \"{exe}\"\n"
            "del \"%~f0\"\n", encoding="utf-8")
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        sys.exit(0)                     # o .bat troca o exe e reabre
    except SystemExit:
        raise
    except Exception:
        return                          # falhou o download: abre a versão atual
