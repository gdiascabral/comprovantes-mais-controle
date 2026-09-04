# -*- coding: utf-8 -*-
"""O Registro tem de continuar LEGÍVEL na janela de quem usa o app.

O defeito de 03/09/2026 (v2.0.163), na máquina do dono — 1920x1080, escala do
Windows a 125%, janela maximizada: na aba Aportes o cartão "A lançar" descia
até quase o pé da tela e o Registro virava uma tira de ~40 px, com a primeira
linha cortada ao meio ("3 operação(ões) concluída(s) saíram da lista." aparecia
pela metade). Na v2.0.120, antes do PR #37, ele era legível.

O que este arquivo mede, e por que MEDE em vez de conferir a olho
-----------------------------------------------------------------
`registro_elastico` sabe encolher e crescer o Registro, e os seus testes em
`test_visual.py` provam isso — mas provam num cartão sozinho dentro da janela,
onde sobra tela para todo mundo. O que quebrou é outra coisa: a aba INTEIRA,
dentro da moldura de verdade (barra de cima + coluna do menu), com o conteúdo
de altura fixa acima do Registro crescendo junto com a fonte. O Registro é o
último a ser empacotado e é ele quem fica com a SOBRA — e quando a sobra é
menor que uma linha, quem some é justamente o que a aba tem a dizer.

Então a régua aqui é a única que a pessoa enxerga: **quantas linhas do Registro
cabem na tela**, medidas em pixels (a altura do widget dividida pela altura de
uma linha da fonte dele), com o pé do campo DENTRO da janela.

A escala entra por `tk scaling`, e não por DPI
----------------------------------------------
É a mesma régua do `widgets.px`: a fonte. `tk scaling` a 1,25x a base põe o
`TkDefaultFont` em 15 px onde ele tinha 12 — que é exatamente o que a máquina
do dono, consciente de DPI e a 125%, entrega ao Tk. A janela vai a 1920x1040,
que é a área de conteúdo de uma janela maximizada num monitor de 1920x1080.
"""
import tkinter as tk
from tkinter import ttk

import pytest

import widgets


#: O mínimo que faz o Registro valer a pena existir. Quatro linhas é o que a
#: aba escreve de uma vez quando termina alguma coisa (o que aconteceu, o que
#: sobrou e o que fazer agora); menos que isso é a tira de 40 px do defeito.
#:
#: É de propósito MENOS que o piso de seis linhas que `registro_elastico`
#: pede: a régua aqui é o que a pessoa precisa ler, e não o número que o
#: conserto escolheu. Passando a valer quatro, a folga entre os dois é o que
#: sobra para o próximo ajuste de layout gastar sem quebrar nada.
LINHAS_MINIMAS = 4

#: A janela do dono, maximizada: 1920x1080 menos a barra de título e a de
#: tarefas. Não é a tela — é a área que sobra para o app desenhar.
#:
#: Ela é montada num FRAME de tamanho travado, e não numa janela de verdade,
#: e isso é o que torna a medida determinística: o Windows recusa janela mais
#: alta que a área de trabalho e devolve outra altura sem avisar — nesta
#: máquina, um `Toplevel` pedindo 1040 nasceu com 876, e a suíte passaria a
#: medir a tela de quem a rodou (menor ainda no runner do CI, que é headless).
#: O Tk calcula o layout de um frame pelo tamanho DELE, esteja ele visível ou
#: não, então travar o frame mede exatamente a janela do defeito em qualquer
#: máquina.
LARGURA, ALTURA = 1920, 1040

#: As duas escalas que precisam valer ao mesmo tempo: a de quem nunca mexeu na
#: escala do Windows, e a da máquina onde o defeito apareceu.
ESCALAS = (1.0, 1.25)

#: O texto de trabalho que a Aportes escreveu no dia do defeito. Seis linhas,
#: porque é assim que uma rodada termina — e a primeira delas era a cortada.
TRABALHO = (
    "3 operação(ões) concluída(s) saíram da lista.",
    "O que sobrou ainda NÃO foi criado — corrija o cadastro e clique em",
    "Lançar de novo; o que já entrou será pulado.",
    "  1/3 ok — pagamento R$ 1.000,00",
    "  2/3 ok — pagamento R$ 2.500,00",
    "  3/3 ok — recebimento R$ 3.500,00",
)


