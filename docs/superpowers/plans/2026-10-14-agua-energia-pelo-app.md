# Água e energia pelo app — Plano 2 do "Sistema no servidor"

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** um botão no app Comprovantes Mais Controle que dispara a rodada do água e energia a qualquer hora, mostra o andamento e o resumo, registra na nuvem quem disparou e nunca deixa duas rodadas rodarem ao mesmo tempo.

**Architecture:** a trava mora no PRÓPRIO `rodada_diaria.py` (repositório `gdiascabral/agua-energia`): um arquivo trancado pelo sistema operacional (`msvcrt.locking`) enquanto o processo vive, que vale para a tarefa agendada e para o botão. O app ganha a aba "Água e energia" (pacote novo `concessionarias/`), que roda `coletor\rodada_diaria.bat --forcar [--so equatorial]` como subprocesso, lê o andamento no `logs\rodada_agendada.log` (o `.bat` escreve tudo lá) e mostra o `relatorios/rodadas/AAAA-MM/rodada_*.txt` que a rodada anuncia na linha "resumo salvo em ...".

**Tech Stack:** Python 3.14 (água e energia) e o Python do motor do app; tkinter; `subprocess`; `msvcrt` (embutido no CPython do Windows).

**Spec:** `docs/superpowers/plans/2026-10-14-sistema-no-servidor-roteiro.md` (linha do plano 2) + o pedido de 14/10/2026: rodar `rodada_diaria.bat --forcar` ou o `--so` escolhido; andamento e resumo na aba; trava contra duas rodadas dentro do `rodada_diaria.py`, valendo também para a tarefa agendada; registro na nuvem (`nuvem/auditoria.registrar`) de quem disparou; funcionar com o Chrome central ligado ou desligado.

## Dois repositórios, dois PRs

