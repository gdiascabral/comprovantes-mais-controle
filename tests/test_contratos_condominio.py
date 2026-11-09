# -*- coding: utf-8 -*-
"""Condomínio: a venda é de UNIDADE, não de casa.

O robô de venda descreve o recebimento do condomínio como
"VENDA UNIDADE 15 - NOME" (regra do dono, 07/10/2026). Até 05/11/2026 a aba
Contratos só entendia CASA/CS e mostrava essas linhas como "CS ??".

Nenhum dado real: nomes e valores inventados (o repositório é público).
"""
from contratos.conferencia import (CONFERE, DIVERGE, _preparar, conferir_casa,
                                   conferir_rua)
from contratos.destino import nome_arquivo
from contratos.escolha import contrato_de, contrato_do_lancamento
from contratos.regras import (imoveis_do_mes, numero_da_unidade,
                              partes_da_descricao, rotulo_da_unidade,
                              tipo_da_descricao, tipo_da_unidade)

OBRA = "CONDOMINIO EXEMPLO"


def receb(descricao, ident="r1"):
    return {"workName": OBRA, "description": descricao,
            "readjustmentType": "0ª Sinal", "nature": "Venda",
            "dateOfReceipt": "2026-10-05", "sumOfReceivedValues": 3000.0,
            "customerName": "FULANO EXEMPLO", "id": ident,
            "saleValue": 300000.0}


def test_unidade_vira_numero():
    assert numero_da_unidade("VENDA UNIDADE 15") == 15
    assert numero_da_unidade("VENDA UNIDADE 07") == 7
    assert numero_da_unidade("UNID. 3") == 3
    assert numero_da_unidade("UN 31") == 31


def test_tipo_da_unidade():
    assert tipo_da_unidade("VENDA UNIDADE 15") == "UN"
    assert tipo_da_unidade("VENDA CASA 01") == "CS"
    assert tipo_da_unidade("VENDA CS 2") == "CS"
    assert tipo_da_unidade("VENDA DO IMOVEL") == "CS"


def test_tipo_so_olha_antes_do_traco():
    """O nome do comprador é texto livre: "UN 2" nele não muda o tipo."""
    assert tipo_da_descricao("VENDA CASA 01 - JOAO UN 2") == "CS"
    assert tipo_da_descricao("VENDA UNIDADE 17 - FULANO") == "UN"


def test_rotulo_do_condominio():
    assert rotulo_da_unidade(15, "UN") == "UN 15"
    assert rotulo_da_unidade(None, "UN") == "UN ??"
    assert rotulo_da_unidade(1) == "CS 01"


def test_unidade_do_condominio_nao_cai_em_revisao():
    imoveis = imoveis_do_mes(
        [receb("VENDA UNIDADE 15 - FULANO EXEMPLO", "a"),
         receb("VENDA UNIDADE 17 - CICLANA EXEMPLO", "b")], log=lambda _m: None)
    assert [(i.unidade, i.rotulo, i.revisao) for i in imoveis] == [
        (15, "UN 15", ""), (17, "UN 17", "")]
    assert imoveis[0].comprador == "FULANO EXEMPLO"


def test_unidade_00_de_teste_segue_em_revisao():
    """A venda de teste "UNIDADE 00" não é unidade nenhuma."""
    unidade, _ = partes_da_descricao("VENDA UNIDADE 00 - TESTE")
    assert not unidade
    [i] = imoveis_do_mes([receb("VENDA UNIDADE 00 - TESTE")],
                         log=lambda _m: None)
    assert i.revisao
    assert i.rotulo == "UN ??"


def test_contrato_da_unidade_e_mensagem_com_un():
    anexos = [{"filename": "CONTRATO DE COMPRA E VENDA UNIDADE 15 - FULANO"},
              {"filename": "CONTRATO DE COMPRA E VENDA UNIDADE 17 - CICLANA"}]
    anexo, _ = contrato_de(anexos, 15, "UN")
    assert anexo is anexos[0]
    anexo, motivo = contrato_de(anexos, 18, "UN")
    assert anexo is None
    assert "UN 18" in motivo


def test_nome_do_arquivo_do_condominio():
    assert nome_arquivo(OBRA, 15, "FULANO EXEMPLO", tipo="UN") == (
        f"CONTRATO DE COMPRA E VENDA {OBRA} UN 15 - FULANO EXEMPLO.pdf")
    # casa de rua continua igual
    assert " CS 02 - " in nome_arquivo("TB 21 QD 46 LT 18", 2, "FULANO")


