# -*- coding: utf-8 -*-
"""A rodada do água e energia disparada pelo app (plano 2, 14/10/2026).

O água e energia é outro repositório, instalado na máquina que roda as
rotinas (`C:\\AUTOMAÇÕES MAIS CONTROLE\\agua_energia`, ou `MC_AGUA_ENERGIA`).
O app não importa nada de lá: roda o mesmo `coletor\\rodada_diaria.bat` da
tarefa agendada e lê o que ele escreve.

O contrato com `coletor/trava_rodada.py` e `coletor/rodada_diaria.py` de lá:
código de saída 3 = outra rodada em andamento; a trava e o info em
`relatorios/`; a linha "resumo salvo em <caminho>" no log. Mudar um lado é
mudar o outro.

O Chrome central não entra aqui: a rodada é que conecta nele quando está
ligado (`mc_central.py` de lá) ou entra no ERP por conta própria (login por
HTTP, com a credencial do app) quando não está — e é a tela (`frame.py`) que
avisa do segundo caso.
"""
from __future__ import annotations

import errno
import json
import os
import re
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path

PASTA_PADRAO = Path(r"C:\AUTOMAÇÕES MAIS CONTROLE\agua_energia")
CODIGO_OCUPADA = 3                       # coletor/trava_rodada.py
NOME_TRAVA = "RODADA_EM_ANDAMENTO.trava"
NOME_INFO = "RODADA_EM_ANDAMENTO.json"
SO_PERMITIDOS = ("equatorial",)          # os `choices` do --so de lá
_SEM_JANELA = 0x08000000                 # CREATE_NO_WINDOW
_ORIGEM_OK = re.compile(r"app: [A-Za-z0-9 .@_-]+\Z")   # o que origem_segura produz
_TRANCADA = (errno.EACCES, errno.EDEADLK)             # o que o msvcrt levanta
_RESUMO = re.compile(r"resumo salvo em (.+?)\s*$")


NOME_MARCADOR = "RODADA_PELO_APP.txt"
MOTIVO_SEM_MARCADOR = (
    "Esta máquina não está marcada para rodar o água e energia pelo app "
    f"(falta {NOME_MARCADOR} na pasta do água e energia). "
    "A rodada roda na máquina das tarefas agendadas.")
MOTIVO_NAO_INSTALADO = ("O água e energia não está instalado nesta máquina "
                        "(ou MC_AGUA_ENERGIA=off).")


def situacao_da_instalacao() -> tuple[Path | None, str]:
    """(pasta, motivo): a pasta quando o botão pode ficar ligado, ou None com
    o motivo em texto de tela.

    Duas condições além de não estar desligada: o `.bat` existe E existe o
    marcador local `RODADA_PELO_APP.txt` ao lado das pastas dele. O marcador é
    criado à mão na máquina que roda a rodada; sem ele, uma cópia do água e
    energia noutro computador (cujas tarefas foram desligadas para não rodar
    em dobro) ligaria o botão, e a trava da rodada é local — duas máquinas
    rodariam ao mesmo tempo."""
    valor = (os.environ.get("MC_AGUA_ENERGIA") or "").strip()
    if valor.lower() == "off":
        return None, MOTIVO_NAO_INSTALADO
    pasta = Path(valor) if valor else PASTA_PADRAO
    if not (pasta / "coletor" / "rodada_diaria.bat").is_file():
        return None, MOTIVO_NAO_INSTALADO
    if not (pasta / NOME_MARCADOR).is_file():
        return None, MOTIVO_SEM_MARCADOR
    return pasta, ""


def pasta_agua_energia() -> Path | None:
    """A instalação do água e energia que roda pelo app, ou None."""
    return situacao_da_instalacao()[0]


def origem_segura(nome: str) -> str:
    """'app: <nome>' só com letras, números, espaço e `.@_-`.

    O texto atravessa o `cmd.exe`, onde `& | % ^ ! < > "` executam ou cortam
    coisas; o acento vira letra simples porque o `cmd` lê os argumentos antes
    de o `.bat` trocar a página de código."""
    simples = unicodedata.normalize("NFKD", nome or "").encode("ascii", "ignore").decode()
    limpo = re.sub(r"[^A-Za-z0-9 .@_-]", "", simples).strip()
    return f"app: {limpo or 'sem nome'}"


def linha_de_comando(*, so: str | None, origem: str) -> str:
    """A linha inteira, montada à mão: com `/s`, o `cmd` tira só o primeiro e
    o último par de aspas, e o resto chega ao `.bat` como está. A lista do
    `subprocess` poria aspas onde o `cmd` não espera. O prefixo de pasta atual
    (ponto e barra) na frente do `.bat` existe porque, com `NoDefaultCurrentDirectoryInExePath` ligado (ambiente
    endurecido) o `cmd` não procura na pasta atual."""
    if so is not None and so not in SO_PERMITIDOS:
        raise ValueError(f"--so desconhecido: {so!r}")
    if not _ORIGEM_OK.match(origem):
        raise ValueError("origem fora do formato: passe por origem_segura")
    args = f'--forcar --esperar 0 --origem "{origem}"'
    if so:
        args += f" --so {so}"
    return f'"{caminho_do_cmd()}" /d /s /c ".\\rodada_diaria.bat {args}"'


