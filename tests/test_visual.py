# -*- coding: utf-8 -*-
"""A aparência compartilhada: paleta, fontes e estilos nomeados.

Dois assuntos, e o primeiro NÃO precisa de tela: o contraste da paleta é
aritmética sobre constantes, então roda no CI como qualquer regra de negócio.
Os testes de fonte e de estilo abrem um Tk de verdade e pulam sem display,
como o `test_widgets.py`.
"""
import ast
import gc
import re
import subprocess
import tkinter as tk
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

import pytest

import util
import widgets

_RAIZ_APP = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------- versão
def _versao_curta():
    """A função do `comprovantes_app`, sem importar o módulo inteiro.

    Importar o app puxa as dez abas, e com elas o Playwright e o cadastro da
    nuvem — caro e frágil para testar uma função de string. O que se lê aqui é
    a MESMA fonte que o app executa: se ela mudar de nome ou de lugar, o teste
    quebra em vez de passar testando outra coisa.
    """
    fonte = (_RAIZ_APP / "comprovantes_app.py").read_text(encoding="utf-8")
    arvore = ast.parse(fonte)
    alvo = next((n for n in arvore.body
                 if isinstance(n, ast.FunctionDef) and n.name == "_versao_curta"),
                None)
    assert alvo is not None, "`_versao_curta` sumiu do comprovantes_app.py"
    ns: dict = {}
    exec(compile(ast.Module(body=[alvo], type_ignores=[]),
                 "comprovantes_app.py", "exec"), ns)
    return ns["_versao_curta"]


@pytest.mark.parametrize("completa, na_tela", [
    ("v2.0.108", "v2.0"),
    ("v2.0.9", "v2.0"),
    ("v1.0.104", "v1.0"),
    ("v10.3.2", "v10.3"),
    ("2.0.108", "v2.0"),        # sem o "v" na frente
    ("v2.0", "v2.0"),           # já curta
])
def test_a_tela_mostra_so_major_e_minor(completa, na_tela):
    """O número de build muda a cada push e não significa nada para quem usa:
    entre a v2.0.108 e a v2.0.109 pode não haver diferença na tela. Ele
    continua acessível na dica do rótulo — ver `widgets.Dica`."""
    assert _versao_curta()(completa) == na_tela


@pytest.mark.parametrize("entrada", [None, "", "   "])
def test_sem_versao_a_tela_nao_escreve_nada(entrada):
    """Vazio é vazio: o app abre sem `versao.txt` quando roda do repositório,
    e "v" sozinho na barra seria pior que nada."""
    assert _versao_curta()(entrada) == ""


@pytest.mark.parametrize("entrada", ["vabc", "v2", "qualquer coisa"])
def test_versao_estranha_sai_inteira(entrada):
    """Lixo entra e sai inteiro. Cortar no lugar errado esconderia justamente
    a pista de que o `versao.txt` veio errado."""
    assert _versao_curta()(entrada) == entrada.strip()


# --------------------------------------------------------------------- meses
def test_o_mes_da_tela_e_o_mes_da_pasta():
    """As duas tabelas de meses têm de dizer a mesma coisa.

    `widgets.MESES` é o rótulo da tela ("Julho") e `util.MESES_PASTA` é o que
    vira NOME DE PASTA no disco ("JULHO"). Existiam sete cópias espalhadas —
    três delas produzindo caminho de arquivamento —, e bastava uma divergir
    (um "MARCO" sem cedilha) para a Conciliação gravar numa pasta e o
    Relatório Mensal noutra: a família exata do defeito que partiu julho/2026
    ao meio. Sobraram duas tabelas, e é este teste que as mantém iguais.
    """
    assert [m.upper() for m in widgets.MESES] == list(util.MESES_PASTA)
    assert len(util.MESES_PASTA) == 12


def test_toda_aba_usa_a_mesma_tabela_de_meses():
    """Nenhum módulo pode ter a sua própria lista de meses de novo."""
    import acessorias.frame
    import contratos.frame
    import extratos_frame
    import relatorio_frame
    import sicoob_config
    import contas_mc

    for modulo in (acessorias.frame, contratos.frame, extratos_frame,
                   relatorio_frame):
        assert list(modulo.MESES) == list(widgets.MESES), modulo.__name__
    for modulo in (sicoob_config, contas_mc):
        assert tuple(modulo.MESES) == util.MESES_PASTA, modulo.__name__


# ------------------------------------------------------------------ contraste
def _luminancia(cor: str) -> float:
    """Luminância relativa da WCAG para '#rrggbb'."""
    canais = []
    cor = cor.lstrip("#")
    for i in (0, 2, 4):
        c = int(cor[i:i + 2], 16) / 255
        canais.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    r, g, b = canais
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contraste(frente: str, fundo: str) -> float:
    a, b = _luminancia(frente), _luminancia(fundo)
    claro, escuro = max(a, b), min(a, b)
    return (claro + 0.05) / (escuro + 0.05)


#: 4,5:1 é o mínimo da WCAG AA para texto normal. Era exatamente isto que os
#: cinzas fixos furavam: `#6b6b6b` dá 3,2:1 no tema escuro e `#8a8a8a` dá
#: 3,4:1 no claro — cada um ilegível em um dos dois temas.
MINIMO = 4.5


@pytest.mark.parametrize("tema", sorted(widgets.PALETA))
@pytest.mark.parametrize("papel", ("apoio", "tenue", "ativo", "ok",
                                   "atencao", "erro"))
def test_cada_cor_de_texto_e_legivel_no_seu_tema(tema, papel):
    cores = widgets.PALETA[tema]
    razao = _contraste(cores[papel], cores["fundo"])
    assert razao >= MINIMO, (
        f"{papel} no tema {tema}: {razao:.1f}:1, abaixo de {MINIMO}:1")


@pytest.mark.parametrize("tema", sorted(widgets.PALETA))
def test_o_registro_e_legivel_no_proprio_fundo(tema):
    """O campo de registro tem fundo PRÓPRIO, diferente do fundo da janela."""
    cores = widgets.PALETA[tema]
    razao = _contraste(cores["log_texto"], cores["log_fundo"])
    assert razao >= MINIMO, f"registro no tema {tema}: {razao:.1f}:1"


def test_os_dois_temas_tem_os_mesmos_papeis():
    """Papel que existe num tema e falta no outro vira KeyError na troca."""
    assert set(widgets.PALETA["claro"]) == set(widgets.PALETA["escuro"])


