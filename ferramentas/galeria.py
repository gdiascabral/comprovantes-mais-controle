# -*- coding: utf-8 -*-
"""
Galeria de telas — ferramenta LOCAL para conferir o visual do app.

O que é
-------
Monta as mesmas 12 telas que `comprovantes_app.py` monta (Início e as onze
abas do menu) e fotografa cada uma — nos dois temas (claro e escuro) e,
com `--escala`, também simulando a escala de exibição do Windows. Não é um
teste: não compara nada contra ninguém e não falha sozinho. É o registro do
estado de cada tela para rodar ANTES e DEPOIS de mexer no visual — a
comparação é o olho de quem mexeu, não um assert.

Por que não é snapshot de CI
-----------------------------
12.298 linhas do app são interface, e nada nos 1.180 testes compara a tela
RENDERIZADA: uma regressão de layout (cartão sem borda, coluna encolhida,
rodapé cobrindo a tabela) passa limpa por todos eles. Comparar PNG contra
uma baseline no CI parecia o próximo passo óbvio, e tem dois problemas que
pesam mais que o ganho: o runner do GitHub Actions é headless e não
renderiza Tk de forma confiável (a mesma razão pela qual a maior parte de
`tests/test_visual.py` evita abrir janela sempre que a conta é aritmética
pura); e uma baseline de pixel envelhece a cada ajuste de 1px em qualquer
cartão — vira mais tempo aprovando diffs do que pegando regressão de
verdade. Esta ferramenta roda só NA MÁQUINA de quem mexeu no visual.

Como a janela é montada sem passar pelo login
------------------------------------------------
`comprovantes_app.main()` não dá para chamar direto: login da nuvem,
sincronização do cadastro e o papel de quem entrou decidem quais abas
existem, tudo ANTES de a barra e o menu serem construídos — não há um corte
limpo entre "montar a janela" e "entrar". Este script monta um ESQUELETO
FIEL em vez disso: a mesma `widgets.BarraTopo`, o mesmo `widgets.painel_menu`
e as mesmas classes de aba (`InicioFrame`, `SepararFrame`, `AnexarFrame`,
...), construídas do jeito que `tests/test_widgets.py` já constrói
`SepararFrame` — direto, dentro de um `Tk()` com o tema aplicado, sem passar
por `main()`. Nenhuma aba abre navegador nem fala com o ERP, a nuvem ou
qualquer rede: as seis que dividem o navegador do ERP recebem a MESMA
instância de `AnexarFrame` que o app de verdade usa (ela só liga o Chrome
quando alguém aperta um botão), e a Baixar Comprovantes recebe o cadastro de
contas vazio.

O que fica de fora, de propósito: login, sincronização do cadastro, o filtro
de abas por papel (aqui aparecem TODAS), avatar/e-mail/versão de quem
entrou, a pílula "cadastro sincronizado" e o combobox de tema do rodapé
(aqui o tema é escolhido pela linha de comando, não clicado na tela).

Como usar
---------
Antes de mexer em `widgets.py` ou nalgum `*_frame.py`:

    python -m ferramentas.galeria --saida antes

Depois da mudança:

    python -m ferramentas.galeria --saida depois

E comparar as pastas `antes/` e `depois/` lado a lado, tema por tema — cada
uma tem uma subpasta `claro/` e `escuro/` com um PNG por tela. Para conferir
a escala de exibição do Windows a 150% (a fonte tem de acompanhar; medida
fixa de layout, não):

    python -m ferramentas.galeria --escala 1.5 --saida depois-150

Precisa do Pillow (`pip install pillow`) só para tirar o print — de
propósito NÃO está no requirements.txt: é ferramenta de desenvolvimento
local, o app nunca a importa.

A rodada leva alguns segundos por tema e roda sem ninguém tocar na
máquina. Como o print é da TELA, a ferramenta segura o monitor aceso
enquanto isso (ver `_tela_acordada`) e recusa qualquer captura inútil —
uma cor só de canto a canto, ou janela minimizada (ver `_capturar`): PNG
preto na pasta "depois" parece captura de verdade até alguém abrir, e já
enganou uma rodada inteira.
"""
from __future__ import annotations

import sys

try:
    from PIL import ImageGrab
except ImportError:
    print("A galeria precisa do Pillow para fotografar a janela: "
          "pip install pillow")
    sys.exit(1)

import argparse
import contextlib
import time
from pathlib import Path

