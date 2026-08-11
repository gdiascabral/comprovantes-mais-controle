# -*- coding: utf-8 -*-
"""Aba "Contratos de Financiamento" (grupo MENSAL).

Dois passos, como Pagamentos do Dia e Extratos Sicoob:

  1. Buscar   — lê o ERP e mostra a lista: obra, casa, comprador, valor,
                empresa de destino e o contrato encontrado (ou o motivo).
  2. Arquivar — baixa, confere o conteúdo e grava só o que passou.

O passo separado existe porque quem confere quer VER antes de gravar — e é no
passo 1 que um erro do mapa cliente→empresa aparece, antes de qualquer arquivo
ir para a pasta errada. Cada rodada também custa uma sessão do ERP, que só
aceita uma por usuário.

Compartilha o navegador e a thread do AnexarFrame, como as outras cinco abas
do mesmo ERP.
"""
from __future__ import annotations

import datetime
import os
import queue
import tempfile
import time
import tkinter as tk
from pathlib import Path
from threading import Event
from tkinter import messagebox, ttk

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

from . import conferencia as conf
from . import pipeline
from . import resolver
from .destino import limpar as _limpar_nome

_fmt_dur = util.fmt_dur

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]

#: O ☑/☐ da primeira coluna. Texto, e não imagem: o Treeview do ttk não tem
#: caixa de marcação, e desenhar uma custaria mais do que vale.
_MARCA = {True: "☑", False: "☐"}


def _sicoob():
    """O pacote do Sicoob, importado tarde.

    A árvore do fechamento (raiz, nome do mês, pasta da empresa) e o cadastro
    das empresas já moram lá; duplicar aqui seria criar um segundo mapa — e
    julho de 2026 já ficou partido uma vez por causa de dois mapas
    discordando. O import é tardio para esta aba montar mesmo se o pacote do
    Sicoob não estiver no caminho."""
    import sicoob_config as cfg
    import sicoob_contas as contas
    return cfg, contas


def _texto_do_pdf(dados: bytes) -> str:
    """Texto do contrato: camada de texto e, faltando ela, OCR.

    Mesmo caminho do `separar_renomear` — render em SÉRIE (pypdfium2 não é
    thread-safe) e reconhecimento em PARALELO. Falha aqui não é erro: devolve
    vazio, e texto vazio vira `?` na conferência, que não retém o arquivo."""
    import io
    try:
        import pdfplumber
    except ImportError:
        return ""
    try:
        with pdfplumber.open(io.BytesIO(dados)) as pl:
            txt = "\n".join((pg.extract_text() or "") for pg in pl.pages)
        if len(txt.strip()) >= 40:
            return txt
        try:
            from separar_renomear import _ocr_pagina
            with pdfplumber.open(io.BytesIO(dados)) as pl:
                return "\n".join(_ocr_pagina(pg, lambda m: None)
                                 for pg in pl.pages)
        except Exception:
            return txt
    except Exception:
        return ""


