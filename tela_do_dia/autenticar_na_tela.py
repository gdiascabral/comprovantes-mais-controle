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

Inter (dono, 29/10/2026: "QR por conta toda manhã, a mesma leitura servindo
para saldo e para autenticar"): depois do Sicoob, uma conta do Inter por vez,
cada uma com o seu QR (`autenticar_inter`, pela sessão do `inter_saldo` da
Prova de saldos). O saldo lido vai para o arquivo do dia, e a Prova de saldos
o usa sem pedir o QR de novo.
"""
from __future__ import annotations

import datetime
import queue
import threading
from tkinter import messagebox

import widgets
from pagamentos_dia import agendamentos_sicoob as A

from . import autenticar as au
from . import autenticar_inter as ai
from . import autenticar_sicoob as asi

TITULO = "Autenticar no banco"


def _hoje() -> datetime.date:
    return datetime.date.today()


def _carregar_mapas():
    """(mapa_mc, empresas, contas_inter) — função à parte para o teste."""
    from baixar_comprovantes import contas_inter
    from pagamentos_dia import pagamentos_frame
    mapa_mc, empresas = pagamentos_frame._carregar_mapas()
    return mapa_mc, empresas, contas_inter.carregar()


def _raiz_saida():
    from conciliacao.frame import RAIZ_SAIDA
    return RAIZ_SAIDA


def pergunta_de_abrir(n_contas: int, inicio, fim, inter=()) -> str:
    partes = []
    if n_contas:
        partes.append(f"o Chrome do Sicoob e ler {n_contas} conta(s) (entre no "
                      "SicoobNet quando ele abrir)")
    if inter:
        partes.append(f"depois o Inter, uma conta por vez, cada uma com o seu QR "
                      f"({', '.join(inter)}) — o saldo lido serve à Prova de saldos")
    return (f"Vou abrir {' e '.join(partes)}, de {inicio:%d/%m} a {fim:%d/%m}: só as "
            "listas de pagamentos, Pix e pendências. Nada é assinado nem baixado.\n\n"
            "Continuar?")


def recusa(lido, leitura, lido_no_dia, hoje) -> str:
    """"" quando dá para autenticar; senão o recado. A prova do banco é
    refeita com o título que o ÚLTIMO Buscar releu no ERP: Buscar de outro
    dia, ou leitura sem o ERP relido (a releitura depois de gravar na nuvem
    só relê a nuvem), deixaria "valor mudou" escondido ou apagaria provas
    (revisão de dinheiro, 29/10/2026)."""
    if lido is None or leitura is None:
        return ("Clique em Buscar primeiro: é ele que relê os títulos no ERP, e "
                "sem isso o banco não prova nada.")
    if lido_no_dia != hoje:
        return ("O último Buscar não é de hoje: clique em Buscar de novo, para os "
                "títulos serem relidos no ERP antes de conferir o banco.")
    if not getattr(lido, "relido", False):
        return ("Os títulos não foram relidos no ERP nesta leitura (ela só releu a "
                "nuvem): clique em Buscar de novo e depois em Autenticar.")
    return ""


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
        motivo = recusa(lido, getattr(tela, "leitura", None),
                        getattr(tela, "_lido_no_dia", None), _hoje())
        if motivo:
            messagebox.showinfo(TITULO, motivo)
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
            mapa_mc, empresas, contas_inter = _carregar_mapas()
        except Exception as e:                               # noqa: BLE001
            messagebox.showwarning(TITULO, widgets.recado_de_erro(
                e, "Não consegui ler o cadastro de contas."))
            return
        contas, falhas = asi.contas_a_ler(
            pendentes, lambda c: A.conta_sicoob(c, mapa_mc, empresas))
        inter, falhas_inter = ai.contas_a_ler(pendentes, mapa_mc, empresas, contas_inter,
                                              getattr(tela, "contas_erp", ()))
        falhas = {**falhas, **falhas_inter}
        periodo = asi.periodo(pendentes, _hoje())
        if not contas and not inter:
            self._aplicar(au.autenticar(pendentes, [], falhas=falhas, hoje=_hoje()))
            messagebox.showinfo(TITULO, "Nenhum agendado pendente é de conta do Sicoob ou "
                                        "do Inter que dê para ler (veja o Registro).")
            return
        inicio, fim = periodo
        if not messagebox.askokcancel(TITULO, pergunta_de_abrir(
                len(contas), inicio, fim, [c.apelido for c in inter.values()])):
            return
        quem = self.outros_no_sicoob()
        if quem:
            messagebox.showinfo(TITULO, f"O Chrome do Sicoob está em uso: {quem}.")
            return
        tela._log("")
        tela._log(f"Autenticar no banco: {len(contas)} conta(s) do Sicoob e "
                  f"{len(inter)} do Inter, {inicio:%d/%m} a {fim:%d/%m}")
        for conta, motivo in falhas.items():
            tela._log(f"  {conta}: {motivo}")
        self._parar.clear()
        self.b.configure(state="disabled")
        self._thread = threading.Thread(
            target=self._t_ler, name="sicoob-autenticar", daemon=True,
            args=(pendentes, contas, falhas, inicio, fim, inter, self._pasta_prints()))
        self._thread.start()

    def _pasta_prints(self):
        try:
            base = self.tela._pasta_pagamentos()
        except Exception:                                    # noqa: BLE001
            base = None
        from pathlib import Path
        return (Path(base) if base else Path(".")) / "Autenticar no banco" / "prints" \
            / f"{_hoje():%Y-%m-%d}"

    def _t_ler(self, pendentes, contas, falhas, inicio, fim, inter=None, pasta=None):
        """Thread dos bancos: só fala com a tela pela fila; sempre termina com "fim"."""
        try:
            r = asi.Leitura()
            if contas:
                r = asi.ler(contas, inicio, fim, asi.valores_por_conta(pendentes),
                            log=self.tela._log, perguntar=self._perguntar_outro_acesso,
                            parar=self._parar.is_set)
            if inter:
                ri, lidos = ai.ler(inter, inicio, fim, pasta, log=self.tela._log,
                                   avisar_qr=lambda apelido: self.q.put(("qr", apelido)),
                                   parar=self._parar.is_set)
                r.movimentos.extend(ri.movimentos)
                r.lidas |= ri.lidas
                r.falhas.update(ri.falhas)
                try:
                    hoje = _hoje()
                    ai.gravar_saldos(lidos, ai.caminho_dos_saldos(_raiz_saida(), hoje), hoje)
                except Exception as e:                       # noqa: BLE001
                    self.q.put(("falhou", f"[!] não gravei o saldo do Inter do dia: {e!r}"))
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
                elif tipo == "qr":
                    self.tela._log(f"  Inter {valor}: escaneie o QR Code no Chrome que abriu.")
                    self.b.configure(text=f"QR do Inter: {valor}…")
                elif tipo == "fim":
                    self.b.configure(state="normal", text="🔎  Autenticar no banco")
        except queue.Empty:
            pass
        except Exception as e:                               # noqa: BLE001
            self.tela._log(f"[!] falha ao mostrar o Autenticar no banco: {e!r}")
        finally:
            self.b.after(200, self._drain)

    def fechar(self):
        self._parar.set()
