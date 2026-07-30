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

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

MODELO_PADRAO = "VALOR - DESCRIÇÃO - DATA"

_sem_acento = util.sem_acento
_fmt_dur = util.fmt_dur


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
    # o layout "impresso" (2026) tem prioridade: nele os rótulos vêm
    # separados dos valores e o parser antigo extrai dados errados
    novo = _campos_impresso(t)
    if novo and novo['valor']:
        return novo
    banco, tipo = detectar(t)
    v = _valor(t); d = _data(t); desc = _descricao(t, banco)
    if banco == 'INTER':
        pag = _nome_apos(t, 'Quem pagou'); dest = _nome_apos(t, 'Quem recebeu')
    else:
        pag = _nome_apos(t, 'Pagador')
        dest = _nome_apos(t, 'Destinat') or _nome_apos(t, 'Beneficiário') or _nome_apos(t, 'Beneficiario')
    return dict(banco=banco, tipo=tipo, valor=v, data=d, desc=desc, pag=pag, dest=dest)


# --------------------------------------------- layout "impresso" (2026)
# Sicoob Internet Banking e Inter novos geram o comprovante como página
# impressa: rótulos e valores vêm em blocos separados (e o PDF muitas
# vezes nem tem camada de texto — aí entra o OCR).
RE_DIN_L = re.compile(r"^\s*R[S$]?\$?\s*([\d\.]+,\d{2})\s*$")
RE_DATA_HORA = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(?:[àa]s\s+)?\d{2}[:h]\d{2}")
RE_DATA_SO = re.compile(r"^(\d{2}/\d{2}/\d{4})$")
RE_CNPJ_L = re.compile(r"\d{2}[\.\s]?\d{3}[\.\s]?\d{3}\s?/\s?\d{4}\s?-\s?\d{2}")
RE_DESC_SITE = re.compile(r"\b(QD|LT|OC|NF|UC|LOTE|APORTE|DISTRIBUI\w*|REF)\b")
RE_ID_LONGO = re.compile(r"^[A-Za-z0-9\-]{20,}$")


def _eh_mascara(l):
    """CPF/CNPJ mascarado (ex.: **.168.971/0001-** com ruído de OCR)."""
    return "*" in l and sum(c.isdigit() for c in l) >= 4 and len(l) < 30


def _detectar_impresso(t):
    u = _sem_acento(t).upper()
    if "SICOOB" in u and ("INTERNET BANKING" in u or "SISBR" in u
                          or "TIPO PAGAMENTO" in u):
        if "PAGAMENTO DE BOLETO" in u:
            return ("SICOOB", "BOLETO")
        if "PAGAMENTO PIX" in u or "TIPO PAGAMENTO" in u:
            return ("SICOOB", "PIX")
        return ("SICOOB", "?")
    if "SOBRE A TRANSA" in u or "FALE COM A GENTE" in u or "BANCO INTER" in u:
        return ("INTER", "PGTO")
    return (None, None)


