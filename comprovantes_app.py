# -*- coding: utf-8 -*-
"""
Comprovantes — Mais Controle (app unificado)

Junta os dois aplicativos numa única janela, separados por abas:

  Aba 1: Separar e Renomear   (separa páginas de PDF e renomeia os comprovantes)
  Aba 2: Anexar Comprovantes  (busca os pagos no Mais Controle e anexa os PDFs)
"""
import sys
from pathlib import Path

# Rodando como script: garante que as subpastas entram no caminho de import.
# (No executável gerado pelo PyInstaller isso não é necessário.)
_RAIZ = Path(__file__).resolve().parent
for _p in (_RAIZ / "separar_renomear", _RAIZ / "anexar"):
    if _p.is_dir() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import tkinter as tk
from tkinter import ttk

from separar_renomear import SepararFrame
from anexar_comprovantes import AnexarFrame


def _nitidez():
    """Deixa o texto nítido em telas de alta resolução (Windows)."""
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass


def _versao_app():
    """Versão do código em uso (versao.txt ao lado deste arquivo, gravado
    pela build; no motor, dentro da pasta de código)."""
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


def main():
    _nitidez()
    _v = _versao_app()
    root = tk.Tk()
    root.title("Comprovantes — Mais Controle" + (f"  {_v}" if _v else ""))
    try:
        root.state("zoomed")            # janela ocupando a tela (Windows)
    except tk.TclError:
        root.geometry("1150x740")
    try:
        import sv_ttk                   # tema moderno (visual Windows 11)
        sv_ttk.set_theme("light")
    except Exception:
        pass

    if _v:   # rótulo discreto com a versão, no canto inferior direito
        ttk.Label(root, text=f"versão {_v}", foreground="#8a8a8a"
                  ).pack(side="bottom", anchor="e", padx=10, pady=(0, 3))

    abas = ttk.Notebook(root)
    aba_sep = SepararFrame(abas)
    aba_anx = AnexarFrame(abas)
    abas.add(aba_sep, text="  1. Separar e Renomear  ")
    abas.add(aba_anx, text="  2. Anexar Comprovantes  ")
    abas.pack(fill="both", expand=True)

    def _sair():
        aba_anx.fechar()                # fecha o Chrome, se estiver aberto
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", _sair)
    root.mainloop()


if __name__ == "__main__":
    main()
