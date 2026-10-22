"""Passo 7: a lista do diretor — só o que foi AGENDADO hoje, uma linha por
conta, nome curto definido uma vez (nuvem), ordinais marcados na hora com a
ordem de ontem como sugestão, texto pronto para o WhatsApp. ("Arrastar" é
↑/↓ na tela: Treeview não arrasta sem código de tela que não se testa.)
Módulo puro: sem tela, sem rede. Dinheiro em Decimal."""
from __future__ import annotations

from dataclasses import dataclass, replace
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
    sem_nome_curto: bool = False


def montar(agendados_hoje, rotulo_de, nomes) -> list[LinhaDaLista]:
    """Soma por rótulo de conta. Valor None ou <= 0 não vira linha."""
    soma: dict[str, Decimal] = {}
    for a in agendados_hoje:
        if a.valor is None or a.valor <= 0:
            continue
        r = rotulo_de(a.conta) or a.conta
        if not r:
            raise ValueError("Agendado sem conta nem rótulo: a lista não pode ter linha sem nome.")
        soma[r] = soma.get(r, ZERO) + a.valor
    return [LinhaDaLista(r, nomes.get(r) or r, v, None, not nomes.get(r))
            for r, v in soma.items()]


def renumerar(linhas) -> list[LinhaDaLista]:
    """Lista nova: numerados primeiro, ordenados por (ordinal, posição) e
    renumerados de 1; depois os sem ordinal. Não altera os objetos recebidos."""
    linhas = list(linhas)
    com = sorted((p for p in enumerate(linhas) if p[1].ordinal is not None),
                 key=lambda p: (p[1].ordinal, p[0]))
    sem = [l for l in linhas if l.ordinal is None]
    return [replace(l, ordinal=n) for n, (_, l) in enumerate(com, 1)] + [replace(l) for l in sem]


def _ordinal_de_ontem(x):
    try:
        n = int(x.get("ordinal"))
    except (TypeError, ValueError):
        return None
    return n if n > 0 else None


def sugerir_ordem(linhas, anterior) -> list[LinhaDaLista]:
    pos: dict[str, tuple[int, int | None]] = {}
    for i, x in enumerate(anterior or ()):
        pos.setdefault(str(x.get("conta")), (i, _ordinal_de_ontem(x)))
    com = sorted((l for l in linhas if pos.get(l.rotulo, (0, None))[1]),
                 key=lambda l: (pos[l.rotulo][1], pos[l.rotulo][0]))
    ids = {id(l) for l in com}
    sem = sorted((l for l in linhas if id(l) not in ids),
                 key=lambda l: (pos.get(l.rotulo, (_FIM, None))[0], -l.valor, l.rotulo))
    return renumerar([replace(l, ordinal=n) for n, l in enumerate(com, 1)]
                     + [replace(l, ordinal=None) for l in sem])


def mover(linhas, i, delta) -> list[LinhaDaLista]:
    """Troca a linha i com a vizinha (nos limites não faz nada) e renumera
    os numerados pela posição na lista."""
    linhas, j = list(linhas), i + delta
    if 0 <= i < len(linhas) and 0 <= j < len(linhas):
        linhas[i], linhas[j] = linhas[j], linhas[i]
    com = [l for l in linhas if l.ordinal is not None]
    sem = [l for l in linhas if l.ordinal is None]
    return [replace(l, ordinal=n) for n, l in enumerate(com, 1)] + [replace(l) for l in sem]


def alternar_ordinal(linhas, i) -> list[LinhaDaLista]:
    """Liga/desliga o ordinal da linha i; quem ganha vai para o fim dos
    numerados (`_FIM` só ordena; o `renumerar` põe o número real)."""
    linhas = list(linhas)
    linhas[i] = replace(linhas[i], ordinal=None if linhas[i].ordinal is not None else _FIM)
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
