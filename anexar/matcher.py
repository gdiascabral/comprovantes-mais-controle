# -*- coding: utf-8 -*-
"""
Casamento entre PDFs renomeados (padrão "VALOR - DESCRIÇÃO - DATA") e os
sub-pagamentos pendentes de comprovante no Mais Controle.

Critérios, do mais forte para o mais fraco (todos exigem o MESMO valor):
  1. nº de OC/NF do nome do PDF = nº do documento (ou aparece na descrição);
  2. centro de custo do PDF aparece nas obras/descrição do lançamento;
  3. data igual (dd-mm) como desempate.

Regras de segurança:
  - cada PDF é usado uma vez só;
  - casamento ambíguo vai para DÚVIDA (nunca "chuta");
  - pagamento sem PDF de mesmo valor vai para SEM PAR.
"""
import os
import re
from collections import defaultdict
from pathlib import Path

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

_norm = util.norm_espaco


# ------------------------------------------------------------------ PDFs
def parse_pdf(fn: str) -> dict | None:
    """Extrai valor/descrição/data/OC/NF do NOME do arquivo.

    Funciona com o modelo padrão (VALOR - DESCRIÇÃO - DATA) e também com
    modelos personalizados: o valor (ex.: 1.234,56) e a data (dd-mm) são
    reconhecidos em QUALQUER posição do nome; o resto vira a descrição.
    O nome precisa conter o VALOR para o casamento automático."""
    if not fn.lower().endswith(".pdf"):
        return None
    base = re.sub(r"\s*\(\d+\)$", "", fn[:-4]).strip()   # remove sufixo " (2)"
    partes = [p.strip() for p in base.split(" - ")]
    if len(partes) < 2:
        return None
    valstr = None
    data = ""
    resto = []
    for p in partes:
        if valstr is None and re.fullmatch(r"\d[\d.]*,\d{2}", p):
            valstr = p
            continue
        m = re.fullmatch(r"(\d{2})-(\d{2})", p)
        if m and not data:
            data = m.group(1) + m.group(2)
            continue
        resto.append(p)
    if valstr is None:
        return None
    desc = " - ".join(resto).strip()
    cents = int(valstr.replace(".", "").replace(",", ""))
    return {
        "fn": fn, "valor": cents, "data": data, "desc": desc, "ndesc": _norm(desc),
        "ocs": set(re.findall(r"\bOC\s*(\d+)", desc, re.I)),
        "nfs": set(re.findall(r"\bNF\s*(\d+)", desc, re.I)),
        "used_by": None,
    }


def carregar_pdfs(pasta: Path, log=print) -> list[dict]:
    pdfs = []
    for fn in sorted(os.listdir(pasta)):
        p = parse_pdf(fn)
        if p:
            pdfs.append(p)
        elif fn.lower().endswith(".pdf"):
            log(f"[aviso] nome fora do padrão, ignorado: {fn}")
    return pdfs


# ------------------------------------------------------------------ features
#: OC/NF citados no lançamento. Mesmo padrão de `mc_api.RE_OC_NF` — o rótulo é
#: obrigatório de propósito: antes, QUALQUER número de 3+ dígitos da descrição
#: virava candidato a OC/NF, então um ano ("2026"), um CEP ou um telefone
#: casavam com um PDF chamado "OC 2026" e fechavam CERTEZA sozinhos.
RE_OC_NF = re.compile(r"\b(?:OC|NFS|NF|OS)\s*[:\-]?\s*(\d{2,})", re.I)


def _ocnf_rotulados(*textos) -> set[str]:
    achados = set()
    for t in textos:
        achados.update(m.group(1) for m in RE_OC_NF.finditer(t or ""))
    return achados


def _features(pe: dict, pd: dict) -> tuple[bool, bool, bool, bool]:
    """(ocnf, cc, date, docnum).

    `docnum` é o nº do documento CRU do lançamento batendo com o OC/NF do PDF:
    sinal fraco, mantido separado porque sozinho nunca deve fechar CERTEZA."""
    do_pdf = pd["ocs"] | pd["nfs"]
    ocnf = bool(do_pdf & _ocnf_rotulados(pe["doc"], pe["desc"]))
    docnum = bool(do_pdf & set(re.findall(r"\d{3,}", pe["doc"])))
    cc = False
    for w in pe["works"]:
        nw = _norm(w)
        if len(nw) >= 6 and nw in pd["ndesc"]:
            cc = True
            break
    if not cc:
        mq = re.search(r"QD\s*([0-9A-Z]+)\s+LT\s*([0-9A-Z\-]+)", pd["ndesc"])
        if mq:
            pat = "QD " + mq.group(1) + " LT " + mq.group(2)
            cc = any(pat in _norm(w) for w in pe["works"])
    date = bool(pe["data"]) and pe["data"] == pd["data"]
    return ocnf, cc, date, docnum


