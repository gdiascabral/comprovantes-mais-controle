# -*- coding: utf-8 -*-
"""Aba "Acessórias" (grupo MENSAL): envia o fechamento ao escritório contábil.

Dois passos, como Pagamentos do Dia, Extratos Sicoob e Contratos:

  1. Preparar — varre a pasta do mês, acha os zips e monta a mensagem de cada
                empresa. NÃO toca no portal.
  2. Enviar   — abre o Chrome, cria uma solicitação por empresa com o zip
                anexado e confere que ela chegou.

O passo separado existe porque `Salvar / Enviar` cria solicitação de verdade no
escritório: é ação externa que não se desfaz do lado de cá. Quem confere quer
VER a mensagem e o anexo antes — e é no passo 1 que um zip da empresa errada,
ou um cadastro faltando, aparece.

Ao contrário da Conferência, dos Aportes e do Relatório Mensal, esta aba NÃO
compartilha o navegador do AnexarFrame: o portal é outro site e outro login, e
o Playwright síncrono não divide thread. Daí o executor próprio e o perfil de
Chrome separado — a mesma decisão do `extratos_sicoob/`.
"""
from __future__ import annotations

import datetime
import os
import queue
import subprocess
import time
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from tkinter import messagebox, ttk

from . import config as cfg
from . import pacote
from .portal import EnvioNaoConfirmado, PortalClient, SessaoPerdida

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

_fmt_dur = util.fmt_dur

MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]


def _sicoob():
    """O pacote do Sicoob, importado tarde.

    A árvore do fechamento (raiz, nome do mês, pasta da empresa) e o cadastro
    das empresas já moram lá; duplicar aqui seria criar um segundo mapa — e
    julho de 2026 já ficou partido uma vez por causa de dois mapas discordando.
    O import é tardio para esta aba montar mesmo se o pacote do Sicoob não
    estiver no caminho, como faz a aba Contratos."""
    import sicoob_config as scfg
    import sicoob_contas as contas
    return scfg, contas


