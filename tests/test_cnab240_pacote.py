# -*- coding: utf-8 -*-
"""O `cnab240` é o primeiro pacote do app que leva DADOS junto do código.

Todos os outros são só `.py`, e por isso o `build.yml` copia `pasta/*.py` e
pronto. Este não: a parametrização do layout CNAB 240 vive em `spec/*.json` e é
lida em runtime. Copiar só os `.py` faz o pacote **importar normalmente** e
estourar bem depois, na hora de montar a remessa — o pior formato de falha que
existe aqui, porque aparece na máquina do usuário e no meio de um pagamento.

O `test_imports_do_motor.py` guarda os submódulos da stdlib; este guarda os
arquivos de dados. São a mesma armadilha em duas roupas: o que ninguém copia
não chega no usuário, e a suíte local não sente falta porque aqui está tudo.
"""
import json
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent
_BUILD = _RAIZ / ".github" / "workflows" / "build.yml"
_SPEC = _RAIZ / "cnab240" / "spec"


def test_a_parametrizacao_existe_e_e_json_valido():
    arquivos = sorted(p.name for p in _SPEC.glob("*.json"))
    assert arquivos == ["dominios.json", "layouts.json", "produtos.json"]
    for arquivo in _SPEC.glob("*.json"):
        json.loads(arquivo.read_text(encoding="utf-8"))


def test_o_build_copia_os_json_da_spec():
    """A linha que falta silenciosamente. Sem ela o app quebra na 1ª remessa."""
    build = _BUILD.read_text(encoding="utf-8")
    assert "Copy-Item cnab240/*.py codigo_embutido/cnab240/" in build, (
        "o build.yml não copia o código do cnab240 para o codigo.zip")
    assert "Copy-Item cnab240/spec/*.json codigo_embutido/cnab240/spec/" in build, (
        "o build.yml copia os .py do cnab240 mas NÃO os spec/*.json. O pacote "
        "vai importar e falhar só na hora de gerar a remessa, na máquina do "
        "usuário. Acrescente a linha que cria codigo_embutido/cnab240/spec.")


def test_a_spec_e_achada_de_dentro_do_pacote():
    """É assim que ela vai ser procurada no exe: `cnab240/spec`, não `../spec`.

    No repositório da biblioteca a pasta fica ao lado do pacote; aqui ela mora
    dentro. `spec.py` aceita os dois, e este teste fixa qual dos dois é o nosso
    — se alguém mover a pasta para a raiz do app, quebra aqui e não no usuário.
    """
    pytest.importorskip("cnab240")
    from cnab240 import spec

    assert spec.layouts(), "nenhum layout carregado"
    achada = spec._achar_spec_dir()
    assert achada == _SPEC, f"spec carregada de {achada}, esperado {_SPEC}"


def test_o_pacote_nao_arrasta_dependencia_de_terceiros():
    """Ele é stdlib pura, e tem de continuar sendo.

    O app já carrega requests, pdfplumber e companhia, mas a remessa é a parte
    que move dinheiro: quanto menos código de terceiros no caminho, melhor. E
    dependência nova no `requirements.txt` custa exe novo para todo mundo.
    """
    import ast
    import sys

    de_fora = {}
    for arquivo in sorted((_RAIZ / "cnab240").glob("*.py")):
        arvore = ast.parse(arquivo.read_text(encoding="utf-8"), str(arquivo))
        modulos = set()
        for no in ast.walk(arvore):
            if isinstance(no, ast.Import):
                modulos |= {a.name.split(".")[0] for a in no.names}
            elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
                modulos.add(no.module.split(".")[0])
        estranhos = {m for m in modulos
                     if m not in sys.stdlib_module_names and m != "cnab240"}
        if estranhos:
            de_fora[arquivo.name] = sorted(estranhos)
    assert not de_fora, f"cnab240 deixou de ser stdlib pura: {de_fora}"


def test_o_motor_garante_o_que_o_pacote_importa():
    """Import de stdlib que o motor não cita pode não estar no exe.

    Foi o que derrubou a v1.0.71. Aqui a lista é curta e explícita: se alguém
    acrescentar um `import` novo no cnab240, este teste cobra a declaração no
    `_garantir_dependencias()` — e a declaração cobra o `motor_minimo.txt`.
    """
    import ast

    motor = ast.parse((_RAIZ / "motor.py").read_text(encoding="utf-8"))
    declarados = set()
    for no in ast.walk(motor):
        if isinstance(no, ast.Import):
            declarados |= {a.name.split(".")[0] for a in no.names}
        elif isinstance(no, ast.ImportFrom) and no.module:
            declarados.add(no.module.split(".")[0])

    # O que o exe tem de sobra por vir de outros caminhos: os nomes que o
    # próprio app já usa em toda parte. A lista é dos que precisam de aval.
    precisa_de_aval = {"decimal", "hashlib", "json", "time", "unicodedata"}
    faltando = sorted(precisa_de_aval - declarados)
    assert not faltando, (
        f"o cnab240 importa {faltando} e o motor.py não declara — acrescente ao "
        "_garantir_dependencias() e suba o motor_minimo.txt no MESMO push.")
