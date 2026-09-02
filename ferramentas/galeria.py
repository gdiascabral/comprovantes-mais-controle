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

    python ferramentas/galeria.py --saida antes

Depois da mudança:

    python ferramentas/galeria.py --saida depois

E comparar as pastas `antes/` e `depois/` lado a lado, tema por tema — cada
uma tem uma subpasta `claro/` e `escuro/` com um PNG por tela. Para conferir
a escala de exibição do Windows a 150% (a fonte tem de acompanhar; medida
fixa de layout, não):

    python ferramentas/galeria.py --escala 1.5 --saida depois-150

Precisa do Pillow (`pip install pillow`) só para tirar o print — de
propósito NÃO está no requirements.txt: é ferramenta de desenvolvimento
local, o app nunca a importa.
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
import time
from pathlib import Path

# Mesma ideia do bloco no topo do comprovantes_app.py: rodando como script,
# as subpastas de aba não estão no sys.path até alguém colocá-las. A raiz
# entra primeiro porque este arquivo mora em ferramentas/, não na raiz — o
# comprovantes_app.py não precisa desta linha porque ELE é a raiz.
_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))
for _p in (_RAIZ / "separar_renomear", _RAIZ / "anexar", _RAIZ / "aportes",
           _RAIZ / "relatorios", _RAIZ / "pagamentos_dia",
           _RAIZ / "extratos_sicoob", _RAIZ / "inicio",
           _RAIZ / "baixar_comprovantes"):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import tkinter as tk
from tkinter import ttk

import widgets
from inicio_frame import InicioFrame
from separar_renomear import SepararFrame
from anexar_comprovantes import AnexarFrame
from conferencia import ConferenciaFrame
from aportes_frame import AportesFrame
from relatorio_frame import RelatorioFrame
from pagamentos_frame import PagamentosDiaFrame
from extratos_frame import ExtratosSicoobFrame
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


def _capturar(root: tk.Tk, caminho: Path):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    x, y = root.winfo_rootx(), root.winfo_rooty()
    w, h = root.winfo_width(), root.winfo_height()
    imagem = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    imagem.save(caminho)


def _assentar(root: tk.Tk):
    """`update()`/`update_idletasks()` e uma folga — o Tk desenha em cima do
    laço de eventos, e um `update()` só não garante que o desenho terminou
    antes do print da tela. `lift()` de novo a cada passo: outra janela pode
    ganhar `-topmost` no meio da rodada (um aviso do Windows, por exemplo), e
    aí é ela que aparece no print em vez do app."""
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

    root = tk.Tk()
    root.withdraw()                      # some da tela até a janela ganhar
                                          # o tamanho e o tema certos
    # A escala tem de ser aplicada ANTES de qualquer widget nascer: ela
    # muda o "pixels por ponto" do interpretador Tcl, e widget já criado não
    # recalcula fonte nenhuma sozinho. É o MESMO `Tk()` daqui até o fim —
    # `tk scaling` é por interpretador, e um segundo `Tk()` começaria do
    # zero, sem a escala pedida.
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
            for i, (chave, _icone, _texto, slug) in enumerate(_ORDEM, start=1):
                if chave not in quadros:
                    print(f"  [pulei] {tema}/{i:02d}-{slug} "
                         "(a aba não foi montada)")
                    continue
                mostrar(chave)
                _assentar(root)
                caminho = pasta_saida / tema / f"{i:02d}-{slug}.png"
                try:
                    _capturar(root, caminho)
                    print(f"  {tema}/{i:02d}-{slug}.png")
                except Exception as e:                     # noqa: BLE001
                    print(f"  [erro] {tema}/{i:02d}-{slug}: {e}")
    finally:
        root.destroy()

    print("Pronto. Compare as pastas de dentro de "
         f"{pasta_saida.resolve()} — o olho de quem mexeu é o teste.")


if __name__ == "__main__":
    main()
