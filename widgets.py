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
import re
from datetime import date

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

MESES = ("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro")

#: Iniciais dos dias na ordem em que o `calendar` do Python monta a semana
#: (segunda a domingo).
DIAS_DA_SEMANA = ("S", "T", "Q", "Q", "S", "S", "D")


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

#: Só o que o tema do sv-ttk não resolve sozinho: texto de apoio, os três
#: estados e o fundo dos campos de registro. Cada valor foi escolhido para
#: passar de 4,5:1 sobre o fundo do SEU tema.
PALETA = {
    "claro": {
        "fundo":     "#fafafa",   # o fundo do sv-ttk, contra o qual se mede
        "apoio":     "#5a5f66",   # legendas e linhas de explicação   6,1:1
        "tenue":     "#6b7079",   # versão, metadados, placeholder    4,8:1
        "ativo":     "#1a5fb4",   # está rodando agora                6,0:1
        "ok":        "#0f7b3f",   # terminou, conferiu, bateu         5,1:1
        "atencao":   "#8a5300",   # entrou, mas precisa de olho       6,0:1
        "erro":      "#b3261e",   # não entrou, falhou                6,2:1
        "log_fundo": "#ffffff",
        "log_texto": "#141414",
    },
    "escuro": {
        "fundo":     "#1c1c1c",
        "apoio":     "#a8afb8",   # 7,7:1
        "tenue":     "#9099a3",   # 5,6:1
        "ativo":     "#7cb7ff",   # 8,1:1
        "ok":        "#6cd08a",   # 8,9:1
        "atencao":   "#f0b354",   # 9,7:1
        "erro":      "#ff8a80",   # 7,4:1
        "log_fundo": "#252525",
        "log_texto": "#e6e6e6",
    },
}

#: Margem lateral das abas. Era `PADX = 14` redigitado em cada `_build`.
PADX = 14

#: Fontes nomeadas do Tk. Nome e não tupla: mudam em todo lugar de uma vez.
FONTE_TITULO = "AppTitulo"      # título da aba
FONTE_SECAO = "AppSecao"        # título de diálogo e de bloco
FONTE_APOIO = "AppApoio"        # legenda, explicação, placeholder
FONTE_MONO = "AppMono"          # campos de registro

#: Família dos campos de registro. NÃO sai do `TkFixedFont`: no Windows ele é
#: "Courier New", que é a fonte de máquina de escrever e fica larga e fraca ao
#: lado da Segoe UI. Consolas vem com o Windows desde o Vista, e era a escolha
#: que as seis abas já faziam à mão.
FAMILIA_MONO = "Consolas"