def caminho_do_cmd() -> str:
    """O `cmd.exe` pelo caminho completo (COMSPEC, ou System32): o nome solto
    seria procurado primeiro na pasta do exe do app."""
    comspec = (os.environ.get("COMSPEC") or "").strip()
    if comspec:
        return comspec
    raiz = os.environ.get("SystemRoot") or r"C:\Windows"
    return os.path.join(raiz, "System32", "cmd.exe")


def novo_log(pasta: Path, agora: datetime | None = None) -> Path:
    """Um log só desta rodada. O `.bat` anexa (`>>`) ao log da tarefa
    agendada e o `cmd` tranca o arquivo: uma segunda execução, enquanto a
    agendada roda, morria sem chamar o Python. Por isso a rodada do app tem
    log próprio, passado ao `.bat` pela variável RODADA_LOG."""
    agora = agora or datetime.now()
    pasta_logs = Path(pasta) / "coletor" / "logs"
    pasta_logs.mkdir(parents=True, exist_ok=True)   # instalação sem logs/ ainda
    base = f"rodada_app_{agora:%Y%m%d_%H%M%S}_{os.getpid()}"
    n = 1
    while True:
        caminho = pasta_logs / (f"{base}.log" if n == 1 else f"{base}_{n}.log")
        try:
            with open(caminho, "x"):                 # reserva o nome
                return caminho
        except FileExistsError:
            n += 1


def iniciar(pasta: Path, *, so: str | None, origem: str, log: Path) -> subprocess.Popen:
    """Dispara a rodada e volta na hora. O processo segue mesmo que o app
    feche; a trava de lá impede a segunda. `log` é o arquivo desta rodada
    (ver `novo_log`)."""
    env = {**os.environ, "RODADA_LOG": str(Path(log).absolute())}
    return subprocess.Popen(linha_de_comando(so=so, origem=origem),
                            cwd=str(Path(pasta) / "coletor"), env=env,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=_SEM_JANELA)


class Leitor:
    """Lê do log só o que chegou depois de ser criado, linha inteira por vez.

    Se o arquivo já existe, o começo dele é de antes: só vale o que chegar
    depois."""

    def __init__(self, caminho: Path):
        self.caminho = Path(caminho)
        try:
            self._pos = self.caminho.stat().st_size
        except OSError:
            self._pos = 0
        self._resto = b""

    def novas(self) -> list[str]:
        try:
            with open(self.caminho, "rb") as f:
                if os.fstat(f.fileno()).st_size < self._pos:
                    self._pos = 0            # log apagado/truncado: recomeça
                    self._resto = b""
                f.seek(self._pos)
                pedaco = f.read()
        except OSError:
            return []
        self._pos += len(pedaco)
        dados = self._resto + pedaco
        *inteiras, self._resto = dados.split(b"\n")
        return [b.decode("utf-8", "replace").rstrip("\r") for b in inteiras]


def resumo_do_log(linhas: list[str]) -> Path | None:
    for linha in reversed(linhas):
        m = _RESUMO.search(linha)
        if m:
            return Path(m.group(1))
    return None


def em_andamento(pasta: Path) -> dict | None:
    """O info de quem roda agora, ou None só quando comprovadamente livre.

    Dois "não dispare" diferentes: {} = trancada, mas sem info (o normal nos
    instantes em que uma rodada pega ou solta a trava); {"ilegivel": True} =
    não deu para saber (erro ao abrir a trava, errno inesperado). Quem chama
    testa `is not None` e usa `descrever` para dizer qual dos dois.

    Testa a trava de verdade (tranca e solta na hora): o `.json` sozinho pode
    ter sobrado de uma rodada que morreu no meio."""
    rel = Path(pasta) / "relatorios"
    trava = rel / NOME_TRAVA
    if not trava.exists():
        return None
    try:
        import msvcrt
    except ImportError:
        return None
    try:
        with _abrir_trava(trava) as f:
            f.seek(0)
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as e:
                if e.errno not in _TRANCADA:
                    return {"ilegivel": True}   # não sei: não dispare
                try:
                    dados = json.loads((rel / NOME_INFO).read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    dados = {}
                return dados if isinstance(dados, dict) else {}
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        return {"ilegivel": True}        # não consegui nem olhar a trava: "livre" seria mentira
    return None


def _abrir_trava(trava: Path):
    return open(trava, "a+b")


def descrever(info: dict | None) -> str:
    if info and info.get("ilegivel"):
        return "não consegui conferir se há outra rodada (trava ilegível)"
    if not info:
        return "uma rodada está em andamento"
    desde = ""
    try:
        desde = f" desde {datetime.fromisoformat(info['inicio']):%d/%m %H:%M}"
    except (KeyError, TypeError, ValueError):
        pass
    return f"rodada em andamento{desde} ({info.get('origem') or 'origem desconhecida'})"


def veredito(rc: int) -> str:
    if rc == 0:
        return "terminou sem alertas"
    if rc == 1:
        return "terminou com ALERTA — veja o resumo"
    if rc == CODIGO_OCUPADA:
        return "não começou: outra rodada já estava em andamento"
    return f"terminou com erro (código {rc})"
