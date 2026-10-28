# -*- coding: utf-8 -*-
"""O Chrome central: um Chrome por acesso do ERP, dono da sessão.

POR QUE EXISTE
--------------
O ERP aceita UMA sessão por usuário: todo `POST /users/login` derruba a
anterior. Mas várias abas do MESMO perfil do Chrome dividem a sessão e
convivem. Então quem faz login é um só (o porteiro, `erp/porteiro.py`, pela
tela), e cada robô abre a SUA aba nesse Chrome em vez de logar.

Este módulo só sabe ONDE está cada acesso e COMO subir o Chrome uma vez. Não
importa Playwright no topo (quem conecta é `AbaCentral`, mais abaixo, que
importa tarde) e não importa nada do app — o água e energia copia este arquivo.

LIGAR E DESLIGAR
----------------
Ligado quando existe `<pasta central>/acessos.json` com o acesso pedido.
`MC_CENTRAL=<pasta>` troca a pasta; `MC_CENTRAL=off` desliga tudo, e o app
volta a ser o de antes.

    {"acessos": [{"nome": "principal", "perfil": "perfis/principal",
                  "porta": 9230, "credencial": "principal.login.dat"}]}

Caminho relativo é relativo à pasta central. A porta de depuração ouve SÓ em
127.0.0.1: quem alcança a porta controla o navegador logado.
"""
from __future__ import annotations

import contextlib
import json
import os
import subprocess
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

PASTA_PADRAO = Path(r"C:\AUTOMAÇÕES MAIS CONTROLE\_central")
ARQUIVO = "acessos.json"

#: Destacado do processo que o sobe: o Chrome central tem de sobreviver ao
#: robô que por acaso o ligou.
_DESTACADO = 0x00000008 | 0x00000200   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


@dataclass(frozen=True)
class Acesso:
    nome: str
    perfil: Path
    porta: int
    credencial: Path | None = None


def pasta_central() -> Path | None:
    """A pasta dos acessos, ou None quando `MC_CENTRAL=off`."""
    valor = (os.environ.get("MC_CENTRAL") or "").strip()
    if valor.lower() == "off":
        return None
    return Path(valor) if valor else PASTA_PADRAO


def _caminho(pasta: Path, valor) -> Path | None:
    if not valor:
        return None
    p = Path(valor)
    return p if p.is_absolute() else pasta / p


