# -*- coding: utf-8 -*-
"""O campo de data — o widget que TODAS as abas com data usam.

Em 11/08/2026 ele quebrou em todas de uma vez: não dava para digitar nem para
abrir o calendário. Duas causas, e as duas estão cobertas aqui.

Os testes abrem uma janela Tk de verdade (escondida). Se o ambiente não tiver
display, eles pulam em vez de falhar.
"""
import tkinter as tk

import pytest

import widgets


# A janela `raiz` mora no conftest e é UMA para a sessão inteira — ver lá o
# porquê: dois módulos abrindo e destruindo o próprio Tk fazem o segundo pular
# com "sem display" num ambiente que tem display.


@pytest.fixture
def campo(raiz):
    var = tk.StringVar(master=raiz, value="01/08/2026")
    c = widgets.CampoData(raiz, var)
    c.pack()
    raiz.update()
    yield c, var, raiz
    # Popup vazando de um teste contamina o próximo: o registro de qual
    # calendário está aberto é do MÓDULO, não da instância.
    try:
        c._fechar_popup()
        c.destroy()
    except tk.TclError:
        pass
    raiz.update()


def _digitar(campo, root, texto, no_fim=True):
    # `focus_force` é obrigatório: evento de tecla gerado por `event_generate`
    # só chega ao widget que tem o foco, e sem ele o teste passaria por não
    # exercitar nada.
    campo.ent.focus_force()
    if no_fim:
        campo.ent.icursor("end")
    for ch in texto:
        campo.ent.insert("insert", ch)
        campo.ent.event_generate("<KeyRelease>", keysym=ch)
        root.update()


# ------------------------------------------------------------------ máscara
def test_digitar_do_zero_ganha_as_barras(campo):
    c, var, root = campo
    var.set("")
    _digitar(c, root, "05082026")
    assert var.get() == "05/08/2026"


def test_editar_no_meio_nao_destroi_a_data(campo):
    """O defeito de 11/08/2026: com "01/08/2026" e o cursor no começo,
    digitar "0" virava "00/10/8202" — a máscara remontava o campo inteiro."""
    c, var, root = campo
    c.ent.focus_force()
    c.ent.icursor(0)
    c.ent.insert(0, "0")
    c.ent.event_generate("<KeyRelease>", keysym="0")
    root.update()
    assert var.get() == "001/08/2026", (
        "a máscara mexeu no texto com o cursor no meio: " + var.get())
    assert "8202" not in var.get()


def test_apagar_no_meio_nao_remonta(campo):
    c, var, root = campo
    c.ent.focus_force()
    c.ent.icursor(3)
    c.ent.event_generate("<KeyRelease>", keysym="BackSpace")
    root.update()
    assert var.get() == "01/08/2026"


def test_completar_ano_ao_sair_do_campo(campo):
    c, var, root = campo
    var.set("05/08")
    c._completar_ano()
    assert var.get().startswith("05/08/") and len(var.get()) == 10
    var.set("05/08/26")
    c._completar_ano()
    assert var.get() == "05/08/2026"


# --------------------------------------------------------------- calendário
def _popups(w):
    achados = []
    for c in w.winfo_children():
        if isinstance(c, tk.Toplevel):
            achados.append(c)
        achados += _popups(c)
    return achados


def test_o_botao_abre_o_calendario(campo):
    c, var, root = campo
    c.bt.invoke()
    root.update()
    assert c._popup is not None
    assert len(_popups(root)) == 1


def test_o_calendario_nao_fecha_sozinho_ao_perder_foco(campo):
    """A versão sem borda nunca ganhava foco de verdade, então o `<FocusOut>`
    disparava na hora e o calendário sumia antes de aparecer."""
    c, var, root = campo
    c.bt.invoke()
    root.update()
    c._popup.event_generate("<FocusOut>")
    root.update()
    assert c._popup is not None, "o calendário fechou sozinho ao perder o foco"


def test_o_calendario_nao_prende_o_app(campo):
    """O defeito de 12/08/2026: com `grab_set`, o Tk entregava todo clique e
    toda tecla ao calendário. Só se saía dele escolhendo uma data ou fechando
    a janelinha — nem o X do app respondia.

    `grab_current()` é a prova mecânica: com alguém segurando o grab, ele
    devolve essa janela; sem ninguém, devolve None."""
    c, var, root = campo
    c.bt.invoke()
    root.update()
    assert c._popup is not None, "o calendário nem abriu"
    assert root.grab_current() is None, (
        "o calendário está modal: o resto do app fica surdo e nem dá para "
        "fechar o programa")


