# -*- coding: utf-8 -*-
"""Os diálogos finos da aba "Pagamentos do dia" (entrega 2).

Só perguntam e devolvem o que foi digitado: nenhuma regra mora aqui. Quem
valida é quem chama (`validar`, função pura de `tela_do_dia.passo2` /
`conferencia`), e o recado aparece DENTRO do diálogo, sem perder o que a
pessoa digitou. Todos usam `tela._janela` e `tela._rodape` do frame: modal,
filha da janela do app (o Enter global não busca de novo).
"""
from __future__ import annotations

import tkinter as tk
from decimal import Decimal
from tkinter import messagebox, ttk

import widgets

from . import conferencia as cf
from . import passo2
from .valores import brl

px = widgets.px


def _texto(corpo, texto):
    if texto:
        ttk.Label(corpo, text=texto, wraplength=px(460), justify="left").pack(anchor="w")


def _entrada(corpo, rotulo, var, largura=48):
    widgets.Campo(corpo, rotulo, lambda p: ttk.Entry(p, textvariable=var, width=largura)
                  ).pack(anchor="w", fill="x", pady=px((10, 0)))


def _lista(corpo, rotulo, var, valores, largura=46):
    widgets.Campo(corpo, rotulo, lambda p: ttk.Combobox(
        p, textvariable=var, values=list(valores), state="readonly", width=largura)
                  ).pack(anchor="w", pady=px((10, 0)))


def pedir_motivo(tela, titulo, explicacao, *, obrigatorio=True) -> str | None:
    """O motivo digitado ("" quando opcional e vazio), ou None (cancelou)."""
    jan, corpo = tela._janela(titulo)
    _texto(corpo, explicacao)
    v = tk.StringVar()
    _entrada(corpo, "Motivo" if obrigatorio else "Motivo (opcional)", v)
    resposta = {}

    def aplicar(_e=None):
        motivo = v.get().strip()
        erro = cf.validar_motivo(motivo) if (obrigatorio or motivo) else ""
        if erro:
            messagebox.showwarning(titulo, erro, parent=jan)
            return "break"
        resposta["v"] = motivo
        jan.destroy()
        return "break"

    tela._rodape(jan, corpo, (("Cancelar", "neutro", jan.destroy),
                              ("Confirmar", "acao", aplicar)), aplicar)
    return resposta.get("v")


def pedir_edicao(tela, iniciais: dict, *, explicacao="", validar=None) -> dict | None:
    """{"campos": o que está no formulário, "motivo", "corrigir_no_erp"} ou
    None. `validar(resposta) -> str` recusa sem fechar."""
    titulo = "Editar o pagamento"
    jan, corpo = tela._janela(titulo)
    _texto(corpo, explicacao)
    vs = {k: tk.StringVar(value=iniciais.get(k, "")) for k in passo2.CAMPOS_DO_DIALOGO}
    v_motivo, v_erp = tk.StringVar(), tk.BooleanVar(value=False)
    _lista(corpo, "Forma de pagar", vs["tipo"], ("", *cf.TIPOS), largura=20)
    _entrada(corpo, "Chave Pix, linha digitável ou conta", vs["dados"], 60)
    _entrada(corpo, "Reembolso: quem recebe (com a forma de pagar DELA acima)",
             vs["reembolso_nome"])
    _entrada(corpo, "Reembolso: CPF/CNPJ de quem recebe", vs["reembolso_documento"], 24)
    _entrada(corpo, "Descrição que vai ao banco", vs["descricao"], 60)
    _entrada(corpo, "Motivo", v_motivo)
    ttk.Checkbutton(corpo, text="Corrigir também no ERP (fica anotado na planilha)",
                    variable=v_erp).pack(anchor="w", pady=px((10, 0)))
    resposta = {}

    def aplicar(_e=None):
        r = {"campos": {k: v.get() for k, v in vs.items()}, "motivo": v_motivo.get().strip(),
             "corrigir_no_erp": bool(v_erp.get())}
        erro = validar(r) if validar else ""
        if erro:
            messagebox.showwarning(titulo, erro, parent=jan)
            return "break"
        resposta["v"] = r
        jan.destroy()
        return "break"

    tela._rodape(jan, corpo, (("Cancelar", "neutro", jan.destroy),
                              ("Gravar", "acao", aplicar)), aplicar)
    return resposta.get("v")


