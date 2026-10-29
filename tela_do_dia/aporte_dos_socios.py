# -*- coding: utf-8 -*-
"""O aporte "de fora" na conta-mãe dividido entre os sócios, e o aviso de
quem precisa igualar. Sem tela.

Regras do dono (29/10/2026):

- os sócios da conta-mãe aportam SÓ nela (no banco dela ou no outro banco da
  mesma empresa), sempre na mesma proporção; num dia um pode aportar mais ou
  sozinho, e o outro iguala depois;
- o movimento à mão "de fora" que entra nessas contas vira, no "Mandar para
  a aba Aportes", um Aporte de Capital de CADA sócio, numa janela que já
  abre na proporção (meio a meio) e cuja soma tem de bater com o valor;
- o aviso "fulano precisa aportar R$ X para igualar beltrano" vem da
  apuração da aba Controle de aportes, nunca de conta feita aqui.

**Quem são os sócios** sai do Controle de aportes, e não do
`confirmar_antes.json`: lá estão os aportadores da conta-mãe com o nome
COMPLETO (o Cliente do ERP) e a parte de cada um, escolhidos pelo dono. O
`confirmar_antes.json` guarda só o começo do nome, e casar nome incompleto
é o que o projeto proíbe (dois aportadores diferentes com o mesmo começo).
Sem a apuração da conta-mãe, nada se divide: a tela diz por quê.

**Aporte não se repete**: cada parte tem chave própria no JSON do dia
(`chave`, prefixo `defora:`); já mandada, vira pendência "já mandado" — a
mesma régua de `para_aportes`.
"""
from __future__ import annotations

from decimal import Decimal

import util
from aportes.regras import (Operacao, como_dinheiro, dividir_por_peso,
                            problema_dos_pesos)
from conciliacao.parsing import normalize_name

from . import para_aportes as pa
from .valores import brl, ler_valor_editado

ZERO = Decimal("0.00")
TIPO = "Aporte de Capital"
PREFIXO = "defora:"


def chave(socio: str, destino: str) -> str:
    """A chave de "já mandado" de uma parte. Sem o valor: corrigir o número
    não abre a porta para mandar de novo."""
    return f"{PREFIXO}{socio}|{destino}"


def ja_mandado(enviados, destino: str) -> bool:
    """Alguma parte do aporte de fora em `destino` já foi mandada hoje."""
    return any(c.startswith(PREFIXO) and c.rpartition("|")[2] == destino
               for c in (enviados or {}))


def _e_transferencia(tipo: str) -> bool:
    return util.sem_acento(tipo or "").casefold().strip().startswith("transf")


def contas_da_mae(regras, mae) -> list[str]:
    """A conta-mãe e as contas para onde ela só TRANSFERE na aba Regras — a
    mesma empresa noutro banco (o aporte dos sócios entra em qualquer uma)."""
    if not mae:
        return []
    saida = [mae]
    for r in regras or ():
        if r.aportador == mae and _e_transferencia(r.tipo) and r.destino not in saida:
            saida.append(r.destino)
    return saida


def movimentos_de_fora(a_mao, contas) -> tuple[dict, list]:
    """({destino: valor somado} dos de fora nas `contas`, [(destino, valor)]
    dos de fora em OUTRAS contas). Dois de fora no mesmo destino são um
    aporte só na janela (a soma)."""
    contas = list(contas or ())
    nas_contas: dict[str, Decimal] = {}
    outras = []
    for origem, destino, valor in a_mao or ():
        if origem is not None or valor is None or valor <= ZERO:
            continue
        if destino in contas:
            nas_contas[destino] = nas_contas.get(destino, ZERO) + como_dinheiro(valor)
        else:
            outras.append((destino, como_dinheiro(valor)))
    return nas_contas, outras


def _conta_do_erp(rotulo: str, entidades: dict) -> str:
    nome = pa.nome_no_cadastro(rotulo, entidades or {})
    if nome is None:
        return ""
    return str((entidades[nome] or {}).get("conta") or "")