#: As fontes vivem aqui porque `tkinter.font.Font.__del__` executa um
#: `font delete` no Tcl: criar a fonte numa variável local a apagava no
#: primeiro coletor de lixo. O sintoma não é erro nenhum — o Tk passa a ler
#: "AppTitulo" como NOME DE FAMÍLIA, não acha, e cai na fonte padrão. Ou seja,
#: todo o escalonamento de tamanho sumia em silêncio.
_fontes: dict[str, tkfont.Font] = {}

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
    sem o app precisar consultá-la."""
    base = tkfont.nametofont("TkDefaultFont")
    familia = base.cget("family")
    tam = int(base.cget("size")) or 9

    for nome, fator, peso, fam in (
            (FONTE_TITULO, 1.55, "bold", familia),
            (FONTE_SECAO, 1.15, "bold", familia),
            (FONTE_APOIO, 0.92, "normal", familia),
            (FONTE_MONO, 1.0, "normal", FAMILIA_MONO)):
        alvo = dict(family=fam, size=_escalar(tam, fator), weight=peso)
        f = _fontes.get(nome)
        try:
            if f is None:
                raise tk.TclError
            f.configure(**alvo)
        except tk.TclError:              # ainda não existe, ou sobrou de um
            f = tkfont.Font(name=nome, exists=False, **alvo)   # Tk já fechado
            _fontes[nome] = f


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
    st.configure("Titulo.TLabel", font=FONTE_TITULO)
    st.configure("Secao.TLabel", font=FONTE_SECAO)
    st.configure("Apoio.TLabel", font=FONTE_APOIO, foreground=c["apoio"])
    st.configure("Tenue.TLabel", font=FONTE_APOIO, foreground=c["tenue"])
    st.configure("Ativo.TLabel", font=FONTE_APOIO, foreground=c["ativo"])
    st.configure("Ok.TLabel", foreground=c["ok"])
    st.configure("Atencao.TLabel", foreground=c["atencao"])
    st.configure("Erro.TLabel", foreground=c["erro"])

    # A trilha de passos fica no tamanho do corpo, e não no da legenda: ela é
    # navegação, não nota de rodapé. Quem separa os três estados é o SÍMBOLO
    # (✓ contra ①), porque cor sozinha não distingue nada para quem não a vê.
    st.configure("PassoFeito.TLabel", foreground=c["ok"])
    st.configure("PassoAtivo.TLabel", foreground=c["ativo"])
    st.configure("PassoFalta.TLabel", foreground=c["tenue"])

    # Cabeçalho de grupo na barra lateral. `Toolbutton` é o estilo chapado do
    # sv-ttk: sem o fundo de cartão que fazia DIÁRIO e MENSAL parecerem itens
    # clicáveis do mesmo nível dos que eles agrupam.
    st.configure("Grupo.Toolbutton", foreground=c["tenue"], font=FONTE_APOIO,
                 anchor="w", padding=(2, 4))


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


class Cabecalho(ttk.Frame):
    """Título da aba e a linha que diz para que ela serve.

    A linha de apoio não é enfeite: é o único lugar onde a aba explica o que
    faz para quem abriu o app pela primeira vez."""

    def __init__(self, pai, titulo: str, apoio: str = "", **kw):
        super().__init__(pai, **kw)
        ttk.Label(self, text=titulo, style="Titulo.TLabel").pack(anchor="w")
        self.lbl_apoio = None
        if apoio:
            self.lbl_apoio = ttk.Label(self, text=apoio, style="Apoio.TLabel",
                                       wraplength=820, justify="left")
            self.lbl_apoio.pack(anchor="w", pady=(2, 0))


class Cartao(ttk.LabelFrame):
    """Um bloco do fluxo, com o padding igual em todas as abas.

    O NÚMERO é opcional porque numerar só informa quando existe ordem de
    verdade: em Pagamentos do Dia buscar vem antes de gerar, e o "1." conta
    isso; no cartão de Registro não há passo nenhum, e numerá-lo seria
    inventar uma sequência que o usuário não precisa seguir."""

    def __init__(self, pai, titulo: str, numero: int | None = None, **kw):
        kw.setdefault("padding", (12, 8, 12, 10))
        super().__init__(pai, text=(f" {numero}. {titulo} " if numero
                                    else f" {titulo} "), **kw)


class Passos(ttk.Frame):
    """A trilha das AÇÕES da aba, logo abaixo do título.

    Por que ela existe: numerar os cartões e numerar os botões ao mesmo tempo
    põe duas contagens diferentes na mesma tela. Em Pagamentos do Dia,
    "2. Contas" é um campo para preencher e "2. Gerar a planilha" é uma ação —
    as duas apareciam como "passo 2", e nenhuma das duas contagens ia até o
    fim sozinha. Aqui o número passa a ser só da AÇÃO, e os cartões viram
    títulos sem número.

    O estado sai do `state` dos próprios botões, e não de um controle novo:
    a aba já habilita o passo seguinte quando o anterior termina, e guardar
    isso de novo criaria duas verdades sobre onde a pessoa está. Enquanto o
    trabalho roda TODOS os botões ficam desabilitados — aí a trilha segura o
    último estado conhecido, em vez de zerar e dizer que nada começou.
    """

    #: Um símbolo por passo. Nenhuma aba passa de três.
    MARCAS = "①②③④⑤"

    def __init__(self, pai, passos, **kw):
        super().__init__(pai, **kw)
        self._nomes = [nome for nome, _ in passos]
        self._botoes = [b for _, b in passos]
        self._rotulos = []
        for i, nome in enumerate(self._nomes):
            if i:
                ttk.Label(self, text="   ·   ", style="PassoFalta.TLabel"
                          ).pack(side="left")
            lbl = ttk.Label(self, text=f"{self.MARCAS[i]}  {nome}")
            lbl.pack(side="left")
            self._rotulos.append(lbl)
        self._ativo = 0
        self._pintar()

    def _pintar(self):
        try:
            livres = [str(b.cget("state")) == "normal" for b in self._botoes]
        except tk.TclError:
            return                       # aba destruída: a trilha morre junto
        if any(livres):
            self._ativo = livres.index(True)
        for i, lbl in enumerate(self._rotulos):
            if i < self._ativo:
                estilo, marca = "PassoFeito.TLabel", "✓"
            elif i == self._ativo:
                estilo, marca = "PassoAtivo.TLabel", self.MARCAS[i]
            else:
                estilo, marca = "PassoFalta.TLabel", self.MARCAS[i]
            texto = f"{marca}  {self._nomes[i]}"
            if lbl.cget("text") != texto:
                lbl.configure(text=texto)
            if str(lbl.cget("style")) != estilo:
                lbl.configure(style=estilo)
        self.after(400, self._pintar)


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
    estado = {"cheio": None, "dentro": False}

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
        except tk.TclError:
            pass                         # aba destruída no meio do caminho
        finally:
            estado["dentro"] = False

    texto.bind("<<Modified>>", _ajustar, add="+")
    _ajustar()


def estilo_log(texto: tk.Text, escuro: bool | None = None) -> None:
    """Cores e fonte do campo de registro, iguais nas seis abas que têm um.

    Existia em quatro cópias byte a byte. Também configura a tag "ph", usada
    pelo texto de tela vazia — que antes era `#8a8a8a` fixo e sumia no claro."""
    if escuro is not None:
        _estado["escuro"] = bool(escuro)
    c = cores()
    texto.configure(background=c["log_fundo"], foreground=c["log_texto"],
                    insertbackground=c["log_texto"], font=FONTE_MONO)
    texto.tag_configure("ph", justify="center", foreground=c["tenue"],
                        spacing1=6, font=FONTE_APOIO)


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


class CampoData(ttk.Frame):
    """Campo de data dd/mm/aaaa, com calendário e máscara.

    Duas formas de preencher, porque as duas aparecem no uso real:

    - DIGITAR, com as barras entrando sozinhas ("0508" vira "05/08") e o ano
      completado ao sair do campo;
    - o botão 📅 (ou um duplo clique no campo) abre o calendário.

    O calendário NÃO abre no clique simples, e isso é decisão, não descuido:
    o clique simples é como se põe o cursor para digitar. Abrindo o popup ali,
    ele roubava o clique e o campo ficava impossível de editar — foi o que
    aconteceu em 11/08/2026, em todas as abas de uma vez.

    O calendário é tkinter puro (Toplevel + grade de botões). Existe pacote
    pronto para isso (`tkcalendar`), mas dependência nova obriga a gerar um
    executável novo de ~150 MB e a subir o `motor_minimo.txt` — caro demais
    para um calendário de 60 linhas.
    """

    def __init__(self, master, textvariable, width=11):
        super().__init__(master)
        self.var = textvariable
        self._popup = None
        self.ent = ttk.Entry(self, textvariable=self.var, width=width)
        self.ent.pack(side="left")
        self.bt = ttk.Button(self, text="📅", width=3, command=self.abrir_calendario)
        self.bt.pack(side="left", padx=(2, 0))

        self.ent.bind("<KeyRelease>", self._ao_digitar)
        self.ent.bind("<Double-Button-1>", lambda _e: self.abrir_calendario())
        self.ent.bind("<FocusOut>", lambda _e: self._completar_ano())

    # ----------------------------------------------------------- digitação
    def _ao_digitar(self, ev):
        # Teclas de navegação e edição não podem remontar o texto embaixo do
        # cursor — senão apagar um dígito no meio vira uma briga com a máscara.
        if ev.keysym in ("BackSpace", "Delete", "Left", "Right", "Up", "Down",
                         "Home", "End", "Tab", "Shift_L", "Shift_R",
                         "Control_L", "Control_R"):
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
    def _data_atual(self) -> tuple[int, int]:
        """(mês, ano) que o calendário deve mostrar ao abrir."""
        hoje = date.today()
        m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", (self.var.get() or "").strip())
        if not m:
            return hoje.month, hoje.year
        mes = int(m.group(2))
        return (mes if 1 <= mes <= 12 else hoje.month), int(m.group(3))

    def _fechar_popup(self):
        if self._popup is not None:
            try:
                self._popup.grab_release()   # antes do destroy: grab preso
                self._popup.destroy()        # deixaria a janela toda surda
            except tk.TclError:
                pass
            self._popup = None

    def abrir_calendario(self):
        if self._popup is not None:       # já aberto: clicar de novo fecha
            self._fechar_popup()
            return

        top = tk.Toplevel(self)
        self._popup = top
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        top.title("Escolher data")
        barra_de_titulo(top)
        # Janela COM barra de título e modal, como era antes. A versão sem
        # borda (`overrideredirect`) parecia mais bonita e não funcionava: ela
        # nunca ganhava o foco de verdade, então o `<FocusOut>` disparava na
        # hora e o calendário fechava sozinho antes de aparecer.
        top.geometry(f"+{self.ent.winfo_rootx()}"
                     f"+{self.ent.winfo_rooty() + self.ent.winfo_height() + 2}")

        moldura = ttk.Frame(top, relief="solid", borderwidth=1, padding=6)
        moldura.pack(fill="both", expand=True)

        mes, ano = self._data_atual()
        estado = {"mes": mes, "ano": ano}

        cab = ttk.Frame(moldura); cab.pack(fill="x")
        lbl = ttk.Label(cab, text="", width=16, anchor="center")
        grade = ttk.Frame(moldura); grade.pack(pady=(4, 0))

        def escolher(dia: int):
            self.var.set(f"{dia:02d}/{estado['mes']:02d}/{estado['ano']}")
            self._fechar_popup()

        def desenhar():
            for w in grade.winfo_children():
                w.destroy()
            lbl.config(text=f"{MESES[estado['mes'] - 1]} {estado['ano']}")
            for i, inicial in enumerate(DIAS_DA_SEMANA):
                ttk.Label(grade, text=inicial, width=3, anchor="center"
                          ).grid(row=0, column=i)
            semanas = calendar.Calendar().monthdayscalendar(
                estado["ano"], estado["mes"])
            for r, semana in enumerate(semanas, 1):
                for c, dia in enumerate(semana):
                    if dia:
                        ttk.Button(grade, text=str(dia), width=3,
                                   command=lambda d=dia: escolher(d)
                                   ).grid(row=r, column=c, padx=1, pady=1)

        def mudar(delta: int):
            m2 = estado["mes"] + delta
            if m2 < 1:
                estado["mes"], estado["ano"] = 12, estado["ano"] - 1
            elif m2 > 12:
                estado["mes"], estado["ano"] = 1, estado["ano"] + 1
            else:
                estado["mes"] = m2
            desenhar()

        ttk.Button(cab, text="◀", width=3, command=lambda: mudar(-1)).pack(side="left")
        lbl.pack(side="left", expand=True)
        ttk.Button(cab, text="▶", width=3, command=lambda: mudar(1)).pack(side="right")

        rodape = ttk.Frame(moldura); rodape.pack(fill="x", pady=(4, 0))
        ttk.Button(rodape, text="Hoje", command=lambda: (
            self.var.set(f"{date.today():%d/%m/%Y}"), self._fechar_popup())
        ).pack(side="left")
        ttk.Button(rodape, text="Fechar", command=self._fechar_popup).pack(side="right")

        desenhar()
        # Escape e o X fecham. NÃO existe fechamento por `<FocusOut>`: era ele
        # que matava o calendário no instante em que abria.
        top.bind("<Escape>", lambda _e: self._fechar_popup())
        top.protocol("WM_DELETE_WINDOW", self._fechar_popup)
        try:
            top.grab_set()               # modal, como o resto dos diálogos
            top.focus_set()
        except tk.TclError:
            pass

    # ------------------------------------------------------------- tema
    def aplicar_cores(self, escuro: bool):
        """Nada a fazer: Entry e Button do ttk seguem o tema sozinhos.

        Existe para a aba poder chamar sem saber o tipo do campo."""
        return
