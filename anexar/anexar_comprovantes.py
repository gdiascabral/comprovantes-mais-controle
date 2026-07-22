# -*- coding: utf-8 -*-
"""
Anexar Comprovantes — Mais Controle

Fluxo da janela:
  1) "Abrir Mais Controle e acessar": abre o Chrome em tela cheia e você faz
     login (só na 1ª vez; o perfil fica salvo).
  2) Informe o PERÍODO (data de pagamento dos comprovantes) e a PASTA dos
     PDFs renomeados (padrão "VALOR - DESCRIÇÃO - DATA") e clique em
     "Carregar contas do período" — o app busca os títulos PAGOS do período.
  3) Marque as CONTAS BANCÁRIAS desejadas (caixas de seleção).
  4) "Casar e anexar": verifica quem já tem comprovante (pula), casa os
     pendentes com os PDFs e anexa. No fim, gera um relatório Excel.

Modo alternativo "Por lista": anexa a partir de um CSV (launchId,valor,arquivo_pdf)
ou de um Excel com aba CERTEZA (coluna link + PDF(s)).
"""
import queue
import re
import threading
import traceback
from datetime import date, datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

try:
    from . import config, matcher, mc_api, planilha
    from .mc_client import MCClient
except ImportError:
    import config, matcher, mc_api, planilha
    from mc_client import MCClient

LINK = config.MC_URL_BASE + "/#/payable-installments/"


def _norm(s):
    import unicodedata
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.upper()


