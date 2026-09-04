# -*- coding: utf-8 -*-
"""
Motor do "Comprovantes — Mais Controle".

O executável é dividido em duas partes:

  MOTOR  = este arquivo + Python + bibliotecas pesadas (OCR, Playwright...).
           Muda raramente; é o exe grande.
  CÓDIGO = a lógica do app (comprovantes_app, separar_renomear, anexar/...),
           publicada como "codigo.zip" (~100 KB) em cada release.

Ao abrir, o motor põe no lugar o código que a abertura anterior deixou pronto
(local, instantâneo) e abre a janela; a conferência de release nova e o
download do zip rodam numa thread solta, enquanto a pessoa trabalha, e o que
chegar é instalado na SAÍDA do app — ver `atualizador.py`. O exe traz uma
cópia do código embutida de fábrica, então funciona offline e no primeiro uso.
Se uma release exigir motor mais novo (motor_minimo.txt), o app oferece o
download completo.

`--autoteste [pasta_do_codigo] [relatorio.txt]` é a porta que o CI usa para
provar que o app IMPORTA dentro deste exe (ver `autoteste`): não abre janela,
não toca a rede e sai com código 1 quando falta módulo.
"""
import sys
from pathlib import Path


# A armadilha desta lista: o código das abas viaja no `codigo.zip`, e o
# PyInstaller NUNCA o analisa — ele só segue os imports a partir deste arquivo.
# Então tudo que as abas importam da biblioteca padrão precisa estar declarado
# AQUI, ainda que o motor não use nada disso. O que ninguém declara não entra no
# exe, e o erro aparece no `import` da aba, antes de existir janela para
# mostrá-lo: o que a pessoa vê é o app não abrir (foi assim na v1.0.71, com o
# `tkinter.font`). Quem vigia isto é `tests/test_imports_do_motor.py`.
def _garantir_dependencias():        # nunca é chamada: só faz o PyInstaller
    import tkinter                    # noqa  enxergar e embutir estes módulos
    from tkinter import ttk, filedialog, messagebox   # noqa
    import queue, csv, unicodedata, threading         # noqa
    import tempfile, subprocess, zipfile, shutil      # noqa
    from concurrent.futures import ThreadPoolExecutor  # noqa
    import requests, pdfplumber, pypdf, openpyxl      # noqa
    import pytesseract                                # noqa
    import sv_ttk                                     # noqa
    import yaml                                       # noqa  (config da Conciliação)
    import decimal, json, urllib.request              # noqa  (conciliação: API + regras)
    import hashlib, time                              # noqa  (cnab240: histórico das remessas)
    import webbrowser, calendar, base64              # noqa  stdlib usados só pelo app
    import difflib                                    # noqa  (aportes/mc_catalogos: os "nomes parecidos" do erro)
    import ctypes.wintypes                            # noqa  (login cifrado DPAPI)
    import logging.handlers                           # noqa  (util.log: o diagnostico.log — a v2.0.159 saiu sem ele e o app nao abriu)
    from playwright.sync_api import sync_playwright   # noqa