def test_so_um_calendario_por_vez(campo, raiz):
    """Sem o modal, nada impede clicar no 📅 de outro campo — e dois
    calendários iguais na tela não dizem qual preenche qual."""
    c, var, root = campo
    outro_var = tk.StringVar(master=raiz, value="02/08/2026")
    outro = widgets.CampoData(raiz, outro_var)
    outro.pack()
    root.update()
    try:
        c.bt.invoke()
        root.update()
        outro.bt.invoke()
        root.update()
        assert c._popup is None, "o calendário do primeiro campo ficou aberto"
        assert outro._popup is not None
        assert len(_popups(root)) == 1
    finally:
        outro._fechar_popup()
        outro.destroy()
        root.update()


def test_fechar_o_calendario_libera_o_registro_do_modulo(campo):
    """Registro de módulo que não é limpo trava o próximo: o campo seguinte
    tentaria fechar um popup que já não existe."""
    c, var, root = campo
    c.bt.invoke()
    root.update()
    assert widgets._calendario_aberto is c
    c._fechar_popup()
    root.update()
    assert widgets._calendario_aberto is None


def test_clique_simples_abre_o_calendario(campo):
    """O clique simples passou a ABRIR o calendário (redesenho de agosto/2026).

    Em 11/08/2026 abrir no clique tornou o campo impossível de editar em todas
    as abas de uma vez: o popup pegava o foco e a tecla digitada ia para ele.
    O conserto de então foi exigir duplo clique; o de agora é o popup não
    pegar foco nenhum. Por isso este teste anda em par com o de baixo — abrir
    sem que o campo deixe de ser digitável é o contrato inteiro, e testar só
    a metade que abre deixaria a regressão de 11/08 passar de novo."""
    c, var, root = campo
    c._ao_clicar()
    root.update()
    assert c._popup is not None


def test_com_o_calendario_aberto_o_campo_continua_editavel(campo):
    """A outra metade do contrato: digitar fecha o popup e o texto entra."""
    c, var, root = campo
    c._ao_clicar()
    root.update()
    assert c._popup is not None

    # Campo vazio de propósito: com "01/08/2026" dentro, a máscara remonta os
    # mesmos oito dígitos e o valor não muda — o teste passaria sem provar que
    # a tecla chegou ao campo.
    var.set("")
    _digitar(c, root, "0509")
    assert c._popup is None, (
        "o calendário sobreviveu à digitação: a próxima tecla vai para ele, "
        "que é exatamente a regressão de 11/08/2026")
    assert var.get() == "05/09"


def _achar_no_popup(w, texto, tipo):
    """Um widget do calendário pelo texto. Os dias são `tk.Label` com clique,
    e não botões: `Button` aceita foco, e aceitar foco é o que tiraria o
    cursor do campo — ver `test_clique_simples_abre_o_calendario`."""
    for filho in w.winfo_children():
        try:
            if isinstance(filho, tipo) and filho.cget("text") == texto:
                return filho
        except tk.TclError:
            pass
        achado = _achar_no_popup(filho, texto, tipo)
        if achado:
            return achado


def test_escolher_um_dia_preenche_e_fecha(campo):
    c, var, root = campo
    c.bt.invoke()
    root.update()

    dia = _achar_no_popup(c._popup, "15", tk.Label)
    assert dia is not None, "o calendário não desenhou os dias"
    dia.event_generate("<Button-1>")
    root.update()
    assert var.get() == "15/08/2026"
    assert c._popup is None


def test_botao_hoje(campo):
    from datetime import date
    c, var, root = campo
    c.bt.invoke()
    root.update()

    _achar_no_popup(c._popup, "Hoje", widgets.Botao).invoke()
    root.update()
    assert var.get() == f"{date.today():%d/%m/%Y}"
    assert c._popup is None


