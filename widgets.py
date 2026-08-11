# -*- coding: utf-8 -*-
"""Widgets compartilhados pelas abas.

Por que NÃO fica no util.py
---------------------------
O `util.py` é declaradamente "sem dependências pesadas": ele é importado por
`pagamentos_dia/relatorio.py`, `relatorios/contas_mc.py` e
`conciliacao/parsing.py`, que são módulos de REGRA — sem navegador e sem
tkinter, justamente para rodarem inteiros em teste. Botar `tkinter` lá dentro
arrastaria a interface para dentro dessas regras e para dentro do CI.

Então a parte visual mora aqui. Fica na RAIZ (como o util.py) e é copiada para
o codigo.zip junto dele.
"""
from __future__ import annotations

import calendar
import re
from datetime import date

import tkinter as tk
from tkinter import ttk

MESES = ("Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
         "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro")

#: Iniciais dos dias na ordem em que o `calendar` do Python monta a semana
#: (segunda a domingo).
DIAS_DA_SEMANA = ("S", "T", "Q", "Q", "S", "S", "D")


class CampoData(ttk.Frame):
    """Campo de data dd/mm/aaaa, com calendário e máscara.

    Duas formas de preencher, porque as duas aparecem no uso real:

    - CLICAR no campo abre o calendário e a data sai do mouse;
    - DIGITAR funciona direto, com as barras entrando sozinhas
      ("0508" vira "05/08") e o ano completado ao sair do campo.

    O calendário é tkinter puro (Toplevel + grade de botões). Existe pacote
    pronto para isso (`tkcalendar`), mas dependência nova obriga a gerar um
    executável novo de ~150 MB e a subir o `motor_minimo.txt` — caro demais
    para um calendário de 60 linhas.
    """

    def __init__(self, master, textvariable, width=11):
        super().__init__(master)
        self.var = textvariable
        self._popup = None
        self.ent = ttk.Entry(self, textvariable=self.var, width=width)
        self.ent.pack(side="left")
        self.bt = ttk.Button(self, text="📅", width=3, command=self.abrir_calendario)
        self.bt.pack(side="left", padx=(2, 0))

        self.ent.bind("<KeyRelease>", self._ao_digitar)
        self.ent.bind("<Button-1>", lambda _e: self.abrir_calendario())
        self.ent.bind("<FocusOut>", lambda _e: self._completar_ano())

    # ----------------------------------------------------------- digitação
    def _ao_digitar(self, ev):
        # Teclas de navegação e edição não podem remontar o texto embaixo do
        # cursor — senão apagar um dígito no meio vira uma briga com a máscara.
        if ev.keysym in ("BackSpace", "Delete", "Left", "Right", "Up", "Down",
                         "Home", "End", "Tab", "Shift_L", "Shift_R",
                         "Control_L", "Control_R"):
            return
        self._fechar_popup()             # começou a digitar: o calendário sai
        t = self.var.get()
        d = "".join(c for c in t if c.isdigit())[:8]
        if len(d) > 4:
            novo = f"{d[:2]}/{d[2:4]}/{d[4:]}"
        elif len(d) > 2:
            novo = f"{d[:2]}/{d[2:]}"
        else:
            novo = d
        if novo != t:
            self.var.set(novo)
            self.ent.icursor("end")

    def _completar_ano(self):
        """"05/08" -> "05/08/2026"; "05/08/26" -> "05/08/2026".

        Sair do campo com a data pela metade é o caso comum de quem digita
        rápido, e o resto do app só aceita dd/mm/aaaa."""
        t = (self.var.get() or "").strip()
        m = re.match(r"^(\d{2})/(\d{2})(?:/(\d{2}|\d{4}))?$", t)
        if not m:
            return
        ano = m.group(3)
        if ano is None:
            ano = str(date.today().year)
        elif len(ano) == 2:
            ano = f"20{ano}"
        self.var.set(f"{m.group(1)}/{m.group(2)}/{ano}")

    # ---------------------------------------------------------- calendário
    def _data_atual(self) -> tuple[int, int]:
        """(mês, ano) que o calendário deve mostrar ao abrir."""
        hoje = date.today()
        m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", (self.var.get() or "").strip())
        if not m:
            return hoje.month, hoje.year
        mes = int(m.group(2))
        return (mes if 1 <= mes <= 12 else hoje.month), int(m.group(3))

    def _fechar_popup(self):
        if self._popup is not None:
            try:
                self._popup.destroy()
            except tk.TclError:
                pass
            self._popup = None

    def abrir_calendario(self):
        if self._popup is not None:       # já aberto: clicar de novo fecha
            self._fechar_popup()
            return

        top = tk.Toplevel(self)
        self._popup = top
        top.transient(self.winfo_toplevel())
        top.resizable(False, False)
        # Sem barra de título: é um popup, não uma janela. E sem grab_set —
        # com grab, digitar no campo ficaria bloqueado enquanto ele estivesse
        # aberto, e digitar é o outro caminho que a pessoa pode querer.
        try:
            top.overrideredirect(True)
        except tk.TclError:
            top.title("Escolher data")
        top.geometry(f"+{self.ent.winfo_rootx()}"
                     f"+{self.ent.winfo_rooty() + self.ent.winfo_height() + 2}")

        moldura = ttk.Frame(top, relief="solid", borderwidth=1, padding=6)
        moldura.pack(fill="both", expand=True)

        mes, ano = self._data_atual()
        estado = {"mes": mes, "ano": ano}

        cab = ttk.Frame(moldura); cab.pack(fill="x")
        lbl = ttk.Label(cab, text="", width=16, anchor="center")
        grade = ttk.Frame(moldura); grade.pack(pady=(4, 0))

        def escolher(dia: int):
            self.var.set(f"{dia:02d}/{estado['mes']:02d}/{estado['ano']}")
            self._fechar_popup()

        def desenhar():
            for w in grade.winfo_children():
                w.destroy()
            lbl.config(text=f"{MESES[estado['mes'] - 1]} {estado['ano']}")
            for i, inicial in enumerate(DIAS_DA_SEMANA):
                ttk.Label(grade, text=inicial, width=3, anchor="center"
                          ).grid(row=0, column=i)
            semanas = calendar.Calendar().monthdayscalendar(
                estado["ano"], estado["mes"])
            for r, semana in enumerate(semanas, 1):
                for c, dia in enumerate(semana):
                    if dia:
                        ttk.Button(grade, text=str(dia), width=3,
                                   command=lambda d=dia: escolher(d)
                                   ).grid(row=r, column=c, padx=1, pady=1)

        def mudar(delta: int):
            m2 = estado["mes"] + delta
            if m2 < 1:
                estado["mes"], estado["ano"] = 12, estado["ano"] - 1
            elif m2 > 12:
                estado["mes"], estado["ano"] = 1, estado["ano"] + 1
            else:
                estado["mes"] = m2
            desenhar()

        ttk.Button(cab, text="◀", width=3, command=lambda: mudar(-1)).pack(side="left")
        lbl.pack(side="left", expand=True)
        ttk.Button(cab, text="▶", width=3, command=lambda: mudar(1)).pack(side="right")

        rodape = ttk.Frame(moldura); rodape.pack(fill="x", pady=(4, 0))
        ttk.Button(rodape, text="Hoje", command=lambda: (
            self.var.set(f"{date.today():%d/%m/%Y}"), self._fechar_popup())
        ).pack(side="left")
        ttk.Button(rodape, text="Fechar", command=self._fechar_popup).pack(side="right")

        desenhar()
        # Clicar fora fecha. `<Escape>` também, porque popup sem saída pelo
        # teclado é armadilha para quem navega por Tab.
        top.bind("<Escape>", lambda _e: self._fechar_popup())
        top.bind("<FocusOut>", lambda _e: self._fechar_popup())
        top.focus_set()

    # ------------------------------------------------------------- tema
    def aplicar_cores(self, escuro: bool):
        """Nada a fazer: Entry e Button do ttk seguem o tema sozinhos.

        Existe para a aba poder chamar sem saber o tipo do campo."""
        return
