# -*- coding: utf-8 -*-
"""O leitor de PDF dos contratos: por página, preguiçoso, OCR só onde falta.

Os PDFs são montados aqui mesmo, à mão, com texto ASCII inventado — não há
contrato real no repositório."""
import pytest

pdfplumber = pytest.importorskip("pdfplumber")

from contratos.leitura import LeitorPDF, abrir_pdf  # noqa: E402


def _pdf(paginas: list[str]) -> bytes:
    """Um PDF mínimo com uma página por item; item vazio = página sem texto."""
    n = len(paginas)
    fonte = 3 + 2 * n
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode()]
    for i, txt in enumerate(paginas):
        cid = 4 + 2 * i
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Contents {cid} 0 R /Resources << /Font << /F1 {fonte} 0 R >> >> >>"
            .encode())
        linhas = [ln.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                  for ln in (txt or "").splitlines()]
        corpo = "BT /F1 12 Tf 72 720 Td 14 TL " + \
            " ".join(f"({ln}) Tj T*" for ln in linhas) + " ET"
        stream = corpo.encode("latin-1")
        objs.append(b"<< /Length " + str(len(stream)).encode()
                    + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    saida = bytearray(b"%PDF-1.4\n")
    offsets = []
    for num, obj in enumerate(objs, 1):
        offsets.append(len(saida))
        saida += f"{num} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(saida)
    saida += f"xref\n0 {len(objs) + 1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets:
        saida += f"{off:010d} 00000 n \n".encode()
    saida += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\n"
              f"startxref\n{xref}\n%%EOF\n").encode()
    return bytes(saida)


PAG1 = "CONTRATO DE COMPRA E VENDA ENTRE VENDEDOR E COMPRADOR PAGINA UM"
PAG2 = "IMOVEL OBJETO RUA X QD 1 LT 2 CASA 01 PAGINA DOIS DO CONTRATO"
PAG3 = "ASSINATURAS DAS PARTES NA PAGINA TRES DO CONTRATO EXEMPLO"


def test_le_a_camada_de_texto_por_pagina():
    leitor = LeitorPDF(_pdf([PAG1, PAG2, PAG3]))
    assert leitor.total == 3
    so_a_primeira = leitor.texto(1)
    assert "PAGINA UM" in so_a_primeira and "PAGINA DOIS" not in so_a_primeira
    assert leitor.tem_mais(1)
    tudo = leitor.texto()
    assert "PAGINA DOIS" in tudo and "PAGINA TRES" in tudo
    assert not leitor.tem_mais(3)
    assert leitor.origem == "camada de texto" and not leitor.usou_ocr


def test_nao_rele_o_que_ja_leu(monkeypatch):
    leitor = LeitorPDF(_pdf([PAG1, PAG2]))
    chamadas = []
    original = LeitorPDF._ler

    def espiao(self, indices):
        chamadas.append(list(indices))
        return original(self, indices)

    monkeypatch.setattr(LeitorPDF, "_ler", espiao)
    leitor.texto(1)
    leitor.texto(1)
    leitor.texto()
    assert chamadas == [[0], [1]]


def test_pagina_sem_texto_vai_para_o_ocr(monkeypatch):
    pedidos = []

    def ocr_falso(self, pl, indices):
        pedidos.append(list(indices))
        return {i: "TEXTO VINDO DO OCR DA PAGINA" for i in indices}

    monkeypatch.setattr(LeitorPDF, "_ocr", ocr_falso)
    leitor = LeitorPDF(_pdf([PAG1, "", PAG3]))
    tudo = leitor.texto()
    assert pedidos == [[1]]                       # só a página sem texto
    assert "TEXTO VINDO DO OCR" in tudo and "PAGINA UM" in tudo
    assert leitor.usou_ocr and leitor.origem == "OCR"


def test_sem_ocr_disponivel_a_pagina_fica_vazia_e_a_origem_avisa(monkeypatch):
    def sem_ocr(self, pl, indices):
        self.ocr_indisponivel = True
        return {}

    monkeypatch.setattr(LeitorPDF, "_ocr", sem_ocr)
    leitor = LeitorPDF(_pdf(["", ""]))
    assert leitor.texto().strip() == ""
    assert leitor.origem == "sem texto e sem OCR disponível"


def test_bytes_que_nao_sao_pdf_nao_quebram():
    leitor = abrir_pdf(b"isto nao e um pdf")
    assert leitor.total == 0
    assert leitor.texto() == ""
    assert leitor.erro and leitor.origem.startswith("não li o PDF")


def test_vazio_nao_quebra():
    assert LeitorPDF(b"").total == 0
    assert LeitorPDF(None).texto() == ""
