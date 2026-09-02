# -*- coding: utf-8 -*-
"""Coloca a RAIZ do projeto no sys.path — e só ela.

Era uma lista de sete pastas, porque as pastas de aba não eram pacotes e cada
módulo se importava pelo nome curto. Desde 02/09/2026 todas têm `__init__.py`
e os testes importam pelo caminho inteiro (`from pagamentos_dia import
relatorio`), então a raiz basta: com ela no caminho, `import pacote.modulo`
acha qualquer módulo do repositório.

A lista velha não era só verbosa, era perigosa. Faltar uma pasta nela não
quebrava a suíte: o teste daquela pasta sumia com `importorskip` e passava a
"passar" sem rodar — foi assim que 30 testes de `pagamentos_dia` e `aportes`
ficaram um tempo sem executar. E ter as sete no caminho punha os nomes curtos
todos no mesmo espaço global, onde `config.py`, `frame.py` e `conferencia.py`
disputavam quem seria importado. Quem guarda a regra agora é
`tests/test_nomes_de_modulo.py`.

O pytest já põe a rootdir no caminho quando não há `__init__.py` em `tests/`,
mas isso depende do modo de import dele; a linha abaixo torna a garantia
explícita e independe de configuração."""
import sys
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent
if str(_RAIZ) not in sys.path:
    sys.path.insert(0, str(_RAIZ))


# ------------------------------------------------------------------ janela Tk
# UM Tk para a SESSÃO inteira, compartilhado por todo teste de interface.
#
# Não é economia: criar e destruir vários `Tk()` no mesmo processo é frágil, e
# o modo de falhar engana. Quando `test_visual.py` abria e destruía o seu, o
# `test_widgets.py` — que roda depois, por ordem alfabética — não conseguia
# mais abrir o dele e PULAVA com "sem display", num ambiente que tem display.
# Nove testes do campo de data sumiram assim, sem nada em vermelho.

@pytest.fixture(scope="session")
def raiz():
    """Janela invisível, mas MAPEADA (`-alpha 0`, não `withdraw`).

    Janela retirada não recebe foco, e sem foco o `event_generate` de tecla
    não chega ao widget: o teste passaria sem exercitar nada."""
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("sem display para abrir uma janela Tk")
    try:
        root.wm_attributes("-alpha", 0.0)
    except tk.TclError:
        pass
    root.geometry("300x120+0+0")
    root.update()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


# ------------------------------------------------------------------ atividade

@pytest.fixture(autouse=True)
def atividade_gravada(monkeypatch):
    """Nenhum teste escreve no `atividade.jsonl` de quem está rodando a suíte.

    Não é zelo com o disco: esse arquivo é o que a tela de Início lê, e desde
    que a auditoria passou a espelhar nele (30/08/2026), rodar a suíte
    enfiava "Liberou o acesso de" e "Desativou" no painel de quem programou —
    eventos de teste indistinguíveis dos de verdade.

    Quem quiser conferir o que foi anotado pede esta fixture e lê a lista.
    """
    import widgets
    anotado = []
    monkeypatch.setattr(
        widgets, "registrar_atividade",
        lambda aba, evento, resultado="ok", detalhe="", numeros=None:
        anotado.append({"aba": aba, "evento": evento, "resultado": resultado,
                        "detalhe": detalhe, "numeros": numeros or {}}))
    return anotado


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
