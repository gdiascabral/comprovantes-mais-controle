# -*- coding: utf-8 -*-
"""Sanesc: a UC tem 5 dígitos ("UC 12345", fictícia) e o boletim a escreve como
"Cadastro 000012345". Até 24/11/2026 a regra pedia 6+ dígitos, toda linha
da Sanesc saía "UC ? (não informada na descrição)" e caía em NÃO LI."""
from pagamentos_dia import nivel, relatorio

# Forma do boletim da Sanesc; nomes, endereço e linha são inventados
# (linha sintética com os dígitos verificadores fechando).
BOLETIM = """AGENCIA DE SANEAMENTO DE SENADOR CANEDO - GO
BOLETIM DE ARRECADACAO
Inscricao
Cadastro
000012345
TB - 19
FULANO DE TAL
RES EXEMPLO
CASA 1
Quadra
51
Lote
13
1098814 000012345
82680000000-0 52743742111-0 12222333344-6 44555566667-3"""
LINHA = "826800000000527437421110122223333446445555666673"


def item(uc="12345"):
    return {"paidTo": "Sanesc", "remainingValue": 52.74,
            "description": f"TB 19 QD 51 LT 13 UC {uc} REF OUT 2026 CASA 1",
            "costCentreDetails": [{"workName": "TB 19 QD 51 LT 13"}]}


def test_uc_de_cinco_digitos_e_lida_da_descricao():
    assert relatorio.unidade_consumidora(item()) == "12345"


def test_uc_da_sanesc_confere_pelo_cadastro_do_boletim():
    resumo, divergiu = relatorio.conferir_documento(item(), [], [BOLETIM],
                                                    textos_valor=[BOLETIM])
    assert not divergiu and "UC 12345 ✓" in resumo


def test_uc_curta_sem_rotulo_nao_prova():
    """CEP, lote, NF ou protocolo com os mesmos 5 dígitos não são a UC."""
    for texto in ["CEP 12345", "Lote 12345", "NF 12345", "Protocolo 12345/2026"]:
        resumo, divergiu = relatorio.conferir_documento(item(), [], [texto],
                                                        textos_valor=[texto])
        assert divergiu and "UC DIVERGE" in resumo, texto


def test_uc_curta_nao_casa_por_acaso_no_meio_de_outro_numero():
    # 12345 escondido dentro de outros números não prova nada.
    texto = "Codigo 9912345001 · 1961234599"
    resumo, divergiu = relatorio.conferir_documento(item(), [], [texto],
                                                    textos_valor=[texto])
    assert divergiu and "UC DIVERGE" in resumo


def test_uc_de_outra_casa_diverge():
    outro = BOLETIM.replace("000012345", "000012399")
    _, divergiu = relatorio.conferir_documento(item(), [], [outro], textos_valor=[outro])
    assert divergiu


def test_uc_so_na_observacao_do_lancamento_nao_prova():
    """A observação é o que o lançamento diz de si mesmo."""
    resumo, divergiu = relatorio.conferir_documento(
        item(), [], ["Cadastro 000012345"], textos_valor=[])
    assert "UC 12345 ✓" not in resumo


def test_sanesc_com_boletim_certo_sai_do_nao_li():
    resumo, _ = relatorio.conferir_documento(item(), [], [BOLETIM], textos_valor=[BOLETIM])
    r = {"status": "APTO", "conferencia": resumo, "tipo": "Boleto",
         "dados": LINHA, "valor": 52.74}
    n = nivel.nivel_da_linha(r)
    assert n.nome == nivel.PODE_PAGAR, n.motivos


def test_observacao_que_so_repete_a_linha_do_boleto_e_ruido():
    coment = "Linha digitavel: 82680000000-0 52743742111-0 12222333344-6 44555566667-3"
    assert relatorio.observacao_relevante(coment, LINHA) == ""


def test_observacao_com_linha_diferente_aparece():
    coment = "Linha digitavel: 82680000000-0 52743742111-0 12222333344-6 44555566668-0"
    assert relatorio.observacao_relevante(coment, LINHA) == coment


def test_observacao_com_texto_alem_da_linha_aparece():
    coment = "Linha digitavel: 82680000000-0 52743742111-0 12222333344-6 44555566667-3 pagar hoje"
    assert relatorio.observacao_relevante(coment, LINHA) == coment


def linha_sanesc(**extra):
    return {"status": "APTO", "tipo": "Boleto", "dados": LINHA, "valor": 52.74,
            "favorecido": "Sanesc",
            "conferencia": "UC ? (não informada na descrição) · valor ✓", **extra}


def test_convenio_prova_a_empresa_mas_sem_uc_vai_para_olhe():
    """O código de barras diz que o dinheiro vai para a Sanesc, não para qual
    casa: lançamento sem UC conferida sai de NÃO LI, mas não fica verde."""
    n = nivel.nivel_da_linha(linha_sanesc())
    assert dict(n.conferido)["quem recebe"] == nivel.BATE
    assert n.nome == nivel.OLHE
    assert nivel.MOTIVO_UC_NAO_CONFERIDA in n.motivos


def test_convenio_com_uc_conferida_pode_pagar():
    n = nivel.nivel_da_linha(linha_sanesc(conferencia="UC 12345 ✓ · valor ✓"))
    assert n.nome == nivel.PODE_PAGAR, n.motivos


def test_convenio_da_sanesc_nao_prova_outro_favorecido():
    n = nivel.nivel_da_linha(linha_sanesc(favorecido="Equatorial"))
    assert n.nome == nivel.NAO_LI


def test_convenio_desconhecido_nao_prova():
    # Mesmo boleto com o código da empresa trocado (DVs refeitos).
    outra = "826500000003527499991117122223333446445555666673"
    from pagamentos_dia import ocr_boleto
    assert ocr_boleto.valida(outra)
    n = nivel.nivel_da_linha(linha_sanesc(dados=outra))
    assert n.nome == nivel.NAO_LI


def test_uc_diverge_vence_o_convenio():
    n = nivel.nivel_da_linha(linha_sanesc(
        conferencia="UC DIVERGE: 12345 não aparece no anexo · valor ✓"))
    assert dict(n.conferido)["quem recebe"] == nivel.DIVERGE
    assert n.nome != nivel.PODE_PAGAR
