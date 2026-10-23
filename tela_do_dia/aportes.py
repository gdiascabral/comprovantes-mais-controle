# -*- coding: utf-8 -*-
"""Passo 3 da tela do dia: aporte mínimo por conta, quem põe e quanto.

O espelho é o das fórmulas do Painel (ver `conciliacao/panel.py`):
mínimo G = D + E − C − M, nunca abaixo de zero (E = o que a conta MANDA para
as outras; M = o que ENTRA nela pela seção «À MÃO» da aba Movimentações:
transferência entre contas, aporte de sócio que entra na mãe), e saldo final
I = C − D − E + F (F = o que entra: o aporte definido mais o M). A regra (aba «Regras») SUGERE, só quando
todo participante tem peso (peso em branco = "o rateio é seu"); o dono digita
o valor POR aportador. A conta-mãe — a que aporta em mais contas — vem primeiro
e fechar negativa nela é alerta forte: é dela que sai o dinheiro das outras.

Saldo que o sistema não trouxe (`None`) NÃO é zero: a conta fica sem mínimo,
fora da sugestão e com alerta de erro. Calcular aporte sobre saldo zero é a
trava que `conciliacao/validate.py` (`exigir_todos_os_saldos`) já recusava.

O aportador é casado pelo NOME COMPLETO, exatamente como está na aba Regras:
dois aportadores com o mesmo primeiro nome são pessoas diferentes.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from aportes.regras import dividir_por_peso

from .valores import brl

ZERO = Decimal("0.00")


@dataclass(frozen=True)
class Participacao:
    aportador: str
    peso: Decimal | None
    tipo: str
    do_painel: bool
    linha_regra: int


@dataclass
class AporteDaConta:
    rotulo: str
    saldo: Decimal | None
    a_pagar: Decimal
    participantes: list = field(default_factory=list)
    definidos: dict = field(default_factory=dict)
    sai: Decimal = ZERO
    e_mae: bool = False
    #: M do Painel: o que entra na conta pela seção «À MÃO».
    entra_a_mao: Decimal = ZERO
    #: Distribuição de lucros feita à mão (item A, 22/10/2026): SAI desta
    #: conta para um sócio, investidor ou empresa. No Excel é linha da seção
    #: «À MÃO» com esta conta na origem — soma no E dela; no M só quando quem
    #: recebe é outra conta do painel (aí entra nela, `entra_a_mao`).
    distribui: Decimal = ZERO

    @property
    def sem_saldo(self) -> bool:
        """O sistema não trouxe o saldo: nada aqui é calculado sobre zero."""
        return self.saldo is None

    @property
    def minimo(self) -> Decimal:
        if self.saldo is None:
            return ZERO                      # não calculado (ver `sem_saldo`)
        falta = self.a_pagar + self.sai + self.distribui - self.saldo - self.entra_a_mao
        return falta if falta > ZERO else ZERO

    @property
    def definido(self) -> Decimal:
        return sum(self.definidos.values(), ZERO)

    @property
    def falta_ratear(self) -> Decimal:
        return max(ZERO, self.minimo - self.definido)

    @property
    def sobra(self) -> Decimal:
        return max(ZERO, self.definido - self.minimo)

    @property
    def saldo_final(self) -> Decimal:
        # Sem saldo, o número só mostra o movimento do dia; a conta já carrega
        # o alerta de erro e não entra em sugestão nem em alerta de negativa.
        return (self.saldo if self.saldo is not None else ZERO) \
            - self.a_pagar - self.sai - self.distribui + self.definido + self.entra_a_mao

    @property
    def sugestao(self) -> dict:
        if self.saldo is None or self.minimo <= ZERO or not self.participantes:
            return {}
        if any(p.peso is None for p in self.participantes):
            return {}
        nomes = [p.aportador for p in self.participantes]
        try:
            partes = dividir_por_peso(self.minimo, nomes,
                                      {p.aportador: p.peso for p in self.participantes})
        except ValueError:                   # peso 0, negativo, nome repetido…
            return {}
        return dict(zip(nomes, partes))


@dataclass
class PainelDeAportes:
    contas: list
    mae: str | None
    alertas: list
    definidos_validos: dict


def _destinos_por_aportador(regras) -> dict[str, set]:
    destinos: dict[str, set] = {}
    for r in regras:
        if r.do_painel:
            destinos.setdefault(r.aportador, set()).add(r.destino)
    return destinos


def _empatadas_na_mae(regras) -> list[str]:
    """Todas as que aportam no maior número de contas, na ordem da aba."""
    destinos = _destinos_por_aportador(regras)
    if not destinos:
        return []
    maior = max(len(d) for d in destinos.values())
    return [a for a, d in destinos.items() if len(d) == maior]


def conta_mae(regras) -> str | None:
    empatadas = _empatadas_na_mae(regras)
    return empatadas[0] if empatadas else None          # empate: a primeira da aba


def montar_aportes(saldos, a_pagar, regras, definidos, a_mao=None,
                   distribuicoes=None) -> PainelDeAportes:
    """`a_mao`: movimentos da seção «À MÃO», [(origem, destino, valor)].
    Origem None = entra de fora (ex.: sócio aporta na mãe). O destino soma
    no M dele (entra); a origem, se for conta do dia, soma no E (sai).
    `distribuicoes`: [(conta de origem, quem recebe, valor)] — SAI da origem
    (`distribui`), que tem de ser conta do dia; quem recebe sendo conta do
    dia (texto igual sem diferença de maiúsculas, como o SUMIF), ENTRA nela
    (`entra_a_mao`)."""
    contas_do_dia = list(dict.fromkeys([*saldos, *a_pagar]))
    participantes: dict[str, list] = {}
    for r in regras:
        participantes.setdefault(r.destino, []).append(
            Participacao(r.aportador, r.peso, r.tipo, r.do_painel, r.linha))
    alertas: list[tuple[str, str]] = []
    validos = {}
    for (destino, aportador), valor in definidos.items():
        if not valor:
            continue
        if valor < ZERO:
            alertas.append(("atencao", f"{aportador} → {destino}: valor negativo "
                                       f"({brl(valor)}) foi ignorado"))
        elif any(p.aportador == aportador for p in participantes.get(destino, ())):
            validos[(destino, aportador)] = valor
        else:
            alertas.append(("atencao", f"{aportador} → {destino}: não está na aba "
                                       f"Regras; o valor {brl(valor)} foi ignorado"))
    sai: dict[str, Decimal] = defaultdict(lambda: ZERO)
    entra: dict[str, Decimal] = defaultdict(lambda: ZERO)
    por_destino: dict[str, dict] = defaultdict(dict)
    for (destino, aportador), valor in validos.items():
        sai[aportador] += valor
        por_destino[destino][aportador] = valor
    for origem, destino, valor in (a_mao or ()):
        de = origem if origem is not None else "fora"
        if not valor:
            continue
        if valor < ZERO:
            alertas.append(("atencao", f"À mão {de} → {destino}: valor negativo "
                                       f"({brl(valor)}) foi ignorado"))
        elif destino not in contas_do_dia:
            alertas.append(("atencao", f"À mão {de} → {destino}: a conta de destino não "
                                       f"está entre as do dia; o valor {brl(valor)} foi ignorado"))
        else:
            entra[destino] += valor
            if origem is not None and origem in contas_do_dia:
                sai[origem] += valor
    distribui: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for origem, socio, valor in (distribuicoes or ()):
        if not valor:
            continue
        if valor < ZERO:
            alertas.append(("atencao", f"Distribuição {origem} → {socio}: valor negativo "
                                       f"({brl(valor)}) foi ignorado"))
        elif origem not in contas_do_dia:
            alertas.append(("atencao", f"Distribuição {origem} → {socio}: a conta de origem "
                                       f"não está entre as do dia; o valor {brl(valor)} "
                                       "foi ignorado"))
        else:
            distribui[origem] += valor
            # Para OUTRA conta do painel (a SPE para a empresa sócia, dono
            # 23/10/2026) o valor também ENTRA no destino, como uma
            # transferência: o SUMIF do M acha a linha (ignorando maiúsculas).
            destino = next((c for c in contas_do_dia
                            if c.casefold() == str(socio or "").strip().casefold()), None)
            if destino is not None and destino != origem:
                entra[destino] += valor
    mae = conta_mae(regras)
    empatadas = _empatadas_na_mae(regras)
    if len(empatadas) > 1:
        alertas.append(("atencao", f"{' e '.join(empatadas)} aportam no mesmo número de "
                                   f"contas — conta-mãe escolhida: {mae}"))
    if mae is not None and mae not in contas_do_dia:
        alertas.append(("atencao", f"A conta-mãe {mae} não está entre as contas do dia — "
                                   "o saldo final dela não é mostrado"))
    contas = []
    for rotulo in contas_do_dia:
        c = AporteDaConta(rotulo=rotulo, saldo=saldos.get(rotulo),
                          a_pagar=a_pagar.get(rotulo, ZERO),
                          participantes=participantes.get(rotulo, []),
                          definidos=dict(por_destino.get(rotulo, {})),
                          sai=sai.get(rotulo, ZERO), e_mae=(rotulo == mae),
                          entra_a_mao=entra.get(rotulo, ZERO),
                          distribui=distribui.get(rotulo, ZERO))
        if (c.e_mae or c.sem_saldo or c.minimo > ZERO or c.definidos
                or c.entra_a_mao or c.sai or c.distribui):
            contas.append(c)
    contas.sort(key=lambda c: not c.e_mae)                  # estável: mãe primeiro
    sem_saldo = []
    for c in contas:
        if c.sem_saldo:
            sem_saldo.append(("erro", f"{c.rotulo}: o sistema não trouxe o saldo — "
                                      "o mínimo não é calculado"))
            continue
        if c.saldo_final < ZERO:
            if c.e_mae:
                alertas.insert(0, ("erro", f"A CONTA-MÃE {c.rotulo} FECHA NEGATIVA: "
                                           f"{brl(c.saldo_final)}. Ela manda {brl(c.sai)} "
                                           "para as outras — reveja os aportes."))
            else:
                alertas.append(("atencao", f"{c.rotulo} fecha negativa: {brl(c.saldo_final)}"))
        if c.falta_ratear > ZERO:
            if not c.participantes:
                alertas.append(("atencao", f"{c.rotulo}: precisa de {brl(c.minimo)} e a "
                                           "aba Regras não diz quem aporta"))
            else:
                alertas.append(("atencao", f"{c.rotulo}: falta ratear {brl(c.falta_ratear)}"))
    return PainelDeAportes(contas=contas, mae=mae, alertas=sem_saldo + alertas,
                           definidos_validos=validos)
