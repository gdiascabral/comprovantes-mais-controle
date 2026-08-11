# -*- coding: utf-8 -*-
"""
Aba "Extratos Sicoob": cria a árvore do mês e baixa OFX + PDF das contas.

Ao contrário da Conferência, dos Aportes e do Relatório Mensal, esta aba NÃO
compartilha o navegador do AnexarFrame: o Sicoob é outro site e outro login, e
o Playwright síncrono não divide thread. Daí o executor próprio e o perfil de
Chrome separado.

O login no Sicoob é manual — a tela tem reCAPTCHA. A aba avisa e espera.
"""
from __future__ import annotations

import datetime
import os
import queue
import subprocess
import sys
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from tkinter import messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sicoob_baixar                                          # noqa: E402
import sicoob_contas as sc                                    # noqa: E402
import sicoob_pastas as sp                                    # noqa: E402
import sicoob_zipar                                           # noqa: E402
from sicoob_client import SicoobClient                        # noqa: E402

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

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]




class ExtratosSicoobFrame(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.q = queue.Queue()
        self.exec = ThreadPoolExecutor(max_workers=1,
                                       thread_name_prefix="sicoob")
        self.worker = None
        self._parar = Event()
        self.mapa: sc.Mapa | None = None
        self.ultima_pasta: Path | None = None

        hoje = datetime.date.today()
        anterior = hoje.replace(day=1) - datetime.timedelta(days=1)
        self.v_mes = tk.StringVar(value=MESES[anterior.month - 1])
        self.v_ano = tk.StringVar(value=str(anterior.year))

        self._build()
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = 14

        cab = ttk.Frame(self)
        cab.pack(fill="x", padx=PADX, pady=(12, 4))
        ttk.Label(cab, text="Extratos Sicoob",
                  font=("Segoe UI", 14, "bold")).pack(anchor="w")
        ttk.Label(cab, foreground="#6b6b6b",
                  text="Cria as pastas do mês e baixa o extrato de cada conta "
                       "do Sicoob em OFX e PDF.").pack(anchor="w")

        # ---- card 1: mês
        f1 = ttk.LabelFrame(self, text=" 1. Mês do fechamento ",
                            padding=(12, 8, 12, 10))
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
                  text="(vem preenchido com o mês anterior)").pack(side="left")

        # ---- card 2: pastas
        f2 = ttk.LabelFrame(self, text=" 2. Pastas ", padding=(12, 8, 12, 10))
        f2.pack(fill="x", padx=PADX, pady=6)
        self.b1 = ttk.Button(f2, text="Conferir e criar pastas",
                             style="Accent.TButton", command=self.criar_pastas)
        self.b1.pack(side="left")
        ttk.Label(f2, foreground="#6b6b6b",
                  text="  Mostra o que será criado e pede confirmação."
                  ).pack(side="left")

        # ---- card 3: download
        f3 = ttk.LabelFrame(self, text=" 3. Baixar extratos ",
                            padding=(12, 8, 12, 10))
        f3.pack(fill="x", padx=PADX, pady=6)
        self.b2 = ttk.Button(f3, text="Baixar extratos do Sicoob",
                             style="Accent.TButton", command=self.baixar)
        self.b2.pack(side="left")
        self.b_stop = ttk.Button(f3, text="⏹ Parar", state="disabled",
                                 command=self._parar_click)
        self.b_stop.pack(side="left", padx=(8, 0))
        ttk.Label(f3, foreground="#6b6b6b",
                  text="  O login é feito por você, na janela do Chrome."
                  ).pack(side="left")

        # ---- card 4: zip
        f4 = ttk.LabelFrame(self, text=" 4. Compactar (quando o mês fechar) ",
                            padding=(12, 8, 12, 10))
        f4.pack(fill="x", padx=PADX, pady=6)
        self.b3 = ttk.Button(f4, text="Gerar os .zip por empresa",
                             command=self.zipar)
        self.b3.pack(side="left")
        self.b_abrir = ttk.Button(f4, text="Abrir a pasta do mês",
                                  state="disabled", command=self._abrir_pasta)
        self.b_abrir.pack(side="left", padx=(8, 0))
        ttk.Label(f4, foreground="#6b6b6b",
                  text="  Rode só depois que os outros bancos entrarem."
                  ).pack(side="left")

        # ---- progresso e log
        f5 = ttk.Frame(self); f5.pack(fill="both", expand=True, padx=PADX, pady=6)
        self.pb = ttk.Progressbar(f5, mode="determinate")
        self.pb.pack(fill="x")
        self.lbl = ttk.Label(f5, text="Pronto.", foreground="#6b6b6b")
        self.lbl.pack(anchor="w", pady=(4, 4))
        self.log = tk.Text(f5, height=14, wrap="word", borderwidth=1,
                           relief="solid")
        self.log.pack(fill="both", expand=True)

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
                elif tipo == "botoes":
                    for b in (self.b1, self.b2, self.b3):
                        b.configure(state=valor)
                    self.b_stop.configure(
                        state="disabled" if valor == "normal" else "normal")
                elif tipo == "pasta_pronta":
                    self.ultima_pasta = valor
                    self.b_abrir.configure(state="normal")
                elif tipo == "confirmar_pastas":
                    self._confirmar_pastas(valor)
        except queue.Empty:
            pass
        self.after(150, self._drain)

    def aplicar_cores(self, escuro: bool):
        fundo = "#1c1c1c" if escuro else "#ffffff"
        frente = "#e8e8e8" if escuro else "#000000"
        try:
            self.log.configure(background=fundo, foreground=frente,
                               insertbackground=frente)
        except tk.TclError:
            pass

    def _parar_click(self):
        self._parar.set()
        self.lbl.configure(text="Parando após a conta atual...")
        self.b_stop.configure(state="disabled")

    def _abrir_pasta(self):
        if self.ultima_pasta and self.ultima_pasta.is_dir():
            try:
                os.startfile(self.ultima_pasta)          # noqa: S606 (Windows)
            except Exception:
                subprocess.Popen(["explorer", str(self.ultima_pasta)])

    # ----------------------------------------------------------------- mapa
    def _periodo(self) -> tuple[int, int]:
        return int(self.v_ano.get()), MESES.index(self.v_mes.get()) + 1

    def _garantir_mapa(self) -> bool:
        """Carrega o mapa das contas, avisando de forma legível quando falta."""
        try:
            self.mapa = sc.carregar()
        except sc.MapaInvalido as e:
            caminho = sc.criar_modelo()
            self._log(f"[!] {e}")
            self._log(f"Criei um modelo em {str(caminho).replace(chr(92), '/')}")
            self.q.put(("status", "Falta preencher o arquivo de contas."))
            return False
        avisos = sc.validar(self.mapa)
        for a in avisos:
            self._log(f"[aviso] {a}")
        return True

    # -------------------------------------------------------------- pastas
    def criar_pastas(self):
        if self.worker and not self.worker.done():
            return
        self.q.put(("botoes", "disabled"))
        self.q.put(("status", "Conferindo as pastas..."))
        self.worker = self.exec.submit(self._t_pastas)

    def _conferir_mapas(self):
        """Avisa se o contas_mc.json manda alguma conta para outra pasta.

        O OFX/PDF daqui e o PDF do Relatório Mensal são da MESMA conta e do
        MESMO mês. Mapas divergentes partem o mês entre duas pastas, e nada no
        disco denuncia — as duas existem e as duas têm arquivo dentro."""
        try:
            import conferir_mapas
            import contas_mc
            import sicoob_config
            n = conferir_mapas.avisar(contas_mc.ARQUIVO_MAPA,
                                      sicoob_config.ARQUIVO_CONTAS, self._log)
            if n:
                self._log("  Alinhe os dois arquivos antes de baixar.")
        except Exception:
            pass          # a conferência é um extra; nunca pode barrar a aba

    def _t_pastas(self):
        try:
            if not self._garantir_mapa():
                return
            self._conferir_mapas()
            ano, mes = self._periodo()
            orfas = sp.comparar_com_mes_anterior(self.mapa, ano, mes)
            if orfas:
                self._log("[aviso] Existem no mês anterior e não estão no mapa: "
                          + ", ".join(orfas))
            plano = sp.planejar(self.mapa, ano, mes)
            self._log(sp.resumo(plano))
            novas = [p for p in plano if p.nova]
            if not novas:
                self._log("\nTodas as pastas já existem — nada a criar.")
                self.q.put(("status", "Pastas já estavam prontas."))
                self.q.put(("pasta_pronta", sp.caminho_do_mes(self.mapa, ano, mes)))
                return
            self.q.put(("confirmar_pastas", (plano, novas, ano, mes)))
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui montar a árvore de pastas."))
        finally:
            self.q.put(("botoes", "normal"))

    def _confirmar_pastas(self, dados):
        """Confirmação na thread da interface — messagebox não roda em worker."""
        plano, novas, ano, mes = dados
        detalhe = "\n".join(f"  {p.caminho.name}" if not p.subpasta
                            else f"      {p.subpasta}" for p in novas[:14])
        if len(novas) > 14:
            detalhe += f"\n  ... e mais {len(novas) - 14}"
        if not messagebox.askyesno(
                "Criar pastas",
                f"{len(novas)} pasta(s) serão criadas em\n"
                f"{str(sp.caminho_do_mes(self.mapa, ano, mes)).replace(chr(92), '/')}\n\n"
                f"{detalhe}\n\nCriar agora?"):
            self._log("\nCriação cancelada.")
            return
        criadas = sp.criar(plano)
        self._log(f"\n{len(criadas)} pasta(s) criadas.")
        self.lbl.configure(text=f"{len(criadas)} pastas criadas.")
        self.ultima_pasta = sp.caminho_do_mes(self.mapa, ano, mes)
        self.b_abrir.configure(state="normal")

    # -------------------------------------------------------------- baixar
    def baixar(self):
        if self.worker and not self.worker.done():
            return
        self._parar.clear()
        self.q.put(("botoes", "disabled"))
        self.q.put(("status", "Abrindo o Chrome do Sicoob..."))
        self.worker = self.exec.submit(self._t_baixar)

    def _t_baixar(self):
        inicio = time.time()
        try:
            if not self._garantir_mapa():
                return
            ano, mes = self._periodo()
            faltando = [c for c in self.mapa.contas
                        if not sp.caminho_da_conta(
                            self.mapa, ano, mes, c.numero).is_dir()]
            if faltando:
                self._log("[!] As pastas do mês ainda não existem. "
                          "Rode o passo 2 antes.")
                self.q.put(("status", "Crie as pastas primeiro."))
                return

            total = len(self.mapa.contas)
            self.q.put(("progresso", (0, total)))
            with SicoobClient(log=self._log) as cli:
                cli.aguardar_login()
                self.q.put(("status", f"Baixando {total} contas..."))
                feitos = {"n": 0}

                def log_e_progresso(msg=""):
                    self._log(msg)
                    if msg.startswith("["):
                        feitos["n"] += 1
                        self.q.put(("progresso", (feitos["n"] - 1, total)))

                rel = sicoob_baixar.baixar_mes(
                    cli, self.mapa, ano, mes, log=log_e_progresso,
                    parar=self._parar.is_set)
                self.q.put(("progresso", (total, total)))

            self.q.put(("pasta_pronta", sp.caminho_do_mes(self.mapa, ano, mes)))
            self.q.put(("status",
                        f"{len(rel.completos)}/{total} contas completas "
                        f"em {_fmt_dur(time.time() - inicio)}."))
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] {e}")
            self.q.put(("status", "O download parou por um erro."))
        finally:
            self.q.put(("botoes", "normal"))

    # ---------------------------------------------------------------- zipar
    def zipar(self):
        if self.worker and not self.worker.done():
            return
        self.q.put(("botoes", "disabled"))
        self.q.put(("status", "Compactando..."))
        self.worker = self.exec.submit(self._t_zipar)

    def _t_zipar(self):
        try:
            if not self._garantir_mapa():
                return
            ano, mes = self._periodo()
            resultados = sicoob_zipar.zipar_mes(self.mapa, ano, mes, log=self._log)
            feitos = sum(1 for r in resultados if r.caminho)
            self.q.put(("pasta_pronta", sp.caminho_do_mes(self.mapa, ano, mes)))
            self.q.put(("status", f"{feitos} arquivo(s) .zip gerados."))
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui compactar."))
        finally:
            self.q.put(("botoes", "normal"))

    # ----------------------------------------------------------------- saída
    def fechar(self):
        self._parar.set()
        self.exec.shutdown(wait=False)