import tkinter as tk
from tkinter import ttk

import widgets
from inicio.inicio_frame import InicioFrame
from separar_renomear.separar_renomear import SepararFrame
from anexar.anexar_comprovantes import AnexarFrame
from anexar.conferencia import ConferenciaFrame
from aportes.aportes_frame import AportesFrame
from relatorios.relatorio_frame import RelatorioFrame
from pagamentos_dia.pagamentos_frame import PagamentosDiaFrame
from extratos_sicoob.extratos_frame import ExtratosSicoobFrame
from conciliacao.frame import ConciliacaoFrame
from contratos.frame import ContratosFrame
from acessorias.frame import AcessoriasFrame
from baixar_comprovantes.comprovantes_frame import ComprovantesFrame


def _dpi_consciente():
    """Mesma chamada de `comprovantes_app._nitidez()`: texto nítido em telas
    de alta resolução. Sem ela, o Windows escala a janela por conta própria
    (a bitmap esticada) e a simulação de `--escala` fica difícil de ler."""
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


#: Bits de `SetThreadExecutionState` (winbase.h). `ES_CONTINUOUS` sozinho
#: devolve a thread ao comportamento normal; somado aos outros dois, o
#: pedido vale até a thread terminar ou chamar de novo só com ele.
_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001
_ES_DISPLAY_REQUIRED = 0x00000002
#: `mouse_event` com este bit e deslocamento zero é um "mexeu o mouse" que
#: não move o cursor um pixel — só conta como interação para o Windows.
_MOUSEEVENTF_MOVE = 0x0001


@contextlib.contextmanager
def _tela_acordada():
    """Segura o monitor ligado pelo tempo da rodada.

    O print é da TELA (ver `_capturar`), e o Windows apaga o monitor por
    ociosidade sem perguntar a ninguém: a rodada inteira roda sem que a
    pessoa toque em teclado ou mouse, e se o tempo de "desligar a tela" das
    opções de energia vence no meio, cada captura dali em diante sai PRETA.
    Foi assim que a pasta "depois" inteira do PR #15 (02/09/2026) saiu com
    24 PNGs de 3 KB, tudo #000000, sem uma linha de erro no console. Duas
    chamadas resolvem, e foram exatamente as duas que destravaram aquela
    rodada:

    1. `mouse_event(MOVE, 0, 0)` — um movimento de zero pixels que o
       Windows conta como interação: zera o contador de ocioso e, se a tela
       JÁ apagou, acende de volta. `SetThreadExecutionState` sozinho não faz
       isso: ele impede que apague, mas não acende o que já está apagado.
    2. `SetThreadExecutionState(ES_CONTINUOUS | ES_DISPLAY_REQUIRED |
       ES_SYSTEM_REQUIRED)` — a mesma chamada que um player de vídeo faz
       para o monitor não apagar durante o filme. Vale para ESTA thread,
       que é a que roda a rodada inteira, e é desfeita no `finally` com
       `ES_CONTINUOUS` sozinho: a ferramenta não pode deixar a máquina de
       quem rodou sem economia de energia depois que terminou.

    Fora do Windows não há `windll`, e a chamada não pode derrubar a
    ferramenta — mesma regra de `_dpi_consciente()`. Quando falha, avisa
    uma vez e segue: a captura preta continua sendo detectada em
    `_capturar`, só não é evitada."""
    kernel32 = None
    try:
        from ctypes import windll
        windll.user32.mouse_event(_MOUSEEVENTF_MOVE, 0, 0, 0, 0)
        # Devolve o estado anterior; NULL (0) é recusa.
        if windll.kernel32.SetThreadExecutionState(
                _ES_CONTINUOUS | _ES_DISPLAY_REQUIRED | _ES_SYSTEM_REQUIRED):
            kernel32 = windll.kernel32
    except Exception:                                      # noqa: BLE001
        kernel32 = None
    if kernel32 is None:
        print("[galeria] não consegui segurar a tela acordada — se o "
              "monitor apagar no meio da rodada, as capturas saem pretas "
              "(e são recusadas, uma a uma).")
    try:
        yield
    finally:
        if kernel32 is not None:
            try:
                kernel32.SetThreadExecutionState(_ES_CONTINUOUS)
            except Exception:                              # noqa: BLE001
                pass


