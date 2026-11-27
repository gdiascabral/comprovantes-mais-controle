# -*- coding: utf-8 -*-
"""O lado da nuvem da leitura das 07:30 (migration 20261127100000_leitura_da_manha.sql).

Só LÊ `agendado_em_aberto` e só ACRESCENTA em `saldo_lido`, `extrato_lido` e
`pre_marca_banco`, com o usuário de papel `robo` (a RLS recusa qualquer outro).
Nunca escreve em `agendado_resposta`: pré-marcar não é responder.
O app não manda `quem`/`quando`: o banco carimba.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from nuvem import rest

EM_ABERTO = "agendado_em_aberto"
SALDO, EXTRATO, PRE_MARCA = "saldo_lido", "extrato_lido", "pre_marca_banco"
#: Teto padrão de linhas por leitura do PostgREST (max_rows do Supabase).
TETO_DE_LINHAS = 1000


class NaoGravou(rest.ErroDaNuvem):
    """O banco respondeu sem devolver as linhas pedidas."""


class LeituraCortada(rest.ErroDaNuvem):
    """A leitura bateu no teto do PostgREST: pode ter ficado agendado de fora."""


def em_aberto(token: str) -> list[dict]:
    linhas = rest.ler(EM_ABERTO, token, filtro="order=dia.asc,id.asc")
    if len(linhas) >= TETO_DE_LINHAS:
        raise LeituraCortada(f"{EM_ABERTO}: {len(linhas)} linhas, pode ter cortado")
    return linhas


def _dinheiro(v: Decimal | None) -> str | None:
    if v is None:
        return None
    if not isinstance(v, Decimal):
        raise TypeError(f"dinheiro em {type(v).__name__}: use Decimal")
    return str(v.quantize(Decimal("0.01"), ROUND_HALF_UP))


def _gravar(tabela: str, token: str, linhas: list[dict]) -> int:
    if not linhas:
        return 0
    gravadas = rest.inserir(tabela, token, linhas) or []
    if len(gravadas) != len(linhas):
        raise NaoGravou(f"{tabela}: o banco devolveu {len(gravadas)} de {len(linhas)} linha(s)")
    return len(gravadas)


def linhas_de_saldo(rodada: str, saldos) -> list[dict]:
    return [{"rodada": rodada, "conta": s.conta[:200], "fonte": s.fonte,
             "empresa": s.empresa[:200], "valor": _dinheiro(s.valor),
             "motivo": s.motivo[:200], "lido_em": s.hora.isoformat()} for s in saldos]


def linhas_de_extrato(rodada: str, extratos) -> list[dict]:
    return [{"rodada": rodada, "conta": x.conta[:200], "fonte": x.fonte,
             "empresa": x.empresa[:200], "dia_extrato": x.dia.isoformat(),
             "saidas": x.saidas, "entradas": x.entradas, "ilegiveis": x.ilegiveis,
             "fora_do_dia": x.fora_do_dia, "motivo": x.motivo[:200]} for x in extratos]


def linhas_de_pre_marca(rodada: str, ontem, marcas) -> list[dict]:
    return [{"rodada": rodada, "dia_extrato": ontem.isoformat(), "agendado_id": int(m.agendado_id),
             "conta": m.conta[:200], "prova": m.prova[:300], "nota": m.nota[:300]}
            for m in marcas]


def gravar(token: str, rodada: str, ontem, saldos, extratos, marcas) -> dict:
    """Grava as três; devolve {tabela: linhas}. Linha a menos levanta NaoGravou."""
    return {SALDO: _gravar(SALDO, token, linhas_de_saldo(rodada, saldos)),
            EXTRATO: _gravar(EXTRATO, token, linhas_de_extrato(rodada, extratos)),
            PRE_MARCA: _gravar(PRE_MARCA, token, linhas_de_pre_marca(rodada, ontem, marcas))}
