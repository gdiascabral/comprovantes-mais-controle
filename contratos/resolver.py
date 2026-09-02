# -*- coding: utf-8 -*-
"""A janela de resolver uma casa que o app não soube decidir sozinho.

Duas pendências cabem aqui, e são independentes:

  - QUAL anexo é o contrato daquela casa (dois disputando, ou nenhum
    começando com CONTRATO);
  - de QUAL empresa é a obra, quando o cliente do ERP não está no
    `clientes_erp` de ninguém.

A janela não decide nada e não escreve em lugar nenhum: mostra o que existe e
devolve a escolha para a aba, que aplica. É o mesmo desenho da janela de
DÚVIDAS do Anexar — quem confere quer VER antes, e ver aqui é poder abrir o
arquivo, não ler o nome dele e torcer.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

import util
import widgets

from .escolha import ordenar_para_escolha


def _nome(anexo: dict) -> str:
    return (anexo.get("filename") or "").strip()


class JanelaResolver(tk.Toplevel):
    """`ao_confirmar(anexo, empresa, gravar_no_cadastro)` só é chamado no OK.

    `abrir_anexo(anexo)` roda na thread do navegador (é ela que baixa) e volta
    na hora: o resultado chega pelo `dizer()`."""

    def __init__(self, master, achado, empresas: list[str],
                 abrir_anexo, ao_confirmar):
        super().__init__(master)
        self.achado = achado
        self.abrir_anexo = abrir_anexo
        self.ao_confirmar = ao_confirmar
        self.por_iid: dict[str, dict] = {}

        self.title(f"Resolver — {achado.imovel.obra} {achado.imovel.rotulo}")
        self.transient(master.winfo_toplevel())
        widgets.barra_de_titulo(self)
        try:
            self.geometry(f"{min(940, self.winfo_screenwidth() - 80)}"
                          f"x{min(620, self.winfo_screenheight() - 120)}")
        except tk.TclError:
            pass

        self.v_busca = tk.StringVar()
        self.v_empresa = tk.StringVar(value=achado.empresa or "")
        self.v_gravar = tk.BooleanVar(value=True)

        self._montar(empresas)
        self._encher()
        self.after(60, self.focus_force)

    # ---------------------------------------------------------------- layout
    def _montar(self, empresas: list[str]):
        i = self.achado.imovel
        cab = ttk.Frame(self)
        cab.pack(fill="x", padx=12, pady=(12, 4))
        ttk.Label(cab, style="Secao.TLabel",
                  text=f"{i.obra}  {i.rotulo}  ·  {i.comprador}").pack(anchor="w")
        ttk.Label(cab, style="Apoio.TLabel",
                  text=f"financiamento R$ {i.valor_financiamento:,.2f}   ·   "
                       f"cliente da obra no ERP: "
                       f"{self.achado.cliente_erp or '(sem cliente)'}"
                  ).pack(anchor="w")

        # ---- contrato
        f1 = widgets.Cartao(self, "Qual anexo é o contrato desta casa",
                            padding=(10, 6, 10, 10))
        f1.pack(fill="both", expand=True, padx=12, pady=6)

        linha = ttk.Frame(f1); linha.pack(fill="x", pady=(0, 6))
        ttk.Label(linha, text="Procurar:").pack(side="left")
        ttk.Entry(linha, textvariable=self.v_busca).pack(side="left", fill="x",
                                                        expand=True, padx=(6, 8))
        self.v_busca.trace_add("write", lambda *_: self._encher())
        ttk.Button(linha, text="Abrir para olhar",
                   command=self._abrir).pack(side="left")

        tabela = ttk.Frame(f1); tabela.pack(fill="both", expand=True)
        self.lista = ttk.Treeview(tabela, columns=("marca", "nome"),
                                  show="headings", height=11, selectmode="browse")
        self.lista.heading("marca", text="")
        self.lista.heading("nome", text="Arquivo anexado à obra")
        self.lista.column("marca", width=90, anchor="center", stretch=False)
        self.lista.column("nome", width=740, anchor="w")
        self.lista.pack(side="left", fill="both", expand=True)
        ttk.Scrollbar(tabela, orient="vertical", command=self.lista.yview
                      ).pack(side="right", fill="y")
        self.lista.bind("<Double-1>", lambda _e: self._abrir())

        # ---- empresa (só quando falta)
        if not self.achado.empresa:
            f2 = widgets.Cartao(self, "De qual empresa é esta obra",
                                padding=(10, 6, 10, 10))
            f2.pack(fill="x", padx=12, pady=6)
            l2 = ttk.Frame(f2); l2.pack(fill="x")
            ttk.Label(l2, text="Empresa:").pack(side="left")
            ttk.Combobox(l2, textvariable=self.v_empresa, values=empresas,
                         state="readonly", width=34).pack(side="left", padx=(6, 0))
            ttk.Checkbutton(
                f2, variable=self.v_gravar,
                text=f'gravar "{self.achado.cliente_erp}" como cliente desta '
                     f"empresa no contas_sicoob.json (resolve os próximos meses)"
                ).pack(anchor="w", pady=(6, 0))

        # ---- rodapé
        rod = ttk.Frame(self); rod.pack(fill="x", padx=12, pady=(4, 12))
        self.lbl = ttk.Label(rod, style="Apoio.TLabel", text="")
        self.lbl.pack(side="left")
        widgets.Botao(rod, "Confirmar", papel="acao", command=self._confirmar
                      ).pack(side="right")
        widgets.Botao(rod, "Cancelar", papel="neutro", command=self.destroy
                      ).pack(side="right", padx=(0, 8))

    # ----------------------------------------------------------------- lista
    def _encher(self):
        procura = util.norm_espaco(self.v_busca.get())
        escolhido = _nome(self.achado.anexo or {})
        self.lista.delete(*self.lista.get_children())
        self.por_iid = {}
        for n, (anexo, candidato) in enumerate(
                ordenar_para_escolha(self.achado.anexos_da_obra,
                                     self.achado.imovel.unidade)):
            nome = _nome(anexo)
            if procura and procura not in util.norm_espaco(nome):
                continue
            iid = str(n)
            self.por_iid[iid] = anexo
            self.lista.insert("", "end", iid=iid,
                              values=("candidato" if candidato else "", nome))
            if nome and nome == escolhido:
                self.lista.selection_set(iid)
                self.lista.see(iid)

        if not self.por_iid:
            vazio = ("a obra não tem nenhum anexo" if not self.achado.anexos_da_obra
                     else "nenhum anexo com esse texto no nome")
            self.lista.insert("", "end", iid="-", values=("", vazio))

    def _selecionado(self) -> dict | None:
        return self.por_iid.get((self.lista.selection() or [None])[0])

    # ----------------------------------------------------------------- ações
    def dizer(self, msg: str):
        """Recado do trabalho que roda na thread do navegador."""
        try:
            self.lbl.configure(text=msg)
        except tk.TclError:
            pass

    def _abrir(self):
        anexo = self._selecionado()
        if anexo is None:
            messagebox.showinfo("Abrir", "Escolha um arquivo da lista primeiro.",
                                parent=self)
            return
        self.dizer("Baixando para abrir...")
        self.abrir_anexo(anexo)

    def _confirmar(self):
        anexo = self._selecionado()
        if anexo is None and not self.achado.anexo:
            messagebox.showinfo(
                "Falta o contrato",
                "Escolha na lista qual anexo é o contrato desta casa.",
                parent=self)
            return
        empresa = (self.v_empresa.get() or "").strip()
        if not empresa and not self.achado.empresa:
            messagebox.showinfo(
                "Falta a empresa",
                "Escolha de qual empresa é esta obra — é ela que decide a "
                "pasta onde o contrato vai ser arquivado.", parent=self)
            return
        self.ao_confirmar(anexo, empresa, bool(self.v_gravar.get()))
        self.destroy()