#: A ordem do menu real (ver `comprovantes_app.main`): Início sozinho, a
#: seção Comprovantes, e os grupos DIÁRIO e MENSAL. É também a ordem — e a
#: numeração — dos arquivos gravados.
_ORDEM = (
    ("ini", "▦", "Início", "inicio"),
    ("bxc", "⬇", "Baixar Comprovantes", "baixar-comprovantes"),
    ("sep", "✂", "Separar e Renomear", "separar-e-renomear"),
    ("anx", "📎", "Anexar", "anexar"),
    ("conf", "✅", "Conferência", "conferencia"),
    ("apt", "💰", "Aportes", "aportes"),
    ("pag", "🗓", "Remessa/Retorno", "remessa-retorno"),
    ("con", "⚖", "Saldo de pagamentos", "saldo-de-pagamentos"),
    ("rel", "📊", "Relatório Mensal", "relatorio-mensal"),
    ("ext", "🏦", "Extratos Sicoob", "extratos-sicoob"),
    ("ctr", "📑", "Contratos", "contratos"),
    ("acs", "📤", "Acessorias", "acessorias"),
)


def _montar_janela(root: tk.Tk, largura: int, altura: int):
    """A moldura e as 12 abas, sem login e sem navegador nenhum.

    `root` já existe (e já tem a escala aplicada, se for o caso — ver
    `main()`: `tk scaling` muda o interpretador Tcl, e um `Tk()` novo não
    herda o de um `Tk()` destruído). Devolve `(quadros, mostrar,
    aplicar_tema)`. Quem falhar ao construir fica de fora de `quadros` com
    um aviso no console — as outras abas continuam sendo fotografadas."""
    root.title("Galeria de telas — Comprovantes Mais Controle")
    root.geometry(f"{largura}x{altura}+40+40")
    # Tamanho fixo: as capturas só são comparáveis entre rodadas (e entre
    # "antes" e "depois") se a janela for sempre do mesmo jeito.
    root.resizable(False, False)
    root.deiconify()
    # `ImageGrab.grab()` fotografa o que está NA TELA, não o conteúdo do
    # widget — e este script roda sem ninguém clicar nele antes. O Windows
    # nega `SetForegroundWindow` a processo que a pessoa não tocou (é a
    # trava que impede programa em segundo plano de roubar o foco), então
    # sem isto a janela nasce ATRÁS do que já estava aberto — foi assim que
    # a primeira rodada fotografou o WhatsApp em vez do app. `-topmost` é um
    # pedido de EMPILHAMENTO (SetWindowPos), não de foco, e esse o Windows
    # concede mesmo a quem está rodando sem interação.
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()
    root.update()                        # mapeia a janela antes de tudo

    try:
        import sv_ttk
    except Exception:
        sv_ttk = None

    quadros: dict[str, ttk.Frame] = {}
    itens: dict[str, "widgets.ItemMenu"] = {}
    atual = {"nome": None}

    def aplicar_tema(escuro: bool):
        efetivo = "dark" if escuro else "light"
        if sv_ttk:
            sv_ttk.set_theme(efetivo)
        # DEPOIS do sv_ttk, nunca antes — ver CLAUDE.md ("widgets.py"):
        # trocar de tema recria o tema do ttk e apaga todo estilo nomeado.
        widgets.aplicar_estilos(escuro)
        widgets.barra_de_titulo(root, escuro)
        try:
            root.configure(background=widgets.cores()["fundo"])
        except tk.TclError:
            pass
        for f in quadros.values():
            try:
                f.aplicar_cores(escuro)
            except Exception:
                pass

    # Tema claro aplicado ANTES de qualquer widget nascer — na ordem real,
    # os estilos nomeados precisam existir na hora em que o primeiro widget
    # pede por eles.
    aplicar_tema(False)

    # ------------------------------------------------------------ moldura
    barra = widgets.BarraTopo(root)
    barra.pack(side="top", fill="x")
    chip = widgets.ChipStatus(barra.direita)
    chip.pack(side="left", padx=(0, 18), pady=14)
    chip.definir("Navegador livre", False)   # estático: aqui não há pulso

    corpo = ttk.Frame(root)
    corpo.pack(side="top", fill="both", expand=True)
    lateral = widgets.painel_menu(corpo, largura=232)
    lateral.pack(side="left", fill="y")
    conteudo = ttk.Frame(corpo, style="Fundo.TFrame")
    conteudo.pack(side="left", fill="both", expand=True)

    # -------------------------------------------------------------- abas
    def _montar(nome: str, fabrica):
        try:
            quadros[nome] = fabrica()
        except Exception as e:                            # noqa: BLE001
            print(f"[galeria] não consegui montar a aba \"{nome}\": {e}")

    _montar("ini", lambda: InicioFrame(conteudo))
    _montar("sep", lambda: SepararFrame(conteudo))

    # As seis abas de baixo dividem o navegador e a thread do AnexarFrame,
    # como no app de verdade — a MESMA instância, e não uma por aba. Ela só
    # abre o Chrome quando algum passo é clicado; construí-la não fala com
    # rede nenhuma.
    _montar("anx", lambda: AnexarFrame(conteudo))
    aba_anx = quadros.get("anx")
    if aba_anx is not None:
        _montar("conf", lambda: ConferenciaFrame(conteudo, aba_anx))
        _montar("apt", lambda: AportesFrame(conteudo, aba_anx))
        _montar("rel", lambda: RelatorioFrame(conteudo, aba_anx))
        _montar("pag", lambda: PagamentosDiaFrame(conteudo, aba_anx))
        _montar("con", lambda: ConciliacaoFrame(conteudo, aba_anx))
        _montar("ctr", lambda: ContratosFrame(conteudo, aba_anx))
    else:
        print("[galeria] sem AnexarFrame: Conferência, Aportes, Relatório "
              "Mensal, Remessa/Retorno, Saldo de pagamentos e Contratos "
              "ficam de fora (todas dependem dele).")

    # Extratos Sicoob e Acessórias NÃO recebem o aba_anx: cada uma tem
    # navegador e thread próprios, como no app de verdade.
    _montar("ext", lambda: ExtratosSicoobFrame(conteudo))
    _montar("acs", lambda: AcessoriasFrame(conteudo))
    # `obter_mapa=None`: sem cadastro de contas, a fila nasce vazia — a tela
    # aparece com a mensagem "nenhuma conta no cadastro", que é a tela real
    # de quem ainda não sincronizou.
    _montar("bxc", lambda: ComprovantesFrame(conteudo))

    if "ini" in quadros:
        # O Início usa isto para os três atalhos do canto — sem ele os
        # botões existem mas não levam a lugar nenhum.
        quadros["ini"].definir_navegacao(lambda nome: mostrar(nome))

    # -------------------------------------------------------------- menu
    def mostrar(nome: str):
        if nome not in quadros or atual["nome"] == nome:
            return
        for f in quadros.values():
            f.pack_forget()
        quadros[nome].pack(fill="both", expand=True)
        atual["nome"] = nome
        for n, it in itens.items():
            try:
                it.ativar(n == nome)
            except tk.TclError:
                pass
        # Mesma regra do menu real: reler o que a aba tem para mostrar toda
        # vez que ela é selecionada.
        atualizar = getattr(quadros[nome], "ao_abrir", None)
        if atualizar is not None:
            try:
                atualizar()
            except Exception:                             # noqa: BLE001
                pass

    def _item(pai, chave: str, icone: str, texto: str, recuo: int = 0):
        if chave not in quadros:
            return                       # aba que falhou ao montar: sem item
        it = widgets.ItemMenu(pai, texto, icone=icone, recuo=recuo,
                              comando=lambda: mostrar(chave))
        it.pack(fill="x")
        itens[chave] = it

    lateral.secao("Visão geral")
    _item(lateral.corpo, "ini", "▦", "Início")
    lateral.secao("Comprovantes")
    for _chave, _icone, _texto, _slug in _ORDEM[1:6]:
        _item(lateral.corpo, _chave, _icone, _texto)

    def _grupo(rotulo: str, itens_do_grupo):
        # Sem colapsar/abrir: aqui os dois grupos nascem sempre abertos, e é
        # tudo que a galeria precisa — a interatividade do clique é do menu
        # de verdade, não desta ferramenta.
        cab = ttk.Button(lateral.corpo, style="Grupo.Toolbutton",
                         text=f"▾  {rotulo}", state="disabled")
        cab.pack(fill="x", pady=(12, 2), padx=(10, 8))
        corpo_g = tk.Frame(lateral.corpo, background=widgets.cores()["cartao"],
                           highlightthickness=0)
        corpo_g.pack(fill="x")
        for chave, icone, texto, _slug in itens_do_grupo:
            _item(corpo_g, chave, icone, texto, recuo=10)

    _grupo("DIÁRIO", tuple(i for i in _ORDEM if i[0] in ("pag", "con")))
    _grupo("MENSAL", tuple(i for i in _ORDEM if i[0] in ("rel", "ext", "ctr", "acs")))

    return quadros, mostrar, aplicar_tema