# ------------------------------------------------------------ autoteste
def autoteste(pasta_codigo, relatorio=None) -> int:
    """Importa cada módulo do pacote de código DENTRO deste exe. 0 = tudo importou.

    A lacuna estrutural da esteira: os testes rodam na biblioteca padrão
    COMPLETA da máquina, e o que chega ao usuário é um exe com a stdlib podada
    pelo PyInstaller, que só embute o que este arquivo faz enxergar. Foi assim
    que a v1.0.71 caiu (`from tkinter import font`) e a v2.0.159 também
    (`logging.handlers`). Aqui o app é importado dentro da MESMA poda — e é o
    exe publicado quem roda isto, não um segundo exe "de fumaça" construído à
    parte, como era até 04/09/2026. Com o mesmo arquivo, o grafo é o mesmo por
    construção, e a build deixa de pagar uma segunda passada do PyInstaller.

    `pasta_codigo` é a pasta do `codigo.zip` a provar (na build, o
    `codigo_embutido` recém-montado — que pode ser MAIS NOVO que o embutido
    neste exe, quando o exe foi reaproveitado de uma release anterior). O
    relatório vai para `relatorio`, porque o exe é `--noconsole` e não tem
    onde imprimir.

    O que ele NÃO alcança, e vale saber: import escrito DENTRO de função.
    `aportes/mc_catalogos.py` faz `import difflib` no corpo do método, e
    importar o módulo não executa o método — esse caso só cai quando a pessoa
    usa a função. Quem pode guardá-lo é o AST de
    `tests/test_imports_do_motor.py`.
    """
    import ast
    import importlib

    raiz = Path(pasta_codigo).resolve()
    linhas = []

    # A MESMA ordem do `principal()`: só a raiz entra no caminho de import.
    p = str(raiz)
    if p not in sys.path:
        sys.path.insert(0, p)

    def _modulos():
        """(nome, pasta) de cada .py do pacote, como o app o importa.

        Pasta com __init__.py é pacote (`conciliacao.erp.api`); pasta sem
        __init__.py tem módulo solto, importado pelo nome cru."""
        for arq in sorted(raiz.rglob("*.py")):
            if arq.name == "__main__.py":     # roda por linha de comando
                continue
            partes, pai = [arq.stem], arq.parent
            while pai != raiz and (pai / "__init__.py").is_file():
                partes.insert(0, pai.name)
                pai = pai.parent
            if partes[-1] == "__init__":
                partes.pop()
                if not partes:
                    continue
            yield ".".join(partes), str(pai)

    def _citados():
        """Nomes que aparecem em algum `import` DENTRO do pacote.

        Separa o que o exe pode ALCANÇAR do que ele carrega sem nunca poder
        chamar: `conciliacao/cli.py` é o plano B por .bat, `aportes/
        teste_lancamento.py` roda à mão — ninguém os importa, então o que
        falta neles não chega a lugar nenhum. Já `cnab240` e `conciliacao/erp`
        não são importados no arranque, mas SÃO importados por outro módulo do
        pacote: entram no primeiro pagamento, e ali a falha custa caro. Por
        isso a regra é "quem cita quem"."""
        nomes = set()
        for arq in sorted(raiz.rglob("*.py")):
            try:
                arvore = ast.parse(arq.read_text(encoding="utf-8"), str(arq))
            except (OSError, SyntaxError):
                continue
            for no in ast.walk(arvore):
                if isinstance(no, ast.Import):
                    for a in no.names:
                        nomes.update(a.name.split("."))
                elif isinstance(no, ast.ImportFrom):
                    if no.module:
                        nomes.update(no.module.split("."))
                    nomes.update(a.name for a in no.names)
        return nomes

    citados = _citados()
    # O comprovantes_app vem primeiro: é o import que o usuário paga se falhar.
    alvos = [("comprovantes_app", p)] + list(_modulos())
    faltando, inalcancavel, outros = {}, {}, {}
    for nome, pasta in alvos:
        if pasta not in sys.path:
            sys.path.append(pasta)
        try:
            importlib.import_module(nome)
        except ImportError as e:
            alcancavel = (nome == "comprovantes_app"
                          or nome.split(".")[-1] in citados)
            alvo = faltando if alcancavel else inalcancavel
            alvo[nome] = "%s: %s" % (type(e).__name__, e)
        except BaseException as e:       # noqa: BLE001
            outros[nome] = "%s: %s" % (type(e).__name__, e)

    for nome in sorted(inalcancavel):
        # Ferramenta de linha de comando dentro do zip: nenhum caminho do exe
        # chega ali, então falta de módulo não derruba release.
        linhas.append("AVISO  %s (ninguem o importa) -- %s"
                      % (nome, inalcancavel[nome]))
    for nome in sorted(outros):
        # Não é falta de módulo: é o módulo reclamando de ambiente (arquivo de
        # cadastro que só existe na máquina de quem usa, por exemplo).
        linhas.append("AVISO  %s -- %s" % (nome, outros[nome]))
    if faltando:
        linhas.append("")
        linhas.append("O exe NAO tem modulos que estas partes do app importam:")
        for nome in sorted(faltando):
            linhas.append("  %s -- %s" % (nome, faltando[nome]))
        linhas.append("")
        linhas.append("E a falha da v1.0.71 (tkinter.font) de novo: o app nao")
        linhas.append("abre, e o erro aparece antes de existir janela. Declare")
        linhas.append("o import no _garantir_dependencias() do motor.py e suba")
        linhas.append("o motor_minimo.txt no MESMO push.")
        codigo = 1
    else:
        linhas.append("autoteste: %d modulos importados dentro do exe -- ok"
                      % (len(alvos) - len(inalcancavel) - len(outros)))
        codigo = 0

    texto = "\n".join(linhas) + "\n"
    if relatorio:
        Path(relatorio).write_text(texto, encoding="utf-8")
    print(texto, end="")                 # nulo no exe --noconsole; útil no CI
    return codigo


