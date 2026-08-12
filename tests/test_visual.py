# -*- coding: utf-8 -*-
"""A aparência compartilhada: paleta, fontes e estilos nomeados.

Dois assuntos, e o primeiro NÃO precisa de tela: o contraste da paleta é
aritmética sobre constantes, então roda no CI como qualquer regra de negócio.
Os testes de fonte e de estilo abrem um Tk de verdade e pulam sem display,
como o `test_widgets.py`.
"""
import gc
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import pytest

import widgets


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


def test_o_cartao_numera_so_quando_ha_ordem(raiz):
    """Numerar informa quando existe sequência; no Registro seria inventar uma."""
    assert widgets.Cartao(raiz, "Período", 1).cget("text") == " 1. Período "
    assert widgets.Cartao(raiz, "Registro").cget("text") == " Registro "


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
    assert str(quadro.focus_get()) == str(data)


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
@pytest.fixture
def trilha(raiz):
    b1 = ttk.Button(raiz, text="1")
    b2 = ttk.Button(raiz, text="2", state="disabled")
    t = widgets.Passos(raiz, (("Buscar", b1), ("Gerar", b2)))
    t.pack()
    raiz.update()
    yield t, b1, b2
    t.destroy(); b1.destroy(); b2.destroy()
    raiz.update()


def _trilha(t):
    return [(l.cget("text"), str(l.cget("style"))) for l in t._rotulos]


def test_a_trilha_comeca_no_primeiro_passo(trilha):
    t, _b1, _b2 = trilha
    assert _trilha(t) == [("①  Buscar", "PassoAtivo.TLabel"),
                          ("②  Gerar", "PassoFalta.TLabel")]


def test_o_passo_cumprido_vira_visto(trilha):
    t, b1, b2 = trilha
    b1.configure(state="disabled")
    b2.configure(state="normal")
    t._pintar()
    assert _trilha(t) == [("✓  Buscar", "PassoFeito.TLabel"),
                          ("②  Gerar", "PassoAtivo.TLabel")]


def test_com_tudo_desabilitado_a_trilha_segura_o_estado(trilha):
    """Enquanto o trabalho roda, a aba desabilita TODOS os botões. Zerar aí
    diria que nada começou, bem no momento em que mais coisa acontece."""
    t, b1, b2 = trilha
    b1.configure(state="disabled")
    b2.configure(state="normal")
    t._pintar()
    b2.configure(state="disabled")       # começou a trabalhar
    t._pintar()
    assert _trilha(t) == [("✓  Buscar", "PassoFeito.TLabel"),
                          ("②  Gerar", "PassoAtivo.TLabel")]


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
    assert [str(w) for w in pai.pack_slaves()] == [str(primeiro), str(meio),
                                                   str(ultimo)]
    pai.destroy()
    raiz.update()