# ------------------------------------- o que a interface PINTA de verdade
# Os três testes acima medem o que a PALETA permite; estes medem o que a TELA
# usa, e a diferença não é acadêmica.
#
# Eles mediam 12 pares, todos na mesma direção: cor de TEXTO contra o fundo do
# painel. Nenhum media "branco sobre uma cor sólida da paleta" — que é
# exatamente o que o botão de passo e o círculo numerado do cartão fazem. A
# `marca` do tema escuro (#6F9BFF) entrou validada como texto, 6,3:1 sobre o
# cartão, e é ela que preenche esses dois: branco por cima dá 2,69:1, abaixo
# até do piso de 3:1 que a WCAG dá a COMPONENTE, quanto mais dos 4,5:1 de
# texto. São ~29 pontos da janela (11 botões de passo + 18 círculos), em quase
# toda tela, e só para quem usa o tema escuro.
#
# A tabela abaixo é escrita à mão de propósito: ela é a lista do que a
# interface pinta, e uma varredura automática do `widgets.py` mediria de novo
# o que a paleta permite. Quem puser cor nova numa tela põe o par novo aqui —
# e `test_o_botao_de_passo_e_o_circulo_pintam_a_cor_medida` existe para a
# tabela não envelhecer sozinha nos dois pontos onde isso já doeu.
BRANCO = "#FFFFFF"

#: 3:1 é o piso da WCAG AA para COMPONENTE de interface e para texto grande —
#: a silhueta do botão contra o que está atrás dela. Não substitui o 4,5:1 do
#: texto que vai por cima: são duas medidas, e um botão precisa passar nas
#: duas.
MINIMO_COMPONENTE = 3.0

#: O papel da paleta que PREENCHE o botão de passo, o círculo numerado do
#: cartão e o dia escolhido do calendário — os três lugares com branco por
#: cima. Numa constante porque é lido em dois lugares que têm de concordar: a
#: tabela de pares (a MEDIDA) e o teste que constrói os widgets (a PROVA de
#: que a medida é a da tela).
#:
#: NÃO é a `marca`, e essa é a correção inteira: a `marca` é o papel de TEXTO
#: (KPI, item aberto do menu, linha selecionada) e continua medida como tal na
#: tabela abaixo. Trocar esta constante de volta para "marca" faz o teste
#: falhar de novo com os mesmos 2,69:1.
COR_DO_PASSO = "marca_solida"

#: (frente, fundo, onde) — `frente`/`fundo` são papéis da paleta, ou a cor
#: crua quando o app a escreve assim (o branco dos rótulos sobre cor sólida).
PARES_DE_TEXTO = (
    # ---- texto dentro do cartão, que é o fundo PADRÃO do ttk neste app
    ("texto", "cartao", "o corpo de texto de qualquer cartão"),
    ("apoio", "cartao", "Apoio.TLabel, a linha que explica a tela"),
    ("tenue", "cartao", "Tenue.TLabel e Mini.TLabel: legenda e rótulo"),
    ("ativo", "cartao", "Ativo.TLabel, o \"está rodando agora\""),
    ("ok", "cartao", "Ok.TLabel"),
    ("atencao", "cartao", "Atencao.TLabel e MonoMiniAtencao.TLabel"),
    ("erro", "cartao", "Erro.TLabel e MonoMiniErro.TLabel"),
    ("marca", "cartao", "KPIMarca.TLabel e o botão-link (\"Marcar todas\")"),
    # ---- texto sobre a pílula/chip do estado, que tem fundo próprio
    ("ok", "ok_fundo", "PillOk.TLabel e a tag \"ok\" do Treeview"),
    ("atencao", "atencao_fundo", "PillAtencao.TLabel"),
    ("erro", "erro_fundo", "PillErro.TLabel"),
    ("info", "info_fundo", "PillInfo.TLabel"),
    ("marca", "marca_fundo", "ItemAtivo.TLabel (o item aberto do menu) e a "
                             "linha selecionada da tabela"),
    # ---- branco sobre cor SÓLIDA: a direção que ninguém media
    (BRANCO, "acao", "Botao papel=\"acao\", o executar verde"),
    (BRANCO, "acao_ativo", "o mesmo botão verde sob o cursor"),
    (BRANCO, COR_DO_PASSO, "Botao papel=\"passo\", o círculo numerado do "
                           "Cartao e o dia escolhido do calendário"),
    (BRANCO, "marca_barra", "Barra.TLabel e Marca.TLabel na barra de cima, e "
                            "o botão de passo sob o cursor"),
    ("marca_sub", "marca_barra", "BarraTenue.TLabel, o texto secundário "
                                 "DENTRO da barra de cima"),
)

#: Os mesmos objetos, medidos como FORMA e não como texto: a silhueta do botão
#: contra o que está atrás dela. O botão de passo e o verde aparecem duas
#: vezes porque aparecem em dois lugares — dentro de um cartão (o círculo
#: numerado) e no cabeçalho da página, que é o cinza do painel.
#:
#: O anel de foco do `widgets.ItemMenu` entrou aqui em 02/09/2026, e por um
#: motivo que a tabela de texto não cobre: ele é `marca` desenhada sobre TRÊS
#: fundos diferentes, conforme o item esteja parado, sob o cursor ou aberto.
#: Dois desses três já são medidos acima, e mais duro — `marca` sobre `cartao`
#: e `marca` sobre `marca_fundo` estão em `PARES_DE_TEXTO`, nos 4,5:1. O que
#: faltava era o terceiro: o item sob o CURSOR, cujo fundo é o cinza do painel.
PARES_DE_COMPONENTE = (
    (COR_DO_PASSO, "cartao", "o círculo numerado, dentro do cartão"),
    (COR_DO_PASSO, "fundo", "o botão de passo, no cabeçalho da página"),
    ("acao", "cartao", "o botão verde, dentro de um cartão"),
    ("acao", "fundo", "o botão verde, no cabeçalho da página"),
    ("marca", "fundo", "o anel de foco do ItemMenu com o cursor no mesmo item"),
)


def _cor(paleta: dict, nome: str) -> str:
    """O papel da paleta, ou a cor crua quando o app já a escreve assim."""
    return nome if nome.startswith("#") else paleta[nome]


def _br(razao: float) -> str:
    """A razão como ela é escrita nos comentários da paleta: "4,63:1"."""
    return f"{razao:.2f}".replace(".", ",") + ":1"


