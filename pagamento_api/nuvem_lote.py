# -*- coding: utf-8 -*-
"""O lado do robô na nuvem: ler o lote aprovado de hoje, anotar cada passo,
o pulso e o botão Parar. Migration `20261126100000_pagamento_pela_api.sql`.

O robô entra com o usuário próprio dele (papel `robo`), nunca com a chave de
serviço: a RLS só o deixa LER e acrescentar evento e pulso.
Gravar evento sem a linha voltar levanta `NaoGravou` — o INICIADO é gravado
antes de pagar, e "gravado" sem ter gravado é o pagamento em dobro da retomada.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from nuvem import rest

from . import executor as ex
from . import lote as lt


class NaoGravou(rest.ErroDaNuvem):
    """O banco respondeu sem devolver a linha do evento."""


@dataclass(frozen=True)
class LoteAprovado:
    id: int
    total: Decimal
    itens: list[lt.ItemLote]


def item_da_linha(r: dict) -> lt.ItemLote:
    return lt.ItemLote(int(r["ordem"]), str(r["titulo"]), str(r["alvo"]), str(r["conta"]),
                       str(r["tipo"]), str(r["dados"]), Decimal(str(r["valor"])),
                       str(r.get("favorecido") or ""), str(r.get("documento_esperado") or ""),
                       str(r.get("descricao") or ""))


def lotes_aprovados(token: str, hoje: date) -> list[LoteAprovado]:
    lotes = rest.ler("lote_pagamento", token, colunas="id", filtro=f"dia=eq.{hoje.isoformat()}")
    ids = [int(l["id"]) for l in lotes]
    if not ids:
        return []
    lista = ",".join(map(str, ids))
    aprov = rest.ler("lote_aprovacao", token, colunas="lote,itens,total",
                     filtro=f"lote=in.({lista})&order=lote.asc")
    saida = []
    for a in aprov:
        ordens = sorted(int(o) for o in a["itens"])
        linhas = rest.ler("lote_item", token, filtro=(
            f"lote=eq.{int(a['lote'])}&ordem=in.({','.join(map(str, ordens))})&order=ordem.asc"))
        itens = [item_da_linha(r) for r in linhas]
        if [i.ordem for i in itens] != ordens:
            continue                     # leitura incompleta: não paga nada deste lote
        total = Decimal(str(a["total"]))
        if lt.total(itens) != total:
            continue
        saida.append(LoteAprovado(int(a["lote"]), total, itens))
    return saida


class LivroNaNuvem:
    def __init__(self, token: str, lote_id: int):
        self.token, self.lote = token, int(lote_id)

    def eventos(self) -> list[ex.Evento]:
        linhas = rest.ler("lote_evento", self.token, colunas="ordem,estado,detalhe,chave",
                          filtro=f"lote=eq.{self.lote}&order=id.asc")
        return [ex.Evento(int(r["ordem"]), str(r["estado"]), str(r.get("detalhe") or ""),
                          str(r.get("chave") or "")) for r in linhas]

    def gravar(self, e: ex.Evento) -> None:
        voltou = rest.inserir("lote_evento", self.token, [{
            "lote": self.lote, "ordem": e.ordem, "estado": e.estado,
            "detalhe": e.detalhe, "chave": e.chave}])
        if not voltou:
            raise NaoGravou(f"evento {e.estado} do item {e.ordem} não voltou do banco")


def parado(token: str) -> bool:
    """O último botão apertado vale. Sem nenhum: não está parado."""
    u = rest.ler("robo_parar", token, colunas="acao", filtro="order=id.desc&limit=1")
    return bool(u) and u[0].get("acao") == "parar"


def pulso(token: str) -> None:
    rest.inserir("robo_pulso", token, [{}], devolver=False)