class ContratosFrame(ttk.Frame):
    def __init__(self, master, anexar_frame):
        super().__init__(master)
        self.anx = anexar_frame          # dono do navegador e da thread
        self.q = queue.Queue()
        self.worker = None
        self._parar = Event()
        self.achados: list = []
        self.ultima_pasta: Path | None = None
        #: {(obra, unidade): nome do arquivo} — o que foi escolhido à mão nesta
        #: sessão, para uma nova busca não fazer perguntar tudo de novo.
        self.escolhas: dict = {}
        self.janela = None               # a de resolver, quando está aberta

        cfg, _ = _sicoob()
        hoje = datetime.date.today()
        ano, mes = cfg.mes_anterior(hoje.year, hoje.month)
        self.v_mes = tk.StringVar(value=MESES[mes - 1])
        self.v_ano = tk.StringVar(value=str(ano))

        self._montar()
        try:                             # já nasce na cor do tema (sem flash)
            self.aplicar_cores(util.cor_escura(
                ttk.Style().lookup("TFrame", "background")))
        except Exception:
            pass
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _montar(self):
        PADX = 14
        cab = ttk.Frame(self)
        cab.pack(fill="x", padx=PADX, pady=(12, 4))
        ttk.Label(cab, text="Contratos de Financiamento",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w")
        self.lbl_sub = ttk.Label(
            cab, foreground="#6b6b6b",
            text="Acha o contrato das casas que financiaram no mês, confere o "
                 "conteúdo e arquiva na pasta da empresa.")
        self.lbl_sub.pack(anchor="w")

        f1 = ttk.LabelFrame(self, text=" 1. Mês ", padding=(12, 8, 12, 10))
        f1.pack(fill="x", padx=PADX, pady=6)
        linha = ttk.Frame(f1); linha.pack(fill="x")
        ttk.Label(linha, text="Mês:").pack(side="left")
        ttk.Combobox(linha, textvariable=self.v_mes, values=MESES,
                     state="readonly", width=12).pack(side="left", padx=(6, 14))
        ttk.Label(linha, text="Ano:").pack(side="left")
        anos = [str(a) for a in range(datetime.date.today().year + 1, 2019, -1)]
        ttk.Combobox(linha, textvariable=self.v_ano, values=anos,
                     state="readonly", width=7).pack(side="left", padx=(6, 14))
        ttk.Label(linha, foreground="#6b6b6b",
                  text="data do RECEBIMENTO do financiamento").pack(side="left")

        f2 = ttk.LabelFrame(
            self, text=" 2. Casas com financiamento no mês "
                       "(marque as que entram no arquivamento) ",
            padding=(10, 6, 10, 10))
        f2.pack(fill="both", expand=True, padx=PADX, pady=6)
        grade = ttk.Frame(f2); grade.pack(fill="both", expand=True)
        colunas = ("marca", "obra", "casa", "comprador", "valor", "empresa",
                   "situacao")
        self.tabela = ttk.Treeview(grade, columns=colunas, show="headings",
                                   height=9)
        for col, titulo, larg in (("marca", "✔", 34), ("obra", "Obra", 180),
                                  ("casa", "Casa", 55),
                                  ("comprador", "Comprador", 200),
                                  ("valor", "Financiamento", 105),
                                  ("empresa", "Empresa", 125),
                                  ("situacao", "Contrato / motivo", 300)):
            self.tabela.heading(col, text=titulo)
            self.tabela.column(col, width=larg, anchor="w", stretch=col != "marca")
        self.tabela.column("marca", anchor="center")
        self.tabela.pack(fill="both", expand=True, side="left")
        ttk.Scrollbar(grade, orient="vertical", command=self.tabela.yview
                      ).pack(side="right", fill="y")
        # Duas maneiras de alternar, porque nenhuma é óbvia sozinha: clicar no
        # ☑ é o que a pessoa tenta primeiro, e o Espaço é o que sobra quando a
        # linha já está selecionada.
        self.tabela.bind("<Button-1>", self._clique_na_tabela)
        self.tabela.bind("<space>", lambda _e: self._alternar_selecionada())
        self.tabela.bind("<Double-1>", self._duplo_clique)

        pe = ttk.Frame(f2); pe.pack(fill="x", pady=(6, 0))
        self.lbl_marcadas = ttk.Label(pe, foreground="#6b6b6b", text="")
        self.lbl_marcadas.pack(side="right")
        ttk.Button(pe, text="Marcar todas",
                   command=lambda: self._marcar_todas(True)).pack(side="left")
        ttk.Button(pe, text="Desmarcar todas",
                   command=lambda: self._marcar_todas(False)
                   ).pack(side="left", padx=6)
        self.b_resolver = ttk.Button(pe, text="Resolver esta casa…",
                                     command=self._resolver, state="disabled")
        self.b_resolver.pack(side="left", padx=(14, 0))
        self.tabela.bind("<<TreeviewSelect>>", lambda _e: self._atualizar_resolver())

        acao = ttk.Frame(self)
        acao.pack(side="bottom", fill="x", padx=PADX, pady=(6, 12))
        prog = ttk.Frame(acao); prog.pack(side="bottom", fill="x", pady=(8, 0))
        self.lbl = ttk.Label(prog, text="Pronto.")
        self.lbl.pack(side="left")
        self.pb = ttk.Progressbar(prog, mode="determinate")
        self.pb.pack(side="left", fill="x", expand=True, padx=12)

        btns = ttk.Frame(acao); btns.pack(fill="x")
        self.b1 = ttk.Button(btns, text="▶ 1. Buscar", command=self.buscar)
        self.b1.pack(side="left")
        self.b2 = ttk.Button(btns, text="▶ 2. Conferir e arquivar",
                             command=self.arquivar, state="disabled")
        self.b2.pack(side="left", padx=10)
        self.b_stop = ttk.Button(btns, text="⏹ Parar", command=self._parar_click,
                                 state="disabled")
        self.b_stop.pack(side="left")
        self.b_abrir = ttk.Button(btns, text="📂 Abrir pasta",
                                  command=self._abrir_pasta, state="disabled")
        self.b_abrir.pack(side="left", padx=(10, 0))
        for b in (self.b1, self.b2):
            try:
                b.configure(style="Accent.TButton")
            except tk.TclError:
                pass

        reg = ttk.LabelFrame(self, text=" Registro ", padding=(10, 6, 10, 10))
        reg.pack(fill="both", expand=True, padx=PADX, pady=6)
        self.log = tk.Text(reg, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0, height=8)
        self.log.pack(fill="both", expand=True)

    def aplicar_cores(self, escuro: bool):
        fundo = "#252525" if escuro else "#ffffff"
        frente = "#e6e6e6" if escuro else "#000000"
        try:
            self.log.configure(background=fundo, foreground=frente,
                               insertbackground=frente)
            self.lbl_sub.configure(foreground="#9a9a9a" if escuro else "#5f5f5f")
        except tk.TclError:
            pass

    # ------------------------------------------------------------- bomba de UI
    def _log(self, msg=""):
        """Pode ser chamado de QUALQUER thread: só enfileira."""
        self.q.put(("log", str(msg)))

    def _drain(self):
        try:
            while True:
                tipo, val = self.q.get_nowait()
                if tipo == "log":
                    self.log.insert("end", val + "\n"); self.log.see("end")
                elif tipo == "status":
                    self.lbl.config(text=val)
                elif tipo == "max":
                    self.pb.config(maximum=max(val, 1), value=0)
                elif tipo == "prog":
                    self.pb.config(value=val)
                elif tipo == "lista":
                    self._mostrar(val)
                elif tipo == "botoes":
                    normal, tem_lista = val
                    self.b1.config(state="normal" if normal else "disabled")
                    self.b2.config(state="normal" if (normal and tem_lista)
                                   else "disabled")
                    self.b_stop.config(state="disabled" if normal else "normal")
                elif tipo == "pasta":
                    self.ultima_pasta = val
                    self.b_abrir.config(state="normal" if val else "disabled")
                elif tipo == "resolver":
                    # Recado do download que roda na thread do navegador. Vai
                    # para a janela se ela ainda estiver aberta; senão, para o
                    # registro, que é onde a pessoa vai procurar depois.
                    aberta = False
                    try:
                        aberta = (self.janela is not None
                                  and self.janela.winfo_exists())
                    except tk.TclError:
                        aberta = False
                    if aberta:
                        self.janela.dizer(val)
                    else:
                        self.log.insert("end", val + "\n"); self.log.see("end")
        except queue.Empty:
            pass
        except Exception:
            pass                     # a bomba de UI nunca pode morrer
        finally:
            self.after(150, self._drain)

    def _mostrar(self, achados):
        self.tabela.delete(*self.tabela.get_children())
        for n, a in enumerate(achados):
            i = a.imovel
            situacao = a.revisao or (a.contrato or "—")
            if a.arquivado:
                situacao = "arquivado: " + Path(a.destino).name
            self.tabela.insert(
                "", "end", iid=str(n),
                values=(_MARCA[a.marcado], i.obra, i.rotulo, i.comprador,
                        f"{i.valor_financiamento:,.2f}",
                        a.empresa or "—", situacao))
        self._contar()
        self._atualizar_resolver()

    # ------------------------------------------------------------- marcação
    def _achado(self, iid: str):
        """O achado daquela linha. O iid É a posição na lista."""
        try:
            return self.achados[int(iid)]
        except (ValueError, IndexError):
            return None

    def _contar(self):
        marcadas = sum(1 for a in self.achados if a.marcado)
        self.lbl_marcadas.config(
            text=f"{marcadas} de {len(self.achados)} marcada(s)"
            if self.achados else "")

    def _alternar(self, iid: str):
        a = self._achado(iid)
        if a is None:
            return
        if not a.marcado and (a.revisao or not a.anexo):
            # Marcar não pode virar "grave assim mesmo": sem contrato não há o
            # que baixar, e sem empresa não há pasta de destino.
            self.lbl.config(text=f"Esta casa ainda não dá para arquivar — "
                                 f"{a.revisao or 'sem contrato escolhido'}.")
            return
        a.marcado = not a.marcado
        self.tabela.set(iid, "marca", _MARCA[a.marcado])
        self._contar()

    def _alternar_selecionada(self):
        for iid in self.tabela.selection():
            self._alternar(iid)

    def _marcar_todas(self, valor: bool):
        for n, a in enumerate(self.achados):
            if valor and (a.revisao or not a.anexo):
                continue                 # o que não dá para arquivar fica fora
            a.marcado = valor
            if self.tabela.exists(str(n)):
                self.tabela.set(str(n), "marca", _MARCA[a.marcado])
        self._contar()

    def _clique_na_tabela(self, ev):
        if (self.tabela.identify_region(ev.x, ev.y) == "cell"
                and self.tabela.identify_column(ev.x) == "#1"):
            self._alternar(self.tabela.identify_row(ev.y))

    def _duplo_clique(self, ev):
        if self.tabela.identify_column(ev.x) == "#1":
            return "break"               # dois cliques no ☑ é só alternar
        self._resolver()

    # -------------------------------------------------------------- resolver
    def _atualizar_resolver(self):
        a = self._achado((self.tabela.selection() or [""])[0])
        self.b_resolver.config(
            state="normal" if (a is not None and pipeline.pode_resolver(a)
                               and not a.arquivado) else "disabled")

    def _resolver(self):
        a = self._achado((self.tabela.selection() or [""])[0])
        if a is None:
            return
        if a.arquivado:
            messagebox.showinfo("Contratos", "Esta casa já foi arquivada.")
            return
        if not pipeline.pode_resolver(a):
            messagebox.showinfo(
                "Contratos",
                f"{a.revisao}\n\nSem a obra no cadastro do Mais Controle não "
                "há anexo para escolher — isso se resolve lá, não aqui.")
            return
        try:
            _, contas = _sicoob()
            empresas = [e.nome for e in contas.carregar().empresas]
        except Exception as e:
            messagebox.showerror("Cadastro", f"Não consegui ler as empresas:\n{e}")
            return
        self.janela = resolver.JanelaResolver(
            self, a, empresas,
            abrir_anexo=lambda anexo: self._abrir_anexo(a, anexo),
            ao_confirmar=lambda anexo, empresa, gravar:
                self._confirmado(a, anexo, empresa, gravar))

    def _confirmado(self, achado, anexo, empresa, gravar):
        """O que a janela decidiu, aplicado à lista (e ao cadastro)."""
        if empresa and gravar and empresa != achado.empresa:
            try:
                _, contas = _sicoob()
                contas.adicionar_cliente_erp(empresa, achado.cliente_erp)
                self._log(f'Cadastro: "{achado.cliente_erp}" agora é cliente '
                          f"de {empresa} no contas_sicoob.json.")
            except Exception as e:
                # A escolha continua valendo para esta rodada: perder o
                # trabalho da pessoa porque o arquivo estava aberto no bloco
                # de notas seria pior do que perguntar de novo no mês que vem.
                messagebox.showwarning(
                    "Não gravei no cadastro",
                    f"{e}\n\nA escolha vale para esta rodada; no mês que vem a "
                    "pergunta volta.")
        falta = pipeline.aplicar_resolucao(achado, anexo=anexo,
                                           empresa_nome=empresa)
        if anexo is not None:
            self.escolhas[pipeline.chave_da_casa(achado)] = \
                (anexo.get("filename") or "").strip()
        self._mostrar(self.achados)
        self._log(f"  RESOLVIDO  {achado.resumo}\n             "
                  + (f"ainda falta: {falta}" if falta
                     else f"contrato: {achado.contrato} · {achado.empresa}"))

    def _abrir_anexo(self, achado, anexo):
        """Baixa e abre o anexo para a pessoa olhar antes de escolher."""
        if self.anx.avisar_se_ocupado("abrir o anexo"):
            return
        self.worker = self.anx.submeter("Contratos — abrir anexo",
                                        self._t_abrir, achado, dict(anexo))

    # ---------------------------------------------------------------- ações
    def _periodo(self) -> tuple[int, int]:
        return int(self.v_ano.get()), MESES.index(self.v_mes.get()) + 1

    def _parar_click(self):
        self._parar.set()
        self._log("\n⏹ Parando… termino o contrato atual e paro.")
        self.b_stop.config(state="disabled")

    def _abrir_pasta(self):
        if not self.ultima_pasta:
            return
        try:
            os.startfile(str(self.ultima_pasta))
        except OSError as e:
            messagebox.showerror("Erro", f"Não consegui abrir a pasta:\n{e}")

    def buscar(self):
        if self.anx.avisar_se_ocupado("os Contratos"):
            return
        self._parar.clear()
        self.log.delete("1.0", "end")
        self.q.put(("botoes", (False, False)))
        self.worker = self.anx.submeter("Contratos — buscar", self._t_buscar)

    def arquivar(self):
        if self.anx.avisar_se_ocupado("os Contratos"):
            return
        if not [a for a in self.achados if a.marcado and not a.revisao and a.anexo]:
            prontas = [a for a in self.achados if not a.revisao and a.anexo]
            messagebox.showinfo(
                "Contratos",
                "Nenhuma casa marcada para arquivar."
                if prontas else "Nada para arquivar nesta lista.")
            return
        self._parar.clear()
        self.q.put(("botoes", (False, True)))
        self.worker = self.anx.submeter("Contratos — arquivar", self._t_arquivar)

    # -------------------------------------------------------------- threads
    def _t_buscar(self):
        comeco = time.time()
        try:
            cfg, contas = _sicoob()
            ano, mes = self._periodo()
            self.q.put(("status", "Entrando no Mais Controle..."))
            api = self.anx.garantir_sessao(self._log)
            if not api.capturar_credenciais(self._log):
                raise RuntimeError("Não capturei a lista de pagamentos — é dela "
                                   "que saem os cabeçalhos de autenticação.")
            # As obras e os anexos vivem no OUTRO back-end, com cabeçalho
            # próprio. Quem garante esse segundo acesso é o `pipeline`, que é
            # quem sabe que precisa dos dois; aqui só se avisa da espera.
            self.q.put(("status", "Preparando o acesso aos anexos..."))

            mapa = contas.carregar()
            for aviso in contas.validar(mapa):
                self._log(f"  [aviso do cadastro] {aviso}")

            self.q.put(("status", "Lendo os recebimentos do mês..."))
            self.achados = pipeline.levantar(
                api, ano, mes, mapa.empresas, self._log,
                cancelar=self._parar.is_set)

            voltaram = pipeline.reaplicar(self.achados, self.escolhas, self._log)
            if voltaram:
                self._log(f"{voltaram} escolha(s) desta sessão reaplicadas.")

            self.q.put(("lista", self.achados))
            prontos = [a for a in self.achados if not a.revisao and a.anexo]
            revisao = [a for a in self.achados if a.revisao]
            self._log("")
            self._log(f"{len(prontos)} contrato(s) prontos para arquivar, "
                      f"{len(revisao)} em revisão.")
            for a in revisao:
                self._log(f"  REVISÃO  {a.resumo}\n           {a.revisao}")
            if revisao:
                self._log("Dá para resolver na tela: selecione a casa e clique "
                          "em \"Resolver esta casa…\" (ou dê dois cliques nela).")
            self.q.put(("status", f"Busca concluída em "
                                  f"{_fmt_dur(time.time() - comeco)}."))
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "A busca parou por um erro."))
        finally:
            self.q.put(("botoes", (True, bool(self.achados))))

    def _t_arquivar(self):
        comeco = time.time()
        try:
            cfg, contas = _sicoob()
            ano, mes = self._periodo()
            mapa = contas.carregar()
            raiz = mapa.raiz or cfg.RAIZ_PADRAO

            api = self.anx.garantir_sessao(self._log)
            self._log("")
            self._log("Baixando e conferindo cada contrato "
                      "(o OCR deixa isto lento)...")
            pipeline.arquivar(
                api, self.achados, Path(raiz), ano, mes,
                cfg.nome_do_mes, cfg.nome_pasta_empresa,
                texto_do_pdf=_texto_do_pdf, log=self._log,
                cancelar=self._parar.is_set,
                progresso=lambda i, n: (self.q.put(("max", n)),
                                        self.q.put(("prog", i))))

            self.q.put(("lista", self.achados))
            arquivados = [a for a in self.achados if a.arquivado]
            retidos = [a for a in self.achados if a.anexo and not a.arquivado]
            self._log("")
            self._log(f"{len(arquivados)} arquivado(s), {len(retidos)} retido(s).")
            caminho = self._resumo(ano, mes, raiz)
            if caminho:
                self._log(f"Resumo: {str(caminho).replace(chr(92), '/')}")
                self.q.put(("pasta", caminho.parent))
            self.q.put(("status", f"Concluído em "
                                  f"{_fmt_dur(time.time() - comeco)}."))
        except Exception as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "O arquivamento parou por um erro."))
        finally:
            self.q.put(("botoes", (True, bool(self.achados))))

    def _t_abrir(self, achado, anexo):
        """Baixa um anexo e abre no visualizador padrão. Thread do navegador.

        Antes de baixar, relista os anexos DAQUELA obra: o `downloadUrl` é URL
        pré-assinada do S3 com `Expires` curto, e a pessoa costuma abrir a
        janela bem depois da busca. Sem isto, "abrir para olhar" viraria "rode
        a busca de novo", que é justamente o que a janela existe para evitar."""
        nome = (anexo.get("filename") or "anexo").strip()
        try:
            api = self.anx.garantir_sessao(self._log)
            frescos = api.anexos_de_obras([achado.obra_id], log=lambda m: None)
            atual = next(
                (x for x in (frescos.get(achado.obra_id) or [])
                 if util.norm_espaco(x.get("filename") or "")
                 == util.norm_espaco(nome)), anexo)
            dados = api.baixar_anexo(atual.get("downloadUrl"))
            if not dados:
                self.q.put(("resolver", f"não consegui baixar \"{nome}\"."))
                return
            alvo = (Path(tempfile.gettempdir()) / "contratos-mais-controle"
                    / (_limpar_nome(nome) or "anexo.pdf"))
            alvo.parent.mkdir(parents=True, exist_ok=True)
            alvo.write_bytes(dados)
            os.startfile(str(alvo))
            self.q.put(("resolver", f"abri \"{nome}\" para conferir."))
        except Exception as e:
            self.q.put(("resolver", f"não deu para abrir \"{nome}\": {e}"))

    def _resumo(self, ano: int, mes: int, raiz) -> Path | None:
        """Grava o resumo do mês ao lado dos contratos.

        Texto, e não PDF: o que se precisa daqui é conferir o que entrou e o
        que ficou de fora, e um .txt abre em qualquer lugar, sobrevive a
        navegador fechado e não depende do CDP."""
        cfg, _ = _sicoob()
        arquivados = [a for a in self.achados if a.arquivado]
        if not arquivados and not self.achados:
            return None
        try:
            pasta = (Path(raiz) / str(ano) / cfg.nome_do_mes(mes))
            pasta.mkdir(parents=True, exist_ok=True)
            alvo = pasta / f"CONTRATOS {ano}{mes:02d} - conferencia.txt"
            linhas = [f"Contratos de financiamento — {cfg.nome_do_mes(mes)} {ano}",
                      "=" * 64, ""]
            total = sum((a.imovel.valor_financiamento for a in self.achados),
                        start=type(self.achados[0].imovel.valor_financiamento)(0))
            linhas.append(f"{len(self.achados)} casa(s) com financiamento no mês, "
                          f"somando R$ {total:,.2f}")
            linhas.append(f"{len(arquivados)} arquivado(s)")
            linhas.append("")
            for a in self.achados:
                if not a.arquivado:
                    continue
                rs = conf.ressalvas(a.resultado_conferencia)
                extra = f"   (não deu para conferir: {', '.join(rs)})" if rs else ""
                linhas.append(f"OK   {a.resumo}")
                linhas.append(f"     -> {Path(a.destino).name}{extra}")
                # Quem decidiu à mão fica registrado. Daqui a seis meses é a
                # diferença entre auditar e adivinhar.
                mao = [t for t, sim in (("contrato escolhido à mão",
                                         a.contrato_manual),
                                        ("empresa definida à mão",
                                         a.empresa_manual)) if sim]
                if mao:
                    linhas.append(f"        ({'; '.join(mao)})")
            pendentes = [a for a in self.achados if not a.arquivado]
            if pendentes:
                linhas += ["", "PRECISAM DE REVISÃO", "-" * 64]
                for a in pendentes:
                    motivo = a.revisao or "não foi marcada para arquivar nesta rodada"
                    linhas.append(f"     {a.resumo}")
                    linhas.append(f"       {motivo}")
            alvo.write_text("\n".join(linhas) + "\n", encoding="utf-8")
            return alvo
        except OSError:
            return None