@pytest.mark.parametrize("tema", sorted(widgets.PALETA))
@pytest.mark.parametrize("frente, fundo, onde", PARES_DE_TEXTO,
                         ids=[f"{f}-sobre-{b}" for f, b, _ in PARES_DE_TEXTO])
def test_o_texto_que_a_tela_pinta_e_legivel(tema, frente, fundo, onde):
    """TEXTO NORMAL: 4,5:1, o mínimo da WCAG AA.

    Vale para os três blocos da tabela, e o terceiro é o que faltava — quando
    a cor da paleta é o FUNDO e o branco é a letra, quem tem de passar é o par
    inteiro, não a cor sozinha. Uma cor pode ser ótima como texto sobre o
    cartão e péssima como fundo com branco por cima: é a mesma distância
    medida entre pontos diferentes."""
    paleta = widgets.PALETA[tema]
    razao = _contraste(_cor(paleta, frente), _cor(paleta, fundo))
    assert razao >= MINIMO, (
        f"{onde}, no tema {tema}: {_cor(paleta, frente)} sobre "
        f"{_cor(paleta, fundo)} ({frente} sobre {fundo}) dá {_br(razao)}, "
        f"abaixo dos {_br(MINIMO)} que a WCAG AA pede para texto normal")


@pytest.mark.parametrize("tema", sorted(widgets.PALETA))
@pytest.mark.parametrize("frente, fundo, onde", PARES_DE_COMPONENTE,
                         ids=[f"{f}-contra-{b}"
                              for f, b, _ in PARES_DE_COMPONENTE])
def test_a_forma_do_botao_se_separa_do_que_esta_atras(tema, frente, fundo,
                                                      onde):
    """COMPONENTE: 3:1, o piso da WCAG para o que não é texto.

    Aqui não há letra nenhuma: o que se mede é se dá para ver ONDE o botão
    começa e termina. Escurecer um botão até o branco de cima ficar legível
    resolve uma ponta e estraga a outra — este teste é a outra ponta."""
    paleta = widgets.PALETA[tema]
    razao = _contraste(_cor(paleta, frente), _cor(paleta, fundo))
    assert razao >= MINIMO_COMPONENTE, (
        f"{onde}, no tema {tema}: {_cor(paleta, frente)} contra "
        f"{_cor(paleta, fundo)} ({frente} contra {fundo}) dá {_br(razao)}, "
        f"abaixo dos {_br(MINIMO_COMPONENTE)} de componente")


# --------------------------------------------------------------------- fontes
# A janela `raiz` vem do conftest, compartilhada com o `test_widgets.py`.


def test_as_fontes_sobrevivem_ao_coletor_de_lixo(raiz):
    """O defeito que apagava a tipografia inteira, em silêncio.

    `tkinter.font.Font.__del__` executa `font delete` no Tcl. Criar a fonte
    numa variável local a apagava no primeiro `gc`, e daí em diante o Tk lia
    "AppTitulo" como NOME DE FAMÍLIA — não achava, caía na fonte padrão, e
    título, legenda e registro saíam todos do mesmo tamanho. Sem erro nenhum.
    """
    widgets.aplicar_estilos(False)
    gc.collect()
    for nome in (widgets.FONTE_TITULO, widgets.FONTE_SECAO,
                 widgets.FONTE_APOIO, widgets.FONTE_MONO):
        tkfont.nametofont(nome)          # levanta TclError se foi apagada


def test_a_escala_de_tamanhos_e_respeitada(raiz):
    widgets.aplicar_estilos(False)
    base = abs(int(tkfont.nametofont("TkDefaultFont").cget("size")))
    tam = {n: abs(int(tkfont.nametofont(n).cget("size")))
           for n in (widgets.FONTE_TITULO, widgets.FONTE_SECAO,
                     widgets.FONTE_APOIO)}
    assert tam[widgets.FONTE_TITULO] > tam[widgets.FONTE_SECAO] > base
    assert tam[widgets.FONTE_APOIO] <= base, "a legenda não pode passar o corpo"


def test_tamanho_negativo_continua_negativo():
    """Tamanho negativo no Tk é medida em PIXELS. Escalar sem preservar o
    sinal transformava o título de 1,55x num texto MENOR que o corpo."""
    assert widgets._escalar(-9, 1.55) == -14
    assert widgets._escalar(9, 1.55) == 14
    assert widgets._escalar(9, 0.0) == 1, "tamanho zero não existe no Tk"


# ------------------------------------------------------- o layout escala junto
# As fontes já acompanhavam a escala do Windows; as MEDIDAS de layout, não. A
# 150% (medido com `ferramentas/galeria.py --escala 1.5`) "ÚLTIMA EXECUÇÃO"
# saía "ÚLTIMA EXECU" numa coluna de 130 px fixos, a coluna SITUAÇÃO sumia
# inteira, e o logotipo da barra encostava no campo de busca — a faixa
# continuava com 52 px enquanto o texto dentro dela crescia 50%.

@pytest.fixture
def em_escala(raiz):
    """Roda o corpo do teste com o app "a 150%", e devolve tudo ao fim.

    Mexe no `tk scaling` da janela COMPARTILHADA (é uma por sessão, ver o
    conftest), então desfazer não é zelo: sem isso os testes seguintes
    mediriam fontes de 150% achando que são as de 100%."""
    def aplicar(escala: float):
        raiz.tk.call("tk", "scaling", base * escala)
        widgets._estado["fator"] = 0.0    # o fator é lido uma vez e guardado
        return widgets.fator_de_escala()

    base = float(raiz.tk.call("tk", "scaling"))
    try:
        yield aplicar
    finally:
        raiz.tk.call("tk", "scaling", base)
        widgets._estado["fator"] = 0.0
        widgets.aplicar_estilos(False)


def test_a_cem_por_cento_a_medida_e_a_mesma(em_escala):
    """A promessa que protege quem já estava bem: a 100% o `px` devolve o
    número que a tela sempre teve, e nenhum pixel se mexe."""
    assert em_escala(1.0) == pytest.approx(1.0, abs=0.05)
    for n in (0, 1, 3, 5, 8, 10, 12, 14, 16, 18, 20, 24, 52, 130, 232, 330):
        assert widgets.px(n) == n


def test_a_cento_e_cinquenta_a_medida_cresce_junto(em_escala):
    assert em_escala(1.5) == pytest.approx(1.5, abs=0.05)
    assert widgets.px(52) == 78            # a altura da barra de cima
    assert widgets.px(232) == 348          # a coluna do menu
    assert widgets.px(130) == 195          # a coluna "ÚLTIMA EXECUÇÃO"
    assert widgets.px((16, 12)) == (24, 18)


