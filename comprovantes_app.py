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
    quadros = {"sep": aba_sep, "anx": aba_anx, "conf": aba_conf,
               "apt": aba_apt, "rel": aba_rel, "pag": aba_pag, "ext": aba_ext,
               "con": aba_con}
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

    ttk.Label(lateral, text="🧾  Comprovantes", font=("Segoe UI", 13, "bold")
              ).pack(anchor="w", pady=(0, 14))

    def _item(pai, chave: str, texto: str):
        b = ttk.Button(pai, text=texto, width=24, command=lambda: mostrar(chave))
        b.pack(fill="x", pady=(0, 6), ipady=3)
        botoes[chave] = b

    for _chave, _texto in (("sep", "✂   Separar e Renomear"),
                           ("anx", "📎   Anexar Comprovantes"),
                           ("conf", "✅   Conferência"),
                           ("apt", "💰   Aportes")):
        _item(lateral, _chave, _texto)

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
        titulo = lambda aberto: f"{'▾' if aberto else '▸'}   {rotulo}"  # noqa: E731
        cab = ttk.Button(lateral, width=24, command=lambda: _alternar(nome))
        cab.pack(fill="x", pady=(6, 4), ipady=3)
        corpo = ttk.Frame(lateral)
        grupos[nome] = {"cabecalho": cab, "corpo": corpo, "titulo": titulo,
                        "aberto": False, "itens": [c for c, _ in itens]}
        for chave, texto in itens:
            _item(corpo, chave, texto)
        cab.configure(text=titulo(False))
        if prefs_grupos.get(nome, True):          # por padrão, abertos
            _alternar(nome, salvar=False)

    _grupo("diario", "DIÁRIO", (("pag", "🗓   Pagamentos do Dia"),
                                ("con", "⚖   Conciliação Diária")))
    _grupo("mensal", "MENSAL", (("rel", "📊   Relatório Mensal"),
                                ("ext", "🏦   Extratos Sicoob")))

    # ---------------- rodapé da barra: tema + versão
    rodape = ttk.Frame(lateral)
    rodape.pack(side="bottom", fill="x", pady=(10, 0))
    ttk.Label(rodape, text="Tema").pack(anchor="w")
    combo_tema = ttk.Combobox(rodape, state="readonly", width=19,
                              values=["Automático (sistema)", "Claro", "Escuro"])
    _ordem = ["auto", "claro", "escuro"]
    combo_tema.current(_ordem.index(escolha_tema)
                       if escolha_tema in _ordem else 0)
    combo_tema.pack(pady=(2, 8))
    if _v:
        ttk.Label(rodape, text=f"versão {_v}", foreground="#8a8a8a"
                  ).pack(anchor="w")

    def aplicar_tema(escolha: str):
        efetivo = tema_efetivo(escolha)
        if sv_ttk:
            sv_ttk.set_theme(efetivo)
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

    aplicar_tema(escolha_tema)
    mostrar("sep")

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
