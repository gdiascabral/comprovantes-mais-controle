# -*- coding: utf-8 -*-
"""Aba "Acessorias" (grupo MENSAL): envia o fechamento ao escritório contábil.

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

import util
import widgets

#: A medida de layout que segue a fonte. `px(14)` são "os 14 px de quem
#: desenhou esta tela a 100%", ditos na escala de hoje — a 150% saem 21, e
#: a 100% saem os mesmos 14. Ver o bloco do `px` no `widgets.py`.
px = widgets.px

_fmt_dur = util.fmt_dur

#: Rótulo de TELA. A tabela que vira nome de pasta é a `util.MESES_PASTA`,
#: e quem guarda a forma de exibição é o `widgets`, par visual do `util`.
MESES = list(widgets.MESES)


def _sicoob():
    """O pacote do Sicoob, importado tarde.

    A árvore do fechamento (raiz, nome do mês, pasta da empresa) e o cadastro
    das empresas já moram lá; duplicar aqui seria criar um segundo mapa — e
    julho de 2026 já ficou partido uma vez por causa de dois mapas discordando.
    O import é tardio para esta aba montar mesmo se o pacote do Sicoob não
    estiver no caminho, como faz a aba Contratos."""
    from extratos_sicoob import sicoob_config as scfg
    from extratos_sicoob import sicoob_contas as contas
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
        # O PortalClient aberto pelo envio. Fica em `self` para que `fechar()`
        # consiga fechá-lo: dentro de um `with` local ele era invisível de
        # fora, e sair do app no meio de um envio deixava um Chrome órfão.
        self.portal = None
        # Último motivo de falha do `_drain`, para não repetir a mesma linha a
        # cada 150 ms (ver o `except` de lá).
        self._erro_drain = None
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
        PADX = px(widgets.PADX)

        self.cab = widgets.Cabecalho(
            self, "Acessorias",
            "Envia o fechamento do mês ao escritório contábil: uma solicitação "
            "por empresa, com o .zip anexado.",
            trilha="Mensal  ›  Acessorias")
        self.cab.pack(fill="x", padx=PADX, pady=px((16, 12)))
        # O verde é ENVIAR — é o irreversível desta tela. Preparar só lê a
        # pasta do mês e não toca no portal.
        self.b1 = widgets.Botao(self.cab.acoes, "Preparar o envio",
                                papel="passo", command=self.preparar)
        self.b1.pack(side="left", padx=px((0, 8)))
        self.b2 = widgets.Botao(self.cab.acoes, "Enviar ao escritório",
                                papel="acao", state="disabled",
                                command=self.enviar)
        self.b2.pack(side="left")

        # ---- card 1: mês e modelos
        f1 = widgets.Cartao(self, "Mês e mensagem", 1)
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

        ttk.Label(f1, text="ASSUNTO", style="Rotulo.TLabel"
                  ).pack(anchor="w", pady=px((12, 3)))
        ttk.Entry(f1, textvariable=self.v_assunto).pack(fill="x")
        ttk.Label(f1, text="COMENTÁRIO", style="Rotulo.TLabel"
                  ).pack(anchor="w", pady=px((10, 3)))
        self.t_modelo = tk.Text(f1, wrap="word", height=5, borderwidth=1,
                                relief="solid", highlightthickness=0)
        self.t_modelo.pack(fill="x")
        self.t_modelo.insert("1.0", pacote.MODELO_COMENTARIO)
        widgets.estilo_campo_texto(self.t_modelo)
        ttk.Label(f1, style="Tenue.TLabel", wraplength=px(820), justify="left",
                  text="Tokens: " + "  ".join(pacote.TOKENS) +
                       "   ·   a lista de contratos é lida de dentro do zip."
                  ).pack(anchor="w", pady=px((6, 0)))
        ttk.Label(f1, style="Tenue.TLabel",
                  text="Preparar só lê a pasta do mês — não toca no portal."
                  ).pack(anchor="w", pady=px((2, 0)))

        # ---- card 2: o que vai ser enviado
        f2 = widgets.Cartao(self, "O que vai ser enviado", 2)
        f2.pack(fill="both", expand=True, padx=PADX, pady=px((0, 12)))

        colunas = ("empresa", "zip", "tamanho", "contratos", "situacao")
        self.tree = ttk.Treeview(f2, columns=colunas, show="headings",
                                 height=7, selectmode="browse")
        for chave, titulo, largura in (("empresa", "EMPRESA", 170),
                                       ("zip", "ARQUIVO", 260),
                                       ("tamanho", "TAMANHO", 90),
                                       ("contratos", "CONTRATOS", 90),
                                       ("situacao", "SITUAÇÃO", 260)):
            self.tree.heading(chave, text=titulo)
            self.tree.column(chave, width=largura,
                             anchor="e" if chave in ("tamanho", "contratos")
                             else "w")
        widgets.estilo_tabela(self.tree)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._trocar_selecao)

        rodape = widgets.RodapeTabela(f2)
        rodape.pack(fill="x", pady=px((8, 8)))
        rodape.definir(texto="Clique numa empresa para ver e corrigir o texto "
                             "que vai ser enviado por ela.")
        self.rodape_envio = rodape
        self.t_previa = tk.Text(f2, wrap="word", height=7, borderwidth=1,
                                relief="solid", highlightthickness=0)
        self.t_previa.pack(fill="both", expand=True)
        widgets.estilo_campo_texto(self.t_previa)

        # ---- barra de execução, acima do registro
        # Para ONDE vai é o dado que o formulário do portal esconde: o
        # departamento é um select cujos valores não seguem a ordem da tela, e
        # errá-lo manda o fechamento para o lugar errado sem nenhum aviso.
        # Deixar isso à vista é mais barato que descobrir depois.
        aviso = ttk.Frame(self, style="Fundo.TFrame")
        aviso.pack(fill="x", padx=PADX, pady=px((0, 8)))
        ttk.Label(aviso, style="FundoTenue.TLabel", wraplength=px(900),
                  justify="left",
                  text=f"Vai para {cfg.DEPARTAMENTO}, prioridade "
                       f"{cfg.PRIORIDADE}. O login é feito por você, na janela "
                       f"do Chrome.").pack(anchor="w")

        acao = ttk.Frame(self, style="Fundo.TFrame")
        acao.pack(fill="x", padx=PADX, pady=px((0, 10)))
        btns = ttk.Frame(acao, style="Fundo.TFrame")
        btns.pack(side="right", padx=px((16, 0)))
        self.b_stop = widgets.Botao(btns, "⏹  Parar", papel="perigo",
                                    state="disabled", command=self._parar_click)
        self.b_stop.pack(side="left")
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
        except Exception as e:                              # noqa: BLE001
            # A bomba de UI NUNCA pode morrer, e por isso o reagendamento está
            # no `finally`. Um `tk.TclError` aqui (mexer num widget recém
            # destruído, por exemplo) parava o ciclo para sempre: o registro
            # congelava, os botões nunca voltavam e a thread do portal seguia
            # trabalhando — sem ninguém saber sequer se dava para fechar o app.
            # É o modelo do `_drain` do Anexar.
            #
            # O motivo vai para o próprio Registro, e não para o
            # `diagnostico.log`: esta aba não importa o `config` do Anexar, e
            # criar essa dependência só para registrar uma linha custaria mais
            # do que resolve. Só quando MUDA — repetido a cada 150 ms, ele
            # afogaria o que a pessoa precisa ler.
            motivo = repr(e)
            if motivo != self._erro_drain:
                self._erro_drain = motivo
                self.q.put(("log", f"[!] falha ao atualizar a tela: {motivo}"))
        finally:
            self.after(150, self._drain)

    def aplicar_cores(self, escuro: bool):
        # O registro é terminal (escuro nos dois temas); o modelo e a prévia
        # são CAMPOS que se digitam, e seguem a cor do cartão. Eram os três no
        # mesmo `estilo_log`, e no tema claro isso não aparecia.
        try:
            widgets.estilo_log(self.log, escuro)
        except tk.TclError:
            pass
        for campo in (self.t_modelo, self.t_previa):
            try:
                widgets.estilo_campo_texto(campo, escuro)
            except tk.TclError:
                pass
        try:
            widgets.estilo_tabela(self.tree)
        except tk.TclError:
            pass

    def ocupado(self) -> str | None:
        """O que esta aba está fazendo agora, ou None.

        O navegador daqui é OUTRO (o portal é outro site e outro login), então
        a barra lateral pergunta a esta aba separadamente — o registro de dono
        do AnexarFrame não sabe nada do que acontece aqui."""
        fut = self.worker
        if fut is not None and not fut.done():
            return self._tarefa_atual or "Acessorias"
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
        """(ano, mês) escolhidos. SÓ pode ser chamado na thread da interface.

        Ler `StringVar` é falar com o Tcl, e o Tcl é de quem criou a janela:
        chamado de dentro do worker, isto trava ou devolve erro sem hora
        marcada — a falha que nunca aparece em teste."""
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
        # TUDO que vem do formulário é lido AQUI, na thread da interface, e vai
        # por argumento: mês e ano inclusive. O assunto e o comentário já
        # seguiam essa regra; o período escapava por estar dentro de um método.
        ano, mes = self._periodo()
        modelo_assunto = self.v_assunto.get()
        modelo_comentario = self.t_modelo.get("1.0", "end-1c")
        self.worker = self.exec.submit(self._t_preparar, ano, mes,
                                       modelo_assunto, modelo_comentario)

    def _t_preparar(self, ano: int, mes: int, modelo_assunto: str,
                    modelo_comentario: str):
        try:
            if not self._garantir_mapa():
                return
            scfg, _ = _sicoob()
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
                "Acessorias",
                "Não dá para enviar enquanto isto não for resolvido:\n\n"
                + "\n".join(f"• {t}" for t in travas[:8]))
            return

        pendentes = [e for e in self.envios if e.pronta]
        if not pendentes:
            messagebox.showinfo("Acessorias", "Não há empresa pronta para "
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
            # O cliente fica em `self` ANTES de qualquer trabalho: era um `with`
            # local, e um navegador que só a própria thread enxerga não pode ser
            # fechado por quem está saindo do app — a janela sumia e o Chrome
            # ficava aberto, segurando o perfil. O `try/finally` faz o mesmo que
            # o `with` fazia; o que muda é que agora `fechar()` alcança o
            # cliente. Ver `AnexarFrame.fechar`, que resolve isto do mesmo jeito.
            cli = PortalClient(self.mapa.vip_url, log=self._log).__enter__()
            self.portal = cli
            try:
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
            finally:
                # Fecha na thread que abriu (exigência do Playwright síncrono)
                # e só então solta a referência — trocar a ordem deixaria
                # `fechar()` sem nada para fechar e o Chrome de pé.
                try:
                    cli.__exit__(None, None, None)
                finally:
                    self.portal = None

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
        """Fecha o Chrome do portal e devolve a thread (chamar ao sair do app).

        Seguro de chamar SEMPRE, inclusive quando nada foi aberto: sem cliente
        e sem trabalho, isto só marca o Event e desliga o executor.

        Duas coisas que o `shutdown(wait=False)` sozinho não resolvia:

        1. **as threads do ThreadPoolExecutor não são daemon.** Enquanto uma
           delas estiver viva o processo não morre — fechar a janela durante um
           envio fazia o app sumir da tela e continuar existindo, invisível, no
           Gerenciador de Tarefas, segurando o perfil do Chrome. Marcar o
           `_parar` é o que faz a thread terminar (o lote para depois da
           empresa atual) em vez de ficar até o fim do lote;
        2. **o navegador ficava aberto.** O `PortalClient` só pode ser fechado
           pela thread que o criou, então o `__exit__` é SUBMETIDO ao próprio
           executor e esperado com prazo curto — é o que `AnexarFrame.fechar`
           já faz. Se o worker ainda estiver no meio de um upload, o pedido
           espera na fila e o prazo vence: aí o `cancel_futures` o descarta e
           quem fecha o Chrome é o `finally` do próprio `_t_enviar`.
        """
        self._parar.set()
        cli = self.portal
        if cli is not None:
            try:
                self.exec.submit(cli.__exit__, None, None, None).result(timeout=8)
                self.portal = None
            except Exception:
                # Estamos saindo: navegador que não fecha limpo não muda nada
                # do que fazer aqui, e levantar impediria as outras abas de
                # fechar (o `_sair` do app percorre todas).
                pass
        try:
            self.exec.shutdown(wait=False, cancel_futures=True)
        except TypeError:                    # Python < 3.9
            self.exec.shutdown(wait=False)
        except Exception:
            pass