def test_zero_continua_zero(em_escala):
    """Sem esta ressalva o `_escalar` devolveria 1 (ele nunca devolve zero,
    porque tamanho zero de fonte não existe no Tk), e todo `padx=(0, 8)` da
    tela ganharia um pixel de folga onde o desenho pedia encostado."""
    em_escala(1.5)
    assert widgets.px(0) == 0
    assert widgets.px((0, 8)) == (0, 12)


def test_fonte_menor_que_a_de_referencia_nao_encolhe_o_layout(em_escala):
    """O erro tem um lado barato. Fonte menor não corta nada — o texto cabe de
    sobra —, então apertar as margens só estragaria uma tela que estava boa."""
    assert em_escala(0.75) == 1.0
    assert widgets.px(20) == 20


def test_a_barra_de_cima_cresce_com_o_que_tem_dentro(em_escala, raiz):
    """A medida que mais estragava: a faixa ficava com 52 px enquanto o
    logotipo dentro dela crescia, e o texto saía cortado por baixo."""
    em_escala(1.5)
    widgets.aplicar_estilos(False)
    barra = widgets.BarraTopo(raiz)
    try:
        barra.pack(fill="x")
        raiz.update()
        assert int(barra.cget("height")) == widgets.px(barra.ALTURA)
        assert int(barra.cget("height")) > barra.ALTURA
    finally:
        barra._fechar_lista()
        barra.destroy()
        raiz.update()


def test_a_coluna_do_menu_cresce_com_os_rotulos(em_escala, raiz):
    em_escala(1.5)
    widgets.aplicar_estilos(False)
    menu = widgets.painel_menu(raiz, largura=232)
    try:
        assert int(menu.cget("width")) == 348
    finally:
        menu.destroy()
        raiz.update()


def test_a_coluna_da_tabela_cresce_com_o_titulo(em_escala, raiz):
    """"ÚLTIMA EXECUÇÃO" em 130 px fixos saía "ÚLTIMA EXECU" a 150%. Quem
    escreveu 130 estava dizendo "cabe o título", e é a frase que tem de
    continuar valendo."""
    em_escala(1.5)
    widgets.aplicar_estilos(False)
    tv = ttk.Treeview(raiz, columns=("rotina", "quando"), show="headings")
    try:
        tv.column("rotina", width=200)
        tv.column("quando", width=130)
        widgets.estilo_tabela(tv)
        assert int(tv.column("quando", "width")) == 195
        assert int(tv.column("rotina", "width")) == 300
        # Chamada duas vezes (o Início e a Acessórias remontam a lista), a
        # largura não pode escalar em cima do que já foi escalado.
        widgets.estilo_tabela(tv)
        assert int(tv.column("quando", "width")) == 195
    finally:
        tv.destroy()
        raiz.update()


def test_o_registro_segue_o_tema(raiz):
    txt = tk.Text(raiz)
    for escuro in (True, False, True):
        widgets.aplicar_estilos(escuro)
        widgets.estilo_log(txt, escuro)
        esperado = widgets.PALETA["escuro" if escuro else "claro"]
        assert str(txt.cget("background")) == esperado["log_fundo"]
        assert str(txt.cget("font")) == widgets.FONTE_MONO


# -------------------------------------------------------------------- estilos
def test_a_troca_de_tema_reconfigura_os_estilos(raiz):
    """`sv_ttk.set_theme` recria o tema do ttk e apaga todo estilo nomeado.

    Aqui a troca é simulada com `theme_use`, para o teste não depender do
    sv-ttk estar instalado: o que importa é que `aplicar_estilos` seja capaz
    de repor tudo depois de qualquer troca."""
    st = ttk.Style()
    original = st.theme_use()
    outros = [t for t in st.theme_names() if t != original]
    if not outros:
        pytest.skip("só há um tema ttk neste ambiente")

    for escuro in (True, False):
        st.theme_use(outros[0] if escuro else original)
        widgets.aplicar_estilos(escuro)
        esperado = widgets.PALETA["escuro" if escuro else "claro"]
        assert st.lookup("Apoio.TLabel", "foreground") == esperado["apoio"]
        assert st.lookup("Erro.TLabel", "foreground") == esperado["erro"]
        assert st.lookup("Titulo.TLabel", "font") == widgets.FONTE_TITULO


def test_a_semana_comeca_no_domingo_e_as_colunas_batem():
    """As iniciais e o primeiro dia da semana andam JUNTOS.

    Mexer numa sem a outra alinha o dia 1 na coluna errada e o mês inteiro
    escorrega — sem erro nenhum, só datas trocadas para quem clica. O
    `calendar` do Python começa na segunda (ISO); aqui começa no domingo,
    como o calendário de parede.
    """
    import calendar
    from datetime import date

    assert widgets.DIAS_DA_SEMANA[0] == "D", "a primeira coluna é domingo"
    assert len(widgets.DIAS_DA_SEMANA) == 7

    # A prova real: em que coluna o dia 1 de um mês conhecido cai.
    semanas = calendar.Calendar(widgets.SEMANA_COMECA_EM).monthdayscalendar(
        2026, 8)
    coluna_do_primeiro = semanas[0].index(1)
    # 1/8/2026 é sábado; com domingo na coluna 0, sábado é a 6.
    assert date(2026, 8, 1).weekday() == 5, "sábado, na contagem do Python"
    assert coluna_do_primeiro == 6, (
        "o dia 1 caiu na coluna errada: as iniciais e SEMANA_COMECA_EM "
        "deixaram de concordar")


def test_a_ressalva_tem_cor_propria_nos_dois_temas(raiz):
    """Faltava o meio-termo: o dado de pagamento que existe mas não serve para
    a remessa só tinha a cor do impedimento, e vermelho que não impede nada é
    lido como defeito do app.

    Nos dois temas, porque a cor foi conferida contra o fundo de cada um."""
    st = ttk.Style()
    for escuro in (False, True):
        widgets.aplicar_estilos(escuro)
        esperado = widgets.PALETA["escuro" if escuro else "claro"]
        assert st.lookup("MonoMiniAtencao.TLabel", "foreground") == esperado["atencao"]
        assert (st.lookup("MonoMiniAtencao.TLabel", "foreground")
                != st.lookup("MonoMiniErro.TLabel", "foreground"))
        # A legenda do topo mora no cinza do painel, e sem a variante de fundo
        # ela nasceria com um retângulo branco em volta.
        assert st.lookup("FundoAtencao.TLabel", "foreground") == esperado["atencao"]
        assert st.lookup("FundoAtencao.TLabel", "background") == esperado["fundo"]
    widgets.aplicar_estilos(False)


