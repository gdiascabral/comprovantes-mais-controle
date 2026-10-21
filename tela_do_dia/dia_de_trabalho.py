# -*- coding: utf-8 -*-
"""O "dia de trabalho" da tela: ajustes de saldo, valores por aportador e o que
já foi mandado para a aba Aportes. Um JSON por dia, ao lado do Excel do dia.

Entrega 1 sem SQL de propósito (a nuvem é a entrega 2). Arquivo ilegível, ou
de OUTRA data, LEVANTA ValueError: a tela então deixa de gravar, porque
sobrescrever com o dia vazio apagaria os ajustes que a pessoa fez e não vê
mais. Só arquivo ausente vira dia vazio.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import util

from .saldos import BANCO, SISTEMA, Ajuste

VERSAO = 1


@dataclass
class DiaDeTrabalho:
    data: date
    ajustes: dict = field(default_factory=dict)
    aportes: dict = field(default_factory=dict)
    #: O que já foi mandado para a aba Aportes hoje: "destino|aportador"
    #: (`para_aportes.chave_de_envio`) -> o VALOR mandado, em Decimal.
    enviados_aportes: dict = field(default_factory=dict)


def pasta_do_dia(raiz_saida, data: date) -> Path:
    return Path(raiz_saida) / str(data.year) / util.MESES_PASTA[data.month - 1]


def nome_do_arquivo(data: date) -> str:
    return f"{data:%d %m} - dia de trabalho.json"


def caminho_do_dia(raiz_saida, data: date) -> Path:
    return pasta_do_dia(raiz_saida, data) / nome_do_arquivo(data)


def _dec(v):
    return None if v is None else str(v)


def para_dict(dia: DiaDeTrabalho) -> dict:
    return {
        "versao": VERSAO,
        "data": dia.data.isoformat(),
        "ajustes": [{"conta": conta, "campo": campo, "valor": str(a.valor),
                     "original": _dec(a.original), "motivo": a.motivo, "quando": a.quando}
                    for conta, campos in sorted(dia.ajustes.items())
                    for campo, a in sorted(campos.items())],
        "aportes": [{"destino": d, "aportador": ap, "valor": str(v)}
                    for (d, ap), v in sorted(dia.aportes.items())],
        "enviados_aportes": {k: str(v) for k, v in sorted(dia.enviados_aportes.items())},
    }


def de_dict(dados: dict, data: date) -> DiaDeTrabalho:
    dia = DiaDeTrabalho(data)
    try:
        for a in dados.get("ajustes") or []:
            if a["campo"] not in (SISTEMA, BANCO):
                raise ValueError(f"campo {a['campo']!r}")
            dia.ajustes.setdefault(a["conta"], {})[a["campo"]] = Ajuste(
                valor=Decimal(a["valor"]),
                original=None if a.get("original") is None else Decimal(a["original"]),
                motivo=a.get("motivo") or "", quando=a.get("quando") or "")
        for item in dados.get("aportes") or []:
            dia.aportes[(item["destino"], item["aportador"])] = Decimal(item["valor"])
        dia.enviados_aportes = {str(k): Decimal(str(v))
                                for k, v in (dados.get("enviados_aportes") or {}).items()}
        if not all(v.is_finite() and v > 0 for v in dia.enviados_aportes.values()):
            raise ValueError("valor mandado que não é número maior que zero")
    except (KeyError, TypeError, AttributeError, InvalidOperation) as e:
        raise ValueError(f"formato inesperado ({e!r})") from e
    return dia


def ler(caminho, data: date) -> DiaDeTrabalho:
    """Arquivo ausente = dia vazio. Ilegível ou de outra data = ValueError."""
    p = Path(caminho)
    if not p.is_file():
        return DiaDeTrabalho(data)
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(dados, dict):
            raise ValueError("o conteúdo não é um objeto")
        if str(dados.get("data")) != data.isoformat():
            raise ValueError(f"arquivo do dia é de {dados.get('data')}, "
                             f"não de {data.isoformat()}")
        return de_dict(dados, data)
    except (OSError, ValueError) as e:
        raise ValueError(f"não consegui ler {p.as_posix()}: {e}") from e


def gravar(dia: DiaDeTrabalho, caminho) -> Path:
    p = Path(caminho)
    p.parent.mkdir(parents=True, exist_ok=True)
    temporario = p.with_name(p.name + ".tmp")
    temporario.write_text(json.dumps(para_dict(dia), ensure_ascii=False, indent=2),
                          encoding="utf-8")
    os.replace(temporario, p)
    return p
