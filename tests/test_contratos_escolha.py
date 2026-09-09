# -*- coding: utf-8 -*-
"""Qual anexo é o contrato de compra e venda.

Os 52 nomes abaixo são os de uma obra REAL, com o nome de pessoa trocado — é o
formato que importa, e o repositório é público. Eles trazem de graça três
armadilhas que ninguém inventaria: a obra escrita errada dentro do arquivo
(QD 26 numa obra QD 46), a versão sem espaço (QD46 LT18) e anexos repetidos.
"""
from contratos.escolha import (candidatos, contrato_de, eh_compra_e_venda,
                               excluido_por, ordenar_para_escolha)

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

CCV_CS01_A = "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 .pdf"
CCV_CS01_B = "CONTRATO DE COMPRA E VENDA TB 21 QD46 LT18 CS 01 .pdf"
CCV_CS02 = "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 02 .pdf"


def _a(nome, ident="x"):
    return {"filename": nome, "extension": ".pdf", "id": ident}


# ------------------------------------------------------------- a obra real
def test_a_casa_02_da_obra_real_resolve_sozinha():
    anexo, motivo = contrato_de(ANEXOS, 2)
    assert anexo is not None, motivo
    assert anexo["filename"] == CCV_CS02


def test_a_casa_01_tem_duas_grafias_e_vira_revisao():
    """`QD 46 LT 18` e `QD46 LT18` podem ser o mesmo arquivo subido duas
    vezes ou uma minuta e a assinada. Só quem abre sabe."""
    anexo, motivo = contrato_de(ANEXOS, 1)
    assert anexo is None
    assert "2 anexos disputam" in motivo
    assert CCV_CS01_A in motivo and CCV_CS01_B in motivo


def test_o_contrato_da_caixa_fica_de_fora():
    """`CONTRATO TB 21 … CS 02` (sem "compra e venda") é o da Caixa."""
    nomes = {a["filename"] for a in candidatos(ANEXOS, 2)}
    assert nomes == {CCV_CS02}
    assert not eh_compra_e_venda("CONTRATO TB 21 QD 46 LT 18 CS 02 .pdf")


def test_os_quase_parecidos_ficam_de_fora():
    for nome in ("DISTRATO TB 21 QD 46 LT 18 C1 .pdf",
                 "TERMO DE ENTREGA TB 21 QD 46 LT 18 CS 02 .pdf",
                 "CONTRATO EMPREITA - NOME DO EMPREITEIRO - TB 21 QD 46 LT 18 .pdf",
                 "CERTIDÃO CS 01 - TB 21 QD 46 LT 18 .pdf"):
        assert not candidatos([_a(nome)], 1) and not candidatos([_a(nome)], 2)


# ---------------------------------------------------------------- grafias
def test_grafias_de_compra_e_venda():
    for nome in ("CONTRATO DE COMPRA E VENDA X CS 01", "Contrato de compra e venda x cs 1",
                 "CONTRATO COMPRA & VENDA X CS 01", "CONTRATO COMPRA-E-VENDA X CS 01",
                 "CCV X CS 01", "PROMESSA DE COMPRA E VENDA X CS 01"):
        assert eh_compra_e_venda(nome), nome
    for nome in ("CONTRATO X CS 01", "CONTRATO EMPREITA - Y", "VENDA X CS 01"):
        assert not eh_compra_e_venda(nome), nome


def test_exclusoes_dizem_a_palavra():
    assert excluido_por("DISTRATO DE COMPRA E VENDA X CS 01") == "DISTRATO"
    assert excluido_por("ADITIVO AO CONTRATO DE COMPRA E VENDA X CS 01") == "ADITIVO"
    assert excluido_por("MINUTA CONTRATO DE COMPRA E VENDA X CS 01") == "MINUTA"
    assert excluido_por("CONTRATO DE COMPRA E VENDA CAIXA X CS 01") == "CAIXA"
    assert excluido_por("CONTRATO DE COMPRA E VENDA E FINANCIAMENTO X CS 01") == "FINANCIAMENTO"
    assert excluido_por("TERMO DE RESCISÃO DO CONTRATO DE COMPRA E VENDA X CS 01") == "RESCIS"
    assert excluido_por("CONTRATO DE COMPRA E VENDA X CS 01") == ""


