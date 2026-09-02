# -*- coding: utf-8 -*-
"""A aparência compartilhada: paleta, fontes e estilos nomeados.

Dois assuntos, e o primeiro NÃO precisa de tela: o contraste da paleta é
aritmética sobre constantes, então roda no CI como qualquer regra de negócio.
Os testes de fonte e de estilo abrem um Tk de verdade e pulam sem display,
como o `test_widgets.py`.
"""
import gc
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
    import ast
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
COR_DO_PASSO = "marca"

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
PARES_DE_COMPONENTE = (
    (COR_DO_PASSO, "cartao", "o círculo numerado, dentro do cartão"),
    (COR_DO_PASSO, "fundo", "o botão de passo, no cabeçalho da página"),
    ("acao", "cartao", "o botão verde, dentro de um cartão"),
    ("acao", "fundo", "o botão verde, no cabeçalho da página"),
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
