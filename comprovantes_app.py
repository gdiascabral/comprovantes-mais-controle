# -*- coding: utf-8 -*-
"""
Comprovantes — Mais Controle (app unificado)

Janela única com navegação lateral:

  Separar e Renomear   (separa páginas de PDF e renomeia os comprovantes)
  Anexar Comprovantes  (busca os pagos no Mais Controle e anexa os PDFs)

Tema claro/escuro com opção "Automático" (segue o Windows), salvo em
"preferencias.json" ao lado do executável.
"""
import json
import sys
from pathlib import Path

# Rodando como script: garante que as subpastas entram no caminho de import.
# (No executável gerado pelo PyInstaller isso não é necessário.)
_RAIZ = Path(__file__).resolve().parent
for _p in (_RAIZ / "separar_renomear", _RAIZ / "anexar", _RAIZ / "aportes",
           _RAIZ / "relatorios", _RAIZ / "pagamentos_dia",
           _RAIZ / "extratos_sicoob"):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import tkinter as tk
from tkinter import ttk

import ativacao
import widgets
from separar_renomear import SepararFrame
from anexar_comprovantes import AnexarFrame
from conferencia import ConferenciaFrame
from aportes_frame import AportesFrame
from relatorio_frame import RelatorioFrame
from pagamentos_frame import PagamentosDiaFrame
from extratos_frame import ExtratosSicoobFrame
# Pacote de verdade (tem __init__.py): importa pelo caminho completo, então não
# disputa nome de módulo no sys.path com as outras pastas de aba.
from conciliacao.frame import ConciliacaoFrame
from contratos.frame import ContratosFrame
from acessorias.frame import AcessoriasFrame


def _nitidez():
    """Deixa o texto nítido em telas de alta resolução (Windows)."""
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _versao_app():
    """Versão do código em uso (versao.txt gravado pela build)."""
    candidatos = [Path(__file__).resolve().parent]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        candidatos.append(Path(base))
        candidatos.append(Path(base) / "codigo_embutido")
    for c in candidatos:
        try:
            return (c / "versao.txt").read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return None


def _pasta_dados() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


def _carregar_prefs() -> dict:
    try:
        return json.loads((_pasta_dados() / "preferencias.json")
                          .read_text(encoding="utf-8"))
    except Exception:
        return {}