def _campos_impresso(t):
    banco, tipo = _detectar_impresso(t)
    if not banco:
        return None
    nl = [l.strip() for l in t.splitlines() if l.strip()]

    # valor: último R$ não-zero em linha própria (boleto: é o "Pago";
    # Inter: é o "Valor total"; PIX: é o único)
    valores = [m.group(1) for l in nl for m in [RE_DIN_L.match(l)] if m]
    naozero = [v for v in valores
               if v.replace(".", "").replace(",", "").strip("0") != ""]
    valor = naozero[-1] if naozero else (valores[-1] if valores else None)

    # data: prioriza data com hora (o cabeçalho de impressão usa vírgula
    # e fica de fora); senão, data sozinha fora das 3 primeiras linhas
    datas = RE_DATA_HORA.findall(t)
    if not datas:
        for i, l in enumerate(nl):
            if i >= 3:
                m = RE_DATA_SO.match(l)
                if m:
                    datas.append(m.group(1))
    data = max(datas, key=lambda d: (datas.count(d), -datas.index(d))) if datas else None

    # descrição: linha com cara de centro de custo / OC / NF...
    desc = None
    for l in nl:
        u = _sem_acento(l).upper()
        if RE_DESC_SITE.search(u) and not RE_ID_LONGO.match(l) and len(l) < 90 \
                and "OUVIDORIA" not in u and "COMPROVANTE" not in u:
            desc = l
            break
    if desc is None and banco == "SICOOB" and tipo == "PIX" and valor:
        # ...ou, no PIX, a linha logo depois do valor
        for i, l in enumerate(nl):
            if RE_DIN_L.match(l):
                if i + 1 < len(nl):
                    cand = nl[i + 1]
                    u = _sem_acento(cand).upper()
                    digitos = sum(c.isdigit() for c in cand) / max(len(cand), 1)
                    if not RE_ID_LONGO.match(cand) and len(cand) > 2 \
                            and not u.startswith("FINALIZADO") \
                            and not u.startswith("OUVIDORIA") \
                            and "{" not in cand and "}" not in cand \
                            and digitos < 0.4:      # rejeita códigos/hashes
                        desc = cand
                break

    pag = dest = None
    if banco == "SICOOB":
        if tipo == "BOLETO":
            # nomes: linha imediatamente anterior a cada CNPJ completo
            nomes = []
            for i, l in enumerate(nl):
                if RE_CNPJ_L.search(l):
                    for j in range(i - 1, -1, -1):
                        cand = nl[j]
                        if not RE_CNPJ_L.search(cand) and len(cand) > 4 \
                                and not RE_DIN_L.match(cand):
                            if cand not in nomes:
                                nomes.append(cand)
                            break
            dest = nomes[0] if nomes else None           # beneficiário
            pag = nomes[1] if len(nomes) > 1 else None   # pagador
        else:  # PIX: nome vem na linha anterior ao CPF/CNPJ (mascarado)
            nomes = []
            for i, l in enumerate(nl):
                if (_eh_mascara(l) or RE_CNPJ_L.search(l)) and i > 0:
                    nomes.append(nl[i - 1])
            pag = nomes[0] if nomes else None
            dest = nomes[1] if len(nomes) > 1 else None
    else:  # INTER novo
        for i, l in enumerate(nl):
            u = _sem_acento(l).upper()
            if "INTER S.A" in u or "BANCO INTER" in u:
                if i > 0:
                    pag = nl[i - 1]
                break
        for i, l in enumerate(nl):
            u = _sem_acento(l).upper()
            if u.startswith("FALE COM A GENTE") or u.startswith("CAPITAIS E REGI"):
                for j in range(i - 1, -1, -1):
                    cand = nl[j]
                    if len(cand) > 4 and not RE_DIN_L.match(cand) \
                            and not cand.isdigit():
                        dest = cand
                        break
                break
    return dict(banco=banco, tipo=tipo, valor=valor, data=data, desc=desc,
                pag=pag, dest=dest)


# --------------------------------------------------------------- OCR
_OCR = {"pronto": None, "lang": "por", "avisado": False}