class AcessoriasFrame(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.q = queue.Queue()
        self.exec = ThreadPoolExecutor(max_workers=1,
                                       thread_name_prefix="acessorias")
        self.worker = None
        self._tarefa_atual = ""          # o que a barra lateral mostra
        self._parar = Event()
        self.mapa = None
        self.envios: list[pacote.Envio] = []
        self._selecionado: str | None = None      # iid da linha em edição
        self.ultima_pasta: Path | None = None

        hoje = datetime.date.today()
        anterior = hoje.replace(day=1) - datetime.timedelta(days=1)
        self.v_mes = tk.StringVar(value=MESES[anterior.month - 1])
        self.v_ano = tk.StringVar(value=str(anterior.year))
        self.v_assunto = tk.StringVar(value=pacote.MODELO_ASSUNTO)

        self._build()
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = widgets.PADX

        self.cab = widgets.Cabecalho(
            self, "Acessórias",
            "Envia o fechamento do mês ao escritório contábil: uma solicitação "
            "por empresa, com o .zip anexado.")
        self.cab.pack(fill="x", padx=PADX, pady=(12, 4))

        # ---- card 1: mês e modelos
        f1 = widgets.Cartao(self, "Mês e mensagem")
        f1.pack(fill="x", padx=PADX, pady=6)

        linha = ttk.Frame(f1); linha.pack(fill="x")
        ttk.Label(linha, text="Mês:").pack(side="left")
        ttk.Combobox(linha, textvariable=self.v_mes, values=MESES,
                     state="readonly", width=12).pack(side="left", padx=(6, 14))
        ttk.Label(linha, text="Ano:").pack(side="left")
        anos = [str(a) for a in range(datetime.date.today().year + 1, 2019, -1)]
        ttk.Combobox(linha, textvariable=self.v_ano, values=anos,
                     state="readonly", width=7).pack(side="left", padx=(6, 14))
        ttk.Label(linha, style="Apoio.TLabel",
                  text="(vem preenchido com o mês anterior)").pack(side="left")

        ttk.Label(f1, text="Assunto:").pack(anchor="w", pady=(10, 0))
        ttk.Entry(f1, textvariable=self.v_assunto).pack(fill="x")
        ttk.Label(f1, text="Comentário:").pack(anchor="w", pady=(8, 0))
        self.t_modelo = tk.Text(f1, wrap="word", height=5, borderwidth=1,
                                relief="solid")
        self.t_modelo.pack(fill="x")
        self.t_modelo.insert("1.0", pacote.MODELO_COMENTARIO)
        ttk.Label(f1, style="Apoio.TLabel", wraplength=820, justify="left",
                  text="Tokens: " + "  ".join(pacote.TOKENS) +
                       "   ·   a lista de contratos é lida de dentro do zip."
                  ).pack(anchor="w", pady=(4, 8))

        self.b1 = ttk.Button(f1, text="Preparar o envio",
                             style="Accent.TButton", command=self.preparar)
        self.b1.pack(side="left")
        ttk.Label(f1, style="Apoio.TLabel",
                  text="  Só lê a pasta do mês — não toca no portal."
                  ).pack(side="left")

        # ---- card 2: o que vai ser enviado
        f2 = widgets.Cartao(self, "O que vai ser enviado")
        f2.pack(fill="both", expand=True, padx=PADX, pady=6)

        colunas = ("empresa", "zip", "tamanho", "contratos", "situacao")
        self.tree = ttk.Treeview(f2, columns=colunas, show="headings",
                                 height=7, selectmode="browse")
        for chave, titulo, largura in (("empresa", "Empresa", 170),
                                       ("zip", "Arquivo", 260),
                                       ("tamanho", "Tamanho", 80),
                                       ("contratos", "Contratos", 80),
                                       ("situacao", "Situação", 260)):
            self.tree.heading(chave, text=titulo)
            self.tree.column(chave, width=largura,
                             anchor="center" if chave in ("tamanho", "contratos")
                             else "w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._trocar_selecao)

        ttk.Label(f2, style="Apoio.TLabel", wraplength=820, justify="left",
                  text="Clique numa empresa para ver e corrigir o texto que "
                       "vai ser enviado por ela.").pack(anchor="w", pady=(6, 2))
        self.t_previa = tk.Text(f2, wrap="word", height=7, borderwidth=1,
                                relief="solid")
        self.t_previa.pack(fill="both", expand=True)

        # ---- card 3: enviar
        f3 = widgets.Cartao(self, "Enviar ao escritório")
        f3.pack(fill="x", padx=PADX, pady=6)
        self.b2 = ttk.Button(f3, text="Enviar ao escritório", state="disabled",
                             style="Accent.TButton", command=self.enviar)
        self.b2.pack(side="left")
        self.b_stop = ttk.Button(f3, text="⏹ Parar", state="disabled",
                                 command=self._parar_click)
        self.b_stop.pack(side="left", padx=(8, 0))
        self.b_abrir = ttk.Button(f3, text="Abrir a pasta do mês",
                                  state="disabled", command=self._abrir_pasta)
        self.b_abrir.pack(side="left", padx=(8, 0))
        # Para ONDE vai é o dado que o formulário do portal esconde: o
        # departamento é um select cujos valores não seguem a ordem da tela, e
        # errá-lo manda o fechamento para o lugar errado sem nenhum aviso.
        # Deixar isso à vista é mais barato que descobrir depois.
        ttk.Label(f3, style="Apoio.TLabel",
                  text=f"  Vai para {cfg.DEPARTAMENTO}, prioridade "
                       f"{cfg.PRIORIDADE}. O login é feito por você, na janela "
                       f"do Chrome.").pack(side="left")

        # A trilha das AÇÕES, dentro do cabeçalho, como nas outras abas de dois
        # passos. Ela só pode nascer depois dos botões: é do `state` deles que
        # sai o estado da trilha.
        widgets.Passos(self.cab, (("Preparar", self.b1),
                                  ("Enviar", self.b2))
                       ).pack(anchor="w", pady=(8, 0))

        # ---- progresso e registro
        f4 = ttk.Frame(self); f4.pack(fill="x", padx=PADX, pady=6)
        self.pb = ttk.Progressbar(f4, mode="determinate")
        self.pb.pack(fill="x")
        self.lbl = ttk.Label(f4, text="Pronto.", style="Apoio.TLabel")
        self.lbl.pack(anchor="w", pady=(4, 4))
        self.log = tk.Text(f4, wrap="word", borderwidth=1, relief="solid")
        self.log.pack(fill="both", expand=True)
        widgets.estilo_log(self.log)
        widgets.registro_elastico(f4, self.log)

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
                    self.b1.configure(state=valor)
                    # O Enviar volta pelo que a tabela diz, não pelo que o
                    # lote fez: sobrando empresa pronta (uma falhou, o lote foi
                    # parado no meio), ele tem de estar clicável de novo.
                    self.b2.configure(
                        state="normal" if (valor == "normal"
                                           and any(e.pronta for e in self.envios))
                        else "disabled")
                    self.b_stop.configure(
                        state="disabled" if valor == "normal" else "normal")
                elif tipo == "envios":
                    self._mostrar_envios(valor)
                elif tipo == "linha":
                    self._atualizar_linha(valor)
                elif tipo == "pasta_pronta":
                    self.ultima_pasta = valor
                    self.b_abrir.configure(state="normal")
        except queue.Empty:
            pass
        self.after(150, self._drain)

    def aplicar_cores(self, escuro: bool):
        for campo in (self.log, self.t_modelo, self.t_previa):
            try:
                widgets.estilo_log(campo, escuro)
            except tk.TclError:
                pass

    def ocupado(self) -> str | None:
        """O que esta aba está fazendo agora, ou None.

        O navegador daqui é OUTRO (o portal é outro site e outro login), então
        a barra lateral pergunta a esta aba separadamente — o registro de dono
        do AnexarFrame não sabe nada do que acontece aqui."""
        fut = self.worker
        if fut is not None and not fut.done():
            return self._tarefa_atual or "Acessórias"
        return None

    def _parar_click(self):
        self._parar.set()
        self.lbl.configure(text="Parando após a empresa atual...")
        self.b_stop.configure(state="disabled")

    def _abrir_pasta(self):
        if self.ultima_pasta and self.ultima_pasta.is_dir():
            try:
                os.startfile(self.ultima_pasta)          # noqa: S606 (Windows)
            except Exception:
                subprocess.Popen(["explorer", str(self.ultima_pasta)])

    # ---------------------------------------------------------------- tabela
    def _envio_por_iid(self, iid: str | None) -> pacote.Envio | None:
        if iid is None:
            return None
        try:
            return self.envios[int(iid)]
        except (ValueError, IndexError):
            return None

    def _guardar_edicao(self):
        """Passa o texto da prévia de volta para o envio em edição.

        A primeira linha é o assunto; o resto é o comentário. Um campo só, e
        não dois, porque é assim que a mensagem chega ao escritório: título e
        corpo, um debaixo do outro."""
        envio = self._envio_por_iid(self._selecionado)
        if envio is None:
            return
        try:
            texto = self.t_previa.get("1.0", "end-1c")
        except tk.TclError:
            return
        assunto, _, comentario = texto.partition("\n")
        envio.assunto = assunto.strip()
        envio.comentario = comentario.strip("\n")

    def _trocar_selecao(self, _ev=None):
        self._guardar_edicao()
        selecao = self.tree.selection()
        self._selecionado = selecao[0] if selecao else None
        envio = self._envio_por_iid(self._selecionado)
        self.t_previa.delete("1.0", "end")
        if envio is None:
            return
        self.t_previa.insert("1.0", f"{envio.assunto}\n{envio.comentario}")

    def _mostrar_envios(self, envios: list[pacote.Envio]):
        self.envios = envios
        self._selecionado = None
        self.tree.delete(*self.tree.get_children())
        self.t_previa.delete("1.0", "end")
        for i, e in enumerate(envios):
            self.tree.insert(
                "", "end", iid=str(i),
                values=(e.empresa, e.caminho.name, e.tamanho_legivel,
                        len(e.contratos) or "—",
                        e.problema or e.situacao or "pronta"))
        prontos = [e for e in envios if e.pronta]
        self.b2.configure(state="normal" if prontos else "disabled")
        if envios:
            self.tree.selection_set("0")

    def _atualizar_linha(self, dados):
        indice, situacao = dados
        iid = str(indice)
        if self.tree.exists(iid):
            valores = list(self.tree.item(iid, "values"))
            valores[4] = situacao
            self.tree.item(iid, values=valores)

    # ----------------------------------------------------------------- mapa
    def _periodo(self) -> tuple[int, int]:
        return int(self.v_ano.get()), MESES.index(self.v_mes.get()) + 1

    def _garantir_mapa(self) -> bool:
        _, contas = _sicoob()
        try:
            self.mapa = contas.carregar()
        except contas.MapaInvalido as e:
            self._log(f"[!] {e}")
            self.q.put(("status", "Falta preencher o arquivo de contas."))
            return False
        return True

    # ------------------------------------------------------------- preparar
    def preparar(self):
        if self.worker and not self.worker.done():
            return
        self.q.put(("botoes", "disabled"))
        self.q.put(("status", "Lendo a pasta do mês..."))
        self._tarefa_atual = "Acessórias — preparar"
        modelo_assunto = self.v_assunto.get()
        modelo_comentario = self.t_modelo.get("1.0", "end-1c")
        self.worker = self.exec.submit(self._t_preparar, modelo_assunto,
                                       modelo_comentario)

    def _t_preparar(self, modelo_assunto: str, modelo_comentario: str):
        try:
            if not self._garantir_mapa():
                return
            scfg, _ = _sicoob()
            ano, mes = self._periodo()
            envios = pacote.montar(self.mapa, ano, mes, scfg.nome_do_mes,
                                   scfg.nome_pasta_empresa,
                                   modelo_assunto, modelo_comentario)
            pasta = pacote.pasta_do_mes(self.mapa.raiz, ano, mes,
                                        scfg.nome_do_mes)
            self.q.put(("pasta_pronta", pasta))

            if not envios:
                self._log(f"Nenhum .zip em {str(pasta).replace(chr(92), '/')}")
                self._log("Gere os .zip na aba Extratos Sicoob (passo 4) antes "
                          "de enviar.")
                self.q.put(("envios", []))
                self.q.put(("status", "Nada para enviar: falta zipar o mês."))
                return

            for e in envios:
                marca = "[!]" if e.problema else "   "
                extra = e.problema or (f"{len(e.contratos)} contrato(s)"
                                       if e.contratos else "sem contratos no zip")
                self._log(f"{marca} {e.caminho.name}  ({e.tamanho_legivel}) — "
                          f"{extra}")

            travas = pacote.impedimentos(envios)
            if travas:
                self._log("")
                self._log("[!] O lote não pode começar assim:")
                for t in travas:
                    self._log(f"    {t}")

            self.q.put(("envios", envios))
            prontas = sum(1 for e in envios if e.pronta)
            self.q.put(("status", f"{prontas} de {len(envios)} empresa(s) "
                                  f"prontas para enviar."))
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] {e}")
            self.q.put(("status", "Não consegui preparar o envio."))
        finally:
            self.q.put(("botoes", "normal"))

    # --------------------------------------------------------------- enviar
    def enviar(self):
        """A confirmação abre AQUI, na thread da interface e ANTES de submeter.

        Quem cancela não pode ter aberto navegador nem consumido nada — é a
        mesma razão pela qual o Pagamentos do Dia confirma antes de `submeter`.
        """
        if self.worker and not self.worker.done():
            return
        self._guardar_edicao()

        travas = pacote.impedimentos(self.envios)
        if travas:
            messagebox.showerror(
                "Acessórias",
                "Não dá para enviar enquanto isto não for resolvido:\n\n"
                + "\n".join(f"• {t}" for t in travas[:8]))
            return

        pendentes = [e for e in self.envios if e.pronta]
        if not pendentes:
            messagebox.showinfo("Acessórias", "Não há empresa pronta para "
                                              "enviar. Prepare o mês primeiro.")
            return

        total_mb = pacote.fmt_tamanho(sum(e.tamanho for e in pendentes))
        nomes = "\n".join(f"  {e.empresa} — {e.caminho.name}"
                          for e in pendentes[:12])
        if len(pendentes) > 12:
            nomes += f"\n  ... e mais {len(pendentes) - 12}"
        if not messagebox.askyesno(
                "Enviar ao escritório",
                f"Vou criar {len(pendentes)} solicitação(ões) no portal, "
                f"com {total_mb} de anexo no total:\n\n{nomes}\n\n"
                "Isso não se desfaz daqui. Enviar agora?"):
            self._log("\nEnvio cancelado.")
            return

        self._parar.clear()
        self.q.put(("botoes", "disabled"))
        self.b2.configure(state="disabled")
        self.q.put(("status", "Abrindo o Chrome do portal..."))
        self._tarefa_atual = "Acessórias — enviar"
        self.worker = self.exec.submit(self._t_enviar, pendentes)

    def _t_enviar(self, pendentes: list[pacote.Envio]):
        inicio = time.time()
        indices = {id(e): i for i, e in enumerate(self.envios)}
        enviadas = repetidas = falhas = 0
        try:
            total = len(pendentes)
            self.q.put(("progresso", (0, total)))
            with PortalClient(self.mapa.vip_url, log=self._log) as cli:
                cli.aguardar_login()
                for n, envio in enumerate(pendentes, start=1):
                    if self._parar.is_set():
                        self._log("\nParado a pedido.")
                        break
                    i = indices.get(id(envio), -1)
                    self.q.put(("status",
                                f"[{n}/{total}] {envio.empresa}..."))
                    self._log(f"\n[{n}/{total}] {envio.empresa}")
                    try:
                        ja = cli.procurar(envio.vip_id, envio.assunto)
                        if ja is not None:
                            repetidas += 1
                            situacao = f"já enviada em {ja.data or '?'}"
                            self._log(f"    {situacao} — pulando "
                                      f"(solicitação {ja.id})")
                            self.q.put(("linha", (i, situacao)))
                            continue

                        cli.criar_solicitacao(envio.vip_id, envio.assunto,
                                              envio.comentario, envio.caminho)
                        s = cli.conferir_envio(envio.vip_id, envio.assunto,
                                               envio.caminho.name)
                        enviadas += 1
                        self._log(f"    enviada e conferida "
                                  f"(solicitação {s.id})")
                        self.q.put(("linha", (i, f"enviada [{s.id}]")))
                    except SessaoPerdida:
                        raise
                    except EnvioNaoConfirmado as e:
                        falhas += 1
                        self._log(f"    [!] erro:nao_confirmado — {e}")
                        self._log("        Confira esta empresa pela tela do "
                                  "portal antes de repetir.")
                        self.q.put(("linha", (i, "NÃO CONFIRMADO")))
                    except Exception as e:                  # noqa: BLE001
                        falhas += 1
                        self._log(f"    [!] {e}")
                        self.q.put(("linha", (i, f"erro: {e}")))
                    finally:
                        self.q.put(("progresso", (n, total)))

            self.q.put(("status",
                        f"{enviadas} enviada(s), {repetidas} já estavam lá, "
                        f"{falhas} com erro em {_fmt_dur(time.time() - inicio)}."))
        except SessaoPerdida as e:
            self._log(f"[!] {e}")
            self._log("Entre de novo no Chrome e rode o envio outra vez — "
                      "quem já foi enviada será pulada.")
            self.q.put(("status", "A sessão do portal caiu."))
        except Exception as e:                              # noqa: BLE001
            self._log(f"[!] {e}")
            self.q.put(("status", "O envio parou por um erro."))
        finally:
            self.q.put(("botoes", "normal"))

    # ----------------------------------------------------------------- saída
    def fechar(self):
        self._parar.set()
        self.exec.shutdown(wait=False)
