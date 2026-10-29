# -*- coding: utf-8 -*-
"""O botão "🔎 Autenticar no banco" do cartão "Agendados a confirmar" (dono,
29/10/2026: a ordem do dia começa conferindo no banco o que foi pago antes).

Lê o Sicoob das contas que têm agendado pendente (`autenticar_sicoob`, só
listas) e casa cada pendente com o que o banco mostra (`autenticar`). A
prova só PRÉ-MARCA: a tela refaz a situação (`nuvem_do_dia.com_provas_do_banco`)
e o dono continua respondendo "Pago", que pergunta.

Precisa do Buscar antes: é ele que relê os títulos no ERP (sem releitura,
`agendados.situacao` não pré-marca nada, nem com prova do banco — é o lado
seguro de "sumiu"/"mudou").

**Thread própria, nunca a do ERP** (`sicoob-autenticar`); **um perfil do
banco, uma sessão**: recusa com qualquer outro uso do Chrome do Sicoob
(`outros_no_sicoob`, ligado no `comprovantes_app.py`), e todos recusam
enquanto ele roda (`ocupado`, `autenticar_sicoob.OCUPADO`).

Inter: ainda não lido aqui (próxima etapa da spec: o QR por conta no
Autenticar, com o saldo reaproveitado pela Prova de saldos). Agendado do
Inter fica como estava, sem nota.
"""
from __future__ import annotations

import datetime
import queue
import threading
from tkinter import messagebox

import widgets
from pagamentos_dia import agendamentos_sicoob as A

from . import autenticar as au
from . import autenticar_sicoob as asi

TITULO = "Autenticar no banco"


def _hoje() -> datetime.date:
    return datetime.date.today()


def _carregar_mapas():
    from pagamentos_dia import pagamentos_frame
    return pagamentos_frame._carregar_mapas()


def pergunta_de_abrir(n_contas: int, inicio, fim) -> str:
    return (f"Vou abrir o Chrome do Sicoob e ler {n_contas} conta(s), de "
            f"{inicio:%d/%m} a {fim:%d/%m}: só as listas de pagamentos, Pix e "
            "pendências de assinatura. Nada é assinado nem baixado.\n\n"
            "Entre no SicoobNet quando o Chrome abrir. Continuar?")


def resumo(autenticacoes: dict) -> str:
    provados = sum(1 for a in autenticacoes.values() if a.prova)
    return (f"Autenticar no banco: {provados} de {len(autenticacoes)} agendado(s) do "
            "Sicoob provados pelo banco (pré-marcados ☑ — confira e clique em Pago).")


