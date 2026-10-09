# -*- coding: utf-8 -*-
"""Pix copia-e-cola lido do QR Code que vem DENTRO dos anexos.

Boleto com "Pague com Pix", fatura de concessionária, guia de prefeitura,
print de cartório: o QR Code impresso é um BR Code, e o BR Code é o próprio
copia-e-cola. Até 08/10/2026 o app não o lia ("decodificar pediria biblioteca
que o exe não tem", `relatorio.anexo_para_pagar_a_mao`) — quem pagava abria
o anexo e apontava o celular. Pedido do dono: ler sempre e trazer o código
pronto para colar no HTML.

POR QUE NÃO BASTA "O LEITOR LEU"
--------------------------------
O mesmo cuidado do `ocr_boleto`: um código errado paga outra pessoa. Só é
aceito o que passa por TRÊS provas:

1. **É Pix**: começa no indicador de formato (`000201`) e traz o GUI
   `br.gov.bcb.pix` — QR de site, de NF-e (o da SEFAZ) e de rastreio não são.
2. **O CRC fecha**: o BR Code termina no CRC16 de tudo o que vem antes
   (campo 63). Leitura truncada ou trocada derruba o CRC.
3. **O resto do app o reconhece**: casa inteiro com `regras.PIX_COPIA_COLA`.
   Sem isto, o HTML trataria o código como chave comum e o "Copiar" levaria
   só os dígitos dele — um código destruído com cara de pronto.

Quem DECIDE se o código paga o lançamento (valor, comprovante, reembolso,
prefeitura) é o `relatorio`; aqui só se lê e se confere a forma.

A biblioteca é a `zxing-cpp` (1 MB, embutida no exe pelo `motor.py`). Faltando
ela — motor velho —, `ler` devolve lista vazia e o app segue como antes.
"""
from __future__ import annotations

import io
import re

from . import regras_pagamento as regras

#: Páginas lidas por PDF. O QR do boleto mora na 1ª página; o do boleto que
#: veio junto da NF ("merge"), na 2ª. Mais que isso custa tempo à toa.
PAGINAS = 3
#: Resolução da renderização. Medido em 08/10/2026 sobre 83 PDFs reais: a 150
#: dpi um boleto com QR pequeno não lia, a 200 lia todos (0,23 s por PDF).
DPI = 200

_GUI_PIX = "br.gov.bcb.pix"


# --------------------------------------------------------------------------
# Forma do BR Code
# --------------------------------------------------------------------------
def crc16(texto: str) -> str:
    """CRC16-CCITT (polinômio 0x1021, início 0xFFFF), como o BR Code exige."""
    crc = 0xFFFF
    for byte in texto.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return f"{crc:04X}"


def campos(codigo: str) -> dict:
    """Os campos de primeiro nível (ID de 2 dígitos + tamanho de 2 + valor).

    Tamanho que não é número ou que passa do fim para a leitura: devolve o
    que leu até ali, e quem consulta um campo ausente recebe vazio."""
    saida, i = {}, 0
    while i + 4 <= len(codigo):
        tag, tam = codigo[i:i + 2], codigo[i + 2:i + 4]
        if not tam.isdigit() or i + 4 + int(tam) > len(codigo):
            break
        saida[tag] = codigo[i + 4:i + 4 + int(tam)]
        i += 4 + int(tam)
    return saida


def valido(codigo) -> bool:
    """As três provas do cabeçalho do módulo."""
    c = str(codigo or "").strip()
    if not c.startswith("000201") or len(c) < 30:
        return False
    if _GUI_PIX not in c.lower():
        return False
    if c[-8:-4] != "6304" or c[-4:] != crc16(c[:-4]):
        return False
    return bool(regras.PIX_COPIA_COLA.fullmatch(re.sub(r"\s+", "", c)))


def valor(codigo: str) -> float | None:
    """O valor embutido (campo 54), ou None quando o código não traz valor
    (QR estático sem valor, ou dinâmico que só o informa na consulta)."""
    bruto = campos(codigo).get("54", "")
    try:
        return round(float(bruto), 2) if bruto else None
    except ValueError:
        return None


def recebedor(codigo: str) -> str:
    """Nome de quem recebe (campo 59), como o emissor o escreveu."""
    return campos(codigo).get("59", "").strip()


def cidade(codigo: str) -> str:
    return campos(codigo).get("60", "").strip()


# --------------------------------------------------------------------------
# Leitura
# --------------------------------------------------------------------------
def _imagens(dados: bytes, eh_pdf: bool):
    """As imagens onde procurar QR: as primeiras páginas do PDF, renderizadas,
    ou a própria imagem do anexo."""
    if eh_pdf:
        import pypdfium2 as pdfium          # vem com o pdfplumber
        doc = pdfium.PdfDocument(dados)
        try:
            for i in range(min(len(doc), PAGINAS)):
                yield doc[i].render(scale=DPI / 72, grayscale=True).to_pil()
        finally:
            doc.close()
    else:
        from PIL import Image
        with Image.open(io.BytesIO(dados)) as img:
            img.load()
            yield img


def ler(dados: bytes, eh_pdf: bool) -> list[str]:
    """Os Pix copia-e-cola VÁLIDOS dos QR Codes do anexo, sem repetição e na
    ordem em que aparecem. Falha de leitura não é erro: devolve lista vazia,
    e o anexo segue sendo lido como sempre foi (texto e OCR)."""
    if not dados:
        return []
    try:
        import zxingcpp
    except Exception:                                     # pragma: no cover
        return []
    achados: list[str] = []
    try:
        for img in _imagens(dados, eh_pdf):
            for b in zxingcpp.read_barcodes(img, formats=zxingcpp.BarcodeFormat.QRCode):
                texto = (b.text or "").strip()
                if valido(texto) and texto not in achados:
                    achados.append(texto)
    except Exception:
        return achados
    return achados
