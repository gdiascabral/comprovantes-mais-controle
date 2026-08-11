# -*- coding: utf-8 -*-
"""
Aba "Pagamentos do Dia": gera o Excel de conferência dos pagamentos do período,
com uma aba por conta bancária.

Compartilha o navegador e a thread do AnexarFrame — o Playwright síncrono só
aceita uma thread, e abrir um segundo Chrome significaria um segundo login.
É o mesmo arranjo da Conferência, dos Aportes e do Relatório Mensal.

FLUXO EM DOIS PASSOS, de propósito
----------------------------------
1. Buscar    — lê os lançamentos e mostra as contas com os totais;
2. Gerar     — só as contas marcadas viram planilha.

Separado porque quem confere quer OLHAR a lista de contas antes (e quase
sempre tira uma ou outra: "APENAS LANÇAMENTO", conta pessoal, conta zerada).
Fazer tudo de uma vez obrigaria a rodar de novo — e cada rodada custa uma
sessão do ERP, que só aceita uma por usuário.
"""
from __future__ import annotations

import datetime
import json
import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from threading import Event
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

import relatorio                                              # noqa: E402


def _pasta_base() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def _fmt_dur(seg: float) -> str:
    seg = int(seg)
    return f"{seg // 60}min {seg % 60}s" if seg >= 60 else f"{seg}s"


def _carregar_reembolsos() -> dict:
    """Chaves Pix dos avisos "PAGAR PARA <nome>".

    Fica em arquivo, ao lado do exe, porque é CPF de gente — não entra no
    repositório. Ausente, o relatório só marca a linha como pendente.
    """
    try:
        dados = json.loads((_pasta_base() / "pix_reembolso.json")
                           .read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in dados.items()} if isinstance(dados, dict) else {}
    except Exception:
        return {}