class CapturaInutil(RuntimeError):
    """O print saiu, mas não mostra a janela: uma cor só de canto a canto."""


def _de_uma_cor_so(imagem) -> bool:
    """`getextrema()` devolve o (mínimo, máximo) de cada canal; se os dois
    coincidem em todos os canais, todo pixel tem a mesma cor. Vale para RGB
    (uma tupla por canal) e para imagem de um canal só (uma tupla)."""
    extremos = imagem.getextrema()
    if not isinstance(extremos[0], tuple):
        extremos = (extremos,)
    return all(minimo == maximo for minimo, maximo in extremos)


def _capturar(root: tk.Tk, caminho: Path):
    """Fotografa a região da tela onde a janela está e grava em `caminho`.

    É print da TELA, não do widget: `ImageGrab.grab(bbox)` lê o que o
    Windows está mostrando naquele retângulo. É isso que faz a foto ser fiel
    (o mesmo pixel que a pessoa vê, com DPI, fonte e barra de título de
    verdade) e também o que a deixa refém do que está NA TELA em vez da
    janela. A armadilha da janela nascendo atrás está tratada em
    `_montar_janela`; a irmã dela é o monitor APAGAR no meio da rodada. Com
    a tela apagada o `grab()` não falha: devolve o retângulo inteiro preto,
    `save()` grava um PNG de uns 3 KB, e nada avisa. Em 02/09/2026 a pasta
    "depois" inteira do PR #15 saiu assim — 24 arquivos de 1280x800 todos
    #000000, cada um anunciado no console como se tivesse dado certo — e só
    foi descoberta ao abrir os arquivos.

    Por isso a imagem é medida antes de ir para o disco: se é uma cor só de
    canto a canto (`_de_uma_cor_so`), o print é recusado com `CapturaInutil`
    e NADA é gravado. Nenhuma tela do app é de uma cor só — barra, menu
    lateral e conteúdo têm cores diferentes por construção, nos dois temas
    — e um PNG preto na pasta "depois" ao lado do "antes" é pior que um
    arquivo a menos, porque parece captura de verdade até alguém abrir. O
    mesmo filtro pega a janela que ainda não desenhou (retângulo inteiro na
    cor de fundo): também inútil, e também sem erro nenhum por parte do Tk.
    Quem chama conta as recusas para o resumo do fim da rodada.

    Janela MINIMIZADA dá o mesmo preto por outro caminho: o Windows a
    estaciona em (-32000, -32000), e o recorte fora da tela sai todo zero
    (conferido: `grab()` nesse retângulo devolve 1280x800 de #000000). Ao
    testar esta correção com a máquina em uso, uma rodada saiu com 3
    capturas boas e 21 pretas, a tela segura por `_tela_acordada` e
    capturável antes e depois — o preto não era o monitor. Por isso o
    estado da janela é conferido ANTES do grab, e a recusa diz qual dos
    casos foi: quem lê "a tela apagou" quando na verdade alguém minimizou
    a janela vai procurar o defeito no lugar errado.

    `_tela_acordada()` é o que EVITA a tela apagar; isto aqui é o que
    garante que, se apagar mesmo assim, ninguém compara uma pasta preta
    achando que está comparando telas."""
    caminho.parent.mkdir(parents=True, exist_ok=True)
    if root.state() == "iconic":
        raise CapturaInutil(
            "a janela está minimizada — alguém a tirou da tela no meio da "
            "rodada; nada foi gravado")
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    imagem = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    if _de_uma_cor_so(imagem):
        cor = imagem.getpixel((0, 0))
        if isinstance(cor, tuple):
            cor = "#" + "".join(f"{c:02X}" for c in cor[:3])
        raise CapturaInutil(
            f"a captura saiu de uma cor só ({cor}) — a tela apagou, a "
            "janela saiu da tela ou não desenhou; nada foi gravado")
    imagem.save(caminho)


