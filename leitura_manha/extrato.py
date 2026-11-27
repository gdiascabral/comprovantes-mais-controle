# -*- coding: utf-8 -*-
"""O número que o banco devolveu, lido sem adivinhar. Sem rede.

Regra: o que não se lê com certeza fica FORA e é contado — nunca vira zero,
nunca vira um valor parecido. Saldo ilegível = "não lido" (None + motivo).
Linha de extrato ilegível = contada em `ilegiveis`; a conta com qualquer linha
ilegível não entra no casamento (`leitura.py`), porque a linha que faltou pode
ser justamente a que decide.

A CONFIRMAR com o 1º extrato real do Sicoob (o Sandbox devolve lorem ipsum em
todos os campos do extrato, medido em 27/11/2026): o texto do `tipo`, o formato
do `valor` (sinal, separador) e o da `data`. Até lá, só entram as formas
abaixo, e o resto cai em `ilegiveis`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from tela_do_dia.autenticar import Movimento, data_do_banco

CENTAVO = Decimal("0.01")
#: Formas aceitas de valor em TEXTO: "1234.56", "1234,56", "1.234,56", "150".
_PONTO = re.compile(r"^\d+(\.\d{1,2})?$")
_VIRGULA = re.compile(r"^(\d{1,3}(\.\d{3})+|\d+),\d{2}$")
SAIDA, ENTRADA = "saida", "entrada"
_TIPOS = {"D": SAIDA, "DEBITO": SAIDA, "DÉBITO": SAIDA,
          "C": ENTRADA, "CREDITO": ENTRADA, "CRÉDITO": ENTRADA}
#: Quantos motivos de linha ilegível vão para a nuvem (o resto só conta).
MOTIVOS_GUARDADOS = 3


class ExtratoIlegivel(ValueError):
    """O extrato inteiro não tem a forma esperada (sem a lista de transações)."""


def _quantizar(d: Decimal) -> Decimal | None:
    """Duas casas, ou None quando o número não cabe no contexto do Decimal
    (1e40 levanta InvalidOperation): para o extrato, é o mesmo ilegível."""
    try:
        return d.quantize(CENTAVO)
    except ArithmeticError:
        return None


def centavos(v) -> Decimal | None:
    """Número JSON (já em Decimal ou int) com até 2 casas, ou None.
    bool, float, texto e número com mais de 2 casas não são dinheiro."""
    if isinstance(v, bool) or not isinstance(v, (int, Decimal)):
        return None
    d = Decimal(v)
    if not d.is_finite():
        return None
    q = _quantizar(d)
    if q is None or d != q:
        return None
    return q


def valor_texto(t) -> Decimal | None:
    """Valor em texto, SEM sinal, numa das formas de `_PONTO`/`_VIRGULA`; senão None."""
    if isinstance(t, (int, Decimal)) and not isinstance(t, bool):
        return centavos(t)
    if not isinstance(t, str):
        return None
    s = t.strip()
    if _PONTO.match(s):
        return _quantizar(Decimal(s))
    if _VIRGULA.match(s):
        return _quantizar(Decimal(s.replace(".", "").replace(",", ".")))
    return None


def _saldo(corpo, campo: str, banco: str) -> tuple[Decimal | None, str]:
    bruto = (corpo or {}).get(campo)
    v = centavos(bruto)
    if v is None:
        return None, f"{banco}: saldo fora do formato ({campo}={str(bruto)[:30]!r})"
    return v, ""


def saldo_sicoob(corpo: dict) -> tuple[Decimal | None, str]:
    """`saldo` do GET /saldo (número). `saldoLimite` não é dinheiro da conta."""
    return _saldo(corpo, "saldo", "Sicoob")


def saldo_inter(corpo: dict) -> tuple[Decimal | None, str]:
    """`disponivel` do GET /banking/v2/saldo (número)."""
    return _saldo(corpo, "disponivel", "Inter")


@dataclass(frozen=True)
class Extrato:
    movimentos: tuple          # só as SAÍDAS do dia, como `autenticar.Movimento`
    entradas: int
    ilegiveis: int
    fora_do_dia: int
    motivos: tuple = ()        # até MOTIVOS_GUARDADOS, para a nuvem


def _transacoes(corpo) -> list:
    lista = (corpo or {}).get("transacoes") if isinstance(corpo, dict) else None
    if not isinstance(lista, list):
        raise ExtratoIlegivel("extrato sem a lista 'transacoes'")
    return lista


def _ler(lista, dia: date, linha_para) -> Extrato:
    """`linha_para(t)` -> (SAIDA|ENTRADA, Movimento), ou levanta ValueError(motivo)."""
    movs, entradas, ilegiveis, fora, motivos = [], 0, 0, 0, []
    for t in lista:
        try:
            tipo, mov = linha_para(t)
        except ValueError as e:
            ilegiveis += 1
            if len(motivos) < MOTIVOS_GUARDADOS:
                motivos.append(str(e)[:80])
            continue
        if mov.data != dia:
            fora += 1
        elif tipo == ENTRADA:
            entradas += 1
        else:
            movs.append(mov)
    return Extrato(tuple(movs), entradas, ilegiveis, fora, tuple(motivos))


def _comum(t, campo_tipo: str, campo_data: str):
    if not isinstance(t, dict):
        raise ValueError("linha não é objeto")
    bruto = str(t.get(campo_tipo) or "").strip().upper()
    tipo = _TIPOS.get(bruto)
    if tipo is None:
        raise ValueError(f"{campo_tipo} desconhecido {bruto[:20]!r}")
    valor = valor_texto(t.get("valor"))
    if valor is None or valor <= 0:
        raise ValueError(f"valor ilegível {str(t.get('valor'))[:20]!r}")
    dia = data_do_banco(t.get(campo_data)) if isinstance(t.get(campo_data), str) else None
    if dia is None:
        raise ValueError(f"{campo_data} ilegível {str(t.get(campo_data))[:20]!r}")
    return tipo, valor, dia


def movimentos_sicoob(corpo: dict, conta_erp: str, dia: date) -> Extrato:
    """GET /extrato do Sicoob: tudo string (`tipo`, `valor`, `data`, ...)."""
    def linha(t):
        tipo, valor, d = _comum(t, "tipo", "data")
        desc = str(t.get("descInfComplementar") or "").strip() or str(t.get("descricao") or "").strip()
        return tipo, Movimento(conta_erp, d, valor, "", desc, "", "Sicoob extrato (API)",
                               str(t.get("transactionId") or ""))
    return _ler(_transacoes(corpo), dia, linha)


def movimentos_inter(corpo: dict, conta_erp: str, dia: date) -> Extrato:
    """GET /banking/v2/extrato do Inter: `tipoOperacao` C/D, `valor` string."""
    def linha(t):
        tipo, valor, d = _comum(t, "tipoOperacao", "dataEntrada")
        desc = str(t.get("descricao") or "").strip() or str(t.get("titulo") or "").strip()
        return tipo, Movimento(conta_erp, d, valor, "", desc, "", "Inter extrato (API)", "")
    return _ler(_transacoes(corpo), dia, linha)
