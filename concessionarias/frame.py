# -*- coding: utf-8 -*-
"""Aba Água e energia: roda a rodada do coletor a qualquer hora (plano 2).

O trabalho é de OUTRO processo (`coletor\\rodada_diaria.bat`, o mesmo da
tarefa agendada). Esta aba só dispara, acompanha o log e mostra o resumo —
não tem navegador nem thread própria, e por isso não tem `fechar()`: fechar o
app não para a rodada, e a trava de lá impede uma segunda.

Chrome central LIGADO: a rodada abre a aba dela no Chrome do porteiro e nada
cai. DESLIGADO: ela abre o próprio Chrome e entra no ERP com o login do app —
uma sessão por usuário, e a do app cai. Por isso, desligado, a aba recusa
enquanto o Anexar trabalha e pede confirmação quando ele está livre.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import util
import widgets
from widgets import px

from . import rodada

_INTERVALO_MS = 1000
_PADRAO = object()


def _central_ligado() -> bool:
    try:
        from erp import central
        return central.ligado()
    except Exception:                                        # noqa: BLE001
        return False


def _quem() -> str:
    # `sessao.quem()` devolve o `Quem`, que só tem `primeiro_nome`;
    # `como_chamar` é do `Usuario` de nuvem/usuarios.py.
    try:
        from nuvem import sessao
        return sessao.quem().primeiro_nome
    except Exception:                                        # noqa: BLE001
        return ""


_log = util.log("agua_energia_aba")


def _msg_andamento(info) -> str:
    final = ("Espere ou chame o suporte." if info.get("ilegivel")
             else "Espere ela terminar.")
    return f"{rodada.descrever(info)}. {final}"


def _registrar(acao, detalhe="", **kw):
    from nuvem import auditoria
    auditoria.registrar(acao, detalhe, **kw)


class AguaEnergiaFrame(ttk.Frame):
    def __init__(self, master, anx=None, *, pasta=_PADRAO, iniciar=None,
                 central_ligado=None, perguntar=None, registrar=None, quem=None):
        super().__init__(master)
        self.anx = anx
        self.pasta = rodada.pasta_agua_energia() if pasta is _PADRAO else pasta
        self._iniciar = iniciar or rodada.iniciar
        self._central_ligado = central_ligado or _central_ligado
        self._perguntar = perguntar or (lambda t, m: messagebox.askyesno(t, m, parent=self))
        self._registrar = registrar or _registrar
        self._quem = quem or _quem
        self.proc = None
        self.leitor = None
        self._linhas: list[str] = []
        self._pedido = ""
        self.v_so = tk.StringVar(value="completa")
        self.v_status = tk.StringVar()
        self._build()
        if self.pasta is None:
            self.b_rodar.configure(state="disabled")
            self.v_status.set("O água e energia não está instalado nesta máquina "
                              "(ou MC_AGUA_ENERGIA=off).")
        else:
            self.v_status.set("Pronto. A tarefa agendada continua rodando nos horários dela.")

    # ---------------------------------------------------------------- layout
    def _build(self):
        PADX = px(widgets.PADX)
        self.cab = widgets.Cabecalho(
            self, "Água e energia",
            "Roda agora a rodada da Equatorial e da Sanesc — a mesma da tarefa "
            "agendada, mesmo fora do horário, fim de semana ou feriado.",
            trilha="Diário  ›  Água e energia")
        self.cab.pack(fill="x", padx=PADX, pady=px((16, 12)))
        self.b_rodar = widgets.Botao(self.cab.acoes, "Rodar agora", papel="acao",
                                     command=self.rodar)
        self.b_rodar.pack(side="left")
        # O meio da tela rola quando não cabe (ver `widgets.AreaRolavel`).
        corpo = widgets.AreaRolavel(self)

        # O Cartao É o conteúdo (a moldura é outro objeto): filhos entram nele.
        c1 = widgets.Cartao(corpo, "O que rodar", 1)
        c1.pack(fill="x", padx=PADX, pady=px((0, 12)))
        for valor, texto in (("completa", "Rodada completa: Equatorial, Sanesc, "
                                           "lançamento no ERP e renovações"),
                             ("equatorial", "Só a Equatorial (sem ERP)")):
            ttk.Radiobutton(c1, text=texto, value=valor,
                            variable=self.v_so).pack(anchor="w")
        ttk.Label(c1, textvariable=self.v_status,
                  wraplength=px(720)).pack(anchor="w", pady=px((8, 0)))

        c3 = widgets.Cartao(corpo, "Resumo da rodada", 2)
        c3.pack(fill="both", expand=True, padx=PADX, pady=px((0, 12)))
        self.resumo = tk.Text(c3, height=12, wrap="word", relief="flat",
                              borderwidth=0, highlightthickness=0)
        widgets.estilo_log(self.resumo)
        self.resumo.pack(fill="both", expand=True)

        # O andamento é o Registro da aba: preso no pé, elástico.
        self.reg = widgets.Cartao(self, "Andamento", padding=(12, 10))
        self.reg.pack(fill="x", padx=PADX, pady=px((0, 12)))
        self.log = tk.Text(self.reg, height=12, wrap="word", relief="flat",
                           borderwidth=0, highlightthickness=0)
        self.log.pack(fill="both", expand=True)
        widgets.estilo_log(self.log)
        widgets.registro_elastico(self.reg, self.log)

        corpo.encaixar(self.reg)

    def aplicar_cores(self, escuro: bool):
        for campo in (self.log, self.resumo):
            try:
                widgets.estilo_log(campo, escuro)
            except tk.TclError:
                pass

    # ------------------------------------------------------------- a rodada
    def ocupado(self) -> str | None:
        if self.proc is not None:
            return "Rodada de água e energia"
        return None

    def ao_abrir(self):
        if self.proc is None and self.pasta is not None:
            info = rodada.em_andamento(self.pasta)
            if info is not None:
                self.v_status.set(_msg_andamento(info))

    def rodar(self):
        if self.pasta is None or self.proc is not None:
            return
        info = rodada.em_andamento(self.pasta)
        if info is not None:
            self.v_status.set(_msg_andamento(info))
            return
        so = None if self.v_so.get() == "completa" else self.v_so.get()
        if so is None and not self._central_ligado():
            tarefa = self.anx.ocupado() if self.anx is not None else None
            if tarefa:
                self.v_status.set(f"O Anexar está usando o ERP ({tarefa}). Sem o Chrome "
                                  "central, a rodada derrubaria essa sessão: espere terminar.")
                return
            if not self._perguntar(
                    "Água e energia",
                    "O Chrome central está desligado: a rodada vai entrar no ERP com o "
                    "login do app, e a sessão do ERP aberta aqui no app cai.\n\nRodar mesmo assim?"):
                return
        origem = rodada.origem_segura(self._quem())
        self._pedido = "--forcar" + (f" --so {so}" if so else "")
        log = rodada.novo_log(self.pasta)
        self.leitor = rodada.Leitor(log)              # ANTES do iniciar
        self._linhas = []
        try:
            self.proc = self._iniciar(self.pasta, so=so, origem=origem, log=log)
        except OSError as e:
            self.leitor = None
            self.v_status.set(f"Não consegui iniciar a rodada: {e}")
            return
        self.b_rodar.configure(state="disabled")
        self.log.delete("1.0", "end")
        self.resumo.delete("1.0", "end")
        self.v_status.set(f"Rodando ({self._pedido}). Pode trocar de aba; o andamento "
                          "continua aqui.")
        self.after(_INTERVALO_MS, self._acompanhar)
        self._auditar("Água e energia: rodada disparada", self._pedido, "ok")

    def _auditar(self, acao, detalhe, resultado):
        """Falha de registro nunca prende a aba nem larga a rodada sem
        acompanhamento: só anota no log do app."""
        try:
            self._registrar(acao, detalhe, aba="agu", resultado=resultado)
        except Exception:                                    # noqa: BLE001
            _log.warning("não consegui registrar '%s'", acao, exc_info=True)

    def _acompanhar(self):
        if self.proc is None:
            return
        for linha in self.leitor.novas():
            self._linhas.append(linha)
            self.log.insert("end", linha + "\n")
            self.log.see("end")
        rc = self.proc.poll()
        if rc is None:
            self.after(_INTERVALO_MS, self._acompanhar)
            return
        for linha in self.leitor.novas():
            self._linhas.append(linha)
            self.log.insert("end", linha + "\n")
        self.proc = None
        self.b_rodar.configure(state="normal")
        texto = rodada.veredito(rc)
        self.v_status.set(f"A rodada {texto}.")
        if rc == rodada.CODIGO_OCUPADA:
            conteudo = "(esta rodada não rodou: outra já estava em andamento)"
        else:
            caminho = rodada.resumo_do_log(self._linhas)
            try:
                conteudo = caminho.read_text(encoding="utf-8") if caminho else ""
            except OSError as e:
                conteudo = f"(não consegui ler {caminho}: {e})"
        self.resumo.insert("1.0", conteudo or "(esta rodada não gravou resumo)")
        resultado = "ok" if rc == 0 else ("aviso" if rc in (1, rodada.CODIGO_OCUPADA) else "erro")
        self._auditar("Água e energia: rodada terminou",
                      f"{self._pedido} — {texto}", resultado)
