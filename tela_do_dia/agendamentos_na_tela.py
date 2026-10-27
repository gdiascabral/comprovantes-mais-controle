# -*- coding: utf-8 -*-
"""O "Conferir agendamentos" na aba "Pagamentos do dia" (dono, 23/10/2026:
"já acrescente o de verificar os agendamentos no pagamentos do dia").

Confronta as transações pendentes de assinatura no Sicoob com o HTML do dia
DESTA tela — o mesmo que o «HTML dos pagamentos» do passo 4 grava em
`<pasta base>/Pagamentos do dia/pagamentos_<período>.html`. Sem esse arquivo,
não escolhe outro: diz para gerar o HTML do dia primeiro (`SEM_HTML`). O
motor é o MESMO da Remessa/Retorno (`pagamentos_dia.conferir_agendamentos`:
separar as contas, ler o banco, a janela do resumão com a marca
"Conferido"); aqui mora só a tela. SÓ LEITURA no banco: nada é assinado,
cancelado nem alterado.

**Thread própria, nunca a do ERP**, como o "Reler Sicoob"
(`sicoob_na_tela.LeitorSicoob`): o `SicoobClient` nasce e morre dentro do
motor, na `Thread` daemon `sicoob-agendamentos-dia`, e a tela só recebe pela
fila. **Um perfil do banco, uma sessão**: recusa começar com o saldo do
Sicoob desta tela, os Extratos, o Baixar comprovantes ou o "Conferir
agendamentos" da Remessa rodando (`outros_no_sicoob`, ligado no
`comprovantes_app.py`), e todos eles recusam enquanto esta roda (`ocupado`,
`OCUPADO`).

**Outro acesso do Sicoob**: conta que este login não enxerga faz a tela
perguntar (pela fila; a thread espera, e fechar o app responde não) se entra
com o outro acesso (QR Code) — o mesmo Chrome do app abre de novo e lê só
as que faltaram (`conferir_agendamentos.ler_no_banco(perguntar=)`).
"""
from __future__ import annotations

import datetime
import queue
import threading
from pathlib import Path
from tkinter import messagebox

import widgets
from pagamentos_dia import agendamentos_sicoob as A
from pagamentos_dia import conferir_agendamentos as ca
from pagamentos_dia import html_pagamentos

from . import decisoes as dc

TITULO = ca.TITULO
#: O que as outras abas mostram quando recusam por causa desta conferência.
OCUPADO = "Pagamentos do dia — conferindo agendamentos"
SEM_HTML = ("Gere o HTML do dia primeiro (passo 4, «HTML dos pagamentos»): a "
            "conferência confronta o que está agendado no Sicoob com o HTML "
            "do dia que esta tela gera, e ele ainda não existe para este "
            "período.")


def _hoje() -> datetime.date:
    """Separado para o teste fixar o dia."""
    return datetime.date.today()


def _carregar_mapas():
    """Os cadastros de contas, pelo MESMO caminho da Remessa (função à parte
    para o teste trocar o disco por um dublê)."""
    from pagamentos_dia import pagamentos_frame
    return pagamentos_frame._carregar_mapas()


def html_do_dia(pasta, ini, fim) -> Path | None:
    """O HTML geral que esta tela grava para o período, se existir. O de
    pessoa física não serve (não é pago pelo SicoobNet)."""
    if pasta is None:
        return None
    p = Path(pasta) / f"pagamentos_{html_pagamentos.rotulo_periodo(ini, fim)}.html"
    return p if p.is_file() else None


def periodo_do_html(tela, hoje):
    """O período do HTML do dia: o da leitura que está na tela (é com ele que
    o «HTML dos pagamentos» grava); sem leitura (app recém-aberto), o dos
    campos DE/ATÉ, pela mesma regra do Buscar. Data inválida levanta
    `ValueError` com o recado."""
    leitura = getattr(tela, "leitura", None)
    if leitura is not None:
        ini, fim = leitura.periodo
        return ini, fim
    p = dc.periodo_da_busca(tela.v_ini.get(), tela.v_fim.get(), tela._sugerido, hoje)
    return p.inicio, p.fim


def pergunta_outro_acesso(nomes) -> str:
    lista = ", ".join(nomes[:6]) + ("…" if len(nomes) > 6 else "")
    return (f"{len(nomes)} conta(s) não aparecem neste login do Sicoob ({lista}). "
            "Devem ser de outro acesso.\n\nEntrar com o outro acesso agora? O "
            "Chrome do Sicoob fecha e abre de novo: entre com o outro acesso "
            "(QR Code).")


