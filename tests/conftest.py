# -*- coding: utf-8 -*-
"""Coloca a raiz do projeto e as subpastas de código no sys.path para que os
testes possam importar os módulos do mesmo jeito que o app faz em runtime."""
import sys
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent
# TODA pasta de aba entra aqui. Faltar uma não quebra a suíte: o teste dela
# some com `importorskip` e passa a "passar" sem rodar — foi o que aconteceu
# com `pagamentos_dia` e `aportes`, 30 testes que nunca executaram.
for _p in (_RAIZ, _RAIZ / "separar_renomear", _RAIZ / "anexar",
           _RAIZ / "extratos_sicoob", _RAIZ / "relatorios",
           _RAIZ / "pagamentos_dia", _RAIZ / "aportes"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


# ---------------------------------------------------------------- conciliação
# Os testes da Conciliação Diária validam o mapa e o painel REAIS, não um dublê
# — é o que dá sentido a `test_modelo_consistencia`, que compara as fórmulas do
# MODELO.xlsx com o que o config diz sobre elas. Mas esses três arquivos têm
# dado da empresa e ficam fora do repositório, então no CI eles não existem:
# as fixtures pulam em vez de falhar. Rodando na máquina de quem usa, valem.

def _ou_pula(caminho: Path, oque: str):
    if not caminho.is_file():
        pytest.skip(f"{oque} ausente (fica fora do repositório)")
    return caminho


@pytest.fixture(scope="session")
def mapping():
    from conciliacao.mapping import AccountMapping
    return AccountMapping.load(_ou_pula(_RAIZ / "mapping.yaml", "mapping.yaml"))


@pytest.fixture(scope="session")
def config():
    from conciliacao.config import load_config
    return load_config(_ou_pula(_RAIZ / "config.yaml", "config.yaml"))


@pytest.fixture(scope="session")
def planilha(config):
    return config.planilha


@pytest.fixture(scope="session")
def modelo_path() -> Path:
    return _ou_pula(_RAIZ / "MODELO.xlsx", "MODELO.xlsx")
