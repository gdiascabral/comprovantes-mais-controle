# -*- coding: utf-8 -*-
"""
Aba "Relatório Mensal": baixa em PDF o extrato de cada conta bancária.

Compartilha o navegador e a thread do AnexarFrame — o Playwright síncrono só
aceita uma thread, e abrir um segundo Chrome significaria um segundo login.
É o mesmo arranjo da Conferência e dos Aportes.
"""
from __future__ import annotations

import calendar
import datetime
import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from threading import Event
from tkinter import messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

import conferir_mapas                                        # noqa: E402
import contas_mc                                             # noqa: E402
import extrato_mc                                            # noqa: E402

# Estes dois vivem em OUTRAS pastas de aba, e entram aqui em cima de
# propósito. Enquanto o import morava dentro do `try` do `_conferir_mapas`, o
# `except Exception: pass` engolia junto a falha de IMPORTAR: bastava a ordem
# do sys.path mudar, ou um arquivo faltar no codigo.zip, para a conferência que
# impede o mês partido sumir para sempre — sem uma linha em lugar nenhum. Aqui,
# se algum dia faltar, o app não abre e alguém fica sabendo no mesmo dia.
try:                                     # cadastro do Sicoob (aba vizinha)
    import sicoob_config                                     # noqa: E402
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                           / "extratos_sicoob"))
    import sicoob_config                                     # noqa: E402

try:                                     # o diagnostico.log é um só, no Anexar
    import config                                            # noqa: E402
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "anexar"))
    import config                                            # noqa: E402

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

#: Duração e pasta-base vinham em cópias byte a byte por aba. Uma cópia de
#: regra de CAMINHO é como um app passa a procurar o mesmo arquivo em dois
#: lugares; uma de FORMATO é como a mesma duração aparece de dois jeitos.
_fmt_dur = util.fmt_dur
_pasta_base = util.pasta_base

try:                                     # widgets compartilhados (raiz)
    import widgets
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import widgets

CampoData = widgets.CampoData

#: Rótulo de TELA. A tabela que vira nome de pasta é a `util.MESES_PASTA`,
#: e quem guarda a forma de exibição é o `widgets`, par visual do `util`.
MESES = list(widgets.MESES)