def _autoteste_da_linha_de_comando() -> int:
    """`--autoteste [pasta] [relatorio]`; sem pasta, o código embutido."""
    i = sys.argv.index("--autoteste")
    resto = sys.argv[i + 1:]
    base = getattr(sys, "_MEIPASS", None)
    pasta = resto[0] if resto else (
        Path(base) / "codigo_embutido" if base
        else Path(__file__).resolve().parent)
    relatorio = resto[1] if len(resto) > 1 else None
    return autoteste(pasta, relatorio)


def _instalar_o_que_chegou() -> None:
    """Na saída: instala o `codigo_nova` que a thread do download deixou.

    `limpar_parcial=False` porque a thread pode ainda estar escrevendo em
    `codigo_nova.parcial`; quem limpa o resto é a abertura seguinte. Nunca
    levanta — o app já está fechando, e a próxima abertura tenta de novo."""
    try:
        import atualizador
        atualizador.aplicar_pendente(limpar_parcial=False)
    except Exception as e:                                # noqa: BLE001
        try:
            import atualizador
            atualizador._logar(f"não deu para instalar o código pendente na "
                               f"saída: {str(e)[:150]}")
        except Exception:                                 # noqa: BLE001
            pass


def principal():
    # Antes de QUALQUER outra coisa: o autoteste não abre janela, não confere
    # release e não toca a rede — é o CI perguntando "o app importa aqui?".
    if "--autoteste" in sys.argv:
        sys.exit(_autoteste_da_linha_de_comando())

    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)   # nitidez em telas HiDPI
    except Exception:
        pass

    congelado = getattr(sys, "frozen", False)
    if congelado:
        import atualizador
        fonte = atualizador.preparar_codigo()
    else:
        fonte = Path(__file__).resolve().parent   # modo script: usa o repositório

    # Só a RAIZ do código entra no caminho de import. Desde 02/09/2026 toda
    # pasta de aba é pacote (tem `__init__.py`) e se importa pelo nome inteiro
    # — `from anexar.conferencia import ...` —, então injetar as subpastas
    # devolveria a colisão que os pacotes vieram desfazer: no sys.path plano
    # nome de módulo é global, e `config.py`, `frame.py` e `conferencia.py`
    # existem em mais de uma pasta. Quem entrasse por último perdia.
    p = str(fonte)
    if p not in sys.path:
        sys.path.insert(0, p)

    try:
        import comprovantes_app
        comprovantes_app.main()
    finally:
        # Depois do `mainloop`, com a janela já fechada: é o único momento em
        # que trocar a pasta `codigo` não pode puxar o tapete de um import
        # tardio (`from nuvem import contas_novas` dentro de função, por
        # exemplo) — e é o que faz a release liberada hoje valer na abertura
        # seguinte, sem a abertura de hoje ter esperado a rede por ela.
        if congelado:
            _instalar_o_que_chegou()


if __name__ == "__main__":
    principal()
