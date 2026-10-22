# tela_do_dia/controle_aportes.py
# -*- coding: utf-8 -*-
"""Controle de aportes: quanto cada aportador pôs em cada conta desde a
abertura, quanto deveria pela proporção e quem deve quanto para igualar.
Sem tela e sem rede — a aba (`controle_frame.py`) só mostra o que sai daqui.

A conta, numa frase: `aportou` = o já aportado antes da abertura + os
recebimentos de aporte do ERP desde a abertura; o NÍVEL é o maior
`aportou ÷ parte`; `deveria` = nível × parte; `para igualar` = deveria −
aportou. Com dois aportadores meio a meio, "A já pôs 50 mil a mais que B"
vira "B deve R$ 50.000,00 para igualar" — a conta que o dono faz de cabeça.

Quem é o aportador de um recebimento: o Cliente dele no ERP (`customerName`),
pelo nome COMPLETO (`util.norm_espaco`: sem acento, caixa e espaço dobrado),
contra os aportadores DAQUELA conta. Nunca por primeiro nome nem por pedaço:
dois aportadores com o mesmo primeiro nome são pessoas diferentes. O que não
casa vai para `sem_dono`, para o dono apontar — nunca some.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import util
from aportes.regras import como_dinheiro, problema_dos_pesos

ZERO = Decimal("0.00")
CENTAVO = Decimal("0.01")


@dataclass(frozen=True)
class Aportador:
    nome_erp: str                 # o Cliente no ERP, nome completo
    peso: Decimal                 # parte (peso: 1 e 1 = meio a meio)
    abertura: Decimal = ZERO      # já aportado ANTES da abertura (>= 0)
    id: int | None = None


@dataclass(frozen=True)
class ContaControlada:
    conta_erp: str                # nome da conta no ERP, letra por letra
    abertura: datetime.date       # primeiro dia contado (inclusive)
    aportadores: tuple = ()
    id: int | None = None
    ativa: bool = True


@dataclass(frozen=True)
class Recebimento:
    id: str
    data: datetime.date
    valor: Decimal
    cliente: str
    natureza: str = ""
    descricao: str = ""
    centro: str = ""


@dataclass(frozen=True)
class Apontamento:
    recebimento_id: str
    aportador_id: int | None      # None = "não é aporte desta conta"
    valor: Decimal                # o valor do recebimento quando foi apontado
    motivo: str
    id: int | None = None


def _dinheiro_do_erp(valor) -> Decimal:
    if valor is None or isinstance(valor, bool) or str(valor).strip() == "":
        raise ValueError("sem valor recebido")
    try:
        d = Decimal(str(valor))
    except InvalidOperation:
        raise ValueError(f"valor ilegível: {valor!r}") from None
    if not d.is_finite():
        raise ValueError(f"valor ilegível: {valor!r}")
    return d.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def recebimento_do_erp(item: dict, natureza: str = "") -> Recebimento:
    """Um item de `receipt-installments`, com os campos que a aba Contratos já
    lê em produção (`contratos/regras.py:183-212`). Levanta `ValueError` sem
    id, data ou valor: recebimento que não se lê não pode virar zero."""
    item = item if isinstance(item, dict) else {}
    ident = str(item.get("id") or "").strip()
    if not ident:
        raise ValueError("recebimento sem id")
    try:
        data = datetime.date.fromisoformat(str(item.get("dateOfReceipt") or "")[:10])
    except ValueError:
        raise ValueError(f"recebimento {ident} sem data de recebimento") from None
    try:
        valor = _dinheiro_do_erp(item.get("sumOfReceivedValues"))
    except ValueError as e:
        raise ValueError(f"recebimento {ident}: {e}") from None
    return Recebimento(id=ident, data=data, valor=valor,
                       cliente=str(item.get("customerName") or "").strip(),
                       natureza=natureza,
                       descricao=str(item.get("description") or "").strip(),
                       centro=str(item.get("workName") or "").strip())


def problemas_da_conta(conta: ContaControlada, hoje: datetime.date, outras=()) -> list[str]:
    """[] quando a conta pode ser gravada e apurada; senão, os motivos."""
    erros: list[str] = []
    nome = (conta.conta_erp or "").strip()
    if not nome:
        erros.append("Falta o nome da conta, como está no Mais Controle.")
    elif any(util.norm_espaco(o.conta_erp) == util.norm_espaco(nome) and o.id != conta.id
             for o in outras):
        erros.append(f'A conta "{nome}" já está no controle.')
    if conta.abertura > hoje:
        erros.append("A abertura não pode ser depois de hoje.")
    nomes = [(a.nome_erp or "").strip() for a in conta.aportadores]
    if not nomes or not all(nomes):
        erros.append("Falta aportador: o nome COMPLETO, como está no Contato do Mais Controle.")
    elif len({util.norm_espaco(n) for n in nomes}) != len(nomes):
        erros.append("Aportador repetido.")
    elif any(a.peso is None for a in conta.aportadores):
        erros.append("Proporção: falta a parte de alguém.")
    else:
        problema = problema_dos_pesos(nomes, {n: a.peso for n, a in zip(nomes, conta.aportadores)})
        if problema:
            erros.append(f"Proporção: {problema}.")
    for a in conta.aportadores:
        ab = a.abertura
        if (not isinstance(ab, Decimal) or not ab.is_finite() or ab < 0
                or ab != ab.quantize(CENTAVO)):
            erros.append(f"Já aportado antes da abertura de {a.nome_erp}: valor inválido.")
    return erros


def aberturas_para_divida(aportadores, devedor: str, valor) -> dict:
    """"FULANO deve R$ V para igualar" -> o já aportado antes da abertura de
    cada um: o devedor com 0, cada outro com V × parte dele ÷ parte do devedor
    (todos os outros no mesmo nível). Com partes que não dividem exato, a
    dívida pode sair um centavo diferente — a tela mostra o resultado."""
    valor = como_dinheiro(valor)
    if valor < 0:
        raise ValueError("A dívida não pode ser negativa.")
    alvo = util.norm_espaco(devedor)
    achados = [a for a in aportadores if util.norm_espaco(a.nome_erp) == alvo]
    if len(achados) != 1:
        raise ValueError("Escolha o devedor entre os aportadores, pelo nome completo.")
    parte_devedor = Decimal(achados[0].peso)
    return {a.nome_erp: (ZERO if a is achados[0]
                         else como_dinheiro(valor * Decimal(a.peso) / parte_devedor))
            for a in aportadores}