def test_o_cartao_numera_so_quando_ha_ordem(raiz):
    """Numerar informa quando existe sequência; no Registro seria inventar uma.

    O número deixou de ser prefixo do texto e virou um círculo azul desenhado
    num Canvas — `Label` no Tk é sempre retângulo. O que se confere aqui
    continua sendo o mesmo: o cartão com ordem mostra o número, o sem ordem
    não mostra nada além do título."""
    com_ordem = widgets.Cartao(raiz, "Período", 1)
    assert com_ordem.lbl_titulo.cget("text") == "Período"
    assert com_ordem._bolha is not None
    assert com_ordem._bolha.itemcget("numero", "text") == "1"

    sem_ordem = widgets.Cartao(raiz, "Registro")
    assert sem_ordem.lbl_titulo.cget("text") == "Registro"
    assert sem_ordem._bolha is None


def test_o_botao_de_passo_e_o_circulo_pintam_a_cor_medida(raiz):
    """A tabela `PARES_DE_TEXTO` é escrita à mão, e tabela à mão envelhece.

    O defeito que ela veio pegar não foi uma cor errada na paleta: foi uma cor
    CERTA usada num papel para o qual ninguém a mediu. Nada impede que isso se
    repita ao contrário — alguém trocar a cor do botão e a tabela continuar
    medindo a antiga, verde, provando nada.

    Por isso aqui os dois widgets são construídos de verdade, nos dois temas,
    e o que eles pintam é comparado com o que o teste mede. O terceiro ponto
    (o dia escolhido do calendário) usa a mesma `COR_DO_PASSO` e não entra: ele
    só nasce dentro do popup, e abri-lo aqui traria a janela sem foco do
    `CampoData` para o meio da suíte."""
    for escuro in (False, True):
        widgets.aplicar_estilos(escuro)
        esperado = widgets.PALETA["escuro" if escuro else "claro"][COR_DO_PASSO]
        botao = widgets.Botao(raiz, "Buscar os lançamentos", papel="passo")
        cartao = widgets.Cartao(raiz, "Período", 1)
        try:
            assert str(botao.cget("background")) == esperado, (
                "o botão de passo deixou de usar a cor que o teste de "
                "contraste mede")
            assert str(botao.cget("foreground")) == BRANCO
            assert str(cartao._bolha.itemcget("bolha", "fill")) == esperado, (
                "o círculo numerado deixou de usar a cor que o teste de "
                "contraste mede")
            assert str(cartao._bolha.itemcget("numero", "fill")) == BRANCO
        finally:
            botao.destroy()
            cartao.destroy()
    widgets.aplicar_estilos(False)


# ------------------------------------------------------- a fonte dos ícones
# Os ícones do menu eram emoji e dingbats soltos, cada um desenhado pela fonte
# que o Windows achasse primeiro: medido com `font actual`, no mínimo QUATRO
# famílias numa coluna de doze linhas. Duas delas caem na Segoe UI Emoji, que é
# COLORIDA, e cor de glifo colorido não obedece ao `foreground` — essas ficavam
# idênticas nos dois temas, inclusive no item aberto, onde todo o resto vira
# azul. Ver o bloco "ícones" no topo do `widgets.py`.
#
# A troca é pela fonte de ícones do próprio Windows, que é monocromática. E ela
# traz a armadilha de sempre do Tk: pedir uma família que a máquina não tem NÃO
# dá erro — o Tk cai na fonte padrão, e os codepoints saem como quadradinhos.
# É a mesma família de defeito do `font delete` lá de cima: falha em silêncio,
# e só aparece na frente de quem usa.

@pytest.mark.parametrize("familias, esperada", [
    # Windows 11: as duas existem, e ganha a Fluent.
    (["Arial", "Segoe UI", "Segoe MDL2 Assets", "Segoe Fluent Icons"],
     "Segoe Fluent Icons"),
    # Windows 10: só a MDL2.
    (["Arial", "Segoe UI", "Segoe MDL2 Assets"], "Segoe MDL2 Assets"),
    # Nenhuma das duas: sobra a família do texto, e o menu fica com o emoji.
    (["Arial", "Segoe UI"], "Segoe UI"),
])
def test_a_familia_de_icones_e_sempre_uma_que_existe(familias, esperada):
    """Os três desfechos, com a lista de famílias entregue de fora.

    `_familia_de_icones` recebe a lista em vez de perguntá-la justamente para
    isto: as três situações são exercitadas na mesma máquina, sem depender de
    ter (ou não ter) cada fonte instalada."""
    achada = widgets._familia_de_icones(familias, "Segoe UI")
    assert achada == esperada
    assert achada in familias, (
        "a família escolhida não está na lista da máquina: o Tk vai cair na "
        "fonte padrão sem avisar, e os ícones saem como quadradinhos")


def test_sem_familia_de_icones_o_menu_volta_ao_emoji(monkeypatch):
    """O terceiro desfecho, do lado de quem desenha: a família do TEXTO é real,
    mas não tem os codepoints. Quem não tem nenhuma das duas fontes precisa
    ficar com o emoji de antes, que ao menos desenha alguma coisa."""
    monkeypatch.setitem(widgets._estado, "familia_icones", "Segoe UI")
    assert widgets.familia_de_icones() == ""
    assert widgets.icone_do_menu("📎") == ("📎", False)


def test_com_familia_de_icones_o_emoji_vira_codepoint(monkeypatch):
    for familia, tabela in widgets.ICONES_POR_FAMILIA.items():
        monkeypatch.setitem(widgets._estado, "familia_icones", familia)
        assert widgets.icone_do_menu("📎") == (tabela["📎"], True), familia
        # Glifo que não está na tabela sai inteiro, na fonte de texto: o ● do
        # pulso passa por aqui, e ele não existe na fonte de ícones.
        assert widgets.icone_do_menu("●") == ("●", False), familia


