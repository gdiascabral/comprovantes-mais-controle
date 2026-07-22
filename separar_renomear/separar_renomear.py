# -*- coding: utf-8 -*-
"""
Separa PDFs (uma página = um arquivo) e renomeia os comprovantes no padrão:

  - com Descrição/Observação (centro de custo + OC/NF):  VALOR - DESCRIÇÃO - DATA
  - aporte/distribuição/transferência:                   VALOR - QUEM PAGOU PARA QUEM RECEBEU - DATA
  - PIX sem descrição (fornecedor):                       VALOR - QUEM RECEBEU - DATA

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

def nome_arquivo(c):
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
    partes = [v] + ([meio] if meio else []) + ([dd] if dd else [])
    nome = ' - '.join(partes)
    nome = re.sub(r'[<>:"/\\|?*]', '', nome).strip()
    return nome[:150] or 'SEM DADOS'


# ------------------------------------------------------------ processamento
def _destino_unico(pasta: Path, base: str) -> Path:
    alvo = pasta / f"{base}.pdf"; n = 2
    while alvo.exists():
        alvo = pasta / f"{base} ({n}).pdf"; n += 1
    return alvo

def processar(pasta_entrada, pasta_saida, log=print):
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
                base = nome_arquivo(campos(txt))
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
def abrir_gui():
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    root = tk.Tk(); root.title("Separar e Renomear Comprovantes")
    try:
        root.state("zoomed")          # ocupa a tela inteira (Windows)
    except tk.TclError:
        root.geometry("900x600")
    ent, sai = tk.StringVar(), tk.StringVar()
    q = queue.Queue()

    frm = ttk.Frame(root); frm.pack(fill="x", padx=10, pady=8)
    ttk.Label(frm, text="Pasta de ENTRADA (PDFs originais):").grid(row=0, column=0, sticky="w")
    ttk.Entry(frm, textvariable=ent, width=58).grid(row=0, column=1, sticky="we")
    ttk.Button(frm, text="…", width=3,
               command=lambda: ent.set(filedialog.askdirectory() or ent.get())).grid(row=0, column=2)
    ttk.Label(frm, text="Pasta de SAÍDA (renomeados):").grid(row=1, column=0, sticky="w", pady=6)
    ttk.Entry(frm, textvariable=sai, width=58).grid(row=1, column=1, sticky="we")
    ttk.Button(frm, text="…", width=3,
               command=lambda: sai.set(filedialog.askdirectory() or sai.get())).grid(row=1, column=2)
    frm.columnconfigure(1, weight=1)

    def preencher_saida(*_):
        if ent.get() and not sai.get():
            sai.set(str(Path(ent.get()) / "RENOMEADOS"))
    ent.trace_add("write", preencher_saida)

    barra = ttk.Progressbar(root, mode="indeterminate"); barra.pack(fill="x", padx=10)
    txt = tk.Text(root, height=20, wrap="word"); txt.pack(fill="both", expand=True, padx=10, pady=8)

    def log(m): q.put(m)
    def drain():
        try:
            while True:
                txt.insert("end", q.get_nowait() + "\n"); txt.see("end")
        except queue.Empty:
            pass
        root.after(150, drain)
    root.after(150, drain)

    def run():
        if not ent.get() or not Path(ent.get()).exists():
            messagebox.showerror("Erro", "Selecione a pasta de entrada."); return
        if not sai.get():
            sai.set(str(Path(ent.get()) / "RENOMEADOS"))
        btn.config(state="disabled"); barra.start(12); txt.delete("1.0", "end")
        def work():
            try:
                n, e = processar(ent.get(), sai.get(), log)
                q.put(f"__FIM__{n}|{e}")
            except Exception as ex:
                q.put("ERRO FATAL: " + str(ex)); q.put("__FIM__0|1")
        threading.Thread(target=work, daemon=True).start()

    def checar_fim():
        # verifica marcador de fim no texto
        conteudo = txt.get("1.0", "end")
        if "__FIM__" in conteudo:
            barra.stop(); btn.config(state="normal")
            txt.delete("1.0", "end")
            txt.insert("end", conteudo.replace("__FIM__", "Fim ("))
        root.after(400, checar_fim)
    root.after(400, checar_fim)

    btn = ttk.Button(root, text="▶ Separar e Renomear", command=run)
    btn.pack(pady=(0, 8))
    root.mainloop()


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        processar(sys.argv[1], sys.argv[2])
    else:
        abrir_gui()
