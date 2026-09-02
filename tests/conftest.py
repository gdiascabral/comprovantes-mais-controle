# -*- coding: utf-8 -*-
"""Coloca a raiz do projeto e as subpastas de código no sys.path para que os
testes possam importar os módulos do mesmo jeito que o app faz em runtime."""
import contextlib
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


# ------------------------------------------------------------------ janela Tk
# UM Tk para a SESSÃO inteira, compartilhado por todo teste de interface.
#
# Não é economia: criar e destruir vários `Tk()` no mesmo processo é frágil, e
# o modo de falhar engana. Quando `test_visual.py` abria e destruía o seu, o
# `test_widgets.py` — que roda depois, por ordem alfabética — não conseguia
# mais abrir o dele e PULAVA com "sem display", num ambiente que tem display.
# Nove testes do campo de data sumiram assim, sem nada em vermelho.

@contextlib.contextmanager
def tcl_com_handles_proprios():
    """Entrega ao Tcl CÓPIAS dos três handles padrão do processo enquanto o
    `Tk()` é criado. Só no Windows; nos outros sistemas não faz nada.

    **O problema que isto resolve parecia de foco, e não era.**
    `test_o_tab_passa_por_cada_item_do_menu` falhava numa rodada a cada cinco
    da suíte inteira, e nunca rodando o arquivo sozinho, com
    `invalid command name "tk_focusNext"`. O `tk_focusNext` é um proc que o
    Tcl carrega sob demanda: na primeira chamada de um comando que não existe,
    o `unknown` manda o `auto_load_index` varrer os `tclIndex` do `auto_path`
    e anotar, em `auto_index`, de que arquivo vem cada proc. Quando o teste
    falhava, o `auto_index` tinha só as 75 entradas do Tcl, nenhuma do Tk, e
    `auto_oldpath` já dizia que o caminho inteiro fora varrido — ou seja, a
    varredura correu, PULOU o diretório do Tk e não voltaria a tentar nunca
    mais naquela sessão. Quem a dispara é qualquer comando inexistente, e o
    primeiro da suíte costuma ser um `after` de aba já destruída (o `_drenar`
    do Baixar Comprovantes ou do Usuários), num instante que varia de rodada
    para rodada — daí a intermitência.

    Por que a varredura pula o Tk: no Windows o Tcl guarda, para cada canal
    que abre, o HANDLE do sistema, e ao criar o interpretador embrulha os três
    handles padrão do processo como `stdin`/`stdout`/`stderr`. A captura de
    saída do pytest (`--capture=fd`, o padrão) faz `dup2` nos fds 0, 1 e 2 a
    cada fase de cada teste — é assim que ela imprime o ponto de progresso —,
    e cada `dup2` FECHA o handle que estava lá, inclusive o que o Tcl
    embrulhou. O Windows reaproveita valores de handle fechados; quando o
    `CreateFile` do `tclIndex` do Tk recebe o mesmo valor de um desses canais
    mortos, o `TclWinOpenFileChannel` conclui que aquele arquivo JÁ está
    aberto, as permissões não batem (leitura contra escrita) e o `open` falha
    com mensagem vazia. O `auto_load_index` trata `open` que falha como "não
    há índice neste diretório" e segue adiante. Reproduzido fora do pytest
    com um único `dup2` sobre o fd 2: o `open` seguinte do Tcl falha, e o
    seguinte a esse funciona (`tests/test_raiz.py` reencena isso). Medido na
    suíte, três processos ao mesmo tempo para apertar: 5 falhas em 24 rodadas
    com a captura ligada, 0 em 16 com `-s`, 0 em 24 com esta proteção.

    Copiar os handles (`DuplicateHandle`) e entregar as cópias ao Tcl pelo
    `SetStdHandle` durante o `Tk()` resolve na raiz: o Tcl passa a segurar
    handles que só ele fecha, e o `dup2` do pytest continua fechando só os
    dele. As cópias apontam para os mesmos arquivos — com a captura ligada,
    para o temporário do pytest —, então o que o Tcl escrever em `stderr`
    continua indo para onde ia. Elas nunca são fechadas de propósito: são do
    Tcl agora, e ele as fecha ao sair. Qualquer falha nas chamadas do Windows
    deixa tudo como estava — o pior caso é o comportamento antigo, e não uma
    suíte que não abre.

    Não é só o `tk_focusNext`: todo proc do Tk carregado sob demanda
    (`bgerror`, `tk_dialog`, os diálogos de arquivo) e todo `source` de
    arquivo `.tcl` (o tema do sv-ttk) passam pelo mesmo `open`. E o job
    `test` do CI roda em `windows-latest`, com a mesma captura."""
    if sys.platform != "win32":
        yield
        return
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetStdHandle.restype = wintypes.HANDLE
    k32.GetStdHandle.argtypes = [wintypes.DWORD]
    k32.SetStdHandle.restype = wintypes.BOOL
    k32.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.DuplicateHandle.restype = wintypes.BOOL
    k32.DuplicateHandle.argtypes = [
        wintypes.HANDLE, wintypes.HANDLE, wintypes.HANDLE,
        ctypes.POINTER(wintypes.HANDLE), wintypes.DWORD, wintypes.BOOL,
        wintypes.DWORD]
    INVALIDO = wintypes.HANDLE(-1).value
    DUPLICATE_SAME_ACCESS = 2
    # STD_INPUT_HANDLE, STD_OUTPUT_HANDLE, STD_ERROR_HANDLE são (DWORD) -10,
    # -11 e -12; a API os quer sem sinal.
    PADRAO = (0xFFFFFFF6, 0xFFFFFFF5, 0xFFFFFFF4)

    processo = k32.GetCurrentProcess()
    trocados = []
    for qual in PADRAO:
        original = k32.GetStdHandle(qual)
        if not original or original == INVALIDO:
            continue        # sem console nem redireção: o Tcl abre NUL sozinho
        copia = wintypes.HANDLE()
        if not k32.DuplicateHandle(processo, original, processo,
                                   ctypes.byref(copia), 0, False,
                                   DUPLICATE_SAME_ACCESS):
            continue
        if k32.SetStdHandle(qual, copia):
            trocados.append((qual, original))
    try:
        yield
    finally:
        for qual, original in trocados:
            k32.SetStdHandle(qual, original)


@pytest.fixture(scope="session")
def raiz():
    """Janela invisível, mas MAPEADA (`-alpha 0`, não `withdraw`).

    Janela retirada não recebe foco, e sem foco o `event_generate` de tecla
    não chega ao widget: o teste passaria sem exercitar nada.

    O `Tk()` nasce dentro de `tcl_com_handles_proprios` — ver o docstring
    dele: sem isso a captura de saída do pytest deixa o Tcl com handles
    mortos, e o autoload do Tk morre em silêncio numa rodada a cada cinco."""
    import tkinter as tk
    try:
        with tcl_com_handles_proprios():
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