class AutenticarNaTela:
    def __init__(self, pai, tela):
        self.tela = tela
        self.q = queue.Queue()
        self._thread = None
        self._parar = threading.Event()
        #: Ligado pelo app: quem mais está com o Chrome do Sicoob.
        self.outros_no_sicoob = lambda: None
        self.b = widgets.Botao(pai, "🔎  Autenticar no banco", papel="passo",
                               command=self.autenticar)
        self.b.after(200, self._drain)

    def ocupado(self) -> str | None:
        t = self._thread
        return asi.OCUPADO if t is not None and t.is_alive() else None

    def autenticar(self):
        tela = self.tela
        if self.ocupado():
            messagebox.showinfo(TITULO, "A leitura anterior ainda está rodando.")
            return
        lido = getattr(tela, "lido", None)
        if lido is None or getattr(tela, "leitura", None) is None:
            messagebox.showinfo(TITULO, "Clique em Buscar primeiro: é ele que relê os "
                                        "títulos no ERP, e sem isso o banco não prova nada.")
            return
        pendentes = [a for a, _s, _r in lido.pendentes]
        if not pendentes:
            messagebox.showinfo(TITULO, "Não há agendado esperando resposta.")
            return
        quem = self.outros_no_sicoob()
        if quem:
            messagebox.showinfo(TITULO, f"O Chrome do Sicoob está em uso: {quem}. "
                                        "Espere terminar.")
            return
        try:
            mapa_mc, empresas = _carregar_mapas()
        except Exception as e:                               # noqa: BLE001
            messagebox.showwarning(TITULO, widgets.recado_de_erro(
                e, "Não consegui ler o cadastro de contas."))
            return
        contas, falhas = asi.contas_a_ler(
            pendentes, lambda c: A.conta_sicoob(c, mapa_mc, empresas))
        periodo = asi.periodo(pendentes, _hoje())
        if not contas:
            self._aplicar(au.autenticar(pendentes, [], falhas=falhas, hoje=_hoje()))
            messagebox.showinfo(TITULO, "Nenhum agendado pendente é de conta do Sicoob "
                                        "que dê para ler (veja o Registro).")
            return
        inicio, fim = periodo
        if not messagebox.askokcancel(TITULO, pergunta_de_abrir(len(contas), inicio, fim)):
            return
        quem = self.outros_no_sicoob()
        if quem:
            messagebox.showinfo(TITULO, f"O Chrome do Sicoob está em uso: {quem}.")
            return
        tela._log("")
        tela._log(f"Autenticar no banco: {len(contas)} conta(s) do Sicoob, "
                  f"{inicio:%d/%m} a {fim:%d/%m}")
        for conta, motivo in falhas.items():
            tela._log(f"  {conta}: {motivo}")
        self._parar.clear()
        self.b.configure(state="disabled")
        self._thread = threading.Thread(
            target=self._t_ler, name="sicoob-autenticar", daemon=True,
            args=(pendentes, contas, falhas, inicio, fim))
        self._thread.start()

    def _t_ler(self, pendentes, contas, falhas, inicio, fim):
        """Thread do Sicoob: só fala com a tela pela fila; sempre termina com "fim"."""
        try:
            r = asi.ler(contas, inicio, fim, asi.valores_por_conta(pendentes),
                        log=self.tela._log, perguntar=self._perguntar_outro_acesso,
                        parar=self._parar.is_set)
            r.falhas.update({c: m for c, m in falhas.items() if c not in r.lidas})
            aut = au.autenticar(pendentes, r.movimentos, r.pendencias, r.lidas, r.falhas,
                                hoje=_hoje())
            self.q.put(("pronto", aut))
        except Exception as e:                               # noqa: BLE001
            self.q.put(("falhou", f"[!] Autenticar no banco: {e!r}"))
        finally:
            self.q.put(("fim", None))

    def _perguntar_outro_acesso(self, nomes) -> bool:
        caixa = {"ev": threading.Event(), "sim": False}
        lista = ", ".join(nomes[:6]) + ("…" if len(nomes) > 6 else "")
        texto = (f"{len(nomes)} conta(s) não aparecem neste login do Sicoob ({lista}). "
                 "Devem ser de outro acesso.\n\nEntrar com o outro acesso agora? O Chrome "
                 "do Sicoob fecha e abre de novo: entre com o outro acesso (QR Code).")
        self.q.put(("perguntar", (texto, caixa)))
        while not caixa["ev"].wait(0.2):
            if self._parar.is_set():
                return False
        return bool(caixa["sim"]) and not self._parar.is_set()

    def _aplicar(self, autenticacoes):
        self.tela._receber_autenticacao(autenticacoes)

    def _drain(self):
        try:
            while True:
                tipo, valor = self.q.get_nowait()
                if tipo == "perguntar":
                    texto, caixa = valor
                    try:
                        caixa["sim"] = bool(messagebox.askyesno(TITULO, texto,
                                                                default=messagebox.YES))
                    finally:
                        caixa["ev"].set()
                elif tipo == "pronto":
                    self._aplicar(valor)
                    self.tela._log(resumo({k: v for k, v in valor.items()}))
                elif tipo == "falhou":
                    self.tela._log(valor)
                elif tipo == "fim":
                    self.b.configure(state="normal")
        except queue.Empty:
            pass
        except Exception as e:                               # noqa: BLE001
            self.tela._log(f"[!] falha ao mostrar o Autenticar no banco: {e!r}")
        finally:
            self.b.after(200, self._drain)

    def fechar(self):
        self._parar.set()
