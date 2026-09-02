# -*- coding: utf-8 -*-
"""Widgets compartilhados pelas abas.

Por que NÃO fica no util.py
---------------------------
O `util.py` é declaradamente "sem dependências pesadas": ele é importado por
`pagamentos_dia/relatorio.py`, `relatorios/contas_mc.py` e
`conciliacao/parsing.py`, que são módulos de REGRA — sem navegador e sem
tkinter, justamente para rodarem inteiros em teste. Botar `tkinter` lá dentro
arrastaria a interface para dentro dessas regras e para dentro do CI.

Então a parte visual mora aqui. Fica na RAIZ (como o util.py) e é copiada para
o codigo.zip junto dele.
"""
from __future__ import annotations

import calendar
import datetime as _dt
import json
import re
import time
import weakref
from datetime import date

import tkinter as tk
from tkinter import ttk

import util                            # comparação de nome: sem acento, sem caixa

MESES = ("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro")

#: Iniciais dos dias na ordem em que o `calendar` do Python monta a semana
#: (segunda a domingo).
#: A semana começa no DOMINGO, como nos calendários de parede daqui — foi
#: assim que o dono pediu, e é a forma que a pessoa já lê sem pensar. O
#: `calendar` do Python começa na segunda por padrão (ISO), então quem monta a
#: grade precisa dizer o contrário: ver `SEMANA_COMECA_EM`.
DIAS_DA_SEMANA = ("D", "S", "T", "Q", "Q", "S", "S")

#: 6 = domingo, na contagem do módulo `calendar` (segunda = 0). As duas coisas
#: — a ordem das iniciais acima e este número — têm de andar juntas: mudar uma
#: sem a outra alinha o dia 1 na coluna errada, e o mês inteiro escorrega.
SEMANA_COMECA_EM = 6


# ===================================================================== visual
# Aparência compartilhada: paleta, fontes e os três blocos que TODA aba monta
# (cabeçalho, cartão de passo, campo de registro).
#
# Por que centralizar
# -------------------
# Cada aba escolhia as próprias cores e fontes: 51 cores fixas e 17 tuplas
# ("Segoe UI", 14, "bold") espalhadas por 12 arquivos. Duas consequências,
# as duas visíveis para quem usa:
#
# 1. os cinzas de legenda eram fixos, então NÃO seguiam o tema. `#6b6b6b`
#    tem 3,2:1 de contraste sobre o fundo escuro do sv-ttk (o mínimo legível
#    é 4,5:1) e `#8a8a8a` tem 3,4:1 sobre o claro — cada cinza falhava em um
#    dos dois temas, e o `aplicar_cores(escuro)` das abas não alcançava
#    essas linhas porque a cor estava escrita na criação do widget;
# 2. tamanho de fonte em número fixo ignora a escala de exibição do Windows.
#    Quem usa 150% via os títulos miúdos, e é justamente quem aumentou a
#    escala que precisava deles maiores.
#
# Aqui a cor vira ESTILO NOMEADO do ttk ("Apoio.TLabel") e o tamanho vira
# fonte NOMEADA derivada do `TkDefaultFont`. Trocar o tema reconfigura os dois
# de uma vez, e nenhuma aba precisa saber que isso aconteceu.

#: A paleta inteira do app, nos dois temas. Não é mais "só o que o sv-ttk não
#: resolve": desde o redesenho de agosto/2026 a janela tem fundo de painel
#: (cinza-azulado), cartões brancos com borda e uma barra superior da cor da
#: marca — nada disso o tema do sv-ttk sabe pintar, e todos são cor de
#: ESTRUTURA, não de texto.
#:
#: Regra que continua valendo para toda cor de TEXTO: mínimo de 4,5:1 sobre o
#: fundo em que ela aparece, medido (não estimado). As três cores do mockup
#: que não passavam entraram um tom mais escuras, e só essas três:
#:
#:   tenue    #8A94A8 dava 2,70:1 sobre o fundo do painel → #656E84 (4,51:1)
#:   ação     branco sobre #0B9E56 dava 3,48:1            → #088347 (4,83:1)
#:   ok       #0E8A4C sobre a pílula dava 3,89:1          → #0C7A43 (4,77:1)
#:   erro     #C6352B sobre a pílula dava 4,48:1          → #BF3129 (4,79:1)
#:
#: O #8A94A8 e o #0B9E56 do mockup não sumiram: viraram `linha` e `acao_viva`,
#: usados onde não há texto por cima (filetes, bolinhas, realce de KPI).
#:
#: A mesma separação de PAPEL explica a `marca_solida`, e ela veio depois. A
#: `marca` do escuro (#6F9BFF) foi medida como TEXTO — 6,3:1 sobre o cartão —
#: e nesse papel continua ótima (KPIMarca.TLabel, item aberto do menu, linha
#: selecionada da tabela). Só que a mesma cor era usada como FUNDO SÓLIDO com
#: branco por cima, no botão de passo e no círculo numerado do cartão: ali ela
#: dava 2,69:1, abaixo até do piso de 3:1 de componente. Uma cor não é boa ou
#: ruim sozinha — é boa ou ruim CONTRA alguma coisa —, e quando os dois usos
#: pedem números opostos a saída é o papel novo, não escurecer a cor de texto.
#:
#: O tema escuro deriva pelo mesmo método — cada valor foi medido contra o
#: fundo do SEU tema, e nenhum entrou por parecer bonito ao lado do claro.
PALETA = {
    "claro": {
        # ---- estrutura
        "fundo":       "#EEF1F7",   # a área de conteúdo, atrás dos cartões
        "cartao":      "#FFFFFF",
        "borda":       "#DBE1EC",
        "linha":       "#8A94A8",   # filete, ícone — nunca texto
        "zebra":       "#F7F9FC",   # a linha par das tabelas
        "cabecalho":   "#F3F5FA",   # cabeçalho de tabela
        # ---- texto
        "texto":       "#1C2537",   # 15,3:1 no cartão · 13,6:1 no fundo
        "apoio":       "#5B6880",   #  5,6:1            ·  5,0:1
        "tenue":       "#656E84",   #  5,1:1            ·  4,5:1
        # ---- marca
        "marca":       "#1746C7",   #  7,7:1 no cartão · branco por cima 7,7:1
        # O azul que é FUNDO com branco por cima (botão de passo, círculo
        # numerado, dia escolhido). No claro é a MESMA cor da `marca` — aqui
        # ela já servia nos dois papéis, e mudá-la mexeria na tela de quem não
        # tem problema nenhum.
        "marca_solida": "#1746C7",  # branco por cima 7,7:1 · 7,7:1 no cartão
        "marca_barra": "#1746C7",   # a barra superior
        "marca_fundo": "#E8EEFC",   # item ativo do menu, pílula de informação
        "marca_sub":   "#C6D4F5",   # texto secundário DENTRO da barra  5,2:1
        # ---- ação
        "acao":        "#088347",   # o botão verde: branco por cima  4,8:1
        "acao_ativo":  "#066B3A",   # o mesmo botão sob o cursor
        "acao_viva":   "#0B9E56",   # o verde do mockup, sem texto por cima
        # ---- estados (texto sobre a pílula da mesma linha)
        "ativo":       "#1746C7",   # está rodando agora
        "ok":          "#0C7A43",   "ok_fundo":      "#E3F5EB",   # 4,8:1
        "atencao":     "#9A6200",   "atencao_fundo": "#FBF0DA",   # 4,5:1
        "erro":        "#BF3129",   "erro_fundo":    "#FBE7E5",   # 4,8:1
        "info":        "#1746C7",   "info_fundo":    "#E8EEFC",   # 6,6:1
        # ---- registro (terminal embutido: escuro NOS DOIS TEMAS)
        "log_fundo":   "#101623",
        "log_texto":   "#C7D2E4",   # 11,9:1
    },
    "escuro": {
        "fundo":       "#0F131B",
        "cartao":      "#171D28",
        "borda":       "#2B3546",
        "linha":       "#4A5568",   # filete, ícone — nunca texto
        "zebra":       "#1B2230",
        "cabecalho":   "#1E2634",
        "texto":       "#E8ECF4",   # 14,3:1 no cartão · 15,7:1 no fundo
        "apoio":       "#A6B2C6",   #  7,9:1            ·  8,7:1
        "tenue":       "#8792A8",   #  5,4:1            ·  5,9:1
        "marca":       "#6F9BFF",   #  6,3:1 no cartão — só como TEXTO
        # Aqui os dois papéis se separam: como fundo sólido, a `marca` deixa o
        # branco em 2,69:1. Este tom é o ponto em que as duas medidas passam
        # ao mesmo tempo — clarear mais afunda o branco, escurecer mais some a
        # forma do botão dentro do cartão.
        "marca_solida": "#3B6FE0",  # branco por cima 4,63:1 · 3,65:1 no cartão
        "marca_barra": "#12379C",   # a barra continua azul, um tom mais fundo
        "marca_fundo": "#1B2A50",
        "marca_sub":   "#BFD0F5",
        "acao":        "#12864F",   # branco por cima  4,6:1
        "acao_ativo":  "#0D6E40",
        "acao_viva":   "#2FBE79",
        "ativo":       "#6F9BFF",
        "ok":          "#63D38F",   "ok_fundo":      "#12301F",   # 7,7:1
        "atencao":     "#F2B65C",   "atencao_fundo": "#33260C",   # 8,2:1
        "erro":        "#FF8F84",   "erro_fundo":    "#3A1A18",   # 7,1:1
        "info":        "#8FB2FF",   "info_fundo":    "#1B2A50",   # 6,7:1
        "log_fundo":   "#101623",
        "log_texto":   "#C7D2E4",
    },
}

#: Cores do registro que NÃO mudam com o tema: ele é um terminal embutido, e
#: um terminal claro no meio de um painel claro deixa de parecer registro.
LOG_CORES = {
    "ts":     "#7C8AA3",   # 5,2:1 sobre o fundo do registro
    "ok":     "#5FD08E",   # 9,4:1
    "aviso":  "#F0B354",   # 9,7:1
    "erro":   "#FF8A80",   # 7,9:1
}

#: Margem lateral das abas. Era `PADX = 14` redigitado em cada `_build`.
#: Subiu para 20 com o redesenho: agora ela é a folga entre o cartão branco e
#: a borda do painel, e não mais entre o texto e a borda da janela.
PADX = 20

#: Fontes nomeadas do Tk. Nome e não tupla: mudam em todo lugar de uma vez.
FONTE_TITULO = "AppTitulo"      # título da página (19 px no padrão do Windows)
FONTE_SECAO = "AppSecao"        # título de diálogo e de cartão
FONTE_APOIO = "AppApoio"        # legenda, explicação, placeholder
FONTE_MONO = "AppMono"          # campos de registro
FONTE_MINI = "AppMini"          # trilha, cabeçalho de tabela, rótulo de campo
FONTE_MINI_FORTE = "AppMiniForte"   # a mesma, em maiúsculas de seção do menu
FONTE_FORTE = "AppForte"        # nome do favorecido, número de rodapé
FONTE_NUM = "AppNum"            # dinheiro em tabela: dígito de largura fixa
FONTE_MONO_MINI = "AppMonoMini"  # chave Pix / linha digitável dentro da célula
FONTE_KPI = "AppKPI"            # o número grande dos cartões do Início
FONTE_MARCA = "AppMarca"        # o logotipo da barra superior

#: Família dos campos de registro. NÃO sai do `TkFixedFont`: no Windows ele é
#: "Courier New", que é a fonte de máquina de escrever e fica larga e fraca ao
#: lado da Segoe UI. Consolas vem com o Windows desde o Vista, e era a escolha
#: que as seis abas já faziam à mão.
FAMILIA_MONO = "Consolas"

_estado = {"escuro": False}


def cores() -> dict:
    """Paleta do tema em uso. Para quem precisa da cor crua (Text, Canvas)."""
    return PALETA["escuro" if _estado["escuro"] else "claro"]


def _escalar(tam: int, fator: float) -> int:
    """Escala preservando o sinal.

    Tamanho NEGATIVO no Tk não é erro: é a medida em pixels, e não em pontos.
    Multiplicar sem cuidado transformava 1,55× num título menor que o corpo."""
    v = max(int(round(abs(tam) * fator)), 1)
    return -v if tam < 0 else v


def _garantir_fontes():
    """Cria (ou reconfigura) as fontes nomeadas a partir das do sistema.

    Sai do `TkDefaultFont` de propósito: ele já vem na família e no tamanho
    que a pessoa escolheu no Windows, então a escala de exibição é respeitada
    sem o app precisar consultá-la.

    Fala com o Tcl direto (`font create` / `font configure`) em vez de usar o
    `tkinter.font`. Não é preciosismo: o exe do usuário só contém os módulos
    que o `_garantir_dependencias()` do motor.py importa, e `tkinter.font` não
    está lá. Importá-lo aqui derrubava o app inteiro no `import widgets`, antes
    de qualquer janela — e como só o CÓDIGO se atualiza sozinho, a única saída
    seria um exe novo de 152 MB para todo mundo. Ver v1.0.71.

    De quebra some uma armadilha: `tkinter.font.Font.__del__` executa um
    `font delete` no Tcl, então guardar a fonte numa variável local a apagava
    no primeiro coletor de lixo — e o sintoma não era erro nenhum, o Tk passava
    a ler "AppTitulo" como NOME DE FAMÍLIA, não achava, e caía na fonte padrão.
    Fonte nomeada criada por `font create` não pertence a objeto Python nenhum:
    não há `__del__` para apagá-la."""
    tcl = ttk.Style().tk                 # o interpretador da janela em uso
    familia = str(tcl.call("font", "configure", "TkDefaultFont", "-family"))
    try:
        tam = int(tcl.call("font", "configure", "TkDefaultFont", "-size")) or 9
    except (ValueError, tk.TclError):
        tam = 9

    existentes = set(tcl.splitlist(tcl.call("font", "names")))
    for nome, fator, peso, fam in (
            (FONTE_TITULO, 1.55, "bold", familia),
            (FONTE_SECAO, 1.15, "bold", familia),
            (FONTE_APOIO, 0.92, "normal", familia),
            (FONTE_MONO, 1.0, "normal", FAMILIA_MONO),
            # As de baixo nasceram com o painel. Continuam saindo do
            # `TkDefaultFont` pelo mesmo motivo das de cima: quem usa o
            # Windows a 150% precisa que o cabeçalho de tabela cresça junto.
            (FONTE_MINI, 0.82, "normal", familia),
            (FONTE_MINI_FORTE, 0.82, "bold", familia),
            (FONTE_FORTE, 1.0, "bold", familia),
            (FONTE_NUM, 0.95, "normal", FAMILIA_MONO),
            (FONTE_MONO_MINI, 0.82, "normal", FAMILIA_MONO),
            (FONTE_KPI, 2.2, "bold", familia),
            (FONTE_MARCA, 1.15, "bold", familia)):
        acao = "configure" if nome in existentes else "create"
        tcl.call("font", acao, nome,
                 "-family", fam, "-size", _escalar(tam, fator), "-weight", peso)