def test_botao_limpar(campo):
    """"Limpar" nasceu com o redesenho: o campo de data podia ser preenchido
    pelo calendário e não havia como esvaziá-lo a não ser apagando à mão."""
    c, var, root = campo
    c.bt.invoke()
    root.update()

    _achar_no_popup(c._popup, "Limpar", widgets.Botao).invoke()
    root.update()
    assert var.get() == ""
    assert c._popup is None


# ------------------------------------------------------ a bomba de UI não morre
# Estes últimos não são do campo de data. Moram aqui porque este é o arquivo de
# teste de INTERFACE do projeto, e o que eles cobrem é da mesma família: defeito
# do Tk que não quebra nada em vermelho e só aparece na frente de quem usa.
#
# A aba usada é a Separar e Renomear por ser a única sem navegador: dá para
# construí-la de verdade e mexer na fila dela sem abrir Chrome nenhum.

@pytest.fixture(scope="module")
def aba_separar(raiz):
    import separar_renomear
    aba = separar_renomear.SepararFrame(raiz)
    # De propósito NÃO destruímos a aba no fim: o `_drain` dela está agendado no
    # `after` da raiz compartilhada, e destruir o widget deixaria o próximo
    # disparo tentando escrever num campo que já não existe — barulho no meio
    # dos outros testes. Sem `pack`, ela não aparece nem atrapalha.
    raiz.update()
    return aba


def test_o_drain_sobrevive_a_um_erro_e_continua(aba_separar):
    """O modo de falha mais desesperador do app: a fila deixa de ser drenada,
    o registro congela, o botão nunca volta — e a thread segue trabalhando, sem
    ninguém saber sequer se dá para fechar o programa. Bastava UM erro que não
    fosse `queue.Empty` (um `tk.TclError` de widget recém-destruído, por
    exemplo) para o ciclo parar para sempre, porque o reagendamento ficava fora
    do `finally`."""
    aba = aba_separar
    aba.fila.put(("prog", None))          # desempacotar None levanta TypeError
    aba._drain()                          # não pode levantar...
    aba.fila.put(("log", "vivo depois do erro"))
    aba._drain()                          # ...e tem de continuar drenando
    aba._drain()
    texto = aba.txt.get("1.0", "end")
    assert "vivo depois do erro" in texto
    # E o motivo não some em silêncio: sem ele, o defeito volta a ser invisível.
    assert "falha ao atualizar a tela" in texto


def test_ocupado_e_fechar_da_aba_separar(aba_separar):
    """`ocupado()` é o que a barra lateral pergunta para acender o ● na aba que
    trabalha; `fechar()` é chamado ao sair do app, em TODAS as abas — inclusive
    nas que nunca começaram nada."""
    assert aba_separar.ocupado() is None
    aba_separar.fechar()                  # sem trabalho nenhum: não pode estourar
    assert aba_separar.ocupado() is None


def test_parar_no_meio_nao_grava_pdf_pela_metade(tmp_path):
    """Fechar o app durante o processamento matava a thread na 2ª passada — a
    que grava —, deixando arquivo pela metade na pasta de saída e nenhum
    registro do que houve. Agora a parada é pedida, e o que não foi gravado
    simplesmente não existe."""
    from pypdf import PdfWriter

    import separar_renomear

    entrada = tmp_path / "entrada"
    entrada.mkdir()
    w = PdfWriter()
    w.add_blank_page(width=200, height=200)
    with open(entrada / "um.pdf", "wb") as fh:
        w.write(fh)
    saida = tmp_path / "saida"

    linhas = []
    gerados, _erros = separar_renomear.processar(entrada, saida, linhas.append,
                                                 parar=lambda: True)
    assert gerados == 0
    assert list(saida.glob("*.pdf")) == []
    assert any("Interrompido" in linha for linha in linhas), linhas


# ------------------------------------------------- o menu pelo teclado
# Até 02/09/2026 o `ItemMenu` era um `tk.Frame` que só escutava `<Button-1>`,
# `<Enter>` e `<Leave>`. Quem usa só o teclado alcançava DIÁRIO e MENSAL (que
# são `ttk.Button`) e não alcançava NENHUMA das doze telas — o contrário da
# regra que o próprio `comprovantes_app.py` escreveu para os cabeçalhos de
# grupo, dois parágrafos acima do código que a desmentia.

