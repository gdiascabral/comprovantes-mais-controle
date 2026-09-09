# -*- coding: utf-8 -*-
"""A conferência do conteúdo do contrato, e o destino do arquivo.

Nomes, endereços, CNPJ e valores são inventados: o repositório é público e
contrato real tem nome, CPF e endereço de gente.
"""
from decimal import Decimal
from pathlib import Path

from contratos.conferencia import (CONFERE, DIVERGE, ILEGIVEL, PONTOS,
                                   conferir, divergencias, pode_gravar,
                                   ressalvas)
from contratos.destino import (caminho_longo, empresa_de, limpar,
                               mesmo_contrato_na_pasta, nome_arquivo,
                               pasta_do_contrato)

ESPERADO = {
    "rua": "Rua RPB 24",
    "complemento": "QD 26A LT 14",
    "unidade": 1,
    "comprador": "FULANO DE TAL SOBRENOME",
    "cnpj": "12.345.678/0001-90",
    "vendedora": ["EMPRESA EXEMPLO SPE LTDA", "EMPRESA EXEMPLO SPE"],
    "valor_venda": Decimal("260000.00"),
}

TEXTO_BOM = """
INSTRUMENTO PARTICULAR DE CONTRATO DE COMPRA E VENDA DE IMOVEL
VENDEDOR: EMPRESA EXEMPLO SPE LTDA, pessoa juridica de direito privado,
inscrita no CNPJ sob o numero 12.345.678/0001-90, neste ato representada.
COMPRADOR: FULANO DE TAL SOBRENOME, brasileiro, solteiro, portador do
CPF 000.000.000-00, residente na Rua Qualquer, Casa 22, Bairro Exemplo.
IMOVEL OBJETO: RUA RPB 24 QD 26 - A LT 14 CASA 01 PARQUE EXEMPLO,
confrontando pelo lado direito com a casa 02 e pelo esquerdo com o lote 15.
Valor de Aquisicao do Imovel: R$ 260.000,00 (duzentos e sessenta mil reais).
As partes assinam o presente instrumento em duas vias de igual teor.
"""

TEXTO_CAIXA = """
CONTRATO POR INSTRUMENTO PARTICULAR DE COMPRA E VENDA DE IMOVEL E MUTUO
A1 - VENDEDOR(ES): EMPRESA EXEMPLO SPE LTDA, inscrita no CNPJ 12.345.678/0001-90
A2 - COMPRADOR(ES) E DEVEDOR(ES) FIDUCIANTE(S): FULANO DE TAL SOBRENOME
A3 - CAIXA ECONOMICA FEDERAL, instituicao financeira sob a forma de empresa publica
B1 - Imovel: Rua RPB 24, QD 26A LT 14, CASA 01, Parque Exemplo.
B6 - Valor da Divida - Financiamento: R$ 200.000,00
"""


# ------------------------------------------------------------- conferência
def test_os_sete_pontos_conferem():
    r = conferir(TEXTO_BOM, ESPERADO)
    assert {p: r[p] for p in PONTOS} == {p: CONFERE for p in PONTOS}
    assert pode_gravar(r) and ressalvas(r) == []


def test_casa_errada_diverge_e_retem():
    """O contrato cita a casa 02 nas confrontações e o vendedor mora numa
    "Casa 22": só o par lote+casa diz de qual casa o contrato é."""
    r = conferir(TEXTO_BOM, dict(ESPERADO, unidade=2))
    assert r["casa"] == DIVERGE
    assert not pode_gravar(r)
    assert divergencias(r) == ["casa"]


def test_casa_com_numero_por_extenso_confere():
    texto = TEXTO_BOM.replace("LT 14 CASA 01", "LT 14 CASA Nº 01")
    assert conferir(texto, ESPERADO)["casa"] == CONFERE


def test_sem_o_par_lote_casa_vale_a_presenca_da_casa():
    texto = "Imovel: CASA 02 no bairro exemplo, comprador e vendedor assinam."
    texto = texto + " " * 40
    assert conferir(texto, dict(ESPERADO, unidade=2))["casa"] == CONFERE
    assert conferir(texto, dict(ESPERADO, unidade=3))["casa"] == DIVERGE


def test_comprador_diferente_diverge():
    r = conferir(TEXTO_BOM, dict(ESPERADO, comprador="OUTRA PESSOA COMPLETAMENTE"))
    assert r["comprador"] == DIVERGE
    assert not pode_gravar(r)


