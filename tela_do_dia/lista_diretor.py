"""Passo 7: a lista do diretor — só o que foi AGENDADO hoje, uma linha por
conta, nome curto definido uma vez (nuvem), ordinais marcados na hora com a
ordem de ontem como sugestão, texto pronto para o WhatsApp. ("Arrastar" é
↑/↓ na tela: Treeview não arrasta sem código de tela que não se testa.)
Módulo puro: sem tela, sem rede. Dinheiro em Decimal."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from .valores import brl

ZERO = Decimal("0.00")
NOME_MAXIMO = 60
_FIM = 10 ** 6


@dataclass
class LinhaDaLista:
    rotulo: str
    nome: str
    valor: Decimal
    ordinal: int | None = None


def montar(agendados_hoje, rotulo_de, nomes) -> list[LinhaDaLista]:
    soma: dict[str, Decimal] = {}
    for a in agendados_hoje:
        r = rotulo_de(a.conta) or a.conta
        soma[r] = soma.get(r, ZERO) + a.valor
    return [LinhaDaLista(r, nomes.get(r) or r, v) for r, v in soma.items()]


def renumerar(linhas) -> list[LinhaDaLista]:
    com = [l for l in linhas if l.ordinal is not None]
    sem = [l for l in linhas if l.ordinal is None]
    for i, l in enumerate(com, 1):
        l.ordinal = i
    return com + sem


def sugerir_ordem(linhas, anterior) -> list[LinhaDaLista]:
    pos = {str(x.get("conta")): (i, x.get("ordinal")) for i, x in enumerate(anterior or ())}
    com = sorted((l for l in linhas if pos.get(l.rotulo, (0, None))[1]),
                 key=lambda l: pos[l.rotulo][1])
    marcados = {id(l) for l in com}
    sem = sorted((l for l in linhas if id(l) not in marcados),
                 key=lambda l: (pos.get(l.rotulo, (_FIM, None))[0], -l.valor, l.rotulo))
    for l in com:
        l.ordinal = 0
    for l in sem:
        l.ordinal = None
    return renumerar(com + sem)


def mover(linhas, i, delta) -> list[LinhaDaLista]:
    linhas, j = list(linhas), i + delta
    if 0 <= i < len(linhas) and 0 <= j < len(linhas):
        linhas[i], linhas[j] = linhas[j], linhas[i]
    return renumerar(linhas)


def alternar_ordinal(linhas, i) -> list[LinhaDaLista]:
    """Liga/desliga o ordinal da linha i. Quem ganha ordinal vai para o fim dos
    numerados (`_FIM` só serve para ordenar; o `renumerar` põe o número real)."""
    linhas = list(linhas)
    linhas[i].ordinal = None if linhas[i].ordinal is not None else _FIM
    return renumerar(linhas)


def texto_whatsapp(linhas) -> str:
    com = [l for l in linhas if l.ordinal]
    sem = [l for l in linhas if not l.ordinal]
    saida = [f"{l.ordinal}º {l.nome} — {brl(l.valor)}" for l in com]
    if com and sem:
        saida.append("Demais:")
    saida += [f"{l.nome} — {brl(l.valor)}" for l in sem]
    return "\n".join(saida)


def para_nuvem(linhas) -> list[dict]:
    return [{"conta": l.rotulo, "ordinal": l.ordinal} for l in linhas]


def validar_nome_curto(nome: str) -> str:
    n = (nome or "").strip()
    if not 1 <= len(n) <= NOME_MAXIMO or "\n" in n:
        return f"O nome curto tem de ter de 1 a {NOME_MAXIMO} caracteres, numa linha."
    return ""