@pytest.fixture
def coluna(raiz):
    """Três itens de menu numa coluna, como o menu de verdade os empilha."""
    pai = tk.Frame(raiz)
    pai.pack(fill="x")
    contagem = {}
    itens = []
    for chave, icone, texto in (("ini", "▦", "Início"),
                                ("anx", "📎", "Anexar"),
                                ("rel", "📊", "Relatório Mensal")):
        contagem[chave] = 0
        it = widgets.ItemMenu(
            pai, texto, icone=icone,
            comando=lambda c=chave: contagem.__setitem__(c, contagem[c] + 1))
        it.pack(fill="x")
        itens.append(it)
    raiz.update()
    yield pai, itens, contagem
    pai.destroy()
    raiz.update()


def test_o_tab_passa_por_cada_item_do_menu(coluna):
    """A coluna inteira tem de estar no caminho do Tab, e não só os grupos.

    `tk_focusNext` é a MESMA travessia que a tecla Tab usa — o Tk a consulta
    para decidir quem é o próximo —, então percorrê-la é perguntar ao Tk o que
    o Tab faria, em vez de confiar que `takefocus=1` baste.

    **A travessia parte do widget que se passa, não do que tem o foco.** O
    `tk_focusNext w` do `focus.tcl` só olha a árvore (`winfo children`,
    `winfo parent`), o `takefocus` e o `winfo viewable` de cada um; o foco do
    momento não entra na conta. A primeira versão deste teste dava
    `focus_force()` ao primeiro item antes de percorrer, e `focus -force` era
    a única chamada daqui que falava com o gerenciador de janelas — à toa,
    porque o resultado não mudava com ela. Saiu.

    O teste foi intermitente (2 falhas em 4 rodadas da suíte inteira em
    02/09/2026, nenhuma rodando o arquivo sozinho), e a suspeita caiu sobre o
    `focus_force`. Não era: o erro era `invalid command name "tk_focusNext"`,
    e a causa mora na captura de saída do pytest — ver
    `tcl_com_handles_proprios` no conftest, que é onde o conserto está."""
    pai, itens, _ = coluna
    for it in itens:
        assert str(it.cget("takefocus")) == "1", (
            f"{it.texto()} não aceita foco: o Tab passa direto por ele")

    visitados = []
    atual = itens[0]
    for _ in range(len(itens)):
        visitados.append(atual)
        atual = atual.tk_focusNext()
    assert visitados == itens, (
        "o Tab não percorre os itens na ordem em que a coluna é lida: "
        f"{[getattr(w, 'texto', lambda: str(w))() for w in visitados]}")


@pytest.mark.parametrize("tecla", ["<Return>", "<space>"])
def test_enter_e_espaco_abrem_a_aba(coluna, tecla):
    """As duas teclas fazem o que o clique faz — e é o MESMO comando.

    Um caminho só, de propósito: com dois, existiria a chance de o teclado
    abrir uma aba e o mouse abrir outra."""
    pai, itens, contagem = coluna
    alvo = itens[1]                       # "Anexar"
    alvo.focus_force()
    pai.update()
    alvo.event_generate(tecla)
    pai.update()
    assert contagem["anx"] == 1, f"{tecla} não acionou o item com o foco"
    assert contagem["ini"] == 0 and contagem["rel"] == 0, (
        "a tecla acionou um item que não era o do foco")


def test_o_item_com_foco_nao_se_parece_com_o_sem_foco(coluna):
    """Foco que não aparece na tela não serve para quem navega por Tab.

    Quem carrega o sinal é o ANEL (`highlightcolor`, na cor `marca`) e o
    filete da borda esquerda — o fundo sozinho dá 1,16:1 contra a coluna no
    tema claro e 1,20:1 no escuro, ou seja, não distingue nada. Ver as medidas
    no docstring de `widgets.ItemMenu`."""
    pai, itens, _ = coluna
    alvo = itens[1]

    def aparencia(it):
        return (str(it.cget("background")),
                str(it.filete.cget("background")),
                str(it.cget("highlightcolor")),
                str(it.cget("highlightbackground")))

    itens[0].focus_force()
    pai.update()
    sem_foco = aparencia(alvo)
    alvo.focus_force()
    pai.update()
    com_foco = aparencia(alvo)

    assert com_foco != sem_foco, (
        "o item com foco está idêntico ao sem foco: quem navega por Tab não "
        "tem como saber onde está")
    # O anel só existe se houver espessura para desenhá-lo, e a espessura não
    # pode mudar com o foco: 1 px entrando e saindo empurraria a coluna
    # inteira para baixo a cada tecla.
    assert int(alvo.cget("highlightthickness")) == 1
    assert (str(alvo.cget("highlightcolor"))
            != str(alvo.cget("highlightbackground"))), (
        "o anel de foco está da mesma cor do fundo: ele não vai aparecer")


