# Porteiro do ERP — Plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um Chrome central por acesso do ERP, dono da sessão. Todo robô (app e
água e energia) conecta nele em vez de fazer login, e duas rotinas rodam ao
mesmo tempo sem uma derrubar a outra.

**Architecture:** `erp/central.py` lê `acessos.json` e sobe o Chrome real com
`--remote-debugging-port` em 127.0.0.1, uma vez só (com trava). O robô que
precisa de tela abre uma aba própria nesse Chrome por `connect_over_cdp`.
O robô que só faz pedidos usa `erp/sessao_pagina.py`: uma aba própria, numa
thread própria, que captura os cabeçalhos do tráfego da tela e faz `fetch` de
dentro da página. Quem faz login, sempre pela tela, é o `erp/porteiro.py`
(com o `MCClient` em modo central), protegido por trava. Com `acessos.json`
ausente ou `MC_CENTRAL=off`, tudo continua exatamente como hoje.

**Tech Stack:** Python 3.11 (alvo do exe), Playwright sync (`connect_over_cdp`),
Chrome real, stdlib (`urllib`, `subprocess`, `threading`, `queue`), pytest.

**Spec:** `docs/superpowers/plans/2026-10-14-sistema-no-servidor-roteiro.md`
(decisões do dono 1–6) e `docs/ERP-CLIENTES.md` (o inventário de quem fala
com o ERP).

## Global Constraints

