# -*- coding: utf-8 -*-
"""A decisão: alterar, criar, já lançado, ou você decide.

É a peça que mexe com dinheiro sem tocar em rede — então é aqui que os casos
ruins têm de estar todos. Nomes e ids INVENTADOS: o repositório é público.
"""
import json
from datetime import date
from decimal import Decimal

from guias import casamento as mod
from guias import regras as mod_regras
from guias import registro as mod_registro
from guias.modelos import ALTERAR, CRIAR, DECIDIR, JA_LANCADO, Guia

COMP = "2026-09"


def _guia(**campos):
    base = dict(vip_id="701", empresa="EMPRESA UM", desc="HONORARIO CONTABIL",
                anx_id="111", competencia=COMP, pdf="C:/tmp/x.pdf",
                valor=Decimal("641.31"), vencimento=date(2026, 9, 12),
                documento="DOC-1")
    base.update(campos)
    return Guia(**base)


def _regras(tmp_path, tipos):
    caminho = tmp_path / "guias_regras.json"
    caminho.write_text(json.dumps({"versao": 1, "tipos": tipos},
                                  ensure_ascii=False), encoding="utf-8")
    return mod_regras.Regras.carregar(caminho)


def _registro(tmp_path):
    return mod_registro.Registro.carregar(tmp_path / "r.jsonl")


TIPO_ALTERAR = {"nome": "honorario", "quando": {"desc_contem": ["HONORARIO"]},
                "acao": "alterar", "categoria": "Honorários",
                "recorrencia": {"701": {"trade_payable_id": "tp-1",
                                        "obra": "obra-9"}}}
TIPO_CRIAR = {"nome": "regularizacao", "quando": {"desc_contem": ["RET"]},
              "acao": "criar", "categoria": "Taxa de abertura",
              "favorecido": "FORNECEDOR FICTICIO",
              "descricao": "{documento} - competencia {competencia}",
              "parcelas": 4, "obra": {"701": "obra-7"}}

PARCELAS = [{"id": "par-1", "tradePayableId": "tp-1",
             "plannedDate": "2026-09-12", "plannedValue": 620.00,
             "documentNumber": "ANTIGO"}]


