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

QUANDO O PLAYWRIGHT NÃO CONECTA (09/11/2026)
--------------------------------------------
Todo `connect_over_cdp` no Chrome central passa por `conectar`, com prazo de
`PRAZO_CONEXAO` em vez dos 180 s que a pessoa esperava antes de ler
`Timeout 180000ms exceeded`. Se o prazo estoura, `sondar_alvos` abre uma
sessão em cada aba pelo websocket do navegador (o mesmo `Runtime.enable` que o
Playwright manda a cada aba ao conectar) e `ChromeSemResposta` diz, em
português, qual aba não respondeu e o que fazer. A sonda nunca fecha,
recarrega ou navega aba nenhuma: a aba pode ser de outro robô ou da pessoa, e
quem decide fechá-la é gente.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import itertools
import json
import os
import socket
import struct
import subprocess
import time
import urllib.parse
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


def chrome_vivo(a: Acesso, *, abrir=urllib.request.urlopen, prazo: float = 2.0) -> bool:
    """O Chrome deste acesso responde na porta de depuração?"""
    try:
        with abrir(f"{endereco(a)}/json/version", timeout=prazo) as r:
            return getattr(r, "status", 200) == 200 and b"Browser" in r.read()
    except Exception:
        return False


# ------------------------------------------- fechado x travado (09/11/2026)
#
# Em 09/11/2026 o Chrome central parou de responder às 14:04 com a porta 9230
# ABERTA: aceitava a conexão e não respondia nada (janela "não respondendo"
# no Windows). `chrome_vivo` dizia False, e quem chamava `garantir_chrome`
# (robô ou porteiro) abria OUTRO chrome.exe no mesmo perfil. Esse Chrome novo
# não consegue entregar a vez ao travado e fica parado para sempre no aviso
# "o Google Chrome não está respondendo" — um a mais por ciclo. E com 2 s de
# prazo, um Chrome só LENTO (servidor sem memória) também passava por
# fechado: das 40 vezes que o log disse "chrome subiu" em 11 dias, a maioria
# era um Chrome vivo ganhando uma janela em branco a mais.
#
# Agora são três estados. "fechado": a porta não aceita conexão, e só aí se
# sobe Chrome. "mudo": a porta aceita e não responde nem com prazo longo —
# ninguém sobe outro Chrome; quem resolve é o porteiro (`matar_chrome`).

#: Prazo da segunda pergunta, quando a porta está aberta e a primeira (2 s)
#: não teve resposta: separa "lento" de "travado".
PRAZO_LENTO = 10.0


class ChromeTravado(RuntimeError):
    """A porta do Chrome central aceita conexão e não responde. `RuntimeError`
    e não `TimeoutError`, como `ChromeSemResposta`: no app, `TimeoutError`
    quer dizer trava de arquivo ocupada. A mensagem contém "não responde na
    porta" de propósito: é a falha passageira que o `rodar_e_relatar.py`
    repete depois de o porteiro se recuperar."""

    def __init__(self, a: "Acesso"):
        super().__init__(
            f"o Chrome central '{a.nome}' está travado: não responde na porta "
            f"{a.porta} (aceita a conexão e fica calado). O porteiro reinicia "
            f"o Chrome sozinho em alguns minutos.")
        self.acesso = a


def porta_ouvindo(a: Acesso, *, prazo: float = 1.0) -> bool:
    """Alguém aceita conexão na porta de depuração deste acesso? Só abre e
    fecha o socket: não fala CDP nem HTTP."""
    try:
        with socket.create_connection(("127.0.0.1", a.porta), timeout=prazo):
            return True
    except OSError:
        return False


def estado_chrome(a: Acesso, *, vivo=None, ouvindo=None, vivo_lento=None) -> str:
    """"vivo", "fechado" ou "mudo". Lê `chrome_vivo` e `porta_ouvindo` do
    módulo na hora (monkeypatch dos testes)."""
    vivo = vivo or chrome_vivo
    if vivo(a):
        return "vivo"
    if not (ouvindo or porta_ouvindo)(a):
        return "fechado"
    lento = vivo_lento or (lambda ac: chrome_vivo(ac, prazo=PRAZO_LENTO))
    return "vivo" if lento(a) else "mudo"


