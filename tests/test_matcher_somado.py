# -*- coding: utf-8 -*-
"""N comprovantes que somam um pagamento (aba "Anexar (novo)"). Puro; dados fictícios."""
from anexar import matcher
from anexar import matcher_somado as ms

A400 = "400,00 - OBRA MODELO OC 5555 - 22-10.pdf"
A600 = "600,00 - OBRA MODELO OC 5555 - 22-10.pdf"


def _pend(paid_id="P1", valor=100000, desc="COMPRA OC 5555", works=("OBRA MODELO",),
          data="2210", doc=""):
    return {"paidId": paid_id, "launchId": "L-" + paid_id, "valor": valor,
            "valores": [valor], "doc": doc, "desc": desc, "works": list(works),
            "data": data, "conta": "CONTA EXEMPLO - SICOOB",
            "favorecido": "Fornecedor Modelo Ltda", "dataFull": "22/10/2026",
            "categoria": ""}


def _rodar(pendentes, nomes, todos=None, preparar=None):
    pdfs = [matcher.parse_pdf(n) for n in nomes]
    if preparar:
        preparar(pendentes, pdfs)
    matcher.casar(pendentes, pdfs)
    return ms.casar_somados(pendentes, pdfs, todos=todos if todos is not None else pendentes), pdfs


def test_o_motivo_do_sem_par_e_o_do_matcher():
    pe = _pend()
    matcher.casar([pe], [])
    assert pe["motivo_sem_par"] == ms.MOTIVO_NENHUM_PDF


def test_dois_comprovantes_que_somam_exato_casam():
    pe = _pend()
    (somados, duvidas), pdfs = _rodar([pe], [A400, A600])
    assert somados == [pe] and duvidas == []
    assert pe["status"] == ms.STATUS_SOMA
    assert pe["pdfs"] == [A600, A400]
    assert pe["motivo"] == "soma exata de 2 comprovantes (OC/NF + centro de custo + data)"
    assert all(pd["used_by"] == "P1" for pd in pdfs)


def test_dois_conjuntos_possiveis_viram_duvida_e_nada_e_usado():
    pe = _pend()
    nomes = [A400, A600, "300,00 - OBRA MODELO OC 5555 - 22-10.pdf",
             "700,00 - OBRA MODELO OC 5555 - 22-10.pdf"]
    (somados, duvidas), pdfs = _rodar([pe], nomes)
    assert somados == [] and duvidas == [pe]
    assert "2 conjuntos" in pe["motivo_sem_par"]
    assert all(pd["used_by"] is None for pd in pdfs)


def test_soma_que_nao_bate_ao_centavo_nao_casa():
    pe = _pend()
    (somados, duvidas), _ = _rodar([pe], [A400, "599,99 - OBRA MODELO OC 5555 - 22-10.pdf"])
    assert somados == duvidas == [] and pe["status"] == "SEM PAR"


def test_comprovante_de_outra_data_nao_entra():
    pe = _pend()
    (somados, _d), _ = _rodar([pe], [A400, "600,00 - OBRA MODELO OC 5555 - 21-10.pdf"])
    assert somados == []


def test_comprovante_que_nao_aponta_o_pagamento_nao_entra():
    pe = _pend()
    (somados, _d), _ = _rodar([pe], [A400, "600,00 - OUTRA COISA - 22-10.pdf"])
    assert somados == []


def test_valor_de_outro_pago_do_periodo_nao_entra_na_soma():
    pe, outro = _pend(), _pend(paid_id="P2", valor=40000, desc="X", works=("OUTRA",))
    (somados, _d), _ = _rodar([pe], [A400, A600], todos=[pe, outro])
    assert somados == []


def test_pagamento_com_pdf_do_proprio_valor_fica_com_a_regra_de_sempre():
    pe = _pend()
    (somados, _d), _ = _rodar([pe], ["1.000,00 - OBRA MODELO OC 5555 - 22-10.pdf", A400, A600])
    assert pe["status"] == "CERTEZA" and somados == []


def test_comprovante_repetido_nao_soma():
    pe = _pend()
    nomes = ["500,00 - OBRA MODELO OC 5555 - 22-10.pdf",
             "500,00 - OBRA MODELO OC 5555 - 22-10 (2).pdf"]
    (somados, duvidas), _ = _rodar([pe], nomes)
    assert somados == [] and duvidas == [pe] and "repetem" in pe["motivo_sem_par"]


def test_comprovante_que_soma_para_dois_pagamentos_vira_duvida_dos_dois():
    a, b = _pend("PA", 100000), _pend("PB", 90000)
    nomes = [A400, A600, "500,00 - OBRA MODELO OC 5555 - 22-10.pdf"]
    (somados, duvidas), pdfs = _rodar([a, b], nomes)
    assert somados == [] and {p["paidId"] for p in duvidas} == {"PA", "PB"}
    assert all(pd["used_by"] is None for pd in pdfs)


def test_pdf_de_outra_conta_nao_entra():
    def contas(pendentes, pdfs):
        pendentes[0]["origem"] = ("SICOOB", "1")
        pdfs[1]["origem"] = ("INTER", "2")
    pe = _pend()
    (somados, _d), _ = _rodar([pe], [A400, A600], preparar=contas)
    assert somados == []


def test_mais_de_quatro_comprovantes_nao_soma():
    pe = _pend(valor=100000)
    nomes = [f"200,{c:02d} - OBRA MODELO OC 5555 - 22-10.pdf" for c in range(4)] + \
            ["199,94 - OBRA MODELO OC 5555 - 22-10.pdf"]
    (somados, _d), _ = _rodar([pe], nomes)
    assert somados == []                                   # precisaria de 5
