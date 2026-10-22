# -*- coding: utf-8 -*-
"""Entrega 5 (A): um lançamento pago com N boletos. Dados fictícios — o repo é público."""
import ast
from datetime import date
from pathlib import Path

from pagamentos_dia import confirmacao, ocr_boleto

DIA = date(2026, 10, 21)
CONTA = "CONTA EXEMPLO - SICOOB"
RAIZ = Path(__file__).resolve().parents[1]
OUTRO_LIVRE = "2680800035545486352881211"


def gera_linha(valor_centavos, fator=9999, livre="1570700024434375241770100"):
    """Linha digitável bancária com os DVs fechando (a de tests/test_casamento_html.py)."""
    b43 = "3419" + f"{fator:04d}" + f"{valor_centavos:010d}" + livre
    b = b43[:4] + str(ocr_boleto._mod11_geral(b43)) + b43[4:]
    campos = [b[0:4] + b[19:24], b[24:34], b[34:44]]
    c = [x + str(ocr_boleto._mod10(x)) for x in campos]
    linha = (f"{c[0][:5]}.{c[0][5:]} {c[1][:5]}.{c[1][5:]} "
             f"{c[2][:5]}.{c[2][5:]} {b[4]} {b[5:19]}")
    assert ocr_boleto.valida(linha)
    return linha


def _anexo(nome, url):
    return {"filename": nome, "tagName": "Boleto", "extension": ".pdf", "downloadUrl": url}


def _item(**extra):
    base = {"id": "L1", "tradePayableId": "T1", "paidTo": "Fornecedor Modelo Ltda",
            "remainingValue": 1000.0, "plannedDate": "2026-10-21", "paid": False,
            "tradePayableAccount": {"name": CONTA}, "tradePayablePaymentMethod": "Boleto",
            "documentNumber": "64000", "costCentreDetails": [{"workName": "OBRA MODELO"}]}
    base.update(extra)
    return base


def _linhas_dos_boletos(valores_centavos, livres=None):
    livres = livres or [None] * len(valores_centavos)
    return [gera_linha(v, livre=l) if l else gera_linha(v)
            for v, l in zip(valores_centavos, livres)]


def _entradas(itens, valores_centavos, livres=None, **k):
    linhas = _linhas_dos_boletos(valores_centavos, livres)
    anexos = {"T1": [_anexo(f"boleto {i}", f"u{i}") for i in range(1, len(linhas) + 1)]}
    textos = {f"u{i}": f"Banco Exemplo\n{ln}\n" for i, ln in enumerate(linhas, 1)}
    return confirmacao.Entradas(
        selecionados=itens, anexos=anexos, overviews={}, textos=textos, urls_ocr=set(),
        cadastro_reembolso=None, regras_fornecedor={}, participantes={},
        periodo=(DIA, DIA), **k)


def _linhas(resultado):
    return [r for regs in resultado.contas.values() for r in regs]


# ------------------------------------------------------ o caso de hoje
def test_dois_boletos_que_somam_o_lancamento_viram_uma_linha_de_varios_boletos():
    """O caso real: 400 + 600 anexados a um lançamento de 1.000. Hoje nenhuma
    linha tem o valor do lançamento e a linha sai sem dado de pagamento."""
    (linha,) = _linhas(confirmacao.remontar(_entradas([_item()], [40000, 60000])))
    assert linha["status"] == "ATENÇÃO — vários boletos no título"
    assert linha["dados"] == ""
    assert linha["obs"].split(" · ")[0] == ("Há 2 boletos no título, não dá para saber "
                                            "qual é desta parcela — conferir antes de pagar")


def test_o_frame_da_remessa_nunca_liga_a_divisao():
    """Guarda: a Remessa/Retorno monta as Entradas dela sem a chave nova."""
    arvore = ast.parse((RAIZ / "pagamentos_dia/pagamentos_frame.py").read_text(encoding="utf-8"))
    assert not [kw for no in ast.walk(arvore) if isinstance(no, ast.Call)
                for kw in no.keywords if kw.arg == "dividir_boletos"]