# ------------------------------------------------------------------ casamento
def _vals(pe) -> set:
    """Valores aceitos do pagamento (nominal e valor pago com juros/desconto)."""
    return set(pe.get("valores") or [pe["valor"]])


def casar(pendentes: list[dict], pdfs: list[dict]) -> tuple[list, list, list]:
    """
    pendentes: registros de mc_api.montar_pagos SEM anexo.
    Retorna (certezas, duvidas, sem_par). Em cada certeza: pend['pdf'] e pend['motivo'].
    O PDF casa se o valor do nome bater com QUALQUER um dos valores do
    pagamento (nominal ou valor pago com juros/multa/desconto).
    """
    byval = defaultdict(list)
    for p in pdfs:
        byval[p["valor"]].append(p)

    for pe in pendentes:
        pe["status"] = None
        pe["cands"] = []
        vistos = set()
        for v in sorted(_vals(pe)):
            for pd in byval.get(v, []):
                if id(pd) in vistos:
                    continue
                vistos.add(id(pd))
                ocnf, cc, date, docnum = _features(pe, pd)
                pe["cands"].append({"pdf": pd, "ocnf": ocnf, "cc": cc, "date": date,
                                    "docnum": docnum,
                                    "score": (100 if ocnf else 0) + (10 if cc else 0)
                                             + (5 if docnum else 0) + (1 if date else 0)})

    def atribuir(filtro):
        mudou = True
        while mudou:
            mudou = False
            quer = defaultdict(list)
            for pe in pendentes:
                if pe["status"]:
                    continue
                for c in pe["cands"]:
                    if c["pdf"]["used_by"] is None and filtro(c):
                        quer[id(c["pdf"])].append(pe["paidId"])
            for pe in pendentes:
                if pe["status"]:
                    continue
                nv = [c for c in pe["cands"] if c["pdf"]["used_by"] is None and filtro(c)]
                if len(nv) == 1 and len(quer[id(nv[0]["pdf"])]) == 1:
                    nv[0]["pdf"]["used_by"] = pe["paidId"]
                    pe["match"] = nv[0]
                    pe["status"] = "CERTEZA"
                    mudou = True
                elif len(nv) > 1:
                    com_data = [c for c in nv if c["date"]]
                    if len(com_data) == 1:
                        pdx = com_data[0]["pdf"]
                        outros = [x for x in quer[id(pdx)] if x != pe["paidId"]]
                        if not outros:
                            pdx["used_by"] = pe["paidId"]
                            pe["match"] = com_data[0]
                            pe["status"] = "CERTEZA"
                            mudou = True

    atribuir(lambda c: c["ocnf"] and c["cc"])
    atribuir(lambda c: c["ocnf"])
    # O nº do documento cru só entra ACOMPANHADO do centro de custo: sozinho
    # ele é fraco demais para fechar CERTEZA (ver _features).
    atribuir(lambda c: c["docnum"] and c["cc"])
    atribuir(lambda c: c["cc"])

    for pe in pendentes:
        if pe["status"]:
            continue
        todos_val = [c["pdf"] for c in pe["cands"]]
        livres = [c for c in pe["cands"] if c["pdf"]["used_by"] is None]
        if not todos_val or not livres:
            pe["status"] = "SEM PAR"
            continue
        concorrentes = [q for q in pendentes if q is not pe and not q["status"]
                        and (_vals(q) & _vals(pe))]
        if len(todos_val) == 1 and len(livres) == 1 and livres[0]["score"] > 0 \
                and not concorrentes:
            livres[0]["pdf"]["used_by"] = pe["paidId"]
            pe["match"] = livres[0]
            pe["status"] = "CERTEZA"
            continue
        # Casar só pela data é permitido apenas quando NÃO existe nenhum
        # outro pagamento pendente com valor em comum (evita anexar errado
        # quando há vários pagamentos de mesmo valor no período).
        com_data = [c for c in livres if c["date"]]
        if len(com_data) == 1 and not concorrentes:
            pdx = com_data[0]["pdf"]
            pdx["used_by"] = pe["paidId"]
            pe["match"] = com_data[0]
            pe["status"] = "CERTEZA"
            continue
        pe["status"] = "DUVIDA"

    def motivo(pe):
        m = pe["match"]
        t = []
        if m["ocnf"]:
            t.append("OC/NF")
        if m.get("docnum"):
            t.append("nº do documento")
        if m["cc"]:
            t.append("centro de custo")
        if m["date"]:
            t.append("data")
        return " + ".join(t) or "valor único"

    certezas = [p for p in pendentes if p["status"] == "CERTEZA"]
    for p in certezas:
        p["pdf"] = p["match"]["pdf"]["fn"]
        p["motivo"] = motivo(p)
    duvidas = [p for p in pendentes if p["status"] == "DUVIDA"]
    sem_par = [p for p in pendentes if p["status"] == "SEM PAR"]
    return certezas, duvidas, sem_par