def _salvar_prefs(prefs: dict):
    try:
        (_pasta_dados() / "preferencias.json").write_text(
            json.dumps(prefs, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def _tema_do_sistema() -> str:
    """Lê a preferência de tema do Windows (claro/escuro)."""
    try:
        import winreg
        chave = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        claro, _ = winreg.QueryValueEx(chave, "AppsUseLightTheme")
        return "light" if claro else "dark"
    except Exception:
        return "light"


def main():
    _nitidez()
    _v = _versao_app()
    prefs = _carregar_prefs()
    escolha_tema = prefs.get("tema", "auto")

    root = tk.Tk()
    root.title("Comprovantes — Mais Controle" + (f"  {_v}" if _v else ""))
    try:                                 # ícone da janela (se disponível)
        for _c in (Path(__file__).resolve().parent / "icone.ico",
                   Path(getattr(sys, "_MEIPASS", ".")) / "icone.ico"):
            if _c.exists():
                root.iconbitmap(str(_c))
                break
    except Exception:
        pass
    try:
        root.state("zoomed")            # janela ocupando a tela (Windows)
    except tk.TclError:
        root.geometry("1150x740")

    try:
        import sv_ttk                   # tema moderno (visual Windows 11)
    except Exception:
        sv_ttk = None

    def tema_efetivo(escolha: str) -> str:
        if escolha == "claro":
            return "light"
        if escolha == "escuro":
            return "dark"
        return _tema_do_sistema()       # automático

    if sv_ttk:
        sv_ttk.set_theme(tema_efetivo(escolha_tema))
    # Antes de construir qualquer aba: os estilos nomeados precisam existir na
    # hora em que os widgets pedem por eles, senão a primeira tela nasce com as
    # legendas na cor padrão e só acerta na primeira troca de tema.
    widgets.aplicar_estilos(tema_efetivo(escolha_tema) == "dark")
    # Antes da janela aparecer: a barra pintada depois do primeiro desenho
    # aparece clara por um instante e escurece na frente de quem olha.
    widgets.barra_de_titulo(root, tema_efetivo(escolha_tema) == "dark")

    # ---------------- senha de primeira utilização
    # Antes de montar as abas: cada frame abre executor e estado próprios, e
    # construir tudo para depois recusar deixaria a janela piscando atrás do
    # diálogo. A principal fica escondida enquanto se pergunta; o tema já foi
    # aplicado acima, então o diálogo nasce na cor certa.
    if not ativacao.ja_ativado(_pasta_dados()):
        root.withdraw()
        if not ativacao.pedir_ativacao(root, _pasta_dados()):
            root.destroy()
            return                       # sem ativar, o app simplesmente não abre
        root.deiconify()
        try:
            root.state("zoomed")         # o withdraw desfaz a maximização
        except tk.TclError:
            pass

    # ---------------- navegação lateral + área de conteúdo
    lateral = ttk.Frame(root)
    lateral.pack(side="left", fill="y", padx=(12, 4), pady=12)
    conteudo = ttk.Frame(root)
    conteudo.pack(side="left", fill="both", expand=True)

    aba_sep = SepararFrame(conteudo)
    aba_anx = AnexarFrame(conteudo)
    aba_conf = ConferenciaFrame(conteudo, aba_anx)
    # Aportes divide o navegador e a thread do Anexar, como a Conferência:
    # o Playwright síncrono só aceita uma thread, e um segundo Chrome
    # significaria um segundo login.
    aba_apt = AportesFrame(conteudo, aba_anx)
    aba_rel = RelatorioFrame(conteudo, aba_anx)
    aba_pag = PagamentosDiaFrame(conteudo, aba_anx)
    # Extratos Sicoob NÃO recebe o aba_anx: é outro site e outro login, então
    # tem navegador e thread próprios (ver extratos_frame.py).
    aba_ext = ExtratosSicoobFrame(conteudo)
    # Conciliação volta a dividir navegador e thread do Anexar: é o mesmo ERP,
    # e ele só aceita uma sessão por usuário.
    aba_con = ConciliacaoFrame(conteudo, aba_anx)
    # Contratos usa o mesmo ERP: divide navegador e thread, como as outras.
    aba_ctr = ContratosFrame(conteudo, aba_anx)
    # Acessórias também NÃO recebe o aba_anx: é o portal do escritório
    # contábil, terceiro site e terceiro login (ver acessorias/portal.py).
    aba_acs = AcessoriasFrame(conteudo)
    quadros = {"sep": aba_sep, "anx": aba_anx, "conf": aba_conf,
               "apt": aba_apt, "rel": aba_rel, "pag": aba_pag, "ext": aba_ext,
               "con": aba_con, "ctr": aba_ctr, "acs": aba_acs}
    atual = {"nome": None}
    botoes = {}

    def mostrar(nome: str):
        if atual["nome"] == nome:
            return
        for f in quadros.values():
            f.pack_forget()
        quadros[nome].pack(fill="both", expand=True)
        atual["nome"] = nome
        for n, b in botoes.items():
            try:
                b.configure(style="Accent.TButton" if n == nome else "TButton")
            except tk.TclError:
                pass
        # Uma aba dentro de um grupo fechado ficaria selecionada e invisível na
        # barra: abre o grupo para o destaque ter onde aparecer.
        for gnome, g in grupos.items():
            if nome in g["itens"] and not g["aberto"]:
                _alternar(gnome)
        # `after_idle`: a aba acabou de ser empacotada e ainda não tem
        # geometria, e é a geometria que decide qual campo é o de cima.
        root.after_idle(lambda: _focar_primeiro(quadros[nome]))

    def _focar_primeiro(quadro):
        try:
            widgets.focar_primeiro_campo(quadro)
        except tk.TclError:
            pass                         # aba fechando enquanto o idle rodava

    ttk.Label(lateral, text="🧾  Comprovantes", style="Titulo.TLabel"
              ).pack(anchor="w", pady=(0, 14))

    # Ícone e nome ficam guardados separados porque o lugar do ícone é também
    # onde entra a marca de "esta aba está trabalhando agora" (ver `_pulso`).
    icones: dict[str, str] = {}
    nomes: dict[str, str] = {}

    def _item(pai, chave: str, icone: str, texto: str, recuo: int = 0):
        b = ttk.Button(pai, text=f"{icone}   {texto}", width=24,
                       command=lambda: mostrar(chave))
        b.pack(fill="x", padx=(recuo, 0), pady=(0, 6), ipady=3)
        botoes[chave] = b
        icones[chave] = icone
        nomes[chave] = texto

    for _chave, _icone, _texto in (("sep", "✂", "Separar e Renomear"),
                                   ("anx", "📎", "Anexar Comprovantes"),
                                   ("conf", "✅", "Conferência"),
                                   ("apt", "💰", "Aportes")):
        _item(lateral, _chave, _icone, _texto)

    # ---- grupos que abrem e fecham
    # As rotinas de fechamento são muitas para uma lista plana, e cada uma se
    # usa num ritmo diferente: as diárias todo dia, as mensais uma vez por mês.
    # O grupo aberto/fechado fica em preferencias.json — quem só faz o diário
    # não reabre o mensal toda vez.
    grupos: dict[str, dict] = {}
    prefs_grupos = prefs.get("grupos") or {}

    def _alternar(nome: str, salvar: bool = True):
        g = grupos[nome]
        g["aberto"] = not g["aberto"]
        if g["aberto"]:
            g["corpo"].pack(fill="x", after=g["cabecalho"])
        else:
            g["corpo"].pack_forget()
        g["cabecalho"].configure(text=g["titulo"](g["aberto"]))
        if salvar:
            prefs.setdefault("grupos", {})[nome] = g["aberto"]
            _salvar_prefs(prefs)

    def _grupo(nome: str, rotulo: str, itens):
        titulo = lambda aberto: f"{'▾' if aberto else '▸'}  {rotulo}"  # noqa: E731
        # Continua sendo um Button — ele abre e fecha o grupo, e trocar por um
        # Label com bind de clique tiraria o item do Tab e do Espaço. O que
        # muda é o ESTILO: chapado e miúdo, para DIÁRIO e MENSAL pararem de
        # parecer irmãos das abas que eles agrupam.
        cab = ttk.Button(lateral, style="Grupo.Toolbutton",
                         command=lambda: _alternar(nome))
        cab.pack(fill="x", pady=(14, 2))
        # O recuo é o que diz "estes pertencem àquele": sem ele, fechar o
        # grupo era a única pista de que existia um grupo.
        corpo = ttk.Frame(lateral)
        grupos[nome] = {"cabecalho": cab, "corpo": corpo, "titulo": titulo,
                        "aberto": False, "itens": [c for c, _, _ in itens]}
        for chave, icone, texto in itens:
            _item(corpo, chave, icone, texto, recuo=10)
        cab.configure(text=titulo(False))
        if prefs_grupos.get(nome, True):          # por padrão, abertos
            _alternar(nome, salvar=False)

    _grupo("diario", "DIÁRIO", (("pag", "🗓", "Pagamentos do Dia"),
                                ("con", "⚖", "Conciliação Diária")))
    _grupo("mensal", "MENSAL", (("rel", "📊", "Relatório Mensal"),
                                ("ext", "🏦", "Extratos Sicoob"),
                                ("ctr", "📑", "Contratos"),
                                ("acs", "📤", "Acessórias")))

    # ---------------- rodapé da barra: atividade + tema + versão
    rodape = ttk.Frame(lateral)
    rodape.pack(side="bottom", fill="x", pady=(10, 0))
    lbl_atividade = ttk.Label(rodape, style="Tenue.TLabel", justify="left",
                              wraplength=172, text="Navegador livre")
    lbl_atividade.pack(anchor="w", pady=(0, 10))
    ttk.Label(rodape, text="Tema").pack(anchor="w")
    combo_tema = ttk.Combobox(rodape, state="readonly", width=19,
                              values=["Automático (sistema)", "Claro", "Escuro"])
    _ordem = ["auto", "claro", "escuro"]
    combo_tema.current(_ordem.index(escolha_tema)
                       if escolha_tema in _ordem else 0)
    combo_tema.pack(pady=(2, 8))
    if _v:
        ttk.Label(rodape, text=f"versão {_v}", style="Tenue.TLabel"
                  ).pack(anchor="w")

    def aplicar_tema(escolha: str):
        efetivo = tema_efetivo(escolha)
        if sv_ttk:
            sv_ttk.set_theme(efetivo)
        # Depois do sv-ttk, nunca antes: trocar de tema recria o tema do ttk
        # inteiro e apaga todo estilo nomeado configurado até aqui.
        widgets.aplicar_estilos(efetivo == "dark")
        widgets.barra_de_titulo(root, efetivo == "dark")
        try:                             # fundo da janela na cor exata do tema
            cor = ttk.Style().lookup("TFrame", "background")
            if cor:
                root.configure(background=cor)
        except tk.TclError:
            pass
        escuro = efetivo == "dark"
        for f in quadros.values():
            try:
                f.aplicar_cores(escuro)
            except Exception:
                pass

    def trocar_tema(_=None):
        nova = _ordem[combo_tema.current()]
        prefs["tema"] = nova
        _salvar_prefs(prefs)
        aplicar_tema(nova)

    combo_tema.bind("<<ComboboxSelected>>", trocar_tema)

    # ---------------- onde o trabalho está acontecendo
    # Nove abas dividem UM navegador (o ERP aceita uma sessão por usuário), e
    # até aqui isso só aparecia quando já era tarde: a pessoa clicava numa
    # segunda aba e levava o aviso "Navegador ocupado". A barra agora responde
    # a pergunta ANTES do clique — a aba que trabalha troca o ícone por ●, e o
    # rodapé diz o que ela está fazendo.
    por_frame = {id(f): n for n, f in quadros.items()}
    _reticencias = ("", ".", "..", "...")
    pulso = {"i": 0}

    def _quem_trabalha() -> tuple[str | None, str]:
        """(aba que está com um navegador, o que ela está fazendo)."""
        for pergunta in (
                # o navegador do ERP, dividido por oito abas...
                lambda: (por_frame.get(id(aba_anx.dona_ocupada())),
                         aba_anx.ocupado()),
                # ...o do Sicoob, que é processo e login à parte...
                lambda: ("ext", aba_ext.ocupado()),
                # ...e o do portal do escritório, pelo mesmo motivo
                lambda: ("acs", aba_acs.ocupado())):
            try:
                chave, tarefa = pergunta()
            except Exception:
                continue                 # aba sem o método: só não sinaliza
            if tarefa:
                return chave, tarefa
        return None, ""

    def _pulso():
        chave, tarefa = _quem_trabalha()
        for n, b in botoes.items():
            alvo = f"{'●' if n == chave else icones[n]}   {nomes[n]}"
            if b.cget("text") != alvo:   # só toca no que mudou: reconfigurar
                b.configure(text=alvo)   # nove botões a cada 600 ms pisca
        if tarefa:
            pulso["i"] = (pulso["i"] + 1) % len(_reticencias)
            lbl_atividade.configure(
                style="Ativo.TLabel",
                text=f"▶  {tarefa}{_reticencias[pulso['i']]}")
        else:
            pulso["i"] = 0
            lbl_atividade.configure(style="Tenue.TLabel",
                                    text="Navegador livre")
        root.after(600, _pulso)

    def _enter_aciona(_ev=None):
        """Enter num campo de texto dispara o passo principal da aba.

        Só a partir de um Entry, e nunca de um Text: o registro ocupa metade
        da tela em seis abas, e Enter ali é quebra de linha para quem leu o
        resultado — não é ordem para começar meia hora de trabalho no ERP."""
        try:
            foco = root.focus_get()
        except (KeyError, tk.TclError):
            return
        if not isinstance(foco, ttk.Entry) or isinstance(foco, ttk.Combobox):
            return
        quadro = quadros.get(atual["nome"])
        # O bind é global (`bind_all`), então o campo com o foco pode estar
        # numa janela de diálogo — a de dúvidas, a de escolher contrato. Enter
        # ali é para o diálogo, não para a aba atrás dele. O caminho do widget
        # no Tk é hierárquico, e conferi-lo é o teste exato de "está dentro".
        if quadro is None or not str(foco).startswith(f"{quadro}."):
            return
        # `acao_enter` quando a aba quer nomear o que o Enter faz (nos Aportes
        # é "adicionar à lista", e não o passo 1, que fala com o ERP); senão
        # `b1` nas abas de passos numerados e `btn` nas de ação única.
        # Aba sem nenhum dos três simplesmente não responde ao Enter.
        for nome_attr in ("acao_enter", "b1", "btn"):
            b = getattr(quadro, nome_attr, None)
            if b is not None and str(b.cget("state")) == "normal":
                b.invoke()
                return

    root.bind_all("<Return>", _enter_aciona)

    aplicar_tema(escolha_tema)
    mostrar("sep")
    _pulso()

    def _sair():
        # Um `fechar()` que levanta não pode impedir o outro nem o destroy():
        # a janela ficaria aberta e sem resposta, e o jeito de sair viraria o
        # Gerenciador de Tarefas — que é justamente o que deixa Chrome órfão.
        for fechar in (aba_anx.fechar,   # Chrome do Mais Controle
                       aba_ext.fechar):  # o Chrome do Sicoob é outro processo
            try:
                fechar()
            except Exception:
                pass
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", _sair)
    root.mainloop()


if __name__ == "__main__":
    main()