# ------------------------------------------------------------------ a moldura
def _abas_com_registro(conteudo):
    """Constrói as abas que têm Registro, como `ferramentas/galeria.py` faz.

    Nenhuma delas abre navegador nem fala com rede ao ser construída: as seis
    que dividem o Chrome do ERP recebem a MESMA instância de `AnexarFrame` que
    o app de verdade lhes passa, e ela só liga o navegador quando alguém aperta
    um botão. Aba que não conseguir nascer aqui fica de fora com o motivo — no
    CI faltam os arquivos de cadastro, que moram fora do repositório."""
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

    quadros, faltaram = {}, {}

    def _montar(nome, fabrica):
        try:
            quadros[nome] = fabrica()
        except Exception as e:                              # noqa: BLE001
            faltaram[nome] = f"{type(e).__name__}: {e}"

    _montar("anx", lambda: AnexarFrame(conteudo))
    anx = quadros.get("anx")
    _montar("sep", lambda: SepararFrame(conteudo))
    _montar("ext", lambda: ExtratosSicoobFrame(conteudo))
    _montar("acs", lambda: AcessoriasFrame(conteudo))
    _montar("bxc", lambda: ComprovantesFrame(conteudo))
    if anx is not None:
        _montar("conf", lambda: ConferenciaFrame(conteudo, anx))
        _montar("apt", lambda: AportesFrame(conteudo, anx))
        _montar("rel", lambda: RelatorioFrame(conteudo, anx))
        _montar("pag", lambda: PagamentosDiaFrame(conteudo, anx))
        _montar("con", lambda: ConciliacaoFrame(conteudo, anx))
        _montar("ctr", lambda: ContratosFrame(conteudo, anx))
    return quadros, faltaram


#: Nome de gente para cada aba, para a mensagem de falha dizer onde olhar.
ABAS = {
    "sep": "Separar e Renomear",
    "anx": "Anexar",
    "conf": "Conferência",
    "apt": "Aportes",
    "pag": "Remessa/Retorno",
    "con": "Saldo de pagamentos",
    "rel": "Relatório Mensal",
    "ext": "Extratos Sicoob",
    "ctr": "Contratos",
    "acs": "Acessorias",
    "bxc": "Baixar Comprovantes",
}


def _registro_de(quadro):
    """O `tk.Text` que `estilo_log` pintou, dentro da aba.

    Pela COR de fundo e não pelo nome do atributo: ele é `self.log` em nove
    abas, `self.txt` na Separar e `self.texto` nos Aportes, e uma lista de três
    nomes envelheceria na primeira aba nova. O fundo do registro é o mesmo nos
    dois temas de propósito (ver `estilo_log`), então a busca não depende do
    tema em que a aba nasceu."""
    fundo = widgets.cores()["log_fundo"]
    pilha, achados = [quadro], []
    while pilha:
        w = pilha.pop()
        pilha.extend(w.winfo_children())
        if isinstance(w, tk.Text):
            try:
                if str(w.cget("background")) == fundo:
                    achados.append(w)
            except tk.TclError:
                pass
    return achados[0] if achados else None


def _linhas_visiveis(texto: tk.Text) -> float:
    """Quantas linhas de texto CABEM na altura que o campo ganhou na tela.

    Pelo Tcl (`font metrics -linespace`) e não por `tkinter.font`: é o mesmo
    motivo do `_garantir_fontes` do `widgets.py` — aquele módulo não está no
    exe, e criar um objeto `Font` aqui traria junto o `__del__` que apaga a
    fonte nomeada do app.

    A folga interna sai do próprio widget: `pady` e o filete cobram PIXELS dos
    dois lados, enquanto `height` conta LINHAS — é a mesma diferença que faz a
    altura do campo vazio ser medida em `registro_elastico`."""
    fonte = texto.cget("font")
    linha = int(texto.tk.call("font", "metrics", fonte, "-linespace"))
    linha += int(texto.cget("spacing1")) + int(texto.cget("spacing3"))
    folga = 2 * (int(texto.cget("pady")) + int(texto.cget("highlightthickness"))
                 + int(texto.cget("borderwidth")))
    return max(texto.winfo_height() - folga, 0) / max(linha, 1)


