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


def _extrair_seguro(zip_path: Path, destino: Path):
    """Extrai conferindo os nomes ANTES (zip-slip).

    `extractall` obedece caminhos como "../../algo" e nomes absolutos: um zip
    adulterado escreveria FORA da pasta de destino. O codigo.zip vem do nosso
    próprio CI, mas chega pela rede e é o caminho mais direto que existe para
    plantar código na máquina de quem usa — conferir custa uma passada."""
    destino_abs = destino.resolve()
    with zipfile.ZipFile(zip_path) as z:
        for nome in z.namelist():
            alvo = (destino_abs / nome).resolve()
            if alvo != destino_abs and not str(alvo).startswith(
                    str(destino_abs) + os.sep):
                raise RuntimeError(f"caminho suspeito no codigo.zip: {nome!r}")
        z.extractall(destino_abs)


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
    # Pasta EXCLUSIVA desta execução. O nome fixo em %TEMP% era compartilhado
    # entre duas instâncias abertas ao mesmo tempo (e entre usuários da mesma
    # máquina): uma sobrescrevia o download da outra no meio da extração.
    trabalho = Path(tempfile.mkdtemp(prefix="comprovantes_upd_"))
    try:
        tmp = trabalho / "codigo.zip"
        with requests.get(url, timeout=(15, 60)) as resp:
            resp.raise_for_status()
            tmp.write_bytes(resp.content)

        nova = pasta.with_name("codigo_nova")
        shutil.rmtree(nova, ignore_errors=True)
        _extrair_seguro(tmp, nova)
        if not (nova / "comprovantes_app.py").exists():
            raise RuntimeError("codigo.zip veio sem o app dentro")

        velha = pasta.with_name("codigo_velha")
        shutil.rmtree(velha, ignore_errors=True)
        if pasta.exists():
            pasta.rename(velha)
        nova.rename(pasta)
        shutil.rmtree(velha, ignore_errors=True)
    finally:
        shutil.rmtree(trabalho, ignore_errors=True)
    _logar(f"código atualizado para {ultima}")


# ------------------------------------------------- motor novo (download grande)
def _baixar_com_progresso(url: str, destino: Path, titulo: str):
    """Baixa mostrando uma janelinha de progresso. Retorna (ok, erro)."""
    import queue
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

    # A thread do download NÃO fala com o Tk. Ela só empilha aqui; quem mexe
    # nos widgets é o `after` abaixo, na thread da interface. `raiz.after` de
    # outra thread é a mesma armadilha que já mordeu o app nas abas.
    avisos: "queue.Queue[tuple]" = queue.Queue()

    def drenar():
        try:
            while True:
                tipo, dado = avisos.get_nowait()
                if tipo == "progresso":
                    pct, txt = dado
                    barra.config(value=pct)
                    info.config(text=txt)
                elif tipo == "fim":
                    raiz.destroy()
                    return
        except queue.Empty:
            pass
        raiz.after(100, drenar)

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
                            avisos.put(("progresso", (
                                feito * 100.0 / total,
                                f"{feito // (1024*1024)} de "
                                f"{total // (1024*1024)} MB")))
            if total and destino.stat().st_size != total:
                raise RuntimeError("download veio incompleto")
        except Exception as e:
            erro.append(str(e)[:200])
        avisos.put(("fim", None))

    threading.Thread(target=trabalho, daemon=True).start()
    raiz.after(100, drenar)
    raiz.mainloop()
    return (not erro), (erro[0] if erro else "")


def _url_do_exe() -> tuple[str, str]:
    """(url, nome) do .exe da release mais nova, pela API.

    Deduzir a URL do nome do arquivo local dava 404 silencioso assim que
    alguém renomeava o executável — e renomear é comum, o app fica numa pasta
    própria e o nome vira o que a pessoa quiser. A release sabe o nome certo."""
    import requests
    r = requests.get(API_LATEST, timeout=15)
    r.raise_for_status()
    for a in (r.json().get("assets") or []):
        nome = a.get("name") or ""
        if nome.lower().endswith(".exe") and a.get("browser_download_url"):
            return a["browser_download_url"], nome
    raise RuntimeError("a release mais nova não tem executável publicado")


