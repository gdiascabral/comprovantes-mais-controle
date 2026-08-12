# -*- coding: utf-8 -*-
"""A conferência do conteúdo do contrato, e o destino do arquivo.

Nomes, endereços e valores são inventados: o repositório é público e contrato
real tem nome, CPF e endereço de gente.
"""
from decimal import Decimal
from pathlib import Path

from contratos.conferencia import (CONFERE, DIVERGE, ILEGIVEL, conferir,
                                   divergencias, pode_gravar, ressalvas)
from contratos.destino import (caminho_longo, empresa_de, limpar,
                               nome_arquivo, pasta_do_contrato)

ESPERADO = {
    "rua": "Rua TB 21",
    "complemento": "QD 46 LT 18",
    "unidade": 2,
    "comprador": "FULANO DE TAL SOBRENOME",
    "valor_financiamento": Decimal("248000.00"),
}

TEXTO_BOM = """
INSTRUMENTO PARTICULAR DE CONTRATO
Imovel situado na Rua TB 21, QD 46 LT 18, CASA 02, no bairro Terrabela.
Comprador: FULANO DE TAL SOBRENOME, brasileiro, portador do documento.
Valor do financiamento: R$ 248.000,00 (duzentos e quarenta e oito mil reais).
As partes assinam o presente instrumento em duas vias de igual teor.
"""


# ------------------------------------------------------------- conferência
def test_os_cinco_pontos_conferem():
    r = conferir(TEXTO_BOM, ESPERADO)
    assert r["rua"] == CONFERE
    assert r["quadra_lote"] == CONFERE
    assert r["casa"] == CONFERE
    assert r["comprador"] == CONFERE
    assert r["valor"] == CONFERE
    assert pode_gravar(r)


def test_casa_errada_diverge_e_retem():
    r = conferir(TEXTO_BOM.replace("CASA 02", "CASA 03"), ESPERADO)
    assert r["casa"] == DIVERGE
    assert not pode_gravar(r)
    assert "casa" in divergencias(r)


def test_valor_errado_diverge():
    r = conferir(TEXTO_BOM.replace("248.000,00", "199.000,00"), ESPERADO)
    assert r["valor"] == DIVERGE
    assert not pode_gravar(r)


def test_texto_vazio_vira_ilegivel_e_nao_retem():
    """Contrato ilegível não é contrato errado. `?` nunca segura o arquivo."""
    r = conferir("", ESPERADO)
    assert all(r[p] == ILEGIVEL for p in
               ("rua", "quadra_lote", "casa", "comprador", "valor"))
    assert pode_gravar(r)
    assert len(ressalvas(r)) == 5


def test_valor_por_extenso_e_ilegivel_e_nao_divergencia():
    """Escrever um leitor de numeral por extenso para depois errar nele só
    fabricaria alarme falso — e alarme falso aqui retém contrato bom."""
    texto = TEXTO_BOM.replace("R$ 248.000,00 (duzentos e quarenta e oito mil reais)",
                              "duzentos e quarenta e oito mil reais")
    r = conferir(texto, ESPERADO)
    assert r["valor"] == ILEGIVEL
    assert pode_gravar(r)


def test_texto_de_ocr_com_codigo_colado_ainda_confere():
    """O OCR come os espaços do centro de custo: TB 21 QD 46 sai TB21QD46."""
    texto = TEXTO_BOM.replace("Rua TB 21, QD 46 LT 18", "Rua TB21 QD46LT18")
    r = conferir(texto, ESPERADO)
    assert r["quadra_lote"] in (CONFERE, ILEGIVEL)
    assert r["quadra_lote"] != DIVERGE


def test_quadra_e_lote_por_extenso_conferem():
    texto = TEXTO_BOM.replace("QD 46 LT 18", "QUADRA 46 LOTE 18")
    assert conferir(texto, ESPERADO)["quadra_lote"] == CONFERE


