# -*- coding: utf-8 -*-
"""A faxina das abas esquecidas no Chrome central (06/11/2026).

POR QUE EXISTE
--------------
Cada robô abre a sua aba no Chrome central e a fecha no `finally`. Robô
MORTO não chega no `finally`: o robô da fila mata quem passa de 10 min, o
Agendador mata quem passa do prazo, e "Finalizar tarefa" é TerminateProcess.
Com `connect_over_cdp` a aba NÃO morre com o processo — fica no Chrome para
sempre. Em 06/11/2026 eram 8 abas, só 1 com dono (o porteiro); o servidor
estava com 650 MB livres de 8 GB e o Chrome central parou de responder às
09:31 e às 09:44 ("não abriu a porta 9230 em 20 s").

DUAS REGRAS, as duas conservadoras
----------------------------------
1. Aba REGISTRADA por um robô (`registrar`, um arquivo por aba em
   `<pasta central>/abas-robos/`) cujo processo morreu: fecha na hora. É o
   caso exato — o dono sumiu, ninguém mais vai usar.
2. Aba de NINGUÉM parada no mesmo endereço "vazio" por mais de `LIMITE`
   (15 min, uns 7 ciclos do porteiro): `about:blank` sempre; a tela de LOGIN
   só com o porteiro logado neste ciclo — aí a sessão é boa e a aba no login
   é sobra de antes da queda. Com a sessão FORA, a aba no login pode ser o
   dono entrando, e não se toca nela.
Nunca entram: as abas do próprio porteiro e a do login principal
(`.<nome>.login.aba`). Nenhuma página com conteúdo de trabalho é fechada
pela regra 2 — robô vivo nunca fica 15 min em `about:blank`.

Só fala HTTP com o Chrome (`/json/list`, `/json/close/<id>`): não roda JS em
aba de ninguém e não precisa de Playwright.
"""
from __future__ import annotations

import contextlib
import json
import os
import time
import urllib.request
from pathlib import Path

from erp import central

#: Quanto uma aba de ninguém pode ficar parada em branco/no login.
LIMITE = 15 * 60
#: Pasta (dentro da pasta central) onde cada robô anota a aba que abriu.
PASTA_REGISTRO = "abas-robos"


def _parada(url: str) -> str | None:
    """'branco', 'login' ou None (aba com trabalho, não é da faxina)."""
    u = (url or "").strip().lower()
    if u in ("", "about:blank"):
        return "branco"
    if "#/login" in u:
        return "login"
    return None


def listar_abas(a, *, abrir=urllib.request.urlopen) -> list[dict]:
    with abrir(f"{central.endereco(a)}/json/list", timeout=10) as r:
        return [t for t in json.loads(r.read().decode("utf-8"))
                if t.get("type") == "page"]


def fechar_aba(a, alvo: str, *, abrir=urllib.request.urlopen) -> None:
    with abrir(f"{central.endereco(a)}/json/close/{alvo}", timeout=10) as r:
        r.read()


def aba_do_login_principal(a) -> str | None:
    """O targetId que o login principal deixou parado (ver login_principal)."""
    with contextlib.suppress(Exception):
        return (Path(a.perfil).parent / f".{a.nome}.login.aba").read_text(
            encoding="utf-8").strip() or None
    return None


# ------------------------------------------------ registro das abas dos robôs


def pasta_registro(pasta: Path | None = None) -> Path | None:
    pasta = pasta if pasta is not None else central.pasta_central()
    return None if pasta is None else Path(pasta) / PASTA_REGISTRO


def registros(pasta_reg: Path | None) -> list[tuple[Path, int, str, int]]:
    """(arquivo, pid, aba, porta) de cada registro legível."""
    saida = []
    if pasta_reg is None or not pasta_reg.is_dir():
        return saida
    for arq in pasta_reg.glob("*.json"):
        with contextlib.suppress(Exception):
            d = json.loads(arq.read_text(encoding="utf-8"))
            saida.append((arq, int(d["pid"]), str(d["aba"]), int(d.get("porta") or 0)))
    return saida