- **Nenhum login HTTP no modo central.** Com o central ligado, nenhum caminho
  chama `POST /users/login`: `erp.Sessao.logar`, `SessaoApi.logar` e o
  `SessaoAPI` do água e energia passam pela página. (Regra do dono: "sempre
  pelo chrome do app".)
- **Robô nunca fecha o Chrome central.** Na saída, fecha só as abas que ele
  mesmo abriu e desconecta (`pw.stop()`). Nunca chama `ctx.close()` nem
  `browser.close()` no modo central.
- **Desligado = idêntico a hoje.** Sem `acessos.json`, ou com
  `MC_CENTRAL=off`, nenhum comportamento muda. Os testes atuais continuam
  verdes sem edição.
- Python **3.11**: rodar `vermin --target=3.11 --violations` nos arquivos
  novos. `ruff check --select E9,F .` limpo.
- **Nenhum import novo de submódulo da stdlib** que o exe ainda não tenha;
  conferir com `tests/test_imports_do_motor.py`. `subprocess`, `threading`,
  `queue`, `urllib.request` e `json` já existem no app.
- **Porta de depuração só em `127.0.0.1`.** Nunca `0.0.0.0` nem o IP do
  Tailscale: quem tem a porta controla o navegador logado.
- **Testes não abrem navegador nem tocam rede.** Dublês de Playwright,
  `urlopen` e `Popen`. A prova ao vivo é a Tarefa 8, feita pelo controlador.
- Repositório **público**: nada de e-mail real, senha, nome de fornecedor,
  CPF ou CNPJ, nem em teste nem em comentário. Caminhos de exemplo com
  `fulano@exemplo.test`.
- Pasta central padrão: `C:\AUTOMAÇÕES MAIS CONTROLE\_central`, trocável por
  `MC_CENTRAL=<pasta>`; `MC_CENTRAL=off` desliga.
- Textos para a pessoa, em português simples. Caminhos exibidos com "/".

## Review Focus

1. **Robô termina e o Chrome central fecha junto.** Esperado: o Chrome e as
   abas dos outros robôs continuam abertos. Teste na Tarefa 2 (o dublê
   registra `close` e o teste exige que não haja nenhum) e prova ao vivo na
   Tarefa 8.
2. **Dois robôs começam juntos com o Chrome desligado.** Esperado: um Chrome
   só. Teste na Tarefa 1, com `Popen` contado e duas threads.
3. **Cabeçalho capturado venceu (401 do `legacy-api`).** Esperado: recarrega a
   aba, recaptura e repete uma vez; no segundo 401, `SessaoRecusada` com
   recado claro. Teste na Tarefa 3.
4. **Sessão caiu (tela de login) enquanto um robô espera.** Esperado: depois
   do prazo, `ErpErro` dizendo que o porteiro precisa entrar, em vez de
   travar para sempre. Teste na Tarefa 3.
5. **`pedir` chamado de duas threads ao mesmo tempo.** Esperado: os dois
   recebem a resposta certa e nenhum toca o Playwright fora da thread dona.
   Teste na Tarefa 3.

## Modelo por tarefa

| Tarefa | Modelo | Por quê |
|---|---|---|
| 1, 2, 4, 6, 7 | sonnet | mecânicas, com o código no plano |
| 3, 5 | opus | concorrência e o coração do app (`MCClient`) |
| 8, 9 | controlador | prova ao vivo e passo a passo; tocam no ERP |

## Mapa de arquivos

App (`gdiascabral/comprovantes-mais-controle`, branch `codigo/porteiro-do-erp`):
- Criar `erp/central.py`: acessos, Chrome central e aba própria.
- Criar `erp/sessao_pagina.py`: `SessaoPelaPagina`, pedidos pela aba numa
  thread dona.
- Criar `erp/porteiro.py`: CLI `python -m erp.porteiro`.
- Modificar `erp/sessao.py`: `Sessao.logar` desvia para o central.
- Modificar `erp/__init__.py`: exportar os nomes novos.
- Modificar `conciliacao/erp/api.py`: `SessaoApi.logar` não exige
  credencial no modo central.
- Modificar `anexar/mc_client.py`: modo central no `__enter__`, `__exit__`,
  `_nova_aba` e `_tentar_entrar`.
- Criar `ferramentas/porteiro/registrar_porteiro.ps1`: tarefa "ao entrar".
- Criar `docs/PORTEIRO.md`: o que é, como ligar e desligar, servidor.
- Testes: `tests/test_erp_central.py`, `tests/test_erp_sessao_pagina.py`,
  `tests/test_erp_porteiro.py`; acréscimos em `tests/test_erp.py` e
  `tests/test_mc_client_central.py`.

Água e energia (`gdiascabral/agua-energia`, branch `codigo/porteiro-do-erp`):
- Criar `coletor/mc_central.py`: cópia de `erp/central.py`.
- Modificar `coletor/lancar_mc.py`: `SessaoMC` em modo central;
  `nova_sessao()` devolve `SessaoMC` no modo central.
- Modificar `coletor/erp_api.py`: fábrica `nova_sessao()`.
- Modificar `coletor/auditar_descricoes.py:1070,1106` e
  `coletor/corrigir_descricoes.py:733`: usar `erp_api.nova_sessao()`.
- Testes: `tests/test_mc_central.py`, `tests/test_sessao_central.py`.

---

### Task 1: `erp/central.py` — acessos e Chrome central

**Files:**
- Create: `erp/central.py`
- Test: `tests/test_erp_central.py`

**Interfaces:**
- Produces:
  - `PASTA_PADRAO: Path`
  - `pasta_central() -> Path | None`, que devolve None quando `MC_CENTRAL=off`
  - `@dataclass(frozen=True) Acesso(nome: str, perfil: Path, porta: int, credencial: Path | None = None)`
  - `carregar_acessos(pasta: Path | None = None) -> dict[str, Acesso]`
  - `acesso(nome: str = "principal", pasta: Path | None = None) -> Acesso | None`
  - `ligado(nome: str = "principal", pasta: Path | None = None) -> bool`
  - `endereco(a: Acesso) -> str`
  - `chrome_vivo(a: Acesso, *, abrir=urllib.request.urlopen) -> bool`
  - `localizar_chrome() -> str`
  - `argumentos_chrome(exe: str, a: Acesso) -> list[str]`
  - `trava(caminho: Path, *, espera: float = 60.0, velha: float = 120.0)`, um context manager
  - `garantir_chrome(a: Acesso, *, popen=subprocess.Popen, vivo=None, exe=None, esperar: float = 20.0, dormir=time.sleep) -> str`

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_erp_central.py
# -*- coding: utf-8 -*-
"""O Chrome central: quem lê o acessos.json e quem sobe o Chrome UMA vez.

Nada aqui abre navegador nem toca rede: `Popen` e `urlopen` são dublês."""
import json
import threading
import time

import pytest

from erp import central


def _escrever(pasta, acessos):
    (pasta / "acessos.json").write_text(
        json.dumps({"acessos": acessos}), encoding="utf-8")


@pytest.fixture
def pasta(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_CENTRAL", str(tmp_path))
    return tmp_path


def test_sem_arquivo_fica_desligado(pasta):
    assert central.carregar_acessos() == {}
    assert central.ligado() is False


def test_mc_central_off_desliga_mesmo_com_arquivo(pasta, monkeypatch):
    _escrever(pasta, [{"nome": "principal", "perfil": str(pasta / "p"), "porta": 9230}])
    monkeypatch.setenv("MC_CENTRAL", "off")
    assert central.pasta_central() is None
    assert central.ligado() is False


def test_le_os_acessos(pasta):
    _escrever(pasta, [
        {"nome": "principal", "perfil": str(pasta / "p1"), "porta": 9230,
         "credencial": str(pasta / "principal.login.dat")},
        {"nome": "robo2", "perfil": "perfis/robo2", "porta": 9231},
    ])
    acessos = central.carregar_acessos()
    assert set(acessos) == {"principal", "robo2"}
    assert acessos["principal"].porta == 9230
    assert acessos["principal"].credencial.name == "principal.login.dat"
    # caminho relativo é relativo à pasta central
    assert acessos["robo2"].perfil == pasta / "perfis" / "robo2"
    assert acessos["robo2"].credencial is None
    assert central.ligado("principal") and not central.ligado("outro")


@pytest.mark.parametrize("acessos, trecho", [
    ([{"nome": "a", "perfil": "x", "porta": 9230},
      {"nome": "b", "perfil": "y", "porta": 9230}], "porta 9230 repetida"),
    ([{"nome": "a", "perfil": "x", "porta": 80}], "porta 80"),
    ([{"nome": "a", "perfil": "x"}], "porta"),
    ([{"nome": "a", "perfil": "x", "porta": 9230},
      {"nome": "a", "perfil": "y", "porta": 9231}], "nome 'a' repetido"),
])
def test_recusa_acessos_invalidos(pasta, acessos, trecho):
    _escrever(pasta, acessos)
    with pytest.raises(ValueError, match=trecho):
        central.carregar_acessos()


def test_json_quebrado_vira_valueerror_com_o_caminho(pasta):
    (pasta / "acessos.json").write_text("{nao é json", encoding="utf-8")
    with pytest.raises(ValueError, match="acessos.json"):
        central.carregar_acessos()


def test_endereco_e_so_local():
    a = central.Acesso("principal", central.PASTA_PADRAO / "p", 9230)
    assert central.endereco(a) == "http://127.0.0.1:9230"


def test_argumentos_do_chrome(tmp_path):
    a = central.Acesso("principal", tmp_path / "perfil", 9230)
    args = central.argumentos_chrome("C:/chrome.exe", a)
    assert args[0] == "C:/chrome.exe"
    assert "--remote-debugging-port=9230" in args
    assert "--remote-debugging-address=127.0.0.1" in args
    assert f"--user-data-dir={tmp_path / 'perfil'}" in args
    assert "--lang=pt-BR" in args
    assert not any("0.0.0.0" in x for x in args)


def test_chrome_vivo_le_json_version(tmp_path):
    a = central.Acesso("principal", tmp_path, 9230)
    pedidos = []

    class _Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *e): return False
        def read(self): return b'{"Browser": "Chrome/141"}'

    def abrir(url, timeout):
        pedidos.append(url)
        return _Resp()

    assert central.chrome_vivo(a, abrir=abrir) is True
    assert pedidos == ["http://127.0.0.1:9230/json/version"]

    def recusa(url, timeout):
        raise OSError("conexão recusada")
    assert central.chrome_vivo(a, abrir=recusa) is False


def test_garantir_chrome_nao_sobe_se_ja_vivo(tmp_path):
    a = central.Acesso("principal", tmp_path / "p", 9230)
    chamadas = []
    end = central.garantir_chrome(a, popen=lambda *x, **k: chamadas.append(x),
                                  vivo=lambda _a: True, exe="C:/chrome.exe")
    assert end == "http://127.0.0.1:9230"
    assert chamadas == []


def test_garantir_chrome_sobe_e_espera_a_porta(tmp_path):
    a = central.Acesso("principal", tmp_path / "p", 9230)
    estado = {"vivo": False, "subidas": 0}

    def popen(args, **kw):
        estado["subidas"] += 1
        estado["vivo"] = True
        assert kw.get("creationflags")   # destacado: sobrevive ao robô
    end = central.garantir_chrome(a, popen=popen, vivo=lambda _a: estado["vivo"],
                                  exe="C:/chrome.exe", dormir=lambda s: None)
    assert end == "http://127.0.0.1:9230"
    assert estado["subidas"] == 1
    assert (tmp_path / "p").is_dir()


def test_garantir_chrome_desiste_com_recado(tmp_path):
    a = central.Acesso("principal", tmp_path / "p", 9230)
    relogio = iter(range(0, 1000))
    with pytest.raises(TimeoutError, match="9230"):
        central.garantir_chrome(a, popen=lambda *x, **k: None,
                                vivo=lambda _a: False, exe="C:/chrome.exe",
                                esperar=3, dormir=lambda s: next(relogio))


def test_dois_robos_ao_mesmo_tempo_sobem_um_chrome_so(tmp_path):
    a = central.Acesso("principal", tmp_path / "p", 9230)
    estado = {"vivo": False, "subidas": 0}
    trava_de_teste = threading.Lock()

    def popen(args, **kw):
        with trava_de_teste:
            estado["subidas"] += 1
        time.sleep(0.2)              # o Chrome demora a abrir a porta
        estado["vivo"] = True

    erros = []
    def robo():
        try:
            central.garantir_chrome(a, popen=popen, vivo=lambda _a: estado["vivo"],
                                    exe="C:/chrome.exe", dormir=time.sleep)
        except Exception as e:      # pragma: no cover - aparece no assert
            erros.append(e)
    t = [threading.Thread(target=robo) for _ in range(2)]
    for x in t: x.start()
    for x in t: x.join(10)
    assert erros == []
    assert estado["subidas"] == 1


def test_trava_velha_e_recuperada(tmp_path):
    caminho = tmp_path / ".principal.trava"
    caminho.write_text("pid morto")
    antigo = time.time() - 600
    import os
    os.utime(caminho, (antigo, antigo))
    with central.trava(caminho, espera=1, velha=120):
        assert caminho.exists()
    assert not caminho.exists()


def test_trava_ocupada_estoura_com_recado(tmp_path):
    caminho = tmp_path / ".principal.trava"
    caminho.write_text("outro")
    with pytest.raises(TimeoutError, match="trava"):
        with central.trava(caminho, espera=0.3, velha=120):
            pass
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_erp_central.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'erp.central'`.

- [ ] **Step 3: Implementar `erp/central.py`**

```python
# -*- coding: utf-8 -*-
"""O Chrome central: um Chrome por acesso do ERP, dono da sessão.

POR QUE EXISTE
--------------
O ERP aceita UMA sessão por usuário: todo `POST /users/login` derruba a
anterior. Mas várias abas do MESMO perfil do Chrome dividem a sessão e
convivem. Então quem faz login é um só (o porteiro, `erp/porteiro.py`, pela
tela), e cada robô abre a SUA aba nesse Chrome em vez de logar.

Este módulo só sabe ONDE está cada acesso e COMO subir o Chrome uma vez. Não
importa Playwright (quem conecta é `AbaCentral`, mais abaixo, que importa
tarde) e não importa nada do app — o água e energia copia este arquivo.

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
        dados = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"não consegui ler {arq}: {e}") from e
    acessos: dict[str, Acesso] = {}
    portas: set[int] = set()
    for item in dados.get("acessos") or []:
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


@contextlib.contextmanager
def trava(caminho: Path, *, espera: float = 60.0, velha: float = 120.0):
    """Trava entre processos por arquivo exclusivo. Arquivo mais velho que
    `velha` segundos é de processo que morreu no meio e é recuperado."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    limite = time.monotonic() + espera
    while True:
        try:
            fd = os.open(str(caminho), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode())
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - caminho.stat().st_mtime > velha:
                    caminho.unlink()
                    continue
            except OSError:
                continue
            if time.monotonic() >= limite:
                raise TimeoutError(f"trava ocupada há mais de {espera:.0f} s: {caminho}")
            time.sleep(0.1)
    try:
        yield
    finally:
        with contextlib.suppress(OSError):
            caminho.unlink()


def garantir_chrome(a: Acesso, *, popen=subprocess.Popen, vivo=None, exe=None,
                    esperar: float = 20.0, dormir=time.sleep) -> str:
    """O endereço CDP do Chrome deste acesso, subindo-o se estiver fechado."""
    vivo = vivo or chrome_vivo
    if vivo(a):
        return endereco(a)
    with trava(a.perfil.parent / f".{a.nome}.chrome.trava", espera=esperar + 30):
        if vivo(a):                       # outro robô subiu enquanto esperávamos
            return endereco(a)
        a.perfil.mkdir(parents=True, exist_ok=True)
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
```

Nota para o implementador: em `test_garantir_chrome_desiste_com_recado` o
`dormir` não dorme, e por isso o laço conta passos, não relógio. Mantenha as
duas saídas: `passos` para o teste e o relógio para a vida real.

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_erp_central.py -q`
Expected: todos PASS.

- [ ] **Step 5: Ruff, vermin e commit**

```bash
python -m ruff check --select E9,F erp/central.py tests/test_erp_central.py
python -m vermin --target=3.11 --violations erp/central.py
git add erp/central.py tests/test_erp_central.py
git commit -m "erp: Chrome central por acesso (acessos.json, trava, garantir_chrome)"
```

---

### Task 2: `AbaCentral` — a aba própria do robô no Chrome central

**Files:**
- Modify: `erp/central.py` (acrescentar ao fim)
- Test: `tests/test_erp_central.py` (acrescentar)

**Interfaces:**
- Consumes: `Acesso`, `garantir_chrome`, `endereco` (Task 1)
- Produces: `class AbaCentral(a: Acesso, *, pw=None, garantir=garantir_chrome)`, um context manager que expõe `.browser`, `.ctx`, `.page` e `nova_aba() -> page`. Na saída fecha só as abas dele.

- [ ] **Step 1: Testes que falham**

```python
# acrescentar a tests/test_erp_central.py

class _Pagina:
    def __init__(self, registro):
        self.registro, self.fechada = registro, False
    def close(self):
        self.fechada = True
        self.registro.append("page.close")
    def is_closed(self):
        return self.fechada


class _Ctx:
    def __init__(self, registro):
        self.registro, self.pages = registro, [_Pagina(registro)]  # aba de outro robô
    def new_page(self):
        p = _Pagina(self.registro)
        self.pages.append(p)
        return p
    def close(self):
        self.registro.append("ctx.close")


class _Browser:
    def __init__(self, registro):
        self.registro, self.contexts = registro, [_Ctx(registro)]
    def close(self):
        self.registro.append("browser.close")


class _PW:
    def __init__(self, registro):
        self.registro = registro
        outer = self
        class _Chromium:
            def connect_over_cdp(self, endereco):
                outer.registro.append(f"cdp {endereco}")
                return _Browser(outer.registro)
        self.chromium = _Chromium()
    def stop(self):
        self.registro.append("pw.stop")


def test_aba_central_fecha_so_as_proprias_e_nunca_o_chrome(tmp_path):
    reg = []
    a = central.Acesso("principal", tmp_path / "p", 9230)
    with central.AbaCentral(a, pw=_PW(reg), garantir=lambda _a: "http://127.0.0.1:9230") as aba:
        alheia = aba.ctx.pages[0]
        extra = aba.nova_aba()
        assert aba.page is not alheia and extra is not alheia
    assert "cdp http://127.0.0.1:9230" in reg
    assert "ctx.close" not in reg and "browser.close" not in reg
    assert alheia.fechada is False
    assert aba.page.fechada and extra.fechada
    assert reg[-1] == "pw.stop"


def test_aba_central_fecha_mesmo_com_erro_no_meio(tmp_path):
    reg = []
    a = central.Acesso("principal", tmp_path / "p", 9230)
    with pytest.raises(RuntimeError):
        with central.AbaCentral(a, pw=_PW(reg), garantir=lambda _a: "http://127.0.0.1:9230"):
            raise RuntimeError("robô caiu")
    assert reg.count("page.close") == 1 and "browser.close" not in reg
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_erp_central.py -q -k aba_central`
Expected: FAIL, `AttributeError: module 'erp.central' has no attribute 'AbaCentral'`.

- [ ] **Step 3: Implementar**

```python
# acrescentar ao fim de erp/central.py

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
```

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_erp_central.py -q`
Expected: todos PASS.

- [ ] **Step 5: Commit**

```bash
git add erp/central.py tests/test_erp_central.py
git commit -m "erp: AbaCentral — aba própria no Chrome central, sem fechar o Chrome"
```

---

### Task 3: `erp/sessao_pagina.py` — pedidos ao ERP pela aba central

**Files:**
- Create: `erp/sessao_pagina.py`
- Test: `tests/test_erp_sessao_pagina.py`

**Interfaces:**
- Consumes: `central.Acesso`, `central.AbaCentral`, `central.acesso` (Tasks 1-2); `erp.hosts.host_de`, `hosts.vale_a_pena`, `hosts.HOST_LEGACY`, `hosts.HOST_ERP_API`; `erp.pagina.TransportePagina`; `erp.sessao.ErpErro`, `SessaoRecusada`.
- Produces: `class SessaoPelaPagina`, com o mesmo contrato público que `erp.Sessao` usa nos consumidores:
  - atributos `jwt_token, access_token, company_id, user_id, organization_unit_id, usuario, empresa, transporte, espera`
  - `pedir(url, *, metodo="GET", corpo=None, extras=None, idempotente=False) -> dict`
  - `token_para(url) -> str`, `cabecalhos_para(url, extras=None) -> dict`, `relogar() -> None`, `fechar() -> None`
  - `@classmethod do_acesso(nome="principal", *, fabrica_aba=None, espera_captura=90.0) -> SessaoPelaPagina`
- Constante `URL_CAPTURA = "https://acessar.maiscontroleerp.com.br/#/payable-installments"`.

**Desenho (ler antes de codar):**
- Uma **thread dona** (daemon, chamada `erp-central-<nome>`) cria a `AbaCentral`, liga `page.on("request", ...)` e navega para `URL_CAPTURA`. Os cabeçalhos ficam num dict `{host: cab}`, filtrados por `hosts.vale_a_pena` e pela presença de `authorization`, com as chaves `authorization`, `company-id`, `user-id` e `organization-unit-id` (a mesma regra de `aportes/erp_sessao.py`).
- "Pronto" = capturou `HOST_LEGACY` **e** `HOST_ERP_API`. Antes disso, `do_acesso` espera até `espera_captura`. Se o prazo vencer, `fechar()` e `ErpErro("o Chrome central '<nome>' não está logado no ERP — o porteiro precisa entrar (python -m erp.porteiro estado)")`.
- `pedir` de **qualquer** thread põe `(funcao, args, Future)` numa `queue.Queue` e espera o `Future` (timeout 300 s). Só a thread dona toca o Playwright. Entre um pedido e outro, ela chama `page.wait_for_timeout(200)`, para os eventos de request chegarem.
- Na thread dona, cada pedido usa `TransportePagina(page, dict(self._cab))`: `buscar` (GET), `postar` (POST) ou `trocar` (PUT). Resposta `{"__erro": 401}`: chama `_recapturar()` (limpa o dict, `page.reload()`, espera pronto por até 30 s) e repete **uma** vez. No segundo 401: `SessaoRecusada("o ERP recusou a sessão do Chrome central duas vezes (401)", codigo=401)`. Outro `__erro`: `ErpErro(f"o ERP respondeu {st} em {caminho}", codigo=st)`. Nunca põe a URL inteira na mensagem (pode carregar id).
- `jwt_token` vem do `authorization` de `HOST_ERP_API` sem o `"Bearer "`; `access_token` vem do de `HOST_LEGACY`; `company_id`, `user_id` e `organization_unit_id` vêm dos cabeçalhos do legacy. `usuario = f"Chrome central ({nome})"`, `empresa = None`. Atualizar esses campos a cada recaptura.
- `transporte` e `espera` são atributos aceitos e ignorados: `conciliacao/erp/api.py` os atribui antes de pedir.
- `relogar()` = `_recapturar()` pela fila. **Não faz login**: quem loga é o porteiro.

- [ ] **Step 1: Testes que falham**

```python
# tests/test_erp_sessao_pagina.py
# -*- coding: utf-8 -*-
"""Pedidos ao ERP pela aba do Chrome central. Sem navegador: a aba é dublê."""
import threading

import pytest

from erp import hosts
from erp.sessao import ErpErro, SessaoRecusada
from erp.sessao_pagina import SessaoPelaPagina

LEG = f"https://{hosts.HOST_LEGACY}"
PROD = f"https://{hosts.HOST_ERP_API}"


class _Req:
    def __init__(self, url, headers):
        self.url, self.headers = url, headers


class _PaginaFalsa:
    """Dispara os requests da tela quando navega/recarrega; responde fetch."""
    def __init__(self, respostas=None, logada=True):
        self.ouvintes, self.respostas = [], list(respostas or [])
        self.logada, self.recargas, self.threads = logada, 0, set()
        self.token = 1

    def on(self, evento, fn):
        assert evento == "request"
        self.ouvintes.append(fn)

    def _tela(self):
        if not self.logada:
            return
        for fn in self.ouvintes:
            fn(_Req(f"{LEG}/maiscontrole/services/x", {
                "authorization": f"Bearer acc{self.token}", "company-id": "emp",
                "user-id": "u1", "organization-unit-id": "o1", "accept": "x"}))
            fn(_Req(f"{PROD}/y", {"authorization": f"Bearer jwt{self.token}",
                                  "company-id": "emp"}))
            fn(_Req("https://api-data-event.exemplo/z", {"authorization": "Bearer tele"}))

    def goto(self, url, **kw):
        self.threads.add(threading.get_ident())
        self._tela()

    def reload(self, **kw):
        self.recargas += 1
        self.token += 1
        self._tela()

    def wait_for_timeout(self, ms):
        self.threads.add(threading.get_ident())

    def evaluate(self, js, args):
        self.threads.add(threading.get_ident())
        r = self.respostas.pop(0) if self.respostas else {"ok": True}
        return r(args) if callable(r) else r


class _AbaFalsa:
    def __init__(self, pagina):
        self.page, self.fechou = pagina, False
    def __enter__(self): return self
    def __exit__(self, *e):
        self.fechou = True
        return False


def _sessao(pagina, **kw):
    aba = _AbaFalsa(pagina)
    s = SessaoPelaPagina.do_acesso("principal", fabrica_aba=lambda: aba,
                                   espera_captura=kw.pop("espera", 2.0))
    return s, aba


def test_captura_os_dois_hosts_e_ignora_telemetria():
    s, _ = _sessao(_PaginaFalsa())
    try:
        assert s.access_token == "acc1" and s.jwt_token == "jwt1"
        assert s.company_id == "emp" and s.user_id == "u1"
        assert s.cabecalhos_para(f"{LEG}/a")["authorization"] == "Bearer acc1"
        assert s.cabecalhos_para(f"{PROD}/a")["authorization"] == "Bearer jwt1"
        assert "accept" not in s.cabecalhos_para(f"{LEG}/a")
        assert s.token_para(f"{PROD}/a") == "jwt1"
    finally:
        s.fechar()


def test_get_passa_os_cabecalhos_do_host():
    vistos = []
    pag = _PaginaFalsa([lambda a: vistos.append(a) or {"itens": [1]}])
    s, _ = _sessao(pag)
    try:
        assert s.pedir(f"{LEG}/lista") == {"itens": [1]}
        assert vistos[0]["headers"]["authorization"] == "Bearer acc1"
    finally:
        s.fechar()


def test_401_recaptura_e_repete_uma_vez():
    pag = _PaginaFalsa([{"__erro": 401}, {"ok": 2}])
    s, _ = _sessao(pag)
    try:
        assert s.pedir(f"{LEG}/lista") == {"ok": 2}
        assert pag.recargas == 1
        assert s.access_token == "acc2"
    finally:
        s.fechar()


def test_dois_401_viram_sessao_recusada():
    pag = _PaginaFalsa([{"__erro": 401}, {"__erro": 401}])
    s, _ = _sessao(pag)
    try:
        with pytest.raises(SessaoRecusada, match="401"):
            s.pedir(f"{LEG}/lista")
    finally:
        s.fechar()


def test_outro_erro_vira_erperro_sem_a_url_inteira():
    pag = _PaginaFalsa([{"__erro": 500}])
    s, _ = _sessao(pag)
    try:
        with pytest.raises(ErpErro) as e:
            s.pedir(f"{LEG}/lista?id=segredo")
        assert e.value.codigo == 500 and "segredo" not in str(e.value)
    finally:
        s.fechar()


def test_post_e_put_usam_o_transporte_certo():
    vistos = []
    pag = _PaginaFalsa([lambda a: vistos.append(a) or {"criado": 1},
                        lambda a: vistos.append(a) or {"trocado": 1}])
    s, _ = _sessao(pag)
    try:
        assert s.pedir(f"{LEG}/p", metodo="POST", corpo={"x": 1}) == {"criado": 1}
        assert s.pedir(f"{LEG}/p", metodo="PUT", corpo={"x": 2}) == {"trocado": 1}
        assert vistos[0]["corpo"] == {"x": 1} and vistos[1]["corpo"] == {"x": 2}
    finally:
        s.fechar()


def test_sem_login_desiste_com_recado_do_porteiro():
    pag = _PaginaFalsa(logada=False)
    with pytest.raises(ErpErro, match="porteiro"):
        _sessao(pag, espera=0.5)


def test_pedidos_de_duas_threads_rodam_na_thread_dona():
    pag = _PaginaFalsa([{"n": i} for i in range(20)])
    s, _ = _sessao(pag)
    resultados = []
    try:
        def trabalhar():
            for _ in range(10):
                resultados.append(s.pedir(f"{LEG}/x"))
        t = [threading.Thread(target=trabalhar) for _ in range(2)]
        for x in t: x.start()
        for x in t: x.join(20)
        assert sorted(r["n"] for r in resultados) == list(range(20))
        assert len(pag.threads) == 1            # só a thread dona tocou a página
        assert threading.get_ident() not in pag.threads
    finally:
        s.fechar()


def test_fechar_fecha_a_aba_e_e_idempotente():
    s, aba = _sessao(_PaginaFalsa())
    s.fechar()
    s.fechar()
    assert aba.fechou is True


def test_aceita_transporte_e_espera_atribuidos_por_fora():
    s, _ = _sessao(_PaginaFalsa())
    try:
        s.transporte, s.espera = object(), 45   # conciliacao/erp/api.py faz isso
    finally:
        s.fechar()
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_erp_sessao_pagina.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'erp.sessao_pagina'`.

- [ ] **Step 3: Implementar `erp/sessao_pagina.py`** seguindo o "Desenho" acima.
  Esqueleto obrigatório (preencher os corpos):

```python
# -*- coding: utf-8 -*-
"""Pedidos ao ERP pela aba do Chrome central — sem login nenhum.

Regra do dono (14/10/2026): o ERP é acessado SEMPRE pelo Chrome do app. Esta
classe é o que `erp.Sessao.logar` devolve quando o modo central está ligado
(`erp/central.py`): uma aba própria no Chrome central, numa thread própria, que
copia a autenticação do tráfego da tela e faz `fetch` de dentro da página.

Playwright sync só pode ser tocado pela thread que o criou. Por isso TODO
pedido, venha de que thread vier, passa por uma fila até a thread dona.
"""
from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from urllib.parse import urlsplit

from . import central, hosts
from .pagina import TransportePagina
from .sessao import ErpErro, SessaoRecusada

URL_CAPTURA = "https://acessar.maiscontroleerp.com.br/#/payable-installments"
_CHAVES = {"authorization", "company-id", "user-id", "organization-unit-id"}
_PRAZO_PEDIDO = 300.0


class SessaoPelaPagina:
    def __init__(self, nome: str, fabrica_aba, espera_captura: float):
        ...  # campos públicos (jwt_token etc.), fila, evento "pronto", thread dona

    @classmethod
    def do_acesso(cls, nome: str = "principal", *, fabrica_aba=None,
                  espera_captura: float = 90.0) -> "SessaoPelaPagina":
        if fabrica_aba is None:
            a = central.acesso(nome)
            if a is None:
                raise ErpErro(f"o acesso '{nome}' não está no acessos.json")
            fabrica_aba = lambda: central.AbaCentral(a)   # noqa: E731
        s = cls(nome, fabrica_aba, espera_captura)
        s._esperar_pronto()          # ErpErro "...porteiro precisa entrar..."
        return s

    # thread dona: _laco(), _ouvir(req), _recapturar(), _executar(metodo, url, corpo)
    # qualquer thread: pedir(), relogar(), fechar(), token_para(), cabecalhos_para()
```

Nota: `cabecalhos_para(url, extras=None)` devolve só as quatro chaves
capturadas do host da URL. Sem captura daquele host, devolve o conjunto do
legacy (mesma regra de `TransportePagina.cabecalhos_para`), mais `extras`.

- [ ] **Step 4: Rodar e ver passar** (rodar 3 vezes, por causa das threads)

Run (três vezes seguidas): `python -m pytest tests/test_erp_sessao_pagina.py -q`
Expected: todos PASS nas três.

- [ ] **Step 5: Commit**

```bash
git add erp/sessao_pagina.py tests/test_erp_sessao_pagina.py
git commit -m "erp: SessaoPelaPagina — pedidos pela aba central, thread dona, recaptura no 401"
```

---

### Task 4: Desviar os logins HTTP do app para o central

**Files:**
- Modify: `erp/sessao.py` (`Sessao.logar`)
- Modify: `erp/__init__.py` (exportar `central`, `SessaoPelaPagina`)
- Modify: `conciliacao/erp/api.py:185-199` (`SessaoApi.logar`)
- Test: `tests/test_erp.py` e `tests/test_conciliacao_erp_api.py` (acrescentar)

**Interfaces:**
- Consumes: `central.ligado()`, `SessaoPelaPagina.do_acesso()` (Tasks 1 e 3)
- Produces: com o central ligado, `Sessao.logar(...)` devolve `SessaoPelaPagina` **sem** chamar a rede, e `SessaoApi.logar(config)` funciona sem credencial.

- [ ] **Step 1: Testes que falham**

```python
# acrescentar a tests/test_erp.py
def test_logar_com_central_ligado_nao_toca_a_rede(monkeypatch):
    from erp import central, sessao_pagina
    monkeypatch.setattr(central, "ligado", lambda nome="principal", pasta=None: True)
    falsa = object()
    monkeypatch.setattr(sessao_pagina.SessaoPelaPagina, "do_acesso",
                        classmethod(lambda cls, nome="principal", **k: falsa))
    def proibido(*a, **k):
        raise AssertionError("login HTTP com o central ligado")
    monkeypatch.setattr(sessao, "_pedir", proibido)
    assert sessao.Sessao.logar("fulano@exemplo.test", "x") is falsa


def test_logar_com_central_desligado_segue_como_antes(monkeypatch):
    from erp import central
    monkeypatch.setattr(central, "ligado", lambda nome="principal", pasta=None: False)
    chamado = {}
    def pedir_falso(*a, **k):
        chamado["sim"] = True
        return CORPO_DO_LOGIN
    monkeypatch.setattr(sessao, "_pedir", pedir_falso)
    s = sessao.Sessao.logar("fulano@exemplo.test", "x")
    assert chamado and s.access_token == "a" * 27
```

O implementador confere em `erp/sessao.py` como `Sessao.logar` chama a rede
hoje (o nome real da função de transporte) e ajusta o `monkeypatch` do teste
ao nome verdadeiro. Ele **não** muda o teste para passar à força.

```python
# acrescentar a tests/test_conciliacao_erp_api.py
def test_sessaoapi_no_central_nao_exige_credencial(monkeypatch):
    from conciliacao.erp import api
    from erp import central
    monkeypatch.setattr(central, "ligado", lambda nome="principal", pasta=None: True)
    monkeypatch.setattr(api, "obter_credenciais", lambda: (None, None))

    class _Interna:
        jwt_token, company_id, usuario, empresa = "jwt", "emp", "Chrome central (principal)", None
    monkeypatch.setattr(api.Sessao, "logar", classmethod(lambda cls, *a, **k: _Interna()))
    s = api.SessaoApi.logar(object(), log=lambda *_: None)
    assert s.token == "jwt" and s.company_id == "emp"
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_erp.py tests/test_conciliacao_erp_api.py -q -k "central"`
Expected: FAIL nos três testes novos.

- [ ] **Step 3: Implementar**

Em `erp/sessao.py`, primeira coisa dentro de `Sessao.logar`:

```python
        # Regra do dono (14/10/2026): com o Chrome central ligado, o ERP é
        # acessado SEMPRE pela página. Login HTTP aqui derrubaria a sessão
        # do Chrome central (o ERP aceita uma por usuário).
        from . import central
        if central.ligado():
            from .sessao_pagina import SessaoPelaPagina
            return SessaoPelaPagina.do_acesso()
```

Em `conciliacao/erp/api.py`, dentro de `SessaoApi.logar`, trocar o
`email, senha = obter_credenciais()` e o `if not (email and senha)` por:

```python
        from erp import central
        if central.ligado():
            email, senha = "", ""        # quem entra é o porteiro, pela tela
        else:
            email, senha = obter_credenciais()
            if not (email and senha):
                raise SessaoExpirada(...)   # o texto atual, sem mudar
```

e usar `usuario=interna.usuario or email or "Chrome central"`.

Em `erp/__init__.py`, acrescentar `central` e `SessaoPelaPagina` ao que o
pacote expõe, seguindo o estilo do arquivo. `SessaoPelaPagina` entra por
import tardio (`__getattr__`) para não carregar a thread em quem só quer
`hosts`, caso o arquivo já use esse padrão. Senão, import direto: o módulo
não importa Playwright no topo.

- [ ] **Step 4: Rodar a suíte do ERP inteira**

Run: `python -m pytest tests/test_erp.py tests/test_conciliacao_erp_api.py tests/test_erp_sessao.py tests/test_erp_central.py tests/test_erp_sessao_pagina.py -q`
Expected: tudo PASS, inclusive os testes antigos sem edição.

- [ ] **Step 5: Commit**

```bash
git add erp/sessao.py erp/__init__.py conciliacao/erp/api.py tests/test_erp.py tests/test_conciliacao_erp_api.py
git commit -m "erp: com o Chrome central ligado, logar vira pedir pela página"
```

---

### Task 5: `MCClient` em modo central

**Files:**
- Modify: `anexar/mc_client.py` (`__init__` :299, `__enter__` :336, `__exit__` :369, `_nova_aba` :378, `_tentar_entrar` :708)
- Test: `tests/test_mc_client_central.py` (novo)

**Interfaces:**
- Consumes: `central.acesso()`, `central.garantir_chrome`, `central.trava`, `central.pasta_central` (Task 1)
- Produces:
  - `MCClient(headless=False, log=print, acesso=None)`: com `acesso` (um `central.Acesso`) ou com o central ligado e `acesso is None`, o cliente entra em modo central. `self.central: bool`.
  - Modo central: `__enter__` faz `connect_over_cdp(garantir_chrome(a))`, `ctx = browser.contexts[0]` e `page = ctx.new_page()`, posta em `_minhas`. `__exit__` fecha só as páginas de `_minhas` e faz `pw.stop()`.
  - `_nova_aba(pagina)` no modo central: adota só a aba aberta a partir de uma aba sua (`opener in _minhas`) e **ignora** as outras; não liga o ouvinte de download nas abas dos outros robôs.
  - `garantir_login()` no modo central roda dentro de `central.trava(pasta/".<nome>.login.trava", espera=180)`: dois robôs nunca tentam entrar ao mesmo tempo, e o segundo, ao pegar a trava, vê "Login OK (sessão ainda aberta)".
  - `_tentar_entrar()` no modo central usa a credencial do `acesso.credencial`, quando houver (mesmo formato DPAPI de `anexar/credenciais.py`, decifrado com `util.revelar_bytes`). Sem ela, usa `credenciais.carregar()`.

- [ ] **Step 1: Testes que falham** (dublês no mesmo estilo de `tests/test_erp_central.py`, Task 2)

```python
# tests/test_mc_client_central.py
# -*- coding: utf-8 -*-
"""MCClient conectado ao Chrome central: entra, trabalha, sai sem fechar nada
dos outros. Sem navegador: o Playwright é dublê."""
import json

import pytest

import util
from anexar import mc_client
from erp import central


class _P:
    def __init__(self, reg, opener=None):
        self.reg, self._opener, self.fechada, self.ouvintes = reg, opener, False, {}
    def opener(self): return self._opener
    def on(self, ev, fn): self.ouvintes.setdefault(ev, []).append(fn)
    def close(self):
        self.fechada = True
        self.reg.append("page.close")
    def is_closed(self): return self.fechada


class _C:
    def __init__(self, reg):
        self.reg, self.pages, self.ouvintes = reg, [_P(reg)], {}
    def new_page(self):
        p = _P(self.reg)
        self.pages.append(p)
        return p
    def on(self, ev, fn): self.ouvintes.setdefault(ev, []).append(fn)
    def close(self): self.reg.append("ctx.close")


class _B:
    def __init__(self, reg): self.reg, self.contexts = reg, [_C(reg)]
    def close(self): self.reg.append("browser.close")


class _PW:
    def __init__(self, reg):
        self.reg = reg
        r = reg
        class _Ch:
            def connect_over_cdp(self, end):
                r.append(f"cdp {end}")
                return _B(r)
            def launch_persistent_context(self, **k):
                raise AssertionError("modo central não lança Chrome próprio")
        self.chromium = _Ch()
    def stop(self): self.reg.append("pw.stop")


@pytest.fixture
def central_falso(tmp_path, monkeypatch):
    reg = []
    a = central.Acesso("principal", tmp_path / "perfil", 9230,
                       tmp_path / "principal.login.dat")
    monkeypatch.setattr(mc_client, "sync_playwright",
                        lambda: type("S", (), {"start": lambda self: _PW(reg)})())
    monkeypatch.setattr(central, "garantir_chrome", lambda a, **k: "http://127.0.0.1:9230")
    return a, reg


def test_entra_pelo_cdp_e_sai_sem_fechar_o_chrome(central_falso):
    a, reg = central_falso
    mc = mc_client.MCClient(log=lambda *_: None, acesso=a)
    with mc:
        alheia = mc.ctx.pages[0]
        assert mc.central is True and mc.page is not alheia
    assert "cdp http://127.0.0.1:9230" in reg
    assert "ctx.close" not in reg and "browser.close" not in reg
    assert alheia.fechada is False and mc.page.fechada is True


def test_aba_de_outro_robo_nao_e_adotada_nem_ouvida(central_falso):
    a, reg = central_falso
    mc = mc_client.MCClient(log=lambda *_: None, acesso=a)
    with mc:
        de_outro = _P(reg)
        mc._nova_aba(de_outro)
        assert de_outro not in mc._minhas and "download" not in de_outro.ouvintes
        filha = _P(reg, opener=mc.page)
        mc._nova_aba(filha)
        assert filha in mc._minhas


def test_credencial_do_acesso_e_usada(central_falso, monkeypatch):
    a, _ = central_falso
    a.credencial.write_bytes(util.proteger_bytes(
        json.dumps({"email": "fulano@exemplo.test", "senha": "s"}).encode()))
    mc = mc_client.MCClient(log=lambda *_: None, acesso=a)
    assert mc._credencial() == ("fulano@exemplo.test", "s")


def test_sem_central_continua_lancando_o_chrome_proprio(monkeypatch):
    monkeypatch.setattr(central, "ligado", lambda *a, **k: False)
    mc = mc_client.MCClient(log=lambda *_: None)
    assert mc.central is False
```

O teste de DPAPI só roda no Windows (`util.proteger_bytes`). Marque com
`pytest.mark.skipif(sys.platform != "win32", reason="DPAPI só no Windows")`.
O CI roda em windows-latest, então ali ele roda.

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_mc_client_central.py -q`
Expected: FAIL, `TypeError: MCClient.__init__() got an unexpected keyword argument 'acesso'`.

- [ ] **Step 3: Implementar.** As mudanças, uma a uma:

1. `__init__(self, headless=False, log=print, acesso=None)`: guardar `self._acesso = acesso if acesso is not None else (central.acesso() if central.ligado() else None)` e `self.central = self._acesso is not None`. Importar `from erp import central` no topo; o módulo não puxa Playwright.
2. `__enter__`: no modo central, `self._pw = sync_playwright().start()`; `self._browser = self._pw.chromium.connect_over_cdp(central.garantir_chrome(self._acesso))`; `self.ctx = self._browser.contexts[0]`; `self.page = self.ctx.new_page()`; `self._minhas.add(self.page)`; os mesmos `ctx.on("page", self._nova_aba)` e `ctx.on("close", self._ao_fechar)`; `return self`. **Não** chamar `util.limpar_historico_de_downloads` com o Chrome aberto (só funciona com o perfil fechado; quem limpa é o porteiro, antes de subir o Chrome). Fora do modo central, o código atual sem nenhuma mudança.
3. `__exit__`: no modo central, fechar cada página de `self._minhas` que não esteja fechada e depois `self._pw.stop()`. Nunca `self.ctx.close()`.
4. `_nova_aba`: no modo central, depois da regra do `opener` (que fica igual), `return` sem ligar o ouvinte de download.
5. Novo `_credencial(self) -> tuple[str, str] | None`: no modo central com `self._acesso.credencial` existente, decifra com `util.revelar_bytes` e devolve `(email, senha)`; em qualquer falha, `config.diag(...)` e `None`. Fora disso, `credenciais.carregar()`. Em `_tentar_entrar`, trocar `creds = credenciais.carregar()` por `creds = self._credencial()`.
6. `garantir_login`: no modo central, envolver o corpo atual em `with central.trava(central.pasta_central() / f".{self._acesso.nome}.login.trava", espera=180):`. A melhor forma é renomear o corpo atual para `_garantir_login_sem_trava` e chamar dentro da trava; fora do modo central, chamar direto.

- [ ] **Step 4: Rodar os testes do cliente e a suíte inteira**

Run: `python -m pytest tests/test_mc_client_central.py -q && python -m pytest tests -q -x`
Expected: tudo PASS. Os testes antigos do `mc_client` não mudam.

- [ ] **Step 5: Commit**

```bash
git add anexar/mc_client.py tests/test_mc_client_central.py
git commit -m "anexar: MCClient conecta no Chrome central (aba própria, trava de login)"
```

---

### Task 6: `erp/porteiro.py` — quem mantém a sessão de pé

**Files:**
- Create: `erp/porteiro.py`
- Create: `ferramentas/porteiro/registrar_porteiro.ps1`
- Create: `docs/PORTEIRO.md`
- Test: `tests/test_erp_porteiro.py`

**Interfaces:**
- Consumes: `central.*` (Task 1), `MCClient(acesso=...)` (Task 5), `util.proteger_bytes`, `util.limpar_historico_de_downloads`
- Produces: CLI `python -m erp.porteiro <comando> [--acesso NOME]`:
  - `estado`: imprime JSON `{"acessos": [{"nome", "porta", "chrome_vivo": bool}]}`. Só lê; não sobe nada.
  - `guardar-login --acesso NOME`: pede e-mail (`input`) e senha (`getpass`) e grava `util.proteger_bytes(json)` em `acesso.credencial`. Recusa se o acesso não tem `credencial` no JSON.
  - `subir`: para cada acesso com o Chrome fechado, roda `util.limpar_historico_de_downloads(perfil)` e `garantir_chrome`. Depois, `MCClient(acesso=a, log=...)` + `garantir_login()` em cada um.
  - `vigiar [--intervalo 120]`: `subir`, e a cada intervalo, para cada acesso: Chrome vivo? Se não, sobe. Logado (`mc.esta_logado()`)? Se não, `garantir_login()`. Tudo vai para o log `<pasta central>/porteiro.log` (`logging`, com rotação já usada no app: `util.log`). Uma exceção num acesso não derruba o laço dos outros.
  - Funções puras testáveis: `montar_estado(acessos, vivo) -> dict` e `um_ciclo(acessos, *, vivo, subir_chrome, checar_login, log) -> list[str]` (devolve o que fez, por acesso).

- [ ] **Step 1: Testes que falham**

```python
# tests/test_erp_porteiro.py
# -*- coding: utf-8 -*-
from erp import central, porteiro


def _acessos(tmp_path):
    return {"principal": central.Acesso("principal", tmp_path / "p1", 9230),
            "robo2": central.Acesso("robo2", tmp_path / "p2", 9231)}


def test_estado_lista_cada_acesso(tmp_path):
    e = porteiro.montar_estado(_acessos(tmp_path), vivo=lambda a: a.nome == "principal")
    assert e == {"acessos": [
        {"nome": "principal", "porta": 9230, "chrome_vivo": True},
        {"nome": "robo2", "porta": 9231, "chrome_vivo": False}]}


def test_ciclo_sobe_o_fechado_e_reloga_o_deslogado(tmp_path):
    feitos = []
    r = porteiro.um_ciclo(
        _acessos(tmp_path),
        vivo=lambda a: a.nome == "principal",
        subir_chrome=lambda a: feitos.append(f"subiu {a.nome}"),
        checar_login=lambda a: feitos.append(f"login {a.nome}") or True,
        log=lambda *_: None)
    assert feitos == ["login principal", "subiu robo2", "login robo2"]
    assert r == ["principal: ok", "robo2: chrome subiu; ok"]


def test_erro_num_acesso_nao_para_os_outros(tmp_path):
    def checar(a):
        if a.nome == "principal":
            raise RuntimeError("tela travada")
        return True
    r = porteiro.um_ciclo(_acessos(tmp_path), vivo=lambda a: True,
                          subir_chrome=lambda a: None, checar_login=checar,
                          log=lambda *_: None)
    assert r[0].startswith("principal: ERRO") and r[1] == "robo2: ok"


def test_login_que_nao_entra_aparece_no_relatorio(tmp_path):
    r = porteiro.um_ciclo({"principal": _acessos(tmp_path)["principal"]},
                          vivo=lambda a: True, subir_chrome=lambda a: None,
                          checar_login=lambda a: False, log=lambda *_: None)
    assert r == ["principal: SEM LOGIN — entre na janela do Chrome central"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `python -m pytest tests/test_erp_porteiro.py -q`
Expected: FAIL, `ModuleNotFoundError`.

- [ ] **Step 3: Implementar `erp/porteiro.py`** (argparse; `if __name__ == "__main__": raise SystemExit(main())`). A `checar_login` real abre `MCClient(acesso=a)` e devolve `mc.garantir_login()`. Ela mantém o cliente aberto entre ciclos, um por acesso num dict, porque a aba do porteiro é a que fica de pé; e recria o cliente se `mc.vivo()` der False. Um docstring no topo explica o porquê, no estilo do repositório.

`ferramentas/porteiro/registrar_porteiro.ps1`: registra a tarefa
"MoraisEng - Porteiro do ERP" com gatilho **ao fazer logon** do usuário atual,
`python -m erp.porteiro vigiar` com diretório de trabalho na raiz do
repositório, `-RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)`,
sem limite de duração (`-ExecutionTimeLimit ([TimeSpan]::Zero)`). O modelo é
`agua_energia/coletor/registrar_tarefa.ps1`. Aceita `-Python <caminho>` e,
se não vier, descobre com `(Get-Command python).Source`.

`docs/PORTEIRO.md`: o que é, em uma frase; como ligar (criar
`acessos.json`, `guardar-login`, `subir`, registrar a tarefa); como desligar
(`MC_CENTRAL=off` ou apagar o `acessos.json`); como conferir
(`python -m erp.porteiro estado`); e a regra de que robô nunca fecha o Chrome
central. Linkar em `docs/ERP-CLIENTES.md`, seção 3, numa linha.

- [ ] **Step 4: Rodar e ver passar**

Run: `python -m pytest tests/test_erp_porteiro.py -q && python -m pytest tests/test_empacotamento.py -q`
Expected: PASS. Se `test_empacotamento` pedir os arquivos novos de `erp/` no
zip: `erp/*.py` já entra inteiro, então não deve pedir. Se pedir, seguir o
que ele disser.

- [ ] **Step 5: Commit**

```bash
git add erp/porteiro.py ferramentas/porteiro/registrar_porteiro.ps1 docs/PORTEIRO.md docs/ERP-CLIENTES.md tests/test_erp_porteiro.py
git commit -m "erp: porteiro — sobe o Chrome central, mantém o login, estado e tarefa ao logon"
```

---

### Task 7: Água e energia conecta no central (repositório `agua-energia`)

**Files (em `C:\AUTOMAÇÕES MAIS CONTROLE\_worktrees\agua-porteiro`, worktree do `agua_energia`):**
- Create: `coletor/mc_central.py`, cópia **byte a byte** de `erp/central.py` da Task 2, com uma linha a mais no topo do docstring: `Cópia de comprovantes-mais-controle/erp/central.py — mude lá e copie.`
- Modify: `coletor/lancar_mc.py` (`SessaoMC.__init__`/`__enter__`/`__exit__` :580-615; `nova_sessao()` :820)
- Modify: `coletor/erp_api.py` (nova função `nova_sessao()`)
- Modify: `coletor/auditar_descricoes.py:1070,1106`, `coletor/corrigir_descricoes.py:733` → `erp_api.nova_sessao()`
- Test: `tests/test_mc_central.py`, `tests/test_sessao_central.py`

**Interfaces:**
- Consumes: `mc_central.ligado()`, `mc_central.acesso()`, `mc_central.garantir_chrome`, `mc_central.trava`, `mc_central.pasta_central`
- Produces:
  - `SessaoMC(acesso=None)`: no modo central, `__enter__` conecta por CDP e abre a aba própria (sem apagar o History e sem `launch_persistent_context`); `__exit__` fecha só a aba própria e faz `pw.stop()`. O `_login_automatico` fica igual, mas roda dentro de `mc_central.trava(pasta/".<nome>.login.trava", espera=180)`, a mesma trava do `MCClient`.
  - `erp_api.nova_sessao()`: com `mc_central.ligado()`, devolve `lancar_mc.SessaoMC()`; senão, `SessaoAPI()`. `lancar_mc.nova_sessao()` passa a chamar `erp_api.nova_sessao()`.
  - Conferir antes que `SessaoMC` tem todos os métodos que `auditar_descricoes` e `corrigir_descricoes` chamam no `SessaoAPI`: `lista_periodo`, `get_trade_payable`, `put_trade_payable`, `trade_payable_do_installment`, `fetch_json`, `garantir_cab_prod`. O `erp_api.py` diz que é "a mesma interface". Confirmar com `grep -n "def " coletor/erp_api.py coletor/lancar_mc.py` e cobrir a diferença no teste `test_sessaomc_tem_a_interface_do_sessaoapi`.

- [ ] **Step 0: Worktree**

```bash
cd "/c/AUTOMAÇÕES MAIS CONTROLE/agua_energia" && git fetch -q origin && git worktree add -b codigo/porteiro-do-erp "../_worktrees/agua-porteiro" origin/main
```

- [ ] **Step 1: Testes que falham**

```python
# tests/test_mc_central.py
import hashlib
from pathlib import Path

APP = Path(r"C:\AUTOMAÇÕES MAIS CONTROLE\fontes\comprovantes-mais-controle\erp\central.py")


def test_copia_igual_a_do_app_quando_o_app_esta_ao_lado():
    """A cópia anda junto com o original. Fora desta máquina (CI), pula."""
    import pytest
    if not APP.exists():
        pytest.skip("repositório do app não está ao lado")
    aqui = Path(__file__).resolve().parents[1] / "coletor" / "mc_central.py"
    corpo = lambda p: [l for l in p.read_text(encoding="utf-8").splitlines()  # noqa: E731
                       if "Cópia de comprovantes-mais-controle" not in l]
    assert corpo(aqui) == corpo(APP)
```

```python
# tests/test_sessao_central.py
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "coletor"))

import erp_api            # noqa: E402
import lancar_mc          # noqa: E402
import mc_central         # noqa: E402


def test_fabrica_escolhe_pelo_central(monkeypatch):
    monkeypatch.setattr(mc_central, "ligado", lambda *a, **k: True)
    assert isinstance(erp_api.nova_sessao(), lancar_mc.SessaoMC)
    monkeypatch.setattr(mc_central, "ligado", lambda *a, **k: False)
    assert isinstance(erp_api.nova_sessao(), erp_api.SessaoAPI)


def test_sessaomc_tem_a_interface_do_sessaoapi():
    publicos = {n for n in dir(erp_api.SessaoAPI) if not n.startswith("_")}
    faltam = publicos - set(dir(lancar_mc.SessaoMC))
    assert faltam == set(), faltam


def test_sessaomc_central_sai_sem_fechar_o_chrome(monkeypatch, tmp_path):
    reg = []
    # mesmos dublês _P/_C/_B/_PW de tests/test_mc_client_central.py do app,
    # copiados aqui: o teste do água e energia não pode importar o do app.
    ...  # o implementador copia os 4 dublês e escreve o assert igual
```

O implementador **copia** os quatro dublês e escreve de fato o terceiro
teste: `"ctx.close"` e `"browser.close"` fora de `reg`, aba própria fechada e
aba alheia aberta. Não deixa `...`.

Se `test_sessaomc_tem_a_interface_do_sessaoapi` falhar (faltar método), o
implementador **para e reporta** quais faltam e onde eles são chamados. Não
inventa implementação.

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd coletor/.. && python -m pytest tests/test_mc_central.py tests/test_sessao_central.py -q`
Expected: FAIL, `ModuleNotFoundError: mc_central`.

- [ ] **Step 3: Implementar** (cópia do `central.py`, modo central na `SessaoMC`, fábrica, e os três pontos de chamada).

- [ ] **Step 4: Suíte inteira do água e energia**

Run: `python -m pytest tests -q`
Expected: tudo PASS (eram 354 em 14/10).

- [ ] **Step 5: Commit**

```bash
git add coletor/mc_central.py coletor/lancar_mc.py coletor/erp_api.py coletor/auditar_descricoes.py coletor/corrigir_descricoes.py tests/test_mc_central.py tests/test_sessao_central.py
git commit -m "coletor: no Chrome central, o ERP é sempre pela página (SessaoMC por CDP)"
```

---

### Task 8 (controlador): prova ao vivo neste notebook

Só com o dono avisado: a prova faz o porteiro entrar no ERP com o usuário do
`login.dat` desta máquina, e isso derruba outra sessão desse mesmo usuário.

1. `mkdir "C:\AUTOMAÇÕES MAIS CONTROLE\_central"` e criar o `acessos.json`
   com `principal`, porta 9230, perfil `perfis/principal`, credencial
   `principal.login.dat`.
2. No worktree do app: `python -m erp.porteiro guardar-login --acesso principal`
   (o dono digita), depois `python -m erp.porteiro subir`. Esperado: um
   Chrome abre e entra no ERP.
3. `python -m erp.porteiro estado`. Esperado: `chrome_vivo: true`.
4. **Duas rotinas ao mesmo tempo:**
   - Terminal A, no worktree do água e energia:
     `python coletor/auditar_descricoes.py` (só leitura; conferir as flags no
     topo do arquivo antes e escolher o modo que não grava).
   - Terminal B, no worktree do app: `python -m ferramentas.sonda` (lê contas
     e saldos via `SessaoApi`).
   - Esperado: as duas terminam sem 401 em cascata. O Chrome central continua
     aberto, com a aba do porteiro logada, depois que as duas saem.
5. Fechar o terminal do porteiro, rodar `subir` de novo e conferir que ele
   reaproveita o Chrome vivo (nenhum Chrome novo).
6. Registrar o resultado no corpo do PR: números medidos, sem print de tela,
   que pode trazer nome de empresa.

### Task 9 (controlador): passo a passo no servidor

Gerar `docs/PORTEIRO-SERVIDOR.md` e entregar ao dono. O roteiro, curto:
1. Entrar no servidor do escritório (endereço no cofre).
2. `git clone` do app em `C:\AUTOMAÇÕES MAIS CONTROLE\fontes\comprovantes-mais-controle`
   (ou `git pull`, se já existir) e
   `pip install -r requirements.txt` + `python -m playwright install chrome`.
3. `git pull` no `agua_energia`.
4. Criar `_central\acessos.json` (o mesmo modelo da Task 8, com o usuário do
   robô) e rodar `guardar-login`.
5. `python -m erp.porteiro subir` e depois `estado`.
6. `powershell -File ferramentas\porteiro\registrar_porteiro.ps1`.
7. Rodar `agua_energia\coletor\rodada_diaria.bat --forcar --so equatorial` com
   o porteiro de pé e conferir o `relatorios/rodada_*.txt`.

---

## Depois deste plano

Plano 2 (água e energia pelo app), Plano 3 (página web no servidor) e Plano 4
(Sicoob/Inter): ver o roteiro.