def test_recorrencia_conhecida_vira_alterar(tmp_path):
    [d] = mod.decidir([_guia()], PARCELAS, _regras(tmp_path, [TIPO_ALTERAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == ALTERAR
    assert d.trade_payable_id == "tp-1"
    assert d.parcela_id == "par-1"
    assert d.categoria == "Honorários"


def test_tipo_desconhecido_vira_decidir(tmp_path):
    [d] = mod.decidir([_guia(desc="ALGO QUE NINGUEM CADASTROU")], PARCELAS,
                      _regras(tmp_path, [TIPO_ALTERAR]), _registro(tmp_path), COMP)

    assert d.acao == DECIDIR
    assert "não conheço" in d.motivo.lower() or "nao conheco" in d.motivo.lower()


def test_recorrencia_que_a_regra_aponta_e_nao_esta_no_mes_vira_decidir(tmp_path):
    """A regra diz que existe recorrência e ela não veio: alguma coisa mudou no
    ERP. Criar aqui seria criar um título paralelo à recorrência."""
    [d] = mod.decidir([_guia()], [], _regras(tmp_path, [TIPO_ALTERAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == DECIDIR


def test_duas_guias_do_mesmo_tipo_na_mesma_empresa_viram_decidir(tmp_path):
    """Review Focus 1: apontariam para a MESMA parcela, e a segunda gravação
    apagaria a primeira sem ninguém ver."""
    guias = [_guia(anx_id="111", documento="DOC-1"),
             _guia(anx_id="112", documento="DOC-2")]

    decisoes = mod.decidir(guias, PARCELAS, _regras(tmp_path, [TIPO_ALTERAR]),
                           _registro(tmp_path), COMP)

    assert [d.acao for d in decisoes] == [DECIDIR, DECIDIR]
    assert all("mais de uma" in d.motivo.lower() for d in decisoes)


def test_guia_sem_pdf_nunca_vira_lancamento(tmp_path):
    """Review Focus 3. Sem `erro` preenchido, para exercitar a guarda do PDF e
    não a do erro — que é outro teste."""
    [d] = mod.decidir([_guia(pdf=None)], PARCELAS,
                      _regras(tmp_path, [TIPO_ALTERAR]), _registro(tmp_path), COMP)

    assert d.acao == DECIDIR
    assert "PDF" in d.motivo or "pdf" in d.motivo


def test_guia_sem_valor_nunca_vira_lancamento(tmp_path):
    [d] = mod.decidir([_guia(valor=None)], PARCELAS,
                      _regras(tmp_path, [TIPO_ALTERAR]), _registro(tmp_path), COMP)

    assert d.acao == DECIDIR


def test_criar_quando_a_regra_manda_criar_e_nao_ha_titulo_igual(tmp_path):
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="DOC-RET",
                 valor=Decimal("2504.95"), vencimento=date(2026, 9, 15))

    [d] = mod.decidir([guia], PARCELAS, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == CRIAR
    assert d.parcelas == 4
    assert d.obra_id == "obra-7"
    assert d.descricao == "DOC-RET - competencia 2026-09"
    assert d.favorecido == "FORNECEDOR FICTICIO"


def test_titulo_com_o_mesmo_documento_no_mes_vira_ja_lancado(tmp_path):
    """A única camada que enxerga lançamento feito à mão pela tela do ERP."""
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="DOC-RET")
    parcelas = PARCELAS + [{"id": "par-9", "tradePayableId": "tp-9",
                            "plannedDate": "2026-09-15",
                            "plannedValue": 641.31,
                            "documentNumber": "DOC-RET"}]

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == JA_LANCADO
    assert d.trade_payable_id == "tp-9"


def test_registro_da_rodada_anterior_vira_ja_lancado(tmp_path):
    reg = _registro(tmp_path)
    reg.anotar(vip_id="701", anx_id="111", competencia=COMP, acao="alterar",
               estado="alterado", tpid="tp-1")

    [d] = mod.decidir([_guia()], PARCELAS, _regras(tmp_path, [TIPO_ALTERAR]),
                      reg, COMP)

    assert d.acao == JA_LANCADO


def test_ja_lancado_leva_o_estado_anterior_no_motivo(tmp_path):
    """I11: "anexo_pendente" é um título SEM PDF. Escondê-lo atrás de um
    "já lançou" genérico faz essa guia voltar toda rodada como pronta, e o
    PDF nunca mais é cobrado de ninguém."""
    reg = _registro(tmp_path)
    reg.anotar(vip_id="701", anx_id="111", competencia=COMP, acao="alterar",
               estado="anexo_pendente", tpid="tp-1")

    [d] = mod.decidir([_guia()], PARCELAS, _regras(tmp_path, [TIPO_ALTERAR]),
                      reg, COMP)

    assert d.acao == JA_LANCADO
    assert "anexo_pendente" in d.motivo


OBRAS = [{"id": "obra-1", "name": "CONDOMINIO PRIMEIRO"},
         {"id": "obra-2", "name": "CONDOMINIO SEGUNDO"}]


def test_sugere_a_obra_cujo_nome_aparece_no_documento():
    assert mod.sugerir_obra("BOLETO RET CONDOMINIO SEGUNDO", OBRAS) == "obra-2"


def test_nao_sugere_obra_quando_duas_batem():
    """Duas obras no mesmo texto: escolher uma seria palpite. O dono escolhe."""
    texto = "RET CONDOMINIO PRIMEIRO E CONDOMINIO SEGUNDO"

    assert mod.sugerir_obra(texto, OBRAS) == ""


def test_nao_sugere_obra_quando_nenhuma_bate():
    assert mod.sugerir_obra("BOLETO SEM NOME DE OBRA", OBRAS) == ""


def test_criar_usa_a_obra_da_regra_e_nao_a_sugestao(tmp_path):
    """Regra é o que o dono já confirmou; sugestão é palpite. Regra ganha."""
    guia = _guia(desc="BOLETO RET CONDOMINIO SEGUNDO", documento="DOC-RET")

    [d] = mod.decidir([guia], PARCELAS, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP, obras=OBRAS)

    assert d.obra_id == "obra-7"


def test_criar_sem_obra_na_regra_recebe_a_sugestao_marcada_como_tal(tmp_path):
    tipo = dict(TIPO_CRIAR)
    tipo.pop("obra")
    guia = _guia(desc="BOLETO RET CONDOMINIO SEGUNDO", documento="DOC-RET")

    [d] = mod.decidir([guia], PARCELAS, _regras(tmp_path, [tipo]),
                      _registro(tmp_path), COMP, obras=OBRAS)

    assert d.obra_id == "obra-2"
    assert d.obra_sugerida is True


def test_criar_sem_obra_nenhuma_vira_decidir(tmp_path):
    """Sem obra não há conta, e sem conta não há lançamento."""
    tipo = dict(TIPO_CRIAR)
    tipo.pop("obra")
    guia = _guia(desc="BOLETO RET SEM NOME DE OBRA", documento="DOC-RET")

    [d] = mod.decidir([guia], PARCELAS, _regras(tmp_path, [tipo]),
                      _registro(tmp_path), COMP, obras=OBRAS)

    assert d.acao == DECIDIR
    assert "obra" in d.motivo.lower()


def test_valor_do_pdf_diferente_do_titulo_avisa_mas_nao_impede(tmp_path):
    """Review Focus 2: o PDF é o documento que se paga, então ele manda — e a
    divergência aparece, em vez de ser escolhida em silêncio."""
    [d] = mod.decidir([_guia(valor=Decimal("999.99"))], PARCELAS,
                      _regras(tmp_path, [TIPO_ALTERAR]), _registro(tmp_path), COMP)

    assert d.acao == ALTERAR
    assert d.aviso
    assert "620" in d.aviso and "999,99" in d.aviso.replace(".", ",")


def test_guia_com_erro_de_leitura_vira_decidir_com_o_motivo_do_erro(tmp_path):
    [d] = mod.decidir([_guia(erro="o link da guia expirou")], PARCELAS,
                      _regras(tmp_path, [TIPO_ALTERAR]), _registro(tmp_path), COMP)

    assert d.acao == DECIDIR
    assert "expirou" in d.motivo


def test_alterar_funciona_com_obra_vazia_na_regra(tmp_path):
    """Alterar NÃO precisa de obra: a conta e a obra já estão no título que o
    ERP devolve, e não são tocadas. A regra "sem obra não há lançamento" vale
    só para CRIAR, onde a conta tem de ser deduzida da obra."""
    tipo = {"nome": "honorario", "quando": {"desc_contem": ["HONORARIO"]},
            "acao": "alterar", "categoria": "Honorários",
            "recorrencia": {"701": {"trade_payable_id": "tp-1", "obra": ""}}}

    [d] = mod.decidir([_guia()], PARCELAS, _regras(tmp_path, [tipo]),
                      _registro(tmp_path), COMP)

    assert d.acao == ALTERAR
    assert d.obra_id == ""


def test_sem_documento_colisao_de_valor_e_vencimento_vira_decidir(tmp_path):
    """Valor e vencimento iguais acontecem entre fornecedores diferentes. Dar
    isso como já lançado faz a conta a pagar nunca ser criada."""
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="",
                 valor=Decimal("641.31"), vencimento=date(2026, 9, 12))
    parcelas = [{"id": "par-9", "tradePayableId": "tp-9",
                 "plannedDate": "2026-09-12", "plannedValue": 641.31,
                 "documentNumber": ""}]

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == DECIDIR
    assert "número de documento" in d.motivo


def test_sem_documento_e_sem_colisao_segue_criando(tmp_path):
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="",
                 valor=Decimal("2504.95"), vencimento=date(2026, 9, 15))

    [d] = mod.decidir([guia], PARCELAS, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == CRIAR
