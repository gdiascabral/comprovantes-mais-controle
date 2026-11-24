# -*- coding: utf-8 -*-
"""Qual parcela do título a linha paga (spec de 19/11/2026, parte 2).

A lista de a pagar traz o total de parcelas (`numberOfFinancingInstallments`)
e não o número. O número sai do título inteiro (`trade-payables/<id>`, lido
por `leitura_do_dia.ler_titulos_no_erp`), pela posição da parcela em
`installments`. Medido em 19/11/2026: cerca de 2% dos lançamentos de seis
meses são de título com mais de uma parcela.

Formato de `installments` medido na Tarefa 1 do plano de 19/11/2026:
medido em 20/11/2026 nas respostas de `trade-payables/<id>` guardadas
em backups de 30/10 a 16/11 (o Chrome do app não deixou a sonda ao vivo
conectar, com uma aba do ERP travada): (1) o `id` de cada item de
`installments` é o mesmo `id` do lançamento na lista de a pagar (5 de 5
títulos conferidos contra as listas); (2) a ordem vem em `order`,
começando em 0; (3) cada parcela traz também `plannedDate` e `comment`.
Nenhum dos backups era de título com mais de uma parcela: a ordem entre
parcelas ainda não foi vista ao vivo, e por isso a data fica de reserva.

Falha fechada: título que não leu ou parcela que não se acha fica com
`numero` None, e `nivel.nivel_da_linha` põe a linha em "Não li".
"""
from __future__ import annotations

from . import relatorio

#: Campo de ordem da parcela no título, na ordem em que se tenta. Sem nenhum,
#: vale a data. Conferido na Tarefa 1 (o medido vai primeiro).
CAMPOS_DE_ORDEM = ("order", "installmentOrder", "number")


def total_do_item(item: dict) -> int:
    try:
        return int((item or {}).get("numberOfFinancingInstallments") or 0)
    except (TypeError, ValueError):
        return 0


def titulos_parcelados(itens) -> list[str]:
    return sorted({str(i.get("tradePayableId")) for i in itens or ()
                   if i.get("tradePayableId") and total_do_item(i) > 1})


def _ordem(p: dict):
    for campo in CAMPOS_DE_ORDEM:
        v = p.get(campo)
        if isinstance(v, int) or (isinstance(v, str) and v.isdigit()):
            return (0, int(v), "")
    return (1, 0, str(p.get("plannedDate") or p.get("dueDate") or ""))


def posicao(titulo, id_parcela) -> int | None:
    lista = [p for p in ((titulo or {}).get("installments") or []) if isinstance(p, dict)]
    for k, p in enumerate(sorted(lista, key=_ordem), 1):
        if str(p.get("id")) == str(id_parcela):
            return k
    return None


def anotar(resultado, selecionados, parcelas_erp, overviews):
    """Põe `parcela` (só título de mais de uma) e `obs_parcela` (o comentário
    do detalhe da parcela) nos registros, pelo id do lançamento. Linha
    dividida em N boletos (`parte`) é do mesmo lançamento: herda o que o
    lançamento tem, e um título de uma parcela não vira "parcela k de N"."""
    por_id = {str(i.get("id")): i for i in selecionados or () if i.get("id")}
    for regs in (getattr(resultado, "contas", None) or {}).values():
        for r in regs:
            item = por_id.get(str(r.get("id") or "").split("#")[0])
            if item is None:
                continue
            obs = relatorio.observacao_relevante(
                relatorio.comentario_do((overviews or {}).get(str(item.get("id")))),
                r.get("linha_da_guia") or r.get("dados") or "")
            if obs:
                r["obs_parcela"] = obs
            total = total_do_item(item)
            if total > 1:
                titulo = (parcelas_erp or {}).get(str(item.get("tradePayableId")))
                r["parcela"] = {"numero": posicao(titulo, item.get("id")) if titulo else None,
                                "total": total}
    return resultado
