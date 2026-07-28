# -*- coding: utf-8 -*-
"""
Atualização automática do executável via GitHub Releases.

Ao abrir o app: consulta a última versão publicada (timeout curto); se for
mais nova que a atual, pergunta ao usuário, baixa com janela de progresso,
troca o arquivo por um .bat auxiliar (com retentativas, por causa de
OneDrive/antivírus) e reabre. Falhas são mostradas ao usuário e gravadas
em "atualizacao.log" ao lado do exe. Rodando como script Python, não faz nada.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO = "gdiascabral/comprovantes-mais-controle"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"


def _logar(msg: str):
    try:
        arq = Path(sys.executable).parent / "atualizacao.log"
        with open(arq, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%d/%m/%Y %H:%M:%S  ") + msg + "\n")
    except OSError:
        pass


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


def _baixar_com_progresso(url: str, destino: Path, ultima: str):
    """Baixa mostrando uma janelinha de progresso. Retorna (ok, erro)."""
    import threading
    import tkinter as tk
    from tkinter import ttk
    import requests

    raiz = tk.Tk()
    raiz.title("Atualizando o app")
    raiz.geometry("440x130")
    raiz.resizable(False, False)
    tk.Label(raiz, text=f"Baixando a versão {ultima}...").pack(pady=(16, 6))
    barra = ttk.Progressbar(raiz, length=400, mode="determinate", maximum=100)
    barra.pack()
    info = tk.Label(raiz, text="conectando...")
    info.pack(pady=4)
    erro = []

    def trabalho():
        try:
            # timeout: 15 s p/ conectar; 120 s sem receber NENHUM byte.
            # Download lento (mas andando) não é interrompido.
            with requests.get(url, stream=True, timeout=(15, 120)) as r:
                r.raise_for_status()
                total = int(r.headers.get("content-length") or 0)
                feito = 0
                with open(destino, "wb") as fh:
                    for parte in r.iter_content(1024 * 256):
                        fh.write(parte)
                        feito += len(parte)
                        if total:
                            pct = feito * 100.0 / total
                            txt = f"{feito // (1024*1024)} de {total // (1024*1024)} MB"
                            raiz.after(0, lambda p=pct, t=txt: (
                                barra.config(value=p), info.config(text=t)))
            if total and destino.stat().st_size != total:
                raise RuntimeError("download veio incompleto")
        except Exception as e:
            erro.append(str(e)[:200])
        raiz.after(0, raiz.destroy)

    threading.Thread(target=trabalho, daemon=True).start()
    raiz.mainloop()
    return (not erro), (erro[0] if erro else "")


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
        "Baixar e atualizar agora? O app reabre sozinho ao terminar.")
    raiz.destroy()
    if not quer:
        _logar(f"atualização {ultima} recusada pelo usuário")
        return

    exe = Path(sys.executable)
    url = (f"https://github.com/{REPO}/releases/latest/download/"
           + exe.name.replace(" ", "%20"))
    novo = Path(tempfile.gettempdir()) / (exe.stem + " novo.exe")
    _logar(f"baixando {ultima} de {url}")
    ok, motivo = _baixar_com_progresso(url, novo, ultima)
    if not ok:
        _logar(f"FALHA no download: {motivo}")
        raiz = tk.Tk(); raiz.withdraw()
        messagebox.showwarning(
            "Atualização não concluída",
            f"Não consegui baixar a atualização.\nMotivo: {motivo}\n\n"
            "O app vai abrir na versão atual. Você pode tentar de novo "
            "fechando e abrindo o app, ou baixar manualmente em:\n"
            f"github.com/{REPO}/releases")
        raiz.destroy()
        return
    _logar(f"download ok ({novo.stat().st_size // (1024*1024)} MB); trocando o exe")

    try:
        pid = os.getpid()
        bat = Path(tempfile.gettempdir()) / "atualizar_comprovantes.bat"
        bat.write_text(
            "@echo off\n"
            ":espera\n"
            f"tasklist /FI \"PID eq {pid}\" | find \"{pid}\" >nul "
            "&& (timeout /t 1 >nul & goto espera)\n"
            "set tent=0\n"
            ":tenta\n"
            f"move /y \"{novo}\" \"{exe}\" >nul 2>&1\n"
            "if errorlevel 1 (\n"
            "  set /a tent+=1\n"
            "  timeout /t 1 >nul\n"
            f"  if %tent% LSS 30 goto tenta\n"
            ")\n"
            f"start \"\" \"{exe}\"\n"
            "del \"%~f0\"\n", encoding="utf-8")
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        sys.exit(0)                     # o .bat troca o exe e reabre
    except SystemExit:
        raise
    except Exception as e:
        _logar(f"FALHA na troca do exe: {e}")
        return
