# -*- coding: utf-8 -*-
"""O exe só contém o que o motor enxerga sendo importado.

Em 12/08/2026 o app parou de abrir nas duas máquinas, na v1.0.71: o
`widgets.py` novo fazia `from tkinter import font`, e o exe instalado não
tinha esse submódulo. O PyInstaller não embute a biblioteca padrão inteira —
ele segue os imports a partir do `motor.py`, e `tkinter.font` não estava em
nenhum. O erro aparece no `import widgets`, antes de existir janela para
mostrá-lo, então o que a pessoa vê é o app não abrir.

O que torna esse defeito caro é o desencontro: só o CÓDIGO se atualiza
sozinho. Um import novo passa nos testes (aqui a biblioteca padrão está
inteira), passa no CI, sai na release — e quebra só na máquina de quem usa,
que roda o código novo dentro de um motor velho.

Estes testes leem o `motor.py` e comparam com o que o app de fato importa.
São texto e AST, sem tela: rodam no CI como qualquer outro.
"""
import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent

#: Pastas de código que viajam no codigo.zip (ver a lista no CLAUDE.md).
_PASTAS = ("", "inicio", "baixar_comprovantes", "separar_renomear", "anexar", "aportes", "relatorios",
           "pagamentos_dia", "extratos_sicoob", "conciliacao",
           "conciliacao/erp", "contratos", "acessorias", "cnab240", "erp",
           "nuvem")

#: Não são código de aba: o motor e o atualizador rodam DENTRO do exe, onde
#: a biblioteca padrão está completa — quem os empacota é o PyInstaller.
#:
#: `nuvem/migrar.py` também fica fora, e por um motivo diferente: ele não
#: entra no codigo.zip (é ferramenta rodada à mão, no repositório), então
#: pode importar o que quiser sem passar pelo motor.
#:
#: `cli.py` e `__main__.py` são o mesmo caso do `migrar.py` com um detalhe a
#: mais: eles VIAJAM no codigo.zip (o build copia `conciliacao/*.py` e
#: `cnab240/*.py` inteiros), mas ninguém os importa — são entradas de
#: `python -m`, usadas no repositório para diagnóstico. Por isso podem usar
#: `argparse` e `getpass`, que não estão no exe: o exe nunca chega a executá-los.
#: Se um dia a interface passar a importar um deles, este teste volta a
#: acusá-los assim que a linha de import existir.
_FORA = {"motor.py", "atualizador.py", "migrar.py", "cli.py", "__main__.py"}


def _arquivos_do_app():
    for pasta in _PASTAS:
        base = _RAIZ / pasta if pasta else _RAIZ
        for arq in sorted(base.glob("*.py")):
            if arq.name not in _FORA:
                yield arq


def _submodulos_importados(arquivo: Path, pacote: str) -> set:
    """{'font', 'ttk', ...} de `from <pacote> import X` e `import <pacote>.X`."""
    achados = set()
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"), str(arquivo))
    for no in ast.walk(arvore):
        if isinstance(no, ast.ImportFrom) and no.module == pacote:
            achados |= {a.name for a in no.names}
        elif isinstance(no, ast.Import):
            for a in no.names:
                if a.name.startswith(f"{pacote}."):
                    achados.add(a.name.split(".", 1)[1].split(".")[0])
    return achados


def _modulos(pacote: str, nomes) -> set:
    """Só os nomes que são MÓDULO de verdade.

    `from tkinter import ttk, Tk` mistura submódulo com classe, e o Tk não tem
    o que ser empacotado."""
    return {n for n in nomes
            if importlib.util.find_spec(f"{pacote}.{n}") is not None}


def _no_exe(pacote: str) -> set:
    """O que o exe REALMENTE contém desse pacote.

    Não é a lista do motor.py: é ela mais tudo que esses imports arrastam, que
    é como o PyInstaller monta o pacote. `urllib.request` traz `parse` e
    `error` de graça — enquanto `tkinter.ttk`, `filedialog` e `messagebox` NÃO
    trazem o `font`, e foi essa diferença que derrubou o app na v1.0.71.

    Roda num interpretador limpo de propósito: neste aqui o pytest já importou
    meio mundo, e a resposta sairia otimista."""
    diretos = sorted(_modulos(pacote, _submodulos_importados(_RAIZ / "motor.py",
                                                             pacote)))
    codigo = (
        "import importlib, sys\n"
        f"import {pacote}\n"
        f"for s in {diretos!r}:\n"
        "    try:\n"
        f"        importlib.import_module('{pacote}.' + s)\n"
        "    except ImportError:\n"
        "        pass\n"
        f"print(' '.join(m for m in sys.modules if m.startswith('{pacote}.')))\n")
    saida = subprocess.run([sys.executable, "-c", codigo],
                           capture_output=True, text=True, timeout=120)
    assert saida.returncode == 0, saida.stderr
    return {m.split(".", 1)[1].split(".")[0] for m in saida.stdout.split()}


