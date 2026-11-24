# -*- coding: utf-8 -*-
"""A aba PF da tela "Pagamentos do dia" (dono, 12/11/2026).

A tela abre com duas abas no alto, PJ e PF. A PJ é a de sempre. A PF lista
TODAS as contas PESSOA FISICA e MOURA DANTAS (`html_pf.contas_da_aba`), o dono
marca quais entram, escolhe o período e a caixa dos reembolsos dos sócios, e
"Ler e gerar o HTML" lê o ERP pelo Chrome do app — a MESMA leitura do Buscar
(`leitura_do_dia.ler_pagamentos`, só com `contas_escolhidas`) — e grava
`pagamentos_pf_<de>_a_<até>.html` (`html_pf.gravar`).

Só leitura no ERP, como a aba inteira. A regra mora em `html_pf` (pura, com
teste); aqui é a tela: a thread do navegador (`anx.submeter`, dona = a tela),
a fila e o Registro da tela PJ, que é o mesmo das duas abas.

As contas lidas ficam em `contas_pf.json` ao lado do exe (nome, id, saldo e
as marcadas da última vez): a lista aparece ao abrir, sem ir ao ERP.
"""
from __future__ import annotations

import datetime
from decimal import Decimal
import json
import os
import queue
import subprocess
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import util
import widgets
from widgets import px
from conciliacao.config import load_config
from conciliacao.errors import ErpError
from erp import sessao as erp_sessao
from pagamentos_dia import baixa_pelo_arquivo as bpa
from pagamentos_dia import html_pf, leitura_do_dia, reembolso
from pagamentos_dia import regras_pagamento as regras_pag
from pagamentos_dia.pagamentos_frame import _carregar_mapas, _historico

from . import decisoes as dc
from . import erp_do_dia

ARQ_CONTAS = "contas_pf.json"
#: O recuo do "Em aberto até hoje" desta aba (a PJ lembra o dela).
CHAVE_DIAS = "dias_em_aberto_pf"