def _relato(nome: str, escala: float, texto: tk.Text, tela) -> str:
    fim = texto.winfo_rooty() + texto.winfo_height()
    pe = tela.winfo_rooty() + tela.winfo_height()
    return (f"{ABAS.get(nome, nome)} a {escala:.2f}x: "
            f"{_linhas_visiveis(texto):.1f} linha(s) visíveis "
            f"({texto.winfo_height()} px de campo), "
            f"pé do campo {fim - pe:+d} px em relação ao pé da janela")


@pytest.fixture(scope="module", params=ESCALAS, ids=lambda e: f"escala-{e:g}")
def moldura(request, raiz):
    """A moldura do app, na escala do parâmetro, com as onze abas já dentro.

    Uma por escala, e não uma por teste: montar as onze abas custa
    segundos, e o que muda de um teste para o outro é só o conteúdo do
    Registro. Mexe no `tk scaling` da janela COMPARTILHADA da suíte (é uma por
    sessão — ver o conftest), então desfazer no fim não é zelo: sem isso os
    testes seguintes mediriam fontes de 125% achando que são as de 100%."""
    escala = request.param
    base_escala = float(raiz.tk.call("tk", "scaling"))
    estilo = ttk.Style()
    tema_antes = estilo.theme_use()

    raiz.tk.call("tk", "scaling", base_escala * escala)
    widgets._estado["fator"] = 0.0            # o fator é lido uma vez e guardado
    try:
        import sv_ttk
        sv_ttk.set_theme("light")
    except Exception:                                       # noqa: BLE001
        pass          # sem sv-ttk a medida muda um pouco; o defeito, não
    # DEPOIS do sv_ttk, nunca antes: ele recria o tema do ttk e apaga todo
    # estilo nomeado (ver CLAUDE.md, "widgets.py").
    widgets.aplicar_estilos(False)

    # `place` com largura e altura escritas, e `pack_propagate(False)`: as duas
    # coisas juntas travam a janela simulada no tamanho pedido, sem depender do
    # tamanho da `raiz` nem do monitor de quem está rodando a suíte.
    tela = tk.Frame(raiz, width=LARGURA, height=ALTURA)
    tela.pack_propagate(False)
    tela.place(x=0, y=0, width=LARGURA, height=ALTURA)

    barra = widgets.BarraTopo(tela)
    barra.pack(side="top", fill="x")
    corpo = ttk.Frame(tela)
    corpo.pack(side="top", fill="both", expand=True)
    lateral = widgets.painel_menu(corpo, largura=232)
    lateral.pack(side="left", fill="y")
    conteudo = ttk.Frame(corpo, style="Fundo.TFrame")
    conteudo.pack(side="left", fill="both", expand=True)
    tela.update()

    quadros, faltaram = _abas_com_registro(conteudo)
    registros = {}
    for nome, quadro in quadros.items():
        quadro.pack(fill="both", expand=True)
        tela.update_idletasks()
        tela.update()
        alvo = _registro_de(quadro)
        if alvo is not None:
            # O que a aba escreveu ao nascer: é a "tela vazia", e ela volta
            # inteira a cada teste, para um teste não medir a sobra do outro.
            registros[nome] = (quadro, alvo, alvo.get("1.0", "end-1c"))
        quadro.pack_forget()

    yield {"tela": tela, "conteudo": conteudo, "escala": escala,
           "registros": registros, "faltaram": faltaram}

    try:
        barra._fechar_lista()
    except Exception:                                       # noqa: BLE001
        pass
    tela.destroy()
    raiz.tk.call("tk", "scaling", base_escala)
    widgets._estado["fator"] = 0.0
    try:
        estilo.theme_use(tema_antes)
    except tk.TclError:
        pass
    widgets.aplicar_estilos(False)
    raiz.update()