def test_conferencia_da_unidade():
    """O texto chega preparado (UNIDADE já virou UN pelos sinônimos)."""
    assert conferir_casa("OBJETO UN 15 DO CONDOMINIO", 15, "UN") == CONFERE
    assert conferir_casa("OBJETO UN 16 DO CONDOMINIO", 15, "UN") == DIVERGE
    # casa de rua não é afetada
    assert conferir_casa("LT 18 CS 02", 2) == CONFERE


# ---------------------------------------------------------------------------
# 09/11/2026: o contrato do condomínio mora no LANÇAMENTO da venda, e o texto
# real do contrato diz "Unidade: Casa nº 15". Nada abaixo é dado real.
# ---------------------------------------------------------------------------
def test_imovel_guarda_as_vendas_do_mes():
    a = dict(receb("VENDA UNIDADE 15 - FULANO", "a"), saleId="venda-1")
    b = dict(receb("VENDA UNIDADE 15 - FULANO", "b"), saleId="venda-1")
    c = dict(receb("VENDA UNIDADE 15 - FULANO", "c"), saleId="venda-2")
    [i] = imoveis_do_mes([a, b, c], log=lambda _m: None)
    assert i.vendas == ["venda-1", "venda-2"]


def test_casa_escrita_por_extenso_na_unidade_confere():
    texto = _preparar("IMÓVEL OBJETO DO CONTRATO (UNIDADE) a) Unidade: Casa nº 15, Tipo 02")
    assert conferir_casa(texto, 15, "UN") == CONFERE
    assert conferir_casa(texto, 16, "UN") == DIVERGE


def test_casa_do_endereco_da_vendedora_nao_conta_como_a_unidade():
    """A sede de quem vende pode ter "Casa 15"; só o objeto diz a unidade."""
    texto = _preparar("Sede na Rua Exemplo, Quadra 04, Lote 08, Casa 15. "
                      "Unidade: Casa nº 22, Tipo 01")
    assert conferir_casa(texto, 15, "UN") == DIVERGE
    assert conferir_casa(texto, 22, "UN") == CONFERE


def test_rua_com_hifen_no_contrato_confere():
    assert conferir_rua(_preparar("Endereço: Rua XYZ-24, Quadra 9"), "Rua XYZ 24") == CONFERE
    assert conferir_rua(_preparar("Endereço: Rua XYZ-25, Quadra 9"), "Rua XYZ 24") == DIVERGE


def _anexo(nome, ident="a"):
    return {"id": ident, "filename": nome, "extension": ".pdf",
            "downloadUrl": f"https://exemplo.invalid/{ident}"}


def test_contrato_do_lancamento_aceita_o_nome_que_o_robo_grava():
    certo = _anexo("CONTRATO CONDOMÍNIO EXEMPLO CASA 15 - FULANO EXEMPLO")
    anexo, _ = contrato_do_lancamento([certo], 15)
    assert anexo is certo


def test_contrato_do_lancamento_aceita_mais_no_lugar_de_espaco():
    certo = _anexo("CONTRATO+DE+COMPRA+E+VENDA+CONDOMINIO+UNIDADE+15")
    anexo, _ = contrato_do_lancamento([certo], 15)
    assert anexo is certo


def test_contrato_do_lancamento_nao_pega_outra_unidade():
    anexo, motivo = contrato_do_lancamento(
        [_anexo("CONTRATO CONDOMÍNIO EXEMPLO CASA 16 - FULANO")], 15)
    assert anexo is None
    assert "UN 15" in motivo


def test_numero_no_nome_do_comprador_nao_vira_a_unidade():
    anexo, _ = contrato_do_lancamento(
        [_anexo("CONTRATO CONDOMÍNIO EXEMPLO CASA 16 - FULANO CASA 15")], 15)
    assert anexo is None


def test_contrato_do_lancamento_nao_pega_caixa_nem_distrato_nem_boleto():
    anexos = [_anexo("CONTRATO CAIXA CASA 15", "a"),
              _anexo("DISTRATO CONTRATO CASA 15", "b"),
              _anexo("BOLETO CASA 15", "c")]
    anexo, _ = contrato_do_lancamento(anexos, 15)
    assert anexo is None


def test_dois_contratos_no_lancamento_viram_revisao():
    anexos = [_anexo("CONTRATO CONDOMÍNIO EXEMPLO CASA 15 - FULANO", "a"),
              _anexo("CONTRATO CONDOMÍNIO EXEMPLO CASA 15 - BELTRANO", "b")]
    anexo, motivo = contrato_do_lancamento(anexos, 15)
    assert anexo is None
    assert "disputam" in motivo
