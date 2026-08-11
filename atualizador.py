# -*- coding: utf-8 -*-
"""
Atualizador do motor (usado apenas dentro do executável).

- preparar_codigo(): baixa o "codigo.zip" novo (leve, segundos) quando há
  release mais nova, escolhe qual código usar (pasta "codigo" ao lado do
  exe ou a cópia embutida de fábrica) e confere o motor mínimo exigido.
- Se a release exigir motor mais novo, oferece o download completo do exe
  com janela de progresso e troca o arquivo via .bat (com retentativas,
  por causa de OneDrive/antivírus).
Tudo é registrado em "atualizacao.log" ao lado do exe.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

REPO = "gdiascabral/comprovantes-mais-controle"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"


# ------------------------------------------------------------ utilidades
def _logar(msg: str):
    try:
        arq = Path(sys.executable).parent / "atualizacao.log"
        with open(arq, "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%d/%m/%Y %H:%M:%S  ") + msg + "\n")
    except OSError:
        pass


def _tupla(tag):
    try:
        return tuple(int(x) for x in str(tag).strip().lstrip("v").split("."))
    except ValueError:
        return ()


def _ler(arquivo: Path):
    try:
        return arquivo.read_text(encoding="utf-8").strip()
    except OSError:
        return None


def _versao_motor():
    base = getattr(sys, "_MEIPASS", None)
    return (_ler(Path(base) / "versao.txt") if base else None) or "v0.0.0"


# ------------------------------------------------------ pacote de código
def preparar_codigo() -> Path:
    """Atualiza (se der) e devolve a pasta de código que o motor deve usar."""
    exe_dir = Path(sys.executable).parent
    pasta = exe_dir / "codigo"
    emb = Path(sys._MEIPASS) / "codigo_embutido"
    v_motor = _versao_motor()

    try:
        _atualizar_codigo(pasta, emb)
    except Exception as e:
        _logar(f"não deu para verificar/baixar código novo: {str(e)[:150]}")

    v_local = _ler(pasta / "versao.txt")
    v_emb = _ler(emb / "versao.txt") or "v0.0.0"
    fonte = pasta if (v_local and _tupla(v_local) >= _tupla(v_emb)) else emb

    minimo = _ler(fonte / "motor_minimo.txt")
    if minimo and _tupla(minimo) > _tupla(v_motor):
        _logar(f"código {_ler(fonte / 'versao.txt')} exige motor {minimo}; "
               f"motor atual é {v_motor}")
        if _oferecer_motor_novo(minimo):
            sys.exit(0)                 # o .bat troca o exe e reabre
        fonte = emb                     # recusou/falhou: usa o código de fábrica
    return fonte


def _atualizar_codigo(pasta: Path, emb: Path):
    """Baixa e instala o codigo.zip se a release for mais nova (rápido)."""
    import requests
    r = requests.get(API_LATEST, timeout=5)
    r.raise_for_status()
    ultima = r.json().get("tag_name") or ""
    v_ref = _ler(pasta / "versao.txt") or _ler(emb / "versao.txt") or "v0"
    if not _tupla(ultima) or _tupla(ultima) <= _tupla(v_ref):
        return
    url = f"https://github.com/{REPO}/releases/latest/download/codigo.zip"
    tmp = Path(tempfile.gettempdir()) / "codigo_novo.zip"
    with requests.get(url, timeout=(15, 60)) as resp:
        resp.raise_for_status()
        tmp.write_bytes(resp.content)

    nova = pasta.with_name("codigo_nova")
    shutil.rmtree(nova, ignore_errors=True)
    with zipfile.ZipFile(tmp) as z:
        z.extractall(nova)
    if not (nova / "comprovantes_app.py").exists():
        raise RuntimeError("codigo.zip veio sem o app dentro")

    velha = pasta.with_name("codigo_velha")
    shutil.rmtree(velha, ignore_errors=True)
    if pasta.exists():
        pasta.rename(velha)
    nova.rename(pasta)
    shutil.rmtree(velha, ignore_errors=True)
    try:
        tmp.unlink()
    except OSError:
        pass
    _logar(f"código atualizado para {ultima}")


# ------------------------------------------------- motor novo (download grande)
def _baixar_com_progresso(url: str, destino: Path, titulo: str):
    """Baixa mostrando uma janelinha de progresso. Retorna (ok, erro)."""
    import threading
    import tkinter as tk
    from tkinter import ttk
    import requests

    raiz = tk.Tk()
    raiz.title("Atualizando o app")
    raiz.geometry("440x130")
    raiz.resizable(False, False)
    tk.Label(raiz, text=titulo).pack(pady=(16, 6))
    barra = ttk.Progressbar(raiz, length=400, mode="determinate", maximum=100)
    barra.pack()
    info = tk.Label(raiz, text="conectando...")
    info.pack(pady=4)
    erro = []

    def trabalho():
        try:
            # 15 s p/ conectar; 120 s sem receber NENHUM byte. Download
            # lento (mas andando) não é interrompido.
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


def script_de_troca(pid: int, novo: Path, exe: Path) -> str:
    """O .bat que espera este processo morrer, troca o exe e reabre o app.

    Função pura para poder ser testada: a troca em si só dá para ver
    acontecendo, e é rara (só quando entra biblioteca nova), então erro aqui
    fica escondido por meses.

    O que mudou depois da troca da v1.0.60, em ordem de importância:

    1. **Apaga as pastas `_MEI*` antes de abrir.** O exe é onefile e se extrai
       ali; resto de execução anterior deixa a extração pela metade e o app
       morre com "Failed to load Python DLL". Foi o erro real da v1.0.60.
    2. **Só abre o app se a troca deu certo.** Antes o `start` rodava mesmo
       depois das tentativas frustradas, abrindo um executável em estado
       indefinido sem avisar ninguém. Falhando, agora explica o que fazer.
    3. `enabledelayedexpansion` + `!tent!`. Antes o `%tent%` era lido no mesmo
       bloco em que o `set /a` escrevia, e blocos `( ... )` são expandidos no
       parse: o contador ficava uma volta atrasado e o retry fazia 31
       tentativas em vez de 30. Inofensivo, mas o código mentia sobre o que
       fazia.
    """
    return (
        "@echo off\n"
        "setlocal enabledelayedexpansion\n"
        ":espera\n"
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul '
        "&& (timeout /t 1 >nul & goto espera)\n"
        "set tent=0\n"
        ":tenta\n"
        f'move /y "{novo}" "{exe}" >nul 2>&1\n'
        "if not errorlevel 1 goto trocou\n"
        "set /a tent+=1\n"
        "if !tent! LSS 30 (timeout /t 1 >nul & goto tenta)\n"
        "echo.\n"
        "echo Nao consegui substituir o aplicativo.\n"
        "echo Feche o programa, apague as pastas _MEI de %TEMP% e tente de novo.\n"
        f'echo Se persistir, mova na mao:  "{novo}"  ->  "{exe}"\n'
        "echo.\n"
        "pause\n"
        "exit /b 1\n"
        ":trocou\n"
        'for /d %%d in ("%TEMP%\\_MEI*") do rd /s /q "%%d" 2>nul\n'
        "timeout /t 2 >nul\n"
        f'start "" "{exe}"\n'
        'del "%~f0"\n'
    )


def _oferecer_motor_novo(minimo: str) -> bool:
    """Baixa o exe completo (raro: só quando entra biblioteca nova).
    Retorna True se a troca foi disparada (o chamador deve encerrar)."""
    import tkinter as tk
    from tkinter import messagebox

    raiz = tk.Tk(); raiz.withdraw()
    quer = messagebox.askyesno(
        "Atualização grande necessária",
        "Esta atualização traz componentes novos e precisa baixar o app "
        "completo (~150 MB) — coisa rara, na maioria das vezes a atualização "
        "é de segundos.\n\nBaixar agora? O app reabre sozinho ao terminar.\n"
        "(Se preferir, responda Não e o app abre na versão atual.)")
    raiz.destroy()
    if not quer:
        _logar("motor novo recusado pelo usuário")
        return False

    exe = Path(sys.executable)
    url = (f"https://github.com/{REPO}/releases/latest/download/"
           + exe.name.replace(" ", "%20"))
    novo = Path(tempfile.gettempdir()) / (exe.stem + " novo.exe")
    _logar(f"baixando motor novo de {url}")
    ok, motivo = _baixar_com_progresso(url, novo, "Baixando o app completo...")
    if not ok:
        _logar(f"FALHA no download do motor: {motivo}")
        raiz = tk.Tk(); raiz.withdraw()
        messagebox.showwarning(
            "Atualização não concluída",
            f"Não consegui baixar o app completo.\nMotivo: {motivo}\n\n"
            "O app vai abrir na versão atual. Tente de novo mais tarde ou "
            f"baixe manualmente em:\ngithub.com/{REPO}/releases")
        raiz.destroy()
        return False
    _logar(f"download do motor ok ({novo.stat().st_size // (1024*1024)} MB); trocando")

    try:
        pid = os.getpid()
        bat = Path(tempfile.gettempdir()) / "atualizar_comprovantes.bat"
        bat.write_text(script_de_troca(pid, novo, exe), encoding="utf-8")
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception as e:
        _logar(f"FALHA na troca do exe: {e}")
        return False