def _mostrar(moldura, nome: str):
    """Deixa só esta aba na tela, como o menu do app faz, e devolve o campo."""
    if nome in moldura["faltaram"]:
        pytest.skip(f"a aba {ABAS.get(nome, nome)} não pôde ser construída "
                    f"neste ambiente — {moldura['faltaram'][nome]}")
    if nome not in moldura["registros"]:
        pytest.fail(f"não achei o campo de Registro da aba "
                    f"{ABAS.get(nome, nome)}: `estilo_log` deixou de pintá-lo?")
    quadro, texto, vazio = moldura["registros"][nome]
    for outro, _t, _v in moldura["registros"].values():
        outro.pack_forget()
    quadro.pack(fill="both", expand=True)
    moldura["tela"].update_idletasks()
    moldura["tela"].update()
    return texto, vazio


def _repor(texto: tk.Text, conteudo: str, marca: str = ""):
    """Troca o que está no Registro. `marca` é a tag "ph" da tela vazia — é ela
    que faz `tem_conteudo_real` responder "isto não é trabalho"."""
    texto.delete("1.0", "end")
    if conteudo and marca:
        texto.insert("end", conteudo, marca)
    elif conteudo:
        texto.insert("end", conteudo)
    texto.update_idletasks()
    texto.update()


@pytest.mark.parametrize("aba", sorted(ABAS))
def test_o_registro_com_trabalho_cabe_na_tela(moldura, aba):
    """O defeito, medido: com o que a aba tem a dizer dentro dele, o Registro
    precisa de pelo menos quatro linhas VISÍVEIS e do pé dentro da janela."""
    texto, _vazio = _mostrar(moldura, aba)
    _repor(texto, "\n".join(TRABALHO) + "\n")
    tela = moldura["tela"]
    tela.update_idletasks()
    tela.update()

    relato = _relato(aba, moldura["escala"], texto, tela)
    assert _linhas_visiveis(texto) >= LINHAS_MINIMAS, (
        "o Registro virou uma tira: " + relato)
    fim = texto.winfo_rooty() + texto.winfo_height()
    assert fim <= tela.winfo_rooty() + tela.winfo_height(), (
        "o Registro passou do pé da janela: " + relato)


@pytest.mark.parametrize("aba", sorted(ABAS))
def test_o_registro_continua_sendo_o_ultimo_da_tela(moldura, aba):
    """A outra metade do conserto: reservar o pé mexe na ORDEM do `pack`.

    `_reservar_o_pe` empacota o cartão `side="bottom"` e ANTES do irmão
    elástico, e é justamente aí que mora a armadilha que o `registro_elastico`
    já avisava: mexer na ordem pode fazer o Registro nascer ACIMA da barra de
    ação, que é onde ficam os botões de começar. Aqui isso é medido — ele tem
    de continuar sendo o mais baixo de todos, com trabalho dentro e sem."""
    texto, vazio = _mostrar(moldura, aba)
    quadro = moldura["registros"][aba][0]
    cartao = texto
    while cartao is not None and cartao.master is not quadro:
        cartao = cartao.master
    for conteudo, marca in ((vazio, "ph"), ("\n".join(TRABALHO) + "\n", "")):
        _repor(texto, conteudo, marca)
        moldura["tela"].update_idletasks()
        moldura["tela"].update()
        pe = cartao.winfo_rooty() + cartao.winfo_height()
        for irmao in quadro.pack_slaves():
            if irmao is cartao:
                continue
            assert irmao.winfo_rooty() + irmao.winfo_height() <= pe, (
                f"{ABAS[aba]} a {moldura['escala']:.2f}x: "
                f"{str(irmao).split('.')[-1]} ficou ABAIXO do Registro")


@pytest.mark.parametrize("aba", sorted(ABAS))
def test_o_registro_vazio_cabe_na_tela(moldura, aba):
    """A tela vazia é o que a aba mostra antes do primeiro clique — e é ela
    que diz o que fazer. Cortada, a aba nasce sem instrução."""
    texto, vazio = _mostrar(moldura, aba)
    _repor(texto, vazio, "ph")
    tela = moldura["tela"]
    tela.update_idletasks()
    tela.update()

    if not vazio.strip():
        pytest.skip("esta aba nasce com o Registro em branco")
    relato = _relato(aba, moldura["escala"], texto, tela)
    linhas = min(int(texto.index("end-1c").split(".")[0]), LINHAS_MINIMAS)
    assert _linhas_visiveis(texto) >= linhas, (
        "a tela vazia nasceu cortada: " + relato)
