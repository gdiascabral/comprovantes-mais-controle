# -*- coding: utf-8 -*-
"""C1 da revisão final: os três arquivos que o bloco de guias grava não podem
ir para o repositório público.

`util.pasta_base()` só devolve a pasta do exe quando o app está congelado;
rodando como script (o caminho documentado, `python comprovantes_app.py`) ela
devolve a RAIZ do repositório — e é lá que `guias/regras.py`,
`guias/registro.py` e `guias/painel.py` gravam nome de fornecedor, obra e,
no backup, o título inteiro do ERP com a conta bancária dentro.

Este teste chama o mesmo `git check-ignore` que a revisão pediu como prova,
para a régua não depender de rodar o comando à mão de novo a cada mudança no
`.gitignore`.
"""
import subprocess
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent

_ARQUIVOS = (
    "guias_regras.json",
    "guias_lancadas.jsonl",
    "guias_backup/x.json",
)


def _ignorado(caminho: str) -> bool:
    resultado = subprocess.run(
        ["git", "check-ignore", "-q", caminho],
        cwd=_RAIZ, capture_output=True)
    if resultado.returncode not in (0, 1):
        pytest.skip("sem git para conferir")
    return resultado.returncode == 0


@pytest.mark.parametrize("caminho", _ARQUIVOS)
def test_arquivo_que_o_bloco_de_guias_grava_esta_no_gitignore(caminho):
    """Nascendo na raiz (rodando como script), nenhum destes pode ir ao commit
    — carregam nome de fornecedor, obra e, no backup, a conta bancária."""
    assert _ignorado(caminho), (
        f"{caminho!r} não está protegido pelo .gitignore: rodando o app como "
        "script ele nasce na raiz do repositório público.")
