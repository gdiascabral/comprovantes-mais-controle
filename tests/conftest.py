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
import contextlib
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
    não chega ao widget: o teste passaria sem exercitar nada. O foco, aliás,
    vai e vem com o Windows — quem gera tecla usa `teclar`, logo abaixo.

    Ela nasce na metade da tela em que o ponteiro NÃO está
    (`longe_do_ponteiro`): a janela é invisível, mas a lista da busca e o
    calendário que os widgets abrem são visíveis, nascem colados nela e
    respondem ao mouse de verdade.

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
    longe_do_ponteiro(root)
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


# ---------------------------------------------------------- teclas e foco
# O Tk entrega tecla GERADA a quem tem o foco, e "quem tem o foco" é o que o
# comando `focus` responde — que fica VAZIO sempre que o Windows tira o foco
# do app: outra janela em primeiro plano, a Tk da suíte vizinha dando
# `focus_force`, um clique de quem está usando a máquina. Nesse estado o
# `event_generate` de tecla é DESCARTADO em silêncio: `TkFocusKeyEvent`
# devolve NULL, o evento não chega a binding nenhuma e nada avisa. É contrato
# do Tk, não defeito (`event(n)`: "key events require that the window has
# focus"), e era por isso que os testes de teclado falhavam de vez em quando
# com três `pytest` rodando ao lado, ou com o dono trabalhando na máquina
# (02/09/2026: `test_as_setas_andam_pela_lista…`, `test_digitar_do_zero…`).
#
# O que NÃO resolve, para o próximo que for procurar atalho:
# - `focus_set()` só ANOTA o foco para quando o app o recuperar (é o que
#   `focus -lastfor` devolve) e não escreve o foco do Tk enquanto o Windows o
#   tem — a tecla gerada em seguida some. É o caminho de `focar_busca()`.
# - `event_generate("<FocusIn>")` não engana o Tk: o evento gerado sai
#   marcado como gerado, e `TkFocusFilterEvent` o repassa às bindings sem
#   mexer no foco (medido no 8.6.15, que é o desta máquina e o do CI).
# - `focus_force()` seguido de `update()` ANTES da tecla reabre a janela: o
#   `update` é justamente onde o FocusOut do Windows é processado.
# - `update()` DEPOIS da tecla, antes do assert, é a mesma armadilha do outro
#   lado: a tecla de `teclar` chega (medido: 0 perdidas em 30 sob um ladrão
#   de foco, em `tk.Entry`, `ttk.Entry` e `ttk.Combobox`), mas o `update`
#   processa o FocusOut que o Windows enfileirou, e o `<FocusOut>` do PRÓPRIO
#   widget desfaz o que a tecla fez — `ComboBusca._ao_sair` devolve a lista
#   inteira, `CampoData._completar_ano` completa o ano. O handler da tecla
#   roda DENTRO de `teclar` (o `event generate` sem `-when` é síncrono), então
#   o `update` ali não serve ao que se mede; quem precisa dele (mapear a
#   lista da busca, deixar a binding de foco pintar) chama e sabe por quê.
#
# O que resolve: `focus_force()` escreve o foco do Tk NA HORA (é o único
# caminho que o faz com o app sem o foco do sistema). As bindings de
# `<FocusIn>`/`<FocusOut>` que ele enfileira rodam ANTES da tecla, como na
# vida real (o campo ganha o foco, depois recebe a tecla) — medido o
# contrário: com o `<FocusIn>` da busca rodando DEPOIS do Enter, ele apagava
# a dica que o Enter tinha acabado de pôr. Para isso serve-se o que JÁ ESTÁ
# na fila do Tcl, e nada mais (`_servir_a_fila`): nem `update`, que redesenha,
# roda o ocioso e lê mensagens novas do Windows — é por aí que o FocusOut
# entra —, nem `dooneevent` solto, que também lê mensagens novas assim que a
# fila esvazia. Este segundo foi medido: com três suítes ao mesmo tempo, cada
# uma via o foco sumir de novo, tomava-o de volta (tirando-o das outras) e o
# laço virava tempestade — 3 a 12 falhas por rodada, com vinte tentativas.
# Daí a SENTINELA: um evento virtual posto no fim da fila e `dooneevent` até
# ele chegar; tudo o que estava antes roda, a fila nunca esvazia e nenhuma
# mensagem nova é lida. Servida a fila, o foco é conferido DE NOVO, e só
# então a tecla é gerada. Um FocusOut que o Windows já tenha mandado só será
# visto no próximo `update` do teste — e o Tk ainda o descarta como velho
# quando é anterior ao serial que o `focus_force` gravou.
# `tests/test_teclar.py` reencena o roubo com `SetFocus(NULL)` e prova as
# duas metades: a tecla crua some, a de `teclar` chega.

def _foco_do_tk(widget) -> str:
    """O caminho de quem tem o foco, ou "" quando o app não o tem.

    Pelo Tcl e não por `focus_get()`, que converte o nome em widget e estoura
    com `KeyError` quando o foco está numa janela que o tkinter não conhece
    (o popdown do Combobox, por exemplo)."""
    return str(widget.tk.call("focus"))