def test_nome_abreviado_no_erp_contra_nome_completo_no_contrato():
    """O contrato traz o nome completo; a descrição do ERP às vezes abrevia.
    Conferir por sobrenomes acha o mesmo comprador sem exigir a mesma grafia."""
    assert conferir(TEXTO_BOM, dict(ESPERADO, comprador="FULANO SOBRENOME"))["comprador"] == CONFERE


def test_casal_exige_os_dois():
    texto = TEXTO_BOM.replace("COMPRADOR: FULANO DE TAL SOBRENOME",
                              "COMPRADORES: FULANO DE TAL SOBRENOME e BELTRANA SILVA")
    ok = dict(ESPERADO, comprador="FULANO SOBRENOME E BELTRANA SILVA")
    assert conferir(texto, ok)["comprador"] == CONFERE
    assert conferir(TEXTO_BOM, ok)["comprador"] == DIVERGE


# ---------------------------------------------------------------- vendedora
def test_vendedora_pelo_cnpj_mesmo_sem_pontuacao():
    texto = TEXTO_BOM.replace("12.345.678/0001-90", "CNPJ 12345678000190")
    assert conferir(texto, ESPERADO)["vendedora"] == CONFERE


def test_vendedora_pela_razao_social_quando_o_cnpj_nao_aparece():
    texto = TEXTO_BOM.replace("12.345.678/0001-90", "00.000.000/0000-00")
    assert conferir(texto, ESPERADO)["vendedora"] == CONFERE


def test_vendedora_errada_diverge_e_retem():
    """É o ponto que pega o contrato anexado na obra errada ou a obra mapeada
    na empresa errada — a pasta de outra empresa."""
    outra = dict(ESPERADO, cnpj="99.999.999/0001-99",
                 vendedora=["OUTRA CONSTRUTORA LTDA"])
    r = conferir(TEXTO_BOM, outra)
    assert r["vendedora"] == DIVERGE
    assert not pode_gravar(r)


def test_sem_cnpj_nem_nome_no_cadastro_a_vendedora_fica_em_interrogacao():
    r = conferir(TEXTO_BOM, dict(ESPERADO, cnpj="", vendedora=[]))
    assert r["vendedora"] == ILEGIVEL and pode_gravar(r)


# --------------------------------------------------------------------- tipo
def test_o_contrato_da_caixa_diverge_no_tipo():
    """Ele também chama a SPE de vendedor e traz casa, comprador e valor:
    passaria em tudo. O que só ele tem é Caixa + devedor fiduciante."""
    r = conferir(TEXTO_CAIXA, ESPERADO)
    assert r["tipo"] == DIVERGE
    assert not pode_gravar(r)


def test_citar_a_caixa_numa_clausula_nao_e_o_contrato_da_caixa():
    texto = TEXTO_BOM + "\nO saldo sera pago com financiamento junto a CAIXA ECONOMICA FEDERAL."
    assert conferir(texto, ESPERADO)["tipo"] == CONFERE


def test_documento_sem_comprador_e_vendedor_fica_em_interrogacao_no_tipo():
    texto = "MEMORIAL DESCRITIVO do imovel na RUA RPB 24 QD 26A LT 14 CASA 01, valor R$ 1,00."
    assert conferir(texto, ESPERADO)["tipo"] == ILEGIVEL


# -------------------------------------------------------------------- valor
def test_valor_diferente_nao_retem():
    """O contábil apura pelo banco, e o preço pode ter sido renegociado."""
    r = conferir(TEXTO_BOM.replace("260.000,00", "199.000,00"), ESPERADO)
    assert r["valor"] == ILEGIVEL
    assert pode_gravar(r) and "valor" in ressalvas(r)


def test_valor_por_extenso_e_ilegivel():
    texto = TEXTO_BOM.replace("R$ 260.000,00 (duzentos e sessenta mil reais)",
                              "duzentos e sessenta mil reais")
    assert conferir(texto, ESPERADO)["valor"] == ILEGIVEL


def test_sem_valor_da_venda_no_erp_o_ponto_fica_em_interrogacao():
    assert conferir(TEXTO_BOM, dict(ESPERADO, valor_venda=None))["valor"] == ILEGIVEL