def test_excluido_nao_e_candidato_mesmo_dizendo_compra_e_venda():
    anexos = [_a("ADITIVO AO CONTRATO DE COMPRA E VENDA X CS 01 .pdf")]
    achado, motivo = contrato_de(anexos, 1)
    assert achado is None and "nenhum anexo" in motivo


def test_c_solto_do_centro_de_custo_nao_engana_a_casa():
    nome = "CONTRATO DE COMPRA E VENDA DONA MORENA QD 18 LT 8 C 259 M 5 CS 01 .pdf"
    assert candidatos([_a(nome)], 1)
    assert not candidatos([_a(nome)], 259)


# ---------------------------------------------------------------- desempate
def test_assinado_desempata_duas_grafias():
    anexos = [_a("CONTRATO DE COMPRA E VENDA X CS 01 .pdf", "a"),
              _a("CONTRATO DE COMPRA E VENDA X CS 01 ASSINADO .pdf", "b")]
    achado, motivo = contrato_de(anexos, 1)
    assert achado is not None and achado["id"] == "b"
    assert "ASSINADO" in motivo


def test_dois_assinados_continuam_em_revisao():
    anexos = [_a("CONTRATO DE COMPRA E VENDA X CS 01 ASSINADO .pdf", "a"),
              _a("CONTRATO DE COMPRA E VENDA X CS 01 ASSINADO v2 .pdf", "b")]
    achado, motivo = contrato_de(anexos, 1)
    assert achado is None and "disputam" in motivo


def test_copias_de_nome_identico_contam_como_uma():
    anexos = [_a("CONTRATO DE COMPRA E VENDA X CS 01 .pdf", "a"),
              _a("CONTRATO DE COMPRA E VENDA X CS 01 .pdf", "b")]
    achado, motivo = contrato_de(anexos, 1)
    assert achado is not None and achado["id"] == "a"


def test_tipo_novo_concorre_e_vira_revisao():
    """Um qualificador que ninguém previu sobrevive ao filtro, mas aí
    concorre com o verdadeiro — e o desfecho certo é revisão, não chute."""
    anexos = [_a("CONTRATO DE COMPRA E VENDA X CS 01 .pdf"),
              _a("CONTRATO DE COMPRA E VENDA DE GAVETA X CS 01 .pdf")]
    achado, motivo = contrato_de(anexos, 1)
    assert achado is None and "disputam" in motivo


# ------------------------------------------------------------------ faltas
def test_sem_casa_nao_ha_candidato():
    assert candidatos(ANEXOS, None) == []
    achado, motivo = contrato_de(ANEXOS, None)
    assert achado is None and "número da casa" in motivo


def test_casa_sem_contrato_na_obra_que_tem_outras():
    achado, motivo = contrato_de(ANEXOS, 7)
    assert achado is None
    assert "CS 07" in motivo and "COMPRA E VENDA" in motivo


def test_obra_sem_contrato_nenhum_vai_para_revisao():
    achado, motivo = contrato_de([_a("ART - X .pdf")], 1)
    assert achado is None
    assert "nenhum anexo" in motivo


# ------------------------------------------------- lista da escolha à mão
def test_a_lista_da_janela_poe_os_candidatos_no_topo():
    """Com 52 anexos, mostrar a ordem do ERP obrigaria a procurar o contrato
    no meio de memorial, RCPM e manual do proprietário — justamente quando o
    app já admitiu não saber decidir."""
    lista = ordenar_para_escolha(ANEXOS, 1)
    assert len(lista) == len(ANEXOS)              # a lista INTEIRA aparece

    candidatos_ = [a["filename"] for a, sim in lista if sim]
    assert sorted(candidatos_) == sorted([CCV_CS01_A, CCV_CS01_B])
    assert lista[0][1] and lista[1][1]
    assert not lista[2][1]                        # daí em diante, o resto


def test_sem_candidato_a_lista_continua_inteira():
    """É o caso em que a janela mais importa: nenhum anexo diz COMPRA E
    VENDA daquela casa, e a pessoa precisa ver o resto para achar o que foi
    salvo com outro nome."""
    lista = ordenar_para_escolha(ANEXOS, 9)
    assert len(lista) == len(ANEXOS)
    assert not any(sim for _, sim in lista)


def test_a_lista_de_obra_vazia_nao_quebra():
    assert ordenar_para_escolha([], 1) == []
    assert ordenar_para_escolha(None, 1) == []
    assert ordenar_para_escolha(ANEXOS, None)[0][1] is False
