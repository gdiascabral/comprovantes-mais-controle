# -*- coding: utf-8 -*-
"""Qual anexo é o contrato de financiamento.

Os 52 nomes abaixo são os de uma obra REAL, com o nome de pessoa trocado — é o
formato que importa, e o repositório é público. Eles trazem de graça três
armadilhas que ninguém inventaria: a obra escrita errada dentro do arquivo
(QD 26 numa obra QD 46), a versão sem espaço (QD46 LT18) e anexos repetidos.
"""
from contratos.escolha import (comeca_com_contrato, contrato_de,
                               tem_qualificador)

# Os 52 anexos da obra TB 21 QD 46 LT 18, como o ERP devolve.
NOMES = [
    "Planilha de pintor - TB 21 QD 26 LT 18 .pdf",
    "Medição mestre de obras - TB 21 QD 26 LT 18 .pdf",
    "Orçamento mármores e granitos - TB 21 QD 26 LT 18 .xlsx",
    "Medição elétrica - TB 21 QD 46 LT 18 .pdf",
    "Medição pintor - TB 21 QD 46 LT 18 .pdf",
    "Planilha de medições e orçamentos - TB 21 QD 46 LT 18 .xlsx",
    "CERTIDÃO CS 01 - TB 21 QD 46 LT 18 .pdf",
    "CERTIDÃO MÃE - TB 21 QD 46 LT 18 .pdf",
    "CERTIDÃO CS 02- TB 21 QD 46 LT 18 .pdf",
    "ESCRITURA - TB 21 QD 46 LT 18 .pdf",
    "ART - TB 21 QD 46 LT 18 .pdf",
    "ART DE SUBSTITUIÇÃO - TB 21 QD 46 LT 18 .pdf",
    "CONTRATO EMPREITA - NOME DO EMPREITEIRO - TB 21 QD 46 LT 18 .pdf",
    "ALVARA - TB 21 QD 46 LT 18 .pdf",
    "ART DE ACRÉSCIMO - TB 21 QD 46 LT 18 .pdf",
    "CNO - TB 21 QD 46 LT 18 .pdf",
    "MEMÓRIA DE CÁLCULO - TB 21 QD 46 LT 18 .pdf",
    "CND TB 21 QD 46 LT 18 .pdf",
    "SCPO - TB 21 QD 46 LT 18 .pdf",
    "HABITE-SE -  TB 21 QD 46 LT 18 .pdf",
    "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 .pdf",
    "RCPM CS2 - TB 21 QD 46 LT 18 .pdf",
    "DISTRATO TB 21 QD 46 LT 18 C1 .pdf",
    "CONTRATO TB 21 QD 46 LT 18 CS 02 .pdf",
    "CONTRATO DE COMPRA E VENDA TB 21 QD46 LT18 CS 01 .pdf",
    "RCPM CS1 - TB 21 QD 46 LT 18 .pdf",
    "TERMO DE ENTREGA TB 21 QD 46 LT 18 CS 02 .pdf",
    "CONTRATO TB 21 QD 46 LT 18 CS 01 .pdf",
    "RET - TB 21 QD 46 LT 18 .pdf",
    "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 02 .pdf",
    "MEMORIAL CS1 - TB 21 QD 46 LT 18 .pdf",
    "DECLARACAO ART CS1 - TB 21 QD 46 LT 18 .pdf",
    "DECLARACAO ART - TB 21 QD 46 LT 18 .pdf",
    "MEMORIAL CS2 - TB 21 QD 46 LT 18 .pdf",
    "HIDROSSANITARIO - TB 21 QD 46 LT 18 CS 02 .pdf",
    "BANCADAS - TB 21 QD 46 LT 18 CS 02 .pdf",
    "HIDRO GERAL .pdf",
    "ELÉTRICO - TB 21 QD 46 LT 18 .pdf",
    "MADEIRAMENTO TELHADO .pdf",
    "HIDROSSANITARIO - TB 21 QD 46 LT 18 CS 01 .pdf",
    "BANCADAS - TB 21 QD 46 LT 18 CS 01 .pdf",
    "PROJETO APROVADO - TB 21 QD 46 LT 18 .pdf",
    "ESTRUTURAL - TB 21 QD 46 LT 18 .pdf",
    "ARQ - TB 21 QD 46 LT 18 .pdf",
    "QUANTITATIVO GERAL .pdf",
    "MANUAL DO PROPRIETARIO CS1 - TB 21 QD 46 LT 18 .pdf",
    "HIDROSSANITARIO - TB 21 QD 46 LT 18 CS 01 .pdf",   # repetido de fato
    "HIDRO GERAL .pdf",                                  # repetido de fato
    "ELÉTRICO - TB 21 QD 46 LT 18 .pdf",                 # repetido de fato
    "PROJETO APROVADO - TB 21 QD 46 LT 18 .pdf",         # repetido de fato
    "MANUAL DO PROPRIETARIO CS2 - TB 21 QD 46 LT 18 .pdf",
    "HIDROSSANITARIO - TB 21 QD 46 LT 18 CS 02 .pdf",    # repetido de fato
]

