# -*- coding: utf-8 -*-
"""Decide o que fazer com cada guia do mês. Não toca em rede.

Nenhuma decisão é tomada por valor: o valor da guia muda todo mês, e casar por
ele acertaria em fevereiro e erraria em março. O que casa é o
`trade_payable_id` que o dono confirmou uma vez e que a regra guardou.

Quando falta informação, a resposta é DECIDIR — nunca um palpite. Palpite aqui
vira parcela alterada na recorrência errada, e isso só se descobre no extrato.
"""
from __future__ import annotations

from collections import Counter
from decimal import Decimal

import util
from guias.modelos import ALTERAR, CRIAR, DECIDIR, JA_LANCADO, Decisao

log = util.log(__name__)


def _dec(valor) -> Decimal | None:
    if valor is None:
        return None
    try:
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    except Exception:
        return None


def _brl(valor) -> str:
    return f"{_dec(valor):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def parcela_da_recorrencia(parcelas: list[dict],
                           trade_payable_id: str) -> dict | None:
    for p in parcelas or []:
        if str(p.get("tradePayableId") or "") == str(trade_payable_id):
            return p
    return None


def titulo_igual(parcelas: list[dict], documento: str, valor,
                 vencimento) -> dict | None:
    """Título que já representa esta guia no mês. Primeiro pelo número do
    documento, que é o que identifica a guia; sem ele, por valor + vencimento.
    """
    doc = util.norm_espaco(str(documento or "")).upper()
    if doc:
        for p in parcelas or []:
            if util.norm_espaco(str(p.get("documentNumber") or "")).upper() == doc:
                return p
        return None
    alvo, data = _dec(valor), (vencimento.isoformat() if vencimento else "")
    if alvo is None or not data:
        return None
    for p in parcelas or []:
        if _dec(p.get("plannedValue")) == alvo and str(p.get("plannedDate") or "")[:10] == data:
            return p
    return None


def sugerir_obra(texto: str, obras) -> str:
    """O id da obra cujo nome aparece no texto do documento. `""` se não houver
    exatamente uma.

    Duas obras citadas no mesmo texto não viram escolha: escolher uma seria
    palpite, e obra errada leva junto a conta errada (a conta vem da obra).
    """
    alvo = util.sem_acento(str(texto or "")).upper()
    achadas = {str(o.get("id")) for o in (obras or [])
               if o.get("name")
               and util.sem_acento(str(o["name"])).upper() in alvo}
    return achadas.pop() if len(achadas) == 1 else ""


def decidir(guias, parcelas, regras, registro, competencia: str,
            obras=None) -> list[Decisao]:
    # Duas guias do mesmo tipo na mesma empresa apontariam para a mesma
    # recorrência: a segunda gravação apagaria a primeira. Contar ANTES.
    marcas = Counter()
    for guia in guias:
        tipo = regras.classificar(guia.desc)
        if tipo and tipo.get("acao") == "alterar":
            marcas[(guia.vip_id, tipo.get("nome"))] += 1

    return [_uma(g, parcelas, regras, registro, competencia, marcas, obras)
            for g in guias]


def _uma(guia, parcelas, regras, registro, competencia, marcas,
         obras=None) -> Decisao:
    if guia.erro:
        return Decisao(guia, DECIDIR, motivo=guia.erro)
    if guia.pdf is None:
        return Decisao(guia, DECIDIR, motivo="sem o PDF da guia")
    if guia.valor is None:
        return Decisao(guia, DECIDIR, motivo="não li o valor no PDF")

    feito = registro.ja_feito(guia.vip_id, guia.anx_id, competencia)
    if feito:
        return Decisao(guia, JA_LANCADO, motivo="esta rodada já lançou",
                       trade_payable_id=str(feito.get("tpid") or ""))

    tipo = regras.classificar(guia.desc)
    if tipo is None:
        return Decisao(guia, DECIDIR,
                       motivo=f"não conheço este documento: {guia.desc[:60]}")

    nome = str(tipo.get("nome") or "")
    categoria = str(tipo.get("categoria") or "")

    if tipo.get("acao") == "alterar":
        if marcas[(guia.vip_id, nome)] > 1:
            return Decisao(guia, DECIDIR, tipo=nome, categoria=categoria,
                           motivo="mais de uma guia deste tipo nesta empresa "
                                  "no mês: qual é a parcela da recorrência?")
        conhecida = regras.recorrencia(nome, guia.vip_id)
        tpid = str(conhecida.get("trade_payable_id") or "")
        if not tpid:
            return Decisao(guia, DECIDIR, tipo=nome, categoria=categoria,
                           motivo="ainda não sei qual é a recorrência desta "
                                  "empresa para este documento")
        parcela = parcela_da_recorrencia(parcelas, tpid)
        if parcela is None:
            return Decisao(guia, DECIDIR, tipo=nome, categoria=categoria,
                           motivo="a recorrência que eu conhecia não tem "
                                  "parcela neste mês")
        decisao = Decisao(guia, ALTERAR, tipo=nome, categoria=categoria,
                          obra_id=str(conhecida.get("obra") or ""),
                          trade_payable_id=tpid,
                          parcela_id=str(parcela.get("id") or ""))
        antes = _dec(parcela.get("plannedValue"))
        if antes is not None and antes != _dec(guia.valor):
            decisao.aviso = (f"a parcela está {_brl(antes)} e a guia diz "
                             f"{_brl(guia.valor)}; vale a guia")
        return decisao

    achado = titulo_igual(parcelas, guia.documento, guia.valor, guia.vencimento)
    if achado is not None:
        return Decisao(guia, JA_LANCADO, tipo=nome, categoria=categoria,
                       motivo="já existe título com este documento no mês",
                       trade_payable_id=str(achado.get("tradePayableId") or ""))

    # A regra é o que o dono já confirmou; a sugestão é palpite sobre o texto.
    # A regra ganha sempre, e o palpite viaja marcado como palpite.
    obra_id, sugerida = regras.obra(nome, guia.vip_id), False
    if not obra_id:
        obra_id = sugerir_obra(f"{guia.desc} {guia.documento}", obras)
        sugerida = bool(obra_id)
    if not obra_id:
        # Sem obra não há conta (a conta vem da obra), e sem conta não há
        # lançamento. Perguntar é a única saída honesta.
        return Decisao(guia, DECIDIR, tipo=nome, categoria=categoria,
                       motivo="não sei em que obra este documento entra")

    molde = str(tipo.get("descricao") or "{documento}")
    return Decisao(
        guia, CRIAR, tipo=nome, categoria=categoria,
        obra_id=obra_id, obra_sugerida=sugerida,
        favorecido=str(tipo.get("favorecido") or ""),
        descricao=molde.format(documento=guia.documento,
                               competencia=competencia, desc=guia.desc),
        parcelas=int(tipo.get("parcelas") or 1))
