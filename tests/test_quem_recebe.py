"""Quem emitiu o papel x favorecido do lançamento (decisão do dono, 25/11/2026).
Dados FICTÍCIOS; sem rede."""
import pytest

from pagamentos_dia import quem_recebe as q

CNPJ_OK = "11.222.333/0001-81"        # DV fecha (fictício)
CNPJ_OUTRO = "11.444.777/0001-61"     # DV fecha (fictício)
CNPJ_FILIAL = "11.222.333/0002-62"    # mesma raiz de CNPJ_OK
CNPJ_RUIM = "11.222.333/0001-82"      # DV não fecha


@pytest.mark.parametrize("a,b", [
    ("V.M PRE-FABRICADOS", "VM PREFABRICADOS"),
    ("V M PRE FABRICADOS LTDA", "VM PREFABRICADOS"),
    ("CASA DAS TINTAS", "casa das tintas ltda"),     # igual fora a forma jurídica
    ("Fornecedor Modelo Ltda", "FORNECEDOR MODELO"),
    ("FORNECEDOR MODELO COMERCIO DE TINTAS ME", "Fornecedor Modelo"),
    ("Açaí Modelo S.A.", "ACAI MODELO"),
    ("Casa Zeta EIRELI", "CASA ZETA EPP"),
])
def test_nomes_que_batem(a, b):
    assert q.nomes_batem(a, b)


@pytest.mark.parametrize("a,b", [
    ("FORNECEDOR MODELO", "FORNECEDOR OUTRO"),
    ("Casa Zeta", "Casa Beta"),
    ("AR", "AR CONDICIONADO MODELO"),         # sigla curta não vale por inclusão
    ("JOAO", "JOAO PEDRO SILVA"),             # uma palavra só
    ("FULANO SOUZA", "FULANO SOUZA LIMA"),    # nome de pessoa: igual, não "contido"
    ("CASA DAS TINTAS", "NOVA CASA DAS TINTAS"),  # só palavras comuns
    ("FORNECEDOR", "FORNECEDOR MODELO"),
    ("", "FORNECEDOR MODELO"),
    ("LTDA", "ME"),
])
def test_nomes_que_nao_batem(a, b):
    assert not q.nomes_batem(a, b)


def test_documento_igual_e_valido_bate_forte_mesmo_com_nome_diferente():
    r = q.conferir({"emitente_nome": "Outro Nome", "emitente_cnpj_cpf": CNPJ_OK},
                   "Fornecedor Modelo", "11222333000181")
    assert (r.estado, r.por) == (q.BATE, "cnpj/cpf")


def test_documento_lido_com_dv_ruim_e_ignorado_e_vale_o_nome():
    r = q.conferir({"emitente_nome": "Fornecedor Modelo", "emitente_cnpj_cpf": CNPJ_RUIM},
                   "Fornecedor Modelo Ltda", "11222333000181")
    assert (r.estado, r.por) == (q.BATE, "nome")


def test_documento_diferente_diverge():
    r = q.conferir({"emitente_nome": "Fornecedor Modelo", "emitente_cnpj_cpf": CNPJ_OUTRO},
                   "Fornecedor Modelo", CNPJ_OK)
    assert r.estado == q.DIVERGE


def test_filial_mesma_raiz_cai_no_nome():
    r = q.conferir({"emitente_nome": "Fornecedor Modelo", "emitente_cnpj_cpf": CNPJ_FILIAL},
                   "Fornecedor Modelo", CNPJ_OK)
    assert r.estado == q.BATE and r.por == "nome"


def test_nome_diferente_diverge_com_motivo():
    r = q.conferir({"emitente_nome": "Loja Beta", "emitente_cnpj_cpf": ""}, "Fornecedor Modelo", "")
    assert r.estado == q.DIVERGE
    assert r.motivo == "papel emitido por Loja Beta, lançamento para Fornecedor Modelo"


def test_nao_lido_continua_nao_conferido():
    for leitura in ({}, {"emitente_nome": "", "emitente_cnpj_cpf": ""},
                    {"emitente_nome": "  "}):
        assert q.conferir(leitura, "Fornecedor Modelo", "").estado == q.NAO


def test_sem_favorecido_nao_confere():
    assert q.conferir({"emitente_nome": "Loja Beta"}, "", "").estado == q.NAO
