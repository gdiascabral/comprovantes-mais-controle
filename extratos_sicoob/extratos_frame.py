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
import sicoob_config                                          # noqa: E402
import sicoob_contas as sc                                    # noqa: E402
import sicoob_pastas as sp                                    # noqa: E402
import sicoob_zipar                                           # noqa: E402
from sicoob_client import SicoobClient                        # noqa: E402

# Estes três vivem em OUTRAS pastas de aba, e entram aqui em cima de
# propósito. Enquanto o import morava dentro do `try` do `_conferir_mapas`, o
# `except Exception: pass` engolia junto a falha de IMPORTAR: bastava a ordem
# do sys.path mudar, ou um arquivo faltar no codigo.zip, para a conferência que
# impede o mês partido sumir para sempre — sem uma linha em lugar nenhum. Aqui,
# se algum dia faltar, o app não abre e alguém fica sabendo no mesmo dia.
try:                                     # os dois mapas de pasta (aba vizinha)
    import conferir_mapas                                     # noqa: E402
    import contas_mc                                          # noqa: E402
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                           / "relatorios"))
    import conferir_mapas                                     # noqa: E402
    import contas_mc                                          # noqa: E402

try:                                     # o diagnostico.log é um só, no Anexar
    import config                                             # noqa: E402
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "anexar"))
    import config                                             # noqa: E402

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

try:                                     # widgets compartilhados (raiz)
    import widgets
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import widgets

#: A medida de layout que segue a fonte. `px(14)` são "os 14 px de quem
#: desenhou esta tela a 100%", ditos na escala de hoje — a 150% saem 21, e
#: a 100% saem os mesmos 14. Ver o bloco do `px` no `widgets.py`.
px = widgets.px

#: Duração e pasta-base vinham em cópias byte a byte por aba. Uma cópia de
#: regra de CAMINHO é como um app passa a procurar o mesmo arquivo em dois
#: lugares; uma de FORMATO é como a mesma duração aparece de dois jeitos.
_fmt_dur = util.fmt_dur

#: Rótulo de TELA. A tabela que vira nome de pasta é a `util.MESES_PASTA`,
#: e quem guarda a forma de exibição é o `widgets`, par visual do `util`.
MESES = list(widgets.MESES)




