# -*- coding: utf-8 -*-
"""Parametrizar, pela aba Aportes, o rateio de uma subconta.

Uma subconta recebe aporte de investidores de fora (empresas ou pessoas que
não têm conta no app) e o valor se divide entre centros de custo (as "obras"
do Mais Controle). Em Pagou ela aparece como "Investidor conta 00000-0"; ao
lançar, cada (CC × investidor) vira um recebimento, em partes iguais (ver
`regras.expandir`).

Até 01/10/2026 esse cadastro (`subconta`, `subconta_obra`,
`subconta_investidor`) só mudava por SQL no painel. A janela do botão
"Rateio de subconta" escolhe investidores e CCs nas listas que o próprio
Mais Controle devolve — o nome tem de bater letra por letra, e escolher na
lista do ERP é o que garante isso.

Aqui mora a regra (testada) e a gravação. A janela está em
`rateio_subconta_dialogo.py`.
"""
from __future__ import annotations

import re

import util

from .dados import INVESTIDOR_PREFIXO

#: "11111-1", "22.222-2", "33333 - 3": o número da conta Sicoob no nome.
_NUMERO = re.compile(r"(\d{2})\.?(\d{3})\s*-\s*(\d)\b")


def numero_da_conta(texto) -> str:
    """O número no formato da tabela `subconta` ("00000-0"), ou ""."""
    m = _NUMERO.search(str(texto or ""))
    return f"{m.group(1)}{m.group(2)}-{m.group(3)}" if m else ""


def subcontas_possiveis(entidades: dict, subcontas: dict) -> list[str]:
    """Os números que a janela oferece: os que já têm rateio e os das contas
    de Pagou/Recebeu com "SUBCONTA" no nome que ainda não têm."""
    numeros = {n for n in subcontas if not n.startswith("_")}
    for dados in entidades.values():
        conta = (dados or {}).get("conta") or ""
        if "SUBCONTA" in util.norm_espaco(conta):
            numero = numero_da_conta(conta)
            if numero:
                numeros.add(numero)
    return sorted(numeros)


def _sem_repetir(nomes) -> list[str]:
    vistos, saida = set(), []
    for nome in nomes:
        nome = str(nome or "").strip()
        k = util.norm_espaco(nome)
        if nome and k not in vistos:
            vistos.add(k)
            saida.append(nome)
    return saida


def validar(numero: str, investidores, obras, *, participantes=None,
            centros=None) -> str:
    """"" quando dá para gravar; senão, o motivo.

    `participantes`/`centros` são os nomes que o ERP devolveu. Quando vêm,
    todo nome escolhido tem de estar lá: rateio com nome que o ERP não
    conhece só falharia na hora de lançar — com parte do dinheiro já
    lançada e parte não."""
    if not re.fullmatch(r"\d{5}-\d", numero or ""):
        return "Escolha o número da subconta (formato 00000-0)."
    if not _sem_repetir(investidores):
        return "Falta pelo menos um investidor."
    if not _sem_repetir(obras):
        return "Falta pelo menos um centro de custo."
    for rotulo, escolhidos, conhecidos in (
            ("investidor", investidores, participantes),
            ("centro de custo", obras, centros)):
        if conhecidos is None:
            continue
        chaves = {util.norm_espaco(c) for c in conhecidos}
        for nome in _sem_repetir(escolhidos):
            if util.norm_espaco(nome) not in chaves:
                return (f"O {rotulo} \"{nome}\" não existe no Mais Controle "
                        "com esse nome. Escolha na lista.")
    return ""


def diferenca(antes: list[dict], depois: list[str]) -> tuple[list[str], list]:
    """`(nomes a inserir, ids a apagar)` para levar `antes` (linhas com `id`
    e `nome`) até `depois`. O que não mudou fica intocado."""
    depois = _sem_repetir(depois)
    ficam = {util.norm_espaco(n) for n in depois}
    tinha = {util.norm_espaco(l["nome"]) for l in antes}
    inserir = [n for n in depois if util.norm_espaco(n) not in tinha]
    apagar = [l["id"] for l in antes if util.norm_espaco(l["nome"]) not in ficam]
    return inserir, apagar