ANEXOS = [{"id": f"a{i}", "filename": n, "extension": ".pdf",
           "downloadUrl": f"https://exemplo.invalid/{i}"}
          for i, n in enumerate(NOMES)]


def test_a_obra_real_resolve_as_duas_casas():
    a1, motivo1 = contrato_de(ANEXOS, 1)
    a2, motivo2 = contrato_de(ANEXOS, 2)
    assert a1 is not None, motivo1
    assert a2 is not None, motivo2
    assert a1["filename"].startswith("CONTRATO TB 21 QD 46 LT 18 CS 01")
    assert a2["filename"].startswith("CONTRATO TB 21 QD 46 LT 18 CS 02")


def test_os_quatro_parecidos_ficam_de_fora():
    escolhidos = {contrato_de(ANEXOS, u)[0]["filename"] for u in (1, 2)}
    for fora in ("CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 .pdf",
                 "CONTRATO DE COMPRA E VENDA TB 21 QD46 LT18 CS 01 .pdf",
                 "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 02 .pdf",
                 "CONTRATO EMPREITA - NOME DO EMPREITEIRO - TB 21 QD 46 LT 18 .pdf"):
        assert fora not in escolhidos


def test_os_quase_parecidos_nao_comecam_com_contrato():
    """DISTRATO, TERMO DE ENTREGA, RCPM, CERTIDÃO, MEMORIAL, MANUAL."""
    for nome in ("DISTRATO TB 21 QD 46 LT 18 C1 .pdf",
                 "TERMO DE ENTREGA TB 21 QD 46 LT 18 CS 02 .pdf",
                 "RCPM CS2 - TB 21 QD 46 LT 18 .pdf",
                 "CERTIDÃO CS 01 - TB 21 QD 46 LT 18 .pdf",
                 "MEMORIAL CS1 - TB 21 QD 46 LT 18 .pdf",
                 "MANUAL DO PROPRIETARIO CS2 - TB 21 QD 46 LT 18 .pdf"):
        assert not comeca_com_contrato(nome), nome


def test_qualificador_e_reconhecido():
    assert tem_qualificador("CONTRATO DE COMPRA E VENDA X CS 01")
    assert tem_qualificador("CONTRATO EMPREITA - Y - X")
    assert not tem_qualificador("CONTRATO TB 21 QD 46 LT 18 CS 01")


def test_obra_sem_contrato_nenhum_vai_para_revisao():
    anexos = [{"filename": "ART - X .pdf", "extension": ".pdf"}]
    achado, motivo = contrato_de(anexos, 1)
    assert achado is None
    assert "nenhum anexo" in motivo


def test_copias_de_nome_identico_contam_como_uma():
    anexos = [{"filename": "CONTRATO X CS 01 .pdf", "extension": ".pdf", "id": "a"},
              {"filename": "CONTRATO X CS 01 .pdf", "extension": ".pdf", "id": "b"}]
    achado, motivo = contrato_de(anexos, 1)
    assert achado is not None and achado["id"] == "a"


def test_dois_nomes_diferentes_viram_revisao_com_os_candidatos():
    """Um qualificador novo que ninguém previu sobrevive ao filtro, mas aí
    concorre com o verdadeiro — e o desfecho certo é revisão, não chute."""
    anexos = [{"filename": "CONTRATO X CS 01 .pdf", "extension": ".pdf"},
              {"filename": "CONTRATO DE GAVETA X CS 01 .pdf", "extension": ".pdf"}]
    achado, motivo = contrato_de(anexos, 1)
    # "DE GAVETA" está na lista de qualificadores, então este caso resolve:
    assert achado is not None and achado["filename"].startswith("CONTRATO X")

    anexos2 = [{"filename": "CONTRATO X CS 01 .pdf", "extension": ".pdf"},
               {"filename": "CONTRATO NOVO TIPO X CS 01 .pdf", "extension": ".pdf"}]
    achado2, motivo2 = contrato_de(anexos2, 1)
    assert achado2 is None
    assert "disputam" in motivo2


def test_casa_sem_contrato_na_obra_que_tem_outras():
    achado, motivo = contrato_de(ANEXOS, 7)
    assert achado is None
    assert "CS 07" in motivo