#: Os widgets clássicos do Tk que precisam ser repintados na troca de tema.
#:
#: Por que existe: o botão verde, o cartão branco e a barra azul NÃO são ttk.
#: O sv-ttk desenha botão e moldura a partir de IMAGENS, com a cor assada
#: dentro; um `style.configure(background=...)` não muda uma imagem. Pintar de
#: verde só era possível voltando ao widget clássico do Tk — que, em troca,
#: não sabe nada de tema e guarda para sempre a cor com que nasceu.
#:
#: `WeakSet` e não lista: aba fechada, diálogo destruído e calendário que
#: sumiu não podem continuar vivos só porque a paleta os conhece.
_repintaveis = weakref.WeakSet()


def _repintar_todos():
    for w in list(_repintaveis):
        try:
            w.aplicar_cores(_estado["escuro"])
        except (tk.TclError, AttributeError):
            pass                         # widget já destruído: sai sozinho


def aplicar_estilos(escuro: bool) -> None:
    """Ponto único de troca de tema. Chamar SEMPRE depois de `sv_ttk.set_theme`.

    O sv-ttk recria o tema do zero a cada troca, e isso apaga todo estilo
    nomeado configurado antes. Chamar na ordem errada não dá erro: as legendas
    simplesmente voltam à cor padrão, e a diferença é sutil o bastante para
    passar despercebida até alguém abrir no tema escuro."""
    _estado["escuro"] = bool(escuro)
    _garantir_fontes()
    c = cores()
    st = ttk.Style()

    # ---------------------------------------------------------------- fundo
    # O fundo PADRÃO do ttk passa a ser o do CARTÃO, e não o da janela.
    #
    # Parece invertido, e é de propósito: quase todo `ttk.Label`, `ttk.Frame` e
    # `ttk.Checkbutton` do app mora DENTRO de um cartão. Fazendo o padrão ser o
    # branco, as dez abas ganharam o cartão sem que nenhuma delas precisasse
    # dizer, widget a widget, em que fundo cada legenda está — e o cinza do
    # painel entra só onde é pedido, pelo estilo "Fundo.*".
    #
    # O preço: o sv-ttk assa o fundo dele (#fafafa no claro) nos cantos
    # arredondados das imagens de botão e de campo. Contra o branco a emenda é
    # de cinco níveis e não se vê; contra o cinza do painel chega a doze e
    # aparece de perto — por isso campo e botão do ttk ficam dentro de cartão.
    for estilo in ("TFrame", "TLabel", "TCheckbutton", "TRadiobutton",
                   "TLabelframe", "TLabelframe.Label", "TPanedwindow"):
        st.configure(estilo, background=c["cartao"])
    for estilo in ("TLabel", "TCheckbutton", "TRadiobutton"):
        st.configure(estilo, foreground=c["texto"])

    # O cinza do painel, para quem está FORA de um cartão.
    for base in ("TFrame", "TLabel", "TCheckbutton"):
        st.configure("Fundo." + base, background=c["fundo"])
    st.configure("Fundo.TLabel", foreground=c["texto"])
    st.configure("Fundo.TCheckbutton", foreground=c["texto"])

    # A barra superior e o menu lateral pintam os próprios filhos.
    st.configure("Barra.TFrame", background=c["marca_barra"])
    st.configure("Barra.TLabel", background=c["marca_barra"],
                 foreground="#FFFFFF")
    st.configure("BarraTenue.TLabel", background=c["marca_barra"],
                 foreground=c["marca_sub"], font=FONTE_MINI)
    st.configure("Marca.TLabel", background=c["marca_barra"],
                 foreground="#FFFFFF", font=FONTE_MARCA)
    st.configure("Menu.TFrame", background=c["cartao"])
    st.configure("Menu.TLabel", background=c["cartao"], foreground=c["texto"])
    st.configure("MenuSecao.TLabel", background=c["cartao"],
                 foreground=c["tenue"], font=FONTE_MINI_FORTE)
    # Os três estados de um item do menu. Estilos e não cores soltas porque o
    # `ItemMenu` troca de estilo a cada passada do cursor, e reconfigurar
    # cor por cor a cada `<Enter>` custaria dez widgets por movimento.
    st.configure("Item.TLabel", background=c["cartao"], foreground=c["texto"])
    st.configure("ItemSobre.TLabel", background=c["fundo"],
                 foreground=c["texto"])
    st.configure("ItemAtivo.TLabel", background=c["marca_fundo"],
                 foreground=c["marca"], font=FONTE_FORTE)

    # --------------------------------------------------------------- texto
    st.configure("Titulo.TLabel", font=FONTE_TITULO, foreground=c["texto"])
    st.configure("Secao.TLabel", font=FONTE_SECAO, foreground=c["texto"])
    st.configure("Apoio.TLabel", font=FONTE_APOIO, foreground=c["apoio"])
    st.configure("Tenue.TLabel", font=FONTE_APOIO, foreground=c["tenue"])
    st.configure("Ativo.TLabel", font=FONTE_APOIO, foreground=c["ativo"])
    st.configure("Ok.TLabel", foreground=c["ok"])
    st.configure("Atencao.TLabel", foreground=c["atencao"])
    st.configure("Erro.TLabel", foreground=c["erro"])
    st.configure("Forte.TLabel", font=FONTE_FORTE, foreground=c["texto"])
    st.configure("Num.TLabel", font=FONTE_NUM, foreground=c["texto"])
    st.configure("Mini.TLabel", font=FONTE_MINI, foreground=c["tenue"])
    st.configure("Rotulo.TLabel", font=FONTE_MINI, foreground=c["apoio"])
    st.configure("MonoMini.TLabel", font=FONTE_MONO_MINI, foreground=c["apoio"])
    st.configure("MonoMiniErro.TLabel", font=FONTE_MONO_MINI,
                 foreground=c["erro"])
    # O meio-termo que faltava: o dado de pagamento que EXISTE mas não serve
    # para a remessa. Sem ele, a única cor disponível era a do impedimento, e
    # vermelho que não impede nada é lido como defeito do app.
    st.configure("MonoMiniAtencao.TLabel", font=FONTE_MONO_MINI,
                 foreground=c["atencao"])
    st.configure("KPI.TLabel", font=FONTE_KPI, foreground=c["texto"])
    st.configure("KPIMarca.TLabel", font=FONTE_KPI, foreground=c["marca"])

    # As mesmas legendas, para quem está no cinza do painel (cabeçalho de
    # página, trilha, barra de execução): sem isto elas nascem com fundo
    # branco e viram um retângulo claro em volta da frase.
    for nome, fonte, cor in (("Titulo", FONTE_TITULO, c["texto"]),
                             ("Secao", FONTE_SECAO, c["texto"]),
                             ("Apoio", FONTE_APOIO, c["apoio"]),
                             ("Tenue", FONTE_APOIO, c["tenue"]),
                             ("Ativo", FONTE_APOIO, c["ativo"]),
                             ("Mini", FONTE_MINI, c["tenue"]),
                             ("Ok", FONTE_APOIO, c["ok"]),
                             ("Atencao", FONTE_APOIO, c["atencao"]),
                             ("Erro", FONTE_APOIO, c["erro"])):
        st.configure("Fundo" + nome + ".TLabel", font=fonte, foreground=cor,
                     background=c["fundo"])
    st.configure("Trilha.TLabel", font=FONTE_MINI, foreground=c["tenue"],
                 background=c["fundo"])

    # ------------------------------------------------------------- pílulas
    # Estado vira fundo colorido com texto da mesma família, como no ERP. O
    # SÍMBOLO continua junto do texto (✓ ⚠ ✖ ·), porque cor sozinha não
    # distingue nada para quem não a vê — a mesma regra da trilha de passos.
    for nome, frente, tras in (("Ok", c["ok"], c["ok_fundo"]),
                               ("Atencao", c["atencao"], c["atencao_fundo"]),
                               ("Erro", c["erro"], c["erro_fundo"]),
                               ("Info", c["info"], c["info_fundo"])):
        st.configure("Pill" + nome + ".TLabel", background=tras,
                     foreground=frente, font=FONTE_MINI, padding=(7, 2))

    # A trilha de passos fica no tamanho do corpo, e não no da legenda: ela é
    # navegação, não nota de rodapé. Quem separa os três estados é o SÍMBOLO
    # (✓ contra ①), porque cor sozinha não distingue nada para quem não a vê.
    st.configure("PassoFeito.TLabel", foreground=c["ok"], background=c["fundo"])
    st.configure("PassoAtivo.TLabel", foreground=c["ativo"], background=c["fundo"])
    st.configure("PassoFalta.TLabel", foreground=c["tenue"], background=c["fundo"])

    # Cabeçalho de grupo na barra lateral. `Toolbutton` é o estilo chapado do
    # sv-ttk: sem o fundo de cartão que fazia DIÁRIO e MENSAL parecerem itens
    # clicáveis do mesmo nível dos que eles agrupam.
    st.configure("Grupo.Toolbutton", foreground=c["tenue"],
                 font=FONTE_MINI_FORTE, anchor="w", padding=(10, 5),
                 background=c["cartao"])

    # ------------------------------------------------------------- tabelas
    # Cabeçalho cinza-claro em maiúsculas miúdas, zebra sutil, linha alta o
    # bastante para a pílula não encostar na de cima.
    #
    # `rowheight` sai da MÉTRICA da fonte, e não de um número fixo: a 150% de
    # escala uma linha de 26 px corta o texto pela metade.
    try:
        altura = max(int(st.tk.call("font", "metrics", FONTE_APOIO,
                                    "-linespace")) + 12, 26)
    except (tk.TclError, ValueError):
        altura = 26
    st.configure("Tabela.Treeview", background=c["cartao"],
                 fieldbackground=c["cartao"], foreground=c["texto"],
                 rowheight=altura, borderwidth=0, relief="flat")
    st.configure("Tabela.Treeview.Heading", background=c["cabecalho"],
                 foreground=c["apoio"], font=FONTE_MINI, relief="flat",
                 padding=(8, 6), borderwidth=0)
    st.map("Tabela.Treeview.Heading", background=[("active", c["cabecalho"])])
    st.map("Tabela.Treeview", background=[("selected", c["marca_fundo"])],
           foreground=[("selected", c["marca"])])
    # A tabela de duas linhas por célula é a mesma coisa com o dobro da
    # altura — não é estilo novo, é a mesma régua medida de novo.
    st.configure("Dupla.Treeview", background=c["cartao"],
                 fieldbackground=c["cartao"], foreground=c["texto"],
                 rowheight=altura * 2 - 4, borderwidth=0, relief="flat")
    st.configure("Dupla.Treeview.Heading", background=c["cabecalho"],
                 foreground=c["apoio"], font=FONTE_MINI, relief="flat",
                 padding=(8, 6), borderwidth=0)
    st.map("Dupla.Treeview.Heading", background=[("active", c["cabecalho"])])
    st.map("Dupla.Treeview", background=[("selected", c["marca_fundo"])],
           foreground=[("selected", c["marca"])])

    # -------------------------------------------------------- progresso fino
    # A barra do sv-ttk é imagem e não afina; a do painel é a `BarraFina`, que
    # é Canvas. Este estilo fica para quem ainda usa `ttk.Progressbar` direto.
    try:
        st.configure("Fina.Horizontal.TProgressbar", thickness=5,
                     background=c["marca"], troughcolor=c["borda"],
                     borderwidth=0)
    except tk.TclError:
        pass

    _repintar_todos()

def barra_de_titulo(janela, escuro: bool | None = None) -> None:
    """Pinta a barra de título do Windows na cor do tema.

    O sv-ttk pinta o CONTEÚDO da janela; a barra de título é do Windows, e o
    Tk não fala com o DWM. O resultado é uma faixa clara em cima de um app
    inteiro escuro — e ela fica no topo, que é onde o olho bate primeiro.

    `DWMWA_USE_IMMERSIVE_DARK_MODE` é 20 do Windows 10 20H1 em diante e era 19
    nas builds anteriores; tentamos os dois, porque o atributo errado só
    devolve erro e não muda nada. Fora do Windows, e em Windows velho demais,
    a função não faz nada — a janela continua com a barra do sistema, que é
    exatamente o que já acontecia."""
    if escuro is None:
        escuro = _estado["escuro"]
    try:
        from ctypes import byref, c_int, sizeof, windll
    except ImportError:
        return                           # não é Windows
    try:
        # O HWND de verdade é o PAI: o `winfo_id` devolve a janela filha que o
        # Tk desenha por dentro, e pintar aquela não muda moldura nenhuma.
        janela.update_idletasks()
        hwnd = windll.user32.GetParent(janela.winfo_id())
        if not hwnd:
            return
        valor = c_int(1 if escuro else 0)
        for atributo in (20, 19):
            if windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, atributo, byref(valor), sizeof(valor)) == 0:
                return
    except Exception:
        return                           # barra na cor do sistema: sem drama


