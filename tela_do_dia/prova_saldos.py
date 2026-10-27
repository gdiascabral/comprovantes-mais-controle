# -*- coding: utf-8 -*-
"""Prova de saldos (ERP × banco): a regra, sem tela, sem rede, sem navegador.

Quem lê é outro (`prova_erp`, `prova_sicoob`, `baixar_comprovantes.
inter_saldo`); quem desenha é `prova_pdf`; quem roda a thread é
`prova_na_tela`. Aqui só se decide: quais contas do painel entram, de que
banco é cada uma, e se o saldo do ERP e o do banco batem em CENTAVOS.

**Conta incerta não bate.** Falha de leitura, conta errada aberta no banco,
valor que não chegou: vira ⚠ com o motivo, nunca ✅ nem ❌. O número nunca
sai de dentro de uma imagem — o print é só prova (spec de 27/10/2026).

Qual conta do Sicoob é cada linha sai de `saldo_sicoob.contas_do_painel` (o
caminho do "Reler Sicoob" e da Remessa). Qual login do Inter é cada linha sai
do cadastro (`contas_mc` diz o banco e a empresa da conta do ERP) cruzado com
`contas_inter.json`: a empresa com UM login é lida; sem login ou com dois, a
linha entra como ⚠ e o banco não é aberto.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import util

from . import saldo_sicoob as ss
from .valores import brl

SICOOB = "SICOOB"
INTER = "INTER"
BATE, NAO_BATE, NAO_LIDA = "bate", "nao_bate", "nao_lida"
MARCA = {BATE: "✅", NAO_BATE: "❌", NAO_LIDA: "⚠"}
PALAVRA = {BATE: "bate", NAO_BATE: "não bate", NAO_LIDA: "não lida"}
CENTAVO = Decimal("0.01")
COLUNAS = ("CONTA", "SALDO ERP", "SALDO BANCO", "DIFERENÇA", "SITUAÇÃO",
           "HORA ERP", "HORA BANCO")
NAO_LIDO = "não lido"
INTERROMPIDA = "prova interrompida antes desta conta"
PARADO = "parado pelo botão Parar antes de terminar"
INTER_FORA_DA_LISTA = ("esta conta do Inter não está na lista do app "
                       "(contas_inter.json) — a prova não abre o banco")
INTER_DOIS_LOGINS = ("a empresa tem mais de uma conta do Inter na lista do "
                     "app — não sei qual login abrir")
INTER_REPETIDA = ("duas linhas do painel caem no mesmo login do Inter "
                  "({apelido}) — confira o cadastro de contas")


def digitos(texto) -> str:
    return re.sub(r"\D", "", str(texto or ""))


def chave_inter(apelido) -> str:
    return util.norm_espaco(apelido or "")


def e_inter(banco) -> bool:
    """"077", "77", "Inter", "BANCO INTER" — a régua de `anexar.origem._banco`."""
    t = util.norm_espaco(banco or "")
    return "INTER" in t or (bool(t) and t.lstrip("0") == "77")


@dataclass(frozen=True)
class ContaDaProva:
    linha: int
    rotulo: str
    banco: str                       # SICOOB | INTER
    #: Sicoob: como o cadastro escreve ("12.345-6"). Inter: os dígitos que o
    #: ERP tem da conta ("" = o ERP não diz; aí só o nome confere).
    numero: str = ""
    apelido: str = ""                # Inter: o login (contas_inter.json)
    nomes: tuple[str, ...] = ()      # Inter: nomes aceitos da empresa na tela
    #: Inter: razões sociais inteiras do cadastro — sem número no ERP, só
    #: uma delas, igual a uma linha da tela, confere a conta aberta.
    razoes: tuple[str, ...] = ()
    erp_id: str = ""                 # UUID da conta no ERP (linha da grade)
    motivo: str = ""                 # não dá para provar: ⚠ sem abrir o banco


@dataclass(frozen=True)
class Leitura:
    saldo: Decimal | None
    lido_em: datetime | None = None
    motivo: str = ""
    imagem: Path | None = None
    sem_imagem: str = ""             # por que não há print


@dataclass(frozen=True)
class LinhaDaProva:
    conta: ContaDaProva
    erp: Leitura
    banco: Leitura
    situacao: str
    diferenca: Decimal | None
    motivo: str


def conta_erp_da_linha(contas_erp, mapping) -> dict:
    """{linha do painel: ErpAccount}, pela MESMA régua do saldo do painel
    (`conciliacao.rules.resolve_balances`): ignoradas primeiro, a última
    conta que cai na linha vence."""
    saida = {}
    for conta in contas_erp or []:
        if mapping.is_ignored(conta.name):
            continue
        row = mapping.resolve_account(conta)
        if row is not None and row.exists_in_erp:
            saida[row.row] = conta
    return saida


def contas_da_prova(linhas, contas_erp, mapping, mapa_mc, empresas,
                    contas_inter) -> list[ContaDaProva]:
    """As contas Sicoob e Inter do painel, na ordem das linhas. Conta de
    outro banco não entra (spec: "Contas fora do escopo")."""
    da_linha = conta_erp_da_linha(contas_erp, mapping)
    linhas = list(linhas)
    # Pela POSIÇÃO (uma `ContaDoPainel` por linha, na ordem dada) e nunca pelo
    # rótulo: dois rótulos iguais no painel trocariam os números do Sicoob.
    do_sicoob = {ln.linha: c for ln, c in zip(linhas, ss.contas_do_painel(
        linhas, contas_erp, mapping, mapa_mc, empresas), strict=True)}
    saida: list[ContaDaProva] = []
    for ln in sorted(linhas, key=lambda x: x.linha):
        erp = da_linha.get(ln.linha)
        erp_id = str(getattr(erp, "id", "") or "")
        sic = do_sicoob.get(ln.linha)
        if sic is not None and sic.do_sicoob:
            saida.append(ContaDaProva(
                ln.linha, ln.rotulo, SICOOB, numero=sic.numero, erp_id=erp_id,
                motivo=(ss.PREFIXO + sic.motivo) if sic.motivo else ""))
            continue
        row = mapping.by_row(ln.linha)
        nome = (getattr(erp, "name", "") or (row.erp_name if row else "")
                or ln.rotulo)
        destino = mapa_mc.de(nome) if mapa_mc is not None else None
        if destino is None or not e_inter(destino.banco):
            continue
        numero = digitos(getattr(erp, "account_number", "")
                         or (row.account_number if row else ""))
        empresa = util.norm_espaco(destino.empresa)
        logins = [c for c in contas_inter or []
                  if util.norm_espaco(c.empresa) == empresa]
        apelido, motivo = "", ""
        if not logins:
            motivo = INTER_FORA_DA_LISTA
        elif len(logins) > 1:
            motivo = INTER_DOIS_LOGINS
        else:
            apelido = logins[0].apelido
        razoes = [getattr(e, "razao_social", "") for e in empresas or []
                  if util.norm_espaco(getattr(e, "nome", "")) == empresa]
        candidatos = [destino.empresa, *(c.empresa for c in logins[:1]), *razoes]
        nomes = tuple(dict.fromkeys(n for n in candidatos if (n or "").strip()))
        inteiras = tuple(dict.fromkeys(r for r in razoes if (r or "").strip()))
        saida.append(ContaDaProva(ln.linha, ln.rotulo, INTER, numero=numero,
                                  apelido=apelido, nomes=nomes, razoes=inteiras,
                                  erp_id=erp_id, motivo=motivo))
    vezes = Counter(chave_inter(c.apelido) for c in saida
                    if c.banco == INTER and c.apelido and not c.motivo)
    return [replace(c, motivo=INTER_REPETIDA.format(apelido=c.apelido))
            if c.banco == INTER and c.apelido and not c.motivo
            and vezes[chave_inter(c.apelido)] > 1 else c
            for c in saida]


def banco_por_linha(contas, sicoob: dict, inter: dict) -> dict:
    """{linha: Leitura do banco}. Sicoob por `digitos(numero)`, Inter por
    `chave_inter(apelido)`. Conta com motivo não tem leitura."""
    saida = {}
    for c in contas:
        if c.motivo:
            continue
        lida = (sicoob.get(digitos(c.numero)) if c.banco == SICOOB
                else inter.get(chave_inter(c.apelido)))
        if lida is not None:
            saida[c.linha] = lida
    return saida


def _centavos(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def comparar(conta: ContaDaProva, erp: Leitura, banco: Leitura) -> LinhaDaProva:
    if conta.motivo:
        return LinhaDaProva(conta, erp, banco, NAO_LIDA, None, conta.motivo)
    if erp.saldo is None:
        return LinhaDaProva(conta, erp, banco, NAO_LIDA, None,
                            f"ERP: {erp.motivo or NAO_LIDO}")
    if banco.saldo is None:
        return LinhaDaProva(conta, erp, banco, NAO_LIDA, None,
                            f"banco: {banco.motivo or NAO_LIDO}")
    dif = _centavos(banco.saldo) - _centavos(erp.saldo)
    if dif == 0:
        return LinhaDaProva(conta, erp, banco, BATE, dif, "")
    return LinhaDaProva(conta, erp, banco, NAO_BATE, dif, f"diferença de {brl(dif)}")


def montar(contas, erp: dict, banco: dict) -> list[LinhaDaProva]:
    vazia = Leitura(None, motivo=NAO_LIDO)
    return [comparar(c, erp.get(c.linha, vazia), banco.get(c.linha, vazia))
            for c in sorted(contas, key=lambda c: c.linha)]


def contagem(linhas) -> dict:
    n = {BATE: 0, NAO_BATE: 0, NAO_LIDA: 0}
    for linha in linhas:
        n[linha.situacao] += 1
    return n


def texto_da_contagem(linhas) -> str:
    n = contagem(linhas)
    return f"{n[BATE]} batem, {n[NAO_BATE]} não batem, {n[NAO_LIDA]} não lidas"


def hora(leitura: Leitura) -> str:
    return f"{leitura.lido_em:%H:%M}" if leitura.lido_em is not None else "—"


def celulas(linha: LinhaDaProva, com_marca: bool = True) -> tuple:
    palavra = PALAVRA[linha.situacao]
    situacao = f"{MARCA[linha.situacao]} {palavra}" if com_marca else palavra
    return (linha.conta.rotulo, brl(linha.erp.saldo), brl(linha.banco.saldo),
            brl(linha.diferenca), situacao, hora(linha.erp), hora(linha.banco))


def texto_do_registro(linha: LinhaDaProva) -> str:
    texto = (f"  {MARCA[linha.situacao]} {linha.conta.rotulo}: ERP "
             f"{brl(linha.erp.saldo)} · banco {brl(linha.banco.saldo)}")
    return texto + (f" — {linha.motivo}" if linha.motivo else "")


def nome_base(agora: datetime) -> str:
    return f"Prova de saldos {agora:%Y-%m-%d %Hh%M}"


def nome_do_print(linha: int, lado: str) -> str:
    return f"{linha:02d} {lado}.png"