def carregar_acessos(pasta: Path | None = None) -> dict[str, Acesso]:
    pasta = pasta or pasta_central()
    if pasta is None:
        return {}
    arq = pasta / ARQUIVO
    if not arq.exists():
        return {}
    try:
        # utf-8-sig: o Bloco de Notas grava BOM, e no servidor o arquivo é
        # criado à mão. Sem isso, o BOM vira "JSON quebrado".
        dados = json.loads(arq.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ValueError(f"não consegui ler {arq}: {e}") from e
    # Formato errado tem de dizer QUAL arquivo, como o JSON quebrado: quem
    # chama traduz ValueError em recado; AttributeError/TypeError escapariam.
    if not isinstance(dados, dict):
        raise ValueError(f"{arq}: o conteúdo tem de ser um objeto "
                         '{"acessos": [...]}')
    lista = dados.get("acessos") or []
    if not isinstance(lista, list):
        raise ValueError(f'{arq}: "acessos" tem de ser uma lista')
    acessos: dict[str, Acesso] = {}
    portas: set[int] = set()
    for item in lista:
        if not isinstance(item, dict):
            raise ValueError(f"{arq}: cada acesso tem de ser um objeto, "
                             f"veio {type(item).__name__}")
        nome = str(item.get("nome") or "").strip()
        porta = item.get("porta")
        if not nome:
            raise ValueError(f"{arq}: acesso sem nome")
        if nome in acessos:
            raise ValueError(f"{arq}: nome '{nome}' repetido")
        if not isinstance(porta, int):
            raise ValueError(f"{arq}: acesso '{nome}' sem porta")
        if not 1024 <= porta <= 65535:
            raise ValueError(f"{arq}: porta {porta} fora de 1024-65535")
        if porta in portas:
            raise ValueError(f"{arq}: porta {porta} repetida")
        portas.add(porta)
        acessos[nome] = Acesso(nome, _caminho(pasta, item.get("perfil") or nome),
                               porta, _caminho(pasta, item.get("credencial")))
    return acessos


def acesso(nome: str = "principal", pasta: Path | None = None) -> Acesso | None:
    return carregar_acessos(pasta).get(nome)


def ligado(nome: str = "principal", pasta: Path | None = None) -> bool:
    return acesso(nome, pasta) is not None


def endereco(a: Acesso) -> str:
    return f"http://127.0.0.1:{a.porta}"


def chrome_vivo(a: Acesso, *, abrir=urllib.request.urlopen) -> bool:
    """O Chrome deste acesso responde na porta de depuração?"""
    try:
        with abrir(f"{endereco(a)}/json/version", timeout=2) as r:
            return getattr(r, "status", 200) == 200 and b"Browser" in r.read()
    except Exception:
        return False


def localizar_chrome() -> str:
    candidatos = [
        Path(os.environ.get(v, "")) / "Google" / "Chrome" / "Application" / "chrome.exe"
        for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")
        if os.environ.get(v)
    ]
    for c in candidatos:
        if c.exists():
            return str(c)
    raise FileNotFoundError("Chrome não encontrado — instale o Google Chrome.")


def argumentos_chrome(exe: str, a: Acesso) -> list[str]:
    return [exe,
            f"--remote-debugging-port={a.porta}",
            "--remote-debugging-address=127.0.0.1",
            f"--user-data-dir={a.perfil}",
            "--lang=pt-BR",
            "--no-first-run", "--no-default-browser-check",
            "--disable-popup-blocking", "--start-maximized",
            "about:blank"]


def pid_vivo(pid: int) -> bool:
    """O processo `pid` existe? Na dúvida, "sim" (nunca rouba trava de vivo).

    No Windows NUNCA `os.kill(pid, 0)`: lá o sinal que não é Ctrl+C/Break
    vira `TerminateProcess` — mataria o dono da trava. Pergunta-se ao Windows
    pelo `OpenProcess` + `GetExitCodeProcess`."""
    if pid <= 0:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True
    try:
        import ctypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.OpenProcess.restype = ctypes.c_void_p
        h = k32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
        if not h:
            # 87 = parâmetro inválido: não existe processo com esse pid.
            return ctypes.get_last_error() != 87
        try:
            codigo = ctypes.c_ulong()
            if not k32.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(codigo)):
                return True
            return codigo.value == 259                   # STILL_ACTIVE
        finally:
            k32.CloseHandle(ctypes.c_void_p(h))
    except Exception:
        return True


def _dono_morto(caminho: Path, pid_vivo_fn) -> bool:
    """A trava guarda "<pid> <token>"; True só com pid legível e morto."""
    try:
        pid = int(caminho.read_bytes().split()[0])
    except (OSError, ValueError, IndexError):
        return False
    return not pid_vivo_fn(pid)


@contextlib.contextmanager
def trava(caminho: Path, *, espera: float = 60.0, velha: float = 120.0,
          pid_vivo=None):
    """Trava entre processos por arquivo exclusivo. Arquivo mais velho que
    `velha` segundos é de processo que morreu no meio e é recuperado — e,
    desde 28/10/2026, também o de pid que não existe mais, na hora (quem
    espera menos que `velha` não fica barrado por um processo morto).
    Arquivo sem pid legível nunca é roubado antes de `velha`.

    O arquivo guarda o pid e um token único de quem o criou. Quem segurou a
    trava além de `velha` pode tê-la perdido para outro processo; ao sair, só
    apaga o arquivo se o conteúdo ainda for o seu, e assim não solta a trava
    do outro."""
    pid_vivo_fn = pid_vivo or globals()["pid_vivo"]
    caminho.parent.mkdir(parents=True, exist_ok=True)
    limite = time.monotonic() + espera
    meu = f"{os.getpid()} {os.urandom(8).hex()}".encode()
    while True:
        try:
            fd = os.open(str(caminho), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, meu)
            os.close(fd)
            break
        except (FileExistsError, PermissionError) as erro:
            # No Windows, arquivo em "delete-pending" (o outro processo acabou
            # de apagar) faz o O_EXCL levantar PermissionError, não
            # FileExistsError: é a mesma corrida, e se espera do mesmo jeito.
            try:
                if (time.time() - caminho.stat().st_mtime > velha
                        or _dono_morto(caminho, pid_vivo_fn)):
                    caminho.unlink()
                    continue
            except FileNotFoundError:
                # A trava sumiu: tente de novo já — mas só se o erro era
                # "existe". PermissionError com arquivo ausente é permissão
                # permanente (pasta, ACL, antivírus): sem prazo e sem sleep
                # seria laço a 100% de CPU ignorando `espera`.
                if isinstance(erro, FileExistsError):
                    continue
            except OSError:
                pass                      # antivírus/indexador: cai no prazo
            if time.monotonic() >= limite:
                if isinstance(erro, PermissionError) and not caminho.exists():
                    raise TimeoutError(
                        f"não foi possível criar a trava (permissão negada) "
                        f"em {espera:.0f} s: {caminho}") from erro
                raise TimeoutError(f"trava ocupada há mais de {espera:.0f} s: {caminho}")
            time.sleep(0.1)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            if caminho.read_bytes() == meu:
                caminho.unlink()