# ================================================================ componentes
# Os blocos que TODA tela monta. Depois do redesenho eles são a única forma de
# o app ganhar uma cor: nenhuma aba escreve `#` seguido de seis dígitos.


class Botao(tk.Button):
    """O botão do painel: chapado, colorido, com o papel dito pela cor.

    É `tk.Button` e não `ttk.Button`, e isso não é regressão. O sv-ttk desenha
    botão a partir de IMAGENS, com a cor assada dentro de cada canto
    arredondado — `style.configure(background="verde")` não muda uma imagem, e
    copiar o layout do `Accent.TButton` significaria gerar um jogo de imagens
    novo por cor e por tema. O widget clássico do Tk aceita a cor direto; o
    que ele não sabe é seguir o tema sozinho, e é por isso que todo botão se
    inscreve em `_repintaveis` ao nascer.

    O resto da API é a do `ttk.Button` que ele substitui: `state`, `invoke()`,
    `cget("text")`, `configure(text=...)`. O `_drain` de cada aba liga e
    desliga estes botões pelo `state`, e o Enter global (`_enter_aciona`) do
    `comprovantes_app` chama `invoke()` — os dois continuam funcionando sem
    saber que a classe mudou.

    Papéis:
      acao    verde — o "executar" principal da tela. Um por tela.
      passo   azul  — os passos numerados que levam até ele.
      neutro  branco com borda — o que não é nem uma coisa nem outra.
      link    sem moldura, texto azul — "Marcar todas", "Abrir".
      perigo  vermelho — parar, apagar.
    """

    def __init__(self, pai, texto="", papel="neutro", numero=None, **kw):
        # O número entra NO RÓTULO, e não num círculo à parte: dentro de um
        # botão o círculo desenhado teria de ser um Canvas irmão, e aí o
        # clique no número não seria clique no botão.
        if numero is not None:
            texto = f"{numero}.  {texto}"
        kw.setdefault("relief", "flat")
        kw.setdefault("borderwidth", 0)
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("cursor", "hand2")
        kw.setdefault("padx", 14)
        kw.setdefault("pady", 7)
        kw.setdefault("font", FONTE_APOIO if papel == "link" else "TkDefaultFont")
        super().__init__(pai, text=texto, **kw)
        self._papel = papel
        _repintaveis.add(self)
        self.aplicar_cores(_estado["escuro"])

    def configure(self, cnf=None, **kw):                      # noqa: D102
        # `state` muda a COR, e não só o que o Tk desenha por cima. O botão
        # clássico não tem cor por estado: desabilitado ele continua verde,
        # com o rótulo cinza por cima — que é pior que não ter cor, porque
        # parece um botão disponível cujo texto sumiu. Interceptar aqui pega
        # todas as trocas, inclusive as vindas do `_drain` das abas.
        mudou = "state" in kw or (isinstance(cnf, dict) and "state" in cnf)
        r = super().configure(cnf, **kw)
        if mudou:
            self.aplicar_cores()
        return r
    config = configure

    def aplicar_cores(self, escuro: bool | None = None):
        c = cores()
        try:
            desligado = str(super().cget("state")) == "disabled"
        except tk.TclError:
            return
        if desligado:
            # Cinza chapado nos dois temas: o botão desligado não é "verde
            # apagado" nem "azul apagado" — ele é o mesmo lugar vazio,
            # qualquer que fosse a cor dele ligado.
            try:
                self.configure(background=c["fundo"], foreground=c["tenue"],
                               activebackground=c["fundo"],
                               activeforeground=c["tenue"],
                               disabledforeground=c["tenue"],
                               highlightthickness=1,
                               highlightbackground=c["borda"],
                               highlightcolor=c["borda"])
            except tk.TclError:
                pass
            return
        frente, tras, aceso = {
            "acao":   ("#FFFFFF", c["acao"], c["acao_ativo"]),
            # `marca_solida` e não `marca`: aqui o azul é FUNDO e o branco é a
            # letra. No escuro a `marca` deixava o rótulo em 2,69:1.
            "passo":  ("#FFFFFF", c["marca_solida"], c["marca_barra"]),
            # O neutro é CINZA e não branco: no cartão branco, um botão
            # branco com borda de 1 px não se lia como botão — o "Hoje" ao
            # lado do campo de data passava por rótulo.
            "neutro": (c["texto"], c["fundo"], c["marca_fundo"]),
            "link":   (c["marca"], c["cartao"], c["cartao"]),
            "perigo": (c["erro"], c["fundo"], c["erro_fundo"]),
        }.get(self._papel, (c["texto"], c["cartao"], c["fundo"]))
        try:
            self.configure(background=tras, foreground=frente,
                           activebackground=aceso, activeforeground=frente,
                           disabledforeground=c["tenue"])
            # Só o neutro e o perigo têm moldura: o verde e o azul já se
            # separam do fundo pela cor, e uma borda em cima deles vira
            # contorno escuro no meio do preenchimento.
            if self._papel in ("neutro", "perigo"):
                self.configure(highlightthickness=1,
                               highlightbackground=c["borda"],
                               highlightcolor=c["borda"])
            else:
                self.configure(highlightthickness=0)
        except tk.TclError:
            pass

    def papel(self, novo: str):
        """Troca o papel depois de criado (o botão que vira o principal)."""
        self._papel = novo
        self.aplicar_cores()


class Dica:
    """Balãozinho com o texto inteiro, ao parar o cursor em cima.

    Existe para o número da versão: a tela mostra "v2.0", que é o que se diz em
    voz alta, e o número de build (v2.0.108) só aparece quando alguém precisa
    dele — para comparar com uma release, para abrir um chamado. Mostrar os dois
    o tempo todo é ruído; esconder o segundo é perder o único jeito de saber
    qual código está rodando.

    NÃO é widget: é um comportamento que se pendura num widget existente
    (`Dica(lbl, "texto")`). Guarda a si mesmo no widget para o coletor de lixo
    não levá-lo enquanto a janela vive.

    `overrideredirect` como o calendário, e pelo mesmo motivo: uma janela com
    barra de título de dois pixels de altura é uma janela do sistema, aparece na
    barra de tarefas e rouba foco. Aqui ela também não pega foco nenhum — quem
    está lendo a dica está com a mão no mouse, não no teclado.
    """

    #: Tempo até aparecer. Curto o bastante para não parecer travado, longo o
    #: bastante para o cursor poder ATRAVESSAR o widget sem disparar nada.
    ATRASO_MS = 450

    def __init__(self, alvo, texto: str):
        self.alvo = alvo
        self.texto = texto
        self._popup = None
        self._agendado = None
        alvo.bind("<Enter>", self._entrou, add="+")
        alvo.bind("<Leave>", self._saiu, add="+")
        alvo.bind("<Button-1>", self._saiu, add="+")
        alvo._dica = self                    # ver o docstring
        _repintaveis.add(self)

    def _entrou(self, _ev=None):
        self._cancelar()
        try:
            self._agendado = self.alvo.after(self.ATRASO_MS, self._mostrar)
        except tk.TclError:
            self._agendado = None

    def _saiu(self, _ev=None):
        self._cancelar()
        self._fechar()

    def _cancelar(self):
        if self._agendado is not None:
            try:
                self.alvo.after_cancel(self._agendado)
            except tk.TclError:
                pass
            self._agendado = None

    def _mostrar(self):
        self._agendado = None
        if self._popup is not None or not self.texto:
            return
        c = cores()
        try:
            top = tk.Toplevel(self.alvo)
            top.overrideredirect(True)
            top.attributes("-topmost", True)
        except tk.TclError:
            return
        self._popup = top
        moldura = tk.Frame(top, background=c["cartao"], highlightthickness=1,
                           highlightbackground=c["borda"],
                           highlightcolor=c["borda"], padx=8, pady=5)
        moldura.pack()
        ttk.Label(moldura, text=self.texto, style="Mini.TLabel").pack()
        try:
            top.update_idletasks()
            x = self.alvo.winfo_rootx()
            y = self.alvo.winfo_rooty() + self.alvo.winfo_height() + 4
            # Puxada para dentro da tela: a versão mora no canto direito da
            # barra, e o balão nasceria metade fora do monitor.
            x = min(x, top.winfo_screenwidth() - top.winfo_reqwidth() - 8)
            top.geometry(f"+{max(x, 8)}+{y}")
        except tk.TclError:
            self._fechar()

    def _fechar(self):
        if self._popup is not None:
            try:
                self._popup.destroy()
            except tk.TclError:
                pass
            self._popup = None

    def aplicar_cores(self, escuro: bool | None = None):
        """Fechar é repintar: o balão lê a paleta ao nascer, e ele vive o tempo
        de uma passada de cursor."""
        self._fechar()


class Pilula(ttk.Label):
    """Um estado, com fundo da cor do estado. As tags do Treeview fazem o
    mesmo dentro das tabelas; esta serve para o estado solto na tela."""

    def __init__(self, pai, texto: str, estado: str = "info", **kw):
        kw.setdefault("style", "Pill" + estado.capitalize() + ".TLabel")
        super().__init__(pai, text=texto, **kw)

    def definir(self, texto: str, estado: str):
        self.configure(text=texto,
                       style="Pill" + estado.capitalize() + ".TLabel")


class BarraFina(tk.Frame):
    """Barra de progresso de 5 px, com a API do `ttk.Progressbar`.

    Existe porque a barra do sv-ttk é imagem: `thickness` não a afina, e a
    faixa grossa no meio do painel era a única coisa fora de escala na tela.
    Um Canvas resolve, e de quebra aceita a cor da marca.

    `configure(mode=/maximum=/value=)`, `start(ms)` e `stop()` são os mesmos
    da barra do ttk — as seis abas que já as chamavam não mudaram uma linha.
    """

    ALTURA = 5

    def __init__(self, pai, mode="determinate", maximum=100, value=0, **kw):
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("borderwidth", 0)
        super().__init__(pai, height=self.ALTURA, **kw)
        self.pack_propagate(False)
        self.grid_propagate(False)
        self._canvas = tk.Canvas(self, height=self.ALTURA, highlightthickness=0,
                                 borderwidth=0)
        self._canvas.pack(fill="both", expand=True)
        self._modo = mode
        self._max = max(float(maximum), 1.0)
        self._valor = float(value)
        self._passo = 0.0
        self._animando = None
        self._canvas.bind("<Configure>", lambda _e: self._desenhar())
        _repintaveis.add(self)
        self.aplicar_cores(_estado["escuro"])

    # ------------------------------------------------------- API do ttk
    def configure(self, cnf=None, **kw):                     # noqa: D102
        for nome in ("mode", "maximum", "value"):
            if nome in kw:
                valor = kw.pop(nome)
                if nome == "mode":
                    self._modo = str(valor)
                elif nome == "maximum":
                    self._max = max(float(valor), 1.0)
                else:
                    self._valor = float(valor)
        if kw or cnf:
            super().configure(cnf, **kw)
        self._desenhar()
    config = configure

    def cget(self, chave):                                   # noqa: D102
        if chave == "mode":
            return self._modo
        if chave == "maximum":
            return self._max
        if chave == "value":
            return self._valor
        return super().cget(chave)

    def start(self, intervalo: int = 12):
        """Vai e volta, para quando não dá para saber quantos faltam."""
        self._modo = "indeterminate"
        if self._animando is None:
            self._animar(max(int(intervalo), 8))

    def stop(self):
        if self._animando is not None:
            try:
                self.after_cancel(self._animando)
            except tk.TclError:
                pass
            self._animando = None
        self._passo = 0.0
        self._desenhar()

    def _animar(self, intervalo):
        self._passo = (self._passo + 0.022) % 1.0
        self._desenhar()
        try:
            self._animando = self.after(intervalo, self._animar, intervalo)
        except tk.TclError:
            self._animando = None

    # ---------------------------------------------------------- desenho
    def aplicar_cores(self, escuro: bool | None = None):
        c = cores()
        try:
            self.configure(background=c["borda"])
            self._canvas.configure(background=c["borda"])
        except tk.TclError:
            return
        self._desenhar()

    def _desenhar(self):
        try:
            largura = self._canvas.winfo_width()
            self._canvas.delete("all")
        except tk.TclError:
            return
        if largura <= 1:
            return
        c = cores()
        if self._modo == "indeterminate" and self._animando is not None:
            corrida = int(largura * 0.28)
            x = int((largura + corrida) * self._passo) - corrida
            self._canvas.create_rectangle(x, 0, x + corrida, self.ALTURA,
                                          fill=c["marca"], outline="")
        else:
            fim = int(largura * min(self._valor / self._max, 1.0))
            if fim > 0:
                self._canvas.create_rectangle(0, 0, fim, self.ALTURA,
                                              fill=c["marca"], outline="")