def test_a_fonte_de_icones_nao_cai_no_padrao_em_silencio(raiz):
    """A prova contra o Tk de verdade, e não contra a função pura.

    `font configure -family` devolve o que foi PEDIDO, não o que será
    desenhado; o que denuncia a queda para a fonte padrão é a família pedida
    não estar na lista da máquina. Estas duas linhas são o teste inteiro."""
    widgets.aplicar_estilos(False)
    tcl = ttk.Style().tk
    familias = set(tcl.splitlist(tcl.call("font", "families")))
    pedida = str(tcl.call("font", "configure", widgets.FONTE_ICONES,
                          "-family"))
    assert pedida in familias, (
        f"a fonte de ícones pede {pedida!r}, que não existe nesta máquina")
    assert pedida == widgets._estado["familia_icones"]
    # E ela é DERIVADA do TkDefaultFont, como as outras onze: a 150% de escala
    # o ícone tem de crescer junto com o nome da aba ao lado dele.
    base = abs(int(tkfont.nametofont("TkDefaultFont").cget("size")))
    assert abs(int(tkfont.nametofont(widgets.FONTE_ICONES).cget("size"))) > base


def test_as_duas_tabelas_de_icones_falam_dos_mesmos_itens():
    """Uma tabela por família porque as fontes não têm o mesmo alfabeto (a
    Fluent mapeia 201 codepoints que a MDL2 não tem). O que elas não podem é
    cobrir conjuntos diferentes de ABAS: aí o Windows 10 fica sem ícone em
    alguma tela, e ninguém que roda no 11 descobre isso."""
    assert set(widgets.ICONES_FLUENT) == set(widgets.ICONES_MDL2)
    for nome, tabela in (("Fluent", widgets.ICONES_FLUENT),
                         ("MDL2", widgets.ICONES_MDL2)):
        assert len(set(tabela.values())) == len(tabela), (
            f"{nome}: dois itens do menu com o mesmo codepoint — duas telas "
            "ganhariam o mesmo ícone, e nada em vermelho diria isso")
        for glifo, cp in tabela.items():
            assert len(cp) == 1 and 0xE000 <= ord(cp) <= 0xF8FF, (
                f"{nome}/{glifo}: {cp!r} não é um codepoint da área de uso "
                "privado — a fonte de ícones não desenha caractere comum")


def test_nenhum_icone_do_menu_ficou_fora_da_tabela():
    """Ícone que o menu use e a tabela não conheça volta ao sorteio de fontes.

    Medido no arquivo que monta o menu: hoje, TODO caractere fora do BMP que o
    `comprovantes_app.py` escreve numa constante é um ícone de aba — são os
    oito de 02/09/2026 —, e todos têm de estar na tabela. Um ícone novo que
    entre sem passar por lá volta a ser desenhado por qualquer família que o
    Windows ache primeiro, e volta a não ter nada a ver com os outros onze.

    A rede tem um furo conhecido: ícone DENTRO do BMP (como o ✂ e o ⚖ de
    hoje, que estão na tabela) passa por aqui sem ser notado. Fechá-lo pediria
    ler os argumentos de `_item` por AST, e a forma dessas chamadas muda mais
    do que o conjunto de ícones — o teste envelheceria antes do problema
    aparecer."""
    import ast
    fonte = (_RAIZ_APP / "comprovantes_app.py").read_text(encoding="utf-8")
    fora_do_bmp = set()
    for no in ast.walk(ast.parse(fonte)):
        if isinstance(no, ast.Constant) and isinstance(no.value, str):
            fora_do_bmp.update(c for c in no.value if ord(c) > 0xFFFF)
    assert fora_do_bmp, (
        "nenhum caractere fora do BMP no comprovantes_app.py: ou os ícones "
        "mudaram de lugar, ou este teste deixou de medir o que dizia medir")
    faltando = sorted(fora_do_bmp - set(widgets.ICONES_FLUENT))
    assert not faltando, (
        "ícone do menu fora da tabela de widgets.py: "
        + ", ".join(f"{c} (U+{ord(c):05X})" for c in faltando))


def test_o_cabecalho_sem_apoio_nao_cria_a_linha(raiz):
    assert widgets.Cabecalho(raiz, "Só título").lbl_apoio is None
    assert widgets.Cabecalho(raiz, "Título", "explica").lbl_apoio is not None


# ----------------------------------------------------------------- foco
@pytest.fixture
def aba(raiz):
    """Uma aba com a MESMA forma da Pagamentos do Dia, que é onde doeu.

    O campo de cima (a data) mora fundo — cartão → linha → moldura → Entry —,
    e o de baixo (o caminho) é filho direto do cartão. É a armadilha inteira:
    a árvore diz uma coisa e a tela diz outra."""
    quadro = ttk.Frame(raiz)
    quadro.pack(fill="both", expand=True)

    cartao1 = ttk.Frame(quadro)
    cartao1.pack(fill="x")
    linha = ttk.Frame(cartao1)
    linha.pack(fill="x")
    moldura = ttk.Frame(linha)
    moldura.pack(side="left")
    data = ttk.Entry(moldura, width=11)
    data.pack(side="left")
    ttk.Combobox(linha, state="readonly", width=8).pack(side="left")

    cartao2 = ttk.Frame(quadro)
    cartao2.pack(fill="x")
    caminho = ttk.Entry(cartao2)         # raso, mas EMBAIXO
    caminho.pack(fill="x")

    raiz.update()
    yield quadro, data, caminho
    quadro.destroy()
    raiz.update()


def test_o_foco_vai_para_o_campo_de_cima_e_nao_para_o_mais_raso(aba):
    quadro, data, caminho = aba
    assert widgets.focar_primeiro_campo(quadro) is data, (
        "o foco caiu no campo raso de baixo: a busca está seguindo a árvore "
        "de widgets em vez da posição na tela")
    # `focus_lastfor` e não `focus_get`: o primeiro é o que a JANELA guarda, o
    # segundo é quem está com o foco do WINDOWS agora. Qualquer outra janela
    # que apareça no meio da suíte — a Tk do teste seguinte, o console
    # voltando ao topo — faz `focus_get` responder outra coisa, e o teste
    # falhava sozinho de vez em quando sem nada ter mudado no código. O que se
    # quer provar aqui é que o cursor foi POSTO no campo certo, e é isso que
    # `focus_lastfor` diz: é o widget que recebe a digitação quando a janela
    # está em primeiro plano.
    assert str(quadro.focus_lastfor()) == str(data)


def test_o_foco_ignora_combobox_readonly(aba):
    """Combobox é subclasse de Entry e aceita foco sem aceitar digitação."""
    quadro, data, caminho = aba
    alvo = widgets.focar_primeiro_campo(quadro)
    assert not isinstance(alvo, ttk.Combobox)