| Parte | Repositório | Worktree | Branch | Base do PR |
|---|---|---|---|---|
| A (tasks 1-2) | `gdiascabral/agua-energia` | `_worktrees/agua-rodada-app` | `codigo/rodada-pelo-app` | `main` (o `rodada_diaria.py` do PR #27 é igual ao da `main`) |
| B (tasks 3-5) | `gdiascabral/comprovantes-mais-controle` | `_worktrees/app-agua-energia` | `codigo/agua-energia-pelo-app` | `codigo/porteiro-do-erp` (usa `erp.central.ligado()`, do PR #130) |

O contrato entre as duas partes é só de linha de comando e de arquivo, e está escrito UMA vez aqui:

- argumentos novos do `rodada_diaria.py`: `--origem TEXTO` (padrão `"agendada"`) e `--esperar MINUTOS` (padrão `90`; `0` = desiste na hora);
- código de saída `3` = "outra rodada em andamento, esta não começou". `0` = sem alertas, `1` = com ALERTA (já existia), qualquer outro = erro;
- arquivos `relatorios/RODADA_EM_ANDAMENTO.trava` (o trancado) e `relatorios/RODADA_EM_ANDAMENTO.json` (`{"pid", "inicio", "origem", "argumentos"}`, apagado no fim);
- a linha `resumo salvo em <caminho>` (já existe) anuncia o resumo;
- a linha `RODADA NÃO INICIADA: <motivo>` anuncia a recusa.

## Global Constraints

- **Interpretador:** no Bash desta máquina `python` cai no atalho da Microsoft Store. Use `"$LOCALAPPDATA/Python/pythoncore-3.14-64/python.exe"` (no PowerShell, `py`). Onde o plano diz `python`, é esse.

- **Não abrir o app, o ERP, nem Chrome**; nada de `comprovantes_app.py`, exe, galeria, `rodada_diaria.bat` de verdade ou script que logue no ERP. Só testes.
- **Testes de interface (fixture `raiz`) abrem uma janela invisível que rouba foco na máquina do dono.** O implementador roda só testes puros (`-k "not <teste Tk>"` ou os arquivos puros listados em cada task). Os testes Tk da task 4 e o `test_registro_visivel.py` rodam UMA vez, pelo coordenador, depois de perguntar se a tela está livre.
- **Repositório público:** nenhum nome de pessoa real, CPF/CNPJ, endereço do servidor ou dado de cliente em código, teste ou comentário. Nome de exemplo nos testes: `"Fulano"`.
- O app e o água e energia não se importam um ao outro. As constantes do contrato acima ficam escritas nos dois lados, com um comentário apontando o outro arquivo.
- O app roda no Python do motor (stdlib podada): nada de import novo além de `subprocess`, `msvcrt`, `re`, `unicodedata`, `json`, `os`, `pathlib`, `threading`, que já estão no exe (`tests/test_imports_do_motor.py` confere).
- Português nos comentários, nos textos de tela e nas mensagens de commit, como o resto dos dois repositórios.
- Commit no fim de cada task. **Ninguém faz push**; o coordenador abre os PRs.

## Modelo por tarefa

| Task | Implementador | Revisor | Motivo |
|---|---|---|---|
| 1 trava | sonnet | opus | código dado; concorrência entre processos merece revisor forte |
| 2 rodada usa a trava | sonnet | sonnet | fiação pequena, código dado |
| 3 `concessionarias/rodada.py` | sonnet | opus | aspas do `cmd.exe` e leitura incremental de arquivo são onde mora o defeito |
| 4 aba | sonnet | sonnet | tela seguindo o padrão das outras abas |
| 5 fiação no app e esteira | sonnet | opus | esquecer uma lista da esteira = app que não abre no usuário |

## Review Focus

1. **Rodada agendada encontra uma manual rodando** (o botão às 12h20, a tarefa às 12h30): a agendada tem de ESPERAR (até 90 min) e não desistir, senão o Sanesc e o lançamento do dia somem calados. Teste na task 1 (`test_espera_e_entra_quando_o_outro_solta`) e o padrão `--esperar 90` na task 2.
2. **Processo da rodada morre no meio** (Finalizar tarefa, queda de luz): a trava tem de soltar sozinha. Teste na task 1 (`test_processo_morto_solta_a_trava`).
3. **Caminho com acento e espaço** (`C:\AUTOMAÇÕES MAIS CONTROLE\...`) e nome de quem disparou com `&`, `%`, aspas ou acento: o `cmd.exe` não pode quebrar nem executar pedaço do nome. Teste na task 3 (`test_comando_roda_um_bat_de_verdade_em_pasta_com_acento`).
4. **Chrome central desligado e o Anexar com o ERP aberto:** a rodada loga com a mesma credencial e derruba a sessão do app no meio de um trabalho. A aba recusa quando o Anexar está ocupado e pede confirmação quando está livre. Testes na task 4.
5. **App aberto (ou reaberto) com uma rodada já rodando** — a agendada, ou a disparada por outra pessoa: a aba diz quem está rodando e desde quando, e o botão não dispara uma segunda (que voltaria com código 3). Teste na task 4 (`test_ao_abrir_mostra_a_rodada_dos_outros`).

---

## Parte A — água e energia (`_worktrees/agua-rodada-app`)

Rodar os testes dali: `python -m pytest tests -q` (todos são puros; nenhum abre janela).

### Task 1: a trava da rodada (`coletor/trava_rodada.py`)

**Files:**
- Create: `coletor/trava_rodada.py`
- Test: `tests/test_trava_rodada.py`

**Interfaces:**
- Produces: `NOME_TRAVA = "RODADA_EM_ANDAMENTO.trava"`, `NOME_INFO = "RODADA_EM_ANDAMENTO.json"`, `CODIGO_OCUPADA = 3`, `class RodadaOcupada(Exception)` com `.info: dict`, `ler_info(pasta: Path) -> dict | None`, `descrever(info: dict | None) -> str`, `segurar(pasta: Path, *, origem: str, argumentos: list[str], esperar_s: float = 0, ao_esperar=None, dormir=time.sleep, relogio=time.monotonic)` (context manager que devolve o `info` gravado).

- [ ] **Step 1: escrever os testes que falham**

```python
# -*- coding: utf-8 -*-
"""Uma rodada por vez: a trava vale para a tarefa agendada e para o botão do app."""
import json
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "coletor"))
import trava_rodada as T  # noqa: E402


def test_segunda_rodada_recusada_com_o_que_a_primeira_gravou(tmp_path):
    with T.segurar(tmp_path, origem="agendada", argumentos=["--so", "equatorial"]):
        with pytest.raises(T.RodadaOcupada) as erro:
            with T.segurar(tmp_path, origem="app: Fulano", argumentos=[]):
                pytest.fail("entrou com a trava ocupada")
    assert erro.value.info["origem"] == "agendada"
    assert erro.value.info["argumentos"] == ["--so", "equatorial"]
    assert "agendada" in str(erro.value)


def test_solta_no_fim_e_apaga_o_info(tmp_path):
    with T.segurar(tmp_path, origem="agendada", argumentos=[]) as info:
        assert T.ler_info(tmp_path) == info
    assert T.ler_info(tmp_path) is None
    with T.segurar(tmp_path, origem="de novo", argumentos=[]):
        pass


def test_solta_mesmo_quando_a_rodada_estoura(tmp_path):
    with pytest.raises(SystemExit):
        with T.segurar(tmp_path, origem="agendada", argumentos=[]):
            raise SystemExit(1)
    with T.segurar(tmp_path, origem="depois", argumentos=[]):
        pass


def test_espera_e_entra_quando_o_outro_solta(tmp_path):
    """A agendada das 12h30 não pode desistir porque alguém apertou o botão às
    12h20: ela espera, e entra quando a outra termina."""
    primeira = T.segurar(tmp_path, origem="app: Fulano", argumentos=[])
    primeira.__enter__()
    avisos, cochilos = [], []

    def dormir(s):
        cochilos.append(s)
        primeira.__exit__(None, None, None)      # a do botão terminou

    with T.segurar(tmp_path, origem="agendada", argumentos=[], esperar_s=600,
                   ao_esperar=avisos.append, dormir=dormir) as info:
        assert info["origem"] == "agendada"
    assert len(avisos) == 1 and avisos[0]["origem"] == "app: Fulano"
    assert cochilos and all(0 < s <= 30 for s in cochilos)


def test_desiste_quando_o_prazo_acaba(tmp_path):
    agora = [0.0]

    def dormir(s):
        agora[0] += s

    with T.segurar(tmp_path, origem="agendada", argumentos=[]):
        with pytest.raises(T.RodadaOcupada):
            with T.segurar(tmp_path, origem="outra", argumentos=[], esperar_s=90,
                           dormir=dormir, relogio=lambda: agora[0]):
                pass
    assert agora[0] >= 90


def test_processo_morto_solta_a_trava(tmp_path):
    """Finalizar tarefa ou queda de luz: o sistema solta a trava junto com o
    processo, sem arquivo velho para alguém apagar à mão."""
    filho = subprocess.Popen(
        [sys.executable, "-c", textwrap.dedent(f"""
            import sys, time
            sys.path.insert(0, {str(Path(T.__file__).parent)!r})
            import trava_rodada as T
            from pathlib import Path
            with T.segurar(Path({str(tmp_path)!r}), origem="filho", argumentos=[]):
                print("dentro", flush=True)
                time.sleep(60)
        """)], stdout=subprocess.PIPE, text=True)
    try:
        assert filho.stdout.readline().strip() == "dentro"
        with pytest.raises(T.RodadaOcupada):
            with T.segurar(tmp_path, origem="eu", argumentos=[]):
                pass
    finally:
        filho.kill()
        filho.wait(10)
    with T.segurar(tmp_path, origem="eu", argumentos=[]):
        pass


def test_descrever():
    assert T.descrever(None) == "outra rodada está em andamento"
    txt = T.descrever({"origem": "app: Fulano", "inicio": "2026-10-14T05:30:00", "pid": 7})
    assert "app: Fulano" in txt and "14/10 05:30" in txt


def test_info_quebrado_nao_derruba(tmp_path):
    (tmp_path / T.NOME_INFO).write_text("{quebrado", encoding="utf-8")
    assert T.ler_info(tmp_path) is None
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/test_trava_rodada.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'trava_rodada'`.

- [ ] **Step 3: implementar**

```python
# -*- coding: utf-8 -*-
"""Uma rodada por vez (14/10/2026, plano 2 do "sistema no servidor").

Até aqui nada impedia duas rodadas juntas: a tarefa agendada e o botão do app
(ou duas pessoas no botão) rodariam o coletor, o lançamento no ERP e as
renovações em dobro, disputando os mesmos arquivos de estado.

A trava é um arquivo TRANCADO PELO SISTEMA (`msvcrt.locking`; `fcntl.flock`
fora do Windows) enquanto o processo vive. Quem morre no meio — Finalizar
tarefa, queda de luz — solta a trava junto, e não sobra arquivo velho para
apagar à mão. Por isso não há prazo de "trava velha", como em
`mc_central.trava`: uma rodada leva mais de uma hora e qualquer prazo
mentiria.

Ao lado fica `RODADA_EM_ANDAMENTO.json`, com quem segura a trava, para a
recusa dizer quem está rodando e desde quando. O app lê os dois arquivos
(`concessionarias/rodada.py`, no repositório do app): mudar um nome aqui é
mudar lá também.
"""
import contextlib
import json
import os
import time
from datetime import datetime
from pathlib import Path

NOME_TRAVA = "RODADA_EM_ANDAMENTO.trava"
NOME_INFO = "RODADA_EM_ANDAMENTO.json"
#: Código de saída da rodada que NÃO começou porque havia outra. O app o lê.
CODIGO_OCUPADA = 3
_COCHILO = 30.0


class RodadaOcupada(Exception):
    def __init__(self, info):
        self.info = info or {}
        super().__init__(descrever(info))


def _tentar(arq) -> bool:
    arq.seek(0)
    if os.name == "nt":
        import msvcrt
        try:
            msvcrt.locking(arq.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False
    import fcntl
    try:
        fcntl.flock(arq.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _soltar(arq) -> None:
    arq.seek(0)
    with contextlib.suppress(OSError):
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(arq.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(arq.fileno(), fcntl.LOCK_UN)


def ler_info(pasta) -> dict | None:
    try:
        dados = json.loads((Path(pasta) / NOME_INFO).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return dados if isinstance(dados, dict) else None


def descrever(info) -> str:
    if not info:
        return "outra rodada está em andamento"
    desde = ""
    try:
        desde = f" desde {datetime.fromisoformat(info['inicio']):%d/%m %H:%M}"
    except (KeyError, TypeError, ValueError):
        pass
    return (f"outra rodada está em andamento{desde} "
            f"({info.get('origem') or 'origem desconhecida'}, pid {info.get('pid', '?')})")


@contextlib.contextmanager
def segurar(pasta, *, origem: str, argumentos: list, esperar_s: float = 0,
            ao_esperar=None, dormir=time.sleep, relogio=time.monotonic):
    """Segura a trava durante o bloco. Ocupada: espera até `esperar_s`
    segundos (avisa `ao_esperar(info)` uma vez) e depois levanta
    `RodadaOcupada`."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    # O arquivo é aberto pelo Python, que o cria NÃO herdável (PEP 446): os
    # passos que a rodada chama por subprocess não ficam com a trava.
    arq = open(pasta / NOME_TRAVA, "a+b")
    try:
        limite = relogio() + esperar_s
        avisou = False
        while not _tentar(arq):
            resta = limite - relogio()
            if resta <= 0:
                raise RodadaOcupada(ler_info(pasta))
            if not avisou and ao_esperar is not None:
                ao_esperar(ler_info(pasta) or {})
                avisou = True
            dormir(min(_COCHILO, resta))
        info = {"pid": os.getpid(),
                "inicio": datetime.now().isoformat(timespec="seconds"),
                "origem": origem, "argumentos": list(argumentos)}
        try:
            (pasta / NOME_INFO).write_text(json.dumps(info, ensure_ascii=False),
                                           encoding="utf-8")
            yield info
        finally:
            with contextlib.suppress(OSError):
                (pasta / NOME_INFO).unlink()
            _soltar(arq)
    finally:
        arq.close()
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/test_trava_rodada.py -q`
Expected: 8 passed.

- [ ] **Step 5: commit**

```bash
git add coletor/trava_rodada.py tests/test_trava_rodada.py
git commit -m "coletor: trava de uma rodada por vez, solta pelo sistema quando o processo morre"
```

### Task 2: a rodada usa a trava (`coletor/rodada_diaria.py`)

**Files:**
- Modify: `coletor/rodada_diaria.py` (`main`, docstring do topo)
- Modify: `coletor/PLAYBOOK_RODADA_DIARIA.md` se existir (`ls coletor docs` para achar o playbook; senão `README.md`) — uma seção curta "Uma rodada por vez"
- Test: `tests/test_rodada_trava.py`

**Interfaces:**
- Consumes: `trava_rodada.segurar`, `RodadaOcupada`, `CODIGO_OCUPADA`, `descrever` (task 1).
- Produces: `rodada_diaria.py --origem TEXTO --esperar MINUTOS`; saída 3 com a linha `RODADA NÃO INICIADA: ...`; linha `disparada por: <origem>` logo abaixo do cabeçalho `=== RODADA ...`.

- [ ] **Step 1: escrever os testes que falham**

```python
# -*- coding: utf-8 -*-
"""A rodada pega a trava ANTES de mexer em qualquer arquivo, e recusa com
código 3 quando já há outra."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "coletor"))
import rodada_diaria as R  # noqa: E402
import trava_rodada as T  # noqa: E402


# BaseException de propósito: o `main` engole `Exception` em volta de
# `caminhos.organizar`/`arrumar` (só avisa e segue), e um erro comum seguiria
# rodada adentro — mexendo nas pastas de verdade do repositório.
class _Parou(BaseException):
    pass


class _Proibido(BaseException):
    pass


@pytest.fixture
def rodada(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "REL_DIR", tmp_path)

    def nada_pode_rodar(*a, **k):
        raise _Proibido("a rodada mexeu em alguma coisa")

    monkeypatch.setattr(R, "roda", nada_pode_rodar)
    monkeypatch.setattr(R.caminhos, "organizar", nada_pode_rodar)
    monkeypatch.setattr(R.caminhos, "arrumar", nada_pode_rodar)
    return tmp_path


def test_recusa_com_codigo_3_quando_ha_outra(rodada, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["rodada_diaria.py", "--forcar", "--esperar", "0",
                                      "--origem", "app: Fulano"])
    with T.segurar(rodada, origem="agendada", argumentos=[]):
        with pytest.raises(SystemExit) as fim:
            R.main()
    assert fim.value.code == T.CODIGO_OCUPADA
    saida = capsys.readouterr().out
    assert "RODADA NÃO INICIADA" in saida and "agendada" in saida


def test_trava_vem_antes_de_organizar_e_grava_quem_disparou(rodada, monkeypatch, capsys):
    vistos = {}

    def organizar(raiz):
        vistos["info"] = json.loads((rodada / T.NOME_INFO).read_text(encoding="utf-8"))
        raise _Parou

    monkeypatch.setattr(R.caminhos, "organizar", organizar)
    monkeypatch.setattr(sys, "argv", ["rodada_diaria.py", "--forcar", "--origem", "app: Fulano"])
    with pytest.raises(_Parou):
        R.main()
    assert vistos["info"]["origem"] == "app: Fulano"
    assert "--forcar" in vistos["info"]["argumentos"]
    assert "disparada por: app: Fulano" in capsys.readouterr().out
    assert T.ler_info(rodada) is None                  # soltou ao sair


def test_agendada_espera_90_minutos_por_padrao(rodada, monkeypatch):
    pedidos = {}

    class _Trava:
        def __enter__(self):
            raise T.RodadaOcupada({"origem": "app: Fulano"})

        def __exit__(self, *a):
            return False

    def segurar(pasta, **kw):
        pedidos.update(kw)
        return _Trava()

    monkeypatch.setattr(R.trava_rodada, "segurar", segurar)
    monkeypatch.setattr(sys, "argv", ["rodada_diaria.py"])
    with pytest.raises(SystemExit):
        R.main()
    assert pedidos["esperar_s"] == 90 * 60
    assert pedidos["origem"] == "agendada"
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/test_rodada_trava.py -q`
Expected: FAIL (`--esperar` desconhecido / `R.trava_rodada` não existe).

- [ ] **Step 3: implementar**

Em `coletor/rodada_diaria.py`:

1. Import junto dos outros locais: `import trava_rodada  # noqa: E402  (coletor/trava_rodada.py — mesma pasta)`.
2. No `argparse`, depois de `--so`:

```python
    ap.add_argument("--origem", default="agendada",
                    help="quem disparou (o app passa 'app: <nome>'); vai para o resumo e para a trava")
    ap.add_argument("--esperar", type=float, default=90,
                    help="minutos esperando outra rodada terminar antes de desistir "
                         "(0 = desiste na hora; o botão do app usa 0)")
```

3. Trocar o corpo de `main()` depois de `args = ap.parse_args()` por:

```python
    # 14/10/2026: uma rodada por vez, para a agendada e para o botão do app.
    # A trava vem ANTES de organizar a pasta: duas rodadas movendo os mesmos
    # arquivos já é o estrago que ela evita.
    def _esperando(info):
        diz(f"{trava_rodada.descrever(info)} — esperando até {args.esperar:g} min")

    try:
        with trava_rodada.segurar(REL_DIR, origem=args.origem, argumentos=sys.argv[1:],
                                  esperar_s=args.esperar * 60, ao_esperar=_esperando):
            _rodada(args)
    except trava_rodada.RodadaOcupada as e:
        diz(f"RODADA NÃO INICIADA: {e}")
        sys.exit(trava_rodada.CODIGO_OCUPADA)


def _rodada(args):
    mes = args.mes
    inicio = datetime.now()
    diz(f"=== RODADA {inicio:%d/%m/%Y %H:%M} (mês {mes}) ===")
    diz(f"disparada por: {args.origem}")
    diz(f"python: {sys.executable}")
    # (daqui para baixo, o corpo antigo de main(), sem mudança)
```

(O comentário acima marca onde entra o corpo existente de `main()` movido sem alteração — do `diz(f"python: {sys.executable}")` até o `sys.exit(codigo_saida)` final. O `sys.exit` de dentro sai pelo `finally` da trava e a solta.)

4. Docstring do topo: acrescentar o item "Uma rodada por vez: `trava_rodada.py`; recusada sai com código 3; a agendada espera até 90 min (`--esperar`)" e trocar a linha de uso por `Uso: python rodada_diaria.py [--mes AAAA-MM] [--forcar] [--so equatorial] [--origem TEXTO] [--esperar MIN]`.
5. Playbook/README: seção "Uma rodada por vez" com: o que a trava faz, os dois arquivos em `relatorios/`, código 3, `--esperar`, e "não apague o `.trava` à mão: ele não trava nada sozinho, quem trava é o processo vivo".

- [ ] **Step 4: rodar e ver passar, e a suíte toda**

Run: `python -m pytest tests -q`
Expected: tudo verde (os testes antigos de `rodada_diaria` continuam passando).

- [ ] **Step 5: commit**

```bash
git add coletor/rodada_diaria.py tests/test_rodada_trava.py <playbook ou README>
git commit -m "rodada: uma por vez — recusa com código 3, agendada espera 90 min, grava quem disparou"
```

---

## Parte B — app (`_worktrees/app-agua-energia`)

Testes puros desta parte: `python -m pytest tests/test_concessionarias_rodada.py tests/test_imports_do_motor.py tests/test_nomes_de_modulo.py tests/test_usuarios.py -q` e `ruff check .`. **Não rode** `pytest tests` inteiro nem arquivo que use a fixture `raiz`.

### Task 3: a parte sem tela (`concessionarias/rodada.py`)

**Files:**
- Create: `concessionarias/__init__.py` (vazio, com docstring de uma linha)
- Create: `concessionarias/rodada.py`
- Test: `tests/test_concessionarias_rodada.py`

**Interfaces:**
- Produces: `PASTA_PADRAO: Path`, `CODIGO_OCUPADA = 3`, `NOME_TRAVA`, `NOME_INFO`, `pasta_agua_energia() -> Path | None`, `origem_segura(nome: str) -> str`, `linha_de_comando(*, so: str | None, origem: str) -> str`, `iniciar(pasta: Path, *, so: str | None, origem: str) -> subprocess.Popen`, `caminho_do_log(pasta: Path) -> Path`, `class Leitor(caminho: Path)` com `.novas() -> list[str]`, `resumo_do_log(linhas: list[str]) -> Path | None`, `em_andamento(pasta: Path) -> dict | None` (`{}` quando trancada sem info), `descrever(info: dict | None) -> str`, `veredito(rc: int) -> str`.

- [ ] **Step 1: escrever os testes que falham**

```python
# -*- coding: utf-8 -*-
"""A rodada do água e energia disparada pelo app: comando, andamento e resumo."""
import os
import sys
from pathlib import Path

import pytest

from concessionarias import rodada as R


def _instalar(raiz: Path) -> Path:
    (raiz / "coletor" / "logs").mkdir(parents=True)
    (raiz / "relatorios").mkdir()
    return raiz


def test_pasta_pela_variavel_e_desligada(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_AGUA_ENERGIA", "off")
    assert R.pasta_agua_energia() is None
    monkeypatch.setenv("MC_AGUA_ENERGIA", str(tmp_path))
    assert R.pasta_agua_energia() is None            # sem o .bat não é instalação
    _instalar(tmp_path)
    (tmp_path / "coletor" / "rodada_diaria.bat").write_text("@echo off\n")
    assert R.pasta_agua_energia() == tmp_path


@pytest.mark.parametrize("nome, esperado", [
    ("Fulano", "app: Fulano"),
    ("Fulâno de Tál", "app: Fulano de Tal"),
    ('Fu"la&no|%PATH%^!<x>', "app: FulanoPATHx"),
    ("", "app: sem nome"),
])
def test_origem_segura(nome, esperado):
    assert R.origem_segura(nome) == esperado


def test_linha_de_comando():
    linha = R.linha_de_comando(so=None, origem="app: Fulano")
    assert linha == 'cmd.exe /d /s /c "rodada_diaria.bat --forcar --esperar 0 --origem "app: Fulano""'
    assert R.linha_de_comando(so="equatorial", origem="app: Fulano").endswith(
        '--origem "app: Fulano" --so equatorial"')
    with pytest.raises(ValueError):
        R.linha_de_comando(so="sanesc; del", origem="app: Fulano")


@pytest.mark.skipif(os.name != "nt", reason="cmd.exe só existe no Windows")
def test_comando_roda_um_bat_de_verdade_em_pasta_com_acento(tmp_path):
    """O caminho de produção tem acento e espaço; o nome de quem disparou passa
    por `origem_segura`. Um .bat dublê grava os argumentos que recebeu."""
    raiz = _instalar(tmp_path / "AUTOMAÇÕES TESTE" / "agua_energia")
    (raiz / "coletor" / "rodada_diaria.bat").write_text(
        "@echo off\r\n"
        'cd /d "%~dp0"\r\n'
        'echo args=[%*]>> "logs\\rodada_agendada.log"\r\n'
        "exit /b 3\r\n", encoding="ascii")
    proc = R.iniciar(raiz, so="equatorial", origem=R.origem_segura('Fu"la & no'))
    assert proc.wait(30) == 3
    log = R.caminho_do_log(raiz).read_text(encoding="ascii")
    assert 'args=[--forcar --esperar 0 --origem "app: Fula  no" --so equatorial]' in log


def test_leitor_so_le_o_que_chegou_depois_e_guarda_a_linha_pela_metade(tmp_path):
    log = tmp_path / "rodada_agendada.log"
    log.write_text("de ontem\n", encoding="utf-8")
    leitor = R.Leitor(log)
    assert leitor.novas() == []
    with open(log, "a", encoding="utf-8") as f:
        f.write("=== RODADA 14/10/2026 10:00 ===\n[2/4] Equat")
    assert leitor.novas() == ["=== RODADA 14/10/2026 10:00 ==="]
    with open(log, "a", encoding="utf-8") as f:
        f.write("orial:\n")
    assert leitor.novas() == ["[2/4] Equatorial:"]


def test_leitor_com_log_que_ainda_nao_existe(tmp_path):
    log = tmp_path / "logs" / "rodada_agendada.log"
    leitor = R.Leitor(log)
    assert leitor.novas() == []
    log.parent.mkdir()
    log.write_text("primeira\n", encoding="utf-8")
    assert leitor.novas() == ["primeira"]


def test_resumo_do_log_pega_o_ultimo():
    linhas = ["resumo salvo em C:\\x\\rodada_1.txt", "e-mail: enviado",
              "resumo salvo em C:\\x\\rodada_2.txt"]
    assert R.resumo_do_log(linhas) == Path("C:\\x\\rodada_2.txt")
    assert R.resumo_do_log(["RODADA NÃO INICIADA: outra"]) is None


@pytest.mark.skipif(os.name != "nt", reason="trava do Windows")
def test_em_andamento_le_a_trava_de_verdade(tmp_path):
    import msvcrt
    raiz = _instalar(tmp_path)
    assert R.em_andamento(raiz) is None              # nunca rodou
    trava = raiz / "relatorios" / R.NOME_TRAVA
    with open(trava, "a+b") as f:
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
        (raiz / "relatorios" / R.NOME_INFO).write_text(
            '{"origem": "agendada", "inicio": "2026-10-14T05:30:00", "pid": 9}',
            encoding="utf-8")
        assert R.em_andamento(raiz)["origem"] == "agendada"
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    assert R.em_andamento(raiz) is None              # info velho, trava solta


def test_veredito_e_descrever():
    assert "sem alertas" in R.veredito(0)
    assert "ALERTA" in R.veredito(1)
    assert "já estava" in R.veredito(R.CODIGO_OCUPADA)
    assert "erro" in R.veredito(9009)
    assert "14/10 05:30" in R.descrever({"origem": "agendada", "inicio": "2026-10-14T05:30:00"})
    assert R.descrever({}) == "uma rodada está em andamento"
```

- [ ] **Step 2: rodar e ver falhar**

Run: `python -m pytest tests/test_concessionarias_rodada.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'concessionarias'`.

- [ ] **Step 3: implementar**

```python
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
ligado (`mc_central.py` de lá) ou abre o próprio Chrome quando não está — e é
a tela (`frame.py`) que avisa do segundo caso.
"""
from __future__ import annotations

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
_RESUMO = re.compile(r"resumo salvo em (.+?)\s*$")


def pasta_agua_energia() -> Path | None:
    """A instalação do água e energia, ou None (desligada ou ausente)."""
    valor = (os.environ.get("MC_AGUA_ENERGIA") or "").strip()
    if valor.lower() == "off":
        return None
    pasta = Path(valor) if valor else PASTA_PADRAO
    return pasta if (pasta / "coletor" / "rodada_diaria.bat").is_file() else None


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
    `subprocess` poria aspas onde o `cmd` não espera."""
    if so is not None and so not in SO_PERMITIDOS:
        raise ValueError(f"--so desconhecido: {so!r}")
    if '"' in origem:
        raise ValueError("origem com aspas: passe por origem_segura")
    args = f'--forcar --esperar 0 --origem "{origem}"'
    if so:
        args += f" --so {so}"
    return f'cmd.exe /d /s /c "rodada_diaria.bat {args}"'


def iniciar(pasta: Path, *, so: str | None, origem: str) -> subprocess.Popen:
    """Dispara a rodada e volta na hora. O processo segue mesmo que o app
    feche; a trava de lá impede a segunda."""
    return subprocess.Popen(linha_de_comando(so=so, origem=origem),
                            cwd=str(Path(pasta) / "coletor"),
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, creationflags=_SEM_JANELA)


def caminho_do_log(pasta: Path) -> Path:
    return Path(pasta) / "coletor" / "logs" / "rodada_agendada.log"


class Leitor:
    """Lê do log só o que chegou depois de ser criado, linha inteira por vez.

    O `.bat` manda tudo para o MESMO log da tarefa agendada, então o começo
    do arquivo é das rodadas de antes."""

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
    """O info de quem roda agora ({} se trancada sem info), ou None.

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
        with open(trava, "a+b") as f:
            f.seek(0)
            try:
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                try:
                    dados = json.loads((rel / NOME_INFO).read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    dados = {}
                return dados if isinstance(dados, dict) else {}
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        return None
    return None


def descrever(info: dict | None) -> str:
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
```

- [ ] **Step 4: rodar e ver passar**

Run: `python -m pytest tests/test_concessionarias_rodada.py -q` e `ruff check concessionarias tests/test_concessionarias_rodada.py`
Expected: 13 passed (os `skipif` rodam no Windows); ruff limpo.

- [ ] **Step 5: commit**

```bash
git add concessionarias/__init__.py concessionarias/rodada.py tests/test_concessionarias_rodada.py
git commit -m "concessionarias: disparar a rodada do água e energia e ler andamento e resumo"
```

### Task 4: a aba (`concessionarias/frame.py`)

**Files:**
- Create: `concessionarias/frame.py`
- Test: `tests/test_concessionarias_frame.py` (usa a fixture `raiz` — **o implementador NÃO roda**; escreve, roda `ruff` e `python -c "import concessionarias.frame"`, e o coordenador roda com a tela livre)

**Interfaces:**
- Consumes: tudo de `concessionarias.rodada` (task 3); `widgets.Cabecalho(pai, titulo, apoio, trilha)` com `.acoes`, `widgets.Cartao(pai, titulo, numero)`, `widgets.AreaRolavel`, `widgets.Botao(pai, texto, papel=, command=, state=)`, `widgets.estilo_log(texto)`, `widgets.registro_elastico(cartao, texto)`, `widgets.px` — **confira cada assinatura com `grep -n "^class X\|^def X" widgets.py` antes de usar; se alguma não bater, siga a de `acessorias/frame.py`**; `nuvem.auditoria.registrar(acao, detalhe, *, aba, resultado)`; `erp.central.ligado()`.
- Produces: `class AguaEnergiaFrame(ttk.Frame)` com `__init__(self, master, anx=None, *, pasta=..., iniciar=None, central_ligado=None, perguntar=None, registrar=None)`, `rodar()`, `ocupado() -> str | None`, `ao_abrir()`, `_acompanhar()`, atributos `v_so: tk.StringVar` (`"completa"`/`"equatorial"`), `v_status: tk.StringVar`, `b_rodar`, `log: tk.Text`, `resumo: tk.Text`.

- [ ] **Step 1: escrever os testes (que falhariam)**

```python
# -*- coding: utf-8 -*-
"""A aba Água e energia: dispara, acompanha, mostra o resumo e registra."""
import tkinter as tk
from pathlib import Path

import pytest

from concessionarias import frame as F
from concessionarias import rodada as R


class _Proc:
    def __init__(self, codigos):
        self._codigos = list(codigos)

    def poll(self):
        return self._codigos.pop(0) if self._codigos else 0


def _instalacao(tmp_path) -> Path:
    raiz = tmp_path / "agua_energia"
    (raiz / "coletor" / "logs").mkdir(parents=True)
    (raiz / "relatorios").mkdir()
    (raiz / "coletor" / "rodada_diaria.bat").write_text("@echo off\n")
    return raiz


def _aba(raiz_tk, pasta, **kw):
    chamadas = {"iniciar": [], "registrar": [], "perguntar": []}

    def iniciar(p, *, so, origem):
        chamadas["iniciar"].append((p, so, origem))
        return kw.pop("_proc", _Proc([None, 0]))

    def registrar(acao, detalhe="", **k):
        chamadas["registrar"].append((acao, detalhe, k))

    def perguntar(titulo, texto):
        chamadas["perguntar"].append(texto)
        return kw.pop("_resposta", True)

    aba = F.AguaEnergiaFrame(raiz_tk, None if "anx" not in kw else kw.pop("anx"),
                             pasta=pasta, iniciar=iniciar, registrar=registrar,
                             perguntar=perguntar,
                             central_ligado=kw.pop("central_ligado", lambda: True),
                             quem=lambda: "Fulano")
    return aba, chamadas


def test_sem_instalacao_o_botao_fica_desligado(raiz):
    aba, ch = _aba(raiz, None)
    assert str(aba.b_rodar["state"]) == "disabled"
    assert "não está instalado" in aba.v_status.get()
    aba.rodar()
    assert ch["iniciar"] == []


def test_dispara_acompanha_e_mostra_o_resumo(raiz, tmp_path):
    pasta = _instalacao(tmp_path)
    resumo = pasta / "relatorios" / "rodada_teste.txt"
    resumo.write_text("=== RODADA ===\nsaúde: sem alertas\n", encoding="utf-8")
    aba, ch = _aba(raiz, pasta, _proc=_Proc([None, 0]))
    aba.v_so.set("equatorial")
    aba.rodar()
    assert ch["iniciar"] == [(pasta, "equatorial", "app: Fulano")]
    assert aba.ocupado()
    with open(R.caminho_do_log(pasta), "a", encoding="utf-8") as f:
        f.write("[2/4] Equatorial:\n")
    aba._acompanhar()                                  # poll -> None: segue
    assert "[2/4] Equatorial:" in aba.log.get("1.0", "end")
    with open(R.caminho_do_log(pasta), "a", encoding="utf-8") as f:
        f.write(f"resumo salvo em {resumo}\n")
    aba._acompanhar()                                  # poll -> 0: terminou
    assert aba.ocupado() is None
    assert "saúde: sem alertas" in aba.resumo.get("1.0", "end")
    assert "sem alertas" in aba.v_status.get()
    acoes = [a for a, _, _ in ch["registrar"]]
    assert acoes == ["Água e energia: rodada disparada", "Água e energia: rodada terminou"]
    assert "--so equatorial" in ch["registrar"][0][1]


def test_recusada_porque_ja_havia_outra(raiz, tmp_path):
    pasta = _instalacao(tmp_path)
    aba, ch = _aba(raiz, pasta, _proc=_Proc([R.CODIGO_OCUPADA]))
    aba.rodar()
    aba._acompanhar()
    assert "já estava em andamento" in aba.v_status.get()
    assert ch["registrar"][-1][2].get("resultado") == "aviso"


def test_central_desligado_e_anexar_ocupado_recusa(raiz, tmp_path):
    class _Anx:
        def ocupado(self):
            return "Anexando comprovantes"

    aba, ch = _aba(raiz, _instalacao(tmp_path), anx=_Anx(),
                   central_ligado=lambda: False)
    aba.rodar()
    assert ch["iniciar"] == [] and ch["perguntar"] == []
    assert "Anexando comprovantes" in aba.v_status.get()


def test_central_desligado_pede_confirmacao(raiz, tmp_path):
    aba, ch = _aba(raiz, _instalacao(tmp_path), central_ligado=lambda: False,
                   _resposta=False)
    aba.rodar()
    assert ch["iniciar"] == []
    assert "sessão" in ch["perguntar"][0]


def test_central_ligado_nao_pergunta(raiz, tmp_path):
    aba, ch = _aba(raiz, _instalacao(tmp_path))
    aba.rodar()
    assert ch["perguntar"] == [] and len(ch["iniciar"]) == 1


def test_ao_abrir_mostra_a_rodada_dos_outros(raiz, tmp_path, monkeypatch):
    pasta = _instalacao(tmp_path)
    monkeypatch.setattr(F.rodada, "em_andamento",
                        lambda p: {"origem": "agendada", "inicio": "2026-10-14T05:30:00"})
    aba, ch = _aba(raiz, pasta)
    aba.ao_abrir()
    assert "agendada" in aba.v_status.get()
    aba.rodar()
    assert ch["iniciar"] == []                          # não dispara a segunda
```

(O `quem=` é o parâmetro que devolve o nome de quem está no app; acrescente-o à assinatura de `Produces`: `quem=None`, padrão `nuvem.sessao.quem().como_chamar` com `try/except` devolvendo `""`. Confira com `grep -n "def quem\|como_chamar" nuvem/sessao.py nuvem/usuarios.py` qual objeto tem `como_chamar`; se `sessao.quem()` não o tiver, use `primeiro_nome`.)

- [ ] **Step 2: conferir que o arquivo de teste importa e falha por falta do módulo**

Run: `python -c "import ast,sys; ast.parse(open('tests/test_concessionarias_frame.py',encoding='utf-8').read())"` e `python -c "import concessionarias.frame"`
Expected: o primeiro passa; o segundo falha com `ModuleNotFoundError`. (Não rode o pytest deste arquivo.)

- [ ] **Step 3: implementar**

```python
# -*- coding: utf-8 -*-
"""Aba Água e energia: roda a rodada do coletor a qualquer hora (plano 2).

O trabalho é de OUTRO processo (`coletor\\rodada_diaria.bat`, o mesmo da
tarefa agendada). Esta aba só dispara, acompanha o log e mostra o resumo —
não tem navegador nem thread própria, e por isso não tem `fechar()`: fechar o
app não para a rodada, e a trava de lá impede uma segunda.

Chrome central LIGADO: a rodada abre a aba dela no Chrome do porteiro e nada
cai. DESLIGADO: ela abre o próprio Chrome e entra no ERP com o login do app —
uma sessão por usuário, e a do app cai. Por isso, desligado, a aba recusa
enquanto o Anexar trabalha e pede confirmação quando ele está livre.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import widgets
from widgets import px

from . import rodada

_INTERVALO_MS = 1000
_PADRAO = object()


def _central_ligado() -> bool:
    try:
        from erp import central
        return central.ligado()
    except Exception:                                        # noqa: BLE001
        return False


def _quem() -> str:
    try:
        from nuvem import sessao
        return sessao.quem().como_chamar
    except Exception:                                        # noqa: BLE001
        return ""


def _registrar(acao, detalhe="", **kw):
    from nuvem import auditoria
    auditoria.registrar(acao, detalhe, **kw)


class AguaEnergiaFrame(ttk.Frame):
    def __init__(self, master, anx=None, *, pasta=_PADRAO, iniciar=None,
                 central_ligado=None, perguntar=None, registrar=None, quem=None):
        super().__init__(master)
        self.anx = anx
        self.pasta = rodada.pasta_agua_energia() if pasta is _PADRAO else pasta
        self._iniciar = iniciar or rodada.iniciar
        self._central_ligado = central_ligado or _central_ligado
        self._perguntar = perguntar or (lambda t, m: messagebox.askyesno(t, m, parent=self))
        self._registrar = registrar or _registrar
        self._quem = quem or _quem
        self.proc = None
        self.leitor = None
        self._linhas: list[str] = []
        self._pedido = ""
        self.v_so = tk.StringVar(value="completa")
        self.v_status = tk.StringVar()
        self._build()
        if self.pasta is None:
            self.b_rodar.configure(state="disabled")
            self.v_status.set("O água e energia não está instalado nesta máquina "
                              "(ou MC_AGUA_ENERGIA=off).")
        else:
            self.v_status.set("Pronto. A tarefa agendada continua rodando nos horários dela.")

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = px(widgets.PADX)
        self.cab = widgets.Cabecalho(
            self, "Água e energia",
            "Roda agora a rodada da Equatorial e da Sanesc — a mesma da tarefa "
            "agendada, mesmo fora do horário, fim de semana ou feriado.",
            trilha="Diário  ›  Água e energia")
        self.cab.pack(fill="x", padx=PADX, pady=px((16, 12)))
        self.b_rodar = widgets.Botao(self.cab.acoes, "Rodar agora", papel="acao",
                                     command=self.rodar)
        self.b_rodar.pack(side="left")
        corpo = widgets.AreaRolavel(self)

        c1 = widgets.Cartao(corpo, "O que rodar", 1)
        c1.pack(fill="x", padx=PADX, pady=px((0, 12)))
        for valor, texto in (("completa", "Rodada completa: Equatorial, Sanesc, "
                                           "lançamento no ERP e renovações"),
                             ("equatorial", "Só a Equatorial (sem ERP)")):
            ttk.Radiobutton(c1.corpo, text=texto, value=valor,
                            variable=self.v_so).pack(anchor="w")
        ttk.Label(c1.corpo, textvariable=self.v_status,
                  wraplength=px(720)).pack(anchor="w", pady=px((8, 0)))

        c2 = widgets.Cartao(corpo, "Andamento", 2)
        c2.pack(fill="both", expand=True, padx=PADX, pady=px((0, 12)))
        self.log = tk.Text(c2.corpo, height=12, wrap="word")
        widgets.estilo_log(self.log)
        self.log.pack(fill="both", expand=True)

        c3 = widgets.Cartao(corpo, "Resumo da rodada", 3)
        c3.pack(fill="both", expand=True, padx=PADX, pady=px((0, 16)))
        self.resumo = tk.Text(c3.corpo, height=12, wrap="word")
        widgets.estilo_log(self.resumo)
        self.resumo.pack(fill="both", expand=True)

    # ------------------------------------------------------------- a rodada
    def ocupado(self) -> str | None:
        if self.proc is not None:
            return "Rodada de água e energia"
        return None

    def ao_abrir(self):
        if self.proc is None and self.pasta is not None:
            info = rodada.em_andamento(self.pasta)
            if info is not None:
                self.v_status.set(f"{rodada.descrever(info)}. Espere ela terminar.")

    def rodar(self):
        if self.pasta is None or self.proc is not None:
            return
        info = rodada.em_andamento(self.pasta)
        if info is not None:
            self.v_status.set(f"{rodada.descrever(info)}. Espere ela terminar.")
            return
        so = None if self.v_so.get() == "completa" else self.v_so.get()
        if so is None and not self._central_ligado():
            tarefa = self.anx.ocupado() if self.anx is not None else None
            if tarefa:
                self.v_status.set(f"O Anexar está usando o ERP ({tarefa}). Sem o Chrome "
                                  "central, a rodada derrubaria essa sessão: espere terminar.")
                return
            if not self._perguntar(
                    "Água e energia",
                    "O Chrome central está desligado: a rodada vai entrar no ERP com o "
                    "login do app, e a sessão do ERP aberta aqui no app cai.\n\nRodar mesmo assim?"):
                return
        origem = rodada.origem_segura(self._quem())
        self._pedido = "--forcar" + (f" --so {so}" if so else "")
        self.leitor = rodada.Leitor(rodada.caminho_do_log(self.pasta))
        self._linhas = []
        try:
            self.proc = self._iniciar(self.pasta, so=so, origem=origem)
        except OSError as e:
            self.v_status.set(f"Não consegui iniciar a rodada: {e}")
            return
        self._registrar("Água e energia: rodada disparada", self._pedido,
                        aba="agu", resultado="ok")
        self.b_rodar.configure(state="disabled")
        self.log.delete("1.0", "end")
        self.resumo.delete("1.0", "end")
        self.v_status.set(f"Rodando ({self._pedido}). Pode trocar de aba; o andamento "
                          "continua aqui.")
        self.after(_INTERVALO_MS, self._acompanhar)

    def _acompanhar(self):
        if self.proc is None:
            return
        for linha in self.leitor.novas():
            self._linhas.append(linha)
            self.log.insert("end", linha + "\n")
            self.log.see("end")
        rc = self.proc.poll()
        if rc is None:
            self.after(_INTERVALO_MS, self._acompanhar)
            return
        for linha in self.leitor.novas():
            self._linhas.append(linha)
            self.log.insert("end", linha + "\n")
        self.proc = None
        self.b_rodar.configure(state="normal")
        texto = rodada.veredito(rc)
        self.v_status.set(f"A rodada {texto}.")
        caminho = rodada.resumo_do_log(self._linhas)
        try:
            conteudo = caminho.read_text(encoding="utf-8") if caminho else ""
        except OSError as e:
            conteudo = f"(não consegui ler {caminho}: {e})"
        self.resumo.insert("1.0", conteudo or "(esta rodada não gravou resumo)")
        resultado = "ok" if rc == 0 else ("aviso" if rc in (1, rodada.CODIGO_OCUPADA) else "erro")
        self._registrar("Água e energia: rodada terminou",
                        f"{self._pedido} — {texto}", aba="agu", resultado=resultado)
```

Antes de dar por pronto: `grep -n "corpo" widgets.py | grep -n "class Cartao" -A40` — se o `Cartao` não expõe `.corpo`, empacote os filhos direto no cartão, como `acessorias/frame.py` faz. Mesma conferência para `AreaRolavel` (onde os cartões são empacotados: no próprio objeto ou em `.interno`?), copiando o uso de `acessorias/frame.py`. Se `registro_elastico` for o padrão das abas para o Registro, use-o no `self.log`.

- [ ] **Step 4: verificar sem abrir janela**

Run: `python -c "import concessionarias.frame"` e `ruff check concessionarias tests/test_concessionarias_frame.py`
Expected: importa; ruff limpo. **Pare aqui e relate**: o coordenador roda `python -m pytest tests/test_concessionarias_frame.py -q` com a tela livre (esperado: 7 passed).

- [ ] **Step 5: commit**

```bash
git add concessionarias/frame.py tests/test_concessionarias_frame.py
git commit -m "concessionarias: aba Água e energia — dispara, acompanha, resumo e auditoria"
```

### Task 5: fiação no app, na esteira e na documentação

**Files:**
- Modify: `comprovantes_app.py` (import da aba, `quadros`, grupo DIÁRIO, `_quem_trabalha`)
- Modify: `.github/workflows/build.yml` (copiar `concessionarias/*.py` para `codigo_embutido/concessionarias/`, junto das outras pastas)
- Modify: `motor_minimo.txt` — **tocar sem mudar a versão** (hoje `v2.0.233` sem fim de linha: acrescente o fim de linha). Mexer no `build.yml` dispara a trava mecânica do job `motor`; subir uma unidade pediria um exe que não existe (o exe reaproveitado é o da v2.0.233) e a build pararia. É o caso "Quando só a esteira muda e o mínimo JÁ é a última release" do `CLAUDE.md`.
- Modify: `tests/test_imports_do_motor.py` (lista de pacotes: acrescentar `"concessionarias"`)
- Modify: `tests/test_registro_visivel.py` (`_montar("agu", lambda: AguaEnergiaFrame(conteudo, pasta=None))` e `"agu": "Água e energia"` em `ABAS`)
- Modify: `CLAUDE.md` (as listas de pacotes do `codigo.zip` e do "chegam sozinhas ao usuário"), `README.md`/`docs/ARQUITETURA.md`/`docs/RECUPERACAO.md` onde listam as abas ou pacotes
- Create: `.claude/rules/arquitetura-concessionarias.md`
- Modify: `docs/superpowers/plans/2026-10-14-sistema-no-servidor-roteiro.md` (linha do plano 2: arquivo `2026-10-14-agua-energia-pelo-app.md`)

**Interfaces:**
- Consumes: `AguaEnergiaFrame(master, anx)` e `.ocupado()` (task 4).

- [ ] **Step 1: achar TODAS as listas antes de editar**

Run: `grep -rn "acessorias" --include=*.py --include=*.yml --include=*.md --include=*.txt . | grep -v "^./acessorias/\|^./tests/test_acess\|^./docs/superpowers/"`
Expected: a lista de onde uma pasta de aba aparece. Cada uma que liste pacotes do zip, abas do menu ou pacotes do motor ganha `concessionarias`/`agu` — inclusive `ferramentas/galeria.py` e `tests/test_nomes_de_modulo.py` se listarem abas ou módulos (leia o que cada um confere antes de mexer; `test_nomes_de_modulo.py` pode exigir nome de módulo único: `concessionarias/frame.py` e `concessionarias/rodada.py` não podem colidir com outro `frame`/`rodada` se o teste proibir — rode-o).

- [ ] **Step 2: escrever as mudanças**

`comprovantes_app.py`, junto dos outros imports de aba:

```python
from concessionarias.frame import AguaEnergiaFrame
```

Depois de `aba_bxc = ComprovantesFrame(...)`:

```python
    # Água e energia não tem navegador: a rodada é outro processo (o mesmo
    # .bat da tarefa agendada). Recebe o aba_anx só para saber se o Anexar
    # está usando o ERP quando o Chrome central está desligado.
    aba_agu = AguaEnergiaFrame(conteudo, aba_anx)
```

`quadros` ganha `"agu": aba_agu`. O grupo DIÁRIO:

```python
    _grupo("diario", "DIÁRIO", (("pag", "🗓", "Remessa/Retorno"),
                                ("con", "⚖", "Saldo de pagamentos"),
                                ("agu", "💧", "Água e energia")))
```

Em `_quem_trabalha`, antes da Separar (última):

```python
                # A rodada do água e energia é outro processo, sem navegador
                # do app — mas leva uma hora, e o ● diz onde ela está.
                lambda: ("agu", aba_agu.ocupado()),
```

`.github/workflows/build.yml`, depois do bloco de `guias/`:

```yaml
          # `concessionarias/` é a aba Água e energia (dispara a rodada do
          # coletor). Pasta nova de código = linha nova aqui.
          New-Item -ItemType Directory codigo_embutido/concessionarias | Out-Null
          Copy-Item concessionarias/*.py codigo_embutido/concessionarias/
```

`.claude/rules/arquitetura-concessionarias.md`: o que a aba faz; o contrato com o água e energia (código 3, `relatorios/RODADA_EM_ANDAMENTO.*`, "resumo salvo em", `--origem`/`--esperar`); `MC_AGUA_ENERGIA` (`off` desliga); por que monta a linha do `cmd` à mão (`/s`) e limpa a origem; Chrome central ligado × desligado; não tem `fechar()` e por quê; auditoria `"Água e energia: rodada disparada/terminou"` com `aba="agu"`.

- [ ] **Step 3: rodar os testes puros e o lint**

Run: `python -m pytest tests/test_imports_do_motor.py tests/test_nomes_de_modulo.py tests/test_usuarios.py tests/test_concessionarias_rodada.py tests/test_empacotamento.py -q` e `ruff check .`
Expected: verde; e `vermin --target=3.11 --violations concessionarias` sem violação. (`test_registro_visivel.py` usa a fixture `raiz`: fica para o coordenador.)

- [ ] **Step 4: commit**

```bash
git add comprovantes_app.py .github/workflows/build.yml motor_minimo.txt tests/ CLAUDE.md README.md docs .claude/rules/arquitetura-concessionarias.md
git commit -m "app: aba Água e energia no menu DIÁRIO, na barra de trabalho e no codigo.zip"
```

---

## Depois das tasks (coordenador)

1. Com a tela livre: `python -m pytest tests/test_concessionarias_frame.py tests/test_registro_visivel.py -q`.
2. Revisão final de cada branch; `revisor-dinheiro` no do app (toca `erp`/auditoria).
3. Push dos dois branches e os dois PRs (o do app com base `codigo/porteiro-do-erp`), cada um citando o outro.
4. **Prova ao vivo fica para o dono**: no servidor, com o central ligado, Rodar agora → o andamento aparece, o resumo aparece, a linha "Água e energia: rodada disparada" aparece na `auditoria`; um segundo clique (de outra máquina, ou a tarefa agendada no meio) recebe "já estava em andamento".
