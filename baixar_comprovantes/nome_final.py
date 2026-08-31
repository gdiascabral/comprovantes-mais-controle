# -*- coding: utf-8 -*-
"""O nome do arquivo, no padrão do Separar e Renomear.

    2.980,00 - RPB 24 QD 26A LT 08 OC 6974 - 24-08.pdf

**Chama a função de lá, não copia o padrão.** `separar_renomear.nome_arquivo`
é quem sabe montar esse nome; reproduzi-lo aqui criaria duas verdades que
divergem no dia em que alguém mudar a regra num lado só — e divergem em
silêncio, porque nada quebra: os arquivos só passam a sair diferentes.

Renomear na BAIXA, e não depois: economiza uma passada e evita o erro de
esquecer a passada.

**De onde vem cada campo, e por que não é do PDF.** O Inter entrega valor,
data, descrição, favorecido e pagador no JSON da API — ler o PDF para
descobrir o que já se tem seria trabalho e risco de graça. O Sicoob entrega
valor e data, mas NÃO o favorecido: ele só existe dentro do comprovante, e é
por isso (e só por isso) que o caminho do Sicoob passa pelo documento.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
for _p in (_RAIZ, _RAIZ / "separar_renomear"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))


def _renomeador():
    """O módulo do Renomear, importado na hora de usar.

    Tardio de propósito: ele carrega `pdfplumber` e `tkinter` no topo, e quem
    só quer baixar comprovante não deve pagar isso na abertura do app."""
    import separar_renomear

    return separar_renomear


def brl(valor) -> str:
    """`2980.0` -> `2.980,00`. É a forma que o Renomear espera receber."""
    try:
        return f"{float(valor):,.2f}".replace(",", "X").replace(
            ".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return ""


def _valor_de_texto(texto: str) -> str:
    """`R$ 108,39` -> `108,39`. O Inter manda com o cifrão na 2ª via."""
    achado = re.search(r"([\d.]+,\d{2})", str(texto or ""))
    return achado.group(1) if achado else ""


def nomear(campos: dict) -> str:
    """O nome final, sem extensão. "" quando não há como montar."""
    try:
        return _renomeador().nome_arquivo(campos)
    except Exception:                                        # noqa: BLE001
        return ""


# ------------------------------------------------------------------- Inter

def do_pix(mov: dict) -> dict:
    """Os campos de um Pix enviado, direto do JSON — sem abrir o PDF."""
    detalhe = mov.get("detalhePix") or {}
    descricao = ""
    for onde in (mov.get("descricao"), detalhe.get("descricaoPagamento"),
                 detalhe.get("campoLivre")):
        if (onde or "").strip():
            descricao = onde.strip()
            break
    return {"valor": brl(mov.get("valor")),
            "data": mov.get("data") or "",
            "desc": descricao or None,
            "dest": (mov.get("nome") or "").strip() or None,
            "pag": (detalhe.get("nomeFantasiaPagador") or "").strip() or None}


def do_2via(item: dict) -> dict:
    """Os campos de um pagamento da 2ª via do Inter."""
    pagamento = item.get("pagamento") or {}
    descricao = (item.get("descricao")
                 or pagamento.get("complementoHistorico") or "").strip()
    return {"valor": _valor_de_texto(item.get("valor")),
            "data": item.get("dataEfetivacao") or "",
            "desc": descricao or None,
            "dest": None,
            "pag": (item.get("nomeRemetente") or "").strip() or None}


# ------------------------------------------------------------------ Sicoob

def favorecido_do_comprovante(texto: str) -> str:
    """Quem recebeu, lido do comprovante do Sicoob.

    Cada tipo escreve num lugar: BOLETO no bloco "Beneficiário", campo
    "Nome/Razão Social"; TRANSFERÊNCIA no bloco "Crédito", na linha da conta
    (`Conta 6.135-2 / ROCHA SANTIAGO ENGENHARIA LTDA`).

    A âncora é o BLOCO, e não o rótulo: "Nome/Razão social" aparece duas vezes
    no comprovante de boleto, e a primeira ocorrência pode ser a do PAGADOR —
    que é justamente quem não interessa aqui.
    """
    linhas = [l.strip() for l in (texto or "").splitlines()]

    for i, linha in enumerate(linhas):
        if re.fullmatch(r"Benefici[áa]rio", linha, re.I):
            for seguinte in linhas[i + 1:i + 4]:
                achado = re.match(r"Nome/Raz[ãa]o [Ss]ocial\s+(.+)", seguinte)
                if achado:
                    return achado.group(1).strip()

    for i, linha in enumerate(linhas):
        if re.fullmatch(r"Cr[ée]dito", linha, re.I):
            for seguinte in linhas[i + 1:i + 4]:
                achado = re.match(r"Conta\s+[\d.\-]+\s*/\s*(.+)", seguinte)
                if achado:
                    return achado.group(1).strip()
    return ""


def data_do_comprovante(texto: str) -> str:
    """A data do PAGAMENTO, e não a da impressão.

    O topo do comprovante traz "31/08/2026 12:04:52", que é quando o arquivo
    foi gerado. Foi essa que o parser do Renomear pegou ao ler estes PDFs, e
    por isso os 23 saíram carimbados com a data de hoje."""
    for padrao in (r"Pagamento\s+(\d{2}/\d{2}/\d{4})",
                   r"Data do lan[çc]amento\s+(\d{2}/\d{2}/\d{4})",
                   r"Realizado\s+(\d{2}/\d{2}/\d{4})"):
        achado = re.search(padrao, texto or "")
        if achado:
            return achado.group(1)
    return ""


def texto_do_pdf(caminho) -> str:
    """A primeira página em texto. "" quando não dá para ler.

    Nunca levanta: um PDF ilegível vira arquivo com o nome de origem, que é
    achável. Derrubar o lote por causa de um nome seria trocar o problema
    pequeno pelo grande."""
    try:
        import pdfplumber

        with pdfplumber.open(caminho) as doc:
            return doc.pages[0].extract_text() or ""
    except Exception:                                        # noqa: BLE001
        return ""


def do_sicoob(item: dict, texto: str) -> dict:
    """Valor e data do JSON (certos); favorecido do documento (só lá existe).

    A data também é conferida no documento: o JSON traz `dataLancamento`, e o
    comprovante traz a do pagamento — quando as duas existem, vale a do
    documento, que é o que o banco afirma no papel."""
    valor = item.get("valorLancamento")
    return {"valor": brl(valor) or _valor_de_texto(valor),
            "data": data_do_comprovante(texto)
            or _data_do_item(item.get("dataLancamento")),
            "desc": None,
            "dest": favorecido_do_comprovante(texto) or None,
            "pag": None}


def _data_do_item(texto: str) -> str:
    """`2026-08-24 00:00:00.0` -> `24/08/2026`."""
    achado = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})", str(texto or ""))
    if not achado:
        return ""
    ano, mes, dia = achado.groups()
    return f"{dia}/{mes}/{ano}"


# ------------------------------------------------------------- o arquivo

def renomear(caminho: Path, campos: dict) -> Path:
    """Renomeia o arquivo já gravado. Devolve o novo caminho — ou o antigo.

    Falhar aqui NUNCA perde comprovante: sem nome montável, ou com o disco
    recusando, o arquivo fica onde está, com o nome de origem. Ele é achável
    assim; o que não se pode é sumir com ele por causa de um nome.

    O desempate segue o do Renomear — ` (2)`, ` (3)` —, e não o `_1` do
    downloader: dois arquivos com o mesmo nome final vêm do mesmo padrão, e
    quem os vê na pasta espera a numeração de lá.
    """
    base = nomear(campos)
    if not base:
        return caminho
    alvo = caminho.parent / f"{base}.pdf"
    n = 2
    while alvo.exists():
        alvo = caminho.parent / f"{base} ({n}).pdf"
        n += 1
    try:
        return caminho.rename(alvo)
    except OSError:
        return caminho