def test_o_item_aberto_tambem_mostra_o_foco(coluna):
    """O caso que o fundo sozinho não resolveria: o item ABERTO já é o mais
    destacado da coluna, e sem o anel o foco pousaria nele sem sinal nenhum."""
    pai, itens, _ = coluna
    alvo = itens[1]
    alvo.ativar(True)
    pai.update()
    assert (str(alvo.cget("highlightcolor"))
            != str(alvo.cget("highlightbackground")))


def test_o_teclado_e_o_clique_chamam_o_mesmo_comando(coluna):
    pai, itens, contagem = coluna
    alvo = itens[2]
    alvo.focus_force()
    pai.update()
    alvo.event_generate("<Return>")
    alvo._clique()                        # o caminho do mouse
    pai.update()
    assert contagem["rel"] == 2


# ------------------------------------------------------------ os ícones
# Os ícones do menu eram emoji e dingbats soltos, e o Tk pegava para cada um a
# fonte que o Windows achasse primeiro: medido com `font actual`, no mínimo
# QUATRO famílias numa coluna de doze linhas (Lucida Sans Unicode, Cambria,
# MS Gothic e Segoe UI Emoji). As duas que caem na Segoe UI Emoji vêm de fonte
# COLORIDA, e cor de glifo colorido não obedece ao `foreground`: essas ficavam
# iguais nos dois temas. Ver o bloco "ícones" no topo do `widgets.py`.

def test_o_icone_do_menu_segue_a_familia_encontrada(coluna):
    """Com uma família de ícones presente, o rótulo passa a mostrar o codepoint
    monocromático NA fonte de ícones; sem nenhuma, continua o emoji de sempre.
    Os dois desfechos são legítimos — o que não pode é o rótulo pedir a fonte
    de ícones e mostrar um emoji, que é o quadradinho de glifo ausente."""
    pai, itens, _ = coluna
    familia = widgets.familia_de_icones()
    for it in itens:
        desenho = str(it.lbl_icone.cget("text"))
        fonte = str(it.lbl_icone.cget("font"))
        if familia:
            assert fonte == widgets.FONTE_ICONES, (
                f"{it.texto()}: há {familia} instalada e o ícone não está "
                "pedindo a fonte de ícones")
            assert desenho in widgets.ICONES_POR_FAMILIA[familia].values(), (
                f"{it.texto()}: o desenho {desenho!r} não é um codepoint da "
                f"tabela de {familia}")
        else:
            assert fonte == "", (
                f"{it.texto()}: sem família de ícones, o rótulo não pode "
                "pedir a fonte de ícones — sairia quadradinho")
            assert desenho == it._icone


def test_a_aba_que_trabalha_volta_para_a_fonte_de_texto(coluna):
    """O ● (U+25CF) não está na fonte de ícones: pedi-lo a ela daria o
    quadradinho de glifo ausente justamente no sinal que existe para dizer
    ONDE o trabalho está."""
    pai, itens, _ = coluna
    alvo = itens[1]
    alvo.trabalhando(True)
    pai.update()
    assert str(alvo.lbl_icone.cget("text")) == "●"
    assert str(alvo.lbl_icone.cget("font")) == "", (
        "o ● está sendo pedido à fonte de ícones, que não o tem")

    alvo.trabalhando(False)
    pai.update()
    assert str(alvo.lbl_icone.cget("text")) != "●", (
        "o ícone de sempre não voltou quando o trabalho acabou")


# ------------------------------------------------- a busca da barra de cima
# Até 02/09/2026 o campo dizia "Buscar lançamento, empresa ou conta… (Ctrl+K)"
# e o Enter ali só devolvia o cursor ao primeiro campo da aba aberta: ele
# prometia três coisas e não fazia nenhuma. Agora ele promete UMA — pular para
# uma das telas do menu — e é essa promessa que estes testes cobram.

