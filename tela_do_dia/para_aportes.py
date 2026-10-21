# -*- coding: utf-8 -*-
"""Os aportes definidos na tela do dia viram operações da aba Aportes.

Nada vai ao ERP daqui: as operações entram na lista "A lançar" e o dono confere
e clica "Lançar no Mais Controle" lá, como sempre. Quatro regras de dinheiro:

- **nome não se chuta.** O rótulo da aba Regras e o cadastro da aba Aportes
  (`contas.csv`) são vocabulários diferentes; casa pelo NOME COMPLETO via
  `normalize_name` (sem acento, caixa ou pontuação) ou pelo NÚMERO da conta, e
  só com UM candidato. Dois aportadores com o mesmo primeiro nome são pessoas
  diferentes: nome pela metade não casa com ninguém. Sobrou dúvida, vira
  pendência;
- **subconta de investidor é UMA operação** ("INVESTIDOR SUBCONTA 00000-0"),
  porque a aba Aportes rateia pelo `subcontas.json`. Se a divisão digitada não
  for a do cadastro, é pendência — a outra aba lançaria a dela, não a sua;
- **o que já foi mandado hoje não vai de novo** sem o dono pedir. A chave é
  só destino e aportador (`chave_de_envio`), e o valor mandado fica guardado
  ao lado dela: corrigir 300,00 para 350,00 e mandar de novo NÃO gera segunda
  operação — vira pendência "já mandado R$ 300,00 hoje; agora R$ 350,00",
  porque a primeira pode já estar lançada e o ERP somaria 650,00. Aporte em
  dobro se desfaz à mão no ERP;
- **conta sem saldo do sistema** (o ERP não trouxe; `AporteDaConta.sem_saldo`)
  não sai calada: a operação vai em `itens`, mas ganha a pendência
  `MOTIVO_SEM_SALDO` e o índice dela em `Envio.sem_saldo`. Quem decide se
  trava é a tela.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import util
from aportes.dados import INVESTIDOR_PREFIXO
from aportes.regras import (TIPO_INVESTIDOR, Operacao, como_dinheiro,
                            dividir_por_peso, e_da_subconta, numero_da_conta)
from conciliacao.parsing import normalize_name

from .valores import brl

ZERO = Decimal("0.00")

MOTIVO_SEM_SALDO = "conta sem saldo do sistema — confira antes de lançar"


@dataclass(frozen=True)
class Pendente:
    destino: str
    aportador: str
    valor: Decimal
    motivo: str


@dataclass
class Envio:
    itens: list = field(default_factory=list)       # [(Operacao, [chave_de_envio])]
    pendentes: list = field(default_factory=list)
    #: chave_de_envio -> valor daquele aportador (o que `marcar_enviados` guarda).
    valores: dict = field(default_factory=dict)
    #: Índices de `itens` cuja conta (destino ou aportador) está sem saldo.
    sem_saldo: list = field(default_factory=list)


def chave_de_envio(destino: str, aportador: str) -> str:
    """Sem o valor, de propósito: o valor mandado é o VALOR do dicionário
    `enviados_aportes`, e mudar o número não abre a porta para mandar de novo."""
    return f"{destino}|{aportador}"


def marcar_enviados(envio: Envio, recusas, enviados: dict) -> None:
    """Guarda em `enviados` (chave -> valor) o que a aba Aportes ACEITOU.
    `recusas` é o que `AportesFrame.receber_operacoes` devolveu."""
    recusadas = {i for i, _motivo in recusas}
    for i, (_op, chaves) in enumerate(envio.itens):
        if i in recusadas:
            continue
        for chave in chaves:
            enviados[chave] = envio.valores[chave]


def nome_no_cadastro(rotulo: str, entidades: dict) -> str | None:
    alvo = normalize_name(rotulo)
    if not alvo:
        return None
    iguais = [n for n, d in entidades.items()
              if alvo in (normalize_name(n), normalize_name((d or {}).get("nome_oficial") or ""))]
    if len(iguais) == 1:
        return iguais[0]
    if iguais:
        return None
    numero = numero_da_conta(rotulo)
    if not numero:
        return None
    pelo_numero = [n for n, d in entidades.items() if e_da_subconta(n, d or {}, numero)]
    return pelo_numero[0] if len(pelo_numero) == 1 else None


def _tipo(tipo_regra: str) -> str:
    t = util.sem_acento(tipo_regra or "Aporte").casefold().strip()
    if t.startswith("aporte"):
        return "Aporte de Capital"
    if t.startswith("distribui"):
        return "Distribuição de Lucro"
    return ""


def _modo(pagador: str, recebedor: str, entidades: dict) -> str:
    if (entidades[pagador] or {}).get("conta") is None:
        return "Só recebimento"
    if (entidades[recebedor] or {}).get("conta") is None:
        return "Só pagamento"
    return "Pagamento + Recebimento"


def _ja_mandado(anterior, valor) -> str:
    if anterior is None:
        return ("já mandado para a aba Aportes hoje — confira lá antes de "
                "mandar de novo")
    if como_dinheiro(anterior) == como_dinheiro(valor):
        return (f"já mandado {brl(como_dinheiro(anterior))} hoje para a aba Aportes — "
                "confira lá antes de mandar de novo")
    return (f"já mandado {brl(como_dinheiro(anterior))} hoje; agora "
            f"{brl(como_dinheiro(valor))} — confira a aba Aportes (a de antes pode "
            "já estar lançada; corrija lá, não mande outra)")


def operacoes(definidos, regras, entidades, subcontas, data, enviados=None,
              sem_saldo=()) -> Envio:
    """`enviados`: {chave_de_envio: valor mandado} do dia (um conjunto de
    chaves também serve, com o valor desconhecido). `sem_saldo`: rótulos das
    contas do dia cujo saldo o sistema não trouxe."""
    if enviados is None:
        enviados = {}
    elif not isinstance(enviados, dict):
        enviados = dict.fromkeys(enviados)
    sem_saldo = set(sem_saldo or ())
    envio = Envio()
    regra_do_par = {(r.destino, r.aportador): r for r in regras}
    da_subconta: dict[tuple[str, str], dict] = {}

    def pendente(destino, aportador, valor, motivo):
        envio.pendentes.append(Pendente(destino, aportador, valor, motivo))

    def incluir(op, pares):
        chaves = [chave_de_envio(d, a) for d, a, _v in pares]
        envio.itens.append((op, chaves))
        for chave, (_d, _a, v) in zip(chaves, pares):
            envio.valores[chave] = como_dinheiro(v)
        if any(d in sem_saldo or a in sem_saldo for d, a, _v in pares):
            envio.sem_saldo.append(len(envio.itens) - 1)
            for d, a, v in pares:
                pendente(d, a, v, MOTIVO_SEM_SALDO)

    for (destino, aportador), valor in definidos.items():
        if not valor or valor <= 0:
            continue
        regra = regra_do_par.get((destino, aportador))
        if regra is None:
            pendente(destino, aportador, valor, "não está na aba Regras do modelo")
            continue
        numero = numero_da_conta(destino)
        if numero and numero in subcontas and not regra.do_painel:
            da_subconta.setdefault((destino, numero), {})[aportador] = valor
            continue
        chave = chave_de_envio(destino, aportador)
        if chave in enviados:
            pendente(destino, aportador, valor, _ja_mandado(enviados[chave], valor))
            continue
        tipo = _tipo(regra.tipo)
        pagador, recebedor = nome_no_cadastro(aportador, entidades), nome_no_cadastro(destino, entidades)
        if not tipo:
            pendente(destino, aportador, valor, f"tipo {regra.tipo!r} da aba Regras não é aporte nem distribuição")
            continue
        if pagador is None or recebedor is None:
            falta = aportador if pagador is None else destino
            pendente(destino, aportador, valor, f"não achei {falta!r} (um só) no cadastro da aba Aportes")
            continue
        op = Operacao(data=data, pagador=pagador, recebedor=recebedor, valor=como_dinheiro(valor),
                      tipo=tipo, modo=_modo(pagador, recebedor, entidades))
        erros = op.validar(entidades, subcontas)
        if erros:
            pendente(destino, aportador, valor, "; ".join(erros))
            continue
        incluir(op, [(destino, aportador, valor)])

    for (destino, numero), valores in da_subconta.items():
        def todos(motivo):
            for a, v in valores.items():
                pendente(destino, a, v, motivo)
        ja = {a for a in valores if chave_de_envio(destino, a) in enviados}
        if ja:
            # A subconta é UMA operação: um investidor já mandado segura todos.
            for a, v in valores.items():
                chave = chave_de_envio(destino, a)
                pendente(destino, a, v, _ja_mandado(enviados[chave], v) if a in ja else
                         f"já mandado outro investidor da subconta {numero} hoje (a "
                         "subconta vai numa operação só) — confira a aba Aportes")
            continue
        cfg = subcontas[numero]
        investidores = cfg.get("investidores") or []
        total = sum(valores.values(), ZERO)
        recebedor = nome_no_cadastro(destino, entidades)
        por_nome = {util.norm_espaco(a): v for a, v in valores.items()}
        if recebedor is None:
            todos(f"não achei {destino!r} (um só) no cadastro da aba Aportes")
            continue
        if (len(por_nome) != len(valores)
                or set(por_nome) != {util.norm_espaco(i) for i in investidores}):
            todos(f"os investidores digitados não são os da subconta {numero} no cadastro")
            continue
        try:
            partes = dividir_por_peso(total, investidores, cfg.get("pesos") or {})
        except ValueError as e:
            todos(str(e))
            continue
        if any(por_nome[util.norm_espaco(i)] != p for i, p in zip(investidores, partes)):
            todos(f"a divisão digitada difere da do cadastro da subconta {numero} "
                  "(a aba Aportes divide pelo cadastro)")
            continue
        op = Operacao(data=data, pagador=INVESTIDOR_PREFIXO + numero, recebedor=recebedor,
                      valor=como_dinheiro(total), tipo=TIPO_INVESTIDOR, modo="Só recebimento")
        erros = op.validar(entidades, subcontas)
        if erros:
            todos("; ".join(erros))
            continue
        incluir(op, [(destino, a, v) for a, v in valores.items()])
    return envio