class BarraExecucao(ttk.Frame):
    """O que está acontecendo agora: frase, barra fina e quanto falta.

    Antes eram um `ttk.Label("Pronto.")` e uma barra grossa lado a lado, e
    nenhum dos dois dizia o TAMANHO do trabalho: "processando" com a barra em
    30% não responde se faltam dez segundos ou vinte minutos. Aqui a mesma
    contagem que move a barra vira "12 de 87 · 14% · faltam ~3 min" — o número
    já existia, só não estava escrito em lugar nenhum.

    Expõe `.lbl` e `.pb` com os mesmos nomes de antes, então as abas que só
    chamam `self.lbl.configure(text=...)` e `self.pb.configure(value=...)`
    continuam valendo.
    """

    def __init__(self, pai, **kw):
        kw.setdefault("style", "Fundo.TFrame")
        super().__init__(pai, **kw)
        self._estilo_fundo = str(kw.get("style", "")).startswith("Fundo")
        sufixo = "Fundo" if self._estilo_fundo else ""
        linha = ttk.Frame(self, style=kw.get("style", "TFrame"))
        linha.pack(fill="x")
        self.lbl = ttk.Label(linha, text="Pronto.",
                             style=(sufixo + "Apoio.TLabel") if sufixo
                             else "Apoio.TLabel")
        self.lbl.pack(side="left")
        self.contagem = ttk.Label(linha, text="",
                                  style=(sufixo + "Mini.TLabel") if sufixo
                                  else "Mini.TLabel")
        self.contagem.pack(side="right")
        self.pb = BarraFina(self)
        self.pb.pack(fill="x", pady=(5, 0))
        #: Quando o trabalho atual começou — a base do "faltam ~".
        self._inicio = None
        self._ultimo_total = 0

    def comecou(self, tarefa: str = ""):
        self._inicio = time.monotonic()
        self._ultimo_total = 0
        if tarefa:
            self.lbl.configure(text=tarefa)
        self.contagem.configure(text="")

    def terminou(self, recado: str = "Pronto."):
        self._inicio = None
        self.pb.stop()
        self.pb.configure(mode="determinate", value=0)
        self.lbl.configure(text=recado)
        self.contagem.configure(text="")

    def progresso(self, feitos: int, total: int):
        """Move a barra E escreve o que ela significa."""
        total = max(int(total), 1)
        feitos = max(min(int(feitos), total), 0)
        if total != self._ultimo_total:      # trabalho novo: recomeça o relógio
            self._ultimo_total = total
            self._inicio = time.monotonic()
        self.pb.configure(mode="determinate", maximum=total, value=feitos)
        partes = [f"{feitos} de {total}", f"{feitos * 100 // total}%"]
        # A estimativa só aparece depois de dois itens: com um só, o tempo do
        # primeiro (que carrega a abertura do navegador) vira a previsão do
        # lote inteiro e diz "faltam 40 minutos" para um trabalho de três.
        if self._inicio and feitos >= 2 and feitos < total:
            gasto = time.monotonic() - self._inicio
            falta = gasto / feitos * (total - feitos)
            partes.append("faltam ~" + util.fmt_dur(falta))
        self.contagem.configure(text="  ·  ".join(partes))


class Cartao(tk.Frame):
    """Um bloco da tela: cartão branco, borda de 1 px, título em cima.

    Era `ttk.LabelFrame` — a moldura com o título encaixado na borda. Virou
    cartão porque o painel inteiro passou a ser feito deles, e a moldura do
    ttk não aceita fundo próprio (o sv-ttk a desenha por imagem).

    CANTO RETO, e não arredondado: o Tk não tem canto arredondado em widget
    de verdade. Dá para desenhar um num Canvas, mas aí o cartão deixa de ser
    um contêiner onde se empacotam `ttk.Label` e `ttk.Entry` — que é
    exatamente o que as dez abas fazem com ele. A borda de 1 px em `#DBE1EC`
    é a aproximação, e é a diferença mais visível para o mockup.

    DOIS FRAMES, e não um
    ---------------------
    `self` é o CONTEÚDO; `self.moldura` é a borda com o título, e é ela que
    entra no `pack` do pai. As chamadas de geometria (`pack`, `grid`, `place`
    e as irmãs) são redirecionadas para a moldura, então quem usa o cartão
    continua escrevendo `f1.pack(fill="x")` sem saber que existem dois.

    O motivo é uma regra do Tk, não gosto: um mesmo pai não pode ter filhos
    no `pack` e filhos no `grid`. Com o título empacotado dentro do próprio
    cartão, toda aba que montava o formulário em `grid` passava a estourar
    com "cannot use geometry manager grid inside ... which already has slaves
    managed by pack" — e são quatro abas assim. Separando os dois, o cartão
    volta a nascer VAZIO para quem o usa, e cada aba escolhe o seu gerenciador
    como sempre escolheu.

    O NÚMERO é opcional porque numerar só informa quando existe ordem de
    verdade: em Remessa/Retorno buscar vem antes de gerar, e o "1" conta isso;
    no cartão de Registro não há passo nenhum, e numerá-lo seria inventar uma
    sequência que ninguém precisa seguir.
    """

    def __init__(self, pai, titulo: str = "", numero: int | None = None,
                 padding=None, **kw):
        c = cores()
        larg, alt = self._folga(padding)
        moldura = tk.Frame(pai, background=c["cartao"], highlightthickness=1,
                           highlightbackground=c["borda"],
                           highlightcolor=c["borda"], borderwidth=0,
                           padx=larg, pady=alt)
        self.moldura = moldura
        self._morrendo = False
        self._titulo = titulo
        self.cabecalho = None
        self._bolha = None
        if titulo:
            self._montar_cabecalho(titulo, numero)
        kw.setdefault("background", c["cartao"])
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("borderwidth", 0)
        super().__init__(moldura, **kw)
        tk.Frame.pack(self, fill="both", expand=True)
        _repintaveis.add(self)

    # ---------------------------------------------- geometria vai à moldura
    # Sem estes, `f1.pack(...)` empacotaria o conteúdo DENTRO da moldura de
    # novo, e o cartão nunca apareceria na tela.
    @staticmethod
    def _vizinhos(kw: dict) -> dict:
        """`after=outro_cartao` tem de virar `after=a moldura dele`.

        O `pack` do Tk só entende widgets que ELE gerencia, e quem está
        empacotado no pai é a moldura — passar o conteúdo faz o Tk reclamar
        que o widget não é filho do mesmo mestre. Traduzir aqui é o que
        mantém `f_lista.pack(after=self.topo)` funcionando sem que a aba
        precise saber que o cartão tem dois frames."""
        for chave in ("after", "before", "in_"):
            alvo = kw.get(chave)
            if isinstance(alvo, Cartao):
                kw[chave] = alvo.moldura
        return kw

    def pack(self, **kw):
        self.moldura.pack(**self._vizinhos(kw))
        return self

    def pack_configure(self, **kw):
        self.moldura.pack_configure(**self._vizinhos(kw))

    def pack_forget(self):
        self.moldura.pack_forget()

    def pack_info(self):
        return self.moldura.pack_info()

    def grid(self, **kw):
        self.moldura.grid(**kw)
        return self

    def grid_configure(self, **kw):
        self.moldura.grid_configure(**kw)

    def grid_forget(self):
        self.moldura.grid_forget()

    def grid_info(self):
        return self.moldura.grid_info()

    def place(self, **kw):
        self.moldura.place(**kw)
        return self

    def place_forget(self):
        self.moldura.place_forget()

    def destroy(self):
        # A moldura leva o conteúdo junto: destruir só o conteúdo deixaria um
        # retângulo branco com borda e título na tela, sem nada dentro.
        #
        # A trava não é zelo: `moldura.destroy()` percorre os filhos DELA, e
        # um deles é este mesmo cartão — sem ela, os dois se chamam até o
        # `RecursionError`. Na segunda entrada o cartão morre como o
        # `tk.Frame` que ele é, e a moldura segue destruindo o resto.
        if self._morrendo:
            tk.Frame.destroy(self)
            return
        self._morrendo = True
        self.moldura.destroy()

    @staticmethod
    def _folga(padding) -> tuple[int, int]:
        """A folga interna. `padding` continua aceito porque trinta e três
        chamadas o passam, mas o `frame` clássico só tem UM padx e UM pady:
        a tupla de quatro lados vira a folga horizontal e a vertical — a
        diferença entre 10 e 12 px de topo não era o que aquelas chamadas
        estavam querendo dizer."""
        if padding is None:
            return 16, 14
        if isinstance(padding, (int, float)):
            return int(padding), int(padding)
        vals = [int(v) for v in padding]
        if len(vals) == 1:
            return vals[0], vals[0]
        if len(vals) == 2:
            return vals[0], vals[1]
        return max(vals[0], vals[2]), max(vals[1], vals[3])

    def _montar_cabecalho(self, titulo: str, numero):
        c = cores()
        linha = tk.Frame(self.moldura, background=c["cartao"],
                         highlightthickness=0)
        linha.pack(fill="x", pady=(0, 9))
        self.cabecalho = linha
        if numero is not None:
            # O círculo azul do passo. Canvas porque um Label redondo não
            # existe no Tk: `Label` é sempre retângulo, com ou sem borda.
            lado = 22
            bolha = tk.Canvas(linha, width=lado, height=lado,
                              highlightthickness=0, borderwidth=0,
                              background=c["cartao"])
            bolha.create_oval(0, 0, lado - 1, lado - 1,
                              fill=c["marca_solida"], outline="",
                              tags="bolha")
            bolha.create_text(lado / 2, lado / 2 + 1, text=str(numero),
                              fill="#FFFFFF", font=FONTE_MINI_FORTE,
                              tags="numero")
            bolha.pack(side="left", padx=(0, 9))
            self._bolha = bolha
        self.lbl_titulo = ttk.Label(linha, text=titulo, style="Secao.TLabel")
        self.lbl_titulo.pack(side="left")
        #: Onde a tela pendura o que fica à DIREITA do título do cartão
        #: (uma contagem, um "Marcar todas", um botão-link).
        self.acoes = ttk.Frame(linha)
        self.acoes.pack(side="right")
        # O filete abaixo do título separa o cabeçalho do conteúdo sem gastar
        # uma linha em branco — que era o que a moldura do LabelFrame fazia.
        self.filete = tk.Frame(self.moldura, height=1, background=c["borda"],
                               highlightthickness=0)
        self.filete.pack(fill="x", pady=(0, 11))

    def titulo(self, texto: str):
        if self.cabecalho is not None:
            self.lbl_titulo.configure(text=texto)

    def aplicar_cores(self, escuro: bool | None = None):
        c = cores()
        try:
            self.configure(background=c["cartao"])
            self.moldura.configure(background=c["cartao"],
                                   highlightbackground=c["borda"],
                                   highlightcolor=c["borda"])
            if self.cabecalho is not None:
                self.cabecalho.configure(background=c["cartao"])
                self.filete.configure(background=c["borda"])
                if self._bolha is not None:
                    self._bolha.configure(background=c["cartao"])
                    self._bolha.itemconfigure("bolha",
                                              fill=c["marca_solida"])
        except tk.TclError:
            pass


class Cabecalho(ttk.Frame):
    """O cabeçalho da PÁGINA: onde estou, o que é isto, e o que dá para fazer.

    Três informações e não mais o título sozinho:

      trilha   "Diário / Remessa e Retorno" — dez abas em quatro seções, e o
               título sozinho não dizia de qual seção a tela era;
      título   o nome da tela;
      apoio    a linha que explica para que ela serve. Não é enfeite: é o
               único lugar onde a aba se explica para quem abriu o app pela
               primeira vez.

    À direita fica `self.acoes`, onde a tela pendura os botões dela — o
    principal em verde. Antes eles moravam todos no rodapé, e o "executar" de
    cada tela ficava no canto de baixo, longe do que se acabou de preencher.
    """

    def __init__(self, pai, titulo: str, apoio: str = "", trilha: str = "",
                 **kw):
        kw.setdefault("style", "Fundo.TFrame")
        super().__init__(pai, **kw)
        esquerda = ttk.Frame(self, style="Fundo.TFrame")
        esquerda.pack(side="left", fill="x", expand=True)
        if trilha:
            ttk.Label(esquerda, text=trilha, style="Trilha.TLabel"
                      ).pack(anchor="w", pady=(0, 2))
        ttk.Label(esquerda, text=titulo, style="FundoTitulo.TLabel"
                  ).pack(anchor="w")
        self.lbl_apoio = None
        if apoio:
            self.lbl_apoio = ttk.Label(esquerda, text=apoio,
                                       style="FundoApoio.TLabel",
                                       wraplength=820, justify="left")
            self.lbl_apoio.pack(anchor="w", pady=(3, 0))
        #: Os botões da tela. `anchor="e"` para eles ficarem alinhados pelo
        #: alto do título, e não centralizados contra a linha de apoio.
        self.acoes = ttk.Frame(self, style="Fundo.TFrame")
        self.acoes.pack(side="right", anchor="ne", padx=(14, 0))
        #: Espaço abaixo da linha de apoio, para quem quiser pendurar algo no
        #: cabeçalho. Nasce vazio e não ocupa lugar até alguém empacotá-lo.
        self.rodape = ttk.Frame(esquerda, style="Fundo.TFrame")


class RodapeTabela(ttk.Frame):
    """O rodapé de uma tabela: o que ela soma à esquerda, o que dá para fazer
    com ela à direita.

    "21 marcados · R$ 41.380,20 · 2 ficam de fora" é a frase que se confere
    antes de apertar o botão verde. Ela existia solta em três telas, cada uma
    com uma redação; aqui é um lugar só, e o "ficam de fora" (que só a Remessa
    tinha) passou a caber em qualquer uma.
    """

    def __init__(self, pai, **kw):
        super().__init__(pai, **kw)
        self.resumo = ttk.Label(self, text="", style="Apoio.TLabel")
        self.resumo.pack(side="left")
        self._links = ttk.Frame(self)
        self._links.pack(side="right")

    def definir(self, marcados=None, total_reais=None, de_fora=0,
                texto: str | None = None):
        if texto is None:
            partes = []
            if marcados is not None:
                partes.append(f"{marcados} marcado" + ("s" if marcados != 1 else ""))
            if total_reais is not None:
                partes.append(brl(total_reais))
            if de_fora:
                partes.append(f"{de_fora} fica" + ("m" if de_fora != 1 else "")
                              + " de fora")
            texto = "  ·  ".join(partes)
        self.resumo.configure(text=texto)

    def limpar_links(self):
        """Tira os botões-link. As listas de contas remontam o rodapé a cada
        busca, e sem isto "Marcar todas" aparecia duplicado na segunda vez."""
        for w in self._links.winfo_children():
            w.destroy()

    def link(self, texto: str, comando):
        b = Botao(self._links, texto, papel="link", command=comando,
                  padx=8, pady=2)
        b.pack(side="left", padx=(10, 0))
        return b