def pedir_a_mao(tela, contas: list[str], ler_link, *, validar=None) -> dict | None:
    """O pagamento à mão digitado, ou None. `ler_link(texto, ao_ler)` lê o
    lançamento FORA da thread da tela e chama `ao_ler(lido, erro)` de volta
    nela; `validar(resposta) -> str` recusa sem fechar."""
    titulo = "Pagamento à mão"
    jan, corpo = tela._janela(titulo)
    _texto(corpo, "Um pagamento que não está na lista do dia. Com o link do lançamento "
                  "do ERP, o valor não passa do em aberto e o Anexar casa o comprovante "
                  "depois. Ele sai no HTML, nunca na remessa do Sicoob.")
    v = {k: tk.StringVar() for k in ("conta", "link", "valor", "favorecido", "descricao",
                                     "tipo", "dados", "motivo")}
    _lista(corpo, "Conta", v["conta"], contas)
    linha_link = ttk.Frame(corpo)
    linha_link.pack(anchor="w", fill="x")
    _entrada(linha_link, "Link do lançamento no ERP (opcional)", v["link"], 60)
    lbl_lido = ttk.Label(corpo, style="Tenue.TLabel", text="", wraplength=px(460),
                         justify="left")
    lido = {"v": None}

    def ao_ler(resultado, erro):
        try:
            lido["v"] = resultado
            if resultado is None:
                lbl_lido.configure(text=erro or "Não li o lançamento.", style="Erro.TLabel")
                return
            partes = [resultado.favorecido, resultado.conta,
                      f"em aberto {resultado.em_aberto}" if resultado.em_aberto is not None
                      else "em aberto desconhecido", *resultado.avisos]
            lbl_lido.configure(text="Lido: " + " · ".join(p for p in partes if p),
                               style="Tenue.TLabel")
            for chave, valor in (("favorecido", resultado.favorecido),
                                 ("conta", resultado.conta if resultado.conta in contas else ""),
                                 ("descricao", resultado.descricao)):
                if valor and not v[chave].get().strip():
                    v[chave].set(valor)
        except tk.TclError:
            pass                         # o diálogo fechou antes da leitura voltar

    def ler():
        lido["v"] = None
        lbl_lido.configure(text="Lendo o lançamento...", style="Tenue.TLabel")
        ler_link(v["link"].get(), ao_ler)

    widgets.Botao(corpo, "Ler o lançamento", papel="neutro", command=ler
                  ).pack(anchor="w", pady=px((6, 0)))
    lbl_lido.pack(anchor="w", fill="x", pady=px((4, 0)))
    _entrada(corpo, "Valor R$", v["valor"], 18)
    _entrada(corpo, "Favorecido", v["favorecido"])
    _entrada(corpo, "Descrição", v["descricao"], 60)
    _lista(corpo, "Forma de pagar (opcional)", v["tipo"], ("", *cf.TIPOS), largura=20)
    _entrada(corpo, "Chave Pix, linha digitável ou conta (opcional)", v["dados"], 60)
    _entrada(corpo, "Motivo", v["motivo"])
    resposta = {}

    def aplicar(_e=None):
        r = {k: x.get() for k, x in v.items()}
        r["lido"] = lido["v"]
        erro = validar(r) if validar else ""
        if erro:
            messagebox.showwarning(titulo, erro, parent=jan)
            return "break"
        resposta["v"] = r
        jan.destroy()
        return "break"

    tela._rodape(jan, corpo, (("Cancelar", "neutro", jan.destroy),
                              ("Gravar", "acao", aplicar)), aplicar)
    return resposta.get("v")


def pedir_resposta(tela, titulo, *, com_data: bool):
    """(motivo, data ou None), ou None. A data (DD/MM/AAAA) só com `com_data`."""
    jan, corpo = tela._janela(titulo)
    v_motivo, v_data = tk.StringVar(), tk.StringVar()
    if com_data:
        _entrada(corpo, "Nova data (DD/MM/AAAA)", v_data, 14)
    _entrada(corpo, "Motivo", v_motivo)
    resposta = {}

    def aplicar(_e=None):
        motivo = v_motivo.get().strip()
        erro = cf.validar_motivo(motivo)
        data = None
        if not erro and com_data:
            try:
                data = passo2.ler_data(v_data.get())
            except ValueError as e:
                erro = str(e)
        if erro:
            messagebox.showwarning(titulo, erro, parent=jan)
            return "break"
        resposta["v"] = (motivo, data)
        jan.destroy()
        return "break"

    tela._rodape(jan, corpo, (("Cancelar", "neutro", jan.destroy),
                              ("Confirmar", "acao", aplicar)), aplicar)
    return resposta.get("v")