#: Os doze nomes na ordem em que o menu os empilha, copiados do
#: `comprovantes_app.main()`. Escritos aqui porque os rótulos moram dentro da
#: função que monta a janela, e ela não roda sem login e sem nuvem.
TELAS_DO_MENU = ("Início", "Baixar Comprovantes", "Separar e Renomear",
                 "Anexar", "Conferência", "Aportes", "Remessa/Retorno",
                 "Saldo de pagamentos", "Relatório Mensal", "Extratos Sicoob",
                 "Contratos", "Acessorias")


@pytest.fixture
def barra(raiz):
    """A barra de cima com as doze telas, do jeito que o app a alimenta:
    pares (nome, comando), e o comando é o que abre a tela."""
    b = widgets.BarraTopo(raiz)
    b.pack(fill="x")
    abertas = []
    b.definir_telas((nome, lambda n=nome: abertas.append(n))
                    for nome in TELAS_DO_MENU)
    raiz.update()
    yield b, abertas, raiz
    try:
        b._fechar_lista()
        b.destroy()
    except tk.TclError:
        pass
    raiz.update()


def _buscar(b, raiz, texto: str):
    """Digita no campo como quem digita: Ctrl+K, o texto, e a tecla solta que
    é o que dispara o filtro."""
    b.focar_busca()
    b.busca.delete(0, "end")
    b.busca.insert(0, texto)
    b.busca.event_generate("<KeyRelease>")
    raiz.update()


def test_a_dica_promete_so_o_que_o_campo_faz(barra):
    """O texto do campo é a única documentação que o usuário lê. Ele não pode
    citar lançamento, empresa nem conta: nada disso é procurável aqui — daria
    um índice do ERP, e a busca não fala com o ERP nem com a rede."""
    b, _, _ = barra
    assert "tela" in widgets.BarraTopo.DICA.lower()
    assert "Ctrl+K" in widgets.BarraTopo.DICA
    for promessa in ("lançamento", "empresa", "conta"):
        assert promessa not in widgets.BarraTopo.DICA.lower(), (
            f"a dica ainda promete procurar {promessa}, e ela não procura")
    assert b.busca.get() == widgets.BarraTopo.DICA


@pytest.mark.parametrize("termo, esperada", [
    ("rem", "Remessa/Retorno"),
    ("saldo", "Saldo de pagamentos"),
    # Sem acento e sem caixa, como toda comparação de nome do projeto
    # (`util.norm_espaco`): quem procura digita o que lembra, não o que o
    # rótulo tem de sinal gráfico.
    ("CONFERENCIA", "Conferência"),
    ("relatorio", "Relatório Mensal"),
    # Pedaço em qualquer posição, e não só o começo do nome.
    ("sicoob", "Extratos Sicoob"),
])
def test_o_enter_pula_para_a_primeira_tela_que_bate(barra, termo, esperada):
    b, abertas, raiz = barra
    _buscar(b, raiz, termo)
    b.busca.event_generate("<Return>")
    raiz.update()
    assert abertas == [esperada], (
        f"{termo!r} devia abrir {esperada!r} e abriu {abertas}")
    # E o campo volta para a dica: ele é um "para onde vou", não um filtro que
    # fica posto.
    assert b.busca.get() == widgets.BarraTopo.DICA


def test_texto_sem_par_nao_move_o_foco(barra):
    """Não achar nada e "achar a tela errada" precisam ser distinguíveis. Sem
    par, o Enter não abre nada e o foco fica onde está — e a lista diz isso em
    letras, em vez de sumir (campo que não responde parece travado)."""
    b, abertas, raiz = barra
    _buscar(b, raiz, "xablau")
    assert b._achados == []
    assert b._popup is not None, "a lista sumiu em vez de dizer que não achou"
    textos = [str(w.cget("text")) for w in b._moldura.winfo_children()]
    assert any("Nenhuma tela" in t for t in textos), textos

    b.busca.event_generate("<Return>")
    raiz.update()
    assert abertas == []
    assert str(raiz.focus_get()) == str(b.busca), (
        "sem tela que bata, o Enter mexeu no foco")