def pagador(numero: str) -> str:
    """Como a subconta aparece em Pagou."""
    return INVESTIDOR_PREFIXO + numero


# --------------------------------------------------------------------------
# Banco
# --------------------------------------------------------------------------
def _filhos(token: str, tabela: str, subconta_id) -> list[dict]:
    from nuvem import rest
    return list(rest.ler(tabela, token, colunas="id,nome",
                         filtro=f"subconta_id=eq.{int(subconta_id)}") or [])


def ler_rateios(token: str) -> dict:
    """O rateio de todas as subcontas, como o BANCO tem agora, no formato do
    `subcontas.json` (sem as chaves `_`)."""
    from nuvem import rest
    subs = rest.ler("subconta", token, colunas="id,nome") or []
    obras = rest.ler("subconta_obra", token, colunas="subconta_id,nome") or []
    invs = rest.ler("subconta_investidor", token,
                    colunas="subconta_id,nome") or []
    saida = {}
    for sub in subs:
        saida[sub["nome"]] = {
            "obras": [o["nome"] for o in obras
                      if o["subconta_id"] == sub["id"]],
            "investidores": [i["nome"] for i in invs
                             if i["subconta_id"] == sub["id"]],
        }
    return saida


def mudou(antes: dict, depois: dict, numero: str) -> bool:
    """O rateio de `numero` é outro (fora ordem, acento e caixa)?"""
    def forma(cfg):
        cfg = cfg or {}
        return tuple(frozenset(util.norm_espaco(n) for n in cfg.get(k) or [])
                     for k in ("obras", "investidores"))
    return forma(antes.get(numero)) != forma(depois.get(numero))


def gravar(token: str, numero: str, investidores, obras) -> None:
    """Cria a subconta se faltar e acerta CCs e investidores.

    Insere ANTES de apagar: se a rede cair no meio, sobra um nome a mais e
    nunca um rateio VAZIO. E, dando certo ou não, o cache desta máquina sai
    com o que o BANCO tem — é o que a próxima abertura do app traria, e o
    que vale para lançar. Falhando, o erro diz o que ficou."""
    from nuvem import rest
    try:
        achadas = rest.ler("subconta", token, colunas="id,nome",
                           filtro=f"nome=eq.{numero}")
        if achadas:
            ident = achadas[0]["id"]
        else:
            ident = rest.inserir("subconta", token,
                                 [{"nome": numero}])[0]["id"]
        for tabela, nomes in (("subconta_investidor", investidores),
                              ("subconta_obra", obras)):
            inserir, apagar = diferenca(_filhos(token, tabela, ident), nomes)
            if inserir:
                rest.inserir(tabela, token,
                             [{"subconta_id": ident, "nome": n}
                              for n in inserir], devolver=False)
            if apagar:
                rest.apagar(tabela, token, "id=in.(" + ",".join(
                    str(int(i)) for i in apagar) + ")")
    except Exception as e:
        try:
            no_banco = ler_rateios(token).get(numero)
        except Exception:
            no_banco = None
        if no_banco is not None:
            _no_cache(numero, no_banco["investidores"], no_banco["obras"])
            raise RuntimeError(
                f"{e}\n\nA gravação parou no meio. O que ficou no banco para "
                f"a subconta {numero}: investidores "
                f"{', '.join(no_banco['investidores']) or '(nenhum)'}; CCs "
                f"{', '.join(no_banco['obras']) or '(nenhum)'}. Abra a "
                "janela de novo e grave o que você quer.") from e
        raise
    no_banco = ler_rateios(token).get(numero) or {}
    _no_cache(numero, no_banco.get("investidores") or [],
              no_banco.get("obras") or [])


def _no_cache(numero: str, investidores, obras) -> None:
    """O `subcontas.json` desta máquina já com a mudança, para a lista de
    hoje trazê-la sem reabrir o app (a abertura regrava tudo do banco)."""
    from nuvem import cache
    from . import dados
    atual = dados.carregar_subcontas()
    atual[numero] = {"obras": _sem_repetir(obras),
                     "investidores": _sem_repetir(investidores)}
    cache.gravar_json("subcontas.json", atual, pasta=dados.ARQUIVO_SUBCONTAS.parent)