def pedir_nome_curto(tela, rotulo, atual) -> str | None:
    titulo = "Nome curto da conta"
    jan, corpo = tela._janela(titulo)
    _texto(corpo, f"Como {rotulo} aparece na lista do diretor.")
    v = tk.StringVar(value=atual or "")
    _entrada(corpo, "Nome curto", v, 30)
    resposta = {}

    def aplicar(_e=None):
        resposta["v"] = v.get().strip()
        jan.destroy()
        return "break"

    tela._rodape(jan, corpo, (("Cancelar", "neutro", jan.destroy),
                              ("Gravar", "acao", aplicar)), aplicar)
    return resposta.get("v")


def pedir_divisao(tela, linhas, socios, avisos, *, dividir, ler, validar) -> dict | None:
    """A janela "Dividir aporte entre os sócios": uma linha por aporte de
    fora na conta-mãe, um campo por sócio, já com a divisão do Controle de
    aportes. Devolve {destino: {sócio: parte}} ou None (cancelou: nada vai).

    `linhas`: [(destino, valor)]; `socios`: [(nome, peso)]; `dividir(valor)
    -> {sócio: parte}`, `ler(texto) -> Decimal` e `validar(valor, partes) ->
    str` são as regras de `aporte_dos_socios` — aqui não se decide nada."""
    titulo = "Dividir aporte entre os sócios"
    jan, corpo = tela._janela(titulo)
    _texto(corpo, "O aporte de fora na conta-mãe vai para a aba Aportes como Aporte de "
                  "Capital de cada sócio. A divisão já vem na proporção do Controle de "
                  "aportes; mude só se hoje foi diferente. Parte zero não vai. A soma de "
                  "cada linha tem de bater com o valor.")
    for aviso in avisos or ():
        ttk.Label(corpo, text=f"{widgets.MARCAS_ESTADO['atencao']} {aviso}",
                  style="Atencao.TLabel", wraplength=px(460), justify="left"
                  ).pack(anchor="w", pady=px((6, 0)))
    nomes = [n for n, _p in socios]
    campos = []
    for destino, valor in linhas:
        bloco = ttk.Frame(corpo)
        bloco.pack(fill="x", pady=px((12, 0)))
        ttk.Label(bloco, text=f"{destino} — {brl(valor)}",
                  style="Secao.TLabel").pack(anchor="w")
        inicial = dividir(valor)
        vs = {}
        for nome in nomes:
            v = tk.StringVar(value=brl(inicial.get(nome, Decimal("0.00"))))
            vs[nome] = v
            _entrada(bloco, nome, v, 20)
        situacao = ttk.Label(bloco, text="", style="Apoio.TLabel")
        situacao.pack(anchor="w", pady=px((4, 0)))
        campos.append((destino, valor, vs, situacao))
    resposta = {}

    def conferir() -> dict | None:
        saida, ok = {}, True
        for destino, valor, vs, situacao in campos:
            try:
                partes = {n: ler(v.get()) for n, v in vs.items()}
                erro = validar(valor, list(partes.values()))
            except ValueError as e:
                partes, erro = {}, f"valor inválido: {e}"
            situacao.configure(text=f"{widgets.MARCAS_ESTADO['erro']} {erro}" if erro
                               else f"{widgets.MARCAS_ESTADO['ok']} bate",
                               style="Erro.TLabel" if erro else "Apoio.TLabel")
            ok = ok and not erro
            saida[destino] = partes
        return saida if ok else None

    for _d, _v, vs, _s in campos:
        for v in vs.values():
            v.trace_add("write", lambda *_a: conferir())
    conferir()

    def aplicar(_e=None):
        saida = conferir()
        if saida is None:
            messagebox.showwarning(titulo, "Há linha cuja soma não bate com o valor — "
                                          "corrija antes de mandar.", parent=jan)
            return "break"
        resposta["v"] = saida
        jan.destroy()
        return "break"

    tela._rodape(jan, corpo, (("Cancelar", "neutro", jan.destroy),
                              ("Mandar", "acao", aplicar)), aplicar)
    return resposta.get("v")
