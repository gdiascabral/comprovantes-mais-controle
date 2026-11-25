# -*- coding: utf-8 -*-
"""Quem emitiu o papel lido pela IA é quem o lançamento diz pagar?

Decisão do dono de 25/11/2026: a leitura por IA, que provava só o VALOR,
passa a ler também QUEM EMITIU o papel (`emitente_nome`, `emitente_cnpj_cpf`,
`emitente_telefone`) e a conferir com o favorecido do lançamento. Módulo puro,
sem rede. Quatro regras:

- CNPJ/CPF lido com dígito verificador válido e igual ao do favorecido (o do
  cadastro de Contatos, quando o registro o tem) = bate forte, mesmo com o nome
  escrito diferente. Documento lido que não fecha o DV é ignorado (a IA leu
  mal); documento diferente do cadastro diverge, salvo filial (mesma raiz de
  CNPJ), que cai na comparação por nome.
- Nome: sem acento, maiúsculo, sem pontuação e sem LTDA/ME/EIRELI/EPP/S.A.;
  "bate" quando os dois são iguais, ou todas as palavras de um estão no outro
  e há ao menos DUAS palavras próprias (fora de `GENERICAS`). Palavra que o outro
  nome escreve junta ou separada ("V.M PRE-FABRICADOS" × "VM PREFABRICADOS")
  conta pela junção de palavras vizinhas, nunca por pedaço de palavra.
- Nome diferente = diverge, com o motivo "papel emitido por X, lançamento
  para Y".
- Nada lido, ou sem favorecido: continua "não conferido".
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import util

from .agendamentos_sicoob import GENERICAS
from .regras_pagamento import documento_valido

BATE, DIVERGE, NAO = "bate", "diverge", "não conferido"

#: Formas jurídicas e ligações que não dizem QUEM é.
_SEM_VALOR = frozenset("LTDA ME EIRELI EPP SA MEI EI DE DA DO DAS DOS E".split())
_SOCIEDADE_ANONIMA = re.compile(r"(?<![A-Z0-9])S[./ ]+A\.?(?![A-Z0-9])")


@dataclass
class QuemRecebe:
    estado: str = NAO
    por: str = ""            # "cnpj/cpf" ou "nome" quando bate
    motivo: str = ""


def _palavras(nome) -> list[str]:
    n = util.sem_acento(str(nome or "")).upper()
    n = _SOCIEDADE_ANONIMA.sub(" ", n)
    n = n.replace(".", "").replace("'", "")
    n = re.sub(r"[^A-Z0-9]+", " ", n)
    return [p for p in n.split() if p not in _SEM_VALOR]


def _pecas_usadas(poucas: list[str], muitas: list[str]) -> list[str] | None:
    """Toda palavra de `poucas` está em `muitas`, inteira ou como a junção de
    palavras vizinhas dela? Devolve as palavras de `muitas` que foram usadas
    (None se alguma não achou)."""
    if not poucas:
        return None
    usadas: list[str] = []
    for p in poucas:
        achou = None
        for i in range(len(muitas)):
            for j in range(i + 1, len(muitas) + 1):
                if "".join(muitas[i:j]) == p:
                    achou = muitas[i:j]
                    break
            if achou:
                break
        if not achou:
            return None
        usadas += achou
    return usadas


def _proprias(palavras) -> int:
    """Quantas palavras de 3+ letras e fora de `GENERICAS` (ramo de negócio,
    forma jurídica, sobrenome e prenome comuns não dizem QUEM é)."""
    return len({p for p in palavras if len(p) >= 3 and p.isalpha() and p not in GENERICAS})


def nomes_batem(a, b) -> bool:
    """Iguais (as palavras juntas dão o mesmo texto) ou um contido no outro com
    pelo menos DUAS palavras próprias. "JOAO" × "JOAO PEDRO SILVA", "FULANO
    SOUZA" × "FULANO SOUZA LIMA" e "CASA DAS TINTAS" × "NOVA CASA DAS TINTAS"
    não batem: uma palavra só, ou só palavras comuns, não prova quem é."""
    pa, pb = _palavras(a), _palavras(b)
    if not pa or not pb:
        return False
    if "".join(pa) == "".join(pb):
        return True
    for pouco, muito in ((pa, pb), (pb, pa)):
        usadas = _pecas_usadas(pouco, muito)
        if usadas is not None and max(_proprias(pouco), _proprias(usadas)) >= 2:
            return True
    return False


def _raiz(doc: str) -> str:
    return doc[:8] if len(doc) == 14 else doc


def conferir(leitura: dict, favorecido, doc_favorecido="") -> QuemRecebe:
    """`leitura` é a da IA (os campos `emitente_*` podem faltar: cache antigo)."""
    nome = str((leitura or {}).get("emitente_nome") or "").strip()
    doc_lido = documento_valido((leitura or {}).get("emitente_cnpj_cpf") or "")
    favorecido = str(favorecido or "").strip()
    if not favorecido or not (nome or doc_lido):
        return QuemRecebe()
    doc_fav = documento_valido(doc_favorecido or "")
    if doc_lido and doc_fav:
        if doc_lido == doc_fav:
            return QuemRecebe(BATE, "cnpj/cpf")
        if _raiz(doc_lido) != _raiz(doc_fav):
            return QuemRecebe(DIVERGE, "", f"CNPJ/CPF do papel {doc_lido} × cadastro de "
                                           f"{favorecido} {doc_fav}")
    if not nome:
        return QuemRecebe()
    if nomes_batem(nome, favorecido):
        return QuemRecebe(BATE, "nome")
    return QuemRecebe(DIVERGE, "", f"papel emitido por {nome}, lançamento para {favorecido}")