def _servir_a_fila(widget) -> None:
    """Roda o que JÁ está na fila do Tcl — as bindings de foco que o
    `focus_force` acabou de enfileirar — e nada mais: nenhuma mensagem nova do
    Windows é lida (ver o bloco acima, e a tempestade que o `dooneevent` solto
    fez). A sentinela é um evento virtual posto no FIM da fila; serve-se um
    evento por vez até ela chegar."""
    import _tkinter
    chegou = []
    fid = widget.bind("<<FimDaFila>>", lambda _e: chegou.append(1), add="+")
    try:
        widget.event_generate("<<FimDaFila>>", when="tail")
        for _ in range(200):
            if chegou:
                return
            widget.tk.dooneevent(_tkinter.DONT_WAIT | _tkinter.WINDOW_EVENTS)
        raise AssertionError(
            "a sentinela não chegou em 200 eventos: a fila do Tcl está "
            "maior do que este helper supõe")
    finally:
        widget.unbind("<<FimDaFila>>", fid)


def focar(widget) -> None:
    """Põe o foco em `widget` do jeito que o Tk enxerga, deixa as bindings de
    foco rodarem, e confere.

    Não custa nada quando o foco já está lá; quando o Windows o levou, toma-o
    de volta com `focus_force`. A conferência é o que separa "não exercitou
    nada" de "provou": widget que o Tk não aceita como foco (sem `pack`, ou
    empacotado sem `update`, que deixa o foco para quando ele aparecer) falha
    aqui, com nome, e não num assert genérico dez linhas abaixo.

    As bindings de `<FocusIn>` e `<FocusOut>` que o `focus_force` enfileira
    rodam antes de voltar — só o que já está na fila, sem ler mensagem nova
    do Windows (`_servir_a_fila`) —, e o foco é conferido DE NOVO depois. Ao
    voltar, o widget tem o foco E já reagiu a isso, que é o estado em que uma
    tecla o encontraria; o `cget` que um teste de aparência lê em seguida
    devolve o que a binding configurou, sem precisar de redesenho."""
    alvo = str(widget)
    for _ in range(3):
        if _foco_do_tk(widget) != alvo:
            widget.focus_force()
        assert _foco_do_tk(widget) == alvo, (
            f"o Tk não pôs o foco em {alvo}: ele está em "
            f"{_foco_do_tk(widget) or 'lugar nenhum'} — o widget está mapeado?")
        _servir_a_fila(widget)
        if _foco_do_tk(widget) == alvo:
            return
    raise AssertionError(
        f"o foco saiu de {alvo} três vezes seguidas enquanto só a fila era "
        "servida: havia FocusOut do Windows já na fila, com serial novo — o "
        "que o bloco \"teclas e foco\" do conftest supõe impossível")


def teclar(widget, sequencia: str, **campos) -> None:
    """Gera uma tecla em `widget` e GARANTE que o Tk a entregue a ele.

    É o `event_generate` de sempre — a tecla segue o caminho normal do Tk, com
    os bindtags, as bindings de classe e o "break" de quem o devolve, então o
    que o teste prova continua sendo que a binding existe e faz o que faz. O
    que muda é que a entrega deixa de depender de quem está em primeiro plano
    no Windows: `focar` confere (ou toma) o foco, deixa as bindings de foco
    rodarem e confere de novo, e a tecla é gerada em seguida, sem volta ao
    laço de eventos entre a conferência e o `event generate` — ver o bloco
    acima."""
    focar(widget)
    widget.event_generate(sequencia, **campos)


def longe_do_ponteiro(raiz) -> None:
    """Leva a janela da suíte para a metade da tela em que o ponteiro NÃO está.

    A janela é invisível (`-alpha 0`), mas as janelinhas que os widgets abrem
    — a lista da busca, o calendário — são visíveis, nascem coladas nela e
    respondem ao mouse de verdade: com o ponteiro parado em cima da lista, o
    `<Enter>` da linha realça a linha (é o desenho: mouse e teclado apontam
    para o mesmo lugar), e `test_as_setas_andam_pela_lista…` viu `_realce` 7
    em vez de 0 com o dono usando a máquina. Quem gera o `<Enter>` é o Tk,
    que consulta a posição do ponteiro ao mapear a janela e a cada 250 ms —
    e ninguém move o ponteiro de ninguém. Move-se a janela.

    Chamada ao nascer a janela e de novo por quem abre lista (a fixture
    `barra`), porque quem usa a máquina move o mouse no meio da suíte."""
    import tkinter as tk
    try:
        px_, py_ = raiz.winfo_pointerxy()
        larg_tela, alt_tela = raiz.winfo_screenwidth(), raiz.winfo_screenheight()
        larg, alt = raiz.winfo_width(), raiz.winfo_height()
    except tk.TclError:
        return
    if px_ < 0 or py_ < 0:                # ponteiro noutro monitor: tanto faz
        return
    x = 0 if px_ > larg_tela // 2 else max(larg_tela - larg - 40, 0)
    y = 0 if py_ > alt_tela // 2 else max(alt_tela - alt - 40, 0)
    raiz.geometry(f"+{x}+{y}")
    raiz.update()


# As três como fixture, que é como um teste pede coisa ao conftest —
# importá-lo funciona hoje só porque `tests/` não é pacote e o modo de import
# do pytest o põe no caminho, e isso não é contrato.

@pytest.fixture(name="teclar")
def _teclar():
    return teclar


@pytest.fixture(name="focar")
def _focar():
    return focar


@pytest.fixture(name="longe_do_ponteiro")
def _longe_do_ponteiro():
    return longe_do_ponteiro


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