class ExtratosSicoobFrame(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.q = queue.Queue()
        self.exec = ThreadPoolExecutor(max_workers=1,
                                       thread_name_prefix="sicoob")
        self.worker = None
        self._tarefa_atual = ""          # o que a barra lateral mostra
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
        PADX = px(widgets.PADX)

        cab = widgets.Cabecalho(
            self, "Extratos Sicoob",
            "Cria as pastas do mês e baixa o extrato de cada conta do Sicoob "
            "em OFX e PDF.",
            trilha="Mensal  ›  Extratos Sicoob")
        cab.pack(fill="x", padx=PADX, pady=px((16, 12)))
        # O verde é BAIXAR: criar pasta e compactar são o antes e o depois.
        self.b1 = widgets.Botao(cab.acoes, "Conferir e criar pastas",
                                papel="passo", command=self.criar_pastas)
        self.b1.pack(side="left", padx=px((0, 8)))
        self.b2 = widgets.Botao(cab.acoes, "Baixar extratos", papel="acao",
                                command=self.baixar)
        self.b2.pack(side="left")

        # ---- card 1: mês
        f1 = widgets.Cartao(self, "Mês do fechamento", 1)
        f1.pack(fill="x", padx=PADX, pady=px((0, 12)))
        linha = ttk.Frame(f1)
        linha.pack(fill="x")
        widgets.Campo(linha, "Mês", lambda p: ttk.Combobox(
            p, textvariable=self.v_mes, values=MESES, state="readonly",
            width=12)).pack(side="left", padx=px((0, 16)))
        anos = [str(a) for a in range(datetime.date.today().year + 1, 2019, -1)]
        widgets.Campo(linha, "Ano", lambda p: ttk.Combobox(
            p, textvariable=self.v_ano, values=anos, state="readonly",
            width=7)).pack(side="left", padx=px((0, 16)))
        ttk.Label(linha, style="Tenue.TLabel",
                  text="vem preenchido com o mês anterior"
                  ).pack(side="left", pady=px((15, 0)))

        # ---- card 2: o que cada passo faz
        # Os três cartões que só seguravam um botão viraram um só: com o botão
        # no cabeçalho, o que sobrava neles era a frase de explicação — e três
        # cartões brancos com uma frase cada eram três cartões vazios.
        f2 = widgets.Cartao(self, "Como o mês fecha", 2)
        f2.pack(fill="x", padx=PADX, pady=px((0, 12)))
        for titulo, frase in (
                ("Conferir e criar pastas",
                 "Mostra o que será criado e pede confirmação."),
                ("Baixar extratos",
                 "O login é feito por você, na janela do Chrome."),
                ("Gerar os .zip por empresa",
                 "Rode só depois que os outros bancos entrarem.")):
            passo = ttk.Frame(f2)
            passo.pack(fill="x", pady=px((0, 6)))
            ttk.Label(passo, text=titulo, style="Forte.TLabel").pack(anchor="w")
            ttk.Label(passo, text=frase, style="Tenue.TLabel").pack(anchor="w")

        # ---- barra de execução, acima do registro
        acao = ttk.Frame(self, style="Fundo.TFrame")
        acao.pack(fill="x", padx=PADX, pady=px((0, 10)))
        btns = ttk.Frame(acao, style="Fundo.TFrame")
        btns.pack(side="right", padx=px((16, 0)))
        self.b_stop = widgets.Botao(btns, "⏹  Parar", papel="perigo",
                                    state="disabled", command=self._parar_click)
        self.b_stop.pack(side="left")
        self.b3 = widgets.Botao(btns, "🗜  Gerar os .zip", papel="neutro",
                                command=self.zipar)
        self.b3.pack(side="left", padx=px((8, 0)))
        self.b_abrir = widgets.Botao(btns, "📂  Abrir a pasta do mês",
                                     papel="neutro", state="disabled",
                                     command=self._abrir_pasta)
        self.b_abrir.pack(side="left", padx=px((8, 0)))
        self.barra_exec = widgets.BarraExecucao(acao)
        self.barra_exec.pack(side="left", fill="x", expand=True)
        self.lbl = self.barra_exec.lbl
        self.pb = self.barra_exec.pb

        # ---- registro
        self.reg = widgets.Cartao(self, "Registro", padding=(12, 10))
        self.reg.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.log = tk.Text(self.reg, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0)
        self.log.pack(fill="both", expand=True)
        widgets.estilo_log(self.log)
        widgets.registro_elastico(self.reg, self.log)

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
                    self.barra_exec.progresso(feitos, total)
                elif tipo == "botoes":
                    for b in (self.b1, self.b2, self.b3):
                        b.configure(state=valor)
                    self.b_stop.configure(
                        state="disabled" if valor == "normal" else "normal")
                elif tipo == "pasta_pronta":
                    self.ultima_pasta = valor
                    self.b_abrir.configure(state="normal")
                    widgets.registrar_atividade(
                        "ext", "Extratos do mês", "ok",
                        str(self.lbl.cget("text"))[:120])
                elif tipo == "confirmar_pastas":
                    self._confirmar_pastas(valor)
        except queue.Empty:
            pass
        self.after(150, self._drain)

    def aplicar_cores(self, escuro: bool):
        try:
            widgets.estilo_log(self.log, escuro)
        except tk.TclError:
            pass

    def ocupado(self) -> str | None:
        """O que esta aba está fazendo agora, ou None.

        O navegador daqui é OUTRO (Sicoob é outro site e outro login), então a
        barra lateral pergunta a esta aba separadamente — o registro de dono do
        AnexarFrame não sabe nada do que acontece aqui."""
        fut = self.worker
        if fut is not None and not fut.done():
            return self._tarefa_atual or "Extratos Sicoob"
        return None

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
        # Aviso é aviso: cadastro estranho pode ser só cadastro estranho, e
        # travar o lote por causa dele custaria o fechamento inteiro.
        barram = sc.impedimentos(self.mapa)
        for a in avisos:
            if a not in barram:
                self._log(f"[aviso] {a}")
        if barram:
            # Este BARRA, no mesmo espírito de "conta sem destino trava o lote
            # antes do primeiro download": duas contas gravando o mesmo
            # arquivo perdem uma das duas, e o relatório diz que as duas
            # ficaram prontas. Depois do lote não há o que desfazer — o
            # arquivo que foi sobrescrito não volta.
            self._log("[!] O lote não pode rodar com o cadastro assim:")
            for b in barram:
                self._log(f"    {b}")
            self.q.put(("status", "Corrija o cadastro das contas antes de rodar."))
            return False
        return True

    # -------------------------------------------------------------- pastas
    def criar_pastas(self):
        if self.worker and not self.worker.done():
            return
        self.q.put(("botoes", "disabled"))
        self.q.put(("status", "Conferindo as pastas..."))
        self._tarefa_atual = "Extratos Sicoob — criar pastas"
        self.worker = self.exec.submit(self._t_pastas)

    def _conferir_mapas(self):
        """Avisa se o contas_mc.json manda alguma conta para outra pasta.

        O OFX/PDF daqui e o PDF do Relatório Mensal são da MESMA conta e do
        MESMO mês. Mapas divergentes partem o mês entre duas pastas, e nada no
        disco denuncia — as duas existem e as duas têm arquivo dentro.

        Continua sem poder barrar a aba, mas não sem poder ser vista falhar:
        o `pass` de antes fazia "não achei divergência" e "não consegui
        conferir" ficarem idênticos para quem olha a tela."""
        try:
            n = conferir_mapas.avisar(contas_mc.ARQUIVO_MAPA,
                                      sicoob_config.ARQUIVO_CONTAS, self._log)
            if n:
                self._log("  Alinhe os dois arquivos antes de baixar.")
        except Exception as e:            # noqa: BLE001 — degrada, mas registra
            config.diag(f"Extratos Sicoob: a conferência dos dois mapas não "
                        f"rodou ({e!r})")
            self._log("  [aviso] não consegui conferir os dois mapas de pasta "
                      "(o motivo ficou no diagnostico.log).")

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
        self._tarefa_atual = "Extratos Sicoob — baixar"
        self.worker = self.exec.submit(self._t_baixar)

    def _t_baixar(self):
        inicio = time.time()
        try:
            if not self._garantir_mapa():
                return
            # Também aqui, e não só no passo que cria pastas: este é o passo
            # que BAIXA, e é o arquivo baixado que fica na pasta errada.
            # Mapas alinhados não escrevem nada, então não polui o registro.
            self._conferir_mapas()
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
        self._tarefa_atual = "Extratos Sicoob — compactar"
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