# ----------------------------------------------------------------- endereço
def test_texto_de_ocr_com_codigo_colado_ainda_confere():
    """O OCR come os espaços: `RPB24 QD26A LT14 CS01`."""
    texto = TEXTO_BOM.replace("RUA RPB 24 QD 26 - A LT 14 CASA 01",
                              "RUA RPB24 QD26A LT14 CS01")
    r = conferir(texto, ESPERADO)
    assert r["quadra_lote"] == CONFERE and r["casa"] == CONFERE


def test_quadra_e_lote_por_extenso_conferem():
    texto = TEXTO_BOM.replace("QD 26 - A LT 14", "QUADRA 26 - A LOTE 14")
    assert conferir(texto, ESPERADO)["quadra_lote"] == CONFERE


def test_letra_do_lote_com_e_sem_hifen():
    for grafia in ("QD 26-A LT 14", "QD 26 A LT 14", "QD 26A LT 14"):
        texto = TEXTO_BOM.replace("QD 26 - A LT 14", grafia)
        assert conferir(texto, ESPERADO)["quadra_lote"] == CONFERE, grafia


def test_quadra_errada_diverge():
    r = conferir(TEXTO_BOM, dict(ESPERADO, complemento="QD 27 LT 14"))
    assert r["quadra_lote"] == DIVERGE


def test_acento_e_caixa_nao_atrapalham():
    assert conferir(TEXTO_BOM, dict(ESPERADO, rua="rua rpb 24"))["rua"] == CONFERE


# ---------------------------------------------------------------- ilegível
def test_texto_vazio_vira_ilegivel_e_nao_retem():
    """Contrato ilegível não é contrato errado. `?` nunca segura o arquivo."""
    r = conferir("", ESPERADO)
    assert all(r[p] == ILEGIVEL for p in PONTOS)
    assert pode_gravar(r)
    assert len(ressalvas(r)) == len(PONTOS)
    assert "sem texto" in r["motivo"]


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


def test_nome_do_arquivo_diz_que_e_compra_e_venda():
    """O nome antigo (`CONTRATO <obra> CS 02 - …`) é o do contrato da Caixa
    posto à mão na mesma pasta: gravar com ele apagaria o da Caixa."""
    n = nome_arquivo("TB 21 QD 46 LT 18", 2, "FULANO DE TAL", ".pdf")
    assert n == "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 02 - FULANO DE TAL.pdf"


def test_caractere_proibido_sai_do_nome():
    n = nome_arquivo("TB 21", 1, 'MARIA / JOSE: "X"', ".pdf")
    assert not any(c in n for c in '\\/:*?"<>|')
    assert n.startswith("CONTRATO DE COMPRA E VENDA TB 21 CS 01 - MARIA JOSE")


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


# ------------------------------------------------- o que já está na pasta
def test_acha_a_mesma_casa_com_outro_nome(tmp_path):
    (tmp_path / "CONTRATO DE COMPRA E VENDA TB 21 QD46 LT18 CASA 1 - OUTRO.pdf").write_bytes(b"x")
    achado = mesmo_contrato_na_pasta(tmp_path, "TB 21 QD 46 LT 18", 1)
    assert achado is not None and achado.name.startswith("CONTRATO DE COMPRA")


def test_o_contrato_da_caixa_na_pasta_nao_conta():
    pass


def test_contrato_da_caixa_e_outra_casa_nao_contam(tmp_path):
    (tmp_path / "CONTRATO TB 21 QD 46 LT 18 CS 01 - FULANO.pdf").write_bytes(b"x")
    (tmp_path / "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 02 - B.pdf").write_bytes(b"x")
    (tmp_path / "CONTRATO DE COMPRA E VENDA TB 14 QD 43 LT 27 CS 01 - C.pdf").write_bytes(b"x")
    assert mesmo_contrato_na_pasta(tmp_path, "TB 21 QD 46 LT 18", 1) is None


def test_o_proprio_destino_nao_conta_como_outro(tmp_path):
    alvo = tmp_path / "CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01 - A.pdf"
    alvo.write_bytes(b"x")
    assert mesmo_contrato_na_pasta(tmp_path, "TB 21 QD 46 LT 18", 1, exceto=alvo) is None
    assert mesmo_contrato_na_pasta(tmp_path, "TB 21 QD 46 LT 18", 1) == alvo


def test_pasta_inexistente_nao_quebra(tmp_path):
    assert mesmo_contrato_na_pasta(tmp_path / "nao existe", "X", 1) is None
