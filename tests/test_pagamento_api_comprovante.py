# -*- coding: utf-8 -*-
"""O PDF do comprovante abre num leitor de verdade (pypdf, que já está no exe)."""
from datetime import date
from decimal import Decimal

from pypdf import PdfReader

from pagamento_api import comprovante as cp
from pagamento_api import lote as lt


def test_pdf_do_comprovante_abre_e_tem_a_descricao(tmp_path):
    item = lt.ItemLote(3, "T3", "T3", "OBRA X - SICOOB", lt.BOLETO, "3" * 44,
                       Decimal("152.30"), "FORNECEDOR (A)", "", "OBRA X NF 12 OC 7")
    p = cp.gerar_pdf(tmp_path, item, {"situacaoPagamento": "EFETIVADO", "valorPagamento": 152.3},
                     date(2026, 11, 27))
    assert p.name == "2026-11-27 OBRA X NF 12 OC 7 R$ 152,30 item 3.pdf"
    texto = PdfReader(str(p)).pages[0].extract_text()
    assert "OBRA X NF 12 OC 7" in texto and "FORNECEDOR (A)" in texto and "EFETIVADO" in texto


def test_bruto_do_convenio_volta_igual(tmp_path):
    item = lt.ItemLote(1, "T1", "T1", "C - SICOOB", lt.CONVENIO, "8" * 44, Decimal("1.00"), "F", "", "D")
    cp.salvar_bruto(tmp_path, item, "convenio", {"comprovante": "QUJD", "arrecadacao": {"nsu": 1}})
    assert cp.ler_bruto(tmp_path, item, "convenio") == {"comprovante": "QUJD", "arrecadacao": {"nsu": 1}}
    outro = lt.ItemLote(2, "T2", "T2", "C - SICOOB", lt.CONVENIO, "8" * 44, Decimal("1.00"), "F", "", "D")
    assert cp.ler_bruto(tmp_path, outro, "convenio") is None