def test_nome_abreviado_no_erp_contra_nome_completo_no_contrato():
    """O contrato traz o nome completo; a descrição do ERP às vezes abrevia.
    Conferir por sobrenomes acha o mesmo comprador sem exigir a mesma grafia."""
    esperado = dict(ESPERADO, comprador="FULANO SOBRENOME")
    assert conferir(TEXTO_BOM, esperado)["comprador"] == CONFERE


def test_comprador_diferente_diverge():
    esperado = dict(ESPERADO, comprador="OUTRA PESSOA COMPLETAMENTE")
    r = conferir(TEXTO_BOM, esperado)
    assert r["comprador"] == DIVERGE
    assert not pode_gravar(r)


def test_acento_e_caixa_nao_atrapalham():
    esperado = dict(ESPERADO, rua="rua tb 21")
    assert conferir(TEXTO_BOM, esperado)["rua"] == CONFERE


# ------------------------------------------------------------------ destino
class _Empresa:
    def __init__(self, nome, clientes):
        self.nome = nome
        self.clientes_erp = clientes


EMPRESAS = [_Empresa("BURITIS", ["MORAIS EMPREENDIMENTOS BURITIS"]),
            _Empresa("TERRA BELA", ["TERRA BELA MORAIS ENGENHARIA SPE"]),
            _Empresa("JOAO V PARTICIPACOES", [])]


def test_cliente_mapeado_acha_a_empresa():
    e = empresa_de("MORAIS EMPREENDIMENTOS BURITIS", EMPRESAS)
    assert e is not None and e.nome == "BURITIS"


def test_cliente_com_acento_e_espaco_duplo_ainda_acha():
    assert empresa_de("terra  bela morais engenharia spe", EMPRESAS).nome == "TERRA BELA"


def test_pessoa_fisica_nao_tem_empresa():
    """Não é lacuna de cadastro: obra de pessoa física não tem pasta de
    fechamento, e o contrato dela fica em revisão por definição."""
    assert empresa_de("FULANO DE TAL DA SILVA", EMPRESAS) is None
    assert empresa_de("", EMPRESAS) is None


def test_nome_do_arquivo():
    n = nome_arquivo("TB 21 QD 46 LT 18", 2, "FULANO DE TAL", ".pdf")
    assert n == "CONTRATO TB 21 QD 46 LT 18 CS 02 - FULANO DE TAL.pdf"


def test_caractere_proibido_sai_do_nome():
    n = nome_arquivo("TB 21", 1, 'MARIA / JOSE: "X"', ".pdf")
    assert not any(c in n for c in '\\/:*?"<>|')
    assert n.startswith("CONTRATO TB 21 CS 01 - MARIA JOSE")


def test_extensao_chega_com_ponto_e_nao_duplica():
    assert nome_arquivo("X", 1, "Y", ".pdf").endswith(".pdf")
    assert nome_arquivo("X", 1, "Y", "pdf").endswith(".pdf")
    assert not nome_arquivo("X", 1, "Y", ".pdf").endswith("..pdf")


def test_limpar_colapsa_espaco():
    assert limpar("A   B") == "A B"


def test_caminho_perto_do_limite_e_denunciado():
    curto = Path("C:/Arquivos/2026/JULHO/X/CONTRATOS/a.pdf")
    assert caminho_longo(curto) is None
    longo = Path("C:/" + "x" * 300 + ".pdf")
    assert caminho_longo(longo) is not None


def test_pasta_do_contrato_monta_a_arvore_do_fechamento():
    p = pasta_do_contrato(Path("C:/Arquivos Morais/EXTRATOS"), 2026, 7,
                          "BURITIS",
                          nome_do_mes=lambda m: "JULHO",
                          nome_pasta_empresa=lambda a, m, e: f"JULHO {a} - {e}")
    assert p == Path("C:/Arquivos Morais/EXTRATOS/2026/JULHO/"
                     "JULHO 2026 - BURITIS/CONTRATOS")