def _assentar(root: tk.Tk):
    """`update()`/`update_idletasks()` e uma folga — o Tk desenha em cima do
    laço de eventos, e um `update()` só não garante que o desenho terminou
    antes do print da tela. `lift()` de novo a cada passo: outra janela pode
    ganhar `-topmost` no meio da rodada (um aviso do Windows, por exemplo), e
    aí é ela que aparece no print em vez do app. O que isto NÃO cobre é o
    monitor apagado: aí o desenho terminou e a tela é que não mostra — ver
    `_tela_acordada` (evita) e `_capturar` (recusa)."""
    root.lift()
    root.update_idletasks()
    root.update()
    time.sleep(0.15)
    root.update()


def main():
    ap = argparse.ArgumentParser(
        description="Fotografa as telas do app, nos dois temas, para "
                    "comparar visual antes/depois de uma mudança.")
    ap.add_argument("--escala", type=float, default=1.0,
                    help="fator de escala do Tk (1.5 simula 150%% de escala "
                         "de exibição do Windows). Padrão: 1.0.")
    ap.add_argument("--saida", default="galeria",
                    help="pasta onde salvar os PNGs. Padrão: galeria/ "
                         "(ignorada pelo .gitignore).")
    ap.add_argument("--largura", type=int, default=1280)
    ap.add_argument("--altura", type=int, default=800)
    args = ap.parse_args()

    _dpi_consciente()

    tentadas = 0
    recusadas: list[str] = []            # inúteis: uma cor só, minimizada
    falhadas: list[str] = []             # qualquer outro erro no print
    # A tela fica segura ANTES de a janela nascer e só é solta depois de a
    # última captura sair (ou de a rodada morrer): é o tempo inteiro em que
    # ninguém toca na máquina.
    with _tela_acordada():
        root = tk.Tk()
        root.withdraw()                  # some da tela até a janela ganhar
                                         # o tamanho e o tema certos
        # A escala tem de ser aplicada ANTES de qualquer widget nascer: ela
        # muda o "pixels por ponto" do interpretador Tcl, e widget já criado
        # não recalcula fonte nenhuma sozinho. É o MESMO `Tk()` daqui até o
        # fim — `tk scaling` é por interpretador, e um segundo `Tk()`
        # começaria do zero, sem a escala pedida.
        if args.escala != 1.0:
            base = float(root.tk.call("tk", "scaling"))
            root.tk.call("tk", "scaling", base * args.escala)

        quadros, mostrar, aplicar_tema = _montar_janela(root, args.largura,
                                                         args.altura)
        pasta_saida = Path(args.saida)
        print(f"Gravando em {pasta_saida.resolve()}")

        try:
            for tema, escuro in (("claro", False), ("escuro", True)):
                aplicar_tema(escuro)
                _assentar(root)
                for i, (chave, _icone, _texto, slug) in enumerate(_ORDEM,
                                                                   start=1):
                    if chave not in quadros:
                        print(f"  [pulei] {tema}/{i:02d}-{slug} "
                             "(a aba não foi montada)")
                        continue
                    mostrar(chave)
                    _assentar(root)
                    caminho = pasta_saida / tema / f"{i:02d}-{slug}.png"
                    rotulo = f"{tema}/{i:02d}-{slug}"
                    tentadas += 1
                    try:
                        _capturar(root, caminho)
                        print(f"  [ok] {rotulo}.png")
                    except CapturaInutil as e:
                        recusadas.append(rotulo)
                        print(f"  [erro] {rotulo}: {e}")
                    except Exception as e:                 # noqa: BLE001
                        falhadas.append(rotulo)
                        print(f"  [erro] {rotulo}: {e}")
        finally:
            root.destroy()

    # O resumo tem de dizer a verdade: "Pronto" com a pasta cheia de PNG
    # preto foi exatamente o que enganou a rodada do PR #15.
    if recusadas or falhadas:
        print()
        print(f"ATENÇÃO: {len(recusadas) + len(falhadas)} de {tentadas} "
              f"capturas NÃO foram gravadas em {pasta_saida.resolve()}.")
        if recusadas:
            print(f"  {len(recusadas)} saíram inúteis — a tela apagou no "
                  "meio da rodada, ou a janela foi minimizada, ou não "
                  "desenhou (o motivo de cada uma está acima). Essa pasta "
                  "não serve para comparar: rode de novo, e deixe a janela "
                  "quieta até o fim.")
        if falhadas:
            print(f"  {len(falhadas)} deram erro no print (ver acima).")
        sys.exit(1)

    print("Pronto. Compare as pastas de dentro de "
         f"{pasta_saida.resolve()} — o olho de quem mexeu é o teste.")


if __name__ == "__main__":
    main()
