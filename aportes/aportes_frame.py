# -*- coding: utf-8 -*-
"""
Aba "Aportes": lança aportes e distribuições direto no Mais Controle.

Compartilha o navegador e a thread do AnexarFrame — o Playwright síncrono só
aceita uma thread, e abrir um segundo Chrome significaria um segundo login.
É o mesmo arranjo que a Conferência já usa.
"""
from __future__ import annotations

import datetime
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parent))

import dados as cadastro                                    # noqa: E402
from mc_catalogos import Catalogos                          # noqa: E402
from mc_lancamentos import (criar_pagamento, criar_recebimento,  # noqa: E402
                            ErroLancamento)
from regras import Operacao, expandir                       # noqa: E402

CABECALHOS = {"authorization", "company-id", "user-id", "organization-unit-id"}
HOSTS_IGNORAR = ("api-data-event", "faro.", "satismeter", "datadog", "google")
URL_PAGAMENTOS = "https://acessar.maiscontroleerp.com.br/#/payable-installments"


def _host_util(host: str) -> bool:
    if any(x in host for x in HOSTS_IGNORAR):
        return False
    return host.endswith("maiscontroleerp.com.br") or "execute-api" in host


class AportesFrame(ttk.Frame):
    def __init__(self, master, anexar_frame):
        super().__init__(master, padding=12)
        self.anx = anexar_frame          # dono do navegador e da thread
        self.operacoes: list[Operacao] = []
        # Para cada operação, os ÍNDICES dos lançamentos que já entraram no ERP.
        # Sem isso, tentar de novo depois de uma falha parcial recria o que deu
        # certo — e aporte duplicado é dinheiro duplicado, desfeito à mão.
        self.criados: list[set[int]] = []
        self.catalogos: Catalogos | None = None
        self._cabecalhos: dict = {}

        self.entidades = cadastro.carregar_contas()
        self.subcontas = cadastro.carregar_subcontas()
        self.obra_padrao = cadastro.config_obra_padrao()

        self._montar()
        self._recarregar_listas()

    # ------------------------------------------------------------ interface
    def _montar(self):
        ttk.Label(self, text="Aportes e Distribuições",
                  font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(self, text="Lança direto no Mais Controle — sem planilha, "
                             "sem importação.").pack(anchor="w", pady=(0, 10))

        form = ttk.LabelFrame(self, text="Novo lançamento", padding=10)
        form.pack(fill="x")

        linha1 = ttk.Frame(form); linha1.pack(fill="x", pady=3)
        ttk.Label(linha1, text="Data", width=8).pack(side="left")
        self.var_data = tk.StringVar(value=f"{datetime.date.today():%d/%m/%Y}")
        ttk.Entry(linha1, textvariable=self.var_data, width=12).pack(side="left")
        ttk.Label(linha1, text="  Valor R$", width=10).pack(side="left")
        self.var_valor = tk.StringVar()
        ttk.Entry(linha1, textvariable=self.var_valor, width=14).pack(side="left")

        linha2 = ttk.Frame(form); linha2.pack(fill="x", pady=3)
        ttk.Label(linha2, text="Pagou", width=8).pack(side="left")
        self.cb_pagador = ttk.Combobox(linha2, state="readonly", width=38)
        self.cb_pagador.pack(side="left")
        ttk.Label(linha2, text="  Recebeu", width=10).pack(side="left")
        self.cb_recebedor = ttk.Combobox(linha2, state="readonly", width=38)
        self.cb_recebedor.pack(side="left")

        linha3 = ttk.Frame(form); linha3.pack(fill="x", pady=3)
        ttk.Label(linha3, text="Tipo", width=8).pack(side="left")
        self.cb_tipo = ttk.Combobox(linha3, state="readonly", width=22,
                                    values=cadastro.TIPOS)
        self.cb_tipo.current(0); self.cb_tipo.pack(side="left")
        ttk.Label(linha3, text="  Lançar", width=10).pack(side="left")
        self.cb_modo = ttk.Combobox(linha3, state="readonly", width=24,
                                    values=cadastro.MODOS)
        self.cb_modo.current(0); self.cb_modo.pack(side="left")
        ttk.Label(linha3, text="  Forma", width=8).pack(side="left")
        self.cb_forma = ttk.Combobox(linha3, state="readonly", width=20,
                                     values=cadastro.FORMAS)
        self.cb_forma.current(0); self.cb_forma.pack(side="left")

        ttk.Button(form, text="+  Adicionar à lista",
                   command=self._adicionar).pack(anchor="w", pady=(8, 0))

        lista = ttk.LabelFrame(self, text="A lançar", padding=8)
        lista.pack(fill="both", expand=True, pady=10)
        self.tabela = ttk.Treeview(lista, columns=("op",), show="headings",
                                   height=7)
        self.tabela.heading("op", text="Operação")
        self.tabela.column("op", width=760, anchor="w")
        self.tabela.pack(fill="both", expand=True, side="left")
        ttk.Scrollbar(lista, orient="vertical", command=self.tabela.yview
                      ).pack(side="right", fill="y")

        botoes = ttk.Frame(self); botoes.pack(fill="x")
        ttk.Button(botoes, text="Remover selecionado",
                   command=self._remover).pack(side="left")
        ttk.Button(botoes, text="Limpar tudo",
                   command=self._limpar).pack(side="left", padx=6)
        ttk.Button(botoes, text="Recarregar cadastros",
                   command=self._recarregar_cadastros).pack(side="left")
        self.lbl_total = ttk.Label(botoes, text="")
        self.lbl_total.pack(side="right")

        acoes = ttk.Frame(self); acoes.pack(fill="x", pady=(10, 0))
        self.b_conferir = ttk.Button(
            acoes, text="1. Conferir cadastro no Mais Controle",
            command=self._conferir)
        self.b_conferir.pack(side="left")
        self.b_lancar = ttk.Button(acoes, text="2. Lançar no Mais Controle",
                                   style="Accent.TButton", command=self._lancar)
        self.b_lancar.pack(side="left", padx=8)

        self.texto = tk.Text(self, height=10, wrap="word")
        self.texto.pack(fill="both", expand=True, pady=(10, 0))

    def _recarregar_listas(self):
        nomes = list(self.entidades)
        pagadores = nomes + [cadastro.INVESTIDOR_PREFIXO + n
                             for n in self.subcontas if not n.startswith("_")]
        self.cb_pagador["values"] = pagadores
        self.cb_recebedor["values"] = nomes
        if pagadores:
            self.cb_pagador.current(0)
        if len(nomes) > 1:
            self.cb_recebedor.current(1)
        if not nomes:
            self._log("Nenhuma conta cadastrada. Crie o arquivo contas.csv "
                      f"em {cadastro.ARQUIVO_CONTAS}")

    def _log(self, msg=""):
        self.texto.insert("end", f"{msg}\n")
        self.texto.see("end")
        self.update_idletasks()

    def aplicar_cores(self, escuro: bool):
        fundo = "#1c1c1c" if escuro else "#ffffff"
        frente = "#e8e8e8" if escuro else "#000000"
        try:
            self.texto.configure(background=fundo, foreground=frente,
                                 insertbackground=frente)
        except tk.TclError:
            pass

    # ------------------------------------------------------------- lista
    def _adicionar(self):
        try:
            data = datetime.datetime.strptime(self.var_data.get().strip(),
                                              "%d/%m/%Y").date()
        except ValueError:
            messagebox.showwarning("Data", "Use o formato dd/mm/aaaa.")
            return
        try:
            valor = float(self.var_valor.get().replace(".", "").replace(",", "."))
        except ValueError:
            messagebox.showwarning("Valor", "Valor inválido.")
            return

        op = Operacao(data=data, pagador=self.cb_pagador.get(),
                      recebedor=self.cb_recebedor.get(), valor=valor,
                      tipo=self.cb_tipo.get(), modo=self.cb_modo.get(),
                      forma=self.cb_forma.get())
        erros = op.validar(self.entidades, self.subcontas)
        if erros:
            messagebox.showwarning("Não dá para lançar assim", "\n".join(erros))
            return
        self.operacoes.append(op)
        self.criados.append(set())
        self.tabela.insert("", "end", values=(op.resumo(),))
        self.var_valor.set("")
        self._atualizar_total()

    def _remover(self):
        # De trás para frente: apagar pelo índice desloca os seguintes.
        for item in sorted(self.tabela.selection(),
                           key=self.tabela.index, reverse=True):
            indice = self.tabela.index(item)
            self.tabela.delete(item)
            del self.operacoes[indice]
            del self.criados[indice]
        self._atualizar_total()

    def _limpar(self):
        self.tabela.delete(*self.tabela.get_children())
        self.operacoes.clear()
        self.criados.clear()
        self._atualizar_total()

    def _retirar_concluidas(self):
        """Tira da fila as operações cujos lançamentos TODOS entraram no ERP.

        Roda na thread da interface. O que falhou fica para nova tentativa; o
        que já foi criado sai da lista, senão o próximo clique em Lançar
        recriaria o mesmo aporte."""
        sobrou_ops, sobrou_criados, concluidas = [], [], 0
        for op, feitos in zip(self.operacoes, self.criados):
            total = len(expandir(op, self.entidades, self.subcontas,
                                 self.obra_padrao))
            if total and len(feitos) >= total:
                concluidas += 1
                continue
            sobrou_ops.append(op)
            sobrou_criados.append(feitos)

        if concluidas:
            self.operacoes[:] = sobrou_ops
            self.criados[:] = sobrou_criados
            self.tabela.delete(*self.tabela.get_children())
            for op in self.operacoes:
                self.tabela.insert("", "end", values=(op.resumo(),))
            self._atualizar_total()
            self._log(f"{concluidas} operação(ões) concluída(s) saíram da lista.")
        if self.operacoes:
            self._log("O que sobrou ainda NÃO foi criado — corrija o cadastro e "
                      "clique em Lançar de novo; o que já entrou será pulado.")

    def _atualizar_total(self):
        total = sum(o.valor for o in self.operacoes)
        # Conta os lançamentos que realmente vão para o ERP: uma operação pode
        # virar dois, e o rateio vira vários. É esse número que tem que bater
        # com o que aparece no Mais Controle depois.
        n = sum(len(expandir(o, self.entidades, self.subcontas,
                             self.obra_padrao)) for o in self.operacoes)
        self.lbl_total.configure(
            text=f"{len(self.operacoes)} operação(ões) · {n} lançamento(s) · "
                 f"R$ {total:,.2f}")

    # --------------------------------------------------------- Mais Controle
    def _preparar_sessao(self, recarregar: bool = False):
        """Roda NA THREAD do navegador. Garante login e catálogos.

        Os cadastros são lidos UMA vez por sessão. Reler a cada botão custava
        centenas de idas ao servidor (são ~440 participantes) e era o que
        deixava a tela parada — os cadastros não mudam no meio do trabalho."""
        self.anx.garantir_sessao(self._log)
        if self.catalogos is not None and not recarregar:
            return
        pagina = self.anx.mc.page

        if not self._cabecalhos:
            def ao_requisitar(req):
                from urllib.parse import urlsplit
                host = urlsplit(req.url).netloc
                if not _host_util(host):
                    return
                cab = {k: v for k, v in req.headers.items()
                       if k.lower() in CABECALHOS}
                if any(k.lower() == "authorization" for k in cab):
                    self._cabecalhos[host] = cab
            pagina.on("request", ao_requisitar)

        # Passar pela tela de Pagamentos faz o ERP autenticar nos serviços.
        # Espera até os cabeçalhos aparecerem em vez de dormir um tempo fixo:
        # normalmente chegam em 1 ou 2 segundos.
        pagina.goto(URL_PAGAMENTOS, wait_until="domcontentloaded")
        alvo = "prod-erp-api.maiscontroleerp.com.br"
        for _ in range(60):
            if alvo in self._cabecalhos:
                break
            pagina.wait_for_timeout(250)

        if alvo not in self._cabecalhos:
            raise RuntimeError(
                "não consegui a autenticação do serviço de cadastros. "
                "Abra uma vez, no Chrome, a tela de Novo Lançamento de "
                "Pagamentos e tente de novo.")

        self.catalogos = Catalogos(pagina, self._cabecalhos, self._log)
        self._log("Lendo os cadastros do Mais Controle:")
        self.catalogos.carregar()
        self.catalogos.carregar_obras()
        for motivo in getattr(self.catalogos, "erros_obras", []):
            self._log(f"  aviso (obras): {motivo}")

    def _recarregar_cadastros(self):
        """Relê contas.csv e os cadastros do ERP. Para quando algo foi criado
        no Mais Controle com o app já aberto."""
        self.entidades = cadastro.carregar_contas()
        self.subcontas = cadastro.carregar_subcontas()
        self.obra_padrao = cadastro.config_obra_padrao()
        self._recarregar_listas()
        self.catalogos = None
        self._log("Cadastros locais relidos; os do ERP serão relidos no "
                  "próximo comando.")

    def _conferir(self):
        self.anx.exec.submit(self._t_conferir)

    def _t_conferir(self):
        try:
            self._preparar_sessao()
            resultado = self.catalogos.conferir(self.entidades)
        except (RuntimeError, ErroLancamento) as e:
            self._log(f"[!] {e}")
            return
        self._log(f"\n{len(resultado['ok'])} de {len(self.entidades)} contas "
                  "existem no Mais Controle.")
        for item in resultado["faltando"]:
            self._log(f"  NAO ENCONTRADA: {item['nome']}")
            for p in item["problemas"]:
                self._log(f"     {p['o_que']}: \"{p['procurado']}\"")
                for parecido in p["parecidos"]:
                    self._log(f"        parecido no ERP: \"{parecido}\"")
        if not resultado["faltando"]:
            self._log("Nenhuma pendência de cadastro.")

    def _lancar(self):
        if not self.operacoes:
            messagebox.showinfo("Aportes", "A lista está vazia.")
            return
        n = sum(len(expandir(o, self.entidades, self.subcontas,
                             self.obra_padrao)) for o in self.operacoes)
        total = sum(o.valor for o in self.operacoes)
        # Confirmação explícita: daqui em diante escreve no sistema, e desfazer
        # significa apagar lançamento por lançamento na tela do ERP.
        if not messagebox.askyesno(
                "Confirmar",
                f"Criar {n} lançamento(s) no Mais Controle, "
                f"somando R$ {total:,.2f}?\n\nIsso escreve no sistema."):
            return
        self.b_lancar.configure(state="disabled")
        self.anx.exec.submit(self._t_lancar)

    def _t_lancar(self):
        try:
            self._preparar_sessao()
            id_usuario = self.catalogos.cabecalho("user-id")
            if not id_usuario:
                raise RuntimeError("não achei o usuário responsável.")

            # Só o que AINDA não entrou no ERP. Numa segunda tentativa depois
            # de falha parcial, repetir o que deu certo duplicaria o aporte.
            plano = []                      # (i_op, i_item, item)
            pulados = 0
            for i_op, op in enumerate(self.operacoes):
                for i_item, item in enumerate(
                        expandir(op, self.entidades, self.subcontas,
                                 self.obra_padrao)):
                    if i_item in self.criados[i_op]:
                        pulados += 1
                        continue
                    plano.append((i_op, i_item, item))

            if pulados:
                self._log(f"\n{pulados} lançamento(s) já criado(s) numa tentativa "
                          "anterior — pulados para não duplicar.")
            if not plano:
                self._log("Nada a criar: tudo desta lista já foi lançado.")
                self.after(0, self._retirar_concluidas)
                return

            self._log(f"\nCriando {len(plano)} lançamento(s):")
            feitos, falhas = 0, []
            for i, (i_op, i_item, item) in enumerate(plano, 1):
                especie = item.pop("tipo_lancamento")
                try:
                    if especie == "pagamento":
                        r = criar_pagamento(self.catalogos, id_usuario=id_usuario,
                                            **item)
                    else:
                        r = criar_recebimento(self.catalogos,
                                              id_usuario=id_usuario, **item)
                except ErroLancamento as e:
                    self._log(f"  {i}/{len(plano)} FALHOU: {e}")
                    falhas.append(str(e))
                    continue
                if r.ok:
                    feitos += 1
                    # Marca ANTES de qualquer outra coisa: se o app morrer aqui,
                    # o pior caso é a lista sobreviver sabendo o que já foi.
                    self.criados[i_op].add(i_item)
                    self._log(f"  {i}/{len(plano)} ok — {especie} "
                              f"R$ {item['valor']:,.2f}")
                else:
                    self._log(f"  {i}/{len(plano)} FALHOU: {r.erro}")
                    falhas.append(r.erro or "erro desconhecido")

            self._log(f"\n{feitos} criado(s), {len(falhas)} com problema.")
            self.after(0, self._retirar_concluidas)
        except RuntimeError as e:
            self._log(f"[!] {e}")
        finally:
            self.after(0, lambda: self.b_lancar.configure(state="normal"))
