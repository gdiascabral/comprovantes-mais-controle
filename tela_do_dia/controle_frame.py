# -*- coding: utf-8 -*-
"""A aba "Controle de aportes" — tela FINA.

Toda regra mora em `controle_aportes` (a conta e o que a tela mostra e manda),
`controle_erp` (a leitura do Mais Controle, só GET, pelo Chrome do app) e
`controle_nuvem` (abertura, proporção e apontamentos). Aqui: ler na thread do
navegador (`submeter`, `dona=self`), mostrar na thread do Tk (fila + `after`)
e mandar para a nuvem — numa thread própria — o que o dono editar, com tudo o
que vem da tela lido ANTES. **Nada desta aba escreve no Mais Controle.**

Falha fechada: a leitura que cai (ERP, nuvem, rede do Playwright — qualquer
exceção) apaga a tela e diz que não leu; nunca deixa os números de antes nem
vira "em dia".
"""
from __future__ import annotations

import datetime
import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import util
import widgets
from aportes import dados as cadastro_aportes
from conciliacao.config import load_config
from nuvem import sessao

from . import controle_aportes as ca
from . import controle_erp, controle_nuvem, erp_do_dia
from .frame import TelaDoDiaFrame
from .valores import brl

px = widgets.px
_ajuda = TelaDoDiaFrame._ajuda
_rodape = TelaDoDiaFrame._rodape
TITULO = "Controle de aportes"
SEM_LEITURA = ("Não li o controle de aportes — nenhum número é mostrado. Veja o Registro e "
               "atualize de novo.")


