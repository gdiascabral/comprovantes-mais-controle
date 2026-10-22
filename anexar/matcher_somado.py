# -*- coding: utf-8 -*-
"""N comprovantes que somam EXATAMENTE um pagamento — só para a aba "Anexar (novo)".

Camada OPCIONAL sobre `matcher.casar`, que continua sendo a régua de um PDF
por pagamento e NÃO muda (lá, somar "afrouxaria a regra" do valor único).
Roda depois dela, só sobre quem ficou SEM PAR por "nenhum PDF com esse valor
na pasta", e só com PDFs que ninguém usou. O caso: o lançamento pago com dois
boletos (entrega 5), cujos comprovantes chegam com a MESMA descrição colada.

Cada PDF do conjunto tem de apontar o pagamento SOZINHO pela régua do matcher:
a MESMA data e OC/NF rotulada ou centro de custo (`matcher._features`), sem
ser de outra conta (`matcher.mesma_conta`). E NUNCA soma quando há dúvida:
- PDF cujo valor é de OUTRO pago do período não entra (pode ser o dele);
- dois conjuntos possíveis → dúvida;
- PDF repetido (mesmo valor, descrição e data) → dúvida (pode ser o mesmo
  comprovante duas vezes);
- PDF que entra na soma de dois pagamentos → dúvida dos dois;
- até `MAX_PDFS_POR_SOMA` PDFs e `MAX_CANDIDATOS` candidatos.
A dúvida daqui NÃO vai para a janela de dúvidas (ela escolhe UM PDF): vai para
o relatório e o Registro, e a pessoa anexa à mão.

Valores em centavos `int` (a unidade de `matcher.parse_pdf` e de
`mc_api.montar_pagos`): a soma é exata, ao centavo, sem float.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations

from . import matcher

#: O motivo de SEM PAR do `matcher.casar` que abre a porta (guardado por teste).
MOTIVO_NENHUM_PDF = "nenhum PDF com esse valor na pasta"
STATUS_SOMA = "SOMA"
MAX_PDFS_POR_SOMA = 4
MAX_CANDIDATOS = 12
_ORDEM_DOS_SINAIS = ("OC/NF", "centro de custo", "data")


def _identifica(pe, pd) -> list[str]:
    """Os sinais com que o PDF aponta o pagamento sozinho; [] quando não aponta."""
    if matcher.mesma_conta(pe.get("origem"), pd.get("origem")) is False:
        return []
    ocnf, cc, data, _docnum = matcher._features(pe, pd)
    if not data or not (ocnf or cc):
        return []
    return [s for s, ok in zip(_ORDEM_DOS_SINAIS, (ocnf, cc, data)) if ok]


def _valores_dos_outros(pe, todos) -> set:
    return {v for q in todos
            if q is not pe and q.get("paidId") != pe.get("paidId")
            for v in matcher._vals(q)}


def _repetidos(conjunto) -> bool:
    chaves = [(pd["valor"], pd["ndesc"], pd["data"]) for pd in conjunto]
    return len(set(chaves)) < len(chaves)


def _duvida(pe, motivo, duvidas):
    pe["motivo_soma"] = pe["motivo_sem_par"] = motivo
    duvidas.append(pe)


def casar_somados(pendentes, pdfs, *, todos, max_pdfs=MAX_PDFS_POR_SOMA,
                  max_candidatos=MAX_CANDIDATOS) -> tuple[list, list]:
    """(somados, dúvidas). `todos` são TODOS os pagos do período (todas as
    contas): é contra eles que se pergunta "este valor é de outro?".

    No somado: `status = STATUS_SOMA`, `pdfs` (nomes, do maior valor para o
    menor), `motivo`, e `used_by` em cada PDF. Na dúvida: `motivo_soma` (e o
    `motivo_sem_par` do relatório); nenhum PDF é marcado."""
    alvos = [pe for pe in pendentes if pe.get("status") == "SEM PAR"
             and pe.get("motivo_sem_par") == MOTIVO_NENHUM_PDF]
    duvidas, unicos, tocados, sinais = [], [], Counter(), {}
    for pe in alvos:
        outros, proprios = _valores_dos_outros(pe, todos), matcher._vals(pe)
        eleg = []
        for pd in pdfs:
            if (pd.get("used_by") is not None or pd["valor"] in outros
                    or pd["valor"] in proprios):
                continue
            s = _identifica(pe, pd)
            if s:
                eleg.append(pd)
                sinais[(id(pe), id(pd))] = s
        if len(eleg) > max_candidatos:
            tocados.update(id(pd) for pd in eleg)
            _duvida(pe, f"{len(eleg)} comprovantes apontam este pagamento — muitos "
                        "para somar com segurança; anexe à mão", duvidas)
            continue
        achados = [c for n in range(2, min(max_pdfs, len(eleg)) + 1)
                   for c in combinations(eleg, n)
                   if sum(pd["valor"] for pd in c) in proprios]
        tocados.update({id(pd) for c in achados for pd in c})
        if any(_repetidos(c) for c in achados):
            _duvida(pe, "os comprovantes que somam o valor se repetem (mesmo valor, "
                        "descrição e data) — pode ser o mesmo arquivo duas vezes; "
                        "anexe à mão", duvidas)
        elif len(achados) > 1:
            _duvida(pe, f"{len(achados)} conjuntos de comprovantes somam o valor — "
                        "anexe à mão", duvidas)
        elif achados:
            unicos.append((pe, achados[0]))
    somados = []
    for pe, conjunto in unicos:
        if any(tocados[id(pd)] > 1 for pd in conjunto):
            _duvida(pe, "um dos comprovantes também soma o valor de outro "
                        "pagamento — anexe à mão", duvidas)
            continue
        for pd in conjunto:
            pd["used_by"] = pe["paidId"]
        usados = {s for pd in conjunto for s in sinais[(id(pe), id(pd))]}
        pe["status"] = STATUS_SOMA
        pe["pdfs"] = [pd["fn"] for pd in sorted(conjunto, key=lambda p: (-p["valor"], p["fn"]))]
        pe["motivo"] = (f"soma exata de {len(conjunto)} comprovantes ("
                        + " + ".join(s for s in _ORDEM_DOS_SINAIS if s in usados) + ")")
        somados.append(pe)
    return somados, duvidas