def _codepage_do_cmd() -> str:
    """A codepage com que o cmd.exe vai LER o .bat (850 no Brasil).

    Não é a do Python nem UTF-8: arquivo .bat é lido na codepage OEM do
    sistema, e é por isso que gravá-lo em UTF-8 estraga caminho com acento."""
    try:
        from ctypes import windll
        return f"cp{windll.kernel32.GetOEMCP()}"
    except Exception:
        return "cp850"


def _caminho_curto(p: Path) -> str:
    """O nome 8.3 do Windows, que é ASCII puro. "" quando não dá.

    É a defesa mais forte contra o problema de codificação: sem acento no
    caminho, nenhuma codepage tem como estragá-lo. Exige que o arquivo já
    exista, o que é o caso dos dois (o exe atual e o baixado)."""
    try:
        from ctypes import create_unicode_buffer, windll
        buf = create_unicode_buffer(1024)
        n = windll.kernel32.GetShortPathNameW(str(p), buf, 1024)
        curto = buf.value if 0 < n < 1024 else ""
        # Volume com 8.3 desligado devolve o caminho longo de volta.
        return curto if curto and curto != str(p) else ""
    except Exception:
        return ""


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
    4. **Caminho 8.3 quando o Windows der.** Em 11/08/2026 a troca falhou na
       máquina real com "O Windows não pode encontrar
       'C:\\AUTOMA├ç├òES MAIS CONTROLE\\...'": o .bat era gravado em UTF-8 e o
       cmd.exe lê .bat na codepage OEM (850 aqui), então `Ç` e `Õ` viravam
       `├ç` e `├ò` e nem o `move` nem o `start` achavam o arquivo. O app
       entrava em laço — abria, baixava 152 MB, falhava, fechava.
       O nome curto não tem acento nenhum, então nenhuma codepage tem como
       estragá-lo; e quem grava o arquivo ainda usa a codepage do cmd, para o
       caso de 8.3 estar desligado no volume.
    """
    novo_txt = _caminho_curto(novo) or str(novo)
    exe_txt = _caminho_curto(exe) or str(exe)
    novo, exe = Path(novo_txt), Path(exe_txt)
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
    try:
        url, nome_release = _url_do_exe()
    except Exception as e:
        _logar(f"FALHA ao descobrir o exe da release: {e}")
        raiz = tk.Tk(); raiz.withdraw()
        messagebox.showwarning(
            "Atualização não concluída",
            f"Não consegui localizar o app novo na release.\nMotivo: {e}\n\n"
            "O app vai abrir na versão atual. Tente de novo mais tarde ou "
            f"baixe manualmente em:\ngithub.com/{REPO}/releases")
        raiz.destroy()
        return False
    novo = Path(tempfile.mkdtemp(prefix="comprovantes_exe_")) / (
        exe.stem + " novo.exe")
    _logar(f"baixando motor novo ({nome_release}) de {url}")
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
        conteudo = script_de_troca(pid, novo, exe)
        # NUNCA utf-8 aqui: quem lê este arquivo é o cmd.exe, e ele usa a
        # codepage OEM do sistema. Ver o item 4 do `script_de_troca`.
        try:
            bat.write_text(conteudo, encoding=_codepage_do_cmd())
        except (UnicodeEncodeError, LookupError):
            # Caractere que não existe na codepage do console: o ASCII puro do
            # caminho 8.3 já deve ter evitado isto, mas se não evitou, gravar
            # errado é pior do que não gravar.
            _logar("não consegui gravar o .bat da troca na codepage do cmd")
            raise
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return True
    except Exception as e:
        _logar(f"FALHA na troca do exe: {e}")
        return False
