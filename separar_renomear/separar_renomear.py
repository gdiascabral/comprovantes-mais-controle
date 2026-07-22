# -*- coding: utf-8 -*-
"""
Separa PDFs (uma página = um arquivo) e renomeia os comprovantes.

Modelo de nome PADRÃO:

  - com Descrição/Observação (centro de custo + OC/NF):  VALOR - DESCRIÇÃO - DATA
  - aporte/distribuição/transferência:                   VALOR - QUEM PAGOU PARA QUEM RECEBEU - DATA
  - PIX sem descrição (fornecedor):                       VALOR - QUEM RECEBEU - DATA

Também aceita um modelo personalizado escrito com as palavras-chave
VALOR, DESCRIÇÃO, DATA, PAGADOR e RECEBEDOR (ex.: "DATA - VALOR - RECEBEDOR").

Cobre SICOOB (PIX / Boleto / Convênio) e Inter (PIX / Pagamento / Boleto-Guia).
Todos os arquivos renomeados vão para UMA pasta só.
"""
import os
import re
import queue
import threading
from pathlib import Path

import pdfplumber
from pypdf import PdfReader, PdfWriter

MODELO_PADRAO = "VALOR - DESCRIÇÃO - DATA"


# ------------------------------------------------------------ extração
def _linhas(t): return [l.rstrip() for l in t.splitlines()]

def detectar(t):
    u = t.upper()
    if 'PIX ENVIADO' in u: return ('INTER', 'PIX')
    if 'PAGAMENTO REALIZADO' in u: return ('INTER', 'PGTO')
    if 'EFETIVAÇÃO DE PAGAMENTO PIX' in u or 'EFETIVACAO DE PAGAMENTO PIX' in u: return ('SICOOB', 'PIX')
    if 'PAGAMENTO DE BOLETO' in u: return ('SICOOB', 'BOLETO')
    if 'PAGAMENTO DE CONVÊNIO' in u or 'PAGAMENTO DE CONVENIO' in u: return ('SICOOB', 'CONVENIO')
    return ('?', '?')

def _valor(t):
    for pat in [r'Valor total:?\s*R\$\s*([\d\.]+,\d{2})',
                r'Valor:\s*R\$\s*([\d\.]+,\d{2})',
                r'Pago:\s*R\$\s*([\d\.]+,\d{2})',
                r'(?m)^\s*R\$\s*([\d\.]+,\d{2})\s*$']:
        m = re.search(pat, t)
        if m: return m.group(1)
    return None

def _data(t):
    for pat in [r'Data do [Pp]agamento[^\d]{0,12}(\d{2}/\d{2}/\d{4})',
                r'Realizado:\s*(\d{2}/\d{2}/\d{4})']:
        m = re.search(pat, t)
        if m: return m.group(1)
    return None

def _nome_apos(t, rotulo):
    i = t.find(rotulo)
    if i < 0: return None
    m = re.search(r'Nome(?:/Raz[ãa]o\s*[Ss]ocial)?:?\s*(.+)', t[i:])
    return m.group(1).strip() if m else None

def _descricao(t, banco):
    if banco == 'INTER':
        m = re.search(r'Descri[çc][ãa]o\s+(.+)', t)
        return m.group(1).strip() if m else None
    L = _linhas(t)
    for i, l in enumerate(L):
        m = re.match(r'(?:Descri[çc][ãa]o|Observa[çc][ãa]o):\s*(.*)', l.strip())
        if m:
            resto = m.group(1).strip()
            if resto:
                return resto
            ant = L[i - 1].strip() if i > 0 else ''
            prox = L[i + 1].strip() if i + 1 < len(L) else ''
            return (ant + ' ' + prox).strip()
    return None

def _limpar_empresa(nome):
    if not nome: return ''
    nome = re.sub(r'\b(LTDA|SPE|S/?A|S\.A|EIRELI|ME|EPP)\b\.?', '', nome, flags=re.I)
    return re.sub(r'\s+', ' ', nome).strip(' .-')

def campos(t):
    banco, tipo = detectar(t)
    v = _valor(t); d = _data(t); desc = _descricao(t, banco)
    if banco == 'INTER':
        pag = _nome_apos(t, 'Quem pagou'); dest = _nome_apos(t, 'Quem recebeu')
    else:
        pag = _nome_apos(t, 'Pagador')
        dest = _nome_apos(t, 'Destinat') or _nome_apos(t, 'Beneficiário') or _nome_apos(t, 'Beneficiario')
    return dict(banco=banco, tipo=tipo, valor=v, data=d, desc=desc, pag=pag, dest=dest)

