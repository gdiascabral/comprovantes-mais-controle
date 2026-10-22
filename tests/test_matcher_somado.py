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


# ---------------------------------------------------------------- conserto 1
D400 = "400,00 - OBRA MODELO DIARIA - 22-10.pdf"
F600 = "600,00 - OBRA MODELO FRETE - 22-10.pdf"
B1 = "1" * 44
B2 = "2" * 44
B3 = "3" * 44


def _conta(pendentes, pdfs):
    for pe in pendentes:
        pe["origem"] = ("SICOOB", "1")
    for pd in pdfs:
        pd["origem"] = ("SICOOB", "1")


def test_a1_comprovantes_de_outros_pagos_da_obra_nao_casam():
    pe = _pend(desc="COMPRA")
    (somados, _d), pdfs = _rodar([pe], [D400, F600])
    assert somados == [] and all(pd["used_by"] is None for pd in pdfs)


def test_a1_descricoes_diferentes_nao_casam_nem_com_a_conta_confirmada():
    pe = _pend(desc="COMPRA")
    (somados, _d), _ = _rodar([pe], [D400, F600], preparar=_conta)
    assert somados == []


def test_a1_centro_de_custo_sozinho_sem_conta_confirmada_nao_casa():
    pe = _pend(desc="COMPRA")
    nomes = ["400,00 - OBRA MODELO DIARIA - 22-10.pdf", "600,00 - OBRA MODELO DIARIA - 22-10.pdf"]
    (somados, _d), _ = _rodar([pe], nomes)
    assert somados == []


def test_a1_centro_de_custo_com_a_conta_confirmada_casa():
    pe = _pend(desc="COMPRA")
    nomes = ["400,00 - OBRA MODELO DIARIA - 22-10.pdf", "600,00 - OBRA MODELO DIARIA - 22-10.pdf"]
    (somados, _d), _ = _rodar([pe], nomes, preparar=_conta)
    assert somados == [pe] and pe["motivo"] == "soma exata de 2 comprovantes (centro de custo + data)"


def test_a1_mesma_oc_com_descricoes_diferentes_nao_casa():
    pe = _pend()
    (somados, _d), _ = _rodar([pe], [A400, "600,00 - OBRA MODELO OC 5555 FRETE - 22-10.pdf"])
    assert somados == []


def test_a1_recebedor_diferente_do_favorecido_nao_entra():
    def docs(pendentes, pdfs):
        pendentes[0]["doc_favorecido"] = "12.345.678/0001-00"
        pdfs[0]["doc_recebedor"] = "12345678000100"
        pdfs[1]["doc_recebedor"] = "98.765.432/0001-00"
    pe = _pend()
    (somados, _d), _ = _rodar([pe], [A400, A600], preparar=docs)
    assert somados == []


def test_a1_recebedor_igual_ao_favorecido_casa():
    def docs(pendentes, pdfs):
        pendentes[0]["doc_favorecido"] = "12.345.678/0001-00"
        for pd in pdfs:
            pd["doc_recebedor"] = "12345678000100"
    pe = _pend()
    (somados, _d), _ = _rodar([pe], [A400, A600], preparar=docs)
    assert somados == [pe]


def test_m1_pdf_com_codigo_de_outro_pendente_nao_entra():
    outro = _pend("P2", 77700, desc="X", works=("OUTRA",))
    outro["barras"] = {B1}

    def cod(pendentes, pdfs):
        pdfs[0]["barras"] = {B1}
    pe = _pend()
    (somados, _d), _ = _rodar([pe, outro], [A400, A600], preparar=cod)
    assert somados == []


def test_m1_pdf_com_codigo_do_proprio_pagamento_entra():
    def cod(pendentes, pdfs):
        pendentes[0]["barras"] = {B1, B2}
        pdfs[0]["barras"] = {B1}
        pdfs[1]["barras"] = {B2}
    pe = _pend()
    (somados, _d), _ = _rodar([pe], [A400, A600], preparar=cod)
    assert somados == [pe]


def test_m2_outro_pendente_de_mesmo_valor_obra_e_data_vira_duvida():
    pe, gemeo = _pend("P1"), _pend("P2", desc="COMPRA OC 7777")
    (somados, duvidas), pdfs = _rodar([pe, gemeo], [A400, A600])
    assert somados == [] and pe in duvidas
    assert all(pd["used_by"] is None for pd in pdfs)


def test_m3_partes_iguais_com_codigos_diferentes_casam():
    def cod(pendentes, pdfs):
        pdfs[0]["barras"] = {B1}
        pdfs[1]["barras"] = {B3}
    pe = _pend()
    nomes = ["500,00 - OBRA MODELO OC 5555 - 22-10.pdf",
             "500,00 - OBRA MODELO OC 5555 - 22-10 (2).pdf"]
    (somados, duvidas), _ = _rodar([pe], nomes, preparar=cod)
    assert somados == [pe] and duvidas == []


def test_m3_partes_iguais_com_o_mesmo_codigo_continuam_repetidas():
    def cod(pendentes, pdfs):
        pdfs[0]["barras"] = {B1}
        pdfs[1]["barras"] = {B1}
    pe = _pend()
    nomes = ["500,00 - OBRA MODELO OC 5555 - 22-10.pdf",
             "500,00 - OBRA MODELO OC 5555 - 22-10 (2).pdf"]
    (somados, duvidas), _ = _rodar([pe], nomes, preparar=cod)
    assert somados == [] and duvidas == [pe]


def test_b1_pdf_de_valor_zero_nao_entra_na_soma():
    pe = _pend()
    nomes = [A400, A600, "0,00 - OBRA MODELO OC 5555 - 22-10.pdf"]
    (somados, _d), pdfs = _rodar([pe], nomes)
    assert somados == [pe] and pdfs[2]["used_by"] is None


def test_b1_pendente_de_valor_zero_e_ignorado():
    pe = _pend(valor=0)
    pdfs = [matcher.parse_pdf(n) for n in ("0,00 - OBRA MODELO OC 5555 - 22-10.pdf",
                                          "0,00 - OBRA MODELO OC 5555 - 22-10 (2).pdf")]
    pe["status"], pe["motivo_sem_par"] = "SEM PAR", ms.MOTIVO_NENHUM_PDF
    assert ms.casar_somados([pe], pdfs, todos=[pe]) == ([], [])
