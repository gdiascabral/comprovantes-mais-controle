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
        # Desde 28/10/2026 (repaginada, etapa 2) a janela tem DOIS fundos: a
        # `janela`, atrás de tudo, e o `fundo`, o painel flutuante onde moram
        # o menu e a página. Os cartões ficam por cima do painel.
        "janela":      "#E6EAF2",
        "fundo":       "#F7F8FC",   # o painel da página e do menu
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
        # A barra de cima: desde 22/10/2026 na cor da PÁGINA, sem faixa azul
        # (protótipo da repaginada). O texto dela é o `barra_texto`.
        "marca_barra": "#E6EAF2",   # a barra de cima mora na `janela`
        "marca_fundo": "#E8EEFC",   # item ativo do menu, pílula de informação
        "marca_sub":   "#5B6880",   # texto secundário da barra e dica da busca
        "barra_texto": "#1C2537",   # o texto da barra de cima
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
        # Azul-marinho desde 22/10/2026 (protótipo da repaginada aprovado pelo
        # dono); antes era um cinza quase preto. Contrastes medidos de novo.
        "janela":      "#050B17",
        "fundo":       "#0B1529",
        "cartao":      "#0F1C36",
        "borda":       "#1F3053",
        "linha":       "#4A5D85",   # filete, ícone — nunca texto · 2,77:1 no fundo
        "zebra":       "#12203D",
        "cabecalho":   "#14223F",
        "texto":       "#E8EDF7",   # 14,4:1 no cartão · 15,5:1 no fundo
        "apoio":       "#A9B6CF",   #  8,3:1            ·  8,9:1
        "tenue":       "#8C9AB8",   #  6,0:1            ·  6,4:1
        "marca":       "#7C9BFF",   #  6,4:1 no cartão — só como TEXTO
        # Aqui os dois papéis se separam: como fundo sólido, a `marca` deixa o
        # branco em 2,69:1. Este tom é o ponto em que as duas medidas passam
        # ao mesmo tempo — clarear mais afunda o branco, escurecer mais some a
        # forma do botão dentro do cartão.
        "marca_solida": "#3D5AFE",  # branco por cima 5,13:1 · 3,30:1 no cartão
        "marca_barra": "#050B17",   # a barra de cima mora na `janela`
        "marca_fundo": "#192A5E",
        "marca_sub":   "#A9B6CF",
        "barra_texto": "#E8EDF7",
        "acao":        "#12864F",   # branco por cima  4,6:1
        "acao_ativo":  "#0D6E40",
        "acao_viva":   "#2FBE79",
        "ativo":       "#6F9BFF",
        "ok":          "#63D38F",   "ok_fundo":      "#0E3226",   # 7,5:1
        "atencao":     "#F2B65C",   "atencao_fundo": "#382A0B",   # 7,7:1
        "erro":        "#FF8F84",   "erro_fundo":    "#3B1421",   # 7,3:1
        "info":        "#8FB2FF",   "info_fundo":    "#192A5E",   # 6,5:1
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
FONTE_ICONES = "AppIcones"      # os ícones do menu lateral

#: Família dos campos de registro. NÃO sai do `TkFixedFont`: no Windows ele é
#: "Courier New", que é a fonte de máquina de escrever e fica larga e fraca ao
#: lado da Segoe UI. Consolas vem com o Windows desde o Vista, e era a escolha
#: que as seis abas já faziam à mão.
FAMILIA_MONO = "Consolas"

#: As fontes nomeadas que, com a Manrope carregada, saem no peso 800 (a
#: "Manrope ExtraBold") em vez do negrito comum — os títulos do protótipo.
_FONTES_EXTRAFORTES = {FONTE_TITULO, FONTE_SECAO, FONTE_KPI, FONTE_MARCA,
                       FONTE_MINI_FORTE}


# ---------------------------------------------------------------- ícones
# Os ícones do menu eram emoji e dingbats soltos, e o Tk desenhava cada um com
# a fonte que o Windows achasse primeiro. MEDIDO nesta máquina com
# `font actual TkDefaultFont -family <char>`, que devolve a família DEPOIS do
# fallback:
#
#   ▦ Início        Lucida Sans Unicode
#   ⬇ Baixar        Cambria
#   ✂ Separar       MS Gothic
#   ✅ Conferência   Segoe UI Emoji   ← colorida
#   ⚖ Saldo         Segoe UI Emoji   ← colorida
#
# Os sete de fora do BMP (📎 💰 🗓 📊 🏦 📑 📤) e o 👥 do rodapé respondem
# "Segoe UI", que é o que o `font actual` tem a dizer de um caractere fora do
# BMP: ali ele não responde de verdade, e a família é a que o Uniscribe
# escolher na hora de desenhar.
#
# São, no mínimo, QUATRO tipografias diferentes numa coluna de doze linhas —
# os ícones não compartilham espessura de traço, tamanho nem linha de base, e
# isso se vê sem medir nada. E os dois que caem na Segoe UI Emoji vêm de fonte
# COLORIDA: o `foreground` que o `_pintar` do `ItemMenu` passa não alcança
# glifo colorido, então esses ficam iguais nos dois temas, inclusive quando o
# item está aberto e todo o resto dele vira azul.
#
# (O CLAUDE.md conta isto ao contrário — que os sete de fora do BMP são os
# coloridos e que ▦ ⬇ ✂ ✅ ⚖ seguem a cor. O que está escrito aqui é o que a
# máquina respondeu; quem consolida a doc que reconcilie.)
#
# A saída é a fonte de ícones do próprio Windows: UMA família para os treze,
# monocromática por construção, que por isso herda o foreground do estilo. O
# tema passa a alcançar todos, e o desenho passa a sair do mesmo alfabeto.
#
#: As duas famílias, na ordem de preferência. "Segoe Fluent Icons" é a do
#: Windows 11; "Segoe MDL2 Assets" é a do Windows 10, e continua presente no 11
#: (medido nesta máquina: as duas existem). Quem não tiver nenhuma das duas
#: fica com o glifo de texto de sempre — ver `_familia_de_icones`.
ICONES_FAMILIAS = ("Segoe Fluent Icons", "Segoe MDL2 Assets")

#: De-para do glifo de texto (o que o `comprovantes_app` e a `ferramentas/
#: galeria.py` passam em `ItemMenu(icone=…)`) para o codepoint da fonte de
#: ícones. O emoji continua sendo a CHAVE, e não some do código: ele é o
#: fallback final, o que aparece em quem não tem nenhuma das duas famílias.
#:
#: Uma tabela POR FAMÍLIA porque as duas fontes não têm o mesmo alfabeto: aqui,
#: medido lendo o `cmap` dos dois arquivos (`SegoeIcons.ttf` e `segmdl2.ttf`),
#: a Fluent mapeia 2.030 codepoints da área privada contra 1.830 da MDL2 — 201
#: só existem na Fluent. Para ESTES doze, porém, os dois valores coincidem: a
#: Fluent preservou os codepoints da MDL2 nos ícones herdados, e os doze foram
#: conferidos glifo a glifo, desenhados a partir dos dois arquivos de fonte.
#: As tabelas ficam separadas mesmo assim — é onde a divergência vai morar no
#: dia em que um ícone novo só existir numa delas, e duas tabelas iguais que se
#: sabe iguais custam menos que uma tabela que mente.
#:
#: Nome oficial de cada um, na tabela da Microsoft (confira por lá, não por
#: aqui): Home, Download, Cut, Attach, CheckList, PaymentCard, Calendar,
#: Calculator, ReportDocument, Bank, Document, Send e Contact. O décimo
#: quarto, BulletedList (Pagamentos do dia, 21/10/2026), entrou pela tabela da
#: Microsoft e ainda pede a conferência na galeria (`python -m
#: ferramentas.galeria`, máquina livre); o décimo quinto, People (Controle de
#: aportes), também.
ICONES_FLUENT = {
    "▦": "\uE80F",      # Home           — Início
    "⬇": "\uE896",      # Download       — Baixar Comprovantes
    "✂": "\uE8C6",      # Cut            — Separar e Renomear
    "📎": "\uE723",      # Attach         — Anexar
    "✅": "\uE9D5",      # CheckList      — Conferência
    "💰": "\uE8C7",      # PaymentCard    — Aportes
    "🗓": "\uE787",      # Calendar       — Remessa/Retorno
    "⚖": "\uE8EF",      # Calculator     — Saldo de pagamentos
    "📊": "\uE9F9",      # ReportDocument — Relatório Mensal
    "🏦": "\uE825",      # Bank           — Extratos Sicoob
    "📑": "\uE8A5",      # Document       — Contratos
    "📤": "\uE724",      # Send           — Acessorias
    "👥": "\uE77B",      # Contact        — Usuários (o item de admin, no rodapé)
    "🧾": "\uE8FD",      # BulletedList   — Pagamentos do dia
    "🤝": "\uE716",      # People         — Controle de aportes
}

#: A MESMA tabela para o Windows 10. Os valores coincidem hoje — ver acima —, e
#: ela é escrita por extenso de propósito: copiar a de cima com um `dict(...)`
#: esconderia que são duas decisões, e a primeira vez que uma delas mudar o
#: `dict(...)` mudaria as duas juntas, em silêncio.
ICONES_MDL2 = {
    "▦": "\uE80F",      # Home
    "⬇": "\uE896",      # Download
    "✂": "\uE8C6",      # Cut
    "📎": "\uE723",      # Attach
    "✅": "\uE9D5",      # CheckList
    "💰": "\uE8C7",      # PaymentCard
    "🗓": "\uE787",      # Calendar
    "⚖": "\uE8EF",      # Calculator
    "📊": "\uE9F9",      # ReportDocument
    "🏦": "\uE825",      # Bank
    "📑": "\uE8A5",      # Document
    "📤": "\uE724",      # Send
    "👥": "\uE77B",      # Contact
    "🧾": "\uE8FD",      # BulletedList
    "🤝": "\uE716",      # People — Controle de aportes
}

ICONES_POR_FAMILIA = {
    "Segoe Fluent Icons": ICONES_FLUENT,
    "Segoe MDL2 Assets": ICONES_MDL2,
}

_estado = {"escuro": False, "familia_icones": "", "fator": 0.0}


def _familia_de_icones(familias, padrao: str) -> str:
    """A primeira família de ícones PRESENTE, ou o `padrao` quando não há.

    Recebe a lista de famílias em vez de perguntá-la: assim a decisão é uma
    função pura, e o teste exercita os três desfechos sem precisar de máquina
    com (ou sem) cada fonte instalada.

    O `padrao` é a família do `TkDefaultFont` — uma família REAL. É o detalhe
    que impede a armadilha de sempre: criar a fonte nomeada apontando para
    "Segoe Fluent Icons" numa máquina que não a tem NÃO dá erro, o Tk
    simplesmente cai na fonte padrão e os codepoints saem como quadradinhos.
    Quem não tem a fonte tem de ficar com o EMOJI de antes, que ao menos
    desenha alguma coisa — e é `familia_de_icones()` quem diz qual dos dois
    caminhos vale."""
    disponiveis = {str(f) for f in familias}
    for fam in ICONES_FAMILIAS:
        if fam in disponiveis:
            return fam
    return padrao


def familia_de_icones() -> str:
    """A família de ícones em uso, ou "" quando nenhuma das duas foi achada."""
    return _estado["familia_icones"] if (
        _estado["familia_icones"] in ICONES_POR_FAMILIA) else ""


def icone_do_menu(glifo: str) -> tuple[str, bool]:
    """(o que desenhar, se usa a fonte de ícones) para o glifo de texto dado.

    Sem família de ícones — ou glifo que não está na tabela — devolve o próprio
    glifo e `False`: o emoji de sempre, na fonte de sempre."""
    tabela = ICONES_POR_FAMILIA.get(familia_de_icones())
    if tabela and glifo in tabela:
        return tabela[glifo], True
    return glifo, False


def cores() -> dict:
    """Paleta do tema em uso. Para quem precisa da cor crua (Text, Canvas)."""
    return PALETA["escuro" if _estado["escuro"] else "claro"]


def _escalar(tam: int, fator: float) -> int:
    """Escala preservando o sinal.

    Tamanho NEGATIVO no Tk não é erro: é a medida em pixels, e não em pontos.
    Multiplicar sem cuidado transformava 1,55× num título menor que o corpo."""
    v = max(int(round(abs(tam) * fator)), 1)
    return -v if tam < 0 else v


# --------------------------------------------- a medida de layout, em pixels
# As fontes já acompanham a escala do Windows: elas saem do `TkDefaultFont`,
# que vem no tamanho que a pessoa escolheu. As MEDIDAS de layout não
# acompanhavam —
# e é o desencontro entre as duas que quebra a tela.
#
# Como isso aparece, medido com `ferramentas/galeria.py --escala 1.5`:
# "ÚLTIMA EXECUÇÃO" vira "ÚLTIMA EXECU" (a coluna tem 130 px fixos e a fonte
# cresceu 50%), a coluna SITUAÇÃO some inteira da tabela do Início, e o
# logotipo da barra encosta no campo de busca — a faixa continua com 52 px de
# altura enquanto o texto dentro dela pede 1,5× disso.
#
# `px(n)` é o "n pixels" de quem desenhou a tela a 100%, dito na escala de
# hoje. A 100% ele devolve o próprio n — nada muda para quem já estava bem.
#
# **A régua é a FONTE, e não o DPI**, e a diferença importa: quem aumenta só o
# tamanho da fonte no Windows (sem mexer na escala de exibição) tem o mesmo
# problema, e resolver por DPI deixaria essa pessoa de fora. É a mesma decisão
# que fez as onze fontes nomeadas saírem do `TkDefaultFont` em vez de
# consultarem a escala do sistema.

#: A altura, em pixels, do `TkDefaultFont` numa máquina a 100%: 9 pontos a
#: 96 dpi. É a régua contra a qual o `px` mede — o número que o desenho das
#: telas assumiu sem dizer, já que TODAS as medidas fixas do app foram
#: escolhidas nessa máquina e nessa escala.
FONTE_BASE_PX = 12.0

#: O teto. Escala de 400% não existe no Windows, e um fator absurdo (fonte
#: quebrada, `tk scaling` esquisito de um servidor X) faria um cartão com
#: 4.000 px de margem — pior do que o problema que isto resolve.
FATOR_MAXIMO = 4.0

#: O fator é arredondado para o degrau de 5% mais próximo, e isso não é
#: preciosismo: MEDIDO nesta máquina a 100%, o `tk scaling` devolve 1,3346 e
#: não os 1,3333 da teoria — o monitor responde 96,1 dpi. Sem o degrau, o
#: fator sairia 1,001 e `px(820)` viraria 821: um pixel de diferença em toda
#: tela de quem não mudou escala nenhuma, e a promessa "a 100% nada muda"
#: deixaria de ser verdade. 5% também é fino o bastante para o 110% que o
#: Windows deixa digitar à mão.
DEGRAU_DA_ESCALA = 0.05


def fator_de_escala() -> float:
    """Quanto a fonte do sistema cresceu em relação aos 100% de referência.

    1,0 em máquina a 100%; 1,5 a 150%. **Nunca menos que 1,0**, e isso é
    deliberado: fonte menor que a de referência não corta nada — o texto cabe
    de sobra —, e encolher as margens só apertaria uma tela que já estava boa.
    O erro tem um lado barato, e é este.

    Sai do TAMANHO do `TkDefaultFont` em pixels (pontos × `tk scaling`), e não
    do `-linespace`: a entrelinha carrega o espaçamento da família e não
    acompanha a escala em proporção limpa (medido nesta máquina: 15 px a 100%
    e 25 a 150%, que dá 1,67 e não 1,5).

    Sem janela Tk aberta devolve 1,0 — é o que faz `px` poder ser chamado de
    qualquer lugar sem que quem chama precise saber se já há tela."""
    if _estado["fator"]:
        return _estado["fator"]
    try:
        tcl = ttk.Style().tk
        tam = int(tcl.call("font", "configure", "TkDefaultFont", "-size"))
        if tam < 0:
            alto = float(-tam)           # negativo no Tk já é pixel
        else:
            alto = tam * float(tcl.call("tk", "scaling"))
        bruto = alto / FONTE_BASE_PX
        # No degrau de 5% mais próximo — ver `DEGRAU_DA_ESCALA`.
        fator = round(bruto / DEGRAU_DA_ESCALA) * DEGRAU_DA_ESCALA
        fator = min(max(fator, 1.0), FATOR_MAXIMO)
    except (tk.TclError, ValueError, ZeroDivisionError, RuntimeError):
        # Sem tela ainda: a medida é a de sempre, e NÃO fica guardada — quem
        # perguntou cedo demais não pode congelar o app em 100% para o resto
        # da execução.
        return 1.0
    _estado["fator"] = fator
    return fator