def _partes_nome(c):
    """Retorna (valor, 'miolo' inteligente do nome, data dd-mm)."""
    v = (c['valor'] or 'SEM VALOR').replace('.', '')
    dd = ''
    if c['data']:
        p = c['data'].split('/'); dd = p[0] + '-' + p[1]
    desc = c['desc']
    aporte = re.search(r'\b(APORTE|DISTRIBUI|TRANSF)', (desc or '').upper())
    if desc and not aporte:
        meio = desc
    else:
        pag = _limpar_empresa(c['pag']); dest = _limpar_empresa(c['dest'])
        if desc and aporte and pag and dest:
            meio = f"{pag} PARA {dest}"
        elif dest:
            meio = dest
        else:
            meio = desc or 'SEM DESCRICAO'
    meio = re.sub(r'\s+', ' ', (meio or '')).strip()
    return v, meio, dd

def nome_arquivo(c, modelo: str | None = None) -> str:
    """Monta o nome do arquivo. modelo=None (ou igual ao padrão) usa o
    comportamento clássico; senão substitui as palavras-chave do modelo."""
    v, meio, dd = _partes_nome(c)
    usar_padrao = not modelo or modelo.strip().upper() in ("", MODELO_PADRAO.upper())
    if usar_padrao:
        partes = [v] + ([meio] if meio else []) + ([dd] if dd else [])
        nome = ' - '.join(partes)
    else:
        nome = modelo
        for token, valor in (("DESCRIÇÃO", meio), ("DESCRICAO", meio),
                             ("RECEBEDOR", _limpar_empresa(c['dest']) or 'SEM RECEBEDOR'),
                             ("PAGADOR", _limpar_empresa(c['pag']) or 'SEM PAGADOR'),
                             ("VALOR", v),
                             ("DATA", dd or 'SEM DATA')):
            nome = nome.replace(token, valor)
        nome = re.sub(r'\s+', ' ', nome)
    nome = re.sub(r'[<>:"/\\|?*]', '', nome).strip()
    return nome[:150] or 'SEM DADOS'


# ------------------------------------------------------------ processamento
def _destino_unico(pasta: Path, base: str) -> Path:
    alvo = pasta / f"{base}.pdf"; n = 2
    while alvo.exists():
        alvo = pasta / f"{base} ({n}).pdf"; n += 1
    return alvo

def processar(pasta_entrada, pasta_saida, log=print, modelo: str | None = None):
    pasta_entrada = Path(pasta_entrada); pasta_saida = Path(pasta_saida)
    pasta_saida.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(p for p in pasta_entrada.glob("*.pdf"))
    total_paginas = 0; erros = 0
    log(f"{len(pdfs)} arquivo(s) PDF na pasta de entrada.")
    for pdf_path in pdfs:
        if pasta_saida in pdf_path.parents or pdf_path.parent == pasta_saida:
            continue  # não reprocessa a própria saída
        try:
            reader = PdfReader(str(pdf_path))
            n = len(reader.pages)
        except Exception as e:
            log(f"[ERRO] abrir {pdf_path.name}: {e}"); erros += 1; continue
        for i in range(n):
            try:
                with pdfplumber.open(str(pdf_path)) as pl:
                    txt = pl.pages[i].extract_text() or ''
                base = nome_arquivo(campos(txt), modelo)
                w = PdfWriter(); w.add_page(reader.pages[i])
                destino = _destino_unico(pasta_saida, base)
                with open(destino, 'wb') as fh:
                    w.write(fh)
                total_paginas += 1
                if total_paginas % 25 == 0:
                    log(f"  ... {total_paginas} páginas processadas")
            except Exception as e:
                log(f"[ERRO] {pdf_path.name} pág {i+1}: {e}"); erros += 1
    log(f"\nConcluído: {total_paginas} comprovante(s) gerado(s) em {pasta_saida}"
        + (f" | {erros} erro(s)" if erros else ""))
    return total_paginas, erros


# ------------------------------------------------------------ GUI
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