def ler_cache(base) -> dict:
    try:
        dados = json.loads((base / ARQ_CONTAS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"contas": [], "escolhidas": None}
    if not isinstance(dados, dict):
        return {"contas": [], "escolhidas": None}
    contas = [c for c in dados.get("contas") or [] if isinstance(c, dict) and c.get("nome")]
    esc = dados.get("escolhidas")
    return {"contas": contas, "escolhidas": list(esc) if isinstance(esc, list) else None}


def gravar_cache(base, contas, escolhidas) -> None:
    try:
        (base / ARQ_CONTAS).write_text(json.dumps(
            {"contas": contas, "escolhidas": list(escolhidas)}, ensure_ascii=False, indent=1),
            encoding="utf-8")
    except OSError:
        pass


def marcadas_depois(nomes_da_aba, conhecidas, marcadas) -> list[str]:
    """Quais contas ficam marcadas depois de uma leitura nova da lista.

    As que o dono já via seguem como ele deixou (`marcadas`, dentre as
    `conhecidas`); conta que NÃO estava na lista é nova e nasce marcada; a que
    sumiu do ERP sai. Sem lista conhecida (primeira vez), todas marcadas."""
    conhecidas, marcadas = set(conhecidas or ()), set(marcadas or ())
    return [n for n in nomes_da_aba if n in marcadas or n not in conhecidas]


def contas_do_erp(contas_erp) -> list[dict]:
    """[{id, nome, saldo}] de TODAS as contas ativas (o "já paguei" escolhe
    entre elas), na forma do cache."""
    saida = []
    for c in contas_erp or ():
        saldo = getattr(c, "balance", None)
        saida.append({"id": getattr(c, "id", ""), "nome": (getattr(c, "name", "") or "").strip(),
                      "saldo": float(saldo) if saldo is not None else None})
    return [c for c in saida if c["nome"]]


class AbaPF:
    def __init__(self, area, tela):
        self.tela = tela
        self.q = queue.Queue()
        self.vars: dict[str, tk.BooleanVar] = {}
        self.ultimo = None
        base = util.pasta_base()
        self._cache = ler_cache(base)
        PADX = tela._padx
        hoje = datetime.date.today()
        ini, fim = dc.textos_sugeridos(hoje)
        self.v_ini, self.v_fim = tk.StringVar(value=ini), tk.StringVar(value=fim)

        c1 = widgets.Cartao(area, "Contas PF e Moura Dantas", 1)
        c1.pack(fill="x", padx=PADX, pady=px((0, 12)))
        tela._ajuda(c1, "Marque as contas que entram. A lista vem do ERP (todas as contas "
                        "PESSOA FISICA e MOURA DANTAS) pelo «Buscar contas», e também "
                        "pelo Buscar da aba PJ; conta nova chega marcada. O app lembra "
                        "a sua última escolha.")
        self.caixa_contas = ttk.Frame(c1)
        self.caixa_contas.pack(fill="x", pady=px((6, 0)))
        linha = ttk.Frame(c1)
        linha.pack(fill="x", pady=px((8, 0)))
        # Dono, 13/11/2026: "sem sentido ter que clicar em ler e gerar pra ele
        # ler as contas". Lê só a lista (segundos); o Buscar das PJ também a
        # traz (`receber_contas`, chamado pelo frame).
        self.b_contas = widgets.Botao(linha, "Buscar contas", papel="passo",
                                      command=self.buscar_contas)
        self.b_contas.pack(side="left", padx=px((0, 8)))
        widgets.Botao(linha, "Marcar todas", papel="neutro",
                      command=lambda: self._marcar_todas(True)).pack(side="left")
        widgets.Botao(linha, "Desmarcar todas", papel="neutro",
                      command=lambda: self._marcar_todas(False)).pack(side="left", padx=px((8, 0)))

        c2 = widgets.Cartao(area, "Período e reembolsos", 2)
        c2.pack(fill="x", padx=PADX, pady=px((0, 12)))
        datas = ttk.Frame(c2)
        datas.pack(fill="x", pady=px((0, 8)))
        widgets.Campo(datas, "De", lambda p: widgets.CampoData(p, self.v_ini)
                      ).pack(side="left", padx=px((0, 16)))
        widgets.Campo(datas, "Até", lambda p: widgets.CampoData(p, self.v_fim)
                      ).pack(side="left", padx=px((0, 16)))
        widgets.Botao(datas, "Em aberto até hoje", papel="neutro",
                      command=self._datas_em_aberto).pack(side="left", pady=px((15, 0)))
        self.pessoas = regras_pag.carregar_confirmar()
        self.var_reembolso = tk.BooleanVar(value=True)
        if self.pessoas:
            ttk.Checkbutton(c2, variable=self.var_reembolso,
                            text="Reembolso para " + " e ".join(self.pessoas)).pack(anchor="w")
            tela._ajuda(c2, "Os reembolsos deles vão sempre no HTML: esta caixa só diz "
                            "como ele abre. Lá no topo há um botão que os põe na lista "
                            "ou na parte recolhida, sem gerar de novo.")
        self.regras = html_pf.carregar_regras()
        fora = self.regras.cc_fora + self.regras.favorecidos_fora
        tela._ajuda(c2, ("Saem direto (regras_pf.json): " + ", ".join(fora)) if fora else
                    "Nenhuma regra de saída direta: crie o regras_pf.json ao lado do app.")

        c3 = widgets.Cartao(area, "Gerar", 3)
        c3.pack(fill="x", padx=PADX, pady=px((0, 12)))
        linha3 = ttk.Frame(c3)
        linha3.pack(fill="x")
        self.b_gerar = widgets.Botao(linha3, "Ler e gerar o HTML", papel="acao",
                                     command=self.gerar)
        self.b_gerar.pack(side="left")
        self.b_abrir = widgets.Botao(linha3, "Abrir o último HTML", papel="neutro",
                                     state="disabled", command=self._abrir_ultimo)
        self.b_abrir.pack(side="left", padx=px((8, 0)))
        tela._ajuda(c3, "Lê os lançamentos das contas marcadas, os anexos e o cadastro, "
                        "com as mesmas regras das PJ (sem anexo, só com reembolso, "
                        "boleto em imagem). O HTML tem código de barras, QR Pix com a "
                        "descrição e o «já paguei», que gera a lista para a baixa.")

        # Etapa 3 da spec de 12/11/2026: o JSON do «Baixar lista das baixas»
        # volta ao app, que confere cada título no ERP e só então baixa.
        c4 = widgets.Cartao(area, "Dar baixa pelo arquivo", 4)
        c4.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.b_baixa = widgets.Botao(c4, "Escolher o arquivo de baixas…", papel="acao",
                                     command=self.escolher_baixas)
        self.b_baixa.pack(anchor="w")
        tela._ajuda(c4, "Escolha o baixas_pf_<data>.json que o HTML salvou. O app relê "
                        "cada título no ERP e mostra a conferência: em aberto, valor "
                        "igual, conta existe e não baixado antes. Vermelho não é "
                        "baixado. O app guarda o que já baixou: o mesmo arquivo "
                        "carregado de novo não baixa duas vezes.")
        self._mostrar_contas()
        area.after(200, self._drain)

    # ------------------------------------------------------------- contas
    def _escolhidas(self) -> list[str]:
        return [n for n, v in self.vars.items() if v.get()]

    def _mostrar_contas(self):
        antes = {n: v.get() for n, v in self.vars.items()}
        for w in self.caixa_contas.winfo_children():
            w.destroy()
        self.vars = {}
        nomes = html_pf.contas_da_aba(c["nome"] for c in self._cache["contas"])
        escolhidas = self._cache["escolhidas"]
        if not nomes:
            ttk.Label(self.caixa_contas, style="Secao.TLabel",
                      text="Nenhuma conta ainda — clique em «Buscar contas» (ou no "
                           "Buscar da aba PJ): elas vêm todas marcadas.").pack(anchor="w")
            return
        for i, nome in enumerate(nomes):
            marcada = antes.get(nome, True if escolhidas is None else nome in escolhidas)
            v = tk.BooleanVar(value=marcada)
            self.vars[nome] = v
            ttk.Checkbutton(self.caixa_contas, variable=v, text=nome).grid(
                row=i // 2, column=i % 2, sticky="w", padx=px((0, 24)), pady=px((0, 2)))

    def _marcar_todas(self, valor: bool):
        for v in self.vars.values():
            v.set(valor)

    def receber_contas(self, contas_erp):
        """Na thread da interface: a lista nova de contas do ERP (do «Buscar
        contas», do Buscar das PJ ou da geração), mantendo as marcas."""
        contas = contas_do_erp(contas_erp)
        if not contas:
            return
        nomes = html_pf.contas_da_aba(c["nome"] for c in contas)
        if self.vars:
            conhecidas, marcadas = list(self.vars), self._escolhidas()
        else:
            conhecidas = html_pf.contas_da_aba(c["nome"] for c in self._cache["contas"])
            esc = self._cache["escolhidas"]
            marcadas = conhecidas if esc is None else esc
        escolhidas = marcadas_depois(nomes, conhecidas, marcadas)
        gravar_cache(util.pasta_base(), contas, escolhidas)
        self._cache = {"contas": contas, "escolhidas": escolhidas}
        self.vars = {}
        self._mostrar_contas()

    def buscar_contas(self):
        tela = self.tela
        if tela.worker and not tela.worker.done():
            return
        if tela.anx.avisar_se_ocupado("a lista de contas das PF", aba=tela):
            return
        self.b_contas.configure(state="disabled")
        tela.q.put(("ocupado", True))
        tela.q.put(("status", "PF: lendo as contas do ERP..."))
        tela.worker = tela.anx.submeter("Pagamentos do dia — contas das PF", self._t_contas,
                                        dona=tela)

    def _t_contas(self):
        tela, log = self.tela, self.tela._log
        try:
            base = util.pasta_base()
            cfg = load_config(base / "config.yaml")
            api = tela.anx.garantir_sessao(log)
            contas = erp_do_dia.ler_saldos(cfg, api, log=log)
            self.q.put(("contas_lidas", contas))
            n = len(html_pf.contas_da_aba(c.name for c in contas))
            log(f"PF: {n} conta(s) PF e Moura Dantas no ERP.")
            tela.q.put(("status", "PF: contas lidas."))
        except Exception as e:                                # noqa: BLE001
            log("\n" + widgets.recado_de_erro(e, "Não consegui ler as contas do ERP."))
            log(dc.detalhe_do_erro(e))
            tela.q.put(("status", "PF: não consegui ler as contas — veja o Registro."))
        finally:
            tela.q.put(("ocupado", False))
            self.q.put(("fim_contas", None))

    def _datas_em_aberto(self):
        """De N dias atrás até hoje; N é o recuo da última geração (ou 7)."""
        ini, fim = dc.textos_em_aberto(
            datetime.date.today(), dc.ler_dias_em_aberto(util.pasta_base(), CHAVE_DIAS))
        self.v_ini.set(ini)
        self.v_fim.set(fim)

    # ------------------------------------------------------------- gerar
    def gerar(self):
        tela = self.tela
        if tela.worker and not tela.worker.done():
            return
        if tela.anx.avisar_se_ocupado("o HTML das PF", aba=tela):
            return
        try:
            periodo = dc.periodo_da_busca(self.v_ini.get(), self.v_fim.get(), ("", ""),
                                          datetime.date.today())
        except ValueError as e:
            messagebox.showinfo("HTML das PF", str(e))
            return
        primeira = not self.vars
        escolhidas = self._escolhidas()
        if not primeira and not escolhidas:
            messagebox.showinfo("HTML das PF", "Marque ao menos uma conta.")
            return
        dias = dc.dias_a_lembrar(periodo, datetime.date.today())
        if dias:
            dc.gravar_dias_em_aberto(util.pasta_base(), dias, CHAVE_DIAS)
        tela._parar.clear()
        self.b_gerar.configure(state="disabled")
        tela.q.put(("ocupado", True))
        tela.q.put(("status", f"PF: lendo {periodo.descrever()}..."))
        tela.worker = tela.anx.submeter("Pagamentos do dia — HTML das PF", self._t_gerar,
                                        periodo, None if primeira else escolhidas,
                                        self.var_reembolso.get(), dona=tela)

    def _t_gerar(self, periodo, escolhidas, reembolso_ligado):
        """Na thread do navegador. `escolhidas` None = a primeira vez: todas."""
        tela, log = self.tela, self.tela._log
        comeco = time.time()
        try:
            base = util.pasta_base()
            cfg = load_config(base / "config.yaml")
            api = tela.anx.garantir_sessao(log)
            tela.q.put(("status", "PF: lendo as contas do ERP..."))
            # A lista de contas que falha não impede o HTML quando já há uma
            # guardada (19/11/2026); na primeira vez (todas), a falha sobe.
            contas, guardadas = dc.contas_ou_as_guardadas(
                lambda: contas_do_erp(erp_do_dia.ler_saldos(cfg, api, log=log)),
                ler_cache(base)["contas"] if escolhidas is not None else [],
                erros=(ErpError,), log=log)
            da_aba = html_pf.contas_da_aba(c["nome"] for c in contas)
            if escolhidas is None:
                escolhidas = da_aba
            sumiram = [n for n in escolhidas if n not in da_aba]
            escolhidas = [n for n in escolhidas if n in da_aba]
            # Com a lista guardada, só a ESCOLHA de hoje é gravada: as contas
            # (e o saldo delas) continuam as da última leitura boa.
            gravar_cache(base, ler_cache(base)["contas"] if guardadas else contas,
                         escolhidas)
            self.q.put(("contas", (contas, escolhidas)))
            for n in sumiram:
                log(f"[!] PF: a conta «{n}» não está mais ativa no ERP — ficou de fora.")
            if not escolhidas:
                log("[!] PF: nenhuma conta PF ou Moura Dantas marcada — nada lido.")
                return
            tela.q.put(("status", "PF: lendo os lançamentos e os anexos..."))
            leitura = leitura_do_dia.ler_pagamentos(
                api, periodo.inicio, periodo.fim,
                abrir_historico=lambda: _historico(log), carregar_mapas=_carregar_mapas,
                cadastro_reembolso=reembolso.carregar(base),
                regras_fornecedor=regras_pag.carregar_fornecedores(),
                destacar=regras_pag.carregar_confirmar(), log=log,
                progresso=lambda f, t: tela.q.put(("status", f"PF: lendo... {f}/{t}")),
                cancelar=tela._parar.is_set, contas_escolhidas=escolhidas)
            if leitura.interrompida:
                log("\nPF: leitura interrompida — nenhum HTML gerado.")
                tela.q.put(("status", "PF: leitura interrompida."))
                return
            for aviso in leitura.avisos:
                log(f"  ! {aviso}")
            tempos = leitura_do_dia.resumo_dos_tempos(leitura.tempos)
            if tempos:
                log(f"  Tempo da leitura: {tempos}")
            pasta = base / "Pagamentos do dia"
            gerado = html_pf.gravar(
                leitura.resultado, leitura.lancamentos, pasta, periodo.inicio, periodo.fim,
                regras_pf=html_pf.carregar_regras(base), pessoas=self.pessoas,
                reembolso_ligado=reembolso_ligado, contas_pagadoras=contas,
                contas_lidas=escolhidas)
            log(f"\nPF: {gerado.entram} pagamento(s), R$ {gerado.total:,.2f}".replace(",", "X")
                .replace(".", ",").replace("X", ".")
                + f" · {gerado.fora} fora · {gerado.reembolsos} reembolso(s) dos sócios "
                + ("na lista" if reembolso_ligado else "recolhido(s)")
                + " (botão no topo do HTML troca)")
            log(f"  HTML: {str(gerado.caminho).replace(os.sep, '/')}")
            self.q.put(("gerado", gerado.caminho))
            total = time.time() - comeco
            tela.q.put(("status", f"PF: HTML pronto em {util.fmt_dur(total)}."))
            log(f"  PF: HTML pronto em {util.fmt_dur(total)}.")
            util.log("tela_do_dia").info("HTML das PF em %d s (%s): %s", total,
                                         periodo.descrever(), tempos)
            widgets.registrar_atividade(
                "dia", "HTML das PF", "ok", periodo.descrever(),
                {"segundos": int(total), "pagamentos": gerado.entram,
                 "etapas": {k: int(v) for k, v in leitura.tempos.items()}})
        except Exception as e:                                # noqa: BLE001
            log("\n" + widgets.recado_de_erro(e, "Não consegui gerar o HTML das PF."))
            log(dc.detalhe_do_erro(e))
            util.log("tela_do_dia").exception("HTML das PF")
            widgets.registrar_atividade("dia", "HTML das PF", "erro", type(e).__name__,
                                        {"segundos": int(time.time() - comeco)})
            tela.q.put(("status", "PF: não consegui gerar — veja o Registro."))
        finally:
            tela.q.put(("ocupado", False))
            self.q.put(("fim", None))

    # ------------------------------------------------------------- baixa
    def escolher_baixas(self):
        tela = self.tela
        if tela.worker and not tela.worker.done():
            return
        caminho = filedialog.askopenfilename(
            title="Arquivo de baixas do HTML das PF",
            filetypes=[("Arquivo de baixas", "baixas_pf_*.json"), ("JSON", "*.json")])
        if not caminho:
            return
        try:
            with open(caminho, encoding="utf-8") as f:
                itens = bpa.ler_arquivo(f.read())
            registro = bpa.Registro(util.pasta_base() / bpa.ARQ_REGISTRO)
        except (OSError, ValueError) as e:
            messagebox.showerror("Dar baixa pelo arquivo", str(e))
            return
        if not erp_sessao.central_ligado():
            messagebox.showinfo("Dar baixa pelo arquivo",
                                "A baixa pelo arquivo fala com o ERP pelo Chrome central "
                                "(porteiro), que não está ligado nesta máquina.")
            return
        if tela.anx.avisar_se_ocupado("a baixa pelo arquivo", aba=tela):
            return
        self.b_baixa.configure(state="disabled")
        tela.q.put(("ocupado", True))
        tela.q.put(("status", f"PF: conferindo {len(itens)} baixa(s) no ERP..."))
        nome = os.path.basename(caminho)
        tela._log(f"\nPF: conferindo {nome} ({len(itens)} item(ns)) no ERP...")
        tela.worker = tela.anx.submeter("Pagamentos do dia — conferir baixas", self._t_conferir,
                                        itens, registro, nome, dona=tela)

    @staticmethod
    def _sessao_central():
        """(pedir, contas cruas) pelo Chrome central — nunca login HTTP."""
        cfg = load_config(util.pasta_base() / "config.yaml")
        # O mesmo caminho dos saldos: `Sessao.logar("", "")` = porteiro; com o
        # central desligado ele LEVANTA em vez de cair no login HTTP.
        api = erp_do_dia._logar_pela_pagina(cfg)
        interna = api._sessao
        from erp.sessao_pagina import SessaoPelaPagina
        if not isinstance(interna, SessaoPelaPagina):
            raise ErpError("o porteiro não devolveu a sessão pela página.")
        contas = api.listar_contas(ativas=True)
        if not contas:
            raise ErpError("o ERP não devolveu nenhuma conta bancária.")

        def pedir(url, metodo="GET", corpo=None):
            return interna.pedir(url, metodo=metodo, corpo=corpo)
        return pedir, contas

    def _t_conferir(self, itens, registro, nome):
        tela, log = self.tela, self.tela._log
        try:
            pedir, contas = self._sessao_central()
            conferidos = bpa.conferir(pedir, itens, contas, registro,
                                      hoje=datetime.date.today(), log=log)
            aptos = [c for c in conferidos if c.apto]
            log(f"PF: {len(aptos)} de {len(conferidos)} passam na conferência.")
            for c in conferidos:
                if not c.apto:
                    log(f"  ✖ {c.item.fornecedor[:30]} — {c.motivo}")
            self.q.put(("conferido", (conferidos, contas, registro, nome)))
            tela.q.put(("status", "PF: conferência pronta — confira e confirme."))
        except Exception as e:                                # noqa: BLE001
            log("\n" + widgets.recado_de_erro(e, "Não consegui conferir as baixas no ERP."))
            log(dc.detalhe_do_erro(e))
            util.log("tela_do_dia").exception("conferir baixas PF")
            tela.q.put(("status", "PF: não consegui conferir — veja o Registro."))
            self.q.put(("fim_baixa", None))
        finally:
            tela.q.put(("ocupado", False))

    def _janela_conferencia(self, conferidos, contas, registro, nome):
        tela = self.tela
        aptos = [c for c in conferidos if c.apto]
        total = sum((c.item.valor for c in aptos), start=Decimal("0"))
        jan = tk.Toplevel(self.caixa_contas.winfo_toplevel())
        jan.title(f"Dar baixa pelo arquivo — {nome}")
        jan.transient(self.caixa_contas.winfo_toplevel())
        ttk.Label(jan, text=(f"{len(aptos)} de {len(conferidos)} prontos para baixar · "
                             f"{bpa._dinheiro(total)}. Vermelho não é baixado."),
                  style="Secao.TLabel").pack(anchor="w", padx=px(12), pady=px((12, 6)))
        cols = ("fornecedor", "valor", "conta", "data", "situacao")
        caixa = ttk.Frame(jan)
        caixa.pack(fill="both", expand=True, padx=px(12))
        t = ttk.Treeview(caixa, columns=cols, show="headings",
                         height=min(max(len(conferidos), 4), 18))
        for col, titulo, larg, anc in (("fornecedor", "FAVORECIDO", 220, "w"),
                                       ("valor", "VALOR", 90, "e"),
                                       ("conta", "CONTA", 170, "w"),
                                       ("data", "PAGO EM", 80, "center"),
                                       ("situacao", "SITUAÇÃO", 300, "w")):
            t.heading(col, text=titulo)
            t.column(col, width=larg, minwidth=larg, anchor=anc, stretch=(col == "situacao"))
        barra = ttk.Scrollbar(caixa, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=barra.set)
        barra.pack(side="right", fill="y")
        t.pack(side="left", fill="both", expand=True)
        widgets.estilo_tabela(t, zebra=False, ordenavel=False)
        for i, c in enumerate(conferidos):
            it = c.item
            situacao = (f"{widgets.MARCAS_ESTADO['ok']} pronto para baixar" if c.apto
                        else f"{widgets.MARCAS_ESTADO['erro']} {c.motivo}")
            t.insert("", "end", iid=str(i), tags=("ok" if c.apto else "erro",), values=(
                it.fornecedor, bpa._dinheiro(it.valor) if it.valor is not None else it.valor_cru,
                it.conta, it.data.strftime("%d/%m/%Y") if it.data else it.data_cru, situacao))
        rodape = ttk.Frame(jan)
        rodape.pack(fill="x", padx=px(12), pady=px(12))

        def fechar():
            jan.destroy()
            self.b_baixa.configure(state="normal")

        def baixar():
            if not messagebox.askyesno(
                    "Dar baixa pelo arquivo",
                    f"Dar baixa de {len(aptos)} pagamento(s), {bpa._dinheiro(total)}, no "
                    "Mais Controle?\n\nCada título é relido logo antes da baixa, e a "
                    "baixa não é repetida.", default="no", parent=jan):
                return
            if tela.anx.avisar_se_ocupado("a baixa pelo arquivo", aba=tela):
                return
            jan.destroy()
            tela._parar.clear()
            tela.q.put(("ocupado", True))
            tela.q.put(("status", f"PF: baixando {len(aptos)} pagamento(s)..."))
            tela._log(f"\nPF: baixando {len(aptos)} pagamento(s) de {nome}...")
            tela.worker = tela.anx.submeter("Pagamentos do dia — dar baixa", self._t_baixar,
                                            conferidos, registro, dona=tela)

        b = widgets.Botao(rodape, f"Baixar os {len(aptos)} pronto(s)", papel="acao",
                          command=baixar)
        b.pack(side="left")
        if not aptos:
            b.configure(state="disabled")
        widgets.Botao(rodape, "Cancelar", papel="neutro", command=fechar).pack(
            side="left", padx=px((8, 0)))
        jan.protocol("WM_DELETE_WINDOW", fechar)

    def _t_baixar(self, conferidos, registro):
        tela, log = self.tela, self.tela._log
        try:
            # Sessão e contas de novo: a conferência pode ter sido há minutos.
            pedir, contas = self._sessao_central()
            rodada = bpa.baixar(pedir, conferidos, contas, registro, log=log,
                                agora=lambda: datetime.datetime.now().isoformat(timespec="seconds"),
                                cancelar=tela._parar.is_set)
            total = sum((r.item.valor for r in rodada.resultados if r.ok),
                        start=Decimal("0"))
            falhas = [r for r in rodada.resultados if not r.ok]
            log(f"PF: {rodada.ok} baixa(s) feita(s), {bpa._dinheiro(total)}"
                + (f" · {len(falhas)} não baixada(s)" if falhas else ""))
            for r in falhas:
                log(f"  ✖ {r.item.fornecedor[:30]} — {r.recado}")
            if rodada.parou:
                log("[!] PF: parei numa baixa sem resposta — confira esse título no ERP "
                    "antes de carregar o arquivo de novo.")
            self.q.put(("baixado", (rodada.ok, total, len(falhas), rodada.parou)))
            tela.q.put(("status", f"PF: {rodada.ok} baixa(s) feita(s)."))
        except Exception as e:                                # noqa: BLE001
            log("\n" + widgets.recado_de_erro(e, "Não consegui dar as baixas."))
            log(dc.detalhe_do_erro(e))
            util.log("tela_do_dia").exception("baixas PF")
            tela.q.put(("status", "PF: as baixas pararam — veja o Registro."))
        finally:
            tela.q.put(("ocupado", False))
            self.q.put(("fim_baixa", None))

    # ------------------------------------------------------------- tela
    def _drain(self):
        try:
            while True:
                tipo, valor = self.q.get_nowait()
                if tipo == "contas":
                    contas, escolhidas = valor
                    self._cache = {"contas": contas, "escolhidas": escolhidas}
                    self.vars = {}
                    self._mostrar_contas()
                elif tipo == "gerado":
                    self.ultimo = valor
                    self.b_abrir.configure(state="normal")
                    self._abrir(valor)
                elif tipo == "fim":
                    self.b_gerar.configure(state="normal")
                elif tipo == "contas_lidas":
                    self.receber_contas(valor)
                elif tipo == "fim_contas":
                    self.b_contas.configure(state="normal")
                elif tipo == "conferido":
                    self._janela_conferencia(*valor)
                elif tipo == "baixado":
                    ok, total, falhas, parou = valor
                    texto = f"{ok} baixa(s) feita(s), {bpa._dinheiro(total)}."
                    if falhas:
                        texto += f"\n{falhas} não baixada(s) — o motivo está no Registro."
                    if parou:
                        texto += ("\n\nParei numa baixa sem resposta: confira esse título "
                                  "no ERP antes de carregar o arquivo de novo.")
                    (messagebox.showwarning if (falhas or parou) else messagebox.showinfo)(
                        "Dar baixa pelo arquivo", texto)
                elif tipo == "fim_baixa":
                    self.b_baixa.configure(state="normal")
        except queue.Empty:
            pass
        except Exception as e:                                # noqa: BLE001
            self.tela._log(f"[!] PF: falha ao atualizar a tela: {e!r}")
        finally:
            try:
                self.caixa_contas.after(200, self._drain)
            except tk.TclError:
                pass

    def _abrir_ultimo(self):
        if self.ultimo:
            self._abrir(self.ultimo)

    @staticmethod
    def _abrir(caminho):
        try:
            os.startfile(caminho)                             # noqa: S606 (Windows)
        except Exception:                                     # noqa: BLE001
            subprocess.Popen(["explorer", str(caminho)])
