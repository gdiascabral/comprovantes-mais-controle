# -*- coding: utf-8 -*-
"""
Casamento entre PDFs renomeados (padrão "VALOR - DESCRIÇÃO - DATA") e os
sub-pagamentos pendentes de comprovante no Mais Controle.

Critérios, do mais forte para o mais fraco (todos exigem o MESMO valor):
  1. nº de OC/NF do nome do PDF = nº do documento (ou aparece na descrição);
  2. nº do documento cru com centro de custo;
  3. centro de custo do PDF aparece nas obras/descrição do lançamento;
  3b. nº do documento = NF escrita no nome do PDF, na MESMA CONTA;
  4. favorecido do lançamento = recebedor do comprovante, na mesma conta e data;
  5. data igual (dd-mm) como desempate.

De onde saiu o pagamento (regra do dono, 14/09/2026): PDF que saiu de OUTRA
conta que não a cadastrada no lançamento nem entra na disputa. A `origem` é
(banco, conta) e quem a preenche é o Anexar -- do registro da baixa, para o
PDF, e do cadastro de contas, para o lançamento. Faltando um dos lados, a conta
não tira ninguém: arquivo posto à mão na pasta continua valendo como antes.

Regras de segurança:
  - cada PDF é usado uma vez só;
  - casamento ambíguo vai para DÚVIDA (nunca "chuta");
  - pagamento sem PDF de mesmo valor vai para SEM PAR.
"""
import os
import re
from collections import defaultdict
from pathlib import Path

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
        "origem": None,          # (banco, conta) -- o Anexar preenche
        "recebedor": None,       # quem recebeu -- o Anexar preenche
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


# ------------------------------------------------------------------ origem
def mesma_conta(a, b) -> bool | None:
    """O PDF saiu da conta do lançamento? None quando não dá para dizer.

    `a` e `b` são (banco, conta). Bancos diferentes já respondem "não", mesmo
    sem o número -- o registro antigo do Inter só sabe o banco. Mesmo banco e
    os dois números conhecidos respondem pelo número; faltando um, não se sabe.
    """
    if not a or not b or not a[0] or not b[0]:
        return None
    if _norm(a[0]) != _norm(b[0]):
        return False
    if a[1] and b[1]:
        return _norm(a[1]) == _norm(b[1])
    return None


#: Palavras que não distinguem ninguém num nome de empresa ou de pessoa.
_SEM_PESO = {"LTDA", "EIRELI", "EPP", "SPE", "CIA", "DAS", "DOS"}


def _palavras(nome) -> set[str]:
    """As palavras que identificam: 3+ letras, número ou numeral romano ("I" e
    "II" são SPEs diferentes do mesmo grupo)."""
    return {w for w in re.findall(r"[A-Z0-9]+", util.norm(nome or ""))
            if w not in _SEM_PESO
            and (len(w) >= 3 or w.isdigit() or re.fullmatch(r"[IVX]+", w))}


def mesmo_favorecido(favorecido, recebedor) -> bool:
    """O favorecido do ERP e quem recebeu no comprovante são a mesma pessoa?

    O nome MENOR tem de estar inteiro no maior, com pelo menos duas palavras.
    Palavras em comum não bastam: irmãos dividem sobrenome e as empresas de um
    grupo dividem o começo do nome (revisão do PR #94). Sinal fraco mesmo
    assim -- por isso só fecha CERTEZA junto com a conta e a data."""
    a, b = _palavras(favorecido), _palavras(recebedor)
    if len(a) < 2 or len(b) < 2:
        return False
    return a <= b or b <= a


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
        pe["fora_da_conta"] = 0
        vistos = set()
        for v in sorted(_vals(pe)):
            for pd in byval.get(v, []):
                if id(pd) in vistos:
                    continue
                vistos.add(id(pd))
                conta = mesma_conta(pe.get("origem"), pd.get("origem"))
                if conta is False:
                    pe["fora_da_conta"] += 1
                    continue
                ocnf, cc, date, docnum = _features(pe, pd)
                fav = conta is True and mesmo_favorecido(pe.get("favorecido"),
                                                         pd.get("recebedor"))
                # O nº do documento do ERP é o da NOTA: com a conta, só vale
                # contra NF escrita no nome do PDF. Contra OC, numa empresa de
                # uma conta só, era o nº do documento sozinho de novo -- e
                # trocava anexos (revisão do PR #94).
                docnf = bool(pd["nfs"] & set(re.findall(r"\d{3,}", pe["doc"])))
                # `conta` e `fav` ficam FORA do score: ele decide o "valor
                # único" das sobras, e somar ali afrouxaria essa regra.
                pe["cands"].append({"pdf": pd, "ocnf": ocnf, "cc": cc, "date": date,
                                    "docnum": docnum, "docnf": docnf,
                                    "conta": conta is True, "fav": fav,
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
    # ...ou a NF do nome do PDF, na conta de onde o pagamento saiu (regra do
    # dono). DEPOIS do centro de custo, que já tinha a precedência.
    atribuir(lambda c: c["docnf"] and c["conta"])
    # Favorecido = recebedor é fraco sozinho; `fav` só existe com a conta
    # batendo, e aqui ainda exige a data.
    atribuir(lambda c: c["fav"] and c["date"])

    for pe in pendentes:
        if pe["status"]:
            continue
        todos_val = [c["pdf"] for c in pe["cands"]]
        livres = [c for c in pe["cands"] if c["pdf"]["used_by"] is None]
        if not todos_val or not livres:
            pe["status"] = "SEM PAR"
            if todos_val:
                pe["motivo_sem_par"] = ("os PDFs de mesmo valor já foram usados "
                                        "por outros pagamentos")
            elif pe["fora_da_conta"]:
                pe["motivo_sem_par"] = (f"{pe['fora_da_conta']} PDF(s) de mesmo "
                                        "valor saíram de outra conta")
            else:
                pe["motivo_sem_par"] = "nenhum PDF com esse valor na pasta"
            continue
        concorrentes = [q for q in pendentes if q is not pe and not q["status"]
                        and (_vals(q) & _vals(pe))]

        def confiavel(c):
            # Com PDF de mesmo valor tirado da disputa por ser de OUTRA conta,
            # o que sobrou só fecha sozinho se a conta dele estiver CONFIRMADA:
            # de origem desconhecida, o certo pode ser justamente o excluído
            # (baixa lançada na conta errada do ERP). Revisão do PR #94.
            return not pe["fora_da_conta"] or c.get("conta")

        if len(todos_val) == 1 and len(livres) == 1 and livres[0]["score"] > 0 \
                and not concorrentes and confiavel(livres[0]):
            livres[0]["pdf"]["used_by"] = pe["paidId"]
            pe["match"] = livres[0]
            pe["status"] = "CERTEZA"
            continue
        # Casar só pela data é permitido apenas quando NÃO existe nenhum
        # outro pagamento pendente com valor em comum (evita anexar errado
        # quando há vários pagamentos de mesmo valor no período).
        com_data = [c for c in livres if c["date"]]
        if len(com_data) == 1 and not concorrentes and confiavel(com_data[0]):
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
        if m.get("docnum") or m.get("docnf"):
            t.append("nº do documento")
        if m.get("conta"):
            t.append("conta")
        if m.get("fav"):
            t.append("favorecido")
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