class ControleAportesFrame(ttk.Frame):
    COLS_CONTAS = (("parte", "PARTE", 70, "e"), ("aportou", "APORTOU", 125, "e"),
                   ("deveria", "DEVERIA", 125, "e"), ("dif", "PARA IGUALAR", 125, "e"),
                   ("situacao", "SITUAÇÃO", 220, "w"))
    COLS_SEM_DONO = (("data", "DATA", 85, "w"), ("conta", "CONTA", 170, "w"),
                     ("cliente", "CLIENTE NO ERP", 190, "w"), ("valor", "VALOR", 110, "e"),
                     ("motivo", "MOTIVO", 280, "w"))
    COLS_APONTADOS = (("data", "DATA", 85, "w"), ("conta", "CONTA", 170, "w"),
                      ("valor", "VALOR", 110, "e"), ("para", "APONTADO PARA", 190, "w"),
                      ("motivo", "MOTIVO", 280, "w"))
    LARGURA_CONTA = 220
    LINHAS_FORM = 6

    def __init__(self, master, anexar_frame):
        super().__init__(master)
        self.anx = anexar_frame
        self.q = queue.Queue()
        self.worker = None
        self._erro_drain = None
        self.pode_editar = False      # o app liga para admin; a RLS nega o resto
        self._nuvem_ocupada = False
        self._lendo = False           # leitura rodando na thread do navegador
        self._leu_bem = False         # a tela tem uma leitura INTEIRA à vista
        self._reler = False           # gravou durante uma leitura: reler no fim
        self.contas, self.apontamentos, self.contas_erp, self.apuracoes = [], {}, [], []
        self._linha_conta, self._linha_sem_dono, self._linha_apontado = {}, {}, {}
        self._build()
        self.after(150, self._drain)

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = px(widgets.PADX)
        cab = widgets.Cabecalho(
            self, TITULO,
            "Quanto cada um aportou em cada conta desde a abertura, quanto deveria pela "
            "proporção e quem deve quanto para igualar. Lê o Mais Controle; não escreve "
            "nada nele.", trilha="Diário  ›  Controle de aportes")
        cab.pack(fill="x", padx=PADX, pady=px((16, 12)))
        self.b1 = widgets.Botao(cab.acoes, "Atualizar", papel="acao", command=self.atualizar)
        self.b1.pack(side="left")
        corpo = widgets.AreaRolavel(self)

        c1 = widgets.Cartao(corpo, "Por conta", 1)
        c1.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.lbl_resumo = _ajuda(c1, "", estilo="Atencao.TLabel")
        _ajuda(c1, "Aportou = o já aportado antes da abertura mais os recebimentos de aporte "
                   "do Mais Controle desde a abertura. Deveria = o que cada um precisa ter "
                   "posto, pela proporção, para igualar quem mais pôs. Para igualar = a "
                   "diferença.")
        self.t_contas = self._tabela(c1, self.COLS_CONTAS, arvore=True, altura=12)
        linha = ttk.Frame(c1)
        linha.pack(fill="x", pady=px((8, 0)))
        self.b_nova = widgets.Botao(linha, "+ Conta no controle…", papel="neutro",
                                    state="disabled", command=lambda: self._editar_conta(None))
        self.b_editar = widgets.Botao(linha, "Editar a conta selecionada…", papel="neutro",
                                      state="disabled", command=self._editar_selecionada)
        for i, b in enumerate((self.b_nova, self.b_editar)):
            b.pack(side="left", padx=px((0 if i == 0 else 8, 0)))

        c2 = widgets.Cartao(corpo, "Sem dono", 2)
        c2.pack(fill="x", padx=PADX, pady=px((0, 12)))
        _ajuda(c2, "Recebimentos de aporte cujo Cliente no Mais Controle não é aportador da "
                   "conta (nome completo, letra por letra). Ficam FORA da conta até o "
                   "administrador apontar de quem são — ou que não são aporte desta conta.")
        self.t_sem_dono = self._tabela(c2, self.COLS_SEM_DONO, arvore=False, altura=8)
        self.b_apontar = widgets.Botao(c2, "Apontar o selecionado…", papel="neutro",
                                       state="disabled", command=self._apontar)
        self.b_apontar.pack(anchor="w", pady=px((8, 0)))

        c3 = widgets.Cartao(corpo, "Apontados por você", 3)
        c3.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.t_apontados = self._tabela(c3, self.COLS_APONTADOS, arvore=False, altura=6)
        self.b_desfazer = widgets.Botao(c3, "Desfazer o selecionado", papel="link",
                                        state="disabled", command=self._desfazer)
        self.b_desfazer.pack(anchor="w", pady=px((8, 0)))

        acao = ttk.Frame(self, style="Fundo.TFrame")
        acao.pack(fill="x", padx=PADX, pady=px((0, 10)))
        self.barra_exec = widgets.BarraExecucao(acao)
        self.barra_exec.pack(side="left", fill="x", expand=True)
        self.lbl, self.pb = self.barra_exec.lbl, self.barra_exec.pb
        self.reg = widgets.Cartao(self, "Registro", padding=(12, 10))
        self.reg.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.log = tk.Text(self.reg, wrap="word", relief="flat", borderwidth=0,
                           highlightthickness=0)
        self.log.pack(fill="both", expand=True)
        widgets.estilo_log(self.log)
        widgets.registro_elastico(self.reg, self.log)
        corpo.encaixar(acao, self.reg)

    @property
    def _botoes_do_dono(self):
        return (self.b_nova, self.b_editar, self.b_apontar, self.b_desfazer)

    def liberar_edicao(self, sim: bool):
        """O app liga para admin. Esconder não protege: quem nega é a RLS."""
        self.pode_editar = bool(sim)
        self._acender_botoes()

    def _acender_botoes(self):
        estado = ca.estado_dos_botoes_do_dono(self.pode_editar, self._lendo, self._leu_bem)
        for b in self._botoes_do_dono:
            b.configure(state=estado)

    def _tabela(self, pai, colunas, *, arvore: bool, altura: int):
        grade = ttk.Frame(pai)
        grade.pack(fill="both", expand=True, pady=px((8, 0)))
        t = ttk.Treeview(grade, columns=[c[0] for c in colunas],
                         show="tree headings" if arvore else "headings", height=altura)
        if arvore:
            t.heading("#0", text="CONTA / APORTADOR", anchor="w")
            t.column("#0", width=px(self.LARGURA_CONTA), anchor="w", stretch=True)
        for chave, titulo, largura, ancora in colunas:
            t.heading(chave, text=titulo, anchor=ancora)
            # Sem `px`: o `estilo_tabela` escala as colunas de dados (como na
            # tela do dia); só o texto (âncora "w") estica.
            t.column(chave, width=largura, anchor=ancora, stretch=ancora == "w")
        widgets.estilo_tabela(t, ordenavel=False)
        # A barra ANTES da tabela (ver `TelaDoDiaFrame._tabela`).
        ttk.Scrollbar(grade, orient="vertical", command=t.yview).pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        return t

    def aplicar_cores(self, escuro: bool):
        try:
            widgets.estilo_log(self.log, escuro)
            for t in (self.t_contas, self.t_sem_dono, self.t_apontados):
                widgets.estilo_tabela(t, ordenavel=False)
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
                elif tipo == "ocupado":
                    (self.pb.start(12) if valor else self.pb.stop())
                elif tipo == "botoes":
                    self.b1.configure(state=valor)
                elif tipo == "fim":
                    self._fim_da_leitura()
                elif tipo == "leitura":
                    self._receber(valor)
                elif tipo == "falha":
                    self._limpar(SEM_LEITURA)
                elif tipo == "nuvem":
                    self._depois_da_nuvem(*valor)
        except queue.Empty:
            pass
        except Exception as e:                              # noqa: BLE001
            # A bomba de UI nunca morre (ver o `_drain` da tela do dia).
            motivo = repr(e)
            if motivo != self._erro_drain:
                self._erro_drain = motivo
                self.q.put(("log", f"[!] falha ao atualizar a tela: {motivo}"))
        finally:
            self.after(150, self._drain)

    # --------------------------------------------------------------- leitura
    def atualizar(self) -> bool:
        """True se a leitura começou."""
        if self.worker and not self.worker.done():
            return False
        # Recusar ANTES de apagar os botões (ver "Um navegador, seis abas").
        if self.anx.avisar_se_ocupado("o Controle de aportes", aba=self):
            return False
        # Os números de antes saem da tela ANTES da leitura nova: leitura que
        # cai no meio não pode deixar a conta de ontem à vista.
        self._limpar("Lendo...")
        self._lendo = True
        self._acender_botoes()
        self.q.put(("botoes", "disabled"))
        self.q.put(("ocupado", True))
        self.q.put(("status", "Lendo o controle na nuvem e os aportes no Mais Controle..."))
        try:
            self.worker = self.anx.submeter("Controle de aportes — ler", self._t_ler,
                                            datetime.date.today(), dona=self)
        except Exception as e:                              # noqa: BLE001
            # Sem isto, `_lendo` ficava ligado para sempre e a aba presa: o
            # `fim` só vem da própria leitura, que nunca começou.
            self._lendo = False
            self._limpar(SEM_LEITURA)
            self._acender_botoes()
            self.q.put(("ocupado", False))
            self.q.put(("botoes", "normal"))
            self.q.put(("status", "Não consegui começar a leitura — veja o Registro."))
            self._log("\n" + widgets.recado_de_erro(e, "Não consegui começar a leitura."))
            return False
        return True

    def _fim_da_leitura(self):
        """Na thread do Tk, depois da última mensagem da leitura."""
        self._lendo = False
        self._acender_botoes()
        if self._reler:
            self._reler = False
            # Não já: o `fim` sai da fila antes de o `worker.done()` virar
            # True, e o `atualizar` recusaria por "navegador ocupado" a
            # releitura que mais importa. Espera a leitura terminar, com teto
            # (`controle_aportes.reler_ou_esperar`).
            self._reler_quando_livre(0)

    def _reler_quando_livre(self, tentativas: int):
        terminou = not (self.worker and not self.worker.done())
        if ca.reler_ou_esperar(terminou, tentativas) == "esperar":
            self.after(50, self._reler_quando_livre, tentativas + 1)
            return
        self._reler_depois_de_gravar()

    def _limpar(self, recado: str):
        self._leu_bem = False
        self.apuracoes = []
        self._linha_conta, self._linha_sem_dono, self._linha_apontado = {}, {}, {}
        for t in (self.t_contas, self.t_sem_dono, self.t_apontados):
            t.delete(*t.get_children())
        self.lbl_resumo.configure(text=recado)

    def _t_ler(self, hoje):
        """Na thread do navegador: nada de widget aqui, só a fila."""
        try:
            contas, apontamentos = controle_nuvem.ler(sessao.token())
            ativas = [c for c in contas if c.ativa]
            cfg = load_config(util.pasta_base() / "config.yaml")
            api = self.anx.garantir_sessao(self._log)
            # As contas do ERP são lidas mesmo sem conta no controle: é delas
            # que o formulário "+ Conta no controle…" oferece o nome.
            contas_erp = erp_do_dia.ler_saldos(cfg, api, log=self._log)
            if not ativas:
                self._log("Nenhuma conta no controle ainda. O dono acrescenta em "
                          "\"+ Conta no controle…\".")
                self.q.put(("leitura", (contas, apontamentos, contas_erp, [])))
                self.q.put(("status", ca.status_da_leitura([])))
                return
            pares, erros = ca.pares_para_ler(ativas, contas_erp)
            # Contraprova SEMPRE (uma conta fora do controle): é ela que prova
            # que o filtro de conta do ERP vale.
            crus = (controle_erp.ler_recebimentos(
                api, pares, hoje, contraprova=ca.conta_de_contraprova(contas_erp, pares),
                log=self._log) if pares else {})
            apuracoes = ca.apurar_tudo(ativas, erros, crus, apontamentos, hoje)
            self.q.put(("leitura", (contas, apontamentos, contas_erp, apuracoes)))
            self.q.put(("status", ca.status_da_leitura(apuracoes)))
        except Exception as e:                              # noqa: BLE001
            # Genérica de propósito: a rede do Playwright cai sem ErpError, e
            # qualquer falha aqui vira "não li" — nunca "em dia".
            self.q.put(("falha", None))
            self._log("\n" + widgets.recado_de_erro(e, "Não consegui ler o controle de aportes."))
            self.q.put(("status", "Não consegui ler — veja o Registro."))
        finally:
            self.q.put(("ocupado", False))
            self.q.put(("botoes", "normal"))
            self.q.put(("fim", None))

    def _receber(self, pacote):
        if self._reler:
            # Esta leitura pode ter começado antes da gravação: não mostra
            # nada dela; a releitura vem no `_fim_da_leitura`.
            return
        try:
            self._mostrar(pacote)
        except Exception as e:                              # noqa: BLE001
            # Tabela pela metade é pior que nenhuma: apaga tudo e diz que não leu.
            self._limpar(SEM_LEITURA)
            self._log("\n" + widgets.recado_de_erro(
                e, "Não consegui mostrar o controle de aportes."))
            self.lbl.configure(text="Não consegui mostrar — veja o Registro.")
        self._acender_botoes()

    def _mostrar(self, pacote):
        self.contas, self.apontamentos, self.contas_erp, apuracoes = pacote
        self._limpar("")
        self.apuracoes = apuracoes
        subcontas = cadastro_aportes.carregar_subcontas()      # cache local, sem rede
        resumo = []
        for ap in self.apuracoes:
            pai = self.t_contas.insert("", "end", text=ap.conta.conta_erp, open=True,
                                       values=ca.valores_da_conta(ap))
            self._linha_conta[pai] = ap.conta
            for l in ap.linhas:
                filho = self.t_contas.insert(pai, "end", text=l.nome,
                                             values=ca.valores_do_aportador(l))
                self._linha_conta[filho] = ap.conta
            resumo += ca.resumo(ap, pode_apontar=self.pode_editar)
            aviso = ca.divergencia_do_rateio(ap.conta, subcontas)
            if aviso:
                resumo.append(f"{ap.conta.conta_erp}: {aviso}")
            for alerta in ap.alertas:
                self._log(f"[!] {ap.conta.conta_erp}: {alerta}")
            for s in ap.sem_dono:
                r = s.recebimento
                iid = self.t_sem_dono.insert("", "end", values=(
                    f"{r.data:%d/%m/%Y}", ap.conta.conta_erp, r.cliente or "—",
                    brl(r.valor), s.motivo))
                self._linha_sem_dono[iid] = (ap.conta, r)
            for r, p, nome in ap.apontados:
                iid = self.t_apontados.insert("", "end", values=(
                    f"{r.data:%d/%m/%Y}", ap.conta.conta_erp, brl(r.valor),
                    nome or ca.NAO_E_APORTE, p.motivo))
                self._linha_apontado[iid] = p
        if not self.apuracoes:
            resumo.append("Nenhuma conta no controle.")
        self.lbl_resumo.configure(text="\n".join(resumo))
        self._leu_bem = True

    # ----------------------------------------------------------------- nuvem
    def _na_nuvem(self, feito: str, trabalho):
        """`trabalho` roda numa thread própria e NÃO toca em Tk: tudo o que
        vem da tela é lido antes."""
        if self._nuvem_ocupada:
            messagebox.showinfo(TITULO, "Ainda gravando a mudança anterior na nuvem — "
                                        "espere um instante.", parent=self)
            return
        self._nuvem_ocupada = True
        self.q.put(("status", "Gravando na nuvem..."))

        def rodar():
            try:
                trabalho()
                self.q.put(("nuvem", (feito, "")))
            except Exception as e:                          # noqa: BLE001
                self.q.put(("nuvem", (feito, widgets.recado_de_erro(
                    e, "Não consegui gravar na nuvem."))))
        threading.Thread(target=rodar, daemon=True).start()

    def _depois_da_nuvem(self, feito: str, erro: str):
        self._nuvem_ocupada = False
        if erro:
            self._log("\n" + erro)
            self.q.put(("status", "Não gravou — veja o Registro."))
        else:
            self._log(f"{feito}. Atualizando os números...")
        # O que vale é o que a nuvem tem: relê, nunca muda a tabela na mão —
        # e os números de antes da gravação saem da tela já. COM ERRO também:
        # a gravação pode ter parado no meio (`controle_aportes.depois_da_nuvem`).
        recado, quando = ca.depois_da_nuvem(bool(erro), self._lendo)
        self._limpar(recado)
        self._acender_botoes()
        if quando == "reler_no_fim":
            self._reler = True
            return
        self._reler_depois_de_gravar()

    def _reler_depois_de_gravar(self):
        if not self.atualizar():         # navegador ocupado por outra aba
            self._limpar("A nuvem mudou (ou pode ter mudado). O navegador está ocupado: "
                         "clique Atualizar quando ele liberar — nenhum número é mostrado "
                         "até lá.")
            self._acender_botoes()

    # -------------------------------------------------------------- diálogos
    def _janela(self, titulo):
        jan = tk.Toplevel(self.winfo_toplevel())
        jan.title(titulo)
        jan.transient(self.winfo_toplevel())
        widgets.barra_de_titulo(jan)
        corpo = ttk.Frame(jan, padding=px(14))
        corpo.pack(fill="both", expand=True)
        return jan, corpo

    def _editar_selecionada(self):
        sel = self.t_contas.selection()
        conta = self._linha_conta.get(sel[0]) if sel else None
        if conta is None:
            messagebox.showinfo(TITULO, "Escolha uma conta na tabela.", parent=self)
            return
        self._editar_conta(conta)

    def _editar_conta(self, conta):
        if not self.pode_editar:
            return
        # Lido AGORA, na thread do Tk: é o que o formulário carrega e o que
        # `gravar_conta` confere contra o banco.
        vistos = ca.vistos_do_formulario(conta)
        jan, corpo = self._janela("Conta no controle de aportes")
        ttk.Label(corpo, wraplength=px(560), justify="left", text=(
            "O nome da conta e o de cada aportador têm de ser os do Mais Controle, letra "
            "por letra — o aportador é o Cliente dos recebimentos de aporte dele. Nome "
            "pela metade não casa com ninguém.")).pack(anchor="w")
        v_conta = tk.StringVar(value=conta.conta_erp if conta else "")
        v_abre = tk.StringVar(value=f"{conta.abertura:%d/%m/%Y}" if conta else "")
        widgets.Campo(corpo, "Conta no Mais Controle", lambda p: ttk.Combobox(
            p, textvariable=v_conta, width=52,
            values=sorted((c.name for c in self.contas_erp), key=util.norm_espaco))
        ).pack(anchor="w", pady=px((10, 0)))
        widgets.Campo(corpo, ca.ROTULO_ABERTURA, lambda p: ttk.Entry(
            p, textvariable=v_abre, width=14)).pack(anchor="w", pady=px((10, 0)))
        grade = ttk.Frame(corpo)
        grade.pack(anchor="w", pady=px((10, 0)))
        for col, txt in enumerate(("Aportador (nome completo, como no Contato do ERP)",
                                   "Parte", "Já aportado antes da abertura (R$)")):
            ttk.Label(grade, text=txt, style="Tenue.TLabel").grid(
                row=0, column=col, sticky="w", padx=px((0, 8)))
        conhecidos = ca.nomes_conhecidos(
            cadastro_aportes.carregar_contas(), cadastro_aportes.carregar_subcontas(),
            [s.recebimento for ap in self.apuracoes for s in ap.sem_dono])
        linhas = []

        def nova_linha(nome="", parte="", ja=""):
            i = len(linhas)
            vs = (tk.StringVar(value=nome), tk.StringVar(value=parte), tk.StringVar(value=ja))
            ttk.Combobox(grade, textvariable=vs[0], width=46, values=conhecidos).grid(
                row=i + 1, column=0, sticky="w", padx=px((0, 8)), pady=px(2))
            ttk.Entry(grade, textvariable=vs[1], width=8).grid(
                row=i + 1, column=1, sticky="w", padx=px((0, 8)))
            ttk.Entry(grade, textvariable=vs[2], width=16).grid(row=i + 1, column=2, sticky="w")
            linhas.append(vs)

        atuais = list(conta.aportadores) if conta else []
        for a in atuais:
            nova_linha(a.nome_erp, format(a.peso.normalize(), "f"),
                       ca.texto_de_dinheiro(a.abertura))
        while len(linhas) < max(self.LINHAS_FORM, len(atuais) + 2):
            nova_linha()

        def digitadas():
            return [tuple(v.get() for v in vs) for vs in linhas]

        def por_nas_linhas(novas):
            while len(linhas) < len(novas):
                nova_linha()
            for vs, valores in zip(linhas, novas):
                for v, x in zip(vs, valores):
                    v.set(x)

        def trazer():
            vindos = ca.do_rateio_da_subconta(v_conta.get(),
                                              cadastro_aportes.carregar_subcontas())
            if not vindos:
                messagebox.showinfo(TITULO, "Esta conta não é uma subconta de investidor com "
                                            "rateio cadastrado na aba Aportes.", parent=jan)
                return
            novas, descartados = ca.linhas_do_rateio(digitadas(), vindos)
            por_nas_linhas(novas)
            if descartados:
                messagebox.showwarning(TITULO, "Saíram, porque não estão no rateio, e tinham "
                                               "já aportado digitado: " + ", ".join(descartados)
                                       + ". Confira antes de gravar.", parent=jan)

        v_dev, v_divida = tk.StringVar(), tk.StringVar()

        def preencher():
            try:
                rascunho = ca.conta_do_formulario(v_conta.get() or "-", v_abre.get(), digitadas())
                aberturas = ca.aberturas_para_divida(rascunho.aportadores, v_dev.get(),
                                                     ca.ler_abertura(v_divida.get()))
            except ValueError as e:
                messagebox.showwarning(TITULO, str(e), parent=jan)
                return
            por_nas_linhas(ca.aberturas_nas_linhas(digitadas(), aberturas))

        ajuda = ttk.Frame(corpo)
        ajuda.pack(anchor="w", pady=px((10, 0)))
        widgets.Botao(ajuda, "Trazer do rateio da subconta", papel="neutro",
                      command=trazer).pack(side="left")
        ttk.Label(ajuda, text="   Quem deve:").pack(side="left")
        ttk.Combobox(ajuda, textvariable=v_dev, width=30, values=conhecidos).pack(side="left")
        ttk.Label(ajuda, text=" R$ ").pack(side="left")
        ttk.Entry(ajuda, textvariable=v_divida, width=14).pack(side="left")
        widgets.Botao(ajuda, "Preencher o já aportado", papel="neutro",
                      command=preencher).pack(side="left", padx=px((8, 0)))

        def aplicar(_e=None):
            hoje = datetime.date.today()
            try:
                nova = ca.conta_do_formulario(v_conta.get(), v_abre.get(), digitadas(),
                                              id=conta.id if conta else None,
                                              ativa=conta.ativa if conta else True)
            except ValueError as e:
                messagebox.showwarning(TITULO, str(e), parent=jan)
                return "break"
            outras = list(self.contas)
            erros = ca.problemas_da_conta(nova, hoje, outras)
            if erros:
                messagebox.showwarning(TITULO, "\n".join(erros), parent=jan)
                return "break"
            if not messagebox.askyesno(TITULO, ca.descrever_conta(nova)
                                       + "\n\nGravar na nuvem?", parent=jan):
                return "break"
            jan.destroy()
            self._na_nuvem("Conta gravada", lambda: controle_nuvem.gravar_conta(
                sessao.token(), nova, hoje, outras, vistos=vistos, aberta=conta))
            return "break"

        _rodape(jan, corpo, (("Cancelar", "neutro", jan.destroy),
                             ("Gravar", "acao", aplicar)), aplicar)

    def _apontar(self):
        if not self.pode_editar:
            return
        sel = self.t_sem_dono.selection()
        if not sel or sel[0] not in self._linha_sem_dono:
            messagebox.showinfo(TITULO, "Escolha um recebimento na lista Sem dono.", parent=self)
            return
        conta, rec = self._linha_sem_dono[sel[0]]
        opcoes = ca.opcoes_de_apontamento(conta)
        jan, corpo = self._janela("Apontar recebimento")
        ttk.Label(corpo, wraplength=px(520), justify="left", text=(
            f"{rec.data:%d/%m/%Y} · {brl(rec.valor)} · {conta.conta_erp}\n"
            f"Cliente no Mais Controle: {rec.cliente or '—'}\n{rec.descricao}")).pack(anchor="w")
        v_quem, v_motivo = tk.StringVar(), tk.StringVar()
        widgets.Campo(corpo, "De quem é este aporte", lambda p: ttk.Combobox(
            p, textvariable=v_quem, state="readonly", width=52,
            values=[o[0] for o in opcoes])).pack(anchor="w", pady=px((10, 0)))
        widgets.Campo(corpo, "Motivo (obrigatório)", lambda p: ttk.Entry(
            p, textvariable=v_motivo, width=52)).pack(anchor="w", pady=px((10, 0)))

        def aplicar(_e=None):
            try:
                aportador_id, motivo = ca.escolha_do_apontamento(opcoes, v_quem.get(),
                                                                 v_motivo.get())
            except ValueError as e:
                messagebox.showwarning(TITULO, str(e), parent=jan)
                return "break"
            jan.destroy()
            # A conta INTEIRA: `apontar` confere o aportador contra ela.
            self._na_nuvem("Recebimento apontado", lambda: controle_nuvem.apontar(
                sessao.token(), conta, rec, aportador_id, motivo))
            return "break"

        _rodape(jan, corpo, (("Cancelar", "neutro", jan.destroy),
                             ("Apontar", "acao", aplicar)), aplicar)

    def _desfazer(self):
        if not self.pode_editar:
            return
        sel = self.t_apontados.selection()
        if not sel or sel[0] not in self._linha_apontado:
            messagebox.showinfo(TITULO, "Escolha um apontamento na lista.", parent=self)
            return
        p = self._linha_apontado[sel[0]]
        if not messagebox.askyesno(TITULO, "Desfazer o apontamento? O recebimento volta "
                                           "para Sem dono.", parent=self):
            return
        ident = p.id
        self._na_nuvem("Apontamento desfeito",
                       lambda: controle_nuvem.desfazer(sessao.token(), ident))