def _data_api(txt: str) -> str | None:
    """'dd/mm/aaaa' -> 'aaaa-mm-dd' (aceita também dd-mm-aaaa)."""
    m = re.match(r"^\s*(\d{2})[/-](\d{2})[/-](\d{4})\s*$", txt or "")
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _fmt_val(cents: int) -> str:
    return f"{cents // 100},{cents % 100:02d}"


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Anexar Comprovantes — Mais Controle")
        try:
            self.state("zoomed")            # janela ocupando a tela (Windows)
        except tk.TclError:
            self.geometry("1100x720")
        self.q = queue.Queue()
        self.worker = None
        self.mc = None                       # MCClient aberto entre as etapas
        self.api = None
        self.pagos = []                      # registros de montar_pagos()
        self.vars_contas: dict[str, tk.BooleanVar] = {}

        hoje = date.today()
        self.v_ini = tk.StringVar(value=hoje.replace(day=1).strftime("%d/%m/%Y"))
        self.v_fim = tk.StringVar(value=hoje.strftime("%d/%m/%Y"))
        self.v_pasta = tk.StringVar()
        self.v_lista = tk.StringVar()
        self.v_modo = tk.StringVar(value="auto")
        self.v_dry = tk.BooleanVar(value=False)
        self.v_ign = tk.BooleanVar(value=True)
        self._build()
        self.after(150, self._drain)
        self.protocol("WM_DELETE_WINDOW", self._fechar)

    # ---------------------------------------------------------------- layout
    def _build(self):
        pad = {"padx": 10, "pady": 4}
        topo = ttk.Frame(self); topo.pack(fill="x", **pad)

        ttk.Radiobutton(topo, text="Automático (casar pelos nomes dos PDFs)",
                        variable=self.v_modo, value="auto",
                        command=self._alternar_modo).grid(row=0, column=0, sticky="w", columnspan=2)
        ttk.Radiobutton(topo, text="Por lista pronta (.csv / .xlsx)",
                        variable=self.v_modo, value="lista",
                        command=self._alternar_modo).grid(row=0, column=2, sticky="w", columnspan=2)

        # ---- modo automático
        self.f_auto = ttk.LabelFrame(self, text=" 1. Período e pasta dos comprovantes ")
        self.f_auto.pack(fill="x", **pad)
        fa = self.f_auto
        ttk.Label(fa, text="Data de pagamento — de:").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(fa, textvariable=self.v_ini, width=12).grid(row=0, column=1, sticky="w")
        ttk.Label(fa, text="até:").grid(row=0, column=2, sticky="e")
        ttk.Entry(fa, textvariable=self.v_fim, width=12).grid(row=0, column=3, sticky="w")
        ttk.Label(fa, text="(dd/mm/aaaa)").grid(row=0, column=4, sticky="w")
        ttk.Label(fa, text="Pasta dos PDFs renomeados:").grid(row=1, column=0, sticky="w", padx=8)
        ttk.Entry(fa, textvariable=self.v_pasta, width=70).grid(row=1, column=1, columnspan=3, sticky="we")
        ttk.Button(fa, text="Selecionar…",
                   command=lambda: self.v_pasta.set(filedialog.askdirectory() or self.v_pasta.get())
                   ).grid(row=1, column=4, padx=6)
        ttk.Checkbutton(fa, text="Ignorar tarifas bancárias, IOF, cesta, aportes, "
                                 "distribuição de lucros e pacote de serviços",
                        variable=self.v_ign).grid(row=2, column=0, columnspan=5, sticky="w", padx=8)
        fa.columnconfigure(3, weight=1)

        self.f_contas = ttk.LabelFrame(self, text=" 2. Contas bancárias (marque as desejadas) ")
        self.f_contas.pack(fill="x", **pad)
        self.contas_box = ttk.Frame(self.f_contas)
        self.contas_box.pack(fill="x", padx=8, pady=4)
        ttk.Label(self.contas_box,
                  text="Clique em \"2. Carregar contas do período\" para listar as contas."
                  ).pack(anchor="w")

        # ---- modo lista
        self.f_lista = ttk.LabelFrame(self, text=" Lista pronta ")
        fl = self.f_lista
        ttk.Label(fl, text="Arquivo (.csv ou .xlsx):").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        ttk.Entry(fl, textvariable=self.v_lista, width=70).grid(row=0, column=1, sticky="we")
        ttk.Button(fl, text="Selecionar…", command=self._sel_lista).grid(row=0, column=2, padx=6)
        fl.columnconfigure(1, weight=1)

        # ---- ações
        acoes = ttk.Frame(self); acoes.pack(fill="x", **pad)
        ttk.Checkbutton(acoes, text="Simular (não anexa de verdade)",
                        variable=self.v_dry).pack(side="left")
        self.b0 = ttk.Button(acoes, text="▶ 1. Abrir Mais Controle e acessar",
                             command=self.abrir_mc)
        self.b0.pack(side="left", padx=10)
        self.b1 = ttk.Button(acoes, text="▶ 2. Carregar contas do período",
                             command=self.conectar)
        self.b1.pack(side="left")
        self.b2 = ttk.Button(acoes, text="▶ 3. Casar e anexar", command=self.executar,
                             state="disabled")
        self.b2.pack(side="left", padx=10)
        self.lbl = ttk.Label(acoes, text="Pronto.")
        self.lbl.pack(side="left", padx=14)

        self.pb = ttk.Progressbar(self, mode="determinate")
        self.pb.pack(fill="x", **pad)
        ttk.Label(self, text="Registro:").pack(anchor="w", padx=10)
        self.log = tk.Text(self, wrap="word")
        self.log.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self._alternar_modo()

    def _alternar_modo(self):
        if self.v_modo.get() == "auto":
            self.f_lista.pack_forget()
            self.b1.config(state="normal")
        else:
            self.f_lista.pack(fill="x", padx=10, pady=4, after=self.f_auto)
            self.b2.config(state="normal")

    def _sel_lista(self):
        f = filedialog.askopenfilename(filetypes=[("Lista", "*.csv *.xlsx")])
        if f:
            self.v_lista.set(f)

    def _log(self, msg):
        self.q.put(("log", msg))

    # ---------------------------------------------------------------- etapa 1
    def abrir_mc(self):
        if self.worker and self.worker.is_alive():
            return
        self.b0.config(state="disabled")
        self.worker = threading.Thread(target=self._t_abrir, daemon=True)
        self.worker.start()

    def _t_abrir(self):
        try:
            if self.mc is None:
                self._log("Abrindo o Chrome... faça login no Mais Controle se for pedido.")
                self.mc = MCClient().__enter__()
                self.api = mc_api.MCApi(self.mc.page)
            self.mc.garantir_login()
            self._log("Mais Controle aberto. Agora confira o período e a pasta dos "
                      "PDFs e clique em \"2. Carregar contas do período\".")
        except Exception as e:
            self._log("ERRO: " + str(e) + "\n" + traceback.format_exc())
            self.mc = None
        self.q.put(("reabilitar0", None))

    # ---------------------------------------------------------------- etapa 2
    def conectar(self):
        ini, fim = _data_api(self.v_ini.get()), _data_api(self.v_fim.get())
        if not ini or not fim:
            messagebox.showerror("Erro", "Datas inválidas. Use dd/mm/aaaa."); return
        if self.v_modo.get() == "auto" and not Path(self.v_pasta.get() or "").is_dir():
            messagebox.showerror("Erro", "Selecione a pasta dos PDFs renomeados."); return
        self.b1.config(state="disabled")
        self.log.delete("1.0", "end")
        self.worker = threading.Thread(target=self._t_conectar, args=(ini, fim), daemon=True)
        self.worker.start()

    def _t_conectar(self, ini, fim):
        try:
            if self.mc is None:
                self._log("Abrindo o Chrome... faça login no Mais Controle se for pedido.")
                self.mc = MCClient().__enter__()
                self.api = mc_api.MCApi(self.mc.page)
                self.mc.garantir_login()
            if not self.api.capturar_credenciais(self._log):
                raise RuntimeError("Não capturei a lista de pagamentos.")
            self._log(f"Buscando títulos PAGOS de {ini} a {fim} (todas as contas)...")
            lanc = self.api.listar_pagos(ini, fim, self._log)
            self.pagos = mc_api.montar_pagos(lanc)
            contas = sorted({p["conta"] for p in self.pagos if p["conta"]})
            self._log(f"{len(lanc)} lançamento(s), {len(self.pagos)} pagamento(s), "
                      f"{len(contas)} conta(s) encontradas.")
            self.q.put(("contas", contas))
        except Exception as e:
            self._log("ERRO: " + str(e) + "\n" + traceback.format_exc())
            self.q.put(("reabilitar", None))

    def _montar_contas(self, contas):
        for w in self.contas_box.winfo_children():
            w.destroy()
        self.vars_contas = {}
        cont = {c: 0 for c in contas}
        for p in self.pagos:
            if p["conta"] in cont:
                cont[p["conta"]] += 1
        colunas = 3
        for i, c in enumerate(contas):
            v = tk.BooleanVar(value=True)
            self.vars_contas[c] = v
            ttk.Checkbutton(self.contas_box, text=f"{c}  ({cont[c]})", variable=v
                            ).grid(row=i // colunas, column=i % colunas, sticky="w", padx=4)
        linha = len(contas) // colunas + 1
        ttk.Button(self.contas_box, text="Marcar todas",
                   command=lambda: [v.set(True) for v in self.vars_contas.values()]
                   ).grid(row=linha, column=0, sticky="w", pady=4)
        ttk.Button(self.contas_box, text="Desmarcar todas",
                   command=lambda: [v.set(False) for v in self.vars_contas.values()]
                   ).grid(row=linha, column=1, sticky="w")

    # ---------------------------------------------------------------- etapa 2
    def executar(self):
        if self.worker and self.worker.is_alive():
            return
        if self.v_modo.get() == "lista":
            if not Path(self.v_lista.get() or "").exists():
                messagebox.showerror("Erro", "Selecione a lista (.csv/.xlsx)."); return
            alvo = self._t_lista
        else:
            if not self.pagos:
                messagebox.showerror("Erro", "Primeiro clique em \"2. Carregar contas do período\"."); return
            alvo = self._t_auto
        self.b2.config(state="disabled")
        self.worker = threading.Thread(target=alvo, daemon=True)
        self.worker.start()

    def _t_auto(self):
        try:
            contas_sel = {c for c, v in self.vars_contas.items() if v.get()}
            if not contas_sel:
                self._log("[!] Nenhuma conta marcada."); self.q.put(("reabilitar2", None)); return
            pagos = [p for p in self.pagos if p["conta"] in contas_sel]
            if self.v_ign.get():
                antes = len(pagos)
                pagos = [p for p in pagos
                         if not any(t in (_norm(p["desc"]) + " | " + _norm(p["categoria"]))
                                    for t in config.IGNORAR_PADRAO)]
                self._log(f"Ignorados por tipo (tarifas/aportes/etc.): {antes - len(pagos)}")
            self._log(f"{len(pagos)} pagamento(s) nas contas marcadas. Verificando anexos...")

            if pagos and not self.api.capturar_credenciais_anexos(pagos[0]["launchId"]):
                raise RuntimeError("Não capturei as credenciais de anexos.")
            self.q.put(("max", len(pagos)))
            att = self.api.verificar_anexos([p["paidId"] for p in pagos], self._log,
                                            progresso=lambda i, n: self.q.put(("prog", (i, 0, 0))))
            pendentes = [p for p in pagos if att.get(p["paidId"], 0) == 0]
            com = len(pagos) - len(pendentes)
            self._log(f"Com comprovante: {com} | SEM comprovante: {len(pendentes)}")

            pdfs = matcher.carregar_pdfs(Path(self.v_pasta.get()), self._log)
            self._log(f"{len(pdfs)} PDF(s) válidos na pasta.")
            certezas, duvidas, sem_par = matcher.casar(pendentes, pdfs)
            self._log(f"Casamentos com certeza: {len(certezas)} | dúvida: {len(duvidas)} "
                      f"| sem par: {len(sem_par)}\n")

            resultados = []
            self.q.put(("max", len(certezas)))
            pasta = Path(self.v_pasta.get())
            for i, pe in enumerate(certezas, 1):
                arq = pasta / pe["pdf"]
                r = self.mc.anexar(pe["launchId"], _fmt_val(pe["valor"]), arq,
                                   doc=pe["doc"] or None, dry_run=self.v_dry.get())
                if r.startswith("erro:"):
                    r = self.mc.anexar(pe["launchId"], _fmt_val(pe["valor"]), arq,
                                       doc=pe["doc"] or None, dry_run=self.v_dry.get())
                pe["resultado"] = r
                resultados.append(pe)
                self.q.put(("prog", (i, sum(1 for x in resultados if not x["resultado"].startswith("erro")), 0)))
                self._log(f"[{i}/{len(certezas)}] {_fmt_val(pe['valor'])}  {pe['pdf']}  -> {r}")

            saida = self._relatorio(resultados, duvidas, sem_par)
            ok = sum(1 for x in resultados
                     if x["resultado"] in ("anexado", "anexado_sem_tag", "ja_tinha", "dry_run"))
            self._log(f"\nConcluído. Anexados/ok: {ok} de {len(certezas)}. Relatório: {saida}")
            self.q.put(("fim", (ok, len(certezas), len(duvidas), len(sem_par), saida)))
        except Exception as e:
            self._log("ERRO: " + str(e) + "\n" + traceback.format_exc())
            self.q.put(("reabilitar2", None))

    def _t_lista(self):
        try:
            tarefas = planilha.carregar_tarefas(Path(self.v_lista.get()))
            self._log(f"{len(tarefas)} linha(s) na lista. Simular={self.v_dry.get()}")
            if self.mc is None:
                self._log("Abrindo o Chrome... faça login se for pedido.")
                self.mc = MCClient().__enter__()
                self.mc.garantir_login()
            self.q.put(("max", len(tarefas)))
            ok = 0
            for i, t in enumerate(tarefas, 1):
                if not t["launchId"] or not t["valor"] or t["arquivo"] is None:
                    r = "erro:linha_incompleta"
                else:
                    r = self.mc.anexar(t["launchId"], t["valor"], t["arquivo"],
                                       doc=t.get("doc") or None, dry_run=self.v_dry.get())
                if r in ("anexado", "anexado_sem_tag", "ja_tinha", "dry_run"):
                    ok += 1
                self.q.put(("prog", (i, ok, i - ok)))
                self._log(f"[{i}/{len(tarefas)}] {t['valor']}  {t['arquivo_bruto']}  -> {r}")
            self._log(f"\nConcluído: {ok}/{len(tarefas)} ok.")
            self.q.put(("fim", (ok, len(tarefas), 0, 0, "")))
        except Exception as e:
            self._log("ERRO: " + str(e) + "\n" + traceback.format_exc())
            self.q.put(("reabilitar2", None))

    # ---------------------------------------------------------------- saída
    def _relatorio(self, anexados, duvidas, sem_par) -> str:
        wb = Workbook(); wb.remove(wb.active)
        verde = PatternFill("solid", fgColor="1B7837")
        branco = Font(bold=True, color="FFFFFF")
        H = ["Valor", "Data", "Centro de custo", "Conta", "Descrição", "Nº doc",
             "PDF", "Motivo/Candidatos", "Resultado", "Link"]

        def aba(nome, linhas):
            ws = wb.create_sheet(nome)
            for j, h in enumerate(H, 1):
                c = ws.cell(1, j, h); c.font = branco; c.fill = verde
            for i, r in enumerate(linhas, 2):
                for j, v in enumerate(r, 1):
                    ws.cell(i, j, v)
            for col, w in zip("ABCDEFGHIJ", [11, 9, 32, 26, 38, 16, 45, 30, 16, 58]):
                ws.column_dimensions[col].width = w
            ws.freeze_panes = "A2"

        aba("ANEXADOS", [[_fmt_val(p["valor"]), p["dataFull"], "; ".join(p["works"]),
                          p["conta"], p["desc"], p["doc"], p["pdf"], p["motivo"],
                          p.get("resultado", ""), LINK + p["launchId"]] for p in anexados])
        aba("DUVIDA", [[_fmt_val(p["valor"]), p["dataFull"], "; ".join(p["works"]),
                        p["conta"], p["desc"], p["doc"], "",
                        " || ".join(c["pdf"]["fn"] for c in p["cands"]
                                    if c["pdf"]["used_by"] is None) or "(sem candidatos livres)",
                        "", LINK + p["launchId"]] for p in duvidas])
        aba("SEM PAR", [[_fmt_val(p["valor"]), p["dataFull"], "; ".join(p["works"]),
                         p["conta"], p["desc"], p["doc"], "", "", "",
                         LINK + p["launchId"]] for p in sem_par])
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out = Path(self.v_pasta.get() or ".") / f"relatorio_anexos_{stamp}.xlsx"
        wb.save(out)
        return str(out)

    # ---------------------------------------------------------------- UI pump
    def _drain(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.log.insert("end", val + "\n"); self.log.see("end")
                elif kind == "max":
                    self.pb.config(maximum=max(val, 1), value=0)
                elif kind == "prog":
                    i, ok, err = val
                    self.pb.config(value=i)
                    self.lbl.config(text=f"{i} processados — {ok} ok" + (f", {err} erros" if err else ""))
                elif kind == "contas":
                    self._montar_contas(val)
                    self.b1.config(state="normal")
                    self.b2.config(state="normal")
                    self.lbl.config(text="Contas carregadas. Marque as desejadas e clique em 3.")
                elif kind == "reabilitar0":
                    self.b0.config(state="normal")
                elif kind == "reabilitar":
                    self.b1.config(state="normal")
                elif kind == "reabilitar2":
                    self.b2.config(state="normal")
                elif kind == "fim":
                    ok, tot, duv, sp, saida = val
                    self.b2.config(state="normal")
                    self.lbl.config(text=f"Concluído: {ok}/{tot} ok"
                                    + (f" | {duv} dúvidas, {sp} sem par" if duv or sp else ""))
                    msg = f"Anexados/ok: {ok} de {tot}"
                    if duv or sp:
                        msg += f"\nDúvidas: {duv}\nSem par: {sp}"
                    if saida:
                        msg += f"\n\nRelatório:\n{saida}"
                    messagebox.showinfo("Concluído", msg)
        except queue.Empty:
            pass
        self.after(150, self._drain)

    def _fechar(self):
        try:
            if self.mc:
                self.mc.__exit__(None, None, None)
        except Exception:
            pass
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