class Campo(ttk.Frame):
    """Rótulo miúdo EM CIMA do campo, e não ao lado.

    Ao lado, o rótulo empurra o campo para a direita e cada linha do
    formulário começa numa coluna diferente — que era o que fazia "De:",
    "até:" e "Onde salvar" nunca se alinharem. Em cima, todos os campos da
    linha nascem na mesma margem.

    `Campo` não cria o widget: recebe o que vai embaixo do rótulo por uma
    fábrica, porque o que entra ali vai de `ttk.Entry` a `CampoData` e a
    `ComboBusca`, e cada um tem a sua própria assinatura.
    """

    def __init__(self, pai, rotulo: str, fabrica, **kw):
        super().__init__(pai, **kw)
        ttk.Label(self, text=rotulo.upper(), style="Rotulo.TLabel"
                  ).pack(anchor="w", pady=(0, 3))
        self.widget = fabrica(self)
        self.widget.pack(anchor="w", fill="x")


# ------------------------------------------------------- moldura da janela
# A barra azul do topo e o menu branco da esquerda. Moram aqui pelo mesmo
# motivo do resto: são `tk.Frame` clássicos (o ttk não deixa pintar), e o
# `comprovantes_app.py` não pode passar a ser o segundo lugar do app onde
# existe um `#` seguido de seis dígitos.


class BarraTopo(tk.Frame):
    """A faixa da cor da marca, acima de tudo.

    Ela responde três perguntas que antes moravam em cantos diferentes da
    janela, ou em canto nenhum:

      onde estou      o logotipo, à esquerda;
      o que procuro   a busca, no meio;
      o app está      o estado do navegador, à direita — que era uma linha
      livre?          cinza no PÉ da barra lateral, o ponto mais distante do
                      olho de quem clica numa aba lá em cima.

    A busca por ora só leva o foco para a aba atual. Está aqui porque o lugar
    dela na tela é uma decisão de layout, e enfiá-la depois obrigaria a mexer
    de novo em tudo o que estiver à direita e à esquerda dela.
    """

    ALTURA = 52

    def __init__(self, pai, marca: str = "mais controle · comprovantes",
                 ao_buscar=None, dica: str = "", **kw):
        c = cores()
        kw.setdefault("background", c["marca_barra"])
        kw.setdefault("highlightthickness", 0)
        super().__init__(pai, height=self.ALTURA, **kw)
        self.pack_propagate(False)
        self._dica = dica or ("Buscar lançamento, empresa ou conta…  "
                              "(Ctrl+K)")
        #: Pública porque quem sabe o que fazer com o termo é a janela, e ela
        #: só descobre isso depois de montar as abas — bem depois desta linha.
        self.ao_buscar = ao_buscar

        self.esquerda = tk.Frame(self, background=c["marca_barra"])
        self.esquerda.pack(side="left", fill="y", padx=(18, 0))
        self.lbl_marca = ttk.Label(self.esquerda, text=marca,
                                   style="Marca.TLabel")
        self.lbl_marca.pack(side="left", pady=14)

        self.direita = tk.Frame(self, background=c["marca_barra"])
        self.direita.pack(side="right", fill="y", padx=(0, 18))

        # O centro entra POR ÚLTIMO, e é o único com `expand`: assim ele fica
        # com a sobra da largura, e o logotipo e o canto direito ficam com o
        # que precisam. Empacotado antes, ele empurrava o canto direito para
        # fora da janela em telas estreitas.
        self.centro = tk.Frame(self, background=c["marca_barra"])
        self.centro.pack(side="left", fill="both", expand=True, padx=24)
        self.busca = tk.Entry(self.centro, relief="flat", borderwidth=0,
                              highlightthickness=1, font="TkDefaultFont")
        self.busca.pack(fill="x", pady=13, ipady=4, ipadx=8)
        self._vazia = True
        self.busca.bind("<FocusIn>", self._entrou)
        self.busca.bind("<FocusOut>", self._saiu)
        self.busca.bind("<Return>", self._buscar)
        self.busca.bind("<Escape>", lambda _e: self.limpar())

        _repintaveis.add(self)
        self.aplicar_cores(_estado["escuro"])
        self._mostrar_dica()

    # ------------------------------------------------------------ busca
    def _mostrar_dica(self):
        self._vazia = True
        self.busca.delete(0, "end")
        self.busca.insert(0, self._dica)
        self.busca.configure(foreground=cores()["marca_sub"])

    def _entrou(self, _ev=None):
        if self._vazia:
            self.busca.delete(0, "end")
            self.busca.configure(foreground="#FFFFFF")
            self._vazia = False

    def _saiu(self, _ev=None):
        if not self.busca.get().strip():
            self._mostrar_dica()

    def limpar(self):
        self._mostrar_dica()
        self.focus_set()

    def _buscar(self, _ev=None):
        if self.ao_buscar and not self._vazia:
            self.ao_buscar(self.busca.get().strip())

    def focar_busca(self, _ev=None):
        self.busca.focus_set()
        self._entrou()
        return "break"

    # ------------------------------------------------------------- tema
    def aplicar_cores(self, escuro: bool | None = None):
        c = cores()
        try:
            self.configure(background=c["marca_barra"])
            for filho in (self.esquerda, self.centro, self.direita):
                filho.configure(background=c["marca_barra"])
            # O campo de busca é mais claro que a barra por dentro, e não
            # branco: branco no meio do azul vira o elemento mais forte da
            # tela, e a busca não é a coisa mais importante desta janela.
            fundo = _mistura(c["marca_barra"], "#FFFFFF", 0.16)
            self.busca.configure(background=fundo, insertbackground="#FFFFFF",
                                 highlightbackground=_mistura(
                                     c["marca_barra"], "#FFFFFF", 0.30),
                                 highlightcolor="#FFFFFF",
                                 foreground=c["marca_sub"] if self._vazia
                                 else "#FFFFFF",
                                 disabledbackground=fundo)
        except tk.TclError:
            pass