class SepararFrame(ttk.Frame):
    """Conteúdo do app Separar e Renomear (usável sozinho ou como aba)."""

    def __init__(self, master):
        super().__init__(master)
        self.ent, self.sai = tk.StringVar(), tk.StringVar()
        self.v_tipo_nome = tk.StringVar(value="padrao")
        self.v_modelo = tk.StringVar(value=MODELO_PADRAO)
        self.fila = queue.Queue()
        self._montar()
        self.after(150, self._drain)

    def _montar(self):
        frm = ttk.Frame(self); frm.pack(fill="x", padx=10, pady=8)
        ttk.Label(frm, text="Pasta de ENTRADA (PDFs originais):").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.ent, width=58).grid(row=0, column=1, sticky="we")
        ttk.Button(frm, text="…", width=3,
                   command=lambda: self.ent.set(filedialog.askdirectory() or self.ent.get())).grid(row=0, column=2)
        ttk.Label(frm, text="Pasta de SAÍDA (renomeados):").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(frm, textvariable=self.sai, width=58).grid(row=1, column=1, sticky="we")
        ttk.Button(frm, text="…", width=3,
                   command=lambda: self.sai.set(filedialog.askdirectory() or self.sai.get())).grid(row=1, column=2)
        frm.columnconfigure(1, weight=1)
        self.ent.trace_add("write", self._sugerir_saida)

        nome = ttk.LabelFrame(self, text=" Nome dos arquivos ")
        nome.pack(fill="x", padx=10, pady=4)
        ttk.Radiobutton(nome, text=f"PADRÃO: {MODELO_PADRAO}",
                        variable=self.v_tipo_nome, value="padrao"
                        ).grid(row=0, column=0, sticky="w", padx=8)
        ttk.Radiobutton(nome, text="Personalizado:",
                        variable=self.v_tipo_nome, value="custom"
                        ).grid(row=1, column=0, sticky="w", padx=8)
        ttk.Entry(nome, textvariable=self.v_modelo, width=50
                  ).grid(row=1, column=1, sticky="we", padx=4)
        ttk.Label(nome, text="Use as palavras VALOR, DESCRIÇÃO, DATA, PAGADOR e RECEBEDOR "
                             "na ordem que quiser (ex.: DATA - VALOR - RECEBEDOR). "
                             "Inclua sempre o VALOR: é ele que permite o casamento "
                             "automático na hora de anexar.",
                  foreground="#555"
                  ).grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        nome.columnconfigure(1, weight=1)

        self.barra = ttk.Progressbar(self, mode="indeterminate")
        self.barra.pack(fill="x", padx=10)
        self.txt = tk.Text(self, height=18, wrap="word")
        self.txt.pack(fill="both", expand=True, padx=10, pady=8)
        self.btn = ttk.Button(self, text="▶ Separar e Renomear", command=self._executar)
        self.btn.pack(pady=(0, 8))

    def _sugerir_saida(self, *_):
        if self.ent.get() and not self.sai.get():
            self.sai.set(str(Path(self.ent.get()) / "RENOMEADOS"))

    def _log(self, m):
        self.fila.put(("log", m))

    def _drain(self):
        try:
            while True:
                kind, m = self.fila.get_nowait()
                if kind == "log":
                    self.txt.insert("end", m + "\n"); self.txt.see("end")
                else:
                    self.barra.stop(); self.btn.config(state="normal")
        except queue.Empty:
            pass
        self.after(150, self._drain)

    def _executar(self):
        if not self.ent.get() or not Path(self.ent.get()).exists():
            messagebox.showerror("Erro", "Selecione a pasta de entrada."); return
        if not self.sai.get():
            self.sai.set(str(Path(self.ent.get()) / "RENOMEADOS"))
        modelo = None if self.v_tipo_nome.get() == "padrao" else self.v_modelo.get()
        self.btn.config(state="disabled"); self.barra.start(12)
        self.txt.delete("1.0", "end")

        def work():
            try:
                processar(self.ent.get(), self.sai.get(), self._log, modelo)
            except Exception as ex:
                self._log("ERRO FATAL: " + str(ex))
            self.fila.put(("fim", None))
        threading.Thread(target=work, daemon=True).start()


def main():
    root = tk.Tk(); root.title("Separar e Renomear Comprovantes")
    try:
        root.state("zoomed")          # ocupa a tela inteira (Windows)
    except tk.TclError:
        root.geometry("900x620")
    SepararFrame(root).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        processar(sys.argv[1], sys.argv[2],
                  modelo=(sys.argv[3] if len(sys.argv) > 3 else None))
    else:
        main()