def px(n):
    """`n` pixels de 100% ditos na escala de hoje. Aceita número ou tupla.

    A tupla existe porque quase toda medida de layout do app é a folga de dois
    lados do `pack` — `pady=px((16, 12))` —, e obrigar cada chamada a escalar
    os dois lados à mão daria o dobro das chances de escalar só um.

    **Zero continua zero.** Sem esta ressalva o `_escalar` devolveria 1, e um
    `padx=(0, 8)` viraria `(1, 8)` em toda a tela — um pixel de folga onde o
    desenho pedia encostado.

    O fator é lido UMA vez e fica guardado: trocar a escala do Windows com o
    app aberto muda as fontes (que são nomeadas) e não muda o layout já
    montado. É a mesma limitação que o próprio Windows anuncia quando pede
    para sair e entrar de novo."""
    if isinstance(n, (tuple, list)):
        return type(n)(px(v) for v in n)
    n = int(n)
    if n == 0:
        return 0
    return _escalar(n, fator_de_escala())


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
    não há `__del__` para apagá-la.

    A `FONTE_ICONES` entra pela MESMA porta, e por isso a lista de famílias é
    lida por `font families` do Tcl e não por `tkinter.font.families()`: o que
    derrubou a v1.0.71 foi o import do submódulo, não a função. Fonte NOMEADA
    viaja no codigo.zip; import de submódulo exige exe novo."""
    tcl = ttk.Style().tk                 # o interpretador da janela em uso
    familia = str(tcl.call("font", "configure", "TkDefaultFont", "-family"))
    try:
        tam = int(tcl.call("font", "configure", "TkDefaultFont", "-size")) or 9
    except (ValueError, tk.TclError):
        tam = 9

    _carregar_tipografia()
    try:
        familias = tcl.splitlist(tcl.call("font", "families"))
    except tk.TclError:
        familias = ()
    # A Manrope do protótipo (28/10/2026), quando carregou: vale também para
    # as fontes PADRÃO do Tk, senão o botão clássico e o campo ficavam na
    # Segoe UI no meio de um app em Manrope.
    manrope = FAMILIA_UI in familias and FAMILIA_UI_FORTE in familias
    if manrope:
        familia = FAMILIA_UI
        for padrao in ("TkDefaultFont", "TkTextFont", "TkHeadingFont",
                       "TkMenuFont", "TkCaptionFont", "TkSmallCaptionFont",
                       "TkTooltipFont", "TkIconFont"):
            try:
                tcl.call("font", "configure", padrao, "-family", FAMILIA_UI)
            except tk.TclError:
                pass
    _estado["familia_icones"] = _familia_de_icones(familias, familia)

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
            (FONTE_MARCA, 1.15, "bold", familia),
            # Os ícones do menu. 1,15× porque o desenho de um ícone ocupa menos
            # da caixa do que a letra ocupa da dela: no mesmo tamanho do corpo
            # eles saem visivelmente menores que o emoji que substituíram.
            # Sai do `TkDefaultFont` como todas as outras — a 150% de escala o
            # ícone tem de crescer junto com o nome da aba ao lado dele.
            (FONTE_ICONES, 1.15, "normal", _estado["familia_icones"])):
        if manrope and peso == "bold" and nome in _FONTES_EXTRAFORTES:
            fam, peso = FAMILIA_UI_FORTE, "normal"
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


# ----------------------------------------------------------- cantos redondos
# Até 28/10/2026 o app inteiro era de canto reto, e o docstring do `Cartao`
# explicava por quê: o Tk não arredonda widget. Continua não arredondando — mas
# ele DESENHA imagem, e é com imagem que o sv-ttk faz os botões redondos dele.
# A repaginada visual (protótipo `mockups/2026-10-22-repaginada`) usa a mesma
# saída, com a cor da NOSSA paleta e sem biblioteca nova:
#
# 1. `_ladrilho` gera um PNG pequeno (2r+1 de lado) com os quatro cantos
#    suavizados — a cobertura de cada pixel sai de 4×4 amostras, o que dá a
#    borda sem serrilhado. PNG porque é o formato que o Tk 8.6 lê com canal
#    alfa; zlib, struct e base64 são da stdlib e já viajam no exe.
# 2. `imagem_redonda` monta uma imagem do tamanho que for com NOVE cópias do
#    ladrilho (`photo copy -from … -to …` repete a fonte até encher o
#    destino). Montar é rápido; só o ladrilho custa, e ele fica em cache.
# 3. Quem usa: os elementos de imagem do ttk (campo, botão, tabela — o
#    `border` do elemento estica o miolo e preserva os cantos), o `Botao`
#    (imagem com o texto por cima, `compound="center"`) e o `FundoRedondo`, um
#    rótulo com a imagem posto ATRÁS do conteúdo de um `tk.Frame` (cartão,
#    painel do menu, painel da página, item aberto do menu).
#
# O canto transparente mostra o fundo do próprio widget, por isso cada um pinta
# o seu fundo com a cor de QUEM ESTÁ ATRÁS (`_cor_atras`), e não com a dele.

_LADRILHOS: dict = {}
_AMOSTRAS = 4


def _rgb(cor: str) -> tuple:
    cor = cor.lstrip("#")
    if len(cor) == 3:
        cor = "".join(ch * 2 for ch in cor)
    return tuple(int(cor[i:i + 2], 16) for i in (0, 2, 4))


def _png(larg: int, alt: int, linhas: list) -> str:
    """PNG RGBA (8 bits por canal) em base64, a partir das linhas cruas."""
    import base64
    import struct
    import zlib

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return (struct.pack(">I", len(dados)) + tipo + dados
                + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF))

    cru = b"".join(b"\x00" + bytes(linha) for linha in linhas)
    png = (b"\x89PNG\r\n\x1a\n"
           + bloco(b"IHDR", struct.pack(">IIBBBBB", larg, alt, 8, 6, 0, 0, 0))
           + bloco(b"IDAT", zlib.compress(cru, 9))
           + bloco(b"IEND", b""))
    return base64.b64encode(png).decode("ascii")


def _png_ladrilho(raio: int, cor: str, borda: str | None = None,
                  espessura: int = 1, fora: str | None = None) -> str:
    """Os quatro cantos de um retângulo de raio `raio`, num quadrado 2r+1.

    A coluna e a linha do meio são retas: é delas que `imagem_redonda` tira
    as bordas e o miolo."""
    lado = 2 * raio + 1
    f = _rgb(cor)
    b = _rgb(borda) if borda else None
    o = _rgb(fora) if fora else None
    passo = 1.0 / _AMOSTRAS
    n = _AMOSTRAS * _AMOSTRAS

    def dentro(x, y, r, m):
        x0, y0, x1, y1 = m, m, lado - m, lado - m
        if x < x0 or x > x1 or y < y0 or y > y1:
            return False
        if r <= 0:
            return True
        cx = min(max(x, x0 + r), x1 - r)
        cy = min(max(y, y0 + r), y1 - r)
        return (x - cx) ** 2 + (y - cy) ** 2 <= r * r

    linhas = []
    for py in range(lado):
        linha = bytearray()
        for px_ in range(lado):
            no_aro = no_miolo = 0
            for sy in range(_AMOSTRAS):
                y = py + (sy + 0.5) * passo
                for sx in range(_AMOSTRAS):
                    x = px_ + (sx + 0.5) * passo
                    if not dentro(x, y, raio, 0):
                        continue
                    if b is not None and not dentro(
                            x, y, max(raio - espessura, 0), espessura):
                        no_aro += 1
                    else:
                        no_miolo += 1
            total = no_aro + no_miolo
            if o is not None:
                # OPACO: o canto já sai misturado com a cor de fora. Imagem
                # com transparência é misturada pixel a pixel, por software,
                # a cada redesenho no Windows — com 160 botões a montagem da
                # tela ficava 12 vezes mais lenta (medido em 28/10/2026).
                rgb = tuple(round((f[i] * no_miolo
                                   + (b[i] if b else f[i]) * no_aro
                                   + o[i] * (n - total)) / n)
                            for i in range(3))
                linha += bytes((*rgb, 255))
                continue
            if not total:
                linha += b"\x00\x00\x00\x00"
                continue
            if b is None or not no_aro:
                rgb = f
            else:
                rgb = tuple(round((f[i] * no_miolo + b[i] * no_aro) / total)
                            for i in range(3))
            linha += bytes((*rgb, round(255 * total / n)))
        linhas.append(linha)
    return _png(lado, lado, linhas)


def _viva(img) -> bool:
    """A imagem ainda existe no Tk? Quem guarda imagem em cache de módulo
    sobrevive à janela que a criou (a galeria e os testes abrem mais de uma
    raiz por processo), e imagem de raiz morta é "invalid command name"."""
    if img is None:
        return False
    try:
        img.tk.call("image", "width", img.name)
        return True
    except (tk.TclError, RuntimeError):
        return False


def _ladrilho(raio: int, cor: str, borda: str | None = None,
              espessura: int = 1, fora: str | None = None) -> "tk.PhotoImage":
    chave = (raio, cor.upper(), (borda or "").upper(), espessura,
             (fora or "").upper())
    img = _LADRILHOS.get(chave)
    if not _viva(img):
        img = tk.PhotoImage(data=_png_ladrilho(raio, cor, borda, espessura,
                                               fora))
        _LADRILHOS[chave] = img
    return img


#: Imagens prontas, pela medida e pelas cores: botões iguais dividem a
#: mesma imagem. Teto para não crescer sem fim com janela redimensionada.
_PRONTAS: dict = {}
_TETO_PRONTAS = 600


def imagem_redonda(larg: int, alt: int, raio: int, cor: str,
                   borda: str | None = None, espessura: int = 1,
                   img: "tk.PhotoImage | None" = None,
                   fora: str | None = None) -> "tk.PhotoImage":
    """Retângulo `larg`×`alt` de cantos redondos, preenchido com `cor`.

    `img` reaproveita uma imagem que já existe (o elemento do ttk aponta para
    ela pelo NOME, então trocar o conteúdo troca o desenho sem recriar o
    elemento — é assim que o tema escuro chega aos campos)."""
    larg, alt = max(int(larg), 3), max(int(alt), 3)
    r = max(1, min(int(raio), (larg - 1) // 2, (alt - 1) // 2))
    chave = None
    if img is None:
        chave = (larg, alt, r, cor.upper(), (borda or "").upper(), espessura,
                 (fora or "").upper())
        pronta = _PRONTAS.get(chave)
        if _viva(pronta):
            return pronta
    fonte = _ladrilho(r, cor, borda, espessura, fora)
    if not _viva(img):
        img = tk.PhotoImage(width=larg, height=alt)
    else:
        img.blank()
        img.configure(width=larg, height=alt)
    lado = 2 * r + 1

    def copiar(fx1, fy1, fx2, fy2, tx1, ty1, tx2, ty2):
        if tx2 > tx1 and ty2 > ty1:
            img.tk.call(img, "copy", fonte, "-from", fx1, fy1, fx2, fy2,
                        "-to", tx1, ty1, tx2, ty2, "-compositingrule", "set")

    copiar(0, 0, r, r, 0, 0, r, r)
    copiar(r + 1, 0, lado, r, larg - r, 0, larg, r)
    copiar(0, r + 1, r, lado, 0, alt - r, r, alt)
    copiar(r + 1, r + 1, lado, lado, larg - r, alt - r, larg, alt)
    copiar(r, 0, r + 1, r, r, 0, larg - r, r)
    copiar(r, r + 1, r + 1, lado, r, alt - r, larg - r, alt)
    copiar(0, r, r, r + 1, 0, r, r, alt - r)
    copiar(r + 1, r, lado, r + 1, larg - r, r, larg, alt - r)
    copiar(r, r, r + 1, r + 1, r, r, larg - r, alt - r)
    if chave is not None:
        if len(_PRONTAS) >= _TETO_PRONTAS:
            _PRONTAS.clear()           # quem já usa segura a sua referência
        _PRONTAS[chave] = img
    return img


def _cor_de(papel_ou_cor: str | None) -> str | None:
    """Papel da paleta ("cartao") ou cor crua ("#0F1C36")."""
    if not papel_ou_cor:
        return None
    if papel_ou_cor.startswith("#"):
        return papel_ou_cor
    return cores()[papel_ou_cor]


def _cor_atras(widget) -> str:
    """A cor de fundo de `widget`, seja ele clássico do Tk ou do ttk."""
    try:
        cor = str(widget.cget("background"))
    except (tk.TclError, AttributeError):
        cor = ""
    if not cor:
        try:
            estilo = str(widget.cget("style")) or widget.winfo_class()
            cor = str(ttk.Style().lookup(estilo, "background"))
        except (tk.TclError, AttributeError):
            cor = ""
    cor = cor or cores()["fundo"]
    if not cor.startswith("#"):
        # Nome de cor do sistema ("SystemButtonFace"): a mistura dos cantos
        # precisa do valor, e o Tk sabe convertê-lo.
        try:
            r, g, b = widget.winfo_rgb(cor)
            cor = f"#{r >> 8:02X}{g >> 8:02X}{b >> 8:02X}"
        except (tk.TclError, AttributeError):
            cor = cores()["fundo"]
    return cor


class FundoRedondo:
    """Fundo de cantos redondos atrás do conteúdo de um `tk.Frame`.

    Um `tk.Label` com a imagem, posto por `place` no tamanho do frame e
    rebaixado para trás dos filhos. O frame e o rótulo ficam na cor de QUEM
    ESTÁ ATRÁS (`fora`; sem ela, o fundo do pai), e é essa cor que aparece nos
    cantos. Os filhos precisam de folga da borda — ~30% do raio basta — senão
    cobrem o canto com o retângulo deles.

    Redesenha quando o frame muda de tamanho e quando o tema troca (entra em
    `_repintaveis`). `definir` troca as cores depois (item do menu aberto)."""

    def __init__(self, alvo, raio: int, cor: str, borda: str | None = None,
                 fora: str | None = None, espessura: int = 1):
        self.alvo = alvo
        self.raio = raio
        self.cor, self.borda, self.fora = cor, borda, fora
        self.espessura = espessura
        self._tam = None
        self._img = None
        self.lbl = tk.Label(alvo, borderwidth=0, highlightthickness=0,
                            padx=0, pady=0)
        self.lbl.place(x=0, y=0, relwidth=1, relheight=1)
        self.lbl.lower()
        alvo.bind("<Configure>", self._mudou, add="+")
        alvo._fundo_redondo = self          # o WeakSet não segura sozinho
        _repintaveis.add(self)

    def definir(self, cor=None, borda=..., fora=...):
        if cor is not None:
            self.cor = cor
        if borda is not ...:
            self.borda = borda
        if fora is not ...:
            self.fora = fora
        self.pintar(forcar=True)

    def _mudou(self, _ev=None):
        self.pintar()

    def aplicar_cores(self, escuro: bool | None = None):
        self.pintar(forcar=True)

    def pintar(self, forcar: bool = False):
        try:
            larg, alt = self.alvo.winfo_width(), self.alvo.winfo_height()
        except tk.TclError:
            return
        if larg < 4 or alt < 4:
            return
        fora = _cor_de(self.fora) or _cor_atras(self.alvo.master)
        # O `place` mede a partir da área INTERNA do frame (descontado o
        # padx/pady dele): sem compensar, a imagem ficava menor que o frame e
        # sobrava uma faixa da cor de fora em volta — o cartão perdia os
        # cantos e virava um retângulo branco dentro de um cinza.
        try:
            fx, fy = int(str(self.alvo.cget("padx"))), int(str(self.alvo.cget("pady")))
        except (tk.TclError, ValueError):
            fx = fy = 0
        if (fx, fy) != getattr(self, "_folga", (0, 0)):
            self._folga = (fx, fy)
            self.lbl.place_configure(x=-fx, y=-fy, width=2 * fx,
                                     height=2 * fy)
        chave = (larg, alt, self.cor, self.borda, fora, _estado["escuro"])
        if chave == self._tam and not forcar:
            return
        self._tam = chave
        try:
            self._img = imagem_redonda(larg, alt, self.raio,
                                       _cor_de(self.cor),
                                       _cor_de(self.borda), self.espessura,
                                       fora=fora)
            self.lbl.configure(image=self._img, background=fora)
            self.alvo.configure(background=fora)
        except tk.TclError:
            pass


# ------------------------------------------------------------- tipografia
#: A família do protótipo. Sai de `tipografia/` (ver o LEIA-ME de lá) e é
#: carregada só para este processo; se não carregar, fica a do sistema.
FAMILIA_UI = "Manrope"
FAMILIA_UI_FORTE = "Manrope ExtraBold"
FAMILIA_UI_MEIA = "Manrope SemiBold"


def _carregar_tipografia() -> bool:
    """Põe a Manrope à disposição do Tk, sem instalar nada no Windows.

    `AddFontResourceExW` com `FR_PRIVATE` (0x10): a fonte vale só para este
    processo e some quando ele fecha. Uma vez por processo."""
    if _estado.get("tipografia") is not None:
        return _estado["tipografia"]
    ok = False
    try:
        import ctypes
        from pathlib import Path
        pasta = Path(__file__).resolve().parent / "tipografia"
        for arq in sorted(pasta.glob("Manrope-*.ttf")):
            if ctypes.windll.gdi32.AddFontResourceExW(str(arq), 0x10, 0):
                ok = True
    except Exception:
        ok = False
    _estado["tipografia"] = ok
    return ok


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
                 foreground=c["barra_texto"])
    st.configure("BarraTenue.TLabel", background=c["marca_barra"],
                 foreground=c["marca_sub"], font=FONTE_MINI)
    st.configure("Marca.TLabel", background=c["marca_barra"],
                 foreground=c["barra_texto"], font=FONTE_MARCA)
    # O menu mora no painel flutuante desde 28/10/2026: cor do `fundo`, e
    # não mais a do cartão.
    st.configure("Janela.TFrame", background=c["janela"])
    st.configure("Menu.TFrame", background=c["fundo"])
    st.configure("Menu.TLabel", background=c["fundo"], foreground=c["texto"])
    st.configure("MenuSecao.TLabel", background=c["fundo"],
                 foreground=c["tenue"], font=FONTE_MINI_FORTE)
    # Os três estados de um item do menu. Estilos e não cores soltas porque o
    # `ItemMenu` troca de estilo a cada passada do cursor, e reconfigurar
    # cor por cor a cada `<Enter>` custaria dez widgets por movimento.
    st.configure("Item.TLabel", background=c["fundo"], foreground=c["texto"])
    st.configure("ItemSobre.TLabel", background=c["cabecalho"],
                 foreground=c["texto"])
    # O item aberto é azul CHEIO com texto branco desde 22/10/2026
    # (protótipo da repaginada); antes era azul-claro com texto azul.
    st.configure("ItemAtivo.TLabel", background=c["marca_solida"],
                 foreground="#FFFFFF", font=FONTE_FORTE)

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
    # O filete que fecha o cabeçalho da página: 1 px na cor de filete, no
    # lugar da faixa de cor que o cabeçalho parecia ter (ver `Cabecalho`).
    st.configure("Filete.TFrame", background=c["linha"])

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

    _pecas_que_aceitam_cor(st, c)

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

def _pecas_que_aceitam_cor(st, c: dict) -> None:
    """Troca as peças do sv-ttk que são IMAGEM pelas nossas, na nossa cor.

    O sv-ttk desenha campo, botão, fundo de tabela e `Toolbutton` por imagem,
    com a cor dele assada dentro: o `fieldbackground` e o `background` que
    `aplicar_estilos` passava eram ignorados. Até 22/10/2026 a troca era por
    peças do tema `clam` (cor sim, canto reto); desde a etapa 2 da repaginada
    (28/10/2026) campo, botão e tabela são IMAGENS NOSSAS de cantos redondos
    (`imagem_redonda`), e só o cabeçalho da tabela e o grupo do menu seguem no
    `clam`.

    Elemento e layout são do TEMA ativo, e o `sv_ttk.set_theme` recria o tema:
    por isso isto roda dentro de `aplicar_estilos`, a cada troca. As imagens
    têm NOME fixo (`mc_*`) e são redesenhadas no lugar, e o `element_create`
    repetido no mesmo tema é ignorado."""
    r_campo, r_tabela, r_botao = px(9), px(12), px(9)

    def img(nome, r, cor, borda=None, esp=1, fora=None):
        # Opacas, com o canto misturado na cor do CARTÃO (onde moram campo,
        # botão e tabela). Com transparência, o ttk misturava cada pixel a
        # cada redesenho: 40 campos levavam 5 s para aparecer (28/10/2026).
        atual = _IMAGENS_NOMEADAS.get(nome)
        # Miolo largo (48 px), e não de 1 px: o ttk estica a imagem REPETINDO
        # o miolo, e com 1 px um campo de 200 px eram 200 desenhos por linha.
        _IMAGENS_NOMEADAS[nome] = imagem_redonda(
            2 * r + 48, 2 * r + 48, r, cor, borda, esp, img=atual,
            fora=fora or c["cartao"])
        return _IMAGENS_NOMEADAS[nome]

    campo = img("mc_campo", r_campo, c["cartao"], c["borda"])
    campo_foco = img("mc_campo_foco", r_campo, c["cartao"],
                     c["marca_solida"], 2)
    campo_off = img("mc_campo_off", r_campo, c["fundo"], c["borda"])
    tabela = img("mc_tabela", r_tabela, c["cartao"], c["borda"])
    botao = img("mc_botao", r_botao, c["cartao"], c["borda"])
    botao_sob = img("mc_botao_sob", r_botao, c["cabecalho"], c["borda"])
    botao_aperto = img("mc_botao_aperto", r_botao, c["marca_fundo"],
                       c["borda"])
    botao_off = img("mc_botao_off", r_botao, c["fundo"], c["borda"])
    acento = img("mc_acento", r_botao, c["marca_solida"])
    acento_sob = img("mc_acento_sob", r_botao, cor_do_passo_sob_o_cursor(c))
    acento_off = img("mc_acento_off", r_botao, c["fundo"], c["borda"])

    def elemento(nome, normal, *estados, borda, folga):
        # `border` diz quanto da imagem é canto (não estica); `padding` é a
        # folga interna. Sem o `padding`, o ttk usa o `border` como folga — e
        # o raio do canto virava altura de campo: texto pequeno num campo de
        # quase 50 px (pedido do dono, 28/10/2026: "sem proporção").
        try:
            st.element_create(nome, "image", normal, *estados,
                              border=borda, padding=folga, sticky="nsew")
        except tk.TclError:
            pass                       # já existe neste tema

    folga_campo = (px(10), px(4))
    elemento("Mc.Campo.field", campo, ("disabled", campo_off),
             ("focus", campo_foco), borda=r_campo, folga=folga_campo)
    elemento("Mc.Treeview.field", tabela, borda=r_tabela, folga=px(3))
    elemento("Mc.Botao.button", botao, ("disabled", botao_off),
             ("pressed", botao_aperto), ("active", botao_sob), borda=r_botao,
             folga=(px(12), px(4)))
    elemento("Mc.Acento.button", acento, ("disabled", acento_off),
             ("active", acento_sob), borda=r_botao, folga=(px(12), px(4)))
    for antigo in ("Mc.Treeheading.cell", "Mc.Toolbutton.button"):
        try:
            st.element_create(antigo, "from", "clam")
        except tk.TclError:
            pass

    # Campo, lista e número: troca só o elemento de fora (o `.field`) e deixa
    # a seta e o miolo que o sv-ttk desenha.
    for estilo in ("TEntry", "TCombobox", "TSpinbox"):
        try:
            st.layout(estilo, _trocar_primeiro(st.layout(estilo), ".field",
                                               "Mc.Campo.field"))
        except tk.TclError:
            pass
        st.configure(estilo, padding=(px(2), px(3)), foreground=c["texto"],
                     insertcolor=c["texto"], fieldbackground=c["cartao"],
                     background=c["cartao"])
    for estilo, el in (("TButton", "Mc.Botao.button"),
                       ("Accent.TButton", "Mc.Acento.button")):
        try:
            st.layout(estilo, _trocar_primeiro(st.layout(estilo), ".button",
                                               el))
        except tk.TclError:
            pass
        st.configure(estilo, padding=(px(2), px(2)), background=c["cartao"])
    st.configure("TButton", foreground=c["texto"])
    st.configure("Accent.TButton", foreground="#FFFFFF")
    st.map("Accent.TButton", foreground=[("disabled", c["tenue"])])

    area = [("Treeview.padding", {"sticky": "nswe", "children": [
        ("Treeview.treearea", {"sticky": "nswe"})]})]
    cabeca = [("Treeheading.padding", {"sticky": "nswe", "children": [
        ("Treeheading.image", {"side": "right", "sticky": ""}),
        ("Treeheading.text", {"sticky": "we"})]})]
    for estilo in ("Tabela.Treeview", "Dupla.Treeview"):
        st.layout(estilo, [("Mc.Treeview.field", {
            "sticky": "nswe", "border": "1", "children": area})])
        # O `padding` afasta o cabeçalho (canto reto) dos cantos redondos.
        st.configure(estilo, bordercolor=c["borda"], lightcolor=c["cartao"],
                     darkcolor=c["cartao"], padding=px(4))
        st.layout(estilo + ".Heading",
                  [("Mc.Treeheading.cell", {"sticky": "nswe"})] + cabeca)
        st.configure(estilo + ".Heading", bordercolor=c["cabecalho"],
                     lightcolor=c["cabecalho"], darkcolor=c["cabecalho"])
    st.layout("Grupo.Toolbutton", [("Mc.Toolbutton.button", {
        "sticky": "nswe", "children": [("Toolbutton.padding", {
            "sticky": "nswe", "children": [("Toolbutton.label", {
                "expand": "1", "sticky": "nswe"})]})]})])
    st.configure("Grupo.Toolbutton", bordercolor=c["fundo"],
                 lightcolor=c["fundo"], darkcolor=c["fundo"],
                 background=c["fundo"])
    sob = [("active", c["cabecalho"]), ("pressed", c["cabecalho"])]
    st.map("Grupo.Toolbutton", background=sob, bordercolor=sob,
           lightcolor=sob, darkcolor=sob)


#: As imagens dos elementos do ttk, pelo nome. Guardadas aqui para o coletor
#: de lixo não apagá-las (imagem apagada = elemento desenhado em branco).
_IMAGENS_NOMEADAS: dict = {}


def _trocar_primeiro(layout, sufixo: str, novo: str):
    """O mesmo layout, com o primeiro elemento terminado em `sufixo` trocado."""
    feito = [False]

    def andar(itens):
        saida = []
        for nome, opcoes in itens:
            opcoes = dict(opcoes)
            if not feito[0] and str(nome).endswith(sufixo):
                nome, feito[0] = novo, True
            if "children" in opcoes:
                opcoes["children"] = andar(opcoes["children"])
            saida.append((nome, opcoes))
        return saida

    return andar(layout)


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


#: O papel da paleta que contorna o botão DESLIGADO. Lido também pelo
#: `tests/test_visual.py`, que mede o contraste dele contra o fundo e o cartão
#: (2,70:1 e 3,05:1 no claro; 2,47:1 e 2,25:1 no escuro). A WCAG dispensa o
#: componente inativo do 3:1, e um contorno mais forte faria o desligado
#: parecer disponível — a régua aqui é "dá para ver que é um botão".
BORDA_DESLIGADO = "linha"

#: A moldura do botão da barra de cima ("Minha aba no ERP"). Desde 22/10/2026
#: a barra é a cor da página e o botão é cartão: sem moldura ele virava texto
#: solto (1,13:1). Medido em `tests/test_visual.py`.
BORDA_DA_BARRA = "linha"


def cor_do_passo_sob_o_cursor(c: dict) -> str:
    """O azul do botão de passo sob o cursor: um tom MAIS ESCURO do mesmo.

    Clarear (o que se fez primeiro, em 22/10/2026) deixava o branco do rótulo
    em 4,2:1 no tema escuro; escurecer só aumenta o contraste dele."""
    return _mistura(c["marca_solida"], "#000000", 0.15)


def cor_da_bolinha(c: dict, estado: str) -> str:
    """A bolinha do navegador: âmbar se ocupado, verde se livre — da paleta
    do tema, porque desde 22/10/2026 a barra de cima é a cor da página."""
    # `ok` e não `acao_viva`: desde 28/10/2026 a barra mora na `janela`, e o
    # verde vivo dava 2,88:1 contra ela no tema claro (o piso é 3:1).
    return c["atencao"] if estado == "ocupado" else c["ok"]


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

    #: Raio dos cantos do botão (28/10/2026, repaginada).
    RAIO = 9

    def __init__(self, pai, texto="", papel="neutro", numero=None, **kw):
        if numero is not None:
            texto = f"{numero}.  {texto}"
        self._papel = papel
        self._img = None
        self._img_sob = None
        self._sob = False
        self._medida = None
        # A folga vira tamanho da IMAGEM (o texto vai por cima dela, centrado);
        # só o papel "link", que não tem fundo, segue usando padx/pady.
        self._folga_x = kw.pop("padx", px(14))
        self._folga_y = kw.pop("pady", px(7))
        kw.setdefault("relief", "flat")
        kw.setdefault("borderwidth", 0)
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("cursor", "hand2")
        kw.setdefault("font", FONTE_APOIO if papel == "link" else "TkDefaultFont")
        super().__init__(pai, text=texto, padx=0, pady=0, compound="center",
                         **kw)
        self.bind("<Enter>", self._entrou, add="+")
        self.bind("<Leave>", self._saiu, add="+")
        self.bind("<Configure>", self._redimensionou, add="+")
        _repintaveis.add(self)
        self.aplicar_cores(_estado["escuro"])

    def configure(self, cnf=None, **kw):                      # noqa: D102
        chaves = set(kw) | (set(cnf) if isinstance(cnf, dict) else set())
        r = super().configure(cnf, **kw)
        if chaves & {"state", "text", "font"}:
            self.aplicar_cores()
        return r

    config = configure

    def _entrou(self, _ev=None):
        self._sob = True
        self._mostrar()

    def _saiu(self, _ev=None):
        self._sob = False
        self._mostrar()

    def _mostrar(self):
        if self._img is None:
            return
        try:
            ligado = str(super().cget("state")) != "disabled"
            super().configure(image=self._img_sob if (self._sob and ligado)
                              else self._img)
        except tk.TclError:
            pass

    def _natural(self) -> tuple[int, int]:
        """Largura e altura do botão pelo texto e pela folga."""
        try:
            fonte = super().cget("font")
            texto = str(super().cget("text"))
            larg = int(self.tk.call("font", "measure", fonte, texto))
            alt = int(self.tk.call("font", "metrics", fonte, "-linespace"))
        except (tk.TclError, ValueError):
            larg, alt = 60, 16
        return larg + 2 * self._folga_x, alt + 2 * self._folga_y

    def _redimensionou(self, _ev=None):
        """Botão esticado pelo `pack(fill=...)`: a imagem acompanha."""
        try:
            tam = (self.winfo_width(), self.winfo_height())
        except tk.TclError:
            return
        if self._img is not None and tam != self._medida and min(tam) > 4:
            self.aplicar_cores()

    def aplicar_cores(self, escuro: bool | None = None):
        c = cores()
        try:
            desligado = str(super().cget("state")) == "disabled"
        except tk.TclError:
            return
        fora = _cor_atras(self.master)
        if self._papel == "link":
            try:
                super().configure(background=fora, foreground=c["marca"],
                                  activebackground=fora,
                                  activeforeground=c["marca"],
                                  disabledforeground=c["tenue"], image="",
                                  padx=self._folga_x, pady=self._folga_y)
            except tk.TclError:
                pass
            return
        borda = None
        if desligado:
            # O desligado é o mesmo lugar vazio qualquer que fosse a cor dele
            # ligado: o fundo do painel com a moldura em `BORDA_DESLIGADO`.
            frente, tras, aceso = c["tenue"], c["fundo"], c["fundo"]
            borda = c[BORDA_DESLIGADO]
        else:
            frente, tras, aceso = {
                "acao":   ("#FFFFFF", c["acao"], c["acao_ativo"]),
                # O passo era azul cheio; na repaginada (28/10/2026) virou
                # azul-claro com texto azul — um passo não pode pesar mais que
                # o "executar" verde da mesma tela.
                "passo":  (c["marca"], c["marca_fundo"], c["info_fundo"]),
                "neutro": (c["texto"], c["cartao"], c["cabecalho"]),
                "barra":  (c["barra_texto"], c["fundo"], c["cabecalho"]),
                "perigo": (c["erro"], c["cartao"], c["erro_fundo"]),
            }.get(self._papel, (c["texto"], c["cartao"], c["cabecalho"]))
            if self._papel in ("neutro", "perigo"):
                borda = c["borda"]
            elif self._papel == "barra":
                borda = c[BORDA_DA_BARRA]
        #: O que o botão pinta, para os testes medirem a cor que a TELA usa
        #: (com a imagem, o `background` do widget é a cor de fora).
        self.pintado = {"frente": frente, "tras": tras, "aceso": aceso,
                        "borda": borda}
        larg, alt = self._natural()
        try:
            real = (max(self.winfo_width(), larg), max(self.winfo_height(), alt))
        except tk.TclError:
            return
        if real[0] < 8 or not self.winfo_ismapped():
            real = (larg, alt)
        self._medida = real
        raio = px(self.RAIO)
        self._img = imagem_redonda(real[0], real[1], raio, tras, borda,
                                   fora=fora)
        self._img_sob = imagem_redonda(real[0], real[1], raio, aceso, borda,
                                       fora=fora)
        try:
            super().configure(width=larg, height=alt, background=fora,
                              activebackground=fora, foreground=frente,
                              activeforeground=frente,
                              disabledforeground=frente, highlightthickness=0)
        except tk.TclError:
            return
        self._mostrar()

    def papel(self, novo: str):
        """Troca o papel depois de criado (o botão que vira o principal)."""
        self._papel = novo
        self.aplicar_cores()


class Dica:
    """Balãozinho com o texto inteiro, ao parar o cursor em cima.

    Nasceu para o número da versão, quando a tela mostrava só "v2.0" e o
    número de build ficava no balão. Desde 14/09/2026 a tela mostra o número
    inteiro (`comprovantes_app._versao_na_tela`), e o balão serve às abas que
    o usam para explicar um botão.

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
                           highlightcolor=c["borda"], padx=px(8), pady=px(5))
        moldura.pack()
        ttk.Label(moldura, text=self.texto, style="Mini.TLabel").pack()
        try:
            top.update_idletasks()
            x = self.alvo.winfo_rootx()
            y = self.alvo.winfo_rooty() + self.alvo.winfo_height() + px(4)
            # Puxada para dentro da tela: a versão mora no canto direito da
            # barra, e o balão nasceria metade fora do monitor.
            x = min(x,
                    top.winfo_screenwidth() - top.winfo_reqwidth() - px(8))
            top.geometry(f"+{max(x, px(8))}+{y}")
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

    #: 5 px na escala de 100%. Passa pelo `px` nos dois usos abaixo: a 150%
    #: uma barra de 5 px ao lado de texto 1,5× maior deixa de ser "fina" e
    #: passa a ser "quase invisível".
    ALTURA = 5

    def __init__(self, pai, mode="determinate", maximum=100, value=0, **kw):
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("borderwidth", 0)
        super().__init__(pai, height=px(self.ALTURA), **kw)
        self.pack_propagate(False)
        self.grid_propagate(False)
        self._canvas = tk.Canvas(self, height=px(self.ALTURA),
                                 highlightthickness=0,
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
        self.pb.pack(fill="x", pady=px((5, 0)))
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
        larg, alt = px(self._folga(padding))
        # Cantos redondos desde 28/10/2026: a moldura fica na cor de quem
        # está atrás e o `FundoRedondo` desenha o cartão (cor + borda) atrás
        # do conteúdo. A folga mínima afasta o conteúdo dos cantos.
        moldura = tk.Frame(pai, background=_cor_atras(pai),
                           highlightthickness=0, borderwidth=0,
                           padx=max(larg, px(8)), pady=max(alt, px(8)))
        self.moldura = moldura
        self._fundo = FundoRedondo(moldura, px(14), "cartao", "borda")
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
            if isinstance(alvo, (Cartao, AreaRolavel)):
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
        linha.pack(fill="x", pady=px((0, 9)))
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
            bolha.pack(side="left", padx=px((0, 9)))
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
        self.filete.pack(fill="x", pady=px((0, 11)))

    def titulo(self, texto: str):
        if self.cabecalho is not None:
            self.lbl_titulo.configure(text=texto)

    def aplicar_cores(self, escuro: bool | None = None):
        c = cores()
        try:
            self.configure(background=c["cartao"])
            if self.cabecalho is not None:
                self.cabecalho.configure(background=c["cartao"])
                self.filete.configure(background=c["borda"])
                if self._bolha is not None:
                    self._bolha.configure(background=c["cartao"])
                    self._bolha.itemconfigure("bolha",
                                              fill=c["marca_solida"])
        except tk.TclError:
            pass


#: O menor `wraplength` do subtítulo do cabeçalho: antes do layout o
#: `<Configure>` chega com largura 1, e quebrar em 1 px faria uma letra por
#: linha por um instante.
APOIO_MINIMO = 200


def largura_do_apoio(largura: int, teto: int) -> int:
    """O `wraplength` do subtítulo: a largura que sobrou ao lado dos botões,
    nunca acima do `teto` (linha legível) nem abaixo de `APOIO_MINIMO`."""
    return max(APOIO_MINIMO, min(int(largura), int(teto)))


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

    SEM FAIXA PRÓPRIA (22/10/2026, pedido do dono). As abas são `ttk.Frame`
    sem estilo, e o fundo padrão do ttk neste app é o do CARTÃO; o cabeçalho,
    no fundo do painel, aparecia como um bloco de outra cor com uma moldura do
    cartão em volta (as margens do `pack`). Agora o cabeçalho passa a aba que
    o recebe para o fundo do painel — só quando ela não escolheu estilo
    nenhum —, e o que separa o cabeçalho dos cartões é um filete de 1 px
    (`self.filete`, estilo `Filete.TFrame`), não um bloco de cor.
    """

    def __init__(self, pai, titulo: str, apoio: str = "", trilha: str = "",
                 **kw):
        kw.setdefault("style", "Fundo.TFrame")
        # A aba inteira no fundo do painel: é o que tira a moldura em volta
        # do cabeçalho. Só `ttk.Frame` sem estilo — um diálogo que já pôs
        # `Fundo.TFrame`, ou quem escolheu outro estilo, fica como está.
        if isinstance(pai, ttk.Frame):
            try:
                if not str(pai.cget("style")):
                    pai.configure(style="Fundo.TFrame")
            except tk.TclError:
                pass
        super().__init__(pai, **kw)
        topo = ttk.Frame(self, style="Fundo.TFrame")
        topo.pack(side="top", fill="x")
        #: O filete que fecha o cabeçalho, de ponta a ponta (título e botões).
        self.filete = ttk.Frame(self, style="Filete.TFrame", height=1)
        self.filete.pack(side="top", fill="x", pady=px((14, 0)))
        #: Os botões da tela. `anchor="e"` para eles ficarem alinhados pelo
        #: alto do título, e não centralizados contra a linha de apoio.
        #: Empacotados ANTES do texto (galeria 1280x800, 22/10/2026): o `pack`
        #: reparte o espaço na ordem, e o subtítulo longo, empacotado primeiro,
        #: levava a largura toda e cortava o botão ("Baixar comprova"). Assim
        #: as ações levam o que pedem e o texto fica com o resto.
        self.acoes = ttk.Frame(topo, style="Fundo.TFrame")
        self.acoes.pack(side="right", anchor="ne", padx=px((14, 0)))
        esquerda = ttk.Frame(topo, style="Fundo.TFrame")
        esquerda.pack(side="left", fill="x", expand=True)
        if trilha:
            ttk.Label(esquerda, text=trilha, style="Trilha.TLabel"
                      ).pack(anchor="w", pady=px((0, 2)))
        ttk.Label(esquerda, text=titulo, style="FundoTitulo.TLabel"
                  ).pack(anchor="w")
        self.lbl_apoio = None
        if apoio:
            teto = px(820)
            self.lbl_apoio = ttk.Label(esquerda, text=apoio,
                                       style="FundoApoio.TLabel",
                                       wraplength=teto, justify="left")
            self.lbl_apoio.pack(anchor="w", pady=px((3, 0)))
            lbl = self.lbl_apoio

            # O subtítulo quebra na largura que SOBROU ao lado dos botões
            # (com o teto de antes, para a linha continuar legível na tela
            # larga), em vez de pedir 820 px e empurrar os botões.
            def _quebrar(e):
                alvo = largura_do_apoio(e.width, teto)
                if str(lbl.cget("wraplength")) != str(alvo):
                    lbl.configure(wraplength=alvo)
            esquerda.bind("<Configure>", _quebrar, add="+")
        #: Espaço abaixo da linha de apoio, para quem quiser pendurar algo no
        #: cabeçalho. Nasce vazio e não ocupa lugar até alguém empacotá-lo.
        self.rodape = ttk.Frame(esquerda, style="Fundo.TFrame")


# ------------------------------------------------------------ área que rola
def passos_da_roda(delta: int) -> int:
    """Quantos passos rolar num `<MouseWheel>`.

    O Windows manda múltiplos de 120 por dente da roda; o touchpad manda
    menos, e `delta // 120` daria 0 para cima e -1 para baixo — a tela
    andaria num sentido só."""
    passos = -int(delta / 120)
    if passos == 0 and delta:
        passos = -1 if delta > 0 else 1
    return passos


def quadros_da_rolagem(distancia: int, n: int) -> list[int]:
    """Reparte `distancia` pixels em até `n` quadros que desaceleram (ease-out).

    O primeiro quadro anda mais, o último menos; a soma é EXATAMENTE
    `distancia` (com o sinal dela) e todo quadro é inteiro e não nulo, então
    a animação nunca gasta quadro parado."""
    distancia = int(distancia)
    if distancia == 0 or n < 1:
        return []
    sinal = 1 if distancia > 0 else -1
    total = abs(distancia)
    n = min(int(n), total)
    pesos = [n - i for i in range(n)]
    soma = sum(pesos)
    quadros, acum, dado = [], 0, 0
    for peso in pesos:
        acum += peso
        alvo = (total * acum + soma // 2) // soma
        quadros.append(sinal * (alvo - dado))
        dado = alvo
    return [q for q in quadros if q]


def _tem_o_que_rolar(widget) -> bool:
    """O conteúdo deste widget passa do que ele mostra?"""
    try:
        lo, hi = widget.yview()
    except (tk.TclError, TypeError, ValueError):
        return False
    return float(lo) > 0.0 or float(hi) < 1.0


def _area_de(widget) -> "AreaRolavel | None":
    """A área rolável mais interna que contém `widget`, se houver.

    Para no `Toplevel`. No tkinter o `master` de uma janela é quem a CRIOU, e
    o calendário do `CampoData` tem como pai lógico um campo que mora num
    cartão da área: sem esta parada, a roda sobre o calendário rolaria a aba
    de trás, e o foco dentro de um diálogo mexeria na rolagem dela."""
    while widget is not None:
        if isinstance(widget, AreaRolavel):
            return widget
        if isinstance(widget, tk.Toplevel):
            return None
        widget = getattr(widget, "master", None)
    return None


def _roda_na_area(ev):
    """A roda do mouse, para o app inteiro.

    Chega por `bind_all`, então roda DEPOIS da ligação da classe do widget sob
    o ponteiro. Quem já rola sozinho (Text, Listbox, Treeview, a própria
    barra) e tem o que rolar fica com o evento; o resto sobe até a área. Uma
    lista em Canvas dentro da área (as contas da Remessa e do Relatório) não
    tem ligação de classe nenhuma, e rola aqui — antes ela não rolava.
    Fora de uma área não se faz nada: diálogos cuidam da própria roda.

    Quem decide é o widget sob o PONTEIRO, e não o que recebeu o evento. No
    Windows os dois coincidem (o Tk entrega a roda à janela sob o cursor),
    mas o evento é do mesmo tipo que a tecla, e há caminho em que ele vai a
    quem tem o foco — aí o campo de data do alto rolaria a página inteira
    enquanto o ponteiro está sobre o Registro."""
    w = ev.widget
    if not isinstance(w, tk.Misc):
        return None                 # popdown do combobox: nome sem objeto
    try:
        sob = w.winfo_containing(ev.x_root, ev.y_root)
    except (tk.TclError, KeyError):
        sob = None                  # janela que o tkinter não conhece
    if sob is not None:
        w = sob
    interno = None
    while w is not None:
        if isinstance(w, tk.Toplevel):
            return None             # diálogo cuida da própria roda (`_area_de`)
        if isinstance(w, AreaRolavel):
            if interno is not None:
                interno.yview_scroll(passos_da_roda(ev.delta), "units")
            else:
                w.rolar(passos_da_roda(ev.delta))
            return None
        if isinstance(w, ttk.Scrollbar):
            return None             # a TScrollbar tem roda própria
        if isinstance(w, (tk.Text, tk.Listbox, ttk.Treeview)):
            if _tem_o_que_rolar(w):
                return None         # a ligação da classe já rolou
        elif (interno is None and isinstance(w, tk.Canvas)
              and str(w.cget("yscrollcommand")) and _tem_o_que_rolar(w)):
            interno = w
        w = getattr(w, "master", None)
    return None


#: O último widget que recebeu foco dentro de uma área, e a hora do último
#: clique do mouse. Ver `_foco_na_area`.
_foco_anterior = {"nome": "", "clique": 0.0}

#: Foco que chega até este tempo depois de um clique veio do MOUSE.
CLIQUE_S = 0.4


def _clique_global(_ev):
    _foco_anterior["clique"] = time.monotonic()


def _foco_na_area(ev):
    """Quem recebe o foco pelo TECLADO tem de aparecer na tela.

    Sem isto, o Tab andava pelos campos da parte rolada e o cursor sumia
    embaixo do Registro. Dois focos não contam. O que VOLTA ao mesmo widget é
    o Windows devolvendo o foco depois do Alt+Tab, e rolar ali puxaria de
    volta ao topo a lista que a pessoa tinha acabado de descer para ler. E o
    que vem de um CLIQUE: o que se clica já está sob o ponteiro, e a página
    saltar debaixo do mouse no meio do clique numa tabela é pior do que meia
    tabela à vista."""
    w = ev.widget
    if not isinstance(w, tk.Misc):
        return None
    nome = str(w)
    if nome == _foco_anterior["nome"]:
        return None
    _foco_anterior["nome"] = nome
    if time.monotonic() - _foco_anterior["clique"] < CLIQUE_S:
        return None
    area = _area_de(w)
    if area is not None and w is not area:
        area.mostrar(w)
    return None


def _instalar_roda(widget) -> None:
    """Liga a roda e o foco das áreas, UMA vez por intérprete do Tcl.

    E desliga a roda do `TCombobox`. O Tk liga a roda ao combobox
    (`ttk::bindMouseWheel TCombobox`), e com a tela rolando isso vira armadilha:
    quem desce a página com o ponteiro passando por "Tipo" ou "Forma" troca o
    valor em silêncio. Foi assim que uma conta de pessoa física apareceu
    escolhida para uma SPE na janela de contas novas (11/09/2026) — lá o
    conserto foi local; aqui vale para todo menu do app. A lista aberta do
    combobox continua rolando: ela é outro widget."""
    try:
        if "_roda_na_area" in str(widget.bind_all("<MouseWheel>")):
            return
        widget.bind_all("<MouseWheel>", _roda_na_area, add="+")
        widget.bind_all("<FocusIn>", _foco_na_area, add="+")
        widget.bind_all("<ButtonPress>", _clique_global, add="+")
        widget.unbind_class("TCombobox", "<MouseWheel>")
    except tk.TclError:
        pass


class AreaRolavel(tk.Frame):
    """Um pedaço da tela que ROLA quando o que tem dentro não cabe.

    O defeito de 11/09/2026: no Anexar, a 1920x1080 com a escala do Windows a
    125%, os três cartões numerados já ocupavam a janela inteira; a barra de
    ação saía cortada no pé e o Registro não aparecia — sumido, não
    espremido. O `_reservar_o_pe` de 03/09 não alcançava o caso, porque ali
    não havia lista para ceder espaço: TODO o conteúdo era de altura fixa.

    A saída é a de qualquer tela que tem mais do que cabe: o meio rola, as
    pontas não. Cada aba passa a ser três faixas:

      cabeçalho   fixo no alto — os botões principais estão nele;
      esta área   os cartões numerados; rola quando não cabem;
      doca        a barra de ação e o Registro, presos no pé (`encaixar`).

    Como o `Cartao`, são DOIS objetos: `self` é o INTERIOR, onde a aba
    empacota os cartões como sempre empacotou (`Cartao(corpo, ...)`), e
    `self.moldura` é o que entra no `pack` da aba. A regra do Tk que obriga é
    a do recorte: um widget só é recortado pela janela-PAI, então os cartões
    precisam ser filhos do interior, e o interior filho do Canvas que rola.

    O interior tem sempre a largura do Canvas e, quando sobra tela, também a
    altura dele — é o que deixa uma lista com `expand` dentro da área crescer
    com a janela. A barra aparece só quando há o que rolar, SOBRE a margem
    direita dos cartões: se ela tomasse largura, o texto quebraria de outro
    jeito ao aparecer, a altura mudaria, e ela podia sumir e voltar em laço.
    """

    #: Pixels de um passo de rolagem; um dente da roda anda três passos.
    PASSO = 20
    #: A cada quanto a área confere se o conteúdo mudou de tamanho. O Tk não
    #: avisa quando o tamanho PEDIDO do interior muda (ele está com altura
    #: fixa dentro do Canvas); os `<Configure>` dos filhos pegam quase tudo
    #: na hora, e esta conferência pega o resto — só enquanto a área está na
    #: tela, então as abas escondidas não custam nada.
    VIGIA_MS = 250
    #: Rolagem suave: cada dente vira um deslocamento em pixels, gasto em
    #: `QUADROS` passos de `QUADRO_MS` (~16 ms, 60 quadros por segundo).
    QUADROS = 6
    QUADRO_MS = 16

    def __init__(self, pai, fundo: str = "fundo", **kw):
        c = cores()
        self._fundo = fundo
        self._morrendo = False
        self._fila: list[int] = []
        self._anim = None
        self._medida = None
        self._vigiados: set[str] = set()
        self._barra_visivel = False
        self._vigia = None
        self.moldura = tk.Frame(pai, background=c[fundo],
                                highlightthickness=0, borderwidth=0)
        self.canvas = tk.Canvas(self.moldura, background=c[fundo],
                                highlightthickness=0, borderwidth=0,
                                width=1, height=1,
                                yscrollincrement=1)
        self.canvas.pack(fill="both", expand=True)
        self.barra = ttk.Scrollbar(self.moldura, orient="vertical",
                                   command=self._barra_pediu)
        self.canvas.configure(yscrollcommand=self._barra_mudou)
        kw.setdefault("background", c[fundo])
        kw.setdefault("highlightthickness", 0)
        kw.setdefault("borderwidth", 0)
        super().__init__(self.canvas, **kw)
        self._janela = self.canvas.create_window(0, 0, window=self,
                                                 anchor="nw")
        self.canvas.bind("<Configure>", self.reajustar, add="+")
        self.bind("<Configure>", self.reajustar, add="+")
        _repintaveis.add(self)
        _instalar_roda(self)
        self._vigia = self.after(self.VIGIA_MS, self._vigiar)

    # ---------------------------------------------- geometria vai à moldura
    def pack(self, **kw):
        self.moldura.pack(**Cartao._vizinhos(kw))
        return self

    def pack_configure(self, **kw):
        self.moldura.pack_configure(**Cartao._vizinhos(kw))

    def pack_forget(self):
        self.moldura.pack_forget()

    def pack_info(self):
        return self.moldura.pack_info()

    def grid(self, **kw):
        self.moldura.grid(**kw)
        return self

    def grid_forget(self):
        self.moldura.grid_forget()

    def place(self, **kw):
        self.moldura.place(**kw)
        return self

    def place_forget(self):
        self.moldura.place_forget()

    def destroy(self):
        # A mesma trava do `Cartao.destroy`: a moldura destrói o Canvas, que
        # destrói este interior, que chamaria a moldura de novo.
        if self._morrendo:
            tk.Frame.destroy(self)
            return
        self._morrendo = True
        self._parar_animacao()
        if self._vigia is not None:
            try:
                self.after_cancel(self._vigia)
            except tk.TclError:
                pass
        self.moldura.destroy()

    # ------------------------------------------------------------- montagem
    def encaixar(self, *doca, padx=0, pady=0):
        """Monta a aba: esta área no meio, e `doca` presa no pé.

        `doca` vem na ordem em que aparece, de cima para baixo — em quase toda
        aba `(acao, self.reg)`. Chamar UMA vez, no fim do `_build`, depois do
        `registro_elastico`.

        A ordem do `pack` é a decisão inteira. O `pack` atende os filhos NA
        ORDEM em que foram empacotados, e quem vem por último fica com o que
        sobrou — por isso a doca é reempacotada `side="bottom"` ANTES da área,
        e a área entra por último: ela é a única que sabe encolher sem perder
        nada, porque rola. O cabeçalho, empacotado antes de tudo, fica onde
        estava."""
        for w in reversed(doca):
            info = w.pack_info()
            info.pop("in", None)
            info["side"] = "bottom"
            w.pack_forget()
            w.pack(**info)
        self.pack(side="top", fill="both", expand=True, padx=padx, pady=pady)
        return self

    # --------------------------------------------------------------- medida
    def reajustar(self, _ev=None):
        """Recalcula o tamanho do interior e a região que rola."""
        if self._morrendo:
            return
        try:
            larg = self.canvas.winfo_width()
            alt = self.canvas.winfo_height()
            req_l = self.winfo_reqwidth()
            req_a = self.winfo_reqheight()
        except tk.TclError:
            return
        self._vigiar_filhos()
        altura = max(alt, req_a, 1)
        medida = (larg, altura, req_l, req_a)
        if medida != self._medida:
            self._medida = medida
            # Altura FIXA só quando há sobra para esticar; no resto, 0 — que
            # no Canvas quer dizer "a que o interior pedir". A diferença é o
            # que faz a área perceber um cartão crescendo: com altura fixa
            # igual à pedida, o último cartão cresce só no PEDIDO (o `pack`
            # do interior não tem mais cavidade para lhe dar), ninguém muda
            # de tamanho e nenhum `<Configure>` dispara — foi o Anexar com as
            # contas recém-carregadas, cortado até a próxima conferência.
            try:
                self.canvas.itemconfigure(self._janela, width=max(larg, 1),
                                          height=alt if alt > req_a else 0)
                # `width`/`height` do Canvas são o que a área PEDE à aba: o
                # tamanho natural do conteúdo. Com isso a aba continua pedindo
                # à janela o mesmo que pedia antes de existir rolagem.
                self.canvas.configure(scrollregion=(0, 0, max(larg, 1), altura),
                                      width=req_l, height=req_a)
            except tk.TclError:
                return
        self._pedir_sobra()

    def _pedir_sobra(self):
        """A área só pede a SOBRA da tela quando tem dentro quem sabe usá-la.

        Com uma lista elástica dentro (a de "A lançar" nos Aportes, a das
        rotinas no Início), a sobra faz a lista crescer. Sem nenhuma, a sobra
        seria só fundo vazio dentro da área — e ela é tirada do Registro, que
        é o outro elástico da aba e o único que tem o que mostrar nela."""
        try:
            self.moldura.pack_info()
        except tk.TclError:
            return                   # não é o `pack` que a põe na tela
        quer = any(_elastico(w) for w in self.pack_slaves())
        if _elastico(self.moldura) != quer:
            try:
                self.moldura.pack_configure(expand=quer)
            except tk.TclError:
                pass

    def _vigiar_filhos(self):
        for w in self.pack_slaves() + self.grid_slaves():
            nome = str(w)
            if nome not in self._vigiados:
                self._vigiados.add(nome)
                w.bind("<Configure>", self.reajustar, add="+")

    def _vigiar(self):
        self._vigia = None
        if self._morrendo:
            return
        try:
            if self.winfo_ismapped() and (
                    self._medida is None
                    or (self.winfo_reqwidth(), self.winfo_reqheight())
                    != self._medida[2:]):
                self.reajustar()
            self._vigia = self.after(self.VIGIA_MS, self._vigiar)
        except tk.TclError:
            pass                     # área destruída entre duas conferências

    # -------------------------------------------------------------- rolagem
    def _barra_mudou(self, lo, hi):
        lo, hi = float(lo), float(hi)
        precisa = lo > 0.0 or hi < 1.0
        try:
            if precisa and not self._barra_visivel:
                self.barra.place(relx=1.0, rely=0.0, relheight=1.0,
                                 anchor="ne")
                self.barra.lift()
            elif not precisa and self._barra_visivel:
                self.barra.place_forget()
            self._barra_visivel = precisa
            self.barra.set(lo, hi)
        except tk.TclError:
            pass

    def rola(self) -> bool:
        """Tem conteúdo fora da vista agora?"""
        return _tem_o_que_rolar(self.canvas)

    def _parar_animacao(self):
        """Descarta o que faltava andar e cancela o quadro pendente."""
        self._fila = []
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except tk.TclError:
                pass
            self._anim = None

    def _barra_pediu(self, *args):
        """A barra mexeu: a animação em curso perde a vez. O Canvas anda 1 px
        por unidade (para a animação ser fina); a seta da barra continua
        andando um PASSO."""
        self._parar_animacao()
        if len(args) == 3 and args[0] == "scroll" and args[2] == "units":
            self.canvas.yview_scroll(int(args[1]) * px(self.PASSO), "units")
        else:
            self.canvas.yview(*args)

    def rolar(self, passos: int):
        """Soma `passos` dentes ao que falta andar e (re)divide em quadros.

        Dentes seguidos NÃO reiniciam a animação: a distância nova entra na
        conta e o conjunto desacelera junto. A distância por dente é a de
        sempre: 3 passos de `PASSO`."""
        if not self.rola():
            return
        faltava = sum(self._fila)
        distancia = faltava + int(passos) * 3 * px(self.PASSO)
        if self._anim is not None:
            try:
                self.after_cancel(self._anim)
            except tk.TclError:
                pass
            self._anim = None
        self._fila = quadros_da_rolagem(distancia, self.QUADROS)
        self._quadro()

    def _quadro(self):
        self._anim = None
        if self._morrendo or not self._fila:
            self._fila = []
            return
        passo = self._fila.pop(0)
        try:
            antes = self.canvas.canvasy(0)
            self.canvas.yview_scroll(passo, "units")
            if self.canvas.canvasy(0) == antes:     # bateu no topo ou no fim
                self._fila = []
                return
            if self._fila:
                self._anim = self.after(self.QUADRO_MS, self._quadro)
        except tk.TclError:
            self._fila = []

    def mostrar(self, widget):
        """Rola o mínimo para `widget` ficar inteiro à vista."""
        if not self.rola():
            return
        self._parar_animacao()
        try:
            topo = widget.winfo_rooty() - self.winfo_rooty()
            fim = topo + widget.winfo_height()
            vista = self.canvas.canvasy(0)
            alt = self.canvas.winfo_height()
            total = max(self.winfo_height(), 1)
        except tk.TclError:
            return
        folga = px(16)
        if topo - folga < vista:
            self.canvas.yview_moveto(max(topo - folga, 0) / total)
        elif fim + folga > vista + alt:
            self.canvas.yview_moveto(min(fim + folga - alt, total - alt)
                                     / total)

    def aplicar_cores(self, escuro: bool | None = None):
        cor = cores()[self._fundo]
        try:
            self.configure(background=cor)
            self.moldura.configure(background=cor)
            self.canvas.configure(background=cor)
        except tk.TclError:
            pass


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
                  padx=px(8), pady=px(2))
        b.pack(side="left", padx=px((10, 0)))
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
                  ).pack(anchor="w", pady=px((0, 3)))
        self.widget = fabrica(self)
        self.widget.pack(anchor="w", fill="x")


# ------------------------------------------------------- moldura da janela
# A barra do topo (na cor da página desde 22/10/2026) e o menu da esquerda. Moram aqui pelo mesmo
# motivo do resto: são `tk.Frame` clássicos (o ttk não deixa pintar), e o
# `comprovantes_app.py` não pode passar a ser o segundo lugar do app onde
# existe um `#` seguido de seis dígitos.


class BarraTopo(tk.Frame):
    """A faixa acima de tudo, na cor da página desde 22/10/2026 (antes azul).

    Ela responde três perguntas que antes moravam em cantos diferentes da
    janela, ou em canto nenhum:

      onde estou      o logotipo, à esquerda;
      para onde vou   o "ir para uma tela", no meio;
      o app está      o estado do navegador, à direita — que era uma linha
      livre?          cinza no PÉ da barra lateral, o ponto mais distante do
                      olho de quem clica numa aba lá em cima.

    **O campo promete o que entrega, e essa é a mudança de 02/09/2026.** Ele
    dizia "Buscar lançamento, empresa ou conta…" e o Enter ali só devolvia o
    cursor ao primeiro campo da aba aberta: procurar lançamento pede um índice
    que ninguém tem, e um campo que promete três coisas e não faz nenhuma
    ensina a não usar campo nenhum. A promessa encolheu até o tamanho do que
    dá para cumprir hoje sem rede e sem ERP — pular para uma das telas do menu.

    Digitar filtra os nomes das telas (sem acento, sem caixa, por pedaço em
    qualquer posição: `util.filtrar`), ↑/↓ andam pela lista, Enter pula para a
    que está realçada e Esc devolve o foco a quem o tinha. Quem sabe o nome e o
    comando de cada tela é a janela, e ela só descobre isso depois de montar o
    menu — daí `definir_telas`, chamada de lá.

    O PRÓXIMO passo, se for pedido: uma paleta de comandos de verdade, sobre
    `widgets.atividades()` — as rotinas já registram o que fizeram ali, com aba,
    evento e números, e isso é um índice local, sem rede. "Remessa de ontem" e
    "último relatório da Buritis" saem dele. Nada disso é assunto desta função:
    ela leva a pessoa até a TELA, e essa é a promessa inteira.

    A lista é um `Toplevel` sem barra de título e **sem foco nenhum**, pelo
    mesmo motivo do calendário do `CampoData`: quem está digitando continua
    digitando: o foco nunca sai do campo, e é por isso que ↑/↓/Enter/Esc são
    ligados ao `Entry` e não à lista.
    """

    #: 52 px na escala de 100%. É a medida que mais estragava a 150%: a faixa
    #: ficava do mesmo tamanho enquanto o logotipo dentro dela crescia 50%, e
    #: o texto saía cortado por baixo, encostado no campo de busca.
    ALTURA = 52

    #: O que o campo diz que faz. Vira constante para o teste poder afirmar
    #: que a promessa e a entrega são a mesma coisa.
    DICA = "Ir para uma tela…  (Ctrl+K)"

    def __init__(self, pai, marca: str = "mais controle · comprovantes",
                 dica: str = "", **kw):
        c = cores()
        kw.setdefault("background", c["marca_barra"])
        kw.setdefault("highlightthickness", 0)
        # Largura PEDIDA (o `pack_propagate(False)` zera o que os filhos
        # pediriam): sem ela, numa janela que nasce do tamanho do conteúdo, a
        # barra pedia 1 px e a pílula da busca ficava sem espaço — o campo
        # desmapeava e não recebia mais o foco.
        kw.setdefault("width", px(960))
        super().__init__(pai, height=px(self.ALTURA), **kw)
        self.pack_propagate(False)
        self._dica = dica or self.DICA
        #: (nome da tela, o que fazer para abri-la). Preenchido por
        #: `definir_telas`; até lá o campo não tem para onde ir e não abre lista.
        self._telas: list[tuple[str, object]] = []
        self._achados: list[tuple[str, object]] = []
        self._realce = 0
        self._popup = None
        self._moldura = None
        self._linhas: list = []
        self._fora = None
        #: Quem estava com o foco quando o Ctrl+K o roubou. É para lá que o Esc
        #: o devolve — quem apertou Ctrl+K sem querer volta ao campo que estava
        #: preenchendo, e não a um lugar qualquer da tela.
        self._voltar_para = None

        self.esquerda = tk.Frame(self, background=c["marca_barra"])
        self.esquerda.pack(side="left", fill="y", padx=px((18, 0)))
        self.lbl_marca = ttk.Label(self.esquerda, text=marca,
                                   style="Marca.TLabel")
        self.lbl_marca.pack(side="left", pady=px(14))

        self.direita = tk.Frame(self, background=c["marca_barra"])
        self.direita.pack(side="right", fill="y", padx=px((0, 18)))

        # O centro entra POR ÚLTIMO, e é o único com `expand`: assim ele fica
        # com a sobra da largura, e o logotipo e o canto direito ficam com o
        # que precisam. Empacotado antes, ele empurrava o canto direito para
        # fora da janela em telas estreitas.
        self.centro = tk.Frame(self, background=c["marca_barra"])
        self.centro.pack(side="left", fill="both", expand=True, padx=px(24))
        # A busca é uma PÍLULA (protótipo de 28/10/2026): o `FundoRedondo`
        # desenha a cápsula na cor do painel, com borda, e o campo de texto
        # mora dentro dela, recuado das pontas.
        self.caixa_busca = tk.Frame(self.centro, background=c["marca_barra"],
                                    highlightthickness=0)
        self.caixa_busca.pack(fill="x", pady=px(10))
        FundoRedondo(self.caixa_busca, px(40), "fundo", "borda",
                     fora="marca_barra")
        self.busca = tk.Entry(self.caixa_busca, relief="flat", borderwidth=0,
                              highlightthickness=0, font="TkDefaultFont")
        self.busca.pack(fill="x", padx=px(18), pady=px(8))
        self._vazia = True
        self.busca.bind("<FocusIn>", self._entrou)
        self.busca.bind("<FocusOut>", self._saiu)
        self.busca.bind("<KeyRelease>", self._ao_digitar)
        self.busca.bind("<Return>", self._ir)
        self.busca.bind("<Escape>", self._desistir)
        self.busca.bind("<Down>", lambda _e: self._mover(1))
        self.busca.bind("<Up>", lambda _e: self._mover(-1))

        _repintaveis.add(self)
        self.aplicar_cores(_estado["escuro"])
        self._mostrar_dica()

    # ------------------------------------------------------------ o campo
    def definir_telas(self, pares) -> None:
        """Os nomes das telas e o que fazer com cada uma: (texto, comando).

        Quem chama é o `comprovantes_app`, DEPOIS de montar o menu, e o comando
        que ele passa é o `acionar` do próprio `ItemMenu` — o mesmíssimo
        caminho do clique. Um caminho só, pelo motivo de sempre: com dois,
        existiria a chance de a busca abrir uma tela e o clique abrir outra.

        Como a lista sai do menu já montado, ela também já vem filtrada pelo
        PAPEL de quem entrou: a busca não leva ninguém a uma tela que o menu
        dessa pessoa não mostra."""
        self._telas = [(str(texto), comando) for texto, comando in pares]

    def _mostrar_dica(self):
        self._vazia = True
        self.busca.delete(0, "end")
        self.busca.insert(0, self._dica)
        self.busca.configure(foreground=cores()["marca_sub"])

    def _entrou(self, _ev=None):
        if self._vazia:
            self.busca.delete(0, "end")
            self.busca.configure(foreground=cores()["barra_texto"])
            self._vazia = False

    def _saiu(self, _ev=None):
        if not self.busca.get().strip():
            self._mostrar_dica()

    def limpar(self):
        """Apaga o que se digitou e devolve o foco a quem o tinha.

        É o que o Esc faz. Devolver o foco importa mais do que parece: o Ctrl+K
        vale com o foco em qualquer lugar, inclusive no meio de um campo de
        data pela metade — desistir tem de deixar a pessoa onde ela estava, e
        não largá-la numa barra azul."""
        self._fechar_lista()
        self._mostrar_dica()
        voltar, self._voltar_para = self._voltar_para, None
        try:
            if voltar is not None and voltar.winfo_exists():
                voltar.focus_set()
                return
        except tk.TclError:
            pass
        self.focus_set()

    def _desistir(self, _ev=None):
        self.limpar()
        return "break"

    def focar_busca(self, _ev=None):
        """Ctrl+K: o foco vem para cá, e a lista das telas abre inteira.

        Inteira e não vazia: filtro que esconde tudo enquanto o campo está em
        branco é pior do que não ter filtro (a mesma regra do
        `util.filtrar`) — e aqui a lista completa é o próprio menu, dito de
        outro jeito, para quem não quer tirar a mão do teclado."""
        try:
            anterior = self.busca.focus_get()
        except (KeyError, tk.TclError):
            anterior = None
        if anterior is not None and str(anterior) != str(self.busca):
            self._voltar_para = anterior
        self.busca.focus_set()
        self._entrou()
        self._filtrar()
        return "break"

    # ------------------------------------------------------------- a lista
    #: Teclas que NÃO são digitação: filtrar nelas remontaria a lista
    #: justamente enquanto a pessoa anda por ela. Mesma ressalva do
    #: `ComboBusca._ao_digitar`.
    _NAO_E_DIGITAR = ("Up", "Down", "Return", "Escape", "Tab", "Shift_L",
                      "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R")

    def _ao_digitar(self, ev=None):
        if ev is not None and ev.keysym in self._NAO_E_DIGITAR:
            return
        self._filtrar()

    def _filtrar(self):
        """Refaz a lista a partir do que está escrito. Sempre da lista INTEIRA:
        filtrar sobre o resultado anterior só a encolheria, e apagar o que se
        digitou não a traria de volta."""
        if not self._telas:
            self._fechar_lista()
            return
        termo = "" if self._vazia else self.busca.get()
        self._achados = util.filtrar(self._telas, termo, chave=lambda p: p[0])
        self._realce = 0
        self._desenhar_lista()

    def _mover(self, passo: int):
        if self._achados:
            self._realce = (self._realce + passo) % len(self._achados)
            self._pintar_realce()
        return "break"

    def _escolher(self, indice: int):
        self._realce = indice
        self._ir()

    def _ir(self, _ev=None):
        """Enter: pula para a tela realçada — e, sem nenhuma que bata, NADA.

        Não mover o foco é a resposta certa para o texto que não acha ninguém:
        levar o cursor para "algum lugar" seria indistinguível de ter
        encontrado a tela errada."""
        if not self._achados or not 0 <= self._realce < len(self._achados):
            return "break"
        comando = self._achados[self._realce][1]
        self._fechar_lista()
        self._mostrar_dica()
        # Daqui em diante quem manda no foco é a tela que abriu (o
        # `focar_primeiro_campo` que o `mostrar` agenda), e não o Esc.
        self._voltar_para = None
        if comando:
            comando()
        return "break"

    def _desenhar_lista(self):
        c = cores()
        if self._popup is None:
            top = tk.Toplevel(self)
            top.withdraw()                   # posiciona antes de aparecer
            top.overrideredirect(True)       # sem barra de título e sem foco
            top.transient(self.winfo_toplevel())
            try:
                top.attributes("-topmost", True)
            except tk.TclError:
                pass
            self._popup = top
            self._moldura = tk.Frame(top, highlightthickness=1)
            self._moldura.pack(fill="both", expand=True)
            # Clique fora fecha, e o bind vai no toplevel do APP: o clique que
            # interessa é o que acontece longe daqui, e esse nunca chega à
            # lista. `add="+"` para não derrubar quem já usa o <Button-1> da
            # janela — o calendário do `CampoData`, por exemplo.
            self._fora = self.winfo_toplevel().bind("<Button-1>",
                                                    self._clique_fora, add="+")
        self._moldura.configure(background=c["cartao"],
                                highlightbackground=c["borda"],
                                highlightcolor=c["borda"])
        for w in self._moldura.winfo_children():
            w.destroy()
        self._linhas = []
        if not self._achados:
            # Dizer que não achou, em vez de sumir com a lista: campo que não
            # responde a nada parece travado, e a pessoa fica tentando de novo.
            tk.Label(self._moldura, text="Nenhuma tela com esse nome.",
                     background=c["cartao"], foreground=c["tenue"],
                     font=FONTE_APOIO, anchor="w", padx=px(10), pady=px(6)
                     ).pack(fill="x")
        for i, (texto, _cmd) in enumerate(self._achados):
            lin = tk.Label(self._moldura, text=texto, anchor="w", padx=px(10),
                           pady=px(4), cursor="hand2")
            lin.pack(fill="x")
            lin.bind("<Button-1>", lambda _e, n=i: self._escolher(n))
            lin.bind("<Enter>", lambda _e, n=i: self._realcar(n))
            self._linhas.append(lin)
        self._pintar_realce()
        self._posicionar()

    def _realcar(self, indice: int):
        """O cursor por cima realça a mesma linha que ↑/↓ realçam: o mouse e o
        teclado apontam para o mesmo lugar, e o Enter sempre abre o que está
        destacado."""
        if self._realce != indice:
            self._realce = indice
            self._pintar_realce()

    def _pintar_realce(self):
        c = cores()
        for i, lin in enumerate(self._linhas):
            marcada = i == self._realce
            try:
                lin.configure(
                    background=c["marca_fundo"] if marcada else c["cartao"],
                    foreground=c["marca"] if marcada else c["texto"])
            except tk.TclError:
                return

    def _posicionar(self):
        top = self._popup
        if top is None:
            return
        try:
            top.update_idletasks()
            larg = max(self.busca.winfo_width(), px(240))
            alt = top.winfo_reqheight()
            x = self.busca.winfo_rootx()
            y = self.busca.winfo_rooty() + self.busca.winfo_height() + px(3)
            # Puxada para dentro da tela: com `overrideredirect` o Windows não
            # reposiciona nada sozinho, e numa janela baixa a lista das treze
            # telas nasceria com metade fora do monitor.
            x = max(min(x, top.winfo_screenwidth() - larg - px(8)), px(8))
            if y + alt > top.winfo_screenheight() - px(8):
                y = max(self.busca.winfo_rooty() - alt - px(3), px(8))
            top.geometry(f"{larg}x{alt}+{x}+{y}")
            top.deiconify()
        except tk.TclError:
            self._fechar_lista()

    def _clique_fora(self, ev):
        """Fecha, a não ser que o clique tenha sido no campo ou na lista.

        Compara o CAMINHO do widget no Tk, que é hierárquico — o mesmo teste
        que o calendário e o Enter global do app usam."""
        if self._popup is None:
            return
        alvo = str(ev.widget)
        if alvo.startswith(str(self._popup)) or alvo.startswith(str(self.busca)):
            return
        self._fechar_lista()

    def _fechar_lista(self):
        if self._fora is not None:
            try:
                self.winfo_toplevel().unbind("<Button-1>", self._fora)
            except tk.TclError:
                pass
            self._fora = None
        if self._popup is not None:
            try:
                self._popup.destroy()
            except tk.TclError:              # a janela principal já a levou
                pass
            self._popup = None
        self._moldura = None
        self._linhas = []

    # ------------------------------------------------------------- tema
    def aplicar_cores(self, escuro: bool | None = None):
        c = cores()
        # A lista lê a paleta ao nascer e vive o tempo de uma digitação:
        # fechá-la é repintá-la, como no calendário.
        self._fechar_lista()
        try:
            self.configure(background=c["marca_barra"])
            for filho in (self.esquerda, self.centro, self.direita):
                filho.configure(background=c["marca_barra"])
            # O campo de busca tem a cor de cartão, com borda fina: desde
            # 22/10/2026 a barra é a cor da página (antes era azul, e o campo
            # era um azul mais claro por dentro).
            fundo = c["fundo"]
            self.busca.configure(background=fundo,
                                 insertbackground=c["barra_texto"],
                                 foreground=c["marca_sub"] if self._vazia
                                 else c["barra_texto"],
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
        # O círculo leva uma LETRA dentro, e a letra cresce com a escala: um
        # círculo de 30 px fixos a 150% é uma inicial estourando a bolha.
        self._lado = px(lado)
        super().__init__(pai, width=self._lado, height=self._lado, **kw)
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
        # Na barra ou fora dela, a mesma bolinha: desde 22/10/2026 a barra é
        # a cor da página, e o branco sobre ela sumiria no tema claro.
        bolha = c["marca_fundo"]
        frente = c["marca"]
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

    A BOLINHA é o que muda de cor; o texto fica sempre legível sobre a barra.
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
        # A bolinha acompanha a escala: parada em 10 px ao lado de um texto
        # 1,5× maior, ela deixa de ser um sinal e vira sujeira na barra.
        self._bolinha = px(10)
        self.bolha = tk.Canvas(self, width=self._bolinha,
                               height=self._bolinha,
                               highlightthickness=0, borderwidth=0)
        self.bolha.pack(side="left", pady=px(2))
        self.lbl = ttk.Label(self, text="Navegador livre",
                             style="Barra.TLabel" if na_barra else "Apoio.TLabel",
                             wraplength=0, anchor="w", width=largura)
        self.lbl.pack(side="left", padx=px((7, 0)))
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
        # Na barra ou fora dela, as cores do tema: até 22/10/2026 a barra era
        # azul escura e usava um verde e um âmbar fixos, claros, que na barra
        # da cor da página clara sumiam (1,4:1).
        cor = cor_da_bolinha(c, self._estado)
        try:
            self.bolha.delete("all")
            self.bolha.create_oval(1, 1, self._bolinha - 1,
                                   self._bolinha - 1, fill=cor, outline="")
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

    Aqui o aberto é azul CHEIO com texto branco (desde 22/10/2026, protótipo
    da repaginada; antes era fundo azul-claro, texto azul e um filete de 3 px
    na borda esquerda). O azul cheio separa sozinho "aberto" de "o cursor
    está em cima", que continua sendo o cinza do painel.

    O ícone é trocado por ● quando a aba está trabalhando (ver `_pulso` no
    `comprovantes_app.py`). Guardado à parte para o ● poder voltar a ser o
    ícone de sempre quando o trabalho acaba.

    O `icone` que chega aqui continua sendo o EMOJI de sempre, e ele agora é
    duas coisas: a chave da tabela `ICONES_POR_FAMILIA` (que o troca pelo
    codepoint monocromático da fonte de ícones do Windows, para o tema
    alcançá-lo) e o fallback de quem não tem nenhuma das duas famílias. Quem
    monta o menu não precisou saber de nada disso — ver o bloco "ícones" no
    topo do arquivo.

    **Ele entra no Tab, e essa é a diferença de 02/09/2026.** Era um `tk.Frame`
    que só escutava `<Button-1>`, `<Enter>` e `<Leave>`: quem usa só o teclado
    alcançava DIÁRIO e MENSAL (que são `ttk.Button`) e não alcançava nenhuma
    das doze telas que eles agrupam. Agora `takefocus=1`, e `<Return>` e
    `<space>` disparam o MESMO `_comando` do clique — um só caminho, para não
    existir a chance de o teclado abrir uma aba e o mouse outra.

    O foco tem sinal PRÓPRIO, e ele é derivado do estado aberto: o filete e o
    anel de 1 px em volta ficam na cor `marca`, a mesma do item aberto, mas o
    texto continua na cor de sempre — "o teclado está aqui" não pode passar por
    "esta aba está aberta". Quem CARREGA o sinal é o anel, e isso foi medido:
    o fundo do foco sozinho dá 1,16:1 no claro e 1,20:1 no escuro contra a
    coluna, ou seja, não distingue nada; o anel dá 7,67:1 no claro
    (#1746C7 sobre #FFFFFF) e 6,28:1 no escuro (#6F9BFF sobre #171D28), bem
    acima dos 3:1 que a WCAG pede de indicador de foco. Sobre o item ABERTO,
    onde o fundo já é `marca_fundo`, o anel ainda dá 6,60:1 e 5,23:1 — é o que
    faz o foco aparecer mesmo na única linha que já estava destacada.

    O anel é `highlightthickness=1` e nunca muda de espessura: o Tk troca
    sozinho `highlightbackground` por `highlightcolor` quando o widget ganha o
    foco, então não há 1 px entrando e saindo do layout a cada Tab — o que
    empurraria a coluna inteira para baixo a cada tecla.
    """

    #: A largura do filete, a 100%. Escala junto: ele é o sinal de "esta aba
    #: está aberta" (e o de "o foco está aqui"), e 3 px ao lado de um item
    #: 1,5× mais alto some.
    FILETE = 3

    def __init__(self, pai, texto: str, icone: str = "", comando=None,
                 recuo: int = 0, **kw):
        c = cores()
        kw.setdefault("background", c["fundo"])
        # 1 px SEMPRE reservado — ver o docstring: o anel muda de cor, nunca de
        # espessura.
        kw.setdefault("highlightthickness", 1)
        kw.setdefault("takefocus", 1)
        kw.setdefault("cursor", "hand2")
        super().__init__(pai, **kw)
        self._icone = icone
        self._texto = texto
        self._ativo = False
        self._trabalhando = False
        self._foco = False
        self._comando = comando

        # A pílula (28/10/2026): o `FundoRedondo` desenha o item aberto e o
        # de passagem, e o corpo fica recuado o bastante para não cobrir as
        # pontas redondas. O filete da borda esquerda saiu da tela (fica o
        # objeto, que os testes de foco ainda leem).
        self._fundo = FundoRedondo(self, px(40), "fundo", fora="fundo")
        self.filete = tk.Frame(self, width=px(self.FILETE),
                               highlightthickness=0)
        self.corpo = tk.Frame(self, highlightthickness=0)
        self.corpo.pack(side="left", fill="both", expand=True,
                        padx=px(10), pady=px(4))
        self.lbl_icone = ttk.Label(self.corpo, text=icone, style="Menu.TLabel",
                                   anchor="center")
        # Sem `width` em caracteres: a largura em "caracteres" é medida na
        # fonte do texto, e o ícone vem de outra fonte, maior — o glifo
        # passava da caixa e era cortado (o dono via isso "desde sempre").
        self.lbl_icone.pack(side="left", padx=px((recuo + 2, 2)), pady=px(3))
        self.lbl = ttk.Label(self.corpo, text=texto, style="Menu.TLabel",
                             anchor="w")
        self.lbl.pack(side="left", padx=px((7, 4)), pady=px(3), fill="x",
                      expand=True)

        for w in (self, self.corpo, self.lbl, self.lbl_icone,
                  self._fundo.lbl):
            w.bind("<Button-1>", self._clique)
            w.bind("<Enter>", self._entrou)
            w.bind("<Leave>", self._saiu)
        # O foco é do FRAME, e só dele: os filhos não aceitam foco, então não há
        # segunda parada de Tab dentro do mesmo item.
        self.bind("<Return>", self._teclou)
        self.bind("<space>", self._teclou)
        self.bind("<FocusIn>", self._ganhou_foco)
        self.bind("<FocusOut>", self._perdeu_foco)
        _repintaveis.add(self)
        self.aplicar_cores(_estado["escuro"])

    # ------------------------------------------------------------ eventos
    def acionar(self):
        """Abre a tela deste item. É o que o clique faz, com nome público.

        Existe porque a busca da barra ("ir para uma tela") pula para a tela
        POR AQUI: um caminho só para o mouse, o teclado e a busca. Com três
        caminhos, existiria a chance de um deles abrir a tela errada — e o
        `mostrar` do app faz mais coisas que trocar de quadro (abre o grupo
        fechado, chama o `ao_abrir` da aba, põe o foco no primeiro campo)."""
        if self._comando:
            self._comando()

    def _clique(self, _ev=None):
        self.acionar()

    def _teclou(self, _ev=None):
        """Enter e Espaço fazem o que o clique faz — o MESMO `_comando`.

        Devolve "break" para o evento parar aqui. O `<Return>` do app é um
        `bind_all` (ver `_enter_aciona` no `comprovantes_app.py`) que dispara o
        passo principal da aba aberta: sem o "break", um Enter no menu abriria
        a aba E mandaria a aba começar a trabalhar."""
        self._clique()
        return "break"

    def _ganhou_foco(self, _ev=None):
        self._foco = True
        self._pintar()

    def _perdeu_foco(self, _ev=None):
        self._foco = False
        self._pintar()

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
        self._pintar(hover=False)

    def texto(self) -> str:
        return self._texto

    # -------------------------------------------------------------- ícone
    def _desenho_do_icone(self) -> tuple[str, str]:
        """(o texto do rótulo do ícone, a fonte que ele pede).

        Resolvido a cada pintura, e não uma vez no `__init__`: a família de
        ícones só é descoberta quando `_garantir_fontes` roda, e nada garante
        que ele tenha rodado antes deste widget nascer.

        O ● (U+25CF) NÃO está na fonte de ícones — ele é um caractere comum, e
        pedi-lo à Segoe Fluent Icons daria o quadradinho de glifo ausente
        justamente no sinal que existe para dizer onde o trabalho está. Por
        isso a aba que trabalha volta para a fonte do estilo."""
        if self._trabalhando:
            return "●", ""
        desenho, usa_fonte = icone_do_menu(self._icone)
        return desenho, (FONTE_ICONES if usa_fonte else "")

    # --------------------------------------------------------------- tema
    def aplicar_cores(self, escuro: bool | None = None):
        self._pintar()

    def _pintar(self, hover: bool = False):
        c = cores()
        if self._ativo:
            fundo, frente, filete = c["marca_solida"], "#FFFFFF", c["marca_solida"]
        elif hover:
            fundo, frente, filete = c["cabecalho"], c["texto"], c["cabecalho"]
        else:
            fundo, frente, filete = c["fundo"], c["texto"], c["fundo"]
        # O foco empresta o filete do item ABERTO — é o mesmo "você está aqui",
        # dito para o teclado — e deixa o texto na cor de sempre, que é o que
        # separa "o foco está neste item" de "esta aba está aberta". Quem
        # carrega o sinal é o anel; ver o docstring da classe para as medidas.
        if self._foco and not self._ativo:
            filete = c["marca"]
        estilo = "ItemAtivo.TLabel" if self._ativo else "Item.TLabel"
        desenho, fonte_icone = self._desenho_do_icone()
        try:
            if hover and not self._ativo:
                estilo = "ItemSobre.TLabel"
            # No item aberto o anel de foco é BRANCO: a `marca` sobre o azul
            # cheio sumiria, e o `texto` do claro dava 2,0:1 contra ele.
            self._fundo.definir(cor=fundo)
            self.configure(background=c["fundo"],
                           highlightbackground=c["fundo"],
                           highlightcolor=c["marca"])
            self.corpo.configure(background=fundo)
            self.filete.configure(background=filete)
            self.lbl.configure(style=estilo)
            # Três opções DO WIDGET por cima do estilo, e as três pelo mesmo
            # motivo — opção de widget ganha do estilo, e aqui é preciso que
            # ganhe:
            #
            # `font`, porque o estilo do item aberto (`ItemAtivo.TLabel`) traz
            # `font=FONTE_FORTE`: sem isto o único item da coluna a perder o
            # ícone seria justamente o que está aberto;
            #
            # `foreground`, porque o ● da aba que trabalha é azul mesmo quando
            # o item não é o aberto — é a única marca na tela que diz ONDE o
            # trabalho está, e na cor do item parado ela passava despercebida.
            # O fundo tem de continuar sendo o do item (branco, cinza de
            # passagem ou azul-claro), e um estilo só para o ● precisaria de
            # uma versão para cada um dos três.
            self.lbl_icone.configure(
                text=desenho, font=fonte_icone, style=estilo,
                foreground=frente if self._ativo
                else (c["ativo"] if self._trabalhando else frente))
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
        kw.setdefault("background", c["janela"])
        kw.setdefault("highlightthickness", 0)
        # A coluna inteira escala (ver o histórico deste trecho no git).
        super().__init__(pai, width=px(largura), **kw)
        self.pack_propagate(False)
        # Painel flutuante de cantos redondos desde 28/10/2026 (protótipo da
        # repaginada); a borda da direita, que separava a coluna da página,
        # saiu da tela — o vão entre os dois painéis é a separação.
        self._fundo = FundoRedondo(self, px(22), "fundo", fora="janela")
        self.borda = tk.Frame(self, width=px(1), highlightthickness=0)
        self.rodape = tk.Frame(self, highlightthickness=0)
        self.rodape.pack(side="bottom", fill="x", padx=px(16),
                         pady=px((8, 16)))
        # O corpo ROLA. Com os dois grupos abertos são treze telas e quatro
        # rótulos de seção, e numa tela baixa (1366x768) ou a 150% isso pode
        # passar da altura da coluna — o rodapé, empacotado antes, continua
        # no lugar, e são os itens de baixo que ficariam fora de alcance.
        self.corpo = AreaRolavel(self, fundo="fundo")
        self.corpo.pack(side="top", fill="both", expand=True,
                        padx=px((8, 6)), pady=px((14, 0)))
        _repintaveis.add(self)
        self.aplicar_cores(_estado["escuro"])

    def secao(self, texto: str, pai=None):
        """O rótulo de seção, em maiúsculas miúdas. Ele não é clicável — é o
        que diz que os quatro itens abaixo dele são a mesma família."""
        lbl = ttk.Label(pai if pai is not None else self.corpo,
                        text=texto.upper(), style="MenuSecao.TLabel")
        lbl.pack(anchor="w", padx=px((14, 0)), pady=px((12, 4)))
        return lbl

    def aplicar_cores(self, escuro: bool | None = None):
        c = cores()
        try:
            self.configure(background=c["janela"])
            self.corpo.configure(background=c["fundo"])
            self.rodape.configure(background=c["fundo"])
            self.borda.configure(background=c["borda"])
        except tk.TclError:
            pass


class PainelPagina(tk.Frame):
    """O painel flutuante da página, à direita do menu (28/10/2026).

    `self` é a moldura de cantos redondos na cor do `fundo`, sobre a
    `janela`; as abas moram em `self.area`, recuada o bastante para não
    cobrir os cantos."""

    def __init__(self, pai, **kw):
        c = cores()
        kw.setdefault("background", c["janela"])
        kw.setdefault("highlightthickness", 0)
        super().__init__(pai, **kw)
        self._fundo = FundoRedondo(self, px(22), "fundo", fora="janela")
        self.area = ttk.Frame(self, style="Fundo.TFrame")
        self.area.pack(fill="both", expand=True, padx=px(10), pady=px(10))


def moldura_da_janela(root):
    """Monta o corpo da janela: o menu e a página como dois painéis
    flutuantes sobre a `janela`. Devolve (corpo, lateral, conteudo), onde
    `conteudo` é onde as abas são criadas — o mesmo papel do antigo
    `ttk.Frame` "Fundo.TFrame" que o `comprovantes_app` e a galeria montavam
    cada um à mão."""
    corpo = ttk.Frame(root, style="Janela.TFrame")
    corpo.pack(side="top", fill="both", expand=True)
    lateral = painel_menu(corpo, largura=232)
    lateral.pack(side="left", fill="y", padx=px((14, 6)), pady=px((2, 14)))
    pagina = PainelPagina(corpo)
    pagina.pack(side="left", fill="both", expand=True,
                padx=px((6, 14)), pady=px((2, 14)))
    return corpo, lateral, pagina.area


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
    "aguardando": "atencao", "em analise": "atencao",
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

    Casa pelo PEDAÇO, sem acento e sem caixa: as abas escrevem "ATENÇÃO — sem
    anexo", "APTO (autorizado)" e "JÁ PAGO em 12/08/2026", e nenhuma delas vai
    passar a escrever uma chave de dicionário só para a tabela ficar colorida.

    Sem caixa é o detalhe que faltou: `util.norm` devolve MAIÚSCULAS e as
    chaves de `ESTADOS` são minúsculas, então "rejeitado" nunca estava em
    "REJEITADO" e toda linha saía "info". Foi assim que a regra "só atenção e
    erro se pintam" (ver `estilo_tabela`) passou sem pintar linha nenhuma.

    O estado que a tela escreve PRIMEIRO manda. "ATENÇÃO — sem anexo" é
    atenção com o motivo atrás, não "sem anexo" (que sozinho é erro) com um
    prefixo; escolher só pelo pedaço mais longo devolvia erro e pintava de
    vermelho o que a Remessa trata como "olhe antes de marcar".
    """
    alvo = util.norm(texto or "").lower()
    if not alvo:
        return "info"
    chaves = sorted(ESTADOS, key=len, reverse=True)
    for chave in chaves:
        if alvo.startswith(chave):
            return ESTADOS[chave]
    for chave in chaves:
        if chave in alvo:
            return ESTADOS[chave]
    # As palavras que aparecem no meio da frase, e não como estado inteiro.
    if "atencao" in alvo or "conferir" in alvo or "divergen" in alvo:
        return "atencao"
    return "info"


def estilo_tabela(tabela: "ttk.Treeview", zebra: bool = True,
                  dupla: bool = False, ordenavel: bool = True,
                  fixos=()) -> "ttk.Treeview":
    """Põe a tabela no visual do painel, registra as tags de estado e liga a
    ordenação por clique no cabeçalho.

    Chamar DEPOIS de criar as colunas e ANTES de inserir as linhas. Quem
    insere passa `tags=("ok",)` — ou o que `estado_de` devolver — e a linha
    ganha a pílula sem a aba precisar saber a cor.

    `ordenavel` vem LIGADO porque cabeçalho de tabela que não responde ao
    clique é lido como tabela quebrada: quem usa planilha o dia inteiro
    experimenta clicar antes de procurar o filtro. Desligar é para a tabela
    cuja ordem JÁ é a informação (um extrato, uma trilha de passos).

    `fixos` são iids que nunca se movem — ficam no topo, na ordem dada. Existe
    por causa da linha "(deixar em dúvida)" do Anexar: ela é uma OPÇÃO, não um
    dado, e ordenar a lista não pode enterrá-la no meio dos arquivos.
    """
    c = cores()
    tabela.configure(style="Dupla.Treeview" if dupla else "Tabela.Treeview")
    tabela._ordenacao = {"coluna": "", "descendente": False, "zebra": zebra,
                         "fixos": tuple(fixos)}
    # O TÍTULO da coluna acompanha o alinhamento do CONTEÚDO dela: o padrão do
    # ttk é centralizar o cabeçalho e alinhar o conteúdo à esquerda, e a coluna
    # de dinheiro ficava com o título no meio e os valores à direita, sem que
    # nada na tela explicasse por quê.
    # A LARGURA das colunas escala aqui, num lugar só, em vez de em cada uma
    # das catorze telas. É a medida que quebrava mais visivelmente a 150%: a
    # coluna "ÚLTIMA EXECUÇÃO" do Início tem 130 px fixos e o cabeçalho saía
    # "ÚLTIMA EXECU"; a "SITUAÇÃO", que vem depois, não cabia mais na tabela e
    # sumia inteira. Quem escreveu 130 estava dizendo "cabe o título", e é essa
    # frase — e não o número — que tem de continuar verdadeira.
    #
    # As larguras de origem ficam guardadas no widget: `estilo_tabela` é
    # chamado DE NOVO por duas telas (Início e Acessórias, ao remontar a
    # lista), e sem a memória a segunda passada escalaria o que já estava
    # escalado.
    larguras = getattr(tabela, "_larguras_base", None)
    try:
        if larguras is None:
            larguras = tabela._larguras_base = {
                c: (int(tabela.column(c, "width")),
                    int(tabela.column(c, "minwidth")))
                for c in tabela["columns"]}
        for col in tabela["columns"]:
            larg, minimo = larguras[col]
            tabela.column(col, width=px(larg), minwidth=px(minimo))
            tabela.heading(col, anchor=str(tabela.column(col, "anchor")))
            # Coluna que JÁ tem dono continua com o dono. A do "marcar todas"
            # do Baixar Comprovantes é um botão disfarçado de cabeçalho, e
            # trocá-la por uma ordenação tiraria da tela o único lugar onde se
            # marca tudo de uma vez.
            if ordenavel and not str(tabela.heading(col, "command")):
                tabela.heading(
                    col, command=lambda c=col: ordenar_tabela(tabela, c))
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


# --------------------------------------------------------- ordenar a tabela
# Clicar no cabeçalho ordena, e clicar de novo inverte. ▲ é do menor para o
# maior; ▼ é o contrário.
#
# Três decisões que não são óbvias:
#
# 1. **o TIPO sai do conteúdo, não de um cadastro de colunas.** "R$ 1.234,56"
#    ordenado como texto põe R$ 987,00 depois de R$ 1.234,56, porque "9" > "1"
#    — e é justamente a coluna de dinheiro que se ordena para achar o maior
#    pagamento do dia. Perguntar à coluna o que ela tem custa uma passada e
#    dispensa cada tela declarar o tipo de cada coluna dela (catorze tabelas,
#    catorze chances de a declaração divergir do que a célula recebe);
# 2. **a zebra é reaplicada depois de mover as linhas.** As tags "par"/"impar"
#    são gravadas NO ITEM quando ele nasce, e mover o item leva a tag junto:
#    sem reaplicar, as listras saem embaralhadas e a tabela parece um erro de
#    desenho. Só o estado (`ok`/`atencao`/`erro`/`info`) sobrevive à mudança,
#    porque ele é do DADO e não da posição;
# 3. **célula sem valor não some nem se disfarça de zero.** "—", "?" e o vazio
#    valem menos que qualquer número e que qualquer data: no ▲ elas abrem a
#    lista, no ▼ elas fecham. É previsível, e é o único jeito de não misturar
#    "não tem valor" com "vale zero" — que, numa tabela de pagamento, são
#    coisas bem diferentes.

#: O que ordena por último (ou por primeiro, no ▼): a célula que não tem valor.
#: São os travessões e afins que as telas escrevem quando o dado não existe.
_SEM_VALOR = {"", "-", "–", "—", "?", "n/d", "nao informado", "r$ —", "r$ -"}

#: As setas do cabeçalho. Ficam à parte para o `_titulo_limpo` saber tirá-las.
SETA_SOBE = " ▲"
SETA_DESCE = " ▼"


def valor_de_brl(texto) -> float | None:
    """O inverso do `brl`: "R$ 1.234,56" vira 1234.56. `None` quando não é
    número.

    Ponto é milhar e vírgula é decimal, como escreve o `brl` e como escreve
    todo o resto do app. Aceita o valor sem o "R$" (as telas gravam os dois
    jeitos na mesma tabela) e o negativo entre parênteses, que é como planilha
    costuma mostrar saída de caixa."""
    t = str(texto or "").replace(" ", " ").strip()
    t = t.replace("R$", "").replace("r$", "").strip()
    if not t:
        return None
    negativo = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("()+- ")
    if not t or any(ch not in "0123456789.," for ch in t):
        return None
    try:
        v = float(t.replace(".", "").replace(",", "."))
    except ValueError:
        return None
    return -v if negativo else v


def _data_de_texto(texto) -> "date | None":
    """dd/mm/aaaa (com ou sem hora depois) vira data. `None` quando não é."""
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})(?:\s.*)?$", str(texto or "").strip())
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None                      # 31/02: digitação, não data


def _sem_valor(texto: str) -> bool:
    return util.norm_espaco(texto).lower() in _SEM_VALOR


def _chave_da_coluna(valores):
    """A função que transforma cada célula desta coluna em algo comparável.

    Decidida pela coluna INTEIRA, e não célula a célula: chave de tipos
    misturados estoura no `sorted`, e uma coluna que ordena como número em
    metade das linhas e como texto na outra metade não ordena coisa nenhuma."""
    cheios = [v for v in valores if not _sem_valor(v)]
    if cheios and all(valor_de_brl(v) is not None for v in cheios):
        return lambda v: (valor_de_brl(v) if not _sem_valor(v)
                          else float("-inf"))
    if cheios and all(_data_de_texto(v) is not None for v in cheios):
        return lambda v: (_data_de_texto(v) if not _sem_valor(v)
                          else date.min)
    # O resto é texto, comparado como o app compara nome em todo lugar: sem
    # acento, sem caixa e sem espaço dobrado (`util.norm_espaco`). Sem isso
    # "Ática" cairia depois de "Zebra", porque "Á" vem depois de "Z" na tabela
    # de caracteres.
    return lambda v: util.norm_espaco(v)


def _titulo_limpo(texto: str) -> str:
    """O título do cabeçalho sem a seta.

    Lido do próprio cabeçalho a cada ordenação, e não guardado na hora de
    ligar: várias telas escrevem o `heading(text=…)` DEPOIS do
    `estilo_tabela`, e um título memorizado cedo demais seria o vazio."""
    t = str(texto or "")
    for seta in (SETA_SOBE, SETA_DESCE):
        if t.endswith(seta):
            return t[:-len(seta)]
    return t


def ordenar_tabela(tabela: "ttk.Treeview", coluna: str,
                   descendente: bool | None = None) -> None:
    """Ordena as linhas por esta coluna. Sem `descendente`, alterna asc/desc.

    Reordena o que já está na tela — não relê nada e não fala com ninguém.
    """
    estado = getattr(tabela, "_ordenacao", None)
    if estado is None:
        estado = tabela._ordenacao = {"coluna": "", "descendente": False,
                                      "zebra": True, "fixos": ()}
    if descendente is None:
        descendente = coluna == estado["coluna"] and not estado["descendente"]
    try:
        fixos = [i for i in estado["fixos"] if tabela.exists(i)]
        itens = [i for i in tabela.get_children("") if i not in fixos]
        # Tabela em ÁRVORE não se ordena aqui: mover um pai leva os filhos, e
        # ordenar os filhos entre pais diferentes muda o que a tabela diz.
        # Nenhuma do app é assim hoje; recusar é mais barato que descobrir.
        if any(tabela.get_children(i) for i in itens):
            return
        valores = [str(tabela.set(i, coluna)) for i in itens]
    except tk.TclError:
        return
    chave = _chave_da_coluna(valores)
    # `sorted` é estável: quem empata mantém a ordem em que estava, e é o que
    # faz ordenar por "valor" e depois por "favorecido" acumular em vez de
    # embaralhar.
    ordenados = [i for _, i in sorted(zip(valores, itens),
                                      key=lambda p: chave(p[0]),
                                      reverse=bool(descendente))]
    try:
        for pos, iid in enumerate(fixos + ordenados):
            tabela.move(iid, "", pos)
        if estado["zebra"]:
            _rezebrar(tabela, fixos + ordenados)
        for col in tabela["columns"]:
            titulo = _titulo_limpo(tabela.heading(col, "text"))
            if col == coluna:
                titulo += SETA_DESCE if descendente else SETA_SOBE
            tabela.heading(col, text=titulo)
    except tk.TclError:
        return
    estado["coluna"], estado["descendente"] = coluna, bool(descendente)


def _rezebrar(tabela: "ttk.Treeview", itens) -> None:
    """As listras seguem a POSIÇÃO; o estado segue o dado.

    A tag "par"/"impar" é gravada no item quando ele nasce e viaja com ele:
    depois de reordenar, sem isto, a zebra sai embaralhada."""
    for pos, iid in enumerate(itens):
        try:
            antigas = [t for t in tabela.item(iid, "tags")
                       if t not in ("par", "impar")]
            tabela.item(iid, tags=linha_zebrada(pos) + tuple(antigas))
        except tk.TclError:
            return


def brl(v) -> str:
    """R$ 1.234,56. Existe aqui porque cinco telas escreviam o mesmo
    `replace(",", "X").replace(".", ",").replace("X", ".")` à mão."""
    try:
        return "R$ " + f"{float(v):,.2f}".replace(",", "X").replace(
            ".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "R$ —"


# ------------------------------------------------------------ erros com nome
# O que a pessoa lê quando algo dá errado.
#
# Por que existe
# --------------
# Dez diálogos do app mostravam a exceção CRUA — `messagebox.showerror(
# "Retorno", f"Não consegui ler o arquivo:\n\n{e}")` — e o que aparecia na tela
# era `HTTPSConnectionPool(host='...', port=443): Max retries exceeded` ou
# `[Errno 13] Permission denied: 'C:/.../remessa.xlsx'`. Texto de biblioteca:
# não diz o que houve, não diz de quem é a falha e não diz o que fazer.
#
# A melhor tradução do projeto já existia, e estava presa numa função privada
# de UMA tela: o `_frase` do `nuvem/login_dialogo.py`, que virava as três
# famílias da nuvem em uma frase com as três partes. Aqui ela fica pública,
# passa a cobrir as famílias que o resto do app encontra — e o login continua
# usando ESTA, sem cópia: duas versões da mesma verdade envelhecem separadas.
#
# TRÊS partes, e não uma frase só, porque são três perguntas diferentes:
#
#   o que houve      a falha em português, sem nome de classe;
#   de quem é        o app, o ERP, o banco na nuvem, a internet ou o Windows.
#                    É o que decide para quem a pessoa reclama, e é justamente
#                    a parte que o texto cru nunca dizia;
#   próximo passo    o que fazer AGORA. "Tente de novo" e "avise quem cuida do
#                    cadastro" são conselhos opostos, e dar o errado custa a
#                    tarde de alguém.
#
# A família é reconhecida pelo NOME DA CLASSE, percorrendo a MRO — e não por
# `isinstance`. Não é preguiça: o `widgets.py` é importado por todas as telas e
# vai no codigo.zip, e importar aqui `nuvem.rest`, `erp.sessao`,
# `conciliacao.errors` e o `playwright` arrastaria rede e navegador para dentro
# do módulo visual (o `playwright` nem sempre está instalado, e um import novo
# custa exe novo — ver a v1.0.71 no CLAUDE.md). Nome de classe é contrato: quem
# renomeia `SemRede` já está mudando API. E a MRO faz a herança valer de graça
# — `SessaoRecusada` é `ErpErro`, `PrecisaEntrar` é `ErroDaNuvem`.
#
# O que ela NÃO faz: mudar o que os diálogos fazem. Continua sendo o mesmo
# `showerror` no mesmo ponto, com o mesmo `return` depois.


def _familia_do_erro(exc) -> tuple[set, set]:
    """Os nomes de classe e os módulos da exceção e de todos os pais dela."""
    try:
        mro = type(exc).__mro__
    except (AttributeError, TypeError):
        return set(), set()
    return ({c.__name__ for c in mro},
            {str(getattr(c, "__module__", "")) for c in mro})


def explicar_erro(exc) -> tuple[str, str, str]:
    """(o que houve, de quem é, o próximo passo) para a exceção dada.

    Todas as três em português e prontas para a tela. Exceção que não cai em
    nenhuma família conhecida sai num genérico HONESTO: ele diz que não soube
    dizer, e ainda mostra o tipo e a mensagem — sumir com o texto original
    deixaria quem for consertar sem nada nas mãos.
    """
    nomes, modulos = _familia_do_erro(exc)
    recado = str(exc).strip()

    # ---- o ERP recusou a identidade
    # `SessaoExpirada` é o nome que a Conciliação usa (`conciliacao/errors.py`)
    # para a mesma coisa que o `erp/sessao.py` chama de `SessaoRecusada`. As
    # duas pedem a mesma coisa de quem lê, então respondem juntas.
    if "SessaoRecusada" in nomes or "SessaoExpirada" in nomes:
        return ("O Mais Controle ERP não aceitou a sessão.",
                "É do ERP, não do app: a sessão caiu ou a senha foi recusada.",
                "Entre no ERP de novo pela aba Anexar. Lembre que ele aceita "
                "UMA sessão por usuário — se alguém entrou com o seu login, a "
                "sua caiu.")

    # ---- a sessão do APP (a nuvem do cadastro)
    if "PrecisaEntrar" in nomes:
        # Quem monta a explicação exata é o `nuvem/sessao.py`: só ele separa
        # "sem internet e a sessão salva venceu" de "a sessão não vale mais".
        # Consumida como está — reescrevê-la criaria uma segunda versão da
        # mesma verdade.
        return ((recado[:1].upper() + recado[1:]) if recado
                else "A sua sessão venceu.",
                "É do login do app (o cadastro na nuvem), não do ERP.",
                "Feche e abra o app para entrar de novo.")

    # ---- não deu para falar com o outro lado
    if "SemRede" in nomes:
        # O `anexar/mc_client.SemRede` promete no próprio docstring que a
        # mensagem dele já vem pronta para o usuário ("quem captura deve
        # mostrar só o texto"). O da nuvem não promete nada disso, e o texto
        # dele é da biblioteca de rede.
        pronta = any("mc_client" in m for m in modulos)
        return ((recado if (pronta and recado)
                 else "Não deu para falar com o servidor."),
                "É da internet ou do serviço do outro lado — não é o app.",
                "Confira a conexão e tente de novo em alguns minutos.")

    # ---- o banco entendeu e disse não
    if "RecusadoPeloBanco" in nomes:
        return ("O servidor entendeu o pedido e recusou.",
                "É do banco na nuvem — não é a sua senha nem falta de "
                "internet.",
                "Tente de novo em alguns minutos; se continuar, avise quem "
                "cuida do cadastro.")

    # ---- o ERP respondeu, mas não o que o app esperava
    if "ErpErro" in nomes or "ErpError" in nomes:
        return ("O Mais Controle ERP não respondeu como o app esperava.",
                "É do ERP (ou de uma tela dele que mudou), não do que você "
                "preencheu.",
                "Tente de novo. Se parar sempre no mesmo ponto, avise quem "
                "cuida do app.")

    # ---- a espera acabou primeiro
    # ANTES do `OSError`: o `TimeoutError` embutido do Python é subclasse dele,
    # e "esperei demais" e "o disco não deixou" pedem coisas diferentes. Vale
    # para o do `playwright` e para o embutido — os dois dizem o mesmo.
    if "TimeoutError" in nomes:
        return ("A espera acabou antes de a resposta chegar.",
                "É do outro lado (a tela do ERP, o site do banco ou a rede), "
                "não do app.",
                "Tente de novo — o ERP fica lento quando o lote é grande.")

    # ---- arquivo e disco
    # `isinstance` aqui, e não nome: são classes EMBUTIDAS, já estão
    # importadas, e não há import novo para pagar.
    #
    # O texto do sistema entra junto porque ele nomeia O ARQUIVO, que é a
    # informação que resolve o caso — sem ele, "feche o arquivo no Excel" não
    # diz qual arquivo.
    if isinstance(exc, PermissionError):
        return ("O Windows não deixou abrir o arquivo."
                + (f"\n{recado}" if recado else ""),
                "É do arquivo, não do app: quase sempre ele está aberto "
                "noutro programa.",
                "Feche o arquivo no Excel (ou onde estiver aberto) e tente de "
                "novo.")
    if isinstance(exc, OSError):
        return ("Não deu para ler ou gravar o arquivo."
                + (f"\n{recado}" if recado else ""),
                "É do computador — a pasta, o disco, ou o OneDrive segurando "
                "o arquivo.",
                "Confira se a pasta existe e se o arquivo não está aberto, e "
                "tente de novo.")

    # ---- o resto: honesto sobre não saber
    tipo = type(exc).__name__ if exc is not None else "erro sem tipo"
    return (f"{tipo}: {recado}" if recado else tipo,
            "Não deu para dizer de quem é a falha: este erro não tem nome "
            "conhecido aqui.",
            "Tente de novo. Se repetir, mande a linha de cima para quem cuida "
            "do app.")


def recado_de_erro(exc, tentando: str = "") -> str:
    """As três partes numa caixa de diálogo, com o que a tela tentava fazer.

    `tentando` é a frase que o diálogo já dizia ("Não consegui ler o arquivo
    de retorno."): ela continua no lugar dela, em cima, porque é a única parte
    que só a TELA sabe — o `explicar_erro` conhece a exceção, não o passo."""
    corpo = "\n".join(p for p in explicar_erro(exc) if p)
    return f"{tentando}\n\n{corpo}" if tentando else corpo


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


def _elastico(widget) -> bool:
    """Este irmão foi empacotado com `expand`? O `pack_info` do Tk devolve o
    valor como veio do Tcl ("1", 1 ou True conforme a versão)."""
    try:
        return str(widget.pack_info().get("expand", 0)).lower() in (
            "1", "true", "yes")
    except (tk.TclError, KeyError, AttributeError):
        return False


def _reservar_o_pe(cartao) -> None:
    """O Registro deixa de ser a SOBRA da tela e passa a ser uma RESERVA.

    O defeito de 03/09/2026: na Aportes a 125%, o Registro virou uma tira de
    ~40 px com a primeira linha cortada ao meio. A causa não está nele — está
    na ordem em que o `pack` atende os irmãos.

    O `pack` do Tk serve os filhos NA ORDEM em que foram empacotados, e dá a
    cada um a altura que ele pediu, cortada pelo que ainda sobrou de cavidade
    (`cavityHeight`); quem vem depois de a cavidade acabar fica com zero. O
    Registro é o último de todas as onze telas, então ele é sempre o primeiro a
    pagar quando a soma não cabe — e a soma passou a não caber porque a fonte
    do sistema cresce (a tabela pede `height` em LINHAS, e uma linha a 125% é
    25% mais alta) enquanto a janela continua do mesmo tamanho.

    A correção é uma linha de `pack`, e o que ela diz é uma decisão: **quem
    cede espaço é a LISTA, nunca o Registro**. O cartão passa a ser empacotado
    `side="bottom"` e ANTES do primeiro irmão elástico — o cartão da tabela, o
    único da tela que já sabe encolher, porque tem barra de rolagem e mostra um
    pedaço do que existe por natureza. Vindo de baixo, ele continua desenhado
    exatamente onde estava (é o único `side="bottom"` da aba, e quem vem depois
    preenche a cavidade de cima para baixo); o que muda é que ele reserva as
    suas linhas ANTES de a tabela pedir as dela.

    Onde não há irmão elástico, nada é mexido: ser o último já é ser o dono da
    sobra, e trocar a ordem ali só criaria a chance de o Registro nascer acima
    da barra de ação. É a mesma armadilha que o aviso de `registro_elastico`
    descreve, e é por isso que esta função é chamada UMA vez, na montagem, e
    não a cada `<<Modified>>`."""
    gerenciado = getattr(cartao, "moldura", cartao)
    try:
        irmaos = gerenciado.master.pack_slaves()
    except (tk.TclError, AttributeError):
        return
    if gerenciado not in irmaos:
        return                  # ainda não empacotado, ou não é o pack que o põe
    # Só os que vêm ANTES dele: irmão elástico posterior já é atendido depois,
    # e passar o Registro para trás dele seria trocar a garantia pelo defeito.
    antes = irmaos[:irmaos.index(gerenciado)]
    disputa = next((w for w in antes if _elastico(w)), None)
    if disputa is None:
        return                  # ninguém para disputar: a ordem já basta
    try:
        cartao.pack_configure(side="bottom", before=disputa)
    except tk.TclError:
        pass                    # aba desmontada no meio da construção


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
    ação — que é justamente onde ficam os botões de começar.

    **`altura_minima` vale nos DOIS estados** (03/09/2026). Com trabalho
    dentro, o campo pedia `height=1` — "fico com a sobra" —, e enquanto sobrou
    tela isso foi invisível: o `expand` devolvia o espaço todo. Numa janela
    apertada (1920x1040 com a fonte a 125%) não sobra nada, e "a sobra" virou
    literalmente uma linha cortada ao meio. Pedir o piso não custa pixel nenhum
    onde já cabia — quem manda ali continua sendo o `expand` — e é o que
    `_reservar_o_pe` transforma em garantia onde não cabe."""
    #: `pintado` é até onde `colorir_registro` já passou. Guardado aqui, e não
    #: recalculado, porque o registro de um lote grande chega a milhares de
    #: linhas e repintá-lo inteiro a cada mensagem trava a janela.
    #: `piso` é a altura mínima em linhas, e é ela que a alça e o "Ampliar"
    #: mexem (ver `_controles_do_registro`); nasce em `altura_minima`.
    estado = {"cheio": None, "dentro": False, "pintado": 1,
              "piso": altura_minima, "arrasto": None}

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
            alvo = (estado["piso"] if cheio
                    else max(_altura_vazia(), estado["piso"]))
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

    _reservar_o_pe(cartao)
    texto.bind("<<Modified>>", _ajustar, add="+")
    _controles_do_registro(cartao, texto, estado, _ajustar, altura_minima)
    _ajustar()


#: Quanto da aba o Registro toma no "Ampliar", e o teto do arrasto da alça.
#: O que sobra é da parte que rola — sem ela, o formulário viraria uma fresta.
FRACAO_AMPLIADO = 0.6
FRACAO_TETO = 0.8


def _altura_da_linha(texto: tk.Text) -> int:
    """Pixels de uma linha do registro.

    Pelo Tcl (`font metrics`), e não por `tkinter.font`: o motivo é o do
    `_garantir_fontes` — aquele módulo não está no exe."""
    try:
        linha = int(texto.tk.call("font", "metrics", texto.cget("font"),
                                  "-linespace"))
        linha += int(texto.cget("spacing1")) + int(texto.cget("spacing3"))
    except (tk.TclError, ValueError):
        return 16
    return max(linha, 1)


class _AlcaDoRegistro(tk.Frame):
    """A faixa no alto do cartão de Registro que se arrasta para mudar a
    altura dele. O traço no meio é o sinal de "isto se puxa" — o mesmo das
    gavetas que sobem do pé da tela —, e o cursor de seta dupla confirma.

    O traço é `tenue` e não `linha`: `linha` é cor de filete, e contra o
    cartão ela não chega aos 3:1 que um controle precisa para ser achado."""

    def __init__(self, pai):
        c = cores()
        super().__init__(pai, height=px(8), background=c["cartao"],
                         highlightthickness=0, borderwidth=0,
                         cursor="sb_v_double_arrow")
        self._sobre = False
        self.traco = tk.Frame(self, width=px(36), height=px(3),
                              background=c["tenue"], highlightthickness=0,
                              borderwidth=0, cursor="sb_v_double_arrow")
        self.traco.place(relx=0.5, rely=0.5, anchor="center")
        for w in (self, self.traco):
            w.bind("<Enter>", lambda _e: self._realcar(True), add="+")
            w.bind("<Leave>", lambda _e: self._realcar(False), add="+")
        _repintaveis.add(self)

    def _realcar(self, sobre: bool):
        self._sobre = sobre
        self.aplicar_cores()

    def aplicar_cores(self, escuro: bool | None = None):
        c = cores()
        try:
            self.configure(background=c["cartao"])
            self.traco.configure(
                background=c["marca"] if self._sobre else c["tenue"])
        except tk.TclError:
            pass


def _controles_do_registro(cartao, texto: tk.Text, estado: dict, ajustar,
                           altura_minima: int) -> None:
    """A alça, o "Ampliar/Recolher" e o "Copiar" do cartão de Registro.

    Pedido de 11/09/2026: o Registro é o que se lê durante a rodada inteira,
    e com a altura decidida só pela sobra da tela, quem queria ler mais não
    tinha o que fazer. Os três mexem só no `piso` (a altura mínima, em
    linhas): onde sobra tela, o `expand` continua dando a sobra ao Registro;
    onde não sobra, quem cede é a parte da aba que rola — nunca a doca.

    "Copiar" existe porque o Registro é o que se manda a quem vai ajudar
    quando algo dá errado, e selecionar trezentas linhas com o mouse num
    campo que rola sozinho é trabalho de três tentativas.

    Só entra em `Cartao` com título: os dois links moram no cabeçalho dele."""
    if not isinstance(cartao, Cartao) or cartao.cabecalho is None:
        return
    moldura = cartao.moldura

    def _linhas_ate(fracao: float) -> int:
        """Quantas linhas cabem se o cartão tomar `fracao` da aba."""
        try:
            cromo = moldura.winfo_height() - texto.winfo_height()
            livre = moldura.master.winfo_height() * fracao - cromo
        except tk.TclError:
            return altura_minima
        return max(altura_minima, int(livre // _altura_da_linha(texto)))

    def _definir(linhas: int):
        estado["piso"] = max(3, int(linhas))
        ajustar()
        try:
            b_ampliar.configure(text="Recolher" if estado["piso"] > altura_minima
                                else "Ampliar")
        except tk.TclError:
            pass

    def _alternar(_ev=None):
        _definir(altura_minima if estado["piso"] > altura_minima
                 else _linhas_ate(FRACAO_AMPLIADO))

    def _copiar():
        if tem_conteudo_real(texto):
            texto.clipboard_clear()
            texto.clipboard_append(texto.get("1.0", "end-1c"))
            recado = "Copiado ✓"
        else:
            recado = "Nada a copiar"
        b_copiar.configure(text=recado)

        def _voltar():
            try:
                b_copiar.configure(text="Copiar")
            except tk.TclError:
                pass                     # aba fechada antes do recado sumir
        b_copiar.after(1600, _voltar)

    def _pegar(ev):
        estado["arrasto"] = (ev.y_root, texto.winfo_height())

    def _arrastar(ev):
        if not estado["arrasto"]:
            return
        y0, h0 = estado["arrasto"]
        # `pady` e o filete cobram PIXELS; `height` conta LINHAS.
        folga = 2 * (int(texto.cget("pady")) + int(texto.cget("borderwidth"))
                     + int(texto.cget("highlightthickness")))
        linhas = round((h0 - folga + y0 - ev.y_root) / _altura_da_linha(texto))
        _definir(min(max(linhas, 3), _linhas_ate(FRACAO_TETO)))

    def _soltar(_ev):
        estado["arrasto"] = None

    # `side="right"`: o primeiro empacotado é o da ponta.
    b_ampliar = Botao(cartao.acoes, "Ampliar", papel="link", command=_alternar,
                      padx=px(8), pady=px(2))
    b_ampliar.pack(side="right", padx=px((10, 0)))
    b_copiar = Botao(cartao.acoes, "Copiar", papel="link", command=_copiar,
                     padx=px(8), pady=px(2))
    b_copiar.pack(side="right", padx=px((10, 0)))

    alca = _AlcaDoRegistro(moldura)
    alca.pack(fill="x", before=cartao.cabecalho)
    for w in (alca, alca.traco):
        w.bind("<ButtonPress-1>", _pegar, add="+")
        w.bind("<B1-Motion>", _arrastar, add="+")
        w.bind("<ButtonRelease-1>", _soltar, add="+")
        w.bind("<Double-Button-1>", _alternar, add="+")
    cartao.alca, cartao.b_ampliar, cartao.b_copiar = alca, b_ampliar, b_copiar


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
                    padx=px(12), pady=px(8))
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
                        relief="flat", padx=px(8), pady=px(6))
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


def _desligar(widget, sequencia: str, funcid: str) -> None:
    """Desfaz UM `bind(..., add="+")`, deixando os outros da mesma sequência.

    O `unbind(seq, funcid)` do tkinter (até o 3.12; o exe roda 3.11) apaga
    TODOS os scripts da sequência, não só o daquele `funcid`: fechar a lista
    de um `ComboBusca` desligaria junto o clique-fora do calendário aberto ao
    lado. Aqui sai só a linha que chama o nosso comando."""
    try:
        atual = widget.tk.call("bind", str(widget), sequencia)
        resto = "\n".join(linha for linha in str(atual).split("\n")
                          if funcid not in linha)
        widget.tk.call("bind", str(widget), sequencia, resto)
        widget.deletecommand(funcid)
    except tk.TclError:
        pass


def _ligar_etiqueta_da_lista(widget) -> None:
    """Liga, uma vez por interpretador Tcl, as teclas da lista do `ComboBusca`
    à etiqueta compartilhada. Cada tecla chama o método do combo que a
    recebeu (`ev.widget`)."""
    tag = ComboBusca._ETIQUETA
    if widget.bind_class(tag):
        return
    acoes = {
        "<Down>": lambda c: c._mover(1),
        "<Up>": lambda c: c._mover(-1),
        "<Next>": lambda c: c._mover(c.VISIVEIS),
        "<Prior>": lambda c: c._mover(-c.VISIVEIS),
        "<Return>": lambda c: c._confirmar(),
        "<KP_Enter>": lambda c: c._confirmar(),
        "<Escape>": lambda c: c._esc(),
    }

    def ligar(seq, acao):
        def tratar(ev):
            if isinstance(ev.widget, ComboBusca):
                return acao(ev.widget)
            return None
        widget.bind_class(tag, seq, tratar)

    for seq, acao in acoes.items():
        ligar(seq, acao)

    def clique(ev):
        if isinstance(ev.widget, ComboBusca):
            return ev.widget._clique(ev)
        return None
    widget.bind_class(tag, "<Button-1>", clique)


def destino_do_clique(elemento: str, *, x: int, largura: int, faixa_seta: int,
                      desabilitado: bool, so_leitura: bool) -> str:
    """Para onde vai um clique no `ComboBusca`: "texto", "lista" ou "nada".

    É a MESMA pergunta do `ttk::combobox::Press` do Tk, virada do avesso. A
    classe posiciona o cursor só quando o campo é editável E o clique cai no
    `textarea`; em todo o resto — seta, borda, enchimento, campo `readonly` —
    ela posta a lista NATIVA. Até 22/10/2026 o nosso clique tomava só a SETA,
    e a moldura do campo ficava com a classe: era o "às vezes abre a lista
    antiga" do print do dono. Respondendo à pergunta dela, nenhum clique que a
    levaria a postar chega até ela.

    `faixa_seta`: os últimos pixels contam como seta mesmo quando o `identify`
    diz texto (em escala alta o texto encosta nela)."""
    if desabilitado:
        return "nada"
    if so_leitura or x >= largura - faixa_seta:
        return "lista"
    if str(elemento).endswith("textarea"):
        return "texto"
    return "lista"


def _script_sem_lista_nativa(comando: str) -> str:
    """O `-postcommand` que impede a lista nativa de abrir.

    `ttk::combobox::Post` roda `uplevel #0 [$cb cget -postcommand]` antes de
    criar a listbox; com `return` no fim, o `uplevel` devolve TCL_RETURN e o
    `Post` sai ali, sem erro e sem a lista existir. É a segunda trava: a
    primeira é o clique e as teclas na etiqueta do combo, e esta pega qualquer
    caminho que ainda chegue ao `Post` (um binding da classe que não
    previmos, um `event generate`, uma versão nova do Tk)."""
    return f"{comando}; return"


class ComboBusca(ttk.Combobox):
    """Combo em que se DIGITA para procurar, além de escolher na lista.

    Existia um campo "Buscar" separado, que filtrava dois combos de uma vez.
    Ele resolvia o problema errado: para achar a conta do "Recebeu" era preciso
    sair para outro campo, digitar, voltar e abrir a lista — e o mesmo filtro
    mexia no "Pagou" junto, mesmo quando só o outro interessava. Aqui o campo é
    o próprio buscador, e cada um filtra o seu.

    Compara sem acento e sem caixa, por PEDAÇO em qualquer posição (`util.
    filtrar`): "111" acha a subconta 11111-1, "fulan" acha "Fulana".

    **A lista abre SOZINHA enquanto se digita** (14/10/2026, pedido do dono:
    "comecei a escrever, tem que aparecer as opções"). Até então ela só abria
    pela seta, porque a lista NATIVA do Tk, posta, toma as teclas para ela — que
    tem busca própria, por prefixo — e a pessoa digitava num lugar diferente do
    que estava olhando. A saída é a mesma da busca da `BarraTopo` e do
    calendário do `CampoData`: a lista é um `Toplevel` nosso, **sem foco
    nenhum**. O foco nunca sai do campo; ↑/↓ andam pela lista, Enter escolhe a
    realçada, Esc fecha. A seta e o ↓ com a lista fechada abrem ESTA mesma
    lista, e não a nativa — uma lista só, com a mesma cara nos dois caminhos.
    Desde 22/10/2026 isso vale para TODO clique fora do texto (a moldura do
    campo abria a nativa, "às vezes", no print do dono) e para qualquer outro
    caminho até o `Post` da classe, travado pelo `-postcommand`
    (`destino_do_clique`, `_script_sem_lista_nativa`). Ela mostra `VISIVEIS` linhas de cada vez e rola (roda, barra ou setas):
    um cadastro de cem contas não pode virar uma janela da altura do monitor.

    E nada é escolhido por adivinhação: texto que não é uma opção fica como foi
    digitado, e quem lança dinheiro recebe o erro em vez de uma conta parecida
    escolhida em silêncio. A única correção automática é de GRAFIA, quando o
    que se digitou casa exatamente com uma opção fora acento e caixa. A lista
    aberta não muda isso: Enter só escolhe o que está REALÇADO na tela, e sair
    do campo com a lista aberta não escolhe nada.
    """

    #: Quantas linhas a lista mostra de cada vez; o resto rola.
    VISIVEIS = 8

    #: A etiqueta (bindtag) das teclas da lista; ver `__init__`.
    _ETIQUETA = "ComboBuscaLista"

    #: Teclas que NÃO são digitação: filtrar nelas remontaria a lista
    #: justamente enquanto a pessoa anda por ela.
    _NAO_E_DIGITAR = ("Up", "Down", "Return", "KP_Enter", "Escape", "Tab",
                      "Left", "Right", "Home", "End", "Prior", "Next",
                      "Shift_L", "Shift_R", "Control_L", "Control_R",
                      "Alt_L", "Alt_R")

    def __init__(self, master, width=38, **kw):
        kw.setdefault("state", "normal")          # readonly não deixa digitar
        self._postcommand_de_quem_usa = kw.pop("postcommand", None)
        super().__init__(master, width=width, **kw)
        # A lista nativa NUNCA abre: qualquer caminho que chegue ao `Post` da
        # classe roda este script, que abre a NOSSA e faz o `Post` desistir.
        self.configure(postcommand=_script_sem_lista_nativa(
            self.register(self._pediram_a_nativa)))
        self._todos: list[str] = []
        #: O que a lista aberta mostra, a linha realçada (índice em `_achados`)
        #: e a primeira linha visível — a lista rola por janela de `VISIVEIS`.
        self._achados: list[str] = []
        self._realce = 0
        self._topo = 0
        self._popup = None
        self._linhas: list = []
        self._barra = None
        self._rodape = None
        self._fora = None
        self._vigia = None
        self._onde = None
        self.bind("<KeyRelease>", self._ao_digitar)
        self.bind("<<ComboboxSelected>>", self._ao_escolher)
        self.bind("<FocusOut>", self._ao_sair)
        # As teclas da lista ficam no CAMPO, porque o foco nunca sai dele — mas
        # numa etiqueta própria, posta ANTES da do widget: quem usa o combo
        # liga o seu `<Return>` direto nele (o "Novo cadastro" acrescenta à
        # lista, as Guias confirmam), e um `bind` sem `add` apagaria o nosso.
        # Assim, com a lista aberta o Enter escolhe e para ali ("break"); com
        # ela fechada, segue para o Enter de quem usa e para o `bind_all` do
        # app. O "break" do ↓ também impede a classe de abrir a lista nativa.
        _ligar_etiqueta_da_lista(self)
        self.bindtags((self._ETIQUETA,) + tuple(self.bindtags()))
        self.bind("<Destroy>", lambda _e: self.fechar_lista(), add="+")

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
        if ev.keysym in self._NAO_E_DIGITAR:
            return
        texto = self.get()
        self["values"] = util.filtrar(self._todos, texto)
        if texto.strip():
            self.abrir_lista()
        else:
            # Apagou tudo: a lista sai. Quem quer ver todas tem a seta e o ↓.
            self.fechar_lista()

    def _ao_escolher(self, _ev=None):
        """Escolheu: a lista volta inteira, senão a próxima abertura ainda
        mostraria só o que sobrou do filtro anterior."""
        self["values"] = self._todos

    def _ao_sair(self, _ev=None):
        # A lista não fecha AQUI: no Windows, clicar numa linha dela pode tirar
        # o foco do campo antes de o clique chegar à linha, e fechá-la já
        # perderia a escolha. Quem fecha é o vigia, logo depois.
        texto = self.get().strip()
        if not texto:
            self["values"] = self._todos
            return
        alvo = util.norm_espaco(texto)
        exatos = [v for v in self._todos if util.norm_espaco(v) == alvo]
        if len(exatos) == 1 and exatos[0] != texto:
            self.set(exatos[0])          # só arruma a grafia
        self["values"] = self._todos

    # ------------------------------------------------- teclas e clique
    def lista_aberta(self) -> bool:
        return self._popup is not None

    def _mover(self, passo: int):
        if self._popup is None:
            # ↓ com a lista fechada abre ESTA lista; ↑ não faz nada.
            if passo > 0:
                self.abrir_lista(tudo_se_escolhido=True)
            return "break"
        if self._achados:
            novo = self._realce + passo
            if abs(passo) == 1:
                novo %= len(self._achados)       # dá a volta, como na barra
            self._realce = max(0, min(novo, len(self._achados) - 1))
            self._mostrar_realce()
        return "break"

    def _confirmar(self, _ev=None):
        """Enter com a lista aberta escolhe a linha realçada. Com ela fechada,
        o Enter segue seu caminho (o passo principal da aba)."""
        if self._popup is None:
            return None
        if self._achados and 0 <= self._realce < len(self._achados):
            self.escolher(self._achados[self._realce])
        else:
            self.fechar_lista()
        return "break"

    def _esc(self, _ev=None):
        if self._popup is None:
            return None
        self.fechar_lista()
        return "break"

    def _clique(self, ev):
        """Todo clique que a classe usaria para postar a lista nativa abre (ou
        fecha) a NOSSA; o clique no texto segue para a classe e só posiciona
        o cursor. Vale para o simples, o duplo, o triplo e o com Shift: na
        etiqueta só existe `<Button-1>`, e o Tk o casa com os quatro.
        Ver `destino_do_clique`."""
        try:
            elemento = str(self.identify(ev.x, ev.y))
        except tk.TclError:
            elemento = ""
        destino = destino_do_clique(
            elemento, x=ev.x, largura=self.winfo_width(), faixa_seta=px(26),
            desabilitado=self.instate(["disabled"]),
            so_leitura=self.instate(["readonly"]))
        if destino == "texto":
            return None
        if destino == "nada":
            return "break"
        self.focus_set()
        if self._popup is not None:
            self.fechar_lista()
        else:
            self.abrir_lista(tudo_se_escolhido=True)
        return "break"

    def _pediram_a_nativa(self):
        """O `-postcommand`: alguém chegou ao `Post` da classe. Abre a nossa
        no lugar (o script devolve `return`, e a nativa não abre)."""
        if self._postcommand_de_quem_usa is not None:
            try:
                self._postcommand_de_quem_usa()
            except Exception:              # noqa: BLE001 — não derruba o combo
                pass
        if self._popup is None and not self.instate(["disabled"]):
            self.abrir_lista(tudo_se_escolhido=True)

    def escolher(self, valor: str) -> None:
        """Põe `valor` no campo como se tivesse vindo da lista nativa: o
        `<<ComboboxSelected>>` é gerado, e quem o escuta (o `_ao_escolher`, e
        qualquer aba) reage do mesmo jeito pelos dois caminhos."""
        self.fechar_lista()
        self.set(valor)
        self.icursor("end")
        self.selection_clear()
        try:
            self.focus_set()
        except tk.TclError:
            pass
        self.event_generate("<<ComboboxSelected>>")

    # ------------------------------------------------------------ a lista
    def abrir_lista(self, tudo_se_escolhido: bool = False) -> None:
        """Abre (ou redesenha) a lista com o que casa com o texto do campo.

        `tudo_se_escolhido`: pela seta ou pelo ↓, um campo que já mostra uma
        opção escolhida abre a lista INTEIRA, com ela realçada — filtrar pelo
        nome completo deixaria uma linha só, e quem abre a lista com algo
        escolhido quer trocar de opção."""
        if not self._todos:
            self.fechar_lista()
            return
        texto = self.get()
        realce = 0
        if tudo_se_escolhido and texto in self._todos:
            self._achados = list(self._todos)
            realce = self._achados.index(texto)
        else:
            self._achados = util.filtrar(self._todos, texto)
        self._realce = realce
        self._topo = 0
        self._desenhar()

    def fechar_lista(self) -> None:
        if self._vigia is not None:
            try:
                self.after_cancel(self._vigia)
            except tk.TclError:
                pass
            self._vigia = None
        if self._fora is not None:
            _desligar(self._fora[0], "<Button-1>", self._fora[1])
            self._fora = None
        if self._popup is not None:
            try:
                self._popup.destroy()
            except tk.TclError:              # a janela já a levou
                pass
            self._popup = None
        self._linhas = []
        self._barra = None
        self._rodape = None
        self._onde = None

    def _desenhar(self):
        c = cores()
        if self._popup is None:
            top = tk.Toplevel(self)
            top.withdraw()                   # posiciona antes de aparecer
            top.overrideredirect(True)       # sem barra de título e sem foco
            top.transient(self.winfo_toplevel())
            try:
                top.attributes("-topmost", True)
            except tk.TclError:
                pass
            # Se o Windows der o foco à lista (clique na barra de rolagem),
            # ele volta ao campo: é nele que a pessoa está digitando.
            top.bind("<FocusIn>", lambda _e: self.after_idle(self._focar_campo))
            self._popup = top
            moldura = tk.Frame(top, highlightthickness=1, background=c["cartao"],
                               highlightbackground=c["borda"],
                               highlightcolor=c["borda"])
            moldura.pack(fill="both", expand=True)
            corpo = tk.Frame(moldura, background=c["cartao"])
            corpo.pack(fill="both", expand=True, padx=px(3), pady=px(3))
            self._barra = ttk.Scrollbar(corpo, orient="vertical",
                                        command=self._rolar_pela_barra)
            linhas = tk.Frame(corpo, background=c["cartao"])
            linhas.pack(side="left", fill="both", expand=True)
            for i in range(self.VISIVEIS):
                lin = tk.Label(linhas, anchor="w", padx=px(10), pady=px(5),
                               cursor="hand2", font="TkDefaultFont",
                               background=c["cartao"], foreground=c["texto"])
                lin.bind("<Button-1>", lambda _e, n=i: self._clicou_linha(n))
                lin.bind("<Enter>", lambda _e, n=i: self._passou_por(n))
                lin.bind("<MouseWheel>", self._roda)
                self._linhas.append(lin)
            self._rodape = tk.Label(moldura, anchor="w", padx=px(13),
                                    pady=px(4), font=FONTE_APOIO,
                                    background=c["cartao"],
                                    foreground=c["tenue"])
            for w in (top, moldura, corpo, linhas, self._rodape):
                w.bind("<MouseWheel>", self._roda)
            # Clique fora fecha. O bind vai no toplevel do CAMPO (a aba ou o
            # diálogo), `add="+"` para não derrubar quem já usa o <Button-1>.
            janela = self.winfo_toplevel()
            fid = janela.bind("<Button-1>", self._clique_fora, add="+")
            self._fora = (janela, fid)
            self._vigia = self.after(self.VIGIA_MS, self._vigiar)

        n = len(self._achados)
        visiveis = min(max(n, 1), self.VISIVEIS)
        for i, lin in enumerate(self._linhas):
            if i < visiveis and n:
                lin.pack(fill="x")
            else:
                lin.pack_forget()
        if n > self.VISIVEIS:
            self._barra.pack(side="right", fill="y", padx=px((2, 0)))
        else:
            self._barra.pack_forget()
        if not n:
            # Dizer que não achou, em vez de sumir com a lista: campo que não
            # responde a nada parece travado.
            texto = self.get().strip()
            self._rodape.configure(text=f"Nada com “{texto}”.")
            self._rodape.pack(fill="x")
        elif n > self.VISIVEIS:
            total = len(self._todos)
            conta = f"{n} opções" if n == total else f"{n} de {total}"
            self._rodape.configure(
                text=f"{conta}  ·  continue digitando para estreitar")
            self._rodape.pack(fill="x")
        else:
            self._rodape.pack_forget()
        self._mostrar_realce()
        self._posicionar()

    def _mostrar_realce(self):
        """Rola a janela até a linha realçada aparecer e repinta as linhas."""
        n = len(self._achados)
        if self._realce < self._topo:
            self._topo = self._realce
        elif self._realce >= self._topo + self.VISIVEIS:
            self._topo = self._realce - self.VISIVEIS + 1
        self._topo = max(0, min(self._topo, max(n - self.VISIVEIS, 0)))
        self._pintar()

    def _pintar(self):
        c = cores()
        n = len(self._achados)
        for i, lin in enumerate(self._linhas):
            k = self._topo + i
            marcada = k == self._realce
            try:
                lin.configure(
                    text=self._achados[k] if k < n else "",
                    background=c["marca_fundo"] if marcada else c["cartao"],
                    foreground=c["marca"] if marcada else c["texto"])
            except tk.TclError:
                return
        if self._barra is not None and n > self.VISIVEIS:
            self._barra.set(self._topo / n, (self._topo + self.VISIVEIS) / n)

    def _passou_por(self, linha: int):
        """O mouse realça a mesma linha que ↑/↓ realçam: o Enter sempre
        escolhe o que está destacado."""
        k = self._topo + linha
        if k < len(self._achados) and k != self._realce:
            self._realce = k
            self._pintar()

    def _clicou_linha(self, linha: int):
        k = self._topo + linha
        if k < len(self._achados):
            self.escolher(self._achados[k])
        return "break"

    def _rolar(self, linhas: int):
        n = len(self._achados)
        novo = max(0, min(self._topo + linhas, max(n - self.VISIVEIS, 0)))
        if novo != self._topo:
            self._topo = novo
            self._pintar()

    def _roda(self, ev):
        self._rolar(-3 if ev.delta > 0 else 3)
        return "break"

    def _rolar_pela_barra(self, acao, *args):
        n = len(self._achados)
        if acao == "moveto":
            self._rolar(round(float(args[0]) * n) - self._topo)
        elif acao == "scroll":
            passo = int(args[0])
            self._rolar(passo * (self.VISIVEIS if args[1] == "pages" else 1))

    def _posicionar(self):
        top = self._popup
        if top is None:
            return
        try:
            top.update_idletasks()
            larg = max(self.winfo_width(), px(260))
            alt = top.winfo_reqheight()
            x = self.winfo_rootx()
            y = self.winfo_rooty() + self.winfo_height() + px(2)
            # Puxada para dentro da tela: com `overrideredirect` o Windows não
            # reposiciona nada sozinho. Sem espaço embaixo, abre para cima.
            x = max(min(x, top.winfo_screenwidth() - larg - px(8)), px(8))
            if y + alt > top.winfo_screenheight() - px(8):
                y = max(self.winfo_rooty() - alt - px(2), px(8))
            top.geometry(f"{larg}x{alt}+{x}+{y}")
            top.deiconify()
            self._onde = (self.winfo_rootx(), self.winfo_rooty(),
                          self.winfo_width())
        except tk.TclError:
            self.fechar_lista()

    #: De quanto em quanto tempo a lista aberta confere se o campo ainda está
    #: onde estava (a página rola, a janela anda) e se ainda tem o foco.
    VIGIA_MS = 200

    def _vigiar(self):
        """Acompanha o campo enquanto a lista está aberta.

        Ela é uma janela à parte e não anda sozinha com a página: a roda do
        mouse rola a aba (`AreaRolavel`) e a lista ficaria flutuando no lugar
        antigo. E fecha quando o foco foi para outro campo (Tab, clique) ou
        para outro programa — sem isso, `-topmost` a deixaria por cima de tudo."""
        self._vigia = None
        if self._popup is None:
            return
        try:
            foco = self.focus_get()
        except (KeyError, tk.TclError):
            foco = None
        dono = str(foco) if foco is not None else ""
        if dono != str(self) and not dono.startswith(str(self._popup)):
            self.fechar_lista()
            return
        try:
            if not self.winfo_viewable():
                self.fechar_lista()
                return
            onde = (self.winfo_rootx(), self.winfo_rooty(), self.winfo_width())
        except tk.TclError:
            self.fechar_lista()
            return
        if onde != self._onde:
            self._posicionar()
        self._vigia = self.after(self.VIGIA_MS, self._vigiar)

    def _focar_campo(self):
        try:
            if self._popup is not None:
                self.focus_set()
        except tk.TclError:
            pass

    def _clique_fora(self, ev):
        """Fecha, a não ser que o clique tenha sido no campo ou na lista —
        compara o CAMINHO do widget no Tk, que é hierárquico."""
        if self._popup is None:
            return
        alvo = str(ev.widget)
        if alvo.startswith(str(self._popup)) or alvo == str(self):
            return
        self.fechar_lista()


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
                        padx=px(7), pady=px(2))
        self.bt.pack(side="left", padx=px((3, 0)))

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
                           highlightcolor=c["borda"], padx=px(10), pady=px(9))
        moldura.pack(fill="both", expand=True)

        mes, ano = self._data_atual()
        estado = {"mes": mes, "ano": ano}
        hoje = date.today()

        cab = tk.Frame(moldura, background=c["cartao"])
        cab.pack(fill="x")
        lbl = ttk.Label(cab, text="", width=17, anchor="center",
                        style="Forte.TLabel")
        grade = tk.Frame(moldura, background=c["cartao"])
        grade.pack(pady=px((6, 0)))

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
                         font=FONTE_MINI).grid(row=0, column=i,
                                               pady=px((0, 3)))
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
                        padx=px(2), pady=px(3), cursor="hand2",
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
                    cel.grid(row=r, column=col, padx=px(1), pady=px(1))
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
              padx=px(6), pady=px(0)).pack(side="left")
        lbl.pack(side="left", expand=True)
        Botao(cab, "›", papel="link", command=lambda: mudar(1),
              padx=px(6), pady=px(0)).pack(side="right")

        rodape = tk.Frame(moldura, background=c["cartao"])
        rodape.pack(fill="x", pady=px((7, 0)))
        Botao(rodape, "Hoje", papel="link", padx=px(4), pady=px(1),
              command=ir_para_hoje).pack(side="left")
        Botao(rodape, "Limpar", papel="link", padx=px(4), pady=px(1),
              command=limpar).pack(side="right")

        desenhar()

        # Debaixo do campo, e puxado para dentro da tela quando não cabe: com
        # `overrideredirect` o Windows não reposiciona nada por conta própria,
        # e um campo perto da borda de baixo abria o calendário fora do monitor.
        top.update_idletasks()
        x = self.ent.winfo_rootx()
        y = self.ent.winfo_rooty() + self.ent.winfo_height() + px(3)
        larg, alt = top.winfo_reqwidth(), top.winfo_reqheight()
        x = max(min(x, top.winfo_screenwidth() - larg - px(8)), px(8))
        if y + alt > top.winfo_screenheight() - px(8):
            y = self.ent.winfo_rooty() - alt - px(3)
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
