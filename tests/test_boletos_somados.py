# -*- coding: utf-8 -*-
"""Entrega 5 (A): um lançamento pago com N boletos. Dados fictícios — o repo é público."""
import ast
from datetime import date
from decimal import Decimal
from pathlib import Path

from pagamentos_dia import boletos_somados as bs
from pagamentos_dia import confirmacao, ocr_boleto, relatorio

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


# ------------------------------------------------------ a divisão (tarefa 2)
def _dividido(valores, itens=None, livres=None):
    itens = itens or [_item()]
    entradas = _entradas(itens, valores, livres)
    base = relatorio.montar_registros(entradas.selecionados, entradas.anexos, {}, entradas.textos)
    return base, bs.dividir(base, entradas)


def test_o_status_que_dispara_e_o_do_relatorio():
    (linha,) = _linhas(confirmacao.remontar(_entradas([_item()], [40000, 60000])))
    assert linha["status"] == bs.STATUS_VARIOS
    assert bs._OBS_VARIOS.fullmatch(linha["obs"].split(" · ")[0])


def test_boletos_que_somam_exato_viram_n_linhas():
    base, res = _dividido([40000, 60000])
    linhas = _linhas(res)
    assert [r["parte"] for r in linhas] == ["1/2", "2/2"]
    valores = [Decimal(str(r["valor"])) for r in linhas]
    assert sorted(valores) == [Decimal("400.00"), Decimal("600.00")]
    assert sum(valores) == Decimal("1000.00")
    assert {ocr_boleto.valor_da_linha(r["dados"]) for r in linhas} == {400.0, 600.0}
    assert all(r["status"] == bs.status_dividido(2) for r in linhas)
    assert all(r["id"] == "L1" for r in linhas)                   # o lançamento é o mesmo
    assert linhas[0]["descricao"] == linhas[1]["descricao"]       # o Anexar casa pela descrição
    assert not any(bs._OBS_VARIOS.fullmatch(p) for r in linhas for p in r["obs"].split(" · "))
    assert _linhas(base)[0]["dados"] == ""                        # o Resultado original não muda


def test_tres_boletos_que_somam_exato():
    _base, res = _dividido([20000, 30000, 50000])
    assert [r["parte"] for r in _linhas(res)] == ["1/3", "2/3", "3/3"]


def test_soma_que_nao_bate_ao_centavo_nao_divide_e_avisa():
    _base, res = _dividido([40000, 59999])
    (linha,) = _linhas(res)
    assert linha["status"] == bs.STATUS_VARIOS and linha["dados"] == ""
    assert "somam R$ 999,99" in linha["obs"] and "R$ 1.000,00" in linha["obs"]
    assert "não dividi" in bs.avisos(res)[0]


def test_parcelas_abertas_do_mesmo_titulo_nao_dividem():
    _base, res = _dividido([40000, 60000], itens=[_item(id="L1"), _item(id="L2")])
    assert [r["status"] for r in _linhas(res)] == [bs.STATUS_VARIOS] * 2
    assert all("2 parcelas em aberto" in r["obs"] for r in _linhas(res))


def test_titulo_com_pagamento_anterior_nao_divide():
    _base, res = _dividido([40000, 60000], itens=[_item(sumOfPaidValues=200.0)])
    (linha,) = _linhas(res)
    assert linha["status"] == bs.STATUS_VARIOS and "já tem pagamento" in linha["obs"]


def test_linha_que_nao_e_de_varios_boletos_passa_intacta():
    entradas = _entradas([_item(remainingValue=400.0)], [40000])
    base = relatorio.montar_registros(entradas.selecionados, entradas.anexos, {}, entradas.textos)
    assert bs.dividir(base, entradas).contas == base.contas


def test_avisos_dizem_que_o_lancamento_virou_n_boletos():
    _base, res = _dividido([40000, 60000])
    assert bs.avisos(res) == [
        "1 lançamento virou 2 boletos (somam exato) — conferir: Fornecedor Modelo Ltda, "
        f"R$ 1.000,00 ({CONTA})"]