class RelatorioFrame(ttk.Frame):
    def __init__(self, master, anexar_frame):
        super().__init__(master)
        self.anx = anexar_frame          # dono do navegador e da thread
        self.q = queue.Queue()
        self.worker = None
        self._parar = Event()
        self.contas: list[dict] = []
        self.vars_contas: dict[str, tk.BooleanVar] = {}
        self.ultima_pasta: Path | None = None
        self.mapa: contas_mc.Mapa | None = None
        self.sem_destino: set[str] = set()

        hoje = datetime.date.today()
        anterior = hoje.replace(day=1) - datetime.timedelta(days=1)
        self.v_mes = tk.StringVar(value=MESES[anterior.month - 1])
        self.v_ano = tk.StringVar(value=str(anterior.year))
        self.v_personalizado = tk.BooleanVar(value=False)
        self.v_ini = tk.StringVar(value=f"{anterior.replace(day=1):%d/%m/%Y}")
        self.v_fim = tk.StringVar(value=f"{anterior:%d/%m/%Y}")
        self.v_pasta = tk.StringVar(value="(definido em contas_mc.json)")

        self._build()
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = widgets.PADX

        self.cab = widgets.Cabecalho(
            self, "Relatório Mensal",
            "Baixa o extrato de cada conta bancária do período, com todos os "
            "lançamentos, num PDF por conta.")
        self.cab.pack(fill="x", padx=PADX, pady=(12, 4))

        # Cartões sem número: quem numera é a trilha de ações, no fim do build.
        f1 = widgets.Cartao(self, "Período")
        f1.pack(fill="x", padx=PADX, pady=6)

        linha = ttk.Frame(f1); linha.pack(fill="x")
        ttk.Label(linha, text="Mês:").pack(side="left")
        self.cb_mes = ttk.Combobox(linha, textvariable=self.v_mes, values=MESES,
                                   state="readonly", width=12)
        self.cb_mes.pack(side="left", padx=(6, 14))
        ttk.Label(linha, text="Ano:").pack(side="left")
        anos = [str(a) for a in range(datetime.date.today().year + 1, 2019, -1)]
        self.cb_ano = ttk.Combobox(linha, textvariable=self.v_ano, values=anos,
                                   state="readonly", width=7)
        self.cb_ano.pack(side="left", padx=(6, 14))
        self.lbl_periodo = ttk.Label(linha, style="Apoio.TLabel")
        self.lbl_periodo.pack(side="left")

        pers = ttk.Frame(f1); pers.pack(fill="x", pady=(8, 0))
        ttk.Checkbutton(pers, text="Usar um intervalo de datas em vez do mês inteiro",
                        variable=self.v_personalizado,
                        command=self._alternar_periodo).pack(anchor="w")
        self.f_datas = ttk.Frame(f1)
        ttk.Label(self.f_datas, text="De:").pack(side="left")
        CampoData(self.f_datas, self.v_ini).pack(side="left", padx=(6, 14))
        ttk.Label(self.f_datas, text="até:").pack(side="left")
        CampoData(self.f_datas, self.v_fim).pack(side="left", padx=(6, 8))
        ttk.Label(self.f_datas, text="(dd/mm/aaaa)", style="Apoio.TLabel").pack(side="left")

        for var in (self.v_mes, self.v_ano):
            var.trace_add("write", lambda *_: self._atualizar_rotulo())
        self._atualizar_rotulo()

        # ---- card 2: contas
        self.f_contas = f2 = widgets.Cartao(
            self, "Contas bancárias (marque as desejadas)")
        f2.pack(fill="x", padx=PADX, pady=6)

        # Lista rolável: são ~34 contas, com nomes longos. Antes de carregar
        # ela é uma frase só, e cresce em `_montar_contas`.
        self.canvas = tk.Canvas(f2, height=24, highlightthickness=0, borderwidth=0)
        self.barra = barra = ttk.Scrollbar(f2, orient="vertical",
                                           command=self.canvas.yview)
        self.contas_box = ttk.Frame(self.canvas)
        self.contas_box.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.janela_lista = self.canvas.create_window((0, 0), window=self.contas_box,
                                                      anchor="nw")
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self.janela_lista, width=e.width))
        self.canvas.configure(yscrollcommand=barra.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        # A barra de rolagem só entra junto com a lista: numa faixa de 24 px
        # ela vira duas setinhas espremidas ao lado de uma frase.
        self.lbl_vazio = ttk.Label(
            self.contas_box, text='Clique em "1. Carregar contas" para listar as contas.')
        self.lbl_vazio.pack(anchor="w")

        # ---- card 3: destino
        # O destino não é mais escolhido à mão: cada conta tem o seu, definido
        # em contas_mc.json. O campo virou informação, não decisão.
        f3 = widgets.Cartao(self, "Onde salva")
        f3.pack(fill="x", padx=PADX, pady=6)
        ttk.Entry(f3, textvariable=self.v_pasta, state="readonly"
                  ).pack(side="left", fill="x", expand=True)
        ttk.Label(f3, style="Apoio.TLabel",
                  text="  cada conta vai para a pasta da sua empresa"
                  ).pack(side="left")

        # ---- barra de ação
        acao = ttk.Frame(self)
        acao.pack(side="bottom", fill="x", padx=PADX, pady=(6, 12))
        prog = ttk.Frame(acao); prog.pack(side="bottom", fill="x", pady=(8, 0))
        self.lbl = ttk.Label(prog, text="Pronto.")
        self.lbl.pack(side="left")
        self.pb = ttk.Progressbar(prog, mode="determinate")
        self.pb.pack(side="left", fill="x", expand=True, padx=12)

        btns = ttk.Frame(acao); btns.pack(fill="x")
        self.b1 = ttk.Button(btns, text="▶ 1. Carregar contas", command=self.carregar)
        self.b1.pack(side="left")
        self.b2 = ttk.Button(btns, text="▶ 2. Gerar os extratos", command=self.gerar,
                             state="disabled")
        self.b2.pack(side="left", padx=10)
        self.b_stop = ttk.Button(btns, text="⏹ Parar", command=self._parar_click,
                                 state="disabled")
        self.b_stop.pack(side="left")
        self.b_abrir = ttk.Button(btns, text="📂 Abrir pasta", command=self._abrir_pasta,
                                  state="disabled")
        self.b_abrir.pack(side="left", padx=(10, 0))
        for b in (self.b1, self.b2):
            try:
                b.configure(style="Accent.TButton")
            except tk.TclError:
                pass

        # ---- registro
        self.reg = widgets.Cartao(self, "Registro", padding=(10, 6, 10, 10))
        self.reg.pack(fill="x", padx=PADX, pady=6)
        self.log = tk.Text(self.reg, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0)
        self.log.pack(fill="both", expand=True)
        widgets.estilo_log(self.log)
        widgets.registro_elastico(self.reg, self.log)

        widgets.Passos(self.cab, (("Carregar contas", self.b1),
                                  ("Gerar os extratos", self.b2))
                       ).pack(anchor="w", pady=(8, 0))

    def _alternar_periodo(self):
        if self.v_personalizado.get():
            self.f_datas.pack(fill="x", pady=(6, 0))
        else:
            self.f_datas.pack_forget()
        self._atualizar_rotulo()

    def _atualizar_rotulo(self):
        try:
            ini, fim = self._periodo()
        except ValueError:
            self.lbl_periodo.configure(text="")
            return
        self.lbl_periodo.configure(text=f"→ {ini:%d/%m/%Y} a {fim:%d/%m/%Y}")

    def _periodo(self) -> tuple[datetime.date, datetime.date]:
        """Datas escolhidas. Levanta ValueError se o que foi digitado não serve."""
        if self.v_personalizado.get():
            ini = datetime.datetime.strptime(self.v_ini.get().strip(), "%d/%m/%Y").date()
            fim = datetime.datetime.strptime(self.v_fim.get().strip(), "%d/%m/%Y").date()
            if ini > fim:
                ini, fim = fim, ini
            return ini, fim
        mes = MESES.index(self.v_mes.get()) + 1
        ano = int(self.v_ano.get())
        return (datetime.date(ano, mes, 1),
                datetime.date(ano, mes, calendar.monthrange(ano, mes)[1]))

    # Os três abaixo são `staticmethod` porque não dependem de nada da tela: é
    # assim que a regra de NOME do arquivo — a que decide se este PDF
    # substitui o do mês fechado — pode ser exercitada sem abrir uma janela.
    @staticmethod
    def _mes_fechado(ini: datetime.date, fim: datetime.date) -> bool:
        """Do primeiro ao último dia do MESMO mês.

        É a única forma de período que pode usar o nome de arquivo do
        fechamento (`202607 ...`). Qualquer outra é recorte, e recorte que
        usasse aquele nome apagaria o extrato do mês inteiro."""
        return (ini.day == 1
                and fim.day == calendar.monthrange(fim.year, fim.month)[1]
                and (ini.year, ini.month) == (fim.year, fim.month))

    @staticmethod
    def _nome_do_periodo(ini: datetime.date, fim: datetime.date) -> str:
        """As duas datas do recorte: "01-07-2026 a 15-07-2026".

        É para ISSO que ela existe, e por isso vale mais que um detalhe de
        formatação: pedir 01/07 a 15/07 para tirar uma dúvida gravava por
        cima do extrato de julho já arquivado, porque o nome saía do mês do
        INÍCIO. A trava de paginação não pega — o extrato parcial está
        completo *para o período pedido*, então `conferir_antes_de_salvar`
        aprova, e nada no disco denuncia depois.

        Separador `-` e não `/`: isto vira nome de arquivo no Windows, onde a
        barra é separador de pasta. O resto (dígitos, espaços e o "a") é
        aceito em qualquer nome."""
        return f"{ini:%d-%m-%Y} a {fim:%d-%m-%Y}"

    @staticmethod
    def _periodo_no_nome(ini: datetime.date, fim: datetime.date) -> str:
        """O que `contas_mc.nome_arquivo` põe no lugar do `AAAAMM`.

        Vazio para mês fechado — aí o nome de sempre vale, e é ele que o
        fechamento arquiva junto do OFX do banco, na mesma pasta e com o
        mesmo começo."""
        if RelatorioFrame._mes_fechado(ini, fim):
            return ""
        return RelatorioFrame._nome_do_periodo(ini, fim)

    def _garantir_mapa(self) -> bool:
        """Carrega o mapa conta→pasta, avisando de forma legível quando falta."""
        if self.mapa is not None:
            return True
        try:
            self.mapa = contas_mc.carregar()
        except contas_mc.MapaInvalido as e:
            self._log(f"[!] {e}")
            return False
        self.v_pasta.set(str(self.mapa.raiz).replace("\\", "/"))
        self._conferir_mapas()
        return True

    def _conferir_mapas(self):
        """Avisa se o outro mapa manda alguma conta para pasta diferente.

        O PDF do Mais Controle e o OFX do Sicoob são da MESMA conta e do MESMO
        mês: têm de cair na mesma pasta. Quando os mapas divergem, cada aba
        cria a sua e o mês fica partido — sem nada no disco denunciando.

        Continua sem poder barrar a aba, mas não sem poder ser vista falhar:
        o `pass` de antes fazia "não achei divergência" e "não consegui
        conferir" ficarem idênticos para quem olha a tela."""
        try:
            n = conferir_mapas.avisar(contas_mc.ARQUIVO_MAPA,
                                      sicoob_config.ARQUIVO_CONTAS, self._log)
            if n:
                self._log("  Alinhe os dois arquivos antes de baixar, senão os "
                          "extratos deste mês vão para pastas diferentes.")
        except Exception as e:            # noqa: BLE001 — degrada, mas registra
            config.diag(f"Relatório Mensal: a conferência dos dois mapas não "
                        f"rodou ({e!r})")
            self._log("  [aviso] não consegui conferir os dois mapas de pasta "
                      "(o motivo ficou no diagnostico.log).")

    def _abrir_pasta(self):
        if self.ultima_pasta and self.ultima_pasta.exists():
            try:
                os.startfile(self.ultima_pasta)          # noqa: S606 (Windows)
            except Exception:
                subprocess.Popen(["explorer", str(self.ultima_pasta)])

    def _parar_click(self):
        self._parar.set()
        self.lbl.configure(text="Parando após a conta atual...")
        self.b_stop.configure(state="disabled")

    def aplicar_cores(self, escuro: bool):
        try:
            widgets.estilo_log(self.log, escuro)
            widgets.estilo_canvas(self.canvas)
        except tk.TclError:
            pass

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
                    self.b2.configure(
                        state="normal" if valor == "normal" and self.contas else "disabled")
                    self.b_stop.configure(
                        state="disabled" if valor == "normal" else "normal")
                elif tipo == "pasta_pronta":
                    self.ultima_pasta = valor
                    self.b_abrir.configure(state="normal")
        except queue.Empty:
            pass
        self.after(150, self._drain)

    # ------------------------------------------------------------- etapa 1
    def carregar(self):
        if self.worker and not self.worker.done():
            return
        # Recusar ANTES de desabilitar os botões: quem sai por aqui não passa
        # mais pelo `_drain`, e a aba ficava travada — botões apagados, nada
        # rodando — até reiniciar o app.
        if self.anx.avisar_se_ocupado("o Relatório Mensal"):
            return
        self.q.put(("botoes", "disabled"))
        self.b_stop.configure(state="disabled")
        self.q.put(("status", "Abrindo o Mais Controle e lendo as contas..."))
        self.worker = self.anx.submeter("Relatório Mensal — carregar contas",
                                        self._t_carregar, dona=self)

    def _t_carregar(self):
        try:
            if not self._garantir_mapa():
                self.q.put(("status", "Falta o mapa contas_mc.json."))
                return
            self.anx.garantir_sessao(self._log)
            self._log("Lendo as contas bancárias...")
            contas = extrato_mc.listar_contas(self.anx.mc.page)
            self.contas = contas
            self._log(f"{len(contas)} conta(s) encontradas.")
            self.q.put(("contas", contas))
            self.q.put(("status", "Contas carregadas. Marque as desejadas e clique em 2."))
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui carregar as contas."))
        finally:
            self.q.put(("botoes", "normal"))

    def _montar_contas(self, contas):
        self.canvas.configure(height=150)
        self.barra.pack(side="right", fill="y")
        widgets.cartao_elastico(self.f_contas, cheio=True)
        for w in self.contas_box.winfo_children():
            w.destroy()
        self.vars_contas = {}
        self.sem_destino = set()
        for conta in contas:
            # A lista vem do ERP; o mapa só diz onde salvar. Conta que o mapa
            # não conhece nasce DESMARCADA e avisando — melhor não baixar do
            # que baixar sem saber o destino.
            destino = self.mapa.de(conta["nome"]) if self.mapa else None
            if destino is None:
                self.sem_destino.add(conta["id"])
            v = tk.BooleanVar(value=destino is not None)
            self.vars_contas[conta["id"]] = v
            rotulo = (f'{conta["nome"]}   →   {destino.empresa} / {destino.pasta}'
                      if destino else f'{conta["nome"]}   (sem pasta no mapa)')
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

    # ------------------------------------------------------------- etapa 2
    def gerar(self):
        if self.worker and not self.worker.done():
            return
        try:
            ini, fim = self._periodo()
        except ValueError:
            messagebox.showwarning("Período", "Use datas no formato dd/mm/aaaa.")
            return
        escolhidas = [c for c in self.contas if self.vars_contas.get(c["id"]) and
                      self.vars_contas[c["id"]].get()]
        if not escolhidas:
            messagebox.showinfo("Relatório Mensal", "Marque ao menos uma conta.")
            return
        # Conta sem destino trava ANTES do primeiro download: com o lote no
        # meio do caminho, decidir onde salvar vira improviso.
        orfas = [c["nome"] for c in escolhidas if c["id"] in self.sem_destino]
        if orfas:
            messagebox.showwarning(
                "Contas sem pasta",
                "Estas contas não estão no contas_mc.json e eu não sei onde "
                "salvá-las:\n\n" + "\n".join(f"  {n}" for n in orfas[:10])
                + ("\n  ..." if len(orfas) > 10 else "")
                + "\n\nDesmarque-as ou acrescente-as ao mapa.")
            return

        # Caminho longo barra aqui pelo mesmo motivo da conta sem destino:
        # é ANTES do primeiro download. Estourar os 260 do Windows aparece
        # como falha de escrita na conta 7 de 34, com causa nada óbvia — e a
        # conferência já existia, sem ninguém chamando. Mede o caminho que
        # vai ser gravado de verdade: só as contas marcadas, e com o período
        # deste lote (um intervalo escreve 17 caracteres a mais que o mês).
        longos = contas_mc.caminhos_longos(
            self.mapa, ini.year, ini.month,
            contas=[c["nome"] for c in escolhidas],
            periodo=self._periodo_no_nome(ini, fim))
        if longos:
            messagebox.showwarning(
                "Caminho longo demais",
                f"Estes destinos passam dos {contas_mc.LIMITE_CAMINHO} "
                "caracteres do Windows e a gravação falharia no meio do "
                "lote:\n\n"
                + "\n".join(f"  {n} ({t} caracteres)" for n, t in longos[:10])
                + ("\n  ..." if len(longos) > 10 else "")
                + "\n\nEncurte a pasta em contas_mc.json ou a raiz dos "
                  "extratos.")
            return

        if self.anx.avisar_se_ocupado("o Relatório Mensal"):
            return
        self._parar.clear()
        self.q.put(("botoes", "disabled"))
        self.q.put(("progresso", (0, len(escolhidas))))
        self.worker = self.anx.submeter("Relatório Mensal — gerar extratos",
                                        self._t_gerar, escolhidas, ini, fim,
                                        dona=self)

    def _t_gerar(self, contas, ini, fim):
        comeco = time.time()
        ini_txt, fim_txt = f"{ini:%d/%m/%Y}", f"{fim:%d/%m/%Y}"
        ano, mes = ini.year, ini.month          # a PASTA segue o mês do início
        # O NOME, não: mês fechado usa o `202607` de sempre; recorte usa as
        # duas datas. Enquanto os dois usavam o mesmo, pedir 01/07 a 15/07
        # para tirar uma dúvida substituía o extrato de julho já arquivado,
        # e nada barrava — o extrato parcial está completo *para o período
        # pedido*, então `conferir_antes_de_salvar` aprova.
        periodo = self._periodo_no_nome(ini, fim)
        pasta_mes = contas_mc.caminho_do_mes(self.mapa, ano, mes)
        pagina = None
        try:
            # Também aqui, e não só no passo 1: este é o passo que GRAVA, e
            # mapa divergente é o que parte o mês entre duas pastas. Quando
            # estão alinhados não escreve nada, então não polui o registro.
            self._conferir_mapas()
            self.anx.garantir_sessao(self._log)
            pagina = self.anx.mc.page
            self._log(f"\nExtratos de {ini_txt} a {fim_txt} — {len(contas)} conta(s)")
            self._log(f"Pasta do mês: {str(pasta_mes).replace(chr(92), '/')}")
            if periodo:
                self._log(f"Período parcial: os arquivos saem como "
                          f"\"{periodo} ...\", para não substituir o extrato "
                          f"do mês fechado.")

            feitos, vazios, falhas = [], [], []
            for i, conta in enumerate(contas, 1):
                if self._parar.is_set():
                    self._log("\nInterrompido a pedido.")
                    break
                nome = conta["nome"]
                self.q.put(("status", f"{i}/{len(contas)} — {nome[:45]}"))
                marca = time.time()
                try:
                    destino = self.mapa.de(nome)
                    if destino is None:         # a interface já barra, mas o
                        raise RuntimeError("conta sem pasta no mapa")  # mapa manda
                    arquivo = contas_mc.caminho_do_arquivo(self.mapa, destino,
                                                           ano, mes, periodo)

                    extrato_mc.abrir_extrato(pagina, conta["id"], ini_txt, fim_txt)
                    n = extrato_mc.carregar_tudo(pagina, parar=self._parar.is_set)

                    # Confere ANTES de gravar: conta certa e paginação encerrada.
                    # Se o usuário interrompeu, o extrato está pela metade de
                    # propósito — aí não se grava nada.
                    if self._parar.is_set():
                        self._log(f"  {i}/{len(contas)} {nome[:50]} — interrompido, não salvei")
                        break
                    problemas = extrato_mc.conferir_antes_de_salvar(
                        extrato_mc.estado(pagina), nome)
                    if problemas:
                        raise RuntimeError("; ".join(problemas))

                    extrato_mc.salvar_pdf(pagina, arquivo)
                    kb = arquivo.stat().st_size // 1024
                    self._log(f"  {i}/{len(contas)} {nome[:44]} — {n} lançamento(s), "
                              f"{kb} KB, {_fmt_dur(time.time() - marca)}")
                    self._log(f"      → {destino.empresa} / {destino.pasta} / {arquivo.name}")
                    feitos.append(arquivo)
                    if not n:
                        vazios.append(nome)
                except Exception as e:
                    self._log(f"  {i}/{len(contas)} {nome[:50]} — FALHOU: {e}")
                    falhas.append(nome)
                self.q.put(("progresso", (i, len(contas))))

            self._log(f"\n{len(feitos)} extrato(s) gerados em "
                      f"{_fmt_dur(time.time() - comeco)}.")
            if vazios:
                self._log(f"{len(vazios)} sem lançamentos no período: "
                          + ", ".join(vazios[:5]) + (" ..." if len(vazios) > 5 else ""))
            if falhas:
                self._log(f"{len(falhas)} com problema: " + ", ".join(falhas[:5]))
            if feitos:
                self.q.put(("pasta_pronta", pasta_mes))
            self.q.put(("status", f"{len(feitos)} PDF(s) em "
                                  f"{str(pasta_mes).replace(chr(92), '/')}"))
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui gerar os extratos."))
        finally:
            # A impressão deixa a página só com o modal: sem restaurar, as
            # outras abas encontrariam um navegador sem app nenhum.
            if pagina is not None:
                extrato_mc.restaurar_pagina(pagina)
            self.q.put(("botoes", "normal"))
