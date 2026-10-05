# -*- coding: utf-8 -*-
"""Quem e o comprador de cada contrato da casa, e qual deles foi distratado.

Puro: entram textos e anexos, saem grupos e uma sugestao. Sem navegador e sem
tkinter.

Regra do dono (05/10/2026): quando a casa tem distrato, o contrato cujo
COMPRADOR tem os sobrenomes escritos no texto do distrato e o "distratado" --
e a sugestao e esse, nao o do comprador do recebimento. Duas pessoas podem ter
comprado a mesma casa em epocas diferentes, e o ERP so aponta o comprador
ATUAL; so o texto do distrato diz de quem foi o contrato desfeito.

O comprador vem do trecho das partes do proprio contrato ("COMPRADOR: FULANO
DE TAL, brasileiro, ..."), conferido num modelo de contrato assinado real. Casa
SEM distrato nao passa por aqui: la o contrato e o do comprador do recebimento
e nao ha o que desempatar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import util

from .conferencia import CONFERE, _preparar, _texto_util, conferir_nome
from .escolha import eh_mais_completo

#: "COMPRADOR:", "COMPRADORA:", "COMPRADOR(A):", "COMPRADORES:" e o que vem
#: depois. Roda sobre `util.norm` com os espacos reduzidos e ANTES de
#: `_preparar`, que solta a pontuacao e apagaria os `:` e `,` que delimitam.
RE_COMPRADOR = re.compile(
    r"\bCOMPRADOR(?:A|ES|AS|\(A\)|\(ES\))?\s*:\s*([A-Z][^,;]*)")

#: Palavras que abrem a qualificacao e, portanto, encerram o nome quando a
#: virgula foi esquecida. "E" entre dois nomes (casal) nao esta aqui.
QUALIFICACAO = ("BRASILEIR", "PORTADOR", "CPF", "RG", "NACIONALIDADE",
                "SOLTEIR", "CASAD", "DIVORCIAD", "VIUV", "INSCRIT",
                "RESIDENTE", "NASCID", "MAIOR", "EMPRESARI")

#: Nome com mais palavras que isto e a qualificacao engolida: melhor "" (vai
#: para revisao) do que um nome errado no arquivo.
TETO_DE_PALAVRAS = 8


def comprador_do_contrato(texto: str) -> str:
    """O nome do comprador como o contrato o qualifica, ou "" se nao achar.

    Termina na primeira virgula/ponto-e-virgula, hifen solto, palavra com
    digito ou palavra de qualificacao (virgula ausente no contrato)."""
    limpo = re.sub(r"\s+", " ", util.norm(texto or ""))
    achou = RE_COMPRADOR.search(limpo)
    if not achou:
        return ""
    nome: list[str] = []
    for palavra in achou.group(1).split():
        if (palavra == "-" or any(c.isdigit() for c in palavra)
                or palavra.startswith(QUALIFICACAO)):
            break
        nome.append(palavra)
    if not nome or len(nome) > TETO_DE_PALAVRAS:
        return ""
    return " ".join(nome).strip()


@dataclass
class Versao:
    """Uma versao baixada do contrato: o anexo do ERP, os bytes e o texto."""
    anexo: dict
    dados: bytes
    texto: str

    @property
    def comprador(self) -> str:
        return comprador_do_contrato(self.texto)


def _nome(v: Versao) -> str:
    return (v.anexo.get("filename") or "").strip()


def agrupar(versoes: list[Versao],
            comprador_recebimento: str) -> list[list[Versao]]:
    """Agrupa as versoes pelo comprador lido; o do recebimento vem primeiro.

    Versao sem comprador lido (escaneada, sem camada de texto) entra no grupo
    do recebimento so se o proprio texto confere com ele; senao fica sozinha,
    para uma pessoa olhar -- juntar no escuro esconderia um contrato alheio."""
    grupos: dict[str, list[Versao]] = {}
    ilegiveis: list[tuple[int, Versao]] = []
    for i, v in enumerate(versoes):
        if v.comprador:
            grupos.setdefault(v.comprador, []).append(v)
        else:
            ilegiveis.append((i, v))

    def do_recebimento(chave: str) -> bool:
        if chave == "":
            return True  # sem nome lido, mas o texto confere
        if chave.startswith("\0"):
            return False
        return conferir_nome(_preparar(chave),
                             comprador_recebimento) == CONFERE

    # Um comprador = um grupo: o ilegivel que confere entra no grupo nomeado
    # do recebimento se ele existe; "" so quando nao ha onde juntar.
    nomeado = next((c for c in sorted(grupos) if do_recebimento(c)), None)
    for i, v in ilegiveis:
        confere = conferir_nome(_texto_util(v.texto) or "",
                                comprador_recebimento) == CONFERE
        if confere:
            chave = nomeado if nomeado is not None else ""
        else:
            chave = f"\0sozinha{i}"
        grupos.setdefault(chave, []).append(v)

    chaves = sorted(grupos, key=lambda c: (not do_recebimento(c), c))
    return [grupos[c] for c in chaves]


def escolher(grupo: list[Versao]) -> tuple[Versao | None, str]:
    """A versao do contrato daquele comprador, ou None e o motivo."""
    if len(grupo) == 1:
        return grupo[0], ""
    if all(v.dados == grupo[0].dados for v in grupo):
        return grupo[0], ""
    completas = [v for v in grupo if eh_mais_completo(_nome(v))]
    if len(completas) == 1:
        return completas[0], ""
    quem = grupo[0].comprador or "comprador nao lido"
    return None, f"{len(grupo)} versões diferentes do contrato de {quem}"


def foi_distratado(comprador: str, textos_distrato: list[str]) -> bool:
    """Os sobrenomes do comprador aparecem em algum texto de distrato?"""
    if not (comprador or "").strip():
        return False
    return any(conferir_nome(_texto_util(t) or "", comprador) == CONFERE
               for t in textos_distrato)