def test_o_foco_ignora_campo_desabilitado(aba):
    quadro, data, caminho = aba
    data.configure(state="disabled")
    assert widgets.focar_primeiro_campo(quadro) is caminho


def test_aba_sem_campo_algum_nao_levanta(raiz):
    vazia = ttk.Frame(raiz)
    vazia.pack()
    raiz.update()
    assert widgets.focar_primeiro_campo(vazia) is None
    vazia.destroy()


# ------------------------------------------------------- trilha de passos
# A trilha de passos (`widgets.Passos`) foi removida no redesenho de
# agosto/2026, e com ela os três testes que a cobriam. Ela numerava as AÇÕES
# enquanto os cartões ficavam sem número; agora o número está no cartão, e
# manter as duas seria a contagem em dobro que o próprio docstring dela
# existia para descrever.


# -------------------------------------------------------- registro elástico
@pytest.fixture
def registro(raiz):
    cartao = widgets.Cartao(raiz, "Registro")
    cartao.pack(fill="x")
    texto = tk.Text(cartao)
    texto.pack(fill="both", expand=True)
    widgets.estilo_log(texto, False)
    widgets.registro_elastico(cartao, texto, altura_minima=6)
    raiz.update()
    yield cartao, texto
    cartao.destroy()
    raiz.update()


def test_o_registro_nasce_encolhido(registro):
    cartao, texto = registro
    assert int(texto.cget("height")) == 6
    assert not cartao.pack_info()["expand"]


def test_a_tela_vazia_nao_conta_como_trabalho(registro):
    """Seis abas nascem com três linhas de instrução dentro do registro. Pelo
    tamanho elas passariam por resultado; o que as separa é a tag "ph"."""
    cartao, texto = registro
    texto.insert("end", "\n\nO resultado aparecerá aqui.\n", "ph")
    texto.update()
    assert not widgets.tem_conteudo_real(texto)
    assert not cartao.pack_info()["expand"]
    # Cabe inteiro: a tela vazia do Anexar tem cinco linhas e nasceu cortada
    # quando a altura do campo vazio era fixa em seis.
    linhas = int(texto.index("end-1c").split(".")[0])
    assert int(texto.cget("height")) > linhas


def test_a_primeira_linha_de_verdade_devolve_a_tela(registro):
    cartao, texto = registro
    texto.insert("end", "\n\nO resultado aparecerá aqui.\n", "ph")
    texto.insert("end", "Conta 1 — 12 pagamentos\n")
    texto.update()
    assert widgets.tem_conteudo_real(texto)
    assert int(texto.cget("height")) == 1
    assert cartao.pack_info()["expand"]


def test_limpar_o_registro_encolhe_de_novo(registro):
    cartao, texto = registro
    texto.insert("end", "trabalho\n")
    texto.update()
    assert cartao.pack_info()["expand"]
    texto.delete("1.0", "end")
    texto.update()
    assert not cartao.pack_info()["expand"]
    assert int(texto.cget("height")) == 6


def test_a_barra_de_titulo_nunca_derruba_a_janela(raiz):
    """Ela fala com o DWM por ctypes, e isso é território de exceção estranha:
    versão de Windows sem o atributo, HWND ainda inexistente, outro sistema.
    Nada disso pode impedir a janela de abrir — no pior caso a moldura fica na
    cor do sistema, que é exatamente o que acontecia antes."""
    top = tk.Toplevel(raiz)
    try:
        raiz.update()
        for escuro in (True, False, None):
            assert widgets.barra_de_titulo(top, escuro) is None
            assert widgets.barra_de_titulo(raiz, escuro) is None
        assert top.winfo_exists()
    finally:
        top.destroy()
        raiz.update()


def test_o_cartao_elastico_nao_muda_a_ordem_dos_widgets(raiz):
    """`pack` reempacota no FIM; `pack_configure` mantém o lugar. Em cinco
    abas o Registro passaria a nascer embaixo da barra de ação."""
    pai = ttk.Frame(raiz)
    pai.pack(fill="both", expand=True)
    primeiro = ttk.Frame(pai); primeiro.pack(fill="x")
    meio = widgets.Cartao(pai, "Registro"); meio.pack(fill="x")
    ultimo = ttk.Frame(pai); ultimo.pack(fill="x")
    raiz.update()

    widgets.cartao_elastico(meio, cheio=True)
    raiz.update()
    # Quem está empacotado no pai é a MOLDURA do cartão, não o conteúdo: são
    # dois frames desde que o cartão passou a ter título e borda próprios
    # (ver o docstring de `widgets.Cartao`). A ordem é que não pode mudar.
    assert [str(w) for w in pai.pack_slaves()] == [str(primeiro),
                                                   str(meio.moldura),
                                                   str(ultimo)]
    pai.destroy()
    raiz.update()


# ------------------------------------------- nenhuma cor fixa fora do widgets
# O CLAUDE.md afirma que "nenhuma aba escreve `#` seguido de seis dígitos", e o
# relatório de UX de agosto conferiu isso à mão, arquivo por arquivo. Regra
# conferida à mão vale até a próxima pessoa distraída — e o custo de furá-la
# não aparece em vermelho: cor escrita na criação do widget NÃO segue o tema,
# então o furo só se manifesta como uma legenda ilegível no tema que a pessoa
# que escreveu não usa. Foi exatamente esse o defeito que originou o
# `widgets.py`: `#6b6b6b` dá 3,2:1 no escuro e `#8a8a8a` dá 3,4:1 no claro,
# cada um ilegível em UM dos dois temas.
#
# Aqui a regra vira teste. Ele não julga a cor: julga o LUGAR dela.

#: Cor escrita como hexadecimal — `#rgb` ou `#rrggbb`. Fora do `widgets.py` ela
#: é sempre um furo, esteja onde estiver: argumento nomeado, item de dicionário,
#: constante de módulo ou elemento de lista.
RE_COR_HEX = re.compile(r"^#(?:[0-9A-Fa-f]{3}|[0-9A-Fa-f]{6})$")

#: Os argumentos que o Tk trata como cor.
#:
#: `fill` e `outline` estão aqui por causa do Canvas (`create_oval(fill=…)`) —
#: e são também a armadilha desta varredura: o `fill` do `pack()` é DIREÇÃO
#: ("x", "y", "both"), não cor. São 211 ocorrências de `fill="x"` no
#: repositório, e uma checagem pelo NOME do argumento acusaria as 211. Por isso
#: quem decide é o VALOR: só entra o que é mesmo uma cor.
ARGUMENTOS_DE_COR = frozenset({"fg", "bg", "foreground", "background",
                               "fill", "outline"})

