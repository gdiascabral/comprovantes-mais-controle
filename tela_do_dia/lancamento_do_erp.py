# -*- coding: utf-8 -*-
"""O lançamento do ERP pelo link — só leitura, pela sessão do Chrome do app.

Usado pela conferência (`conferencia.nova_a_mao`) para não pagar mais que o em
aberto nem título já pago. Nada aqui escreve no ERP nem faz login por fora.

De onde vem cada peça (o detalhe `payable-installments/{id}` NÃO traz
fornecedor nem centro de custo — medido em 21/10/2026):
- fornecedor, centro de custo, conta, descrição e valor em aberto: o ITEM da
  lista de pagamentos (os `conhecidos` da leitura do dia ou, fora dela,
  `listar_a_pagar` na data prevista do detalhe);
- NF e OC: o item e o detalhe (`listar_overviews`: `documentNumber`,
  `purchaseOrder.number`);
- sem o item da lista: só o detalhe, com aviso; fornecedor e centro de custo
  ficam VAZIOS (o dono digita) e o em aberto sai de `pendingValue` ou de
  `plannedValue - sumOfPaidValues`; faltando os dois, `em_aberto=None`.
Nunca se chuta valor.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from pagamentos_dia import relatorio

from .valores import de_float

_NO_LINK = re.compile(r"payable-installments/([A-Za-z0-9-]{1,64})")
_CRU = re.compile(r"[A-Za-z0-9-]{1,64}")


def id_do_link(texto: str) -> str:
    """O id do lançamento, vindo do link da tela do ERP ou do id cru; "" se não for."""
    t = (texto or "").strip()
    m = _NO_LINK.search(t)
    if m:
        return m.group(1)
    return t if _CRU.fullmatch(t) else ""


@dataclass(frozen=True)
class LancamentoLido:
    id: str
    conta: str = ""
    favorecido: str = ""
    centro_custo: str = ""
    nf: str = ""
    oc: str = ""
    descricao: str = ""
    em_aberto: Decimal | None = None
    vencimento: date | None = None
    pago: bool = False
    avisos: tuple = ()


def _texto(valor) -> str:
    # `paidTo` veio `{}` no detalhe: só texto de verdade conta.
    return valor.strip() if isinstance(valor, str) else ""


def _em_aberto(item: dict) -> Decimal | None:
    if item.get("remainingValue") is not None:
        return de_float(item["remainingValue"])
    if item.get("pendingValue") is not None:
        return de_float(item["pendingValue"])
    if item.get("plannedValue") is not None and item.get("sumOfPaidValues") is not None:
        return de_float(item["plannedValue"]) - de_float(item["sumOfPaidValues"])
    return None


def do_item(item: dict, overview: dict | None, *, avisos=()) -> LancamentoLido:
    return LancamentoLido(
        id=str(item.get("id") or ""),
        conta=relatorio.nome_da_conta(item) if item.get("tradePayableAccount") else "",
        favorecido=_texto(item.get("paidTo")),
        centro_custo=relatorio.centro_de_custo(item),
        nf=relatorio.achar_doc(item, [], overview),
        oc=relatorio.achar_oc(item, [], "", overview),
        descricao=_texto(item.get("description")),
        em_aberto=_em_aberto(item),
        vencimento=relatorio.data_do_item(item),
        pago=bool(item.get("paid") or item.get("markedAsPaid")),
        avisos=tuple(avisos))


def ler(api, ident: str, conhecidos=(), *, log=print) -> LancamentoLido:
    """Lê o lançamento `ident`; `LookupError` se o ERP não o conhece."""
    if not ident:
        raise LookupError("sem o número do lançamento")
    if not getattr(api, "_req_pagos", None) and not api.capturar_credenciais(log):
        raise RuntimeError("A tela de Pagamentos não carregou no Chrome do app.")
    overview = (api.listar_overviews([ident], log=log) or {}).get(ident)
    item = next((i for i in conhecidos or () if str(i.get("id")) == ident), None)
    if item is not None:
        extra = () if overview else ("não li o detalhe do lançamento — a OC pode faltar",)
        return do_item(item, overview, avisos=extra)
    if overview is None:
        raise LookupError(f"não achei o lançamento {ident} no ERP")
    venc = relatorio.data_do_item(overview)
    if venc is not None:
        dia = f"{venc:%Y-%m-%d}"
        item = next((i for i in api.listar_a_pagar(dia, dia, log=log) or ()
                     if str(i.get("id")) == ident), None)
        if item is not None:
            return do_item(item, overview)
    return do_item({**overview, "id": ident}, overview,
                   avisos=("li só o detalhe do lançamento — confira fornecedor, conta e valor em aberto",))
