# -*- coding: utf-8 -*-
"""O rateio de uma subconta de INVESTIDOR, cadastrado pela aba Aportes.

Uma subconta recebe aporte de investidores de fora (empresas ou pessoas que
não têm conta no app). Em Pagou ela aparece como "INVESTIDOR SUBCONTA
00000-0"; em Recebeu, como "SUBCONTA 00000-0 - SICOOB - INVESTIDOR". Ao
lançar (tipo "Aporte de Investidor"), o valor se divide:

1. entre os aportadores, na PROPORÇÃO de cada um (peso: "60 e 40", "2 e 1";
   vazio em todos = partes iguais);
2. a parte de cada aportador, em partes IGUAIS entre as obras (centros de
   custo) da subconta.

Cada (obra × aportador) vira um recebimento (ver `regras.expandir`). As
contas principais da empresa não passam por aqui: o aporte
delas vai inteiro para o CC "Controle de Aportes".

Até 01/10/2026 este cadastro só mudava por SQL. Hoje é a janela "Novo
cadastro", na opção "Subconta de investidor"; aportadores e obras saem das
listas do próprio Mais Controle — o nome tem de bater letra por letra.
"""
from __future__ import annotations

import re

import util

from . import regras
from .dados import INVESTIDOR_PREFIXO

numero_da_conta = regras.numero_da_conta


def nome_em_recebeu(numero: str, banco: str = "SICOOB") -> str:
    """"SUBCONTA 00000-0 - SICOOB - INVESTIDOR" (padrão do dono)."""
    return f"SUBCONTA {numero} - {(banco or 'SICOOB').strip().upper()} - INVESTIDOR"


def _sem_repetir(nomes) -> list[str]:
    vistos, saida = set(), []
    for nome in nomes:
        nome = str(nome or "").strip()
        k = util.norm_espaco(nome)
        if nome and k not in vistos:
            vistos.add(k)
            saida.append(nome)
    return saida


def ler_parte(texto) -> str | None:
    """A parte digitada na tela, como texto do peso. "60", "60%", "33,5",
    "2" (de 2:1). Vazio = None. Recusa com ValueError o que não é número."""
    t = str(texto or "").strip().replace("%", "").replace(",", ".").strip()
    if not t:
        return None
    try:
        valor = regras.Decimal(t)
    except Exception:
        valor = None
    if valor is None or not valor.is_finite():
        raise ValueError(f"\"{texto}\" não é uma parte (use 60, 33,5 ou 2).")
    return format(valor.normalize(), "f")


def partes_de_proporcao(texto, quantos: int) -> list[str] | None:
    """"2:1" (ou "60:40", "1:1:1") -> ["2", "1"], quando o número de partes
    bate com o de aportadores. None quando não é proporção."""
    if ":" not in str(texto or ""):
        return None
    partes = [p.strip() for p in str(texto).split(":")]
    if len(partes) != quantos:
        raise ValueError(f"\"{texto}\" tem {len(partes)} partes, e há "
                         f"{quantos} aportador(es).")
    return [ler_parte(p) for p in partes]