class ConferenciaNaTela:
    def __init__(self, pai, tela):
        self.tela = tela
        self.q = queue.Queue()
        self._thread = None
        self._parar = threading.Event()
        #: Ligado pelo app: quem mais está com o Chrome do Sicoob.
        self.outros_no_sicoob = lambda: None
        self.b_conferir = widgets.Botao(pai, "🔎  Conferir agendamentos", papel="neutro",
                                        command=self.conferir)
        self.b_conferir.after(200, self._drain)

    def ocupado(self) -> str | None:
        t = self._thread
        return OCUPADO if t is not None and t.is_alive() else None

    # ------------------------------------------------------------- ação
    def conferir(self):
        if self.ocupado():
            messagebox.showinfo(TITULO, "A conferência anterior ainda está rodando.")
            return
        quem = self.outros_no_sicoob()
        if quem:
            messagebox.showinfo(TITULO, ca.recado_em_uso(quem))
            return
        try:
            ini, fim = periodo_do_html(self.tela, _hoje())
        except ValueError as e:
            messagebox.showinfo(TITULO, str(e))
            return
        caminho = html_do_dia(self.tela._pasta_pagamentos(), ini, fim)
        if caminho is None:
            messagebox.showinfo(TITULO, SEM_HTML)
            return
        try:
            contas = A.ler_html(caminho.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            messagebox.showwarning(TITULO, widgets.recado_de_erro(
                e, "Não consegui ler o HTML do dia."))
            return
        try:
            mapa_mc, empresas = _carregar_mapas()
        except Exception as e:                               # noqa: BLE001
            messagebox.showwarning(TITULO, widgets.recado_de_erro(
                e, "Não consegui ler o cadastro de contas."))
            return
        sep = ca.separar(contas, mapa_mc, empresas)
        recusa = sep.recusa()
        if recusa:
            ca.mostrar_recusa(recusa)
            return
        inicio, fim_consulta = A.periodo_da_consulta(_hoje())
        try:
            gerado = datetime.datetime.fromtimestamp(caminho.stat().st_mtime)
            quando = f" (gerado às {gerado:%H:%M} de {gerado:%d/%m})"
        except OSError:
            quando = ""
        if not messagebox.askokcancel(
                TITULO, f"HTML do dia: {caminho.name}{quando}.\n\n"
                        + ca.pergunta_de_abrir(len(sep.no_sicoob), inicio, fim_consulta)):
            return
        # De novo depois da pergunta: com ela aberta, o saldo (o fim do Buscar)
        # pode ter aberto o Chrome do Sicoob no MESMO perfil.
        quem = self.outros_no_sicoob()
        if quem:
            messagebox.showinfo(TITULO, ca.recado_em_uso(quem))
            return
        log = self.tela._log
        log("")
        log(f"Conferir agendamentos: {caminho.name}")
        for c, _n, motivo in sep.fora:
            log(f"  fora da conferência: {c.get('nome')} — {motivo}")
        self._parar.clear()
        self.b_conferir.configure(state="disabled")
        self._thread = threading.Thread(
            target=self._t_conferir, name="sicoob-agendamentos-dia", daemon=True,
            args=(caminho, sep.no_sicoob, sep.fora, inicio, fim_consulta))
        self._thread.start()

    def _t_conferir(self, caminho, no_sicoob, fora, inicio, fim):
        """Thread do Sicoob. Só fala com a tela pela fila; sempre termina com "fim"."""
        try:
            confrontos = ca.ler_no_banco(no_sicoob, fora, inicio, fim, log=self.tela._log,
                                         perguntar=self._perguntar_outro_acesso,
                                         parar=self._parar.is_set)
            self.q.put(("pronto", (caminho, confrontos)))
        except Exception as e:                               # noqa: BLE001
            self.q.put(("falhou", f"[!] Conferir agendamentos: {e!r}"))
        finally:
            self.q.put(("fim", None))

    def _perguntar_outro_acesso(self, nomes) -> bool:
        """Chamado da thread do Sicoob: a pergunta vai pela fila (Tk só na
        thread da tela) e a thread espera. Fechar o app (`fechar`) responde
        "não"."""
        caixa = {"ev": threading.Event(), "sim": False}
        self.q.put(("perguntar", (pergunta_outro_acesso(nomes), caixa)))
        while not caixa["ev"].wait(0.2):
            if self._parar.is_set():
                return False
        return bool(caixa["sim"]) and not self._parar.is_set()

    # ------------------------------------------------------------- tela
    def _drain(self):
        try:
            while True:
                tipo, valor = self.q.get_nowait()
                if tipo == "perguntar":
                    texto, caixa = valor
                    try:
                        caixa["sim"] = bool(messagebox.askyesno(
                            TITULO, texto, default=messagebox.YES))
                    finally:
                        caixa["ev"].set()
                elif tipo == "pronto":
                    ca.abrir_janela(self.b_conferir.winfo_toplevel(), *valor)
                elif tipo == "falhou":
                    self.tela._log(valor)
                elif tipo == "fim":
                    self.b_conferir.configure(state="normal")
        except queue.Empty:
            pass
        except Exception as e:                               # noqa: BLE001
            self.tela._log(f"[!] falha ao mostrar a conferência dos agendamentos: {e!r}")
        finally:
            self.b_conferir.after(200, self._drain)

    def fechar(self):
        self._parar.set()