# ------------------------------------------------------------------ a faxina


class Faxina:
    """Guarda, entre os ciclos, desde quando cada aba de ninguém está parada."""

    def __init__(self, *, listar=listar_abas, fechar=fechar_aba,
                 pid_vivo=central.pid_vivo, pasta_reg=None,
                 relogio=time.monotonic, limite=LIMITE):
        self._listar, self._fechar = listar, fechar
        self._pid_vivo, self._relogio, self._limite = pid_vivo, relogio, limite
        self._pasta_reg = pasta_reg if pasta_reg is not None else pasta_registro()
        self._vistas: dict[str, dict[str, tuple[str, float]]] = {}

    def passar(self, a, *, minhas=(), logado: bool) -> list[str]:
        """Um passo da faxina no Chrome de `a`. Devolve uma linha por aba
        fechada (para o log). Erro ao fechar UMA aba não para as outras."""
        abas = self._listar(a)
        abertas = {t["id"]: t.get("url", "") for t in abas if t.get("id")}
        poupar = set(minhas)
        principal = aba_do_login_principal(a)
        if principal:
            poupar.add(principal)
        fechadas: list[str] = []

        # 1) abas registradas por robô que já morreu
        registradas = set()
        for arq, pid, aba, porta in registros(self._pasta_reg):
            if porta and porta != a.porta:
                continue
            if self._pid_vivo(pid):
                registradas.add(aba)
                continue
            if aba in abertas and aba not in poupar:
                try:
                    self._fechar(a, aba)
                    fechadas.append(f"aba do robô {pid} (morto): {abertas.pop(aba) or 'about:blank'}")
                except Exception as e:
                    fechadas.append(f"aba do robô {pid}: não fechou ({e!r})")
                    continue
            with contextlib.suppress(OSError):
                arq.unlink()

        # 2) abas de ninguém paradas em branco / no login
        agora = self._relogio()
        antes = self._vistas.get(a.nome, {})
        novas: dict[str, tuple[str, float]] = {}
        for alvo, url in abertas.items():
            tipo = _parada(url)
            if alvo in poupar or alvo in registradas or tipo is None:
                continue
            if tipo == "login" and not logado:
                continue
            url0, desde = antes.get(alvo, (url, agora))
            if url0 != url:
                desde = agora
            if agora - desde < self._limite:
                novas[alvo] = (url, desde)
                continue
            try:
                self._fechar(a, alvo)
                minutos = int((agora - desde) // 60)
                fechadas.append(f"aba esquecida ({tipo}, {minutos} min): {url or 'about:blank'}")
            except Exception as e:
                novas[alvo] = (url, desde)
                fechadas.append(f"aba esquecida: não fechou ({e!r})")
        self._vistas[a.nome] = novas
        return fechadas


# ------------------------------------------- o lado do robô (copiável)


def registrar(aba: str, porta: int, pasta: Path | None = None, pid: int | None = None) -> Path | None:
    """Anota que o processo `pid` abriu a aba `aba`. Quem fecha a aba apaga
    o arquivo (`desregistrar`); se o processo morrer antes, a faxina do
    porteiro fecha a aba. Falhar aqui nunca impede o robô de trabalhar."""
    reg = pasta_registro(pasta)
    if reg is None:
        return None
    pid = os.getpid() if pid is None else pid
    with contextlib.suppress(Exception):
        reg.mkdir(parents=True, exist_ok=True)
        arq = reg / f"{pid}-{aba}.json"
        arq.write_text(json.dumps({"pid": pid, "aba": aba, "porta": porta}), encoding="utf-8")
        return arq
    return None


def desregistrar(arq: Path | None) -> None:
    if arq is not None:
        with contextlib.suppress(OSError):
            arq.unlink()
