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
    quadros = {"sep": aba_sep, "anx": aba_anx, "conf": aba_conf,
               "apt": aba_apt, "rel": aba_rel, "pag": aba_pag, "ext": aba_ext}
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

    ttk.Label(lateral, text="🧾  Comprovantes", font=("Segoe UI", 13, "bold")
              ).pack(anchor="w", pady=(0, 14))
    botoes["sep"] = ttk.Button(lateral, text="✂   Separar e Renomear", width=24,
                               command=lambda: mostrar("sep"))
    botoes["sep"].pack(fill="x", pady=(0, 6), ipady=3)
    botoes["anx"] = ttk.Button(lateral, text="📎   Anexar Comprovantes", width=24,
                               command=lambda: mostrar("anx"))
    botoes["anx"].pack(fill="x", pady=(0, 6), ipady=3)
    botoes["conf"] = ttk.Button(lateral, text="✅   Conferência", width=24,
                                command=lambda: mostrar("conf"))
    botoes["conf"].pack(fill="x", pady=(0, 6), ipady=3)
    botoes["apt"] = ttk.Button(lateral, text="💰   Aportes", width=24,
                               command=lambda: mostrar("apt"))
    botoes["apt"].pack(fill="x", pady=(0, 6), ipady=3)
    botoes["rel"] = ttk.Button(lateral, text="📊   Relatório Mensal", width=24,
                               command=lambda: mostrar("rel"))
    botoes["rel"].pack(fill="x", pady=(0, 6), ipady=3)
    botoes["pag"] = ttk.Button(lateral, text="🗓   Pagamentos do Dia", width=24,
                               command=lambda: mostrar("pag"))
    botoes["pag"].pack(fill="x", pady=(0, 6), ipady=3)
    botoes["ext"] = ttk.Button(lateral, text="🏦   Extratos Sicoob", width=24,
                               command=lambda: mostrar("ext"))
    botoes["ext"].pack(fill="x", ipady=3)

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
        aba_anx.fechar()                # fecha o Chrome, se estiver aberto
        aba_ext.fechar()                # o Chrome do Sicoob é outro processo
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", _sair)
    root.mainloop()


if __name__ == "__main__":
    main()
