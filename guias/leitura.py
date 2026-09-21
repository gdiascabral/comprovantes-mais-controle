# -*- coding: utf-8 -*-
"""Do texto de uma guia/boleto para valor, vencimento e número do documento.

`ler_texto` é pura de propósito: é nela que mora toda a regra, e é ela que o
teste exercita. `ler_pdf` só extrai o texto e delega — assim nenhum PDF real
precisa entrar no repositório, que é público.

Os boletos da contabilidade têm texto (não são imagem), então não há OCR aqui.
PDF sem texto devolve lista vazia, e quem chamou trata como "não consegui ler".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

import util

log = util.log(__name__)

#: `1.234,56` e `641,31`. O milhar é opcional e os centavos não: valor sem
#: centavos num boleto é quase sempre outro número da página (código, conta).
RE_VALOR = re.compile(r"R?\$?\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+),([0-9]{2})")
RE_VALOR_ROTULO = re.compile(
    r"(?:valor\s+(?:do\s+)?(?:documento|cobran[çc]a|total)?)\s*[:\-]?\s*"
    r"R?\$?\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+),([0-9]{2})", re.I)
RE_VENCIMENTO = re.compile(
    r"vencimento\s*[:\-]?\s*([0-3]?[0-9])[/.-]([01]?[0-9])[/.-](20[0-9]{2})", re.I)
RE_DOCUMENTO = re.compile(
    r"(?:nosso\s*n[uú]mero|n[uú]mero\s*(?:do\s*)?documento|documento)\s*"
    r"[:\-]?\s*([0-9][0-9./\-]{5,})", re.I)
#: A linha digitável do boleto: 47 dígitos com pontos e espaços, ou 44 corridos.
RE_LINHA = re.compile(r"\b([0-9]{5}[.\s][0-9]{5,6}[\s.][0-9]{5}[.\s][0-9]{6}"
                      r"[\s.][0-9]{5}[.\s][0-9]{6}[\s.][0-9][\s.][0-9]{14})\b")


@dataclass
class ItemLido:
    valor: Decimal | None = None
    vencimento: date | None = None
    documento: str = ""
    pagina: int = 1

    @property
    def tem_cobranca(self) -> bool:
        """Página que vale um lançamento: tem valor E (vencimento ou documento)."""
        return self.valor is not None and bool(self.vencimento or self.documento)


def _decimal(inteiro: str, centavos: str) -> Decimal | None:
    try:
        return Decimal(f"{inteiro.replace('.', '')}.{centavos}")
    except InvalidOperation:
        return None


def ler_texto(texto: str, pagina: int = 1) -> ItemLido:
    texto = texto or ""
    item = ItemLido(pagina=pagina)

    achado = RE_VALOR_ROTULO.search(texto) or RE_VALOR.search(texto)
    if achado:
        item.valor = _decimal(achado.group(1), achado.group(2))

    venc = RE_VENCIMENTO.search(texto)
    if venc:
        dia, mes, ano = (int(g) for g in venc.groups())
        try:
            item.vencimento = date(ano, mes, dia)
        except ValueError:
            log.warning("vencimento fora do calendário numa guia")

    doc = RE_DOCUMENTO.search(texto)
    if doc:
        item.documento = doc.group(1).strip()
    else:
        linha = RE_LINHA.search(texto)
        if linha:
            item.documento = linha.group(1).strip()
    return item


def _paginas_de_texto(caminho: Path) -> list[str]:
    """O texto de cada página. Isolado para o teste não precisar de PDF."""
    import pdfplumber
    with pdfplumber.open(str(caminho)) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


def ler_pdf(caminho: Path) -> list[ItemLido]:
    """Um item por página que tenha cobrança. Lista vazia = não deu para ler."""
    try:
        paginas = _paginas_de_texto(Path(caminho))
    except Exception:
        log.warning("não deu para abrir a guia com o pdfplumber", exc_info=True)
        return []
    itens = [ler_texto(t, i) for i, t in enumerate(paginas, start=1)]
    return [i for i in itens if i.tem_cobranca]
