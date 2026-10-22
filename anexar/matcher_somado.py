# -*- coding: utf-8 -*-
"""N comprovantes que somam EXATAMENTE um pagamento — só para a aba "Anexar (novo)".

Camada OPCIONAL sobre `matcher.casar`, que continua sendo a régua de um PDF
por pagamento e NÃO muda (lá, somar "afrouxaria a regra" do valor único).
Roda depois dela, só sobre quem ficou SEM PAR por "nenhum PDF com esse valor
na pasta", e só com PDFs que ninguém usou. O caso: o lançamento pago com dois
boletos (entrega 5), cujos comprovantes chegam com a MESMA descrição colada.

Cada PDF do conjunto tem de apontar o pagamento SOZINHO pela régua do matcher:
a MESMA data e OC/NF rotulada, ou centro de custo com a conta CONFIRMADA
(`matcher._features`, `matcher.mesma_conta`); nunca de outra conta, nem de
recebedor com CPF/CNPJ diferente do favorecido, nem com o código de barras do
título de outro pendente — trava que quase nunca tem com quem comparar: o
código dos títulos só é lido na fase 1, só os de valor igual a um pendente, e
PDF desse valor já sai pela regra do valor de outro pago (ver
`.claude/rules/arquitetura-anexar.md`). Todos os PDFs do conjunto têm a MESMA
descrição (o caso real: a descrição colada nos N boletos). E NUNCA soma quando
há dúvida:
- PDF cujo valor é de OUTRO pago do período não entra (pode ser o dele);
- dois conjuntos possíveis → dúvida;
- PDF repetido (mesmo valor, descrição e data) → dúvida (pode ser o mesmo
  comprovante duas vezes), salvo códigos de barras diferentes nos dois;
- outro pendente não casado com o mesmo valor, obra e data → dúvida;
- PDF de valor zero ou negativo, e pagamento de valor zero, ficam de fora;
- PDF que entra na soma de dois pagamentos → dúvida dos dois;
- até `MAX_PDFS_POR_SOMA` PDFs e `MAX_CANDIDATOS` candidatos.
A dúvida daqui NÃO vai para a janela de dúvidas (ela escolhe UM PDF): vai para
o relatório e o Registro, e a pessoa anexa à mão.

Valores em centavos `int` (a unidade de `matcher.parse_pdf` e de
`mc_api.montar_pagos`): a soma é exata, ao centavo, sem float.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations

from . import matcher

#: O motivo de SEM PAR do `matcher.casar` que abre a porta (guardado por teste).
MOTIVO_NENHUM_PDF = "nenhum PDF com esse valor na pasta"
STATUS_SOMA = "SOMA"
MAX_PDFS_POR_SOMA = 4
MAX_CANDIDATOS = 12
_ORDEM_DOS_SINAIS = ("OC/NF", "centro de custo", "data")


def _so_digitos(texto) -> str:
    return "".join(c for c in str(texto or "") if c.isdigit())


def _identifica(pe, pd) -> list[str]:
    """Os sinais com que o PDF aponta o pagamento sozinho; [] quando não aponta.

    A MESMA data e: OC/NF rotulada que bate, OU centro de custo com a conta
    CONFIRMADA (`mesma_conta is True`) — centro de custo sozinho não basta:
    outro pago da mesma obra, no mesmo dia, sem comprovante baixado, somaria
    o valor e viraria prova falsa de pagamento. Recebedor com CPF/CNPJ
    conhecido e diferente do favorecido conhecido também derruba."""
    conta = matcher.mesma_conta(pe.get("origem"), pd.get("origem"))
    if conta is False:
        return []
    fav, rec = _so_digitos(pe.get("doc_favorecido")), _so_digitos(pd.get("doc_recebedor"))
    if fav and rec and fav != rec:
        return []
    ocnf, cc, data, _docnum = matcher._features(pe, pd)
    if not data or not (ocnf or (cc and conta is True)):
        return []
    return [s for s, ok in zip(_ORDEM_DOS_SINAIS, (ocnf, cc, data)) if ok]


def _valores_dos_outros(pe, todos) -> set:
    return {v for q in todos
            if q is not pe and q.get("paidId") != pe.get("paidId")
            for v in matcher._vals(q)}


def _de_outro_titulo(pe, pd, dono_do_codigo) -> bool:
    """O código de barras do PDF é do título de OUTRO pendente (e não deste) —
    a mesma régua da fase 1 (`matcher.casar`, "de_outro_titulo")."""
    b_pe, b_pd = pe.get("barras") or set(), pd.get("barras") or set()
    return not (b_pe & b_pd) and any(dono_do_codigo.get(b, set()) - {id(pe)}
                                     for b in b_pd)


def _gemeo(pe, pendentes) -> bool:
    """Outro pendente NÃO casado (qualquer motivo, DÚVIDA inclusive) com um
    valor aceito igual, a mesma obra e a mesma data: a soma pode ser dele."""
    obras = {matcher._norm(w) for w in pe.get("works") or ()}
    for q in pendentes:
        if q is pe or q.get("paidId") == pe.get("paidId"):
            continue
        if q.get("status") in ("CERTEZA", STATUS_SOMA):
            continue
        if (matcher._vals(q) & matcher._vals(pe) and q.get("data") == pe.get("data")
                and obras & {matcher._norm(w) for w in q.get("works") or ()}):
            return True
    return False


def _repetidos(conjunto) -> bool:
    """Dois PDFs de mesmo valor, descrição e data são o mesmo comprovante duas
    vezes — salvo quando os dois trazem código de barras e os códigos são
    diferentes: aí são partes iguais legítimas do mesmo lançamento."""
    for a, b in combinations(conjunto, 2):
        if (a["valor"], a["ndesc"], a["data"]) != (b["valor"], b["ndesc"], b["data"]):
            continue
        ba, bb = a.get("barras") or set(), b.get("barras") or set()
        if not (ba and bb and not ba & bb):
            return True
    return False


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
    # De quem é cada código de barras (todos os pagos do período e os pendentes).
    dono_do_codigo: dict[str, set] = defaultdict(set)
    for q in list(todos) + list(pendentes):
        for b in q.get("barras") or ():
            dono_do_codigo[b].add(id(q))
    duvidas, unicos, tocados, sinais = [], [], Counter(), {}
    for pe in alvos:
        outros = _valores_dos_outros(pe, todos)
        proprios = {v for v in matcher._vals(pe) if v > 0}
        if not proprios:
            continue                       # pagamento de valor zero: nada a somar
        eleg = []
        for pd in pdfs:
            if (pd.get("used_by") is not None or pd["valor"] <= 0
                    or pd["valor"] in outros or pd["valor"] in proprios
                    or _de_outro_titulo(pe, pd, dono_do_codigo)):
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
                   if len({pd["ndesc"] for pd in c}) == 1          # a MESMA descrição
                   and sum(pd["valor"] for pd in c) in proprios]
        tocados.update({id(pd) for c in achados for pd in c})
        if achados and _gemeo(pe, pendentes):
            _duvida(pe, "outro pagamento sem comprovante tem o mesmo valor, obra e "
                        "data — a soma pode ser dele; anexe à mão", duvidas)
        elif any(_repetidos(c) for c in achados):
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
