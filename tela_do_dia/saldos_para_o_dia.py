# -*- coding: utf-8 -*-
"""O saldo que a Prova de saldos leu vale para o Pagamentos do dia.

Pedido do dono (16/11/2026): "quando fizer a prova de saldo, grave e já deixe
salvo para o pagamentos do dia — adianta um processo". A Prova já faz o login
do Sicoob e lê o QR de cada Inter; o Pagamentos do dia pedia o login do
Sicoob de novo (Reler Sicoob) e o Inter era digitado.

Nada de arquivo novo: a Prova grava nos MESMOS arquivos do dia que já
existiam —

- Sicoob: `<pasta do dia>/DD MM - saldos do sicoob.json` (`saldo_sicoob`), o
  que o "Reler Sicoob" grava e o Buscar lê; havendo leitura de hoje, o Buscar
  não abre o Chrome do Sicoob.
- Inter: `<pasta do dia>/DD MM - saldos do inter.json` (`autenticar_inter`),
  o que o "Autenticar no banco" grava. O Pagamentos do dia passa a pôr esse
  saldo na coluna do banco das linhas do Inter (`aplicar_inter`).

**Leitura que falhou nunca apaga leitura boa** do mesmo dia: a conta que a
Prova não conseguiu ler fica com o saldo que já estava no arquivo (por
outra Prova ou pelo Reler Sicoob). A mais nova lida vence. O digitado na tela
(o ajuste) continua valendo sobre o lido, como sempre (`saldos.LinhaSaldo`).
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import replace
from decimal import Decimal, InvalidOperation
from pathlib import Path
from types import SimpleNamespace

from . import prova_saldos as ps
from . import saldo_sicoob as ss

#: De onde veio o saldo do Inter no arquivo do dia (o Autenticar grava "tela"
#: ou "extrato", que é por onde o `inter_saldo` leu).
VIA_PROVA = "prova de saldos"


# --------------------------------------------------------------- Sicoob
def juntar_sicoob(antes, lidos: dict, numeros: dict, data: _dt.date):
    """`LeituraSicoob` do dia com o que a Prova leu por cima do que já havia.

    `antes`: a leitura do arquivo (ou None); `lidos`: {dígitos: ps.Leitura}
    da Prova; `numeros`: {dígitos: número como o cadastro escreve}. A conta
    lida pela Prova troca o saldo; a que falhou só entra se o arquivo não
    tinha saldo dela (aí leva o porquê, como o Reler Sicoob faria)."""
    contas = dict(antes.contas) if antes is not None and antes.data == data else {}
    for dig, lido in lidos.items():
        numero = numeros.get(dig) or dig
        if (lido.saldo is not None and lido.lido_em is not None
                and lido.lido_em.date() == data):
            contas[dig] = ss.SaldoLido(numero, lido.saldo, lido.lido_em, "")
        elif contas.get(dig) is None or contas[dig].saldo is None:
            contas[dig] = ss.SaldoLido(numero, None, None, lido.motivo or ps.NAO_LIDO)
    return ss.LeituraSicoob(data, contas)


# ---------------------------------------------------------------- Inter
def inter_para_gravar(contas, inter: dict, data: _dt.date | None = None):
    """({chave: lido}, {chave: número}) no formato de
    `autenticar_inter.gravar_saldos` — só as contas do Inter lidas."""
    lidos, numeros = {}, {}
    for c in contas:
        if c.banco != ps.INTER or c.motivo or not c.apelido:
            continue
        chave = ps.chave_inter(c.apelido)
        lido = inter.get(chave)
        if lido is None or lido.saldo is None or lido.lido_em is None:
            continue
        if data is not None and lido.lido_em.date() != data:
            continue
        lidos[chave] = SimpleNamespace(saldo=lido.saldo, lido_em=lido.lido_em,
                                       imagem=lido.imagem, via=VIA_PROVA)
        numeros[chave] = c.numero
    return lidos, numeros


def ler_inter(arquivo, data: _dt.date) -> dict:
    """{chave do login: (saldo, lido_em, número conferido)} lidos HOJE; arquivo ausente, de
    outro dia ou estragado = {}. Estragado nunca vira saldo."""
    try:
        dados = json.loads(Path(arquivo).read_text(encoding="utf-8"))
        if not isinstance(dados, dict) or dados.get("data") != data.isoformat():
            return {}
        saida = {}
        for chave, c in (dados.get("contas") or {}).items():
            saldo = Decimal(str(c["saldo"]))
            lido_em = _dt.datetime.fromisoformat(c["lido_em"])
            if saldo.is_finite() and lido_em.date() == data:
                saida[str(chave)] = (saldo, lido_em, ps.digitos(c.get("numero") or "").lstrip("0"))
        return saida
    except (OSError, ValueError, KeyError, TypeError, AttributeError, InvalidOperation):
        return {}


#: Até quantos minutos o saldo do Inter lido vale na coluna do banco — a
#: mesma régua da Prova reaproveitando o Autenticar (revisão de dinheiro de
#: 16/11/2026): o saldo das 08:00 às 16:00, com débitos no meio, faria o
#: aporte mínimo sair baixo. Mais velho, a linha fica "banco não lido".
IDADE_MAXIMA_MIN = 120


def aplicar_inter(linhas, contas, lidos: dict, agora: _dt.datetime) -> list:
    """O saldo do Inter lido hoje na coluna do banco das linhas do Inter.

    `contas`: as `ContaDaProva` do painel (a mesma régua da Prova: linha →
    login); só entra conta sem motivo e com login. Linha que já tem banco
    lido (Sicoob) não é tocada; linha sem leitura fica como estava. Número
    da conta conferida diferente do da linha (os dois preenchidos) não entra;
    lido há mais de `IDADE_MAXIMA_MIN` vira nota, nunca saldo."""
    por_linha = {c.linha: c for c in contas
                 if c.banco == ps.INTER and not c.motivo and c.apelido}
    saida = []
    for ln in linhas:
        c = por_linha.get(ln.linha)
        lido = lidos.get(ps.chave_inter(c.apelido)) if c is not None else None
        if lido is None or ln.banco is not None:
            saida.append(ln)
            continue
        saldo, lido_em, numero = lido
        da_linha = ps.digitos(c.numero).lstrip("0")
        if numero and da_linha and numero != da_linha:
            saida.append(replace(ln, nota_banco=(
                f"Inter: o saldo lido é da conta {numero}, não da {da_linha} — digite")))
        elif (agora - lido_em).total_seconds() > IDADE_MAXIMA_MIN * 60:
            saida.append(replace(ln, nota_banco=(
                f"Inter lido às {lido_em:%H:%M}, há mais de {IDADE_MAXIMA_MIN // 60} h — "
                "rode a Prova de saldos de novo ou digite o saldo")))
        else:
            saida.append(replace(ln, banco=saldo, nota_banco=""))
    return saida


# ------------------------------------------------- a Prova grava, a tela lê
def guardar(raiz_saida, data: _dt.date, contas, sicoob: dict, inter: dict, log=print) -> None:
    """Chamado pela Prova depois de ler os bancos. Falha ao gravar só vai ao
    Registro: a Prova continua valendo, o Pagamentos do dia lê de novo."""
    from . import autenticar_inter as ai
    numeros = {ps.digitos(c.numero): c.numero for c in contas
               if c.banco == ps.SICOOB and c.numero and not c.motivo}
    do_sicoob = {d: l for d, l in sicoob.items() if d in numeros}
    # Prova que não leu conta nenhuma do Sicoob (Parar, login que estourou)
    # não grava: um arquivo só de "não lido" desligaria a leitura do Buscar.
    if any(l.saldo is not None for l in do_sicoob.values()):
        try:
            arq = ss.caminho(raiz_saida, data)
            antes = ss.ler(arq, data)[0]
            ss.gravar(juntar_sicoob(antes, do_sicoob, numeros, data), arq)
        except Exception as e:                               # noqa: BLE001
            log(f"[!] não consegui guardar o saldo do Sicoob para o Pagamentos do dia ({e})")
    lidos, nums = inter_para_gravar(contas, inter, data)
    if lidos:
        try:
            ai.gravar_saldos(lidos, ai.caminho_dos_saldos(raiz_saida, data), data, nums)
        except Exception as e:                               # noqa: BLE001
            log(f"[!] não consegui guardar o saldo do Inter para o Pagamentos do dia ({e})")


class InterNoDia:
    """O Inter do arquivo do dia na tela do Pagamentos do dia. O arquivo e o
    cadastro (linha → login) são relidos quando o Buscar traz outras contas
    ou quando o arquivo muda no disco (a Prova gravou depois)."""

    def __init__(self, log=print):
        self.log = log
        self._chave_contas = None
        self.contas = []
        self._arquivo = None             # (caminho, mtime)
        self.lidos = {}

    def aplicar(self, linhas, contas_erp, mapping, data: _dt.date):
        from conciliacao.frame import RAIZ_SAIDA

        from . import autenticar_inter as ai
        chave = self._chave_contas
        arq = ai.caminho_dos_saldos(RAIZ_SAIDA, data)
        try:
            marca = (str(arq), arq.stat().st_mtime_ns)
        except OSError:
            marca = (str(arq), None)
        # O cadastro (login → empresa) é relido também quando o arquivo muda:
        # um login trocado de empresa no meio do dia não leva o saldo junto.
        if (chave is None or chave[0] is not contas_erp or chave[1] is not mapping
                or marca != self._arquivo):
            self._chave_contas = (contas_erp, mapping)
            try:
                from baixar_comprovantes import contas_inter
                from pagamentos_dia import pagamentos_frame
                mapa_mc, empresas = pagamentos_frame._carregar_mapas()
                self.contas = [c for c in ps.contas_da_prova(
                    linhas, contas_erp, mapping, mapa_mc, empresas, contas_inter.carregar())
                    if c.banco == ps.INTER]
            except Exception as e:                           # noqa: BLE001
                self.contas = []
                self.log(f"[!] Inter: não consegui ler o cadastro de contas ({e}); "
                         "o saldo do banco fica digitado.")
        if marca != self._arquivo:
            self._arquivo = marca
            self.lidos = ler_inter(arq, data) if marca[1] is not None else {}
        return aplicar_inter(linhas, self.contas, self.lidos, _dt.datetime.now())