#: As cores com NOME que o Tk aceita e que alguém digitaria à mão. A lista é
#: curta de propósito: ela não precisa cobrir as ~750 do X11, precisa cobrir o
#: que uma pessoa escreve sem pensar. O hexadecimal, que é o caso comum, já é
#: pego em qualquer posição pela `RE_COR_HEX`.
CORES_COM_NOME = frozenset({
    "white", "black", "red", "green", "blue", "cyan", "magenta", "yellow",
    "gray", "grey", "orange", "purple", "brown", "pink", "navy", "teal",
    "olive", "maroon", "silver", "lime", "gold", "beige", "ivory", "khaki",
    "salmon", "tan", "violet", "wheat", "azure", "coral", "crimson",
    "darkblue", "darkgreen", "darkred", "darkgray", "darkgrey", "lightblue",
    "lightgreen", "lightgray", "lightgrey", "lightyellow", "systembuttonface",
    "systemwindow", "systemwindowtext",
})

#: Quem PODE escrever cor. O `widgets.py` é o dono da paleta; `tests/` mede
#: contraste e constrói widgets de mentira, e para isso precisa de cor literal.
LIVRES_DA_REGRA = ("widgets.py",)


def _e_cor_com_nome(valor) -> bool:
    if not isinstance(valor, str):
        return False
    v = valor.strip().lower().replace(" ", "")
    return v in CORES_COM_NOME or bool(re.fullmatch(r"(?:gray|grey)\d{1,3}", v))


def _cores_fixas_em(caminho: Path, rotulo: str) -> list:
    """As cores escritas à mão em UM arquivo, como "arquivo:linha: motivo".

    `utf-8-sig` e não `utf-8`: arquivo salvo com BOM (o que o Bloco de Notas e
    o `Set-Content` do PowerShell fazem sozinhos) é UTF-8 válido, mas o
    `ast.parse` morre nele com "invalid non-printable character U+FEFF". O BOM
    não é problema desta guarda, e derrubá-la por causa dele trocaria "achei
    uma cor fixa" por um traceback que não diz nada sobre cor."""
    fonte = caminho.read_text(encoding="utf-8-sig")
    arvore = ast.parse(fonte, filename=rotulo)
    achados = []
    for no in ast.walk(arvore):
        # 1. hexadecimal em QUALQUER posição — inclusive dentro de dicionário,
        #    lista ou constante de módulo, que é por onde uma paleta paralela
        #    nasceria sem passar por argumento nomeado nenhum.
        if isinstance(no, ast.Constant) and isinstance(no.value, str) \
                and RE_COR_HEX.match(no.value):
            achados.append(f"{rotulo}:{no.lineno}: a cor {no.value} está "
                           "escrita aqui — ela tem de sair da widgets.PALETA")
        # 2. cor COM NOME, e só em posição de cor: "white" solto no meio de um
        #    texto é uma palavra, não uma cor.
        if isinstance(no, ast.Call):
            for kw in no.keywords:
                if kw.arg in ARGUMENTOS_DE_COR \
                        and isinstance(kw.value, ast.Constant) \
                        and _e_cor_com_nome(kw.value.value):
                    achados.append(
                        f"{rotulo}:{kw.value.lineno}: "
                        f"{kw.arg}={kw.value.value!r} — cor com nome não segue "
                        "o tema; use widgets.cores() ou um estilo nomeado")
    return achados


def _pys_rastreados() -> list:
    """Os `.py` que o git conhece.

    Rastreado pelo git, e não uma varredura do disco: `.venv`, `build/` e a
    pasta de trabalho de quem estiver com um experimento aberto não são o
    código do app, e uma delas com um `#FFFFFF` dentro faria o teste falhar
    por algo que não é do repositório."""
    try:
        saida = subprocess.run(["git", "ls-files", "*.py"], cwd=_RAIZ_APP,
                               capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:   # noqa: BLE001
        pytest.skip(f"sem git para listar os arquivos rastreados: {e}")
    if saida.returncode != 0:
        pytest.skip("`git ls-files` falhou: " + saida.stderr.strip())
    return [p.strip() for p in saida.stdout.splitlines() if p.strip()]


def test_nenhuma_cor_fixa_fora_do_widgets():
    """A regra do CLAUDE.md, medida em vez de conferida à mão.

    Cor escrita na criação do widget não segue o tema. O furo não dá erro, não
    aparece em teste nenhum e não incomoda quem o escreveu: ele incomoda quem
    usa o OUTRO tema, meses depois."""
    rastreados = _pys_rastreados()
    assert len(rastreados) > 50, (
        f"só {len(rastreados)} arquivos rastreados — a lista veio curta "
        "demais, e uma guarda que não olha nada passa igual")

    problemas = []
    for rel in rastreados:
        if rel in LIVRES_DA_REGRA or rel.startswith("tests/"):
            continue
        caminho = _RAIZ_APP / rel
        if not caminho.is_file():
            continue                     # rastreado mas ausente neste checkout
        problemas += _cores_fixas_em(caminho, rel)

    assert not problemas, (
        f"{len(problemas)} cor(es) fixa(s) fora do widgets.py:\n  "
        + "\n  ".join(problemas)
        + "\n\nToda cor do app nasce em widgets.PALETA, com o contraste "
          "medido nos dois temas. Quem precisa da cor crua (tk.Text, "
          "tk.Canvas) pede a widgets.cores(); o resto usa estilo nomeado.")


def test_a_varredura_de_cor_realmente_acha_cor():
    """Guarda que não guarda nada passa igual — e esta é fácil de neutralizar
    sem querer: basta um regex que nunca casa, ou uma lista de arquivos vazia,
    e o teste de cima fica verde para sempre.

    O `widgets.py` é o controle: ele é o único que PODE ter cor escrita, e tem
    a paleta inteira. Se a varredura não achar cor lá, ela não acharia em lugar
    nenhum."""
    achados = _cores_fixas_em(_RAIZ_APP / "widgets.py", "widgets.py")
    assert len(achados) > 50, (
        f"a varredura achou só {len(achados)} cores no widgets.py, que tem a "
        "paleta dos dois temas inteira: ela parou de enxergar cor")