class PagamentosDiaFrame(ttk.Frame):
    def __init__(self, master, anexar_frame):
        super().__init__(master)
        self.anx = anexar_frame          # dono do navegador e da thread
        self.q = queue.Queue()
        self.worker = None
        self._parar = Event()
        self.lancamentos: list[dict] = []
        self.anexos: dict = {}
        self.overviews: dict = {}
        self.contas: list[tuple] = []
        self.vars_contas: dict[str, tk.BooleanVar] = {}
        self.ultimo_arquivo: Path | None = None

        hoje = datetime.date.today()
        self.v_ini = tk.StringVar(value=f"{hoje:%d/%m/%Y}")
        self.v_fim = tk.StringVar(value=f"{hoje:%d/%m/%Y}")
        self.v_cruzar = tk.BooleanVar(value=True)
        self.v_incluir_pagos = tk.BooleanVar(value=False)
        self.v_pasta = tk.StringVar(
            value=str(_pasta_base() / "Pagamentos do dia").replace("\\", "/"))

        self._build()
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = 14

        cab = ttk.Frame(self)
        cab.pack(fill="x", padx=PADX, pady=(12, 4))
        ttk.Label(cab, text="Pagamentos do Dia",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(cab, foreground="#6b6b6b",
                  text="Planilha de conferência dos pagamentos do período: como pagar "
                       "cada um e se o documento anexado bate com o lançamento."
                  ).pack(anchor="w")

        # ---- card 1: período
        f1 = ttk.LabelFrame(self, text=" 1. Período ", padding=(12, 8, 12, 10))
        f1.pack(fill="x", padx=PADX, pady=6)
        linha = ttk.Frame(f1); linha.pack(fill="x")
        ttk.Label(linha, text="De:").pack(side="left")
        ttk.Entry(linha, textvariable=self.v_ini, width=12).pack(side="left", padx=(6, 12))
        ttk.Label(linha, text="até:").pack(side="left")
        ttk.Entry(linha, textvariable=self.v_fim, width=12).pack(side="left", padx=(6, 8))
        ttk.Label(linha, text="(dd/mm/aaaa)", foreground="#6b6b6b").pack(side="left")
        ttk.Button(linha, text="Hoje", command=self._hoje).pack(side="left", padx=(12, 0))

        opc = ttk.Frame(f1); opc.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(opc, variable=self.v_cruzar,
                        text="Conferir os documentos anexados (baixa os PDFs; "
                             "mais lento, mas é a conferência de verdade)"
                        ).pack(anchor="w")
        ttk.Checkbutton(opc, variable=self.v_incluir_pagos,
                        text="Incluir também o que já foi pago no período"
                        ).pack(anchor="w")

        # ---- card 2: contas
        f2 = ttk.LabelFrame(self, text=" 2. Contas (marque as que entram no relatório) ",
                            padding=(12, 8, 12, 10))
        f2.pack(fill="both", expand=True, padx=PADX, pady=6)
        self.canvas = tk.Canvas(f2, height=170, highlightthickness=0, borderwidth=0)
        barra = ttk.Scrollbar(f2, orient="vertical", command=self.canvas.yview)
        self.contas_box = ttk.Frame(self.canvas)
        self.contas_box.bind("<Configure>", lambda _e: self.canvas.configure(
            scrollregion=self.canvas.bbox("all")))
        self.janela_lista = self.canvas.create_window((0, 0), window=self.contas_box,
                                                      anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(
            self.janela_lista, width=e.width))
        self.canvas.configure(yscrollcommand=barra.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        barra.pack(side="right", fill="y")
        ttk.Label(self.contas_box,
                  text='Clique em "1. Buscar os lançamentos" para listar as contas.'
                  ).pack(anchor="w")

        # ---- card 3: pasta
        f3 = ttk.LabelFrame(self, text=" 3. Onde salvar ", padding=(12, 8, 12, 10))
        f3.pack(fill="x", padx=PADX, pady=6)
        ttk.Entry(f3, textvariable=self.v_pasta).pack(side="left", fill="x", expand=True)
        ttk.Button(f3, text="Selecionar…", command=self._sel_pasta
                   ).pack(side="left", padx=(6, 0))

        # ---- barra de ação
        acao = ttk.Frame(self)
        acao.pack(side="bottom", fill="x", padx=PADX, pady=(6, 12))
        prog = ttk.Frame(acao); prog.pack(side="bottom", fill="x", pady=(8, 0))
        self.lbl = ttk.Label(prog, text="Pronto.")
        self.lbl.pack(side="left")
        self.pb = ttk.Progressbar(prog, mode="determinate")
        self.pb.pack(side="left", fill="x", expand=True, padx=12)

        btns = ttk.Frame(acao); btns.pack(fill="x")
        self.b1 = ttk.Button(btns, text="▶ 1. Buscar os lançamentos", command=self.buscar)
        self.b1.pack(side="left")
        self.b2 = ttk.Button(btns, text="▶ 2. Gerar a planilha", command=self.gerar,
                             state="disabled")
        self.b2.pack(side="left", padx=10)
        self.b_stop = ttk.Button(btns, text="⏹ Parar", command=self._parar_click,
                                 state="disabled")
        self.b_stop.pack(side="left")
        self.b_abrir = ttk.Button(btns, text="📂 Abrir planilha", command=self._abrir,
                                  state="disabled")
        self.b_abrir.pack(side="left", padx=(10, 0))
        for b in (self.b1, self.b2):
            try:
                b.configure(style="Accent.TButton")
            except tk.TclError:
                pass

        reg = ttk.LabelFrame(self, text=" Registro ", padding=(10, 6, 10, 10))
        reg.pack(fill="both", expand=True, padx=PADX, pady=6)
        self.log = tk.Text(reg, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0, height=8, font=("Consolas", 10))
        self.log.pack(fill="both", expand=True)

    def _hoje(self):
        hoje = datetime.date.today()
        self.v_ini.set(f"{hoje:%d/%m/%Y}")
        self.v_fim.set(f"{hoje:%d/%m/%Y}")

    def _sel_pasta(self):
        escolhida = filedialog.askdirectory(initialdir=self.v_pasta.get() or None)
        if escolhida:
            self.v_pasta.set(escolhida.replace("\\", "/"))

    def _abrir(self):
        if self.ultimo_arquivo and self.ultimo_arquivo.exists():
            try:
                os.startfile(self.ultimo_arquivo)          # noqa: S606 (Windows)
            except Exception:
                subprocess.Popen(["explorer", str(self.ultimo_arquivo)])

    def _parar_click(self):
        self._parar.set()
        self.lbl.configure(text="Parando...")
        self.b_stop.configure(state="disabled")

    def aplicar_cores(self, escuro: bool):
        fundo = "#1c1c1c" if escuro else "#ffffff"
        frente = "#e8e8e8" if escuro else "#000000"
        try:
            self.log.configure(background=fundo, foreground=frente,
                               insertbackground=frente)
            self.canvas.configure(background=fundo)
        except tk.TclError:
            pass

    def _periodo(self) -> tuple[datetime.date, datetime.date]:
        ini = datetime.datetime.strptime(self.v_ini.get().strip(), "%d/%m/%Y").date()
        fim = datetime.datetime.strptime(self.v_fim.get().strip(), "%d/%m/%Y").date()
        return (fim, ini) if ini > fim else (ini, fim)

    # ------------------------------------------------------------- mensagens
    def _log(self, msg=""):
        self.q.put(("log", msg))

    def _drain(self):
        try:
            while True:
                tipo, valor = self.q.get_nowait()
                if tipo == "log":
                    self.log.insert("end", f"{valor}\n")
                    self.log.see("end")
                elif tipo == "status":
                    self.lbl.configure(text=valor)
                elif tipo == "progresso":
                    feitos, total = valor
                    self.pb.configure(maximum=max(total, 1), value=feitos)
                elif tipo == "contas":
                    self._montar_contas(valor)
                elif tipo == "botoes":
                    self.b1.configure(state=valor)
                    self.b2.configure(state="normal" if valor == "normal" and self.contas
                                      else "disabled")
                    self.b_stop.configure(state="disabled" if valor == "normal" else "normal")
                elif tipo == "arquivo":
                    self.ultimo_arquivo = valor
                    self.b_abrir.configure(state="normal")
        except queue.Empty:
            pass
        self.after(150, self._drain)

    # --------------------------------------------------------------- etapa 1
    def buscar(self):
        if self.worker and not self.worker.done():
            return
        try:
            ini, fim = self._periodo()
        except ValueError:
            messagebox.showwarning("Período", "Use datas no formato dd/mm/aaaa.")
            return
        self._parar.clear()
        self.q.put(("botoes", "disabled"))
        self.q.put(("status", "Abrindo o Mais Controle..."))
        if self.anx.avisar_se_ocupado("os Pagamentos do Dia"):
            return
        self.worker = self.anx.submeter("Pagamentos do Dia — buscar",
                                        self._t_buscar, ini, fim)

    def _t_buscar(self, ini, fim):
        comeco = time.time()
        try:
            api = self.anx.garantir_sessao(self._log)
            # garantir_sessao só abre o navegador: quem observa a tela de
            # Pagamentos e pega os cabeçalhos de autenticação é esta chamada.
            if not api.capturar_credenciais(self._log):
                raise RuntimeError("A tela de Pagamentos não carregou a lista no Chrome.")
            self._log(f"\nLançamentos previstos de {ini:%d/%m/%Y} a {fim:%d/%m/%Y}")
            self.q.put(("status", "Lendo os lançamentos..."))
            brutos = api.listar_a_pagar(f"{ini:%Y-%m-%d}", f"{fim:%Y-%m-%d}", log=self._log)

            # Rede de segurança: se a API ignorar o filtro, não deixamos o
            # relatório sair errado em silêncio.
            self.lancamentos = relatorio.filtrar_periodo(brutos, ini, fim, log=self._log)
            self._log(f"{len(self.lancamentos)} lançamento(s) no período.")
            if not self.lancamentos:
                self.q.put(("status", "Nenhum lançamento no período."))
                return

            titulos = sorted({str(i.get("tradePayableId")) for i in self.lancamentos
                              if i.get("tradePayableId")})
            self.q.put(("status", f"Lendo os anexos de {len(titulos)} título(s)..."))
            if not api._req_anexos:
                api.capturar_credenciais_anexos(self.lancamentos[0].get("id"))
            self.anexos = api.anexos_de_titulos(
                titulos, log=self._log,
                progresso=lambda f, t: self.q.put(("progresso", (f, t))),
                cancelar=self._parar.is_set)
            com = sum(1 for v in self.anexos.values() if v)
            self._log(f"{com} título(s) com anexo, {len(titulos) - com} sem.")

            ids = [str(i.get("id")) for i in self.lancamentos if i.get("id")]
            self.q.put(("status", f"Lendo o detalhe de {len(ids)} lançamento(s)..."))
            self.overviews = api.listar_overviews(
                ids, log=self._log,
                progresso=lambda f, t: self.q.put(("progresso", (f, t))),
                cancelar=self._parar.is_set)
            com_oc = sum(1 for v in self.overviews.values()
                         if (v.get("purchaseOrder") or {}).get("number"))
            com_obs = sum(1 for v in self.overviews.values() if (v.get("comment") or "").strip())
            self._log(f"{len(self.overviews)} detalhe(s) — {com_oc} com OC, "
                      f"{com_obs} com observação.")

            self.contas = relatorio.resumo_por_conta(self.lancamentos)
            self.q.put(("contas", self.contas))
            self.q.put(("status", f"Pronto em {_fmt_dur(time.time() - comeco)}. "
                                  "Marque as contas e clique em 2."))
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui buscar os lançamentos."))
        finally:
            self.q.put(("botoes", "normal"))

    def _montar_contas(self, contas):
        for w in self.contas_box.winfo_children():
            w.destroy()
        self.vars_contas = {}
        for nome, qtd, total, pagos, ignorada in contas:
            # Contas de ajuste começam desmarcadas: quase nunca entram, mas
            # ficam visíveis para o caso de precisarem entrar.
            v = tk.BooleanVar(value=not ignorada and qtd > 0)
            self.vars_contas[nome] = v
            extra = []
            if ignorada:
                extra.append("conta de ajuste")
            if pagos:
                extra.append(f"{pagos} já pago(s)")
            rotulo = (f"{nome}  —  {qtd} a pagar, {relatorio.brl(total)}"
                      + (f"  ({'; '.join(extra)})" if extra else ""))
            ttk.Checkbutton(self.contas_box, text=rotulo, variable=v).pack(anchor="w")

        rodape = ttk.Frame(self.contas_box)
        rodape.pack(anchor="w", pady=(6, 0))
        ttk.Button(rodape, text="Marcar todas",
                   command=lambda: [v.set(True) for v in self.vars_contas.values()]
                   ).pack(side="left")
        ttk.Button(rodape, text="Desmarcar todas",
                   command=lambda: [v.set(False) for v in self.vars_contas.values()]
                   ).pack(side="left", padx=6)
        self.b2.configure(state="normal")

    # --------------------------------------------------------------- etapa 2
    def gerar(self):
        if self.worker and not self.worker.done():
            return
        escolhidas = [n for n, v in self.vars_contas.items() if v.get()]
        if not escolhidas:
            messagebox.showinfo("Pagamentos do Dia", "Marque ao menos uma conta.")
            return
        if not self.v_pasta.get().strip():
            messagebox.showwarning("Pasta", "Escolha onde salvar a planilha.")
            return
        self._parar.clear()
        self.q.put(("botoes", "disabled"))
        if self.anx.avisar_se_ocupado("os Pagamentos do Dia"):
            return
        self.worker = self.anx.submeter("Pagamentos do Dia — gerar planilha",
                                        self._t_gerar, escolhidas)

    def _t_gerar(self, escolhidas):
        comeco = time.time()
        try:
            ini, fim = self._periodo()
            escolha = {relatorio.chave(n) for n in escolhidas}
            selecionados = [i for i in self.lancamentos
                            if relatorio.chave(relatorio.nome_da_conta(i)) in escolha]

            a_pagar, pagos = relatorio.separar_pagos(selecionados)
            if pagos:
                self._log(f"\n{len(pagos)} já pago(s) no período"
                          + ("; incluídos." if self.v_incluir_pagos.get() else "; fora."))
            if not self.v_incluir_pagos.get():
                selecionados = a_pagar
            if not selecionados:
                self.q.put(("status", "Nada a pagar nas contas marcadas."))
                return

            textos = {}
            if self.v_cruzar.get():
                textos = self._baixar_textos(selecionados)

            registros = relatorio.montar_registros(
                selecionados, self.anexos, self.overviews, textos,
                pix_reembolso=_carregar_reembolsos())
            if not registros:
                self.q.put(("status", "Nenhuma linha para as contas marcadas."))
                return

            destino = (Path(self.v_pasta.get().strip())
                       / f"pagamentos_{ini:%Y-%m-%d}"
                       f"{'' if ini == fim else f'_a_{fim:%Y-%m-%d}'}.xlsx")
            arquivo = relatorio.gerar_excel(registros, destino, log=self._log)

            n = sum(len(r) for r in registros.values())
            total = sum(x["valor"] for r in registros.values() for x in r)
            atencao = sum(1 for r in registros.values() for x in r
                          if x["status"].startswith("ATEN"))
            self._log(f"\n{n} pagamento(s) em {len(registros)} conta(s). "
                      f"Total {relatorio.brl(total)}")
            for conta, regs in registros.items():
                self._log(f"  {conta[:46]:46} {len(regs):>3}  "
                          f"{relatorio.brl(sum(x['valor'] for x in regs)):>16}")
            if atencao:
                self._log(f"\n{atencao} linha(s) em laranja para conferir na mão.")
            self._log(f"\nPlanilha: {str(arquivo).replace(chr(92), '/')}  "
                      f"({_fmt_dur(time.time() - comeco)})")
            self.q.put(("arquivo", arquivo))
            self.q.put(("status", f"{n} pagamento(s) · {relatorio.brl(total)} · "
                                  f"{atencao} para conferir"))
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui gerar a planilha."))
        finally:
            self.q.put(("botoes", "normal"))

    def _baixar_textos(self, selecionados) -> dict:
        """{downloadUrl: texto} dos PDFs. Um download serve para as duas
        coisas: extrair a linha digitável do boleto E cruzar valor/fornecedor."""
        urls = []
        for item in selecionados:
            for f in self.anexos.get(str(item.get("tradePayableId"))) or []:
                if f.get("downloadUrl") and relatorio.eh_pdf(f):
                    urls.append(f["downloadUrl"])
        urls = list(dict.fromkeys(urls))
        if not urls:
            return {}

        self._log(f"\nBaixando e lendo {len(urls)} PDF(s) para o cruzamento...")
        textos, sem_texto = {}, 0
        for i, url in enumerate(urls, 1):
            if self._parar.is_set():
                self._log("Interrompido a pedido — o cruzamento fica incompleto.")
                break
            dados = self.anx.api.baixar_anexo(url)
            texto = relatorio.texto_de_pdf(dados) if dados else ""
            textos[url] = texto
            if not texto.strip():
                sem_texto += 1
            self.q.put(("progresso", (i, len(urls))))
            if i % 25 == 0:
                self.q.put(("status", f"Lendo PDFs... {i}/{len(urls)}"))
        if sem_texto:
            self._log(f"  {sem_texto} PDF(s) sem texto (foto/escaneado) — "
                      "esses não dá para cruzar.")
        return textos