def socios_da_mae(apuracoes, mae: str, entidades: dict) -> tuple[list, str]:
    """([(nome no cadastro, peso)], "") dos aportadores da conta-mãe no
    Controle de aportes, ou ([], o recado do que falta)."""
    if not mae:
        return [], "a conta-mãe não foi achada na aba Regras"
    conta = _conta_do_erp(mae, entidades)
    if not conta:
        return [], (f"não achei {mae!r} (um só, com a conta do ERP) no cadastro da "
                    "aba Aportes")
    alvo = normalize_name(conta)
    achadas = [ap for ap in apuracoes or () if normalize_name(ap.conta.conta_erp) == alvo]
    if not achadas:
        return [], (f"o Controle de aportes não foi lido ou não tem a conta {conta!r} — "
                    "busque de novo (ou abra a aba Controle de aportes)")
    if len(achadas) > 1:
        return [], f"a conta {conta!r} aparece mais de uma vez no Controle de aportes"
    aportadores = list(achadas[0].conta.aportadores)
    if len(aportadores) < 2:
        return [], (f"a conta {conta!r} tem {len(aportadores)} aportador no Controle "
                    "de aportes — não há o que dividir")
    socios = []
    for a in aportadores:
        nome = pa.nome_no_cadastro(a.nome_erp, entidades or {})
        if nome is None:
            return [], (f"não achei {a.nome_erp!r} (um só) no cadastro da aba Aportes — "
                        "cadastre com o nome completo")
        socios.append((nome, a.peso))
    if len({n for n, _p in socios}) != len(socios):
        return [], "dois aportadores do Controle casam com o mesmo cadastro"
    return socios, ""


def divisao_inicial(valor, socios) -> dict:
    """{sócio: parte} na proporção do Controle (1 e 1 = meio a meio). Os
    centavos que sobram vão por `dividir_por_peso` — a soma fecha sempre."""
    nomes = [n for n, _p in socios]
    pesos = {n: p for n, p in socios}
    if problema_dos_pesos(nomes, pesos):
        pesos = {}
    return dict(zip(nomes, dividir_por_peso(como_dinheiro(valor), nomes, pesos)))


def ler_parte(texto) -> Decimal:
    """O valor digitado de uma parte: vazio é zero. Levanta ValueError."""
    if not str(texto or "").strip():
        return ZERO
    v = ler_valor_editado(texto)
    if v < ZERO:
        raise ValueError("parte negativa")
    return como_dinheiro(v)


def validar_divisao(valor, partes) -> str:
    """"" ou o recado de uma linha da janela."""
    partes = [como_dinheiro(p) for p in partes]
    if any(p < ZERO for p in partes):
        return "parte negativa"
    soma = sum(partes, ZERO)
    if soma == ZERO:
        return "as partes estão zeradas"
    falta = como_dinheiro(valor) - soma
    if falta > ZERO:
        return f"faltam {brl(falta)}"
    if falta < ZERO:
        return f"passou {brl(-falta)}"
    return ""


def _par_na_regras(destino, socio, definidos, entidades):
    """(aportador da aba Regras, valor) do mesmo sócio na mesma conta, ou None."""
    for (d, aportador), v in (definidos or {}).items():
        if d == destino and v and v > ZERO and (
                aportador == socio or pa.nome_no_cadastro(aportador, entidades) == socio):
            return aportador, v
    return None