def test_o_exe_tem_os_submodulos_de_tkinter_que_o_app_usa():
    """O caso real: `from tkinter import font` no widgets.py.

    Submódulo que o app importa e o exe não tem: o `import` estoura antes de
    existir janela, e o que a pessoa vê é o app não abrir. Para liberar um
    novo, acrescente-o ao `_garantir_dependencias()` do motor.py — e aí é exe
    novo, com `motor_minimo.txt` subindo no MESMO push (o CI recusa a build se
    faltar).
    """
    dentro = _no_exe("tkinter")
    faltando = {}
    for arq in _arquivos_do_app():
        usados = _modulos("tkinter", _submodulos_importados(arq, "tkinter"))
        if usados - dentro:
            faltando[arq.relative_to(_RAIZ).as_posix()] = sorted(usados - dentro)
    assert not faltando, (
        "estes submódulos de tkinter não existem no exe do usuário — o app "
        f"não vai abrir: {faltando}. O exe tem {sorted(dentro)}.")


def test_o_proprio_widgets_nao_depende_de_tkinter_font():
    """A regressão exata da v1.0.71, apontada no arquivo onde ela nasceu.

    O `_garantir_fontes` fala com o Tcl direto (`font create`/`font
    configure`), que é o que o `tkinter.font` faz por baixo — e de graça some
    o `__del__` que apagava a fonte no coletor de lixo.
    """
    assert "font" not in _submodulos_importados(_RAIZ / "widgets.py", "tkinter")


#: O que a biblioteca padrão traz e que NÃO precisa estar no exe: são nomes
#: que o CPython já carrega antes de rodar qualquer linha nossa.
_SEMPRE_PRESENTES = frozenset(("sys", "builtins", "__future__"))


def _topo_no_exe() -> set:
    """Os módulos de TOPO que o exe contém.

    Mesmo método do `_no_exe`: importa num interpretador limpo exatamente o
    que o `_garantir_dependencias()` importa, e olha o que veio junto. O
    PyInstaller monta o pacote seguindo esses mesmos imports, então o que
    aparece aqui é o que vai estar lá."""
    fonte = (_RAIZ / "motor.py").read_text(encoding="utf-8")
    arvore = ast.parse(fonte, "motor.py")
    linhas = []
    for no in ast.walk(arvore):
        if isinstance(no, ast.FunctionDef) and no.name == "_garantir_dependencias":
            for filho in no.body:
                if isinstance(filho, (ast.Import, ast.ImportFrom)):
                    linhas.append(ast.unparse(filho))
    assert linhas, "não achei os imports de _garantir_dependencias no motor.py"
    codigo = ("\n".join(linhas) + "\n"
              "import sys\n"
              "print(' '.join(m for m in sys.modules if '.' not in m))\n")
    saida = subprocess.run([sys.executable, "-c", codigo],
                           capture_output=True, text=True, timeout=180)
    assert saida.returncode == 0, saida.stderr
    return set(saida.stdout.split())


def _topo_importados(arquivo: Path) -> set:
    """`import x` e `from x import y` — só o nome de topo, e só stdlib."""
    achados = set()
    arvore = ast.parse(arquivo.read_text(encoding="utf-8"), str(arquivo))
    for no in ast.walk(arvore):
        # Import DENTRO de função é adiado de propósito em várias abas (o
        # `import requests` do atualizador, o `from cnab240 import ...` da
        # remessa). Continua contando: adiado ou não, ele roda na máquina do
        # usuário e precisa existir no exe.
        if isinstance(no, ast.Import):
            achados |= {a.name.split(".")[0] for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            achados.add(no.module.split(".")[0])
    return {n for n in achados if n in sys.stdlib_module_names}


def test_o_exe_tem_os_modulos_de_topo_que_o_app_usa():
    """`import weakref` no widgets.py e o exe sem ele: o app não abre.

    É a v1.0.71 outra vez, um nível acima — lá foi `tkinter.font`, submódulo;
    aqui é o módulo inteiro. Quem estava sem cobertura era justamente este
    caso, e o redesenho de agosto/2026 acrescentou três imports de topo novos
    (`weakref`, `json`, `time`) sem nada para conferir se eles chegavam ao
    exe. Chegavam — mas por acaso, arrastados por outros.

    Para liberar um módulo que não chega: acrescente-o ao
    `_garantir_dependencias()` do motor.py — e aí é exe novo, com
    `motor_minimo.txt` subindo no MESMO push.
    """
    dentro = _topo_no_exe() | _SEMPRE_PRESENTES
    faltando = {}
    for arq in _arquivos_do_app():
        usados = _topo_importados(arq)
        if usados - dentro:
            faltando[arq.relative_to(_RAIZ).as_posix()] = sorted(usados - dentro)
    assert not faltando, (
        "estes módulos da biblioteca padrão não existem no exe do usuário — o "
        f"app não vai abrir: {faltando}")


def test_o_exe_tem_os_submodulos_de_urllib_que_o_app_usa():
    """Mesma armadilha, outro pacote — e o contraexemplo que ensina a regra.

    `conciliacao/erp/api.py` importa `urllib.error` e `urllib.parse`, e o
    motor.py não cita nenhum dos dois. Mesmo assim está tudo certo: ele importa
    `urllib.request`, que arrasta os outros. Exigir declaração DIRETA acusaria
    um defeito que não existe — por isso o teste mede o que o exe contém, e não
    o que o motor escreve."""
    dentro = _no_exe("urllib")
    faltando = {}
    for arq in _arquivos_do_app():
        usados = _modulos("urllib", _submodulos_importados(arq, "urllib"))
        if usados - dentro:
            faltando[arq.relative_to(_RAIZ).as_posix()] = sorted(usados - dentro)
    assert not faltando, f"submódulos de urllib fora do exe: {faltando}"