def garantir_chrome(a: Acesso, *, popen=subprocess.Popen, vivo=None, exe=None,
                    esperar: float = 20.0, dormir=time.sleep) -> str:
    """O endereço CDP do Chrome deste acesso, subindo-o se estiver fechado.

    `chrome_vivo` e `endereco` são lidos do módulo na hora da chamada (não
    capturados em default de argumento) para o monkeypatch dos testes valer."""
    vivo = vivo or chrome_vivo
    if vivo(a):
        return endereco(a)
    with trava(a.perfil.parent / f".{a.nome}.chrome.trava", espera=esperar + 30):
        if vivo(a):                       # outro robô subiu enquanto esperávamos
            return endereco(a)
        a.perfil.mkdir(parents=True, exist_ok=True)
        # Chrome FECHADO e trava na mão: a única hora segura de apagar o
        # histórico. O Chrome 152 morre no 1º download de um perfil que já
        # baixou (medido em 08/09/2026; ver `util.limpar_historico_de_downloads`
        # no app) — e quem sobe pode ser qualquer robô, não só o porteiro.
        # Repetido aqui, e não importado, porque este arquivo não importa nada
        # do app (o água e energia o copia).
        for nome in ("History", "History-journal"):
            with contextlib.suppress(OSError):
                (a.perfil / "Default" / nome).unlink()
        popen(argumentos_chrome(exe or localizar_chrome(), a),
              creationflags=_DESTACADO, close_fds=True)
        inicio = time.monotonic()
        passos = 0
        while passos < esperar * 4:
            if vivo(a):
                return endereco(a)
            dormir(0.25)
            passos += 1
            if time.monotonic() - inicio > esperar + 5:
                break
    raise TimeoutError(f"o Chrome central '{a.nome}' não abriu a porta {a.porta} "
                       f"em {esperar:.0f} s")


class AbaCentral:
    """Uma aba PRÓPRIA no Chrome central, para um robô.

    Na saída fecha só o que abriu e desconecta. Nunca `ctx.close()` nem
    `browser.close()`: com `connect_over_cdp`, fechar o navegador fecharia o
    Chrome de todo mundo — as abas dos outros robôs e a sessão do porteiro.

    Playwright sync: use da MESMA thread que entrou no `with`."""

    def __init__(self, a: Acesso, *, pw=None, garantir=None):
        self.acesso = a
        self._pw_externo = pw
        self._garantir = garantir or garantir_chrome
        self._pw = None
        self.browser = self.ctx = self.page = None
        self._minhas: list = []

    def __enter__(self):
        if self._pw_externo is not None:
            self._pw = self._pw_externo
        else:
            from playwright.sync_api import sync_playwright   # tarde: módulo leve
            self._pw = sync_playwright().start()
        try:
            self.browser = self._pw.chromium.connect_over_cdp(self._garantir(self.acesso))
            self.ctx = self.browser.contexts[0]
            self.page = self.nova_aba()
        except Exception:
            self._pw.stop()
            raise
        return self

    def nova_aba(self):
        p = self.ctx.new_page()
        self._minhas.append(p)
        return p

    def __exit__(self, *exc):
        try:
            for p in self._minhas:
                with contextlib.suppress(Exception):
                    if not p.is_closed():
                        p.close()
        finally:
            self._pw.stop()
        return False