def test_o_esc_limpa_e_devolve_o_foco_de_onde_ele_veio(barra):
    """O Ctrl+K vale com o foco em qualquer lugar, inclusive no meio de um
    campo pela metade. Desistir tem de deixar a pessoa onde ela estava."""
    b, abertas, raiz = barra
    campo = tk.Entry(raiz)
    campo.pack()
    campo.insert(0, "01/08/2026")
    campo.focus_force()
    raiz.update()

    _buscar(b, raiz, "rem")
    assert str(raiz.focus_get()) == str(b.busca)

    b.busca.event_generate("<Escape>")
    raiz.update()
    assert abertas == [], "o Esc abriu uma tela"
    assert b.busca.get() == widgets.BarraTopo.DICA
    assert b._popup is None, "a lista continuou aberta depois do Esc"
    assert str(raiz.focus_get()) == str(campo), (
        "o Esc não devolveu o foco ao campo que estava sendo preenchido")
    campo.destroy()


def test_as_setas_andam_pela_lista_e_o_enter_abre_a_realcada(barra):
    b, abertas, raiz = barra
    _buscar(b, raiz, "s")                 # bate em várias
    assert len(b._achados) > 1
    primeira, segunda = b._achados[0][0], b._achados[1][0]
    assert b._realce == 0
    b.busca.event_generate("<Down>")
    raiz.update()
    b.busca.event_generate("<Return>")
    raiz.update()
    assert abertas == [segunda] and abertas != [primeira]


def test_a_busca_abre_a_tela_pelo_mesmo_caminho_do_clique(raiz):
    """Um caminho só: o comando que a barra guarda é o `acionar` do próprio
    `ItemMenu`. Com dois, existiria a chance de a busca abrir uma tela e o
    clique abrir outra."""
    pai = tk.Frame(raiz)
    pai.pack(fill="x")
    contagem = {"n": 0}
    item = widgets.ItemMenu(pai, "Remessa/Retorno", icone="🗓",
                            comando=lambda: contagem.__setitem__(
                                "n", contagem["n"] + 1))
    item.pack(fill="x")
    b = widgets.BarraTopo(raiz)
    b.pack(fill="x")
    b.definir_telas([(item.texto(), item.acionar)])
    raiz.update()
    try:
        item._clique()                    # o caminho do mouse
        _buscar(b, raiz, "remessa")
        b.busca.event_generate("<Return>")
        raiz.update()
        assert contagem["n"] == 2, (
            "a busca não passou pelo mesmo comando que o clique")
    finally:
        b._fechar_lista()
        b.destroy()
        pai.destroy()
        raiz.update()


def test_sem_telas_definidas_a_busca_nao_abre_lista(raiz):
    """A barra nasce antes de o menu existir — ela é a primeira coisa que o
    `main()` empacota. Até `definir_telas` ser chamada não há para onde ir, e
    abrir uma lista vazia diria que o app não tem telas."""
    b = widgets.BarraTopo(raiz)
    b.pack(fill="x")
    raiz.update()
    try:
        b.focar_busca()
        b.busca.insert(0, "rem")
        b.busca.event_generate("<KeyRelease>")
        raiz.update()
        assert b._popup is None
        b.busca.event_generate("<Return>")
        raiz.update()                     # e não estoura
    finally:
        b._fechar_lista()
        b.destroy()
        raiz.update()


def test_trocar_de_tema_fecha_a_lista(barra):
    """A lista lê a paleta ao nascer e vive o tempo de uma digitação: repintá-la
    custaria mais do que redesenhá-la na próxima tecla — a mesma decisão do
    calendário do `CampoData`."""
    b, _, raiz = barra
    _buscar(b, raiz, "a")
    assert b._popup is not None
    b.aplicar_cores(True)
    raiz.update()
    assert b._popup is None


def test_fechar_da_acessorias_sem_nada_aberto(raiz):
    """O `_sair()` do app percorre as abas chamando `fechar()`. O da Acessórias
    fecha o Chrome do portal na thread dele e desliga o executor — e precisa ser
    seguro quando não há navegador nenhum, que é o caso mais comum."""
    pytest.importorskip("playwright")
    from acessorias.frame import AcessoriasFrame

    aba = AcessoriasFrame(raiz)
    try:
        assert aba.ocupado() is None
        assert aba.portal is None
        aba.fechar()
        aba.fechar()                      # duas vezes também não pode estourar
    finally:
        aba.fechar()