def validar(numero: str, investidores, obras, *, participantes=None,
            centros=None, pesos=None) -> str:
    """"" quando dá para gravar; senão, o motivo.

    `participantes`/`centros` são os nomes que o ERP devolveu. Quando vêm,
    todo nome escolhido tem de estar lá: rateio com nome que o ERP não
    conhece só falharia na hora de lançar — com parte do dinheiro já
    lançada e parte não."""
    if not re.fullmatch(r"\d{5}-\d", numero or ""):
        return "Escolha o número da subconta (formato 00000-0)."
    if not _sem_repetir(investidores):
        return "Falta pelo menos um aportador."
    if not _sem_repetir(obras):
        return "Falta pelo menos um centro de custo."
    problema = regras.problema_dos_pesos(_sem_repetir(investidores),
                                         pesos or {})
    if problema:
        return f"Proporção dos aportadores: {problema}."
    for rotulo, escolhidos, conhecidos in (
            ("aportador", investidores, participantes),
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
def _filhos(token: str, tabela: str, subconta_id,
            com_peso: bool = False) -> list[dict]:
    from nuvem import rest
    return list(rest.ler(tabela, token,
                         colunas="id,nome,peso" if com_peso else "id,nome",
                         filtro=f"subconta_id=eq.{int(subconta_id)}") or [])


def pesos_das_linhas(linhas) -> dict:
    """`{aportador: "2"}` das linhas de `subconta_investidor`; {} sem peso.

    Em TEXTO no JSON, e não float: entra numa conta de dinheiro, e `regras`
    o lê como Decimal."""
    saida = {}
    for l in linhas:
        peso = l.get("peso")
        if peso is not None and str(peso).strip() != "":
            saida[l["nome"]] = format(regras.Decimal(str(peso)).normalize(), "f")
    return saida


def ler_rateios(token: str) -> dict:
    """O rateio de todas as subcontas, como o BANCO tem agora, no formato do
    `subcontas.json` (sem as chaves `_`)."""
    from nuvem import rest
    subs = rest.ler("subconta", token, colunas="id,nome") or []
    obras = rest.ler("subconta_obra", token, colunas="subconta_id,nome") or []
    invs = rest.ler("subconta_investidor", token,
                    colunas="subconta_id,nome,peso") or []
    saida = {}
    for sub in subs:
        deles = [i for i in invs if i["subconta_id"] == sub["id"]]
        saida[sub["nome"]] = {
            "obras": [o["nome"] for o in obras
                      if o["subconta_id"] == sub["id"]],
            "investidores": [i["nome"] for i in deles],
            "pesos": pesos_das_linhas(deles),
        }
    return saida


def mudou(antes: dict, depois: dict, numero: str) -> bool:
    """O rateio de `numero` é outro (fora ordem, acento e caixa)?"""
    def forma(cfg):
        cfg = cfg or {}
        pesos = frozenset(
            (util.norm_espaco(n), regras.Decimal(str(v)))
            for n, v in (cfg.get("pesos") or {}).items())
        return tuple(frozenset(util.norm_espaco(n) for n in cfg.get(k) or [])
                     for k in ("obras", "investidores")) + (pesos,)
    return forma(antes.get(numero)) != forma(depois.get(numero))


def _decimal_ou_none(v):
    return None if v is None or str(v).strip() == "" else regras.Decimal(str(v))


def gravar(token: str, numero: str, investidores, obras, pesos=None) -> None:
    """Cria a subconta se faltar e acerta aportadores (com o peso) e obras.

    Insere ANTES de apagar: se a rede cair no meio, sobra um nome a mais e
    nunca um rateio VAZIO. E, dando certo ou não, o cache desta máquina sai
    com o que o BANCO tem — é o que a próxima abertura do app traria, e o
    que vale para lançar. Falhando, o erro diz o que ficou."""
    from nuvem import rest
    pesos = pesos or {}

    def peso(nome):
        v = regras.peso_de(pesos, nome)
        return None if v is None else format(v.normalize(), "f")

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
            com_peso = tabela == "subconta_investidor"
            antes = _filhos(token, tabela, ident, com_peso)
            inserir, apagar = diferenca(antes, nomes)
            if inserir:
                rest.inserir(tabela, token,
                             [dict({"subconta_id": ident, "nome": n},
                                   **({"peso": peso(n)} if com_peso else {}))
                              for n in inserir], devolver=False)
            if com_peso:
                # O aportador que fica mas mudou de parte: só a coluna.
                for linha in antes:
                    if linha["id"] in apagar:
                        continue
                    novo = peso(linha["nome"])
                    if _decimal_ou_none(linha.get("peso")) != _decimal_ou_none(novo):
                        rest.alterar(tabela, token, f"id=eq.{int(linha['id'])}",
                                     {"peso": novo})
            if apagar:
                rest.apagar(tabela, token, "id=in.(" + ",".join(
                    str(int(i)) for i in apagar) + ")")
    except Exception as e:
        try:
            no_banco = ler_rateios(token).get(numero)
        except Exception:
            no_banco = None
        if no_banco is not None:
            _no_cache(numero, no_banco)
            raise RuntimeError(
                f"{e}\n\nA gravação parou no meio. O que ficou no banco para "
                f"a subconta {numero}: aportadores "
                f"{', '.join(no_banco['investidores']) or '(nenhum)'}; obras "
                f"{', '.join(no_banco['obras']) or '(nenhuma)'}. Abra a "
                "janela de novo e grave o que você quer.") from e
        raise
    _no_cache(numero, ler_rateios(token).get(numero) or {})


def _no_cache(numero: str, cfg: dict) -> None:
    """O `subcontas.json` desta máquina já com a mudança, para a lista de
    hoje trazê-la sem reabrir o app (a abertura regrava tudo do banco)."""
    from nuvem import cache
    from . import dados
    atual = dados.carregar_subcontas()
    atual[numero] = {"obras": _sem_repetir(cfg.get("obras") or []),
                     "investidores": _sem_repetir(cfg.get("investidores") or [])}
    if cfg.get("pesos"):
        atual[numero]["pesos"] = dict(cfg["pesos"])
    cache.gravar_json("subcontas.json", atual, pasta=dados.ARQUIVO_SUBCONTAS.parent)