def pids_do_chrome(a: Acesso, *, rodar=subprocess.run) -> list[int]:
    """Os processos PRINCIPAIS (sem `--type=`) do Chrome deste perfil.
    Conta todos: o travado e os que ficaram presos no aviso "não está
    respondendo" tentando entregar a vez a ele."""
    perfil = str(a.perfil).replace("'", "''")
    script = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
              f"? {{ $_.CommandLine -and $_.CommandLine.Contains('--user-data-dir={perfil}') "
              "-and $_.CommandLine -notmatch '--type=' }} | % { $_.ProcessId }")
    r = rodar(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
              capture_output=True, text=True, timeout=60,
              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return [int(x) for x in (r.stdout or "").split() if x.strip().isdigit()]


def matar_chrome(a: Acesso, *, pids=None, rodar=subprocess.run) -> list[int]:
    """Mata o Chrome DESTE perfil, com os filhos. SÓ o porteiro chama, e só
    com o Chrome mudo há vários ciclos: é a única exceção à regra "ninguém
    fecha o Chrome central" — travado, ele já não serve a ninguém, e sem isto
    tudo fica parado até alguém fechá-lo à mão (03/11, 05/11, 06/11 e
    09/11/2026). Devolve os pids que recebeu ordem de morrer."""
    lista = (pids or pids_do_chrome)(a)
    for pid in lista:
        with contextlib.suppress(Exception):
            rodar(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True,
                  timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return lista


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
                    esperar: float = 20.0, dormir=time.sleep, ouvindo=None,
                    vivo_lento=None) -> str:
    """O endereço CDP do Chrome deste acesso, subindo-o se estiver FECHADO.

    Porta aberta e calada não é "fechado": levanta `ChromeTravado` e não abre
    outro chrome.exe (ver `estado_chrome`).

    `chrome_vivo`, `porta_ouvindo` e `endereco` são lidos do módulo na hora da
    chamada (não capturados em default de argumento) para o monkeypatch dos
    testes valer."""
    vivo = vivo or chrome_vivo

    def estado():
        return estado_chrome(a, vivo=vivo, ouvindo=ouvindo, vivo_lento=vivo_lento)

    agora = estado()
    if agora == "vivo":
        return endereco(a)
    if agora == "mudo":
        raise ChromeTravado(a)
    with trava(a.perfil.parent / f".{a.nome}.chrome.trava", espera=esperar + 30):
        agora = estado()
        if agora == "vivo":               # outro robô subiu enquanto esperávamos
            return endereco(a)
        if agora == "mudo":
            raise ChromeTravado(a)
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


# ------------------------------------------- conectar, e a sonda das abas

#: Prazo do `connect_over_cdp` no Chrome central. Sadio, ele conecta em
#: ~1 s (0,9 s medido em 09/11/2026); os dois estouros de 04/11 e 09/11 só
#: desistiram em 180 s. Quarenta e cinco dá folga a uma máquina lenta com
#: muitas abas e devolve a resposta à pessoa em menos de um minuto.
PRAZO_CONEXAO = 45.0
#: Quanto cada aba tem para responder à sonda (aceitar a sessão, depois o
#: `Runtime.enable`). A aba travada de 09/11 não respondeu em 6 s; as sãs
#: respondem em milissegundos.
PRAZO_ALVO = 3.0
#: Teto da sonda inteira: com várias abas mudas, ela desiste do resto em vez
#: de somar `PRAZO_ALVO` por aba.
PRAZO_SONDA = 20.0
#: O que um Chrome devolve sobre um alvo que ninguém quer ver na lista.
_TIPOS_FORA = {"browser"}
_GUID_WS = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_LOCAIS = {"127.0.0.1", "localhost", "::1"}


class _SemResposta(Exception):
    """O Chrome não respondeu a um pedido dentro do prazo."""


class _CanalCdp:
    """O websocket do NAVEGADOR (não o de uma aba), só com a biblioteca
    padrão: o `websockets` não está no exe, e um import novo de terceiro
    custaria um exe de ~150 MB para todo mundo (ver a regra de ouro do
    CLAUDE.md). Fala só com 127.0.0.1 e só o necessário do RFC 6455: o
    handshake conferido, quadros de texto mascarados na ida, fragmentos, ping
    e fechamento na volta.

    Lê sem perder o lugar: um quadro só sai do buffer quando chegou inteiro,
    então estourar o prazo no meio de um quadro não estraga o próximo pedido."""

    def __init__(self, url_ws: str, prazo: float):
        p = urllib.parse.urlsplit(url_ws)
        if p.scheme != "ws" or p.hostname not in _LOCAIS:
            raise ValueError(f"a sonda só fala com o Chrome local: {url_ws}")
        porta = p.port or 80
        caminho = (p.path or "/") + (f"?{p.query}" if p.query else "")
        self._buf = b""
        self._partes: list[bytes] = []
        self._ids = itertools.count(1)
        self._s = socket.create_connection((p.hostname, porta), timeout=prazo)
        try:
            chave = base64.b64encode(os.urandom(16))
            self._s.sendall(
                (f"GET {caminho} HTTP/1.1\r\nHost: {p.hostname}:{porta}\r\n"
                 "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                 f"Sec-WebSocket-Key: {chave.decode()}\r\n"
                 "Sec-WebSocket-Version: 13\r\n\r\n").encode("ascii"))
            limite = time.monotonic() + prazo
            while b"\r\n\r\n" not in self._buf:
                self._buf += self._receber(limite)
            cab, self._buf = self._buf.split(b"\r\n\r\n", 1)
            linhas = cab.decode("latin-1").split("\r\n")
            campos = {k.strip().lower(): v.strip() for k, v in
                      (x.split(":", 1) for x in linhas[1:] if ":" in x)}
            aceite = base64.b64encode(hashlib.sha1(chave + _GUID_WS).digest()).decode()
            if " 101 " not in f"{linhas[0]} " or campos.get("sec-websocket-accept") != aceite:
                raise ConnectionError(f"o Chrome recusou o handshake: {linhas[0][:80]}")
        except BaseException:
            self._s.close()
            raise

    def _receber(self, limite: float) -> bytes:
        falta = limite - time.monotonic()
        if falta <= 0:
            raise _SemResposta()
        self._s.settimeout(falta)
        try:
            dados = self._s.recv(65536)
        except socket.timeout:
            raise _SemResposta() from None
        if not dados:
            raise ConnectionError("o Chrome fechou a conexão da sonda")
        return dados

    def _quadro_pronto(self):
        """(opcode, fin, dados) do primeiro quadro, se ele já chegou inteiro."""
        b = self._buf
        if len(b) < 2:
            return None
        n, i = b[1] & 0x7F, 2
        if n == 126:
            if len(b) < 4:
                return None
            n, i = struct.unpack(">H", b[2:4])[0], 4
        elif n == 127:
            if len(b) < 10:
                return None
            n, i = struct.unpack(">Q", b[2:10])[0], 10
        mascara = None
        if b[1] & 0x80:                   # servidor não mascara; se mascarar, vale
            if len(b) < i + 4:
                return None
            mascara, i = b[i:i + 4], i + 4
        if len(b) < i + n:
            return None
        dados, self._buf = b[i:i + n], b[i + n:]
        if mascara:
            dados = bytes(x ^ mascara[k % 4] for k, x in enumerate(dados))
        return b[0] & 0x0F, bool(b[0] & 0x80), dados

    def _enviar_quadro(self, op: int, dados: bytes) -> None:
        n = len(dados)
        if n < 126:
            cab = bytes([0x80 | op, 0x80 | n])
        elif n < 65536:
            cab = bytes([0x80 | op, 0x80 | 126]) + struct.pack(">H", n)
        else:
            cab = bytes([0x80 | op, 0x80 | 127]) + struct.pack(">Q", n)
        mascara = os.urandom(4)
        self._s.sendall(cab + mascara +
                        bytes(x ^ mascara[k % 4] for k, x in enumerate(dados)))

    def _mensagem(self, limite: float) -> bytes:
        while True:
            q = self._quadro_pronto()
            if q is None:
                self._buf += self._receber(limite)
                continue
            op, fin, dados = q
            if op == 0x9:                                  # ping → pong
                self._enviar_quadro(0xA, dados)
                continue
            if op == 0xA:
                continue
            if op == 0x8:
                raise ConnectionError("o Chrome fechou a conexão da sonda")
            self._partes.append(dados)
            if fin:
                msg, self._partes = b"".join(self._partes), []
                return msg

    def pedir(self, metodo: str, params: dict | None = None, *,
              sessao: str | None = None, prazo: float = PRAZO_ALVO) -> dict:
        """A resposta (com `result` ou `error`) ao pedido, ou `_SemResposta`.
        Eventos e respostas atrasadas de pedidos anteriores são descartados."""
        mid = next(self._ids)
        msg = {"id": mid, "method": metodo, "params": params or {}}
        if sessao:
            msg["sessionId"] = sessao
        self._enviar_quadro(0x1, json.dumps(msg).encode("utf-8"))
        limite = time.monotonic() + prazo
        while True:
            try:
                obj = json.loads(self._mensagem(limite))
            except ValueError:
                continue
            if isinstance(obj, dict) and obj.get("id") == mid:
                return obj

    def fechar(self) -> None:
        with contextlib.suppress(OSError):
            self._enviar_quadro(0x8, struct.pack(">H", 1000))
        with contextlib.suppress(OSError):
            self._s.close()


@dataclass(frozen=True)
class AlvoSondado:
    """Uma aba (ou worker, ou iframe) do Chrome e o que a sonda viu nela.
    `responde`: True, False (calada no prazo) ou None (sumiu, ou ficou de
    fora pelo teto da sonda)."""
    id: str
    tipo: str
    titulo: str
    url: str
    responde: bool | None
    ms: float
    nota: str = ""


def _sondar_um(canal, info: dict, prazo: float) -> AlvoSondado:
    base = (str(info.get("targetId") or ""), str(info.get("type") or ""),
            str(info.get("title") or ""), str(info.get("url") or ""))
    inicio = time.monotonic()

    def ms():
        return (time.monotonic() - inicio) * 1000

    try:
        r = canal.pedir("Target.attachToTarget",
                        {"targetId": base[0], "flatten": True}, prazo=prazo)
    except _SemResposta:
        return AlvoSondado(*base, False, ms(), "não aceitou a sessão")
    sessao = (r.get("result") or {}).get("sessionId")
    if not sessao:
        erro = (r.get("error") or {}).get("message") or "sem sessão"
        return AlvoSondado(*base, None, ms(), f"sumiu ou recusou: {erro}"[:120])
    try:
        # O que o Playwright manda a cada aba ao conectar: é exatamente o
        # pedido que deixou a aba travada de 09/11 sem resposta. Não roda JS
        # na página, e destacar a sessão desliga o domínio de novo.
        canal.pedir("Runtime.enable", sessao=sessao, prazo=prazo)
        responde, nota = True, ""
    except _SemResposta:
        responde, nota = False, "não respondeu ao Runtime.enable"
    gasto = ms()
    with contextlib.suppress(_SemResposta, OSError):
        canal.pedir("Target.detachFromTarget", {"sessionId": sessao},
                    prazo=min(1.0, prazo))
    return AlvoSondado(*base, responde, gasto, nota)


def sondar_alvos(endereco_cdp: str, *, prazo_alvo: float = PRAZO_ALVO,
                 prazo_total: float = PRAZO_SONDA, abrir=urllib.request.urlopen,
                 canal=_CanalCdp) -> list[AlvoSondado]:
    """Pergunta a cada alvo do Chrome, pelo websocket do NAVEGADOR, se ele
    responde. Uma sessão por alvo (`Target.attachToTarget` com `flatten`),
    um `Runtime.enable` com prazo curto, e a sessão destacada.

    Só pergunta: nunca fecha, recarrega nem navega. Levanta `OSError`/
    `ConnectionError`/`ValueError` se nem o navegador responde."""
    with abrir(f"{endereco_cdp}/json/version", timeout=prazo_alvo) as r:
        url_ws = json.loads(r.read())["webSocketDebuggerUrl"]
    c = canal(url_ws, prazo_alvo)
    try:
        try:
            r = c.pedir("Target.getTargets", prazo=prazo_alvo)
        except _SemResposta:
            raise ConnectionError("o Chrome não devolveu a lista de abas") from None
        infos = [t for t in (r.get("result") or {}).get("targetInfos") or []
                 if isinstance(t, dict) and t.get("type") not in _TIPOS_FORA]
        limite = time.monotonic() + prazo_total
        saida = []
        for t in infos:
            if time.monotonic() >= limite:
                saida.append(AlvoSondado(
                    str(t.get("targetId") or ""), str(t.get("type") or ""),
                    str(t.get("title") or ""), str(t.get("url") or ""),
                    None, 0.0, "não sondado (teto da sonda)"))
                continue
            saida.append(_sondar_um(c, t, prazo_alvo))
        return saida
    finally:
        c.fechar()


def _host(url: str) -> str:
    """Só o host: o caminho da URL pode carregar id de lançamento."""
    try:
        p = urllib.parse.urlsplit(url)
    except ValueError:
        return ""
    if p.scheme in ("http", "https"):
        return p.hostname or ""
    return f"{p.scheme}:" if p.scheme else ""


def _curto(texto: str, n: int = 60) -> str:
    texto = " ".join(texto.split())
    return texto if len(texto) <= n else texto[:n - 1] + "…"


def _nome_do_alvo(a: AlvoSondado) -> str:
    nome = f"“{_curto(a.titulo or '(sem título)')}”"
    host = _host(a.url)
    return f"{nome} ({host})" if host else nome


def recado_sem_resposta(endereco_cdp: str, prazo: float, alvos, erro_sonda=None) -> str:
    """O que a pessoa lê quando o Playwright não conectou no prazo."""
    porta = urllib.parse.urlsplit(endereco_cdp).port
    inicio = (f"O Chrome do app (porta {porta}) não respondeu em {prazo:.0f} s "
              "para o robô conectar.")
    fim = ("Não feche o Chrome inteiro: as abas dos outros robôs e o login "
           "do ERP estão nele.")
    if alvos is None:
        motivo = f" ({erro_sonda})" if erro_sonda else ""
        return (f"{inicio} E não consegui conferir as abas{motivo}. Espere um "
                "ou dois minutos e tente de novo; se continuar, feche abas e "
                f"programas que não estiver usando (pouca memória deixa o "
                f"Chrome lento). {fim}")
    mudas = [a for a in alvos if a.responde is False]
    if not mudas:
        return (f"{inicio} Conferi agora e todas as {len(alvos)} abas respondem "
                "— tente de novo. Se repetir, feche abas e programas que não "
                "estiver usando (pouca memória deixa o Chrome lento).")
    nomes = ", ".join(_nome_do_alvo(a) for a in mudas[:3])
    if len(mudas) > 3:
        nomes += f" e mais {len(mudas) - 3}"
    qual = "Esta aba não responde" if len(mudas) == 1 else "Estas abas não respondem"
    return (f"{inicio} {qual}: {nomes}. Se a aba for sua, feche-a e tente de "
            "novo. Se for de um robô, espere um ou dois minutos (ela costuma "
            f"voltar sozinha) e tente de novo. {fim}")


class ChromeSemResposta(RuntimeError):
    """O `connect_over_cdp` estourou o prazo; a mensagem já vem pronta para a
    pessoa. `alvos` é o que a sonda viu (None se ela não rodou) e
    `relatorio()` o detalhe para o diagnóstico.

    `RuntimeError` e não `TimeoutError` de propósito: no app,
    `except TimeoutError` quer dizer "a trava de arquivo estourou" e vira
    "outro robô está entrando no ERP" — o recado errado."""

    def __init__(self, endereco_cdp: str, prazo: float, alvos=None, erro_sonda=None):
        super().__init__(recado_sem_resposta(endereco_cdp, prazo, alvos, erro_sonda))
        self.endereco = endereco_cdp
        self.prazo = prazo
        self.alvos = alvos
        self.erro_sonda = erro_sonda

    def relatorio(self) -> str:
        linhas = [f"connect_over_cdp estourou {self.prazo:.0f} s em {self.endereco}"]
        if self.alvos is None:
            linhas.append(f"  sonda não rodou: {self.erro_sonda!r}")
        for a in self.alvos or []:
            estado = {True: "responde", False: "não responde",
                      None: "sem resposta conhecida"}[a.responde]
            linhas.append(f"  {a.tipo:<15} {estado:<22} {a.ms:7.0f} ms  "
                          f"{_nome_do_alvo(a)}{'  — ' + a.nota if a.nota else ''}")
        return "\n".join(linhas)


def _estourou(e: BaseException) -> bool:
    """É o estouro de prazo do Playwright? Pelo NOME na MRO, como o
    `widgets.explicar_erro`: este arquivo não importa o Playwright no topo."""
    return any(c.__name__ == "TimeoutError" for c in type(e).__mro__)


def conectar(pw, endereco_cdp: str, *, prazo: float = PRAZO_CONEXAO, sondar=None):
    """`pw.chromium.connect_over_cdp` com prazo curto. No estouro, sonda as
    abas e levanta `ChromeSemResposta` com o recado; qualquer outro erro
    passa como veio. `sondar_alvos` é lido do módulo na hora (monkeypatch)."""
    try:
        return pw.chromium.connect_over_cdp(endereco_cdp, timeout=prazo * 1000)
    except Exception as e:
        if not _estourou(e):
            raise
        sondar = sondar or sondar_alvos
        alvos, erro_sonda = None, None
        try:
            alvos = sondar(endereco_cdp)
        except Exception as s:                    # noqa: BLE001 — vira recado
            erro_sonda = s
        raise ChromeSemResposta(endereco_cdp, prazo, alvos, erro_sonda) from e


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
            self.browser = conectar(self._pw, self._garantir(self.acesso))
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