def _configurar_ocr() -> bool:
    try:
        import pytesseract
    except ImportError:
        return False
    import shutil
    import sys
    cands = []
    base = getattr(sys, "_MEIPASS", None)
    if base:
        cands.append(Path(base) / "tesseract" / "tesseract.exe")
    cands.append(Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"))
    achado = shutil.which("tesseract")
    if achado:
        cands.append(Path(achado))
    for c in cands:
        if c.exists():
            pytesseract.pytesseract.tesseract_cmd = str(c)
            tess = c.parent / "tessdata"
            if tess.is_dir():
                os.environ["TESSDATA_PREFIX"] = str(tess)
            try:
                langs = set(pytesseract.get_languages(config=""))
            except Exception:
                langs = set()
            _OCR["lang"] = "por" if "por" in langs else "eng"
            return True
    return False


def _ocr_pagina(pagina, log=print) -> str:
    """OCR de uma página sem camada de texto (comprovantes 'impressos')."""
    if _OCR["pronto"] is None:
        _OCR["pronto"] = _configurar_ocr()
    if not _OCR["pronto"]:
        if not _OCR["avisado"]:
            log("[aviso] Comprovante sem texto e OCR indisponível — use o "
                "executável (já traz o OCR) ou instale o Tesseract OCR.")
            _OCR["avisado"] = True
        return ""
    import pytesseract
    img = pagina.to_image(resolution=300).original
    return pytesseract.image_to_string(img, lang=_OCR["lang"])

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
        try:
            pl = pdfplumber.open(str(pdf_path))   # abre UMA vez por arquivo
        except Exception as e:
            log(f"[ERRO] abrir {pdf_path.name}: {e}"); erros += 1; continue
        with pl:
            for i in range(n):
                try:
                    pagina = pl.pages[i]
                    txt = pagina.extract_text() or ''
                    if len(txt.strip()) < 30:      # sem camada de texto -> OCR
                        lido = _ocr_pagina(pagina, log)
                        if lido.strip():
                            txt = lido
                            log(f"  [OCR] {pdf_path.name} pág {i+1}")
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
    log(f"\nConcluído: {total_paginas} comprovante(s) gerado(s) em "
        f"{str(pasta_saida).replace(chr(92), '/')}"
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
        try:                             # já nasce na cor do tema (sem flash)
            self.aplicar_cores(util.cor_escura(ttk.Style().lookup("TFrame", "background")))
        except Exception:
            pass
        self.after(150, self._drain)

    def _montar(self):
        frm = ttk.Frame(self); frm.pack(fill="x", padx=10, pady=8)
        ttk.Label(frm, text="Pasta de ENTRADA (PDFs originais):").grid(row=0, column=0, sticky="w")
        ttk.Entry(frm, textvariable=self.ent, width=64).grid(row=0, column=1, sticky="w", padx=(6, 0))
        ttk.Button(frm, text="Selecionar…",
                   command=lambda: self.ent.set(
                       (filedialog.askdirectory() or self.ent.get()).replace("\\", "/"))
                   ).grid(row=0, column=2, padx=6, sticky="w")
        ttk.Label(frm, text="Pasta de SAÍDA (renomeados):").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(frm, textvariable=self.sai, width=64).grid(row=1, column=1, sticky="w", padx=(6, 0))
        ttk.Button(frm, text="Selecionar…",
                   command=lambda: self.sai.set(
                       (filedialog.askdirectory() or self.sai.get()).replace("\\", "/"))
                   ).grid(row=1, column=2, padx=6, sticky="w")
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
        self.lbl_dica = ttk.Label(
            nome, text="Use as palavras VALOR, DESCRIÇÃO, DATA, PAGADOR e RECEBEDOR "
                       "na ordem que quiser (ex.: DATA - VALOR - RECEBEDOR). "
                       "Inclua sempre o VALOR: é ele que permite o casamento "
                       "automático na hora de anexar.",
            foreground="#555")
        self.lbl_dica.grid(row=2, column=0, columnspan=2, sticky="w", padx=8, pady=(0, 4))
        nome.columnconfigure(1, weight=1)

        self.barra = ttk.Progressbar(self, mode="indeterminate")
        self.barra.pack(fill="x", padx=10)
        self.txt = tk.Text(self, height=18, wrap="word", relief="flat",
                           borderwidth=0, highlightthickness=1,
                           highlightbackground="#d0d0d0", background="#ffffff",
                           font=("Consolas", 10))
        self.txt.pack(fill="both", expand=True, padx=10, pady=8)
        self.btn = ttk.Button(self, text="▶ Separar e Renomear", command=self._executar)
        self.btn.pack(pady=(0, 10), ipadx=14)
        try:
            self.btn.configure(style="Accent.TButton")   # botão azul (tema sv-ttk)
        except tk.TclError:
            pass

    def aplicar_cores(self, escuro: bool):
        """Ajusta as cores dos widgets clássicos ao tema claro/escuro."""
        if escuro:
            self.txt.configure(background="#252525", foreground="#e6e6e6",
                               insertbackground="#e6e6e6",
                               highlightbackground="#3a3a3a")
            self.lbl_dica.configure(foreground="#9a9a9a")
        else:
            self.txt.configure(background="#ffffff", foreground="#000000",
                               insertbackground="#000000",
                               highlightbackground="#d0d0d0")
            self.lbl_dica.configure(foreground="#555555")

    def _sugerir_saida(self, *_):
        if self.ent.get() and not self.sai.get():
            self.sai.set(str(Path(self.ent.get()) / "RENOMEADOS").replace("\\", "/"))

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
            self.sai.set(str(Path(self.ent.get()) / "RENOMEADOS").replace("\\", "/"))
        modelo = None if self.v_tipo_nome.get() == "padrao" else self.v_modelo.get()
        self.btn.config(state="disabled"); self.barra.start(12)
        self.txt.delete("1.0", "end")

        def work():
            import time as _t
            inicio = _t.time()
            self._log(f"⏱ Início: {_t.strftime('%H:%M:%S')}")
            try:
                processar(self.ent.get(), self.sai.get(), self._log, modelo)
            except Exception as ex:
                self._log("ERRO FATAL: " + str(ex))
            self._log(f"⏱ Fim: {_t.strftime('%H:%M:%S')} — tempo total: "
                      f"{_fmt_dur(_t.time() - inicio)}")
            self.fila.put(("fim", None))
        threading.Thread(target=work, daemon=True).start()


def main():
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)   # texto nítido em telas HiDPI
    except Exception:
        pass
    root = tk.Tk(); root.title("Separar e Renomear Comprovantes")
    try:
        root.state("zoomed")          # ocupa a tela inteira (Windows)
    except tk.TclError:
        root.geometry("900x620")
    try:
        import sv_ttk                 # tema moderno (visual Windows 11)
        sv_ttk.set_theme("light")
    except Exception:
        pass
    SepararFrame(root).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3:
        processar(sys.argv[1], sys.argv[2],
                  modelo=(sys.argv[3] if len(sys.argv) > 3 else None))
    else:
        main()