def operacoes(divisoes, valores, entidades, subcontas, data, enviados=None,
              definidos=None, sem_saldo=(), na_aba_aportes=None) -> tuple:
    """(Envio, {(destino, aportador da Regras)}) das partes digitadas.

    `divisoes`: {destino: {sócio do cadastro: parte}}; `valores`: {destino:
    valor do aporte de fora} — a soma das partes tem de bater com ele, senão
    nada daquele destino vai. Parte zero não vira operação. O segundo valor são os pares da aba Regras do MESMO sócio na
    MESMA conta: os dois lados viram pendência (somar calado lançaria o
    dobro se fossem o mesmo dinheiro) — quem passa isso a
    `para_aportes.operacoes(pares_em_dobro=)` é a tela."""
    enviados = dict(enviados or {})
    sem_saldo = set(sem_saldo or ())
    envio = pa.Envio()
    em_dobro = set()
    for destino, partes in (divisoes or {}).items():
        rotulo_socio = lambda s: f"{s} (aporte de fora)"  # noqa: E731
        total = (valores or {}).get(destino)
        problema = ("o aporte de fora não está mais na tela" if total is None
                    else validar_divisao(total, list(partes.values())))
        if problema:
            for s, v in partes.items():
                envio.pendentes.append(pa.Pendente(destino, rotulo_socio(s), v, problema))
            continue
        recebedor = pa.nome_no_cadastro(destino, entidades)
        sub = pa.numero_de_subconta_de_investidor(destino, entidades)
        for socio, valor in partes.items():
            valor = como_dinheiro(valor)
            if valor <= ZERO:
                continue
            quem = rotulo_socio(socio)
            k = chave(socio, destino)
            if k in enviados:
                la = pa.ainda_na_aba(socio, recebedor, data, na_aba_aportes)
                envio.pendentes.append(pa.Pendente(
                    destino, quem, valor, pa._ja_mandado(enviados[k], valor,
                                                         fora_da_aba=la is False)))
                continue
            if recebedor is None:
                envio.pendentes.append(pa.Pendente(
                    destino, quem, valor,
                    f"não achei {destino!r} (um só) no cadastro da aba Aportes"))
                continue
            if sub:
                envio.pendentes.append(pa.Pendente(
                    destino, quem, valor,
                    f"{destino!r} é subconta de investidor ({sub}): aporte de capital "
                    "de sócio não vai para lá"))
                continue
            if socio not in (entidades or {}):
                envio.pendentes.append(pa.Pendente(
                    destino, quem, valor, f"não achei {socio!r} no cadastro da aba Aportes"))
                continue
            na_regras = _par_na_regras(destino, socio, definidos, entidades)
            if na_regras is not None:
                aportador, v_regra = na_regras
                em_dobro.add((destino, aportador))
                envio.pendentes.append(pa.Pendente(
                    destino, quem, valor,
                    f"{socio} também aporta nesta conta pela aba Regras hoje "
                    f"({brl(como_dinheiro(v_regra))}) — tire um dos dois"))
                continue
            op = Operacao(data=data, pagador=socio, recebedor=recebedor, valor=valor,
                          tipo=TIPO, modo=pa._modo(socio, recebedor, entidades))
            erros = op.validar(entidades, subcontas)
            if erros:
                envio.pendentes.append(pa.Pendente(destino, quem, valor, "; ".join(erros)))
                continue
            envio.itens.append((op, [k]))
            envio.valores[k] = valor
            if destino in sem_saldo:
                envio.sem_saldo.append(op)
                envio.avisos.append(pa.Pendente(destino, quem, valor, pa.MOTIVO_SEM_SALDO))
    return envio, em_dobro


def juntar(envio, outro) -> None:
    """Soma `outro` (o dos sócios) em `envio` (o da aba Regras)."""
    envio.itens.extend(outro.itens)
    envio.pendentes.extend(outro.pendentes)
    envio.avisos.extend(outro.avisos)
    envio.informativos.extend(outro.informativos)
    envio.valores.update(outro.valores)
    envio.sem_saldo.extend(outro.sem_saldo)


# ------------------------------------------------------- aviso de igualar
def avisos_de_igualar(apuracoes, erro: str = "") -> list[str]:
    """Uma frase por aportador que está atrás, conta por conta, pela
    apuração do Controle de aportes. Conta igualada não aparece."""
    if erro:
        return [f"Controle de aportes não lido: {erro}"]
    saida = []
    for ap in apuracoes or ():
        conta = ap.conta.conta_erp
        if ap.erro:
            saida.append(f"Controle de aportes: {conta} não fechou ({ap.erro}) — veja a aba")
            continue
        devem = [l for l in ap.linhas if l.diferenca > 0]
        if not devem:
            continue
        lideres = [l.nome for l in ap.linhas if l.diferenca <= 0]
        quem = " e ".join(lideres) or "os outros"
        for l in devem:
            saida.append(f"{l.nome} precisa aportar {brl(l.diferenca)} para igualar "
                         f"{quem} em {conta}")
        if ap.sem_dono:
            saida.append(f"{conta}: {len(ap.sem_dono)} recebimento(s) sem dono — a conta "
                         "acima pode mudar (veja a aba Controle de aportes)")
    return saida


def avisos_dos_socios(apuracoes, mae: str, entidades: dict) -> list[str]:
    """Os avisos de igualar só da conta-mãe, para a janela de divisão."""
    alvo = normalize_name(_conta_do_erp(mae, entidades))
    if not alvo:
        return []
    return avisos_de_igualar([ap for ap in apuracoes or ()
                              if normalize_name(ap.conta.conta_erp) == alvo])