def _mistura(a: str, b: str, quanto: float) -> str:
    """`quanto` do caminho de `a` até `b`, canal a canal.

    Serve para tirar do azul da marca um azul um pouco mais claro (o campo de
    busca) sem inventar um sexto tom na paleta — e sem que o tema escuro
    precise de um valor próprio para ele."""
    ca = [int(a.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    cb = [int(b.lstrip("#")[i:i + 2], 16) for i in (0, 2, 4)]
    return "#" + "".join(f"{int(x + (y - x) * quanto):02X}"
                         for x, y in zip(ca, cb))


class Avatar(tk.Canvas):
    """A inicial de quem está logado, num círculo. Canvas porque `Label` é
    sempre retângulo — não há como arredondar um no Tk."""

    def __init__(self, pai, nome: str = "", lado: int = 30,
                 na_barra: bool = True, **kw):
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("borderwidth", 0)
        super().__init__(pai, width=lado, height=lado, **kw)
        self._lado = lado
        self._na_barra = na_barra
        self._inicial = (nome.strip()[:1] or "?").upper()
        _repintaveis.add(self)
        self.aplicar_cores(_estado["escuro"])

    def nome(self, novo: str):
        self._inicial = (novo.strip()[:1] or "?").upper()
        self.aplicar_cores()

    def aplicar_cores(self, escuro: bool | None = None):
        c = cores()
        fundo = c["marca_barra"] if self._na_barra else c["cartao"]
        bolha = (_mistura(c["marca_barra"], "#FFFFFF", 0.26) if self._na_barra
                 else c["marca_fundo"])
        frente = "#FFFFFF" if self._na_barra else c["marca"]
        try:
            self.configure(background=fundo)
            self.delete("all")
            self.create_oval(0, 0, self._lado - 1, self._lado - 1, fill=bolha,
                             outline="")
            self.create_text(self._lado / 2, self._lado / 2 + 1,
                             text=self._inicial, fill=frente,
                             font=FONTE_MINI_FORTE)
        except tk.TclError:
            pass


class ChipStatus(tk.Frame):
    """Bolinha + frase: o estado do navegador, na barra de cima.

    Era "Navegador livre" no pé da barra lateral. Subiu porque a pergunta que
    ele responde ("dá para clicar noutra aba agora?") se faz ANTES do clique,
    e o rodapé da lateral é o canto mais longe do olho de quem vai clicar.

    A BOLINHA é o que muda de cor; o texto fica sempre legível sobre o azul.
    Verde parado é livre, âmbar piscando é ocupado — e aí a frase diz o que a
    aba está fazendo, que é a informação cara.
    """

    def __init__(self, pai, na_barra: bool = True, largura: int = 30, **kw):
        c = cores()
        kw.setdefault("background", c["marca_barra"] if na_barra
                      else c["cartao"])
        kw.setdefault("highlightthickness", 0)
        super().__init__(pai, **kw)
        self._na_barra = na_barra
        self._estado = "livre"
        self.bolha = tk.Canvas(self, width=10, height=10,
                               highlightthickness=0, borderwidth=0)
        self.bolha.pack(side="left", pady=2)
        self.lbl = ttk.Label(self, text="Navegador livre",
                             style="Barra.TLabel" if na_barra else "Apoio.TLabel",
                             wraplength=0, anchor="w", width=largura)
        self.lbl.pack(side="left", padx=(7, 0))
        _repintaveis.add(self)
        self.aplicar_cores(_estado["escuro"])

    def definir(self, texto: str, ocupado: bool):
        self._estado = "ocupado" if ocupado else "livre"
        try:
            self.lbl.configure(text=texto)
        except tk.TclError:
            return
        self._pintar_bolha()

    def _pintar_bolha(self):
        c = cores()
        cor = c["atencao"] if self._estado == "ocupado" else c["acao_viva"]
        if self._na_barra:
            # Sobre o azul da marca, o verde e o âmbar da paleta clara somem.
            # Estes dois são os mesmos tons puxados para o claro — a barra é
            # escura nos dois temas, então servem para os dois.
            cor = "#FFC24D" if self._estado == "ocupado" else "#5FD08E"
        try:
            self.bolha.delete("all")
            self.bolha.create_oval(1, 1, 9, 9, fill=cor, outline="")
        except tk.TclError:
            pass

    def aplicar_cores(self, escuro: bool | None = None):
        c = cores()
        fundo = c["marca_barra"] if self._na_barra else c["cartao"]
        try:
            self.configure(background=fundo)
            self.bolha.configure(background=fundo)
        except tk.TclError:
            return
        self._pintar_bolha()


class ItemMenu(tk.Frame):
    """Um item do menu lateral: filete, ícone e nome.

    Substitui o `ttk.Button` com `style="Accent.TButton"` que marcava a aba
    aberta. O botão de destaque do sv-ttk é azul CHEIO — dez itens numa
    coluna, e o aberto virava o objeto mais pesado da janela inteira, mais
    forte que o botão de executar da tela que ele abriu.

    Aqui o aberto é fundo azul-claro, texto azul e um filete de 3 px na
    borda esquerda. Os três juntos porque o filete sozinho some em tela
    pequena, e o fundo sozinho não distingue "aberto" de "o cursor está em
    cima".

    O ícone é trocado por ● quando a aba está trabalhando (ver `_pulso` no
    `comprovantes_app.py`). Guardado à parte para o ● poder voltar a ser o
    ícone de sempre quando o trabalho acaba.
    """

    FILETE = 3

    def __init__(self, pai, texto: str, icone: str = "", comando=None,
                 recuo: int = 0, **kw):
        c = cores()
        kw.setdefault("background", c["cartao"])
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("cursor", "hand2")
        super().__init__(pai, **kw)
        self._icone = icone
        self._texto = texto
        self._ativo = False
        self._trabalhando = False
        self._comando = comando

        self.filete = tk.Frame(self, width=self.FILETE, highlightthickness=0)
        self.filete.pack(side="left", fill="y")
        self.corpo = tk.Frame(self, highlightthickness=0)
        self.corpo.pack(side="left", fill="both", expand=True)
        self.lbl_icone = ttk.Label(self.corpo, text=icone, style="Menu.TLabel",
                                   width=2, anchor="center")
        self.lbl_icone.pack(side="left", padx=(9 + recuo, 0), pady=6)
        self.lbl = ttk.Label(self.corpo, text=texto, style="Menu.TLabel",
                             anchor="w")
        self.lbl.pack(side="left", padx=(7, 8), pady=6, fill="x", expand=True)

        for w in (self, self.corpo, self.lbl, self.lbl_icone):
            w.bind("<Button-1>", self._clique)
            w.bind("<Enter>", self._entrou)
            w.bind("<Leave>", self._saiu)
        _repintaveis.add(self)
        self.aplicar_cores(_estado["escuro"])

    # ------------------------------------------------------------ eventos
    def _clique(self, _ev=None):
        if self._comando:
            self._comando()

    def _entrou(self, _ev=None):
        if not self._ativo:
            self._pintar(hover=True)

    def _saiu(self, _ev=None):
        if not self._ativo:
            self._pintar()

    # ------------------------------------------------------------- estado
    def ativar(self, sim: bool):
        if sim == self._ativo:
            return
        self._ativo = bool(sim)
        self._pintar()

    def trabalhando(self, sim: bool):
        """● no lugar do ícone enquanto esta aba segura um navegador."""
        sim = bool(sim)
        if sim == self._trabalhando:
            return
        self._trabalhando = sim
        try:
            self.lbl_icone.configure(text="●" if sim else self._icone)
        except tk.TclError:
            pass
        self._pintar(hover=False)

    def texto(self) -> str:
        return self._texto

    # --------------------------------------------------------------- tema
    def aplicar_cores(self, escuro: bool | None = None):
        self._pintar()

    def _pintar(self, hover: bool = False):
        c = cores()
        if self._ativo:
            fundo, frente, filete = c["marca_fundo"], c["marca"], c["marca"]
        elif hover:
            fundo, frente, filete = c["fundo"], c["texto"], c["fundo"]
        else:
            fundo, frente, filete = c["cartao"], c["texto"], c["cartao"]
        estilo = "ItemAtivo.TLabel" if self._ativo else "Item.TLabel"
        try:
            if hover and not self._ativo:
                estilo = "ItemSobre.TLabel"
            self.configure(background=fundo)
            self.corpo.configure(background=fundo)
            self.filete.configure(background=filete)
            self.lbl.configure(style=estilo)
            # O ● da aba que trabalha é azul mesmo quando o item não é o
            # aberto: é a única marca na tela que diz ONDE o trabalho está,
            # e na cor do item parado ela passava despercebida. Vai como
            # opção DO WIDGET, e não como estilo: o fundo tem de continuar
            # sendo o do item (branco, cinza de passagem ou azul-claro), e um
            # estilo só para o ● precisaria de uma versão para cada um dos
            # três.
            self.lbl_icone.configure(
                style=estilo,
                foreground=c["ativo"] if self._trabalhando else frente)
        except tk.TclError:
            pass


class PainelMenu(tk.Frame):
    """A coluna branca da esquerda: onde ficam as dez telas.

    Branca e com borda só do lado direito — que é o que separa a navegação do
    painel de trabalho sem gastar uma linha divisória de verdade. `tk.Frame`
    porque nenhuma das duas coisas o `ttk.Frame` faz: ele não tem fundo
    próprio (o sv-ttk o desenha) nem borda de um lado só.

    `pack_propagate(False)` prende a largura: sem isso a coluna encolhe até o
    tamanho do item mais curto assim que um grupo fecha, e o menu inteiro
    muda de largura a cada clique.
    """

    def __init__(self, pai, largura: int = 232, **kw):
        c = cores()
        kw.setdefault("background", c["cartao"])
        kw.setdefault("highlightthickness", 0)
        super().__init__(pai, width=largura, **kw)
        self.pack_propagate(False)
        self.borda = tk.Frame(self, width=1, highlightthickness=0)
        self.borda.pack(side="right", fill="y")
        self.rodape = tk.Frame(self, highlightthickness=0)
        self.rodape.pack(side="bottom", fill="x", padx=14, pady=(8, 12))
        self.corpo = tk.Frame(self, highlightthickness=0)
        self.corpo.pack(side="top", fill="both", expand=True, pady=(10, 0))
        _repintaveis.add(self)
        self.aplicar_cores(_estado["escuro"])

    def secao(self, texto: str, pai=None):
        """O rótulo de seção, em maiúsculas miúdas. Ele não é clicável — é o
        que diz que os quatro itens abaixo dele são a mesma família."""
        lbl = ttk.Label(pai if pai is not None else self.corpo,
                        text=texto.upper(), style="MenuSecao.TLabel")
        lbl.pack(anchor="w", padx=(14, 0), pady=(12, 4))
        return lbl

    def aplicar_cores(self, escuro: bool | None = None):
        c = cores()
        try:
            self.configure(background=c["cartao"])
            self.corpo.configure(background=c["cartao"])
            self.rodape.configure(background=c["cartao"])
            self.borda.configure(background=c["borda"])
        except tk.TclError:
            pass


def painel_menu(pai, largura: int = 232) -> "PainelMenu":
    """Atalho de leitura, para o `comprovantes_app` não precisar do nome da
    classe onde só quer a coluna."""
    return PainelMenu(pai, largura=largura)


# ---------------------------------------------------------------- tabelas
#: Estado -> nome da tag do Treeview. A tela diz o estado em português, e o
#: de-para mora aqui para "apto", "completa" e "baixado" não pintarem de três
#: verdes diferentes em três abas.
ESTADOS = {
    # verde: acabou bem
    "apto": "ok", "completa": "ok", "baixado": "ok", "pago": "ok",
    "anexado": "ok", "ok": "ok", "conferido": "ok",
    # âmbar: entrou, mas precisa de olho
    "duvida": "atencao", "em duvida": "atencao", "sem pdf": "atencao",
    "baixando": "atencao", "parcial": "atencao", "atencao": "atencao",
    "aguardando": "atencao",
    # vermelho: não entrou
    "falta": "erro", "rejeitado": "erro", "sem anexo": "erro", "erro": "erro",
    "falhou": "erro",
    # azul: é informação, não problema
    "fora": "info", "fica de fora": "info", "na fila": "info", "info": "info",
    "pulado": "info",
}

#: O símbolo que acompanha cada estado. Vai junto do texto porque cor sozinha
#: não distingue nada para quem não a vê — a mesma regra da trilha de passos.
MARCAS_ESTADO = {"ok": "✓", "atencao": "⚠", "erro": "✖", "info": "·"}


def estado_de(texto: str) -> str:
    """A tag ('ok'/'atencao'/'erro'/'info') do estado escrito em português.

    Casa pelo PEDAÇO, e sem acento: as abas escrevem "ATENÇÃO — sem anexo",
    "APTO (autorizado)" e "JÁ PAGO em 12/08/2026", e nenhuma delas vai passar
    a escrever uma chave de dicionário só para a tabela ficar colorida.
    """
    alvo = util.norm(texto or "")
    if not alvo:
        return "info"
    for chave in sorted(ESTADOS, key=len, reverse=True):
        if chave in alvo:
            return ESTADOS[chave]
    # As palavras que aparecem no meio da frase, e não como estado inteiro.
    if "atencao" in alvo or "conferir" in alvo or "divergen" in alvo:
        return "atencao"
    return "info"


def estilo_tabela(tabela: "ttk.Treeview", zebra: bool = True,
                  dupla: bool = False) -> "ttk.Treeview":
    """Põe a tabela no visual do painel e registra as tags de estado.

    Chamar DEPOIS de criar as colunas e ANTES de inserir as linhas. Quem
    insere passa `tags=("ok",)` — ou o que `estado_de` devolver — e a linha
    ganha a pílula sem a aba precisar saber a cor.
    """
    c = cores()
    tabela.configure(style="Dupla.Treeview" if dupla else "Tabela.Treeview")
    # O TÍTULO da coluna acompanha o alinhamento do CONTEÚDO dela: o padrão do
    # ttk é centralizar o cabeçalho e alinhar o conteúdo à esquerda, e a coluna
    # de dinheiro ficava com o título no meio e os valores à direita, sem que
    # nada na tela explicasse por quê.
    try:
        for col in tabela["columns"]:
            tabela.heading(col, anchor=str(tabela.column(col, "anchor")))
    except tk.TclError:
        pass
    # A ORDEM importa e não é a da leitura: no Treeview do Tk ganha a tag
    # configurada PRIMEIRO, não a última da lista do item. Os estados vêm
    # antes da zebra de propósito — uma linha rejeitada não pode ficar cinza
    # só por ser par.
    #
    # SÓ atenção e erro se pintam, e essa é a diferença mais visível entre
    # esta tabela e o mockup. A pílula do mockup pinta uma CÉLULA; a tag do
    # Treeview pinta a LINHA inteira, e o Tk não tem cor por célula.
    #
    # Pintando os quatro estados, uma tabela de dez rotinas virava faixas
    # verdes, azuis e vermelhas alternadas — e aí nada se destaca, que é o
    # oposto do que a cor está ali para fazer. Pintando dois, a linha que
    # precisa de alguém é a única colorida da tela.
    #
    # O "deu certo" e o "é só informação" não ficam mudos: a coluna de
    # situação leva o SÍMBOLO junto do texto (✓ ⚠ ✖ ·), que é o que distingue
    # os quatro estados para quem não vê cor — a mesma regra que rege a
    # trilha de passos desde que ela existe.
    for tag in ("atencao", "erro"):
        tabela.tag_configure(tag, foreground=c[tag],
                             background=c[tag + "_fundo"])
    for tag in ("ok", "info"):
        tabela.tag_configure(tag, foreground=c["texto"])
    if zebra:
        # A zebra é aplicada por quem insere (`linha_zebrada`), e é
        # configurada DEPOIS dos estados pelo motivo dito acima.
        tabela.tag_configure("par", background=c["zebra"])
        tabela.tag_configure("impar", background=c["cartao"])
    return tabela


def linha_zebrada(indice: int, estado: str = "") -> tuple:
    """As tags de uma linha: a zebra primeiro, o estado por cima."""
    tags = ["par" if indice % 2 else "impar"]
    if estado:
        tags.append(estado)
    return tuple(tags)


def brl(v) -> str:
    """R$ 1.234,56. Existe aqui porque cinco telas escreviam o mesmo
    `replace(",", "X").replace(".", ",").replace("X", ".")` à mão."""
    try:
        return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(
            ".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ —"


# --------------------------------------------------------------- atividade
#: O que as telas fizeram, em ordem, para o Início poder contar.
#:
#: Arquivo e não banco: é histórico de UMA máquina, ele tem de continuar
#: legível quando a nuvem está fora, e ninguém decide dinheiro por ele. JSONL
#: (um evento por linha) porque escrever é sempre um `append` — nenhuma
#: rotina precisa reler nem reescrever o que as outras gravaram, e uma linha
#: corrompida custa uma linha, não o arquivo.
ARQ_ATIVIDADE = "atividade.jsonl"

#: Quantas linhas o arquivo guarda. Ele é lido inteiro na abertura do Início;
#: sem um teto, o dia em que alguém rodar mil lotes é o dia em que a primeira
#: tela do app fica lenta.
MAX_ATIVIDADE = 400


def registrar_atividade(aba: str, evento: str, resultado: str = "ok",
                        detalhe: str = "", numeros: dict | None = None) -> None:
    """Anota que uma rotina aconteceu. Nunca levanta.

    Falhar aqui não pode parar trabalho nenhum: é registro de tela, e o pior
    caso é o Início mostrar um evento a menos.

    `numeros` é o que a tela ACABOU de contar — quantos lançamentos, quanto em
    reais, quantos sem anexo. Guardar aqui é o que permite ao Início mostrar
    números de verdade sem abrir o navegador na abertura do app: quem já
    contou é a rotina, e ela conta uma vez só.
    """
    linha = {"quando": _dt.datetime.now().isoformat(timespec="seconds"),
             "aba": aba, "evento": evento, "resultado": resultado,
             "detalhe": detalhe, "numeros": numeros or {}}
    try:
        caminho = util.pasta_base() / ARQ_ATIVIDADE
        with open(caminho, "a", encoding="utf-8") as arq:
            arq.write(json.dumps(linha, ensure_ascii=False) + "\n")
        _podar_atividade(caminho)
    except Exception:                                        # noqa: BLE001
        pass


def _podar_atividade(caminho) -> None:
    """Corta o arquivo quando ele passa do teto. Só de vez em quando: reler e
    reescrever a cada evento faria toda rotina pagar o preço do histórico."""
    try:
        if caminho.stat().st_size < 120 * MAX_ATIVIDADE:
            return
        linhas = caminho.read_text(encoding="utf-8").splitlines()
        if len(linhas) <= MAX_ATIVIDADE:
            return
        caminho.write_text("\n".join(linhas[-MAX_ATIVIDADE:]) + "\n",
                           encoding="utf-8")
    except Exception:                                        # noqa: BLE001
        pass


def atividades(limite: int = 40) -> list:
    """Os últimos eventos, do mais novo para o mais velho."""
    try:
        linhas = (util.pasta_base() / ARQ_ATIVIDADE).read_text(
            encoding="utf-8").splitlines()
    except OSError:
        return []
    saida = []
    for linha in reversed(linhas):
        if len(saida) >= limite:
            break
        try:
            saida.append(json.loads(linha))
        except ValueError:
            continue                     # linha pela metade: pula, não estoura
    return saida


def ultima_atividade(aba: str) -> dict | None:
    """O último evento de uma aba — o "última execução" da tela de Início."""
    for ev in atividades(MAX_ATIVIDADE):
        if ev.get("aba") == aba:
            return ev
    return None


def quando_humano(iso: str) -> str:
    """"hoje 14:32", "ontem 09:10", "12/08 16:44" — o formato que se lê de
    relance numa coluna estreita."""
    try:
        q = _dt.datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return "—"
    dias = (_dt.date.today() - q.date()).days
    if dias == 0:
        return f"hoje {q:%H:%M}"
    if dias == 1:
        return f"ontem {q:%H:%M}"
    return f"{q:%d/%m %H:%M}"

def _chars(texto: tk.Text, ini, fim) -> int:
    n = texto.count(ini, fim, "chars")
    return n[0] if n else 0


def tem_conteudo_real(texto: tk.Text) -> bool:
    """Há algo no registro além do texto de tela vazia?

    O texto de tela vazia entra todo com a tag "ph" (ver `estilo_log`), então
    "real" é simplesmente o que sobra fora dela. Contar caracteres em vez de
    olhar se o campo está vazio importa porque seis abas nascem com três
    linhas de instrução dentro do registro — pelo tamanho, elas passariam por
    trabalho feito."""
    total = _chars(texto, "1.0", "end-1c")
    if not total:
        return False
    faixas = texto.tag_ranges("ph")
    marcado = sum(_chars(texto, faixas[i], faixas[i + 1])
                  for i in range(0, len(faixas), 2))
    return total > marcado


def cartao_elastico(cartao, cheio: bool) -> None:
    """Cartão que só toma a tela quando tem o que mostrar.

    `pack_configure` e NÃO `pack`: reempacotar joga o widget para o fim da
    ordem. Vale o mesmo aviso de `registro_elastico`."""
    cartao.pack_configure(fill="both" if cheio else "x", expand=bool(cheio))


def registro_elastico(cartao, texto: tk.Text, altura_minima: int = 6) -> None:
    """O cartão de Registro ocupa a tela só quando tem o que mostrar.

    Parado, ele era metade da janela em branco com uma frase cinza no meio,
    enquanto o formulário ficava espremido em cima. Vazio agora vale seis
    linhas; a primeira linha de trabalho devolve o espaço todo.

    Quem dispara é o `<<Modified>>` do próprio campo, e não a aba: as nove
    abas escrevem no registro de lugares diferentes (`_drain`, `_log`,
    placeholder), e pedir que cada uma avisasse daria dezoito pontos de
    chamada para esquecer um.

    `pack_configure` e NÃO `pack`: reempacotar move o widget para o FIM da
    ordem, e em cinco abas o Registro passaria a nascer embaixo da barra de
    ação — que é justamente onde ficam os botões de começar."""
    #: `pintado` é até onde `colorir_registro` já passou. Guardado aqui, e não
    #: recalculado, porque o registro de um lote grande chega a milhares de
    #: linhas e repintá-lo inteiro a cada mensagem trava a janela.
    estado = {"cheio": None, "dentro": False, "pintado": 1}

    def _altura_vazia() -> int:
        """Quantas linhas o texto de tela vazia precisa para caber inteiro.

        Ele varia por aba (de três a cinco linhas) e leva `spacing1`, que o Tk
        cobra em PIXELS enquanto `height` conta LINHAS — daí a folga. Com uma
        altura fixa de seis, o Anexar cortava a última frase no meio, que é
        justamente a que diz o que fazer."""
        linhas = int(texto.index("end-1c").split(".")[0])
        return min(max(linhas + 3, altura_minima), 14)

    def _ajustar(_ev=None):
        if estado["dentro"]:             # `edit_modified` mexe na flag e pode
            return                       # reentrar no próprio <<Modified>>
        estado["dentro"] = True
        try:
            texto.edit_modified(False)
            cheio = tem_conteudo_real(texto)
            # A altura é recalculada a cada mudança, e não só na virada: a aba
            # apaga o campo ANTES de reescrever a tela vazia, e nesse instante
            # ele tem uma linha. Medir só ali fixaria a altura do campo vazio,
            # e o texto que entra logo depois nasceria cortado.
            alvo = 1 if cheio else _altura_vazia()
            if cheio != estado["cheio"] or int(texto.cget("height")) != alvo:
                estado["cheio"] = cheio
                texto.configure(height=alvo)
                cartao_elastico(cartao, cheio)
            # A cor das linhas entra AQUI, e não em cada `_log` das abas: o
            # `<<Modified>>` já é o ponto por onde passa toda escrita no
            # registro, venha ela do `_drain`, do placeholder ou de um
            # `insert` direto. Pendurar a pintura noutro lugar significaria
            # dezoito pontos de chamada para esquecer um.
            if cheio:
                estado["pintado"] = colorir_registro(texto, estado["pintado"])
            else:
                estado["pintado"] = 1    # voltou à tela vazia: recomeça
        except tk.TclError:
            pass                         # aba destruída no meio do caminho
        finally:
            estado["dentro"] = False

    texto.bind("<<Modified>>", _ajustar, add="+")
    _ajustar()


def estilo_log(texto: tk.Text, escuro: bool | None = None) -> None:
    """Cores e fonte do campo de registro, iguais nas sete abas que têm um.

    Existia em quatro cópias byte a byte. Também configura a tag "ph", usada
    pelo texto de tela vazia — que antes era `#8a8a8a` fixo e sumia no claro.

    ESCURO NOS DOIS TEMAS, e isso é escolha e não descuido: o registro é um
    terminal embutido, e um terminal branco no meio de um painel branco
    deixa de se distinguir do formulário que está logo acima. É também a
    única superfície do app onde a cor carrega significado por linha (✔ ⚠ ✖),
    e o fundo fundo é o que dá contraste para os três de uma vez.
    """
    if escuro is not None:
        _estado["escuro"] = bool(escuro)
    c = cores()
    texto.configure(background=c["log_fundo"], foreground=c["log_texto"],
                    insertbackground=c["log_texto"], font=FONTE_MONO,
                    selectbackground="#2A3A57", selectforeground="#FFFFFF",
                    # A moldura existe por causa do tema ESCURO: ali o fundo do
                    # registro (#101623) e o do cartão (#171D28) ficam a seis
                    # níveis de distância, e sem o filete o terminal embutido
                    # virava só uma área um pouco mais escura do cartão. No
                    # claro ela não faz falta nem atrapalha.
                    highlightthickness=1, highlightbackground=c["borda"],
                    highlightcolor=c["borda"],
                    padx=12, pady=8)
    texto.tag_configure("ph", justify="center", foreground=c["tenue"],
                        spacing1=6, font=FONTE_APOIO)
    for tag, cor in LOG_CORES.items():
        texto.tag_configure(tag, foreground=cor)
    texto.tag_configure("forte", foreground="#FFFFFF")


#: O que é aviso e o que é erro no texto que as abas já escrevem.
#:
#: Casa contra o que ELAS escrevem hoje — "[!]", "⚠", "ERRO:", "✔" — em vez de
#: pedir que cada uma passe a marcar a linha. São sete abas e dezenas de
#: pontos de `_log(...)`; um de-para aqui não deixa nenhum de fora, e uma
#: convenção nova deixaria.
_MARCAS_LOG = (
    ("erro", re.compile(r"(^|\s)(\[x\]|✖|✗|ERRO\b|FALHOU\b|Não deu|Nao deu)", re.I)),
    ("aviso", re.compile(r"(^|\s)(\[!\]|⚠|ATEN[ÇC][ÃA]O\b|aviso:)", re.I)),
    ("ok", re.compile(r"(^|\s)(\[ok\]|✔|✓|pronto\b|conclu[íi]d)", re.I)),
)

#: O relógio no começo da linha. As abas escrevem "[14:32]" e "14:32:07 — ".
_HORA_LOG = re.compile(r"^\s*\[?(\d{2}:\d{2}(?::\d{2})?)\]?")


def colorir_registro(texto: tk.Text, de_linha: int = 1) -> int:
    """Pinta as linhas do registro a partir de `de_linha`. Devolve onde parou.

    Linha inteira e não palavra: o que interessa é achar de relance a linha
    que deu errado no meio de duzentas que deram certo, e uma palavra colorida
    dentro de uma linha cinza não se acha de relance.
    """
    try:
        ultima = int(texto.index("end-1c").split(".")[0])
    except tk.TclError:
        return de_linha
    for n in range(max(de_linha, 1), ultima + 1):
        ini, fim = f"{n}.0", f"{n}.end"
        try:
            linha = texto.get(ini, fim)
        except tk.TclError:
            break
        if not linha.strip():
            continue
        hora = _HORA_LOG.match(linha)
        if hora:
            texto.tag_add("ts", ini, f"{n}.{hora.end()}")
        for tag, padrao in _MARCAS_LOG:
            if padrao.search(linha):
                texto.tag_add(tag, f"{n}.{hora.end() if hora else 0}", fim)
                break
    return ultima

def estilo_campo_texto(texto: tk.Text, escuro: bool | None = None) -> None:
    """Um `tk.Text` que é CAMPO, e não registro.

    Existem três no app (o modelo de comentário e a prévia da Acessórias, e o
    registro dos Aportes que também se digita), e eles nasciam brancos com
    borda cinza fixa — o que no tema escuro deixava um retângulo branco no
    meio do cartão. Aqui eles pegam a cor do cartão e a borda da paleta, como
    qualquer `ttk.Entry`.

    Não é o `estilo_log`: aquele pinta o terminal embutido, que é escuro nos
    dois temas de propósito. Este é para texto que a pessoa ESCREVE."""
    if escuro is not None:
        _estado["escuro"] = bool(escuro)
    c = cores()
    try:
        texto.configure(background=c["cartao"], foreground=c["texto"],
                        insertbackground=c["texto"],
                        selectbackground=c["marca_fundo"],
                        selectforeground=c["marca"],
                        # A fonte do CORPO, e não a `TkFixedFont` que o
                        # `tk.Text` usa por padrão: aqui se escreve português,
                        # e o Courier ao lado da Segoe UI dos rótulos parecia
                        # um campo de outro programa.
                        font="TkDefaultFont",
                        highlightthickness=1, highlightbackground=c["borda"],
                        highlightcolor=c["marca"], borderwidth=0,
                        relief="flat", padx=8, pady=6)
    except tk.TclError:
        pass


def focar_primeiro_campo(quadro) -> "ttk.Entry | None":
    """Põe o cursor no campo de texto mais ALTO da aba. Devolve quem recebeu.

    Quase toda aba começa por uma data, e abrir com o foco perdido obriga a
    clicar antes de digitar — todo dia, em toda aba.

    Ordena pela posição na TELA, e não pela ordem na árvore de widgets. Em
    Pagamentos do Dia o campo "Onde salvar" é filho DIRETO do cartão 3,
    enquanto a data mora três níveis abaixo (cartão → linha → CampoData →
    Entry): qualquer varredura da árvore acha o caminho primeiro e larga o
    cursor no fim do formulário.

    Só entra campo MAPEADO: aba ainda não desenhada não tem posição, e sem
    posição a comparação de "mais alto" é entre zeros."""
    candidatos = []
    pilha = [quadro]
    while pilha:
        w = pilha.pop()
        # Combobox É subclasse de Entry, e o `readonly` das listas de escolha
        # aceita foco sem aceitar digitação: cair nele é pior do que não focar.
        if (isinstance(w, ttk.Entry) and not isinstance(w, ttk.Combobox)
                and str(w.cget("state")) == "normal" and w.winfo_ismapped()):
            candidatos.append(w)
        pilha.extend(w.winfo_children())
    if not candidatos:
        return None
    alvo = min(candidatos, key=lambda w: (w.winfo_rooty(), w.winfo_rootx()))
    alvo.focus_set()
    return alvo


def estilo_canvas(canvas: tk.Canvas, escuro: bool | None = None) -> None:
    """Fundo do Canvas igual ao do cartão que o contém.

    O Canvas é widget clássico e nasce branco. Pagamentos do Dia e Relatório
    Mensal o pintavam com a cor do REGISTRO (`#ffffff` no claro), mas ele mora
    dentro de um cartão que o sv-ttk pinta de `#fafafa`: sobrava um retângulo
    branco atrás da lista de contas, com a emenda aparecendo na borda."""
    if escuro is not None:
        _estado["escuro"] = bool(escuro)
    try:
        cor = ttk.Style().lookup("TFrame", "background")
    except tk.TclError:
        cor = ""
    canvas.configure(background=cor or cores()["log_fundo"])


#: Qual `CampoData` está com o calendário aberto — no máximo um em todo o app.
#: Enquanto o popup era modal, o próprio Tk garantia isso: com o app inteiro
#: surdo, não havia como clicar no 📅 de outro campo. Sem o modal, dois
#: calendários abertos ficariam iguais na tela e ninguém saberia qual preenche
#: qual — e o segundo taparia o primeiro.
_calendario_aberto = None


class ComboBusca(ttk.Combobox):
    """Combo em que se DIGITA para procurar, além de escolher na lista.

    Existia um campo "Buscar" separado, que filtrava dois combos de uma vez.
    Ele resolvia o problema errado: para achar a conta do "Recebeu" era preciso
    sair para outro campo, digitar, voltar e abrir a lista — e o mesmo filtro
    mexia no "Pagou" junto, mesmo quando só o outro interessava. Aqui o campo é
    o próprio buscador, e cada um filtra o seu.

    Compara sem acento e sem caixa, por PEDAÇO em qualquer posição (`util.
    filtrar`): "696" acha a subconta 55696-3, "livia" acha "Livian".

    A lista NÃO se abre sozinha a cada tecla, de propósito. Com a lista posta,
    o Tk manda as teclas para ELA — que tem busca própria, por prefixo — e a
    pessoa acaba digitando num lugar diferente do que está olhando. Abrir fica
    com quem abre: a seta, o clique ou ↓.

    E nada é escolhido por adivinhação: texto que não é uma opção fica como foi
    digitado, e quem lança dinheiro recebe o erro em vez de uma conta parecida
    escolhida em silêncio. A única correção automática é de GRAFIA, quando o
    que se digitou casa exatamente com uma opção fora acento e caixa.
    """

    def __init__(self, master, width=38, **kw):
        kw.setdefault("state", "normal")          # readonly não deixa digitar
        super().__init__(master, width=width, **kw)
        self._todos: list[str] = []
        self.bind("<KeyRelease>", self._ao_digitar)
        self.bind("<<ComboboxSelected>>", self._ao_escolher)
        self.bind("<FocusOut>", self._ao_sair)

    # ------------------------------------------------------------ conteúdo
    def definir_valores(self, valores) -> None:
        """A lista COMPLETA. O filtro sempre parte dela.

        Guardada à parte porque filtrar sobre `self["values"]` faria cada
        tecla filtrar o resultado da anterior: a lista só encolheria, e apagar
        o que se digitou não a traria de volta."""
        self._todos = [str(v) for v in valores]
        self["values"] = self._todos

    def valores_completos(self) -> list[str]:
        return list(self._todos)

    # -------------------------------------------------------------- eventos
    def _ao_digitar(self, ev):
        # Navegação e escolha não são digitação: filtrar aqui embaralharia a
        # lista justamente enquanto a pessoa anda por ela.
        if ev.keysym in ("Up", "Down", "Return", "Escape", "Tab", "Left",
                         "Right", "Home", "End", "Shift_L", "Shift_R",
                         "Control_L", "Control_R"):
            return
        self["values"] = util.filtrar(self._todos, self.get())

    def _ao_escolher(self, _ev=None):
        """Escolheu: a lista volta inteira, senão a próxima abertura ainda
        mostraria só o que sobrou do filtro anterior."""
        self["values"] = self._todos

    def _ao_sair(self, _ev=None):
        texto = self.get().strip()
        if not texto:
            self["values"] = self._todos
            return
        alvo = util.norm_espaco(texto)
        exatos = [v for v in self._todos if util.norm_espaco(v) == alvo]
        if len(exatos) == 1 and exatos[0] != texto:
            self.set(exatos[0])          # só arruma a grafia
        self["values"] = self._todos


class CampoData(ttk.Frame):
    """Campo de data dd/mm/aaaa, com calendário e máscara.

    Duas formas de preencher, porque as duas aparecem no uso real:

    - DIGITAR, com as barras entrando sozinhas ("0508" vira "05/08") e o ano
      completado ao sair do campo;
    - CLICAR no campo (ou no 📅), que abre o calendário sob ele.

    O clique simples ABRE o calendário — e essa foi a decisão que precisou de
    duas tentativas para ficar de pé. Em 11/08/2026 abrir no clique tornou o
    campo impossível de editar em todas as abas de uma vez: o popup pegava o
    foco, e a tecla digitada ia para ele. O conserto de então foi exigir duplo
    clique; o conserto de agora é o popup NÃO PEGAR FOCO NENHUM.

    Daí saem as três regras que sustentam este calendário, e nenhuma delas é
    detalhe de estilo:

    1. o foco fica no `Entry`. O popup é `overrideredirect` (sem barra de
       título) e nunca chama `focus_set`. Quem clica no campo e começa a
       digitar segue digitando; a primeira tecla fecha o calendário;
    2. os dias são `tk.Label` com clique, e não botões. Botão aceita foco, e
       aceitar foco é justamente o que o item 1 proíbe. De quebra, `Label`
       aceita cor de fundo — o `ttk.Button` do sv-ttk é imagem e não aceitava
       o azul do dia escolhido nem o contorno do dia de hoje;
    3. fechar é por Esc, por clique fora ou por escolher o dia — nunca por
       `<FocusOut>`. Foi o `<FocusOut>` que matou a primeira versão sem
       borda: o popup nascia sem foco (por construção), o evento disparava no
       mesmo instante, e o calendário fechava antes de aparecer.

    Não há `grab_set`: um grab entrega TODO clique e TODA tecla do app a esta
    janelinha, e quem abrisse o calendário sem querer ficava preso nele — nem
    o X da janela principal respondia.

    O calendário é tkinter puro (Toplevel + grade de Labels). Existe pacote
    pronto (`tkcalendar`), mas dependência nova obriga a gerar um executável
    novo de ~150 MB e a subir o `motor_minimo.txt` — caro demais para um
    calendário de cem linhas.
    """

    def __init__(self, master, textvariable, width=11):
        super().__init__(master)
        self.var = textvariable
        self._popup = None
        self._fora = None                # o bind de "clicou fora", enquanto aberto
        self.ent = ttk.Entry(self, textvariable=self.var, width=width)
        self.ent.pack(side="left")
        self.bt = Botao(self, "📅", papel="neutro", command=self.abrir_calendario,
                        padx=7, pady=2)
        self.bt.pack(side="left", padx=(3, 0))

        self.ent.bind("<KeyRelease>", self._ao_digitar)
        self.ent.bind("<Button-1>", self._ao_clicar)
        self.ent.bind("<FocusOut>", lambda _e: self._completar_ano())
        # Esc no CAMPO, e não só no popup: o foco nunca sai do campo, então é
        # ele quem recebe a tecla.
        self.ent.bind("<Escape>", lambda _e: self._fechar_popup())

    # ----------------------------------------------------------- digitação
    def _ao_clicar(self, _ev=None):
        """Clique no campo: põe o cursor E abre o calendário.

        Devolve nada (não interrompe o evento), então o `Entry` continua
        tratando o clique como sempre — é isso que mantém o campo editável.
        O `after_idle` deixa o Tk terminar de posicionar o cursor antes de a
        janelinha aparecer; abrindo no meio do evento, o popup roubava a
        segunda metade do clique."""
        if self._popup is None:
            self.after_idle(self.abrir_calendario)

    def _ao_digitar(self, ev):
        # Teclas de navegação e edição não podem remontar o texto embaixo do
        # cursor — senão apagar um dígito no meio vira uma briga com a máscara.
        if ev.keysym in ("BackSpace", "Delete", "Left", "Right", "Up", "Down",
                         "Home", "End", "Tab", "Shift_L", "Shift_R",
                         "Control_L", "Control_R", "Escape"):
            return
        self._fechar_popup()             # começou a digitar: o calendário sai

        # A máscara SÓ age quando se digita no fim do campo. Ela remonta o
        # texto a partir de todos os dígitos, e fazer isso no meio de uma data
        # já preenchida destrói o valor: com "01/08/2026" e o cursor no
        # começo, digitar "0" virava "00/10/8202". Editar o meio, colar e
        # corrigir um dígito passam intactos.
        try:
            if self.ent.index("insert") != len(self.var.get()):
                return
        except tk.TclError:
            return

        t = self.var.get()
        d = "".join(c for c in t if c.isdigit())[:8]
        if len(d) > 4:
            novo = f"{d[:2]}/{d[2:4]}/{d[4:]}"
        elif len(d) > 2:
            novo = f"{d[:2]}/{d[2:]}"
        else:
            novo = d
        if novo != t:
            self.var.set(novo)
            self.ent.icursor("end")

    def _completar_ano(self):
        """"05/08" -> "05/08/2026"; "05/08/26" -> "05/08/2026".

        Sair do campo com a data pela metade é o caso comum de quem digita
        rápido, e o resto do app só aceita dd/mm/aaaa."""
        t = (self.var.get() or "").strip()
        m = re.match(r"^(\d{2})/(\d{2})(?:/(\d{2}|\d{4}))?$", t)
        if not m:
            return
        ano = m.group(3)
        if ano is None:
            ano = str(date.today().year)
        elif len(ano) == 2:
            ano = f"20{ano}"
        self.var.set(f"{m.group(1)}/{m.group(2)}/{ano}")

    # ---------------------------------------------------------- calendário
    def _escolhida(self) -> date | None:
        """A data que já está no campo, quando ela está inteira."""
        m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", (self.var.get() or "").strip())
        if not m:
            return None
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None                  # 31/02: digitação, não data

    def _data_atual(self) -> tuple[int, int]:
        """(mês, ano) que o calendário deve mostrar ao abrir."""
        escolhida = self._escolhida()
        if escolhida:
            return escolhida.month, escolhida.year
        hoje = date.today()
        return hoje.month, hoje.year

    def _fechar_popup(self):
        global _calendario_aberto
        if self._fora is not None:
            try:
                self.winfo_toplevel().unbind("<Button-1>", self._fora)
            except tk.TclError:
                pass
            self._fora = None
        if self._popup is not None:
            try:
                self._popup.destroy()
            except tk.TclError:              # a janela principal já levou o
                pass                         # popup junto ao ser destruída
            self._popup = None
        if _calendario_aberto is self:
            _calendario_aberto = None

    def abrir_calendario(self):
        global _calendario_aberto
        if self._popup is not None:       # já aberto: clicar de novo fecha
            self._fechar_popup()
            return
        if _calendario_aberto is not None:   # um calendário de cada vez
            _calendario_aberto._fechar_popup()

        c = cores()
        top = tk.Toplevel(self)
        self._popup = top
        top.withdraw()                   # posiciona antes de aparecer
        top.overrideredirect(True)       # sem barra de título: ver a classe
        top.transient(self.winfo_toplevel())
        try:
            top.attributes("-topmost", True)
        except tk.TclError:
            pass

        # A borda é do próprio frame, já que não há moldura de janela.
        moldura = tk.Frame(top, background=c["cartao"], highlightthickness=1,
                           highlightbackground=c["borda"],
                           highlightcolor=c["borda"], padx=10, pady=9)
        moldura.pack(fill="both", expand=True)

        mes, ano = self._data_atual()
        estado = {"mes": mes, "ano": ano}
        hoje = date.today()

        cab = tk.Frame(moldura, background=c["cartao"])
        cab.pack(fill="x")
        lbl = ttk.Label(cab, text="", width=17, anchor="center",
                        style="Forte.TLabel")
        grade = tk.Frame(moldura, background=c["cartao"])
        grade.pack(pady=(6, 0))

        def escolher(dia: int):
            self.var.set(f"{dia:02d}/{estado['mes']:02d}/{estado['ano']}")
            self._fechar_popup()
            self.ent.focus_set()
            self.ent.icursor("end")

        def ir_para_hoje():
            self.var.set(f"{hoje:%d/%m/%Y}")
            self._fechar_popup()
            self.ent.focus_set()
            self.ent.icursor("end")

        def limpar():
            self.var.set("")
            self._fechar_popup()
            self.ent.focus_set()

        def desenhar():
            for w in grade.winfo_children():
                w.destroy()
            lbl.config(text=f"{MESES[estado['mes'] - 1]} {estado['ano']}")
            for i, inicial in enumerate(DIAS_DA_SEMANA):
                tk.Label(grade, text=inicial, width=3, anchor="center",
                         background=c["cartao"], foreground=c["tenue"],
                         font=FONTE_MINI).grid(row=0, column=i, pady=(0, 3))
            escolhida = self._escolhida()
            semanas = calendar.Calendar(SEMANA_COMECA_EM).monthdayscalendar(
                estado["ano"], estado["mes"])
            for r, semana in enumerate(semanas, 1):
                for col, dia in enumerate(semana):
                    if not dia:
                        continue
                    este = date(estado["ano"], estado["mes"], dia)
                    marcado = escolhida == este
                    cel = tk.Label(
                        grade, text=str(dia), width=3, anchor="center",
                        padx=2, pady=3, cursor="hand2",
                        background=c["marca_solida"] if marcado
                        else c["cartao"],
                        foreground="#FFFFFF" if marcado else c["texto"],
                        # O dia de HOJE é contorno, e o ESCOLHIDO é
                        # preenchimento: são duas informações diferentes, e o
                        # dia que é os dois ao mesmo tempo tem de mostrar as
                        # duas — com uma cor só, uma delas sumiria.
                        #
                        # São dois azuis, e de propósito: o preenchimento leva
                        # branco por cima e precisa da `marca_solida`; o
                        # contorno é um filete de 1 px, não tem texto nenhum e
                        # some se escurecer — ali a `marca` entrega 6,3:1
                        # contra o cartão, contra os 3,65:1 da outra.
                        highlightthickness=1 if este == hoje else 0,
                        highlightbackground=c["marca"],
                        highlightcolor=c["marca"])
                    cel.grid(row=r, column=col, padx=1, pady=1)
                    cel.bind("<Button-1>", lambda _e, d=dia: escolher(d))
                    if not marcado:
                        cel.bind("<Enter>", lambda e: e.widget.configure(
                            background=c["marca_fundo"]))
                        cel.bind("<Leave>", lambda e: e.widget.configure(
                            background=c["cartao"]))

        def mudar(delta: int):
            m2 = estado["mes"] + delta
            if m2 < 1:
                estado["mes"], estado["ano"] = 12, estado["ano"] - 1
            elif m2 > 12:
                estado["mes"], estado["ano"] = 1, estado["ano"] + 1
            else:
                estado["mes"] = m2
            desenhar()

        Botao(cab, "‹", papel="link", command=lambda: mudar(-1),
              padx=6, pady=0).pack(side="left")
        lbl.pack(side="left", expand=True)
        Botao(cab, "›", papel="link", command=lambda: mudar(1),
              padx=6, pady=0).pack(side="right")

        rodape = tk.Frame(moldura, background=c["cartao"])
        rodape.pack(fill="x", pady=(7, 0))
        Botao(rodape, "Hoje", papel="link", padx=4, pady=1,
              command=ir_para_hoje).pack(side="left")
        Botao(rodape, "Limpar", papel="link", padx=4, pady=1,
              command=limpar).pack(side="right")

        desenhar()

        # Debaixo do campo, e puxado para dentro da tela quando não cabe: com
        # `overrideredirect` o Windows não reposiciona nada por conta própria,
        # e um campo perto da borda de baixo abria o calendário fora do monitor.
        top.update_idletasks()
        x = self.ent.winfo_rootx()
        y = self.ent.winfo_rooty() + self.ent.winfo_height() + 3
        larg, alt = top.winfo_reqwidth(), top.winfo_reqheight()
        x = max(min(x, top.winfo_screenwidth() - larg - 8), 8)
        if y + alt > top.winfo_screenheight() - 8:
            y = self.ent.winfo_rooty() - alt - 3
        top.geometry(f"+{x}+{y}")
        top.deiconify()

        # Clique fora fecha. Vai no toplevel do APP (não no popup), porque o
        # que interessa é o clique que acontece longe daqui — e ele nunca
        # chega ao popup. `add="+"` para não derrubar binds de quem já usava
        # o <Button-1> da janela.
        self._fora = self.winfo_toplevel().bind("<Button-1>", self._clique_fora,
                                                add="+")
        top.bind("<Escape>", lambda _e: self._fechar_popup())
        _calendario_aberto = self

    def _clique_fora(self, ev):
        """Fecha, a não ser que o clique tenha sido no campo ou no calendário.

        Compara o CAMINHO do widget no Tk (`.!frame.!entry`), que é
        hierárquico: é o mesmo teste que o Enter global usa para saber se o
        campo com o foco está dentro da aba atual."""
        if self._popup is None:
            return
        alvo = str(ev.widget)
        if alvo.startswith(str(self._popup)) or alvo.startswith(str(self)):
            return
        self._fechar_popup()

    # ------------------------------------------------------------- tema
    def aplicar_cores(self, escuro: bool):
        """O `Entry` do ttk segue o tema sozinho; o 📅 é `Botao` e se repinta
        pela `_repintaveis`. O calendário aberto fecha — ele lê a paleta ao
        nascer, e repintá-lo custaria mais do que redesenhá-lo no próximo
        clique."""
        self._fechar_popup()
