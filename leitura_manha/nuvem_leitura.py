# -*- coding: utf-8 -*-
"""O lado da nuvem da leitura das 07:30 (migration 20261127100000_leitura_da_manha.sql).

Só LÊ `agendado_em_aberto` e só ACRESCENTA em `saldo_lido`, `extrato_lido`,
`pre_marca_banco` e `leitura_rodada`, com o usuário de papel `robo` (a RLS
recusa qualquer outro). Nunca escreve em `agendado_resposta`: pré-marcar não é
responder. O app não manda `quem`/`quando` (o banco carimba), mas manda o `dia`
(o hoje de São Paulo da rodada, não o do relógio do banco na hora do insert).
`leitura_rodada` vai POR ÚLTIMO: rodada sem ela é incompleta e o leitor a ignora.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from nuvem import rest

EM_ABERTO = "agendado_em_aberto"
SALDO, EXTRATO, PRE_MARCA = "saldo_lido", "extrato_lido", "pre_marca_banco"
RODADA = "leitura_rodada"
#: Teto padrão de linhas por leitura do PostgREST (max_rows do Supabase).
TETO_DE_LINHAS = 1000


class NaoGravou(rest.ErroDaNuvem):
    """O banco respondeu sem devolver as linhas pedidas."""


class LeituraCortada(rest.ErroDaNuvem):
    """A leitura bateu no teto do PostgREST: pode ter ficado agendado de fora."""


class GravacaoParcial(rest.ErroDaNuvem):
    """Uma gravação falhou DEPOIS de outra já ter entrado: a mensagem diz o que ficou."""

    def __init__(self, gravado: dict, tabela: str, causa: Exception):
        self.gravado = dict(gravado)
        ja = ", ".join(f"{t} {n}" for t, n in self.gravado.items())
        super().__init__(f"gravou {ja}; falhou {tabela}: {type(causa).__name__}: {str(causa)[:150]}")


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


def linhas_de_saldo(rodada: str, hoje, saldos) -> list[dict]:
    return [{"rodada": rodada, "dia": hoje.isoformat(), "conta": s.conta[:200], "fonte": s.fonte,
             "empresa": s.empresa[:200], "valor": _dinheiro(s.valor),
             "motivo": s.motivo[:200], "lido_em": s.hora.isoformat()} for s in saldos]


def linhas_de_extrato(rodada: str, hoje, extratos) -> list[dict]:
    def contagem(x, valor):   # extrato não lido nunca vira zero: vai NULL
        return valor if x.lido else None
    return [{"rodada": rodada, "dia": hoje.isoformat(), "conta": x.conta[:200], "fonte": x.fonte,
             "empresa": x.empresa[:200], "dia_extrato": x.dia.isoformat(), "lido": x.lido,
             "saidas": contagem(x, x.saidas), "entradas": contagem(x, x.entradas),
             "ilegiveis": contagem(x, x.ilegiveis), "fora_do_dia": contagem(x, x.fora_do_dia),
             "motivo": x.motivo[:200]} for x in extratos]


def linhas_de_pre_marca(rodada: str, hoje, ontem, marcas) -> list[dict]:
    return [{"rodada": rodada, "dia": hoje.isoformat(), "dia_extrato": ontem.isoformat(),
             "agendado_id": int(m.agendado_id),
             "conta": m.conta[:200], "prova": m.prova[:300], "nota": m.nota[:300]}
            for m in marcas]


def linha_da_rodada(rodada: str, hoje, ontem, contas: int, marcas_puladas: bool) -> dict:
    """O marcador: só é escrito quando as outras três entraram inteiras."""
    return {"rodada": rodada, "dia": hoje.isoformat(), "dia_extrato": ontem.isoformat(),
            "completa": True, "marcas_puladas": bool(marcas_puladas), "contas": int(contas)}


def gravar(token: str, rodada: str, hoje, ontem, saldos, extratos, marcas, *,
           marcas_puladas: bool = False) -> dict:
    """Grava as quatro, nesta ordem; devolve {tabela: linhas}. Linha a menos levanta
    NaoGravou; falha depois de algo gravado levanta GravacaoParcial (diz o que entrou).
    O marcador `leitura_rodada` vai por último: se algo antes falhou, ele não é
    gravado e a rodada fica incompleta (por ausência). `contas` = uma linha de
    extrato por conta do arquivo."""
    passos = ((SALDO, linhas_de_saldo(rodada, hoje, saldos)),
              (EXTRATO, linhas_de_extrato(rodada, hoje, extratos)),
              (PRE_MARCA, linhas_de_pre_marca(rodada, hoje, ontem, marcas)),
              (RODADA, [linha_da_rodada(rodada, hoje, ontem, len(extratos), marcas_puladas)]))
    feito: dict = {}
    for tabela, linhas in passos:
        try:
            feito[tabela] = _gravar(tabela, token, linhas)
        except Exception as e:  # noqa: BLE001 — qualquer tipo: o que entrou tem de aparecer
            if not feito:
                raise
            raise GravacaoParcial(feito, tabela, e) from e
    return feito
