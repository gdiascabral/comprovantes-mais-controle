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

#: A forma REAL da lista de pagamentos: `value` nulo e o dinheiro partido em
#: `remainingValue` + `sumOfPaidValues` (contrato conferido em produção,
#: `conciliacao/erp/payments_api.py`). A fixtura antiga trazia `plannedValue`,
#: que só existe no DETALHE do título — e por isso concordava com o engano do
#: código em vez de expô-lo.
PARCELAS = [{"id": "par-1", "tradePayableId": "tp-1",
             "plannedDate": "2026-09-12", "value": None,
             "remainingValue": 620.00, "sumOfPaidValues": 0,
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
                            "value": None, "remainingValue": 641.31,
                            "sumOfPaidValues": 0,
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


def test_titulo_pago_em_parte_ainda_casa_pelo_valor_CHEIO(tmp_path):
    """A guia traz o valor cheio; o ERP, na lista, traz o que FALTA pagar.

    Se a comparação usar só `remainingValue`, um título já pago pela metade
    deixa de ser reconhecido — e não reconhecer aqui não dá erro nenhum: dá um
    SEGUNDO lançamento para a mesma guia, que ninguém vê até alguém pagar duas
    vezes.
    """
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="",
                 valor=Decimal("641.31"), vencimento=date(2026, 9, 12))
    parcelas = [{"id": "par-9", "tradePayableId": "tp-9",
                 "plannedDate": "2026-09-12", "value": None,
                 "remainingValue": 400.00, "sumOfPaidValues": 241.31,
                 "documentNumber": ""}]

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == DECIDIR
    assert d.trade_payable_id == "tp-9"


def test_parcela_que_so_traz_plannedValue_NAO_e_lida(tmp_path):
    """`plannedValue` é campo do DETALHE do título, não da lista.

    Este teste existe para o dia em que alguém "consertar" a leitura de volta
    para o nome que parece certo: a lista real não tem esse campo, e uma
    fixtura que o tivesse concordaria com o engano em silêncio.
    """
    assert mod.valor_da_parcela({"plannedValue": 641.31}) is None

    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="",
                 valor=Decimal("641.31"), vencimento=date(2026, 9, 12))
    parcelas = [{"id": "par-9", "tradePayableId": "tp-9",
                 "plannedDate": "2026-09-12", "plannedValue": 641.31,
                 "documentNumber": ""}]

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == CRIAR


def test_linha_digitavel_FORMATADA_casa_com_os_digitos_crus(tmp_path):
    """O caso que a primeira rodada real encontraria.

    A guia com boleto traz a linha digitável com pontos e espaços, porque é
    assim que ela sai do documento; quem lançou o título à mão no ERP digitou
    os dígitos crus. Comparar só o texto diz "não é o mesmo" e manda CRIAR —
    segundo título para uma conta que já existe.
    """
    linha = "00000.00000 00000.000000 00000.000000 0 00000000000001"
    crus = "00000000000000000000000000000000000000000000001"
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento=linha)
    parcelas = [{"id": "par-9", "tradePayableId": "tp-9",
                 "plannedDate": "2026-09-12", "value": None,
                 "remainingValue": 641.31, "sumOfPaidValues": 0,
                 "documentNumber": crus}]

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == JA_LANCADO
    assert d.trade_payable_id == "tp-9"


def test_numero_curto_NAO_casa_por_digitos(tmp_path):
    """Sem um piso de dígitos, "Guia 1" e "Doc 1" seriam o mesmo documento."""
    assert mod.documento_igual("GUIA 1", "DOC 1") is False
    assert mod.documento_igual("12345", "1-23-45") is False
    assert mod.documento_igual("", "123456") is False
    # Os que um piso baixo casaria de graça, e que não têm nada a ver com a
    # linha digitável — o único caso que motiva comparar por dígitos.
    assert mod.documento_igual("123456", "NF 123456") is False
    assert mod.documento_igual("092026", "09/2026") is False
    assert mod.documento_igual("2026/0001", "2026-0001") is False
    # E o caso de verdade: 47 dígitos com pontos contra 47 dígitos crus.
    linha = "00000.00000 00000.000000 00000.000000 0 00000000000001"
    crus = "00000000000000000000000000000000000000000000001"
    assert mod.documento_igual(linha, crus) is True


def test_documento_que_nao_casa_com_titulo_no_mesmo_vencimento_vira_DECIDIR(tmp_path):
    """Não reconhecer o documento não autoriza criar.

    O título está lá, no mesmo vencimento e com valor compatível, e o número
    dele foi escrito de um jeito que eu não sei ler. Criar por cima é a única
    coisa aqui que ninguém desfaz sozinho; perguntar custa uma linha.
    """
    guia = _guia(desc="BOLETO RET 62 UNIDADES",
                 documento="00000.00000 00000.000000 00000.000000 0 "
                           "00000000000001")
    parcelas = [{"id": "par-9", "tradePayableId": "tp-9",
                 "plannedDate": "2026-09-12", "value": None,
                 "remainingValue": 641.31, "sumOfPaidValues": 0,
                 "documentNumber": "NOSSO NUMERO 12345"}]

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == DECIDIR
    assert d.trade_payable_id == "tp-9"
    assert "outro número de documento" in d.motivo


def test_guia_paga_com_juros_vira_DECIDIR_e_nao_CRIAR(tmp_path):
    """`sumOfPaidValues` traz o que SAIU, com multa e juros: o título fica
    MAIOR que a guia. Exigir valor igual mandaria criar de novo."""
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="",
                 valor=Decimal("620.00"), vencimento=date(2026, 9, 12))
    parcelas = [{"id": "par-9", "tradePayableId": "tp-9",
                 "plannedDate": "2026-09-12", "value": None,
                 "remainingValue": 0, "sumOfPaidValues": 645.31,
                 "documentNumber": ""}]

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == DECIDIR


def test_titulo_grande_demais_no_mesmo_dia_NAO_segura_a_criacao(tmp_path):
    """O teto existe para o outro lado: um título de R$ 9.000 que só coincide
    na data não é esta guia, e virar DECIDIR em cima dele encheria a lista de
    perguntas falsas até o dono aprovar sem ler."""
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="",
                 valor=Decimal("620.00"), vencimento=date(2026, 9, 12))
    parcelas = [{"id": "par-9", "tradePayableId": "tp-9",
                 "plannedDate": "2026-09-12", "value": None,
                 "remainingValue": 9000.00, "sumOfPaidValues": 0,
                 "documentNumber": ""}]

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == CRIAR


def test_recorrencia_escolhe_a_parcela_do_vencimento_da_guia(tmp_path):
    """A janela cobre dois meses, e a recorrência mensal tem uma parcela em
    cada um. Pegar a primeira da lista alteraria o título do mês errado — que
    pode já estar pago."""
    parcelas = [
        {"id": "par-out", "tradePayableId": "tp-1", "plannedDate": "2026-10-12",
         "value": None, "remainingValue": 620.00, "sumOfPaidValues": 0,
         "documentNumber": ""},
        {"id": "par-set", "tradePayableId": "tp-1", "plannedDate": "2026-09-12",
         "value": None, "remainingValue": 620.00, "sumOfPaidValues": 0,
         "documentNumber": ""},
    ]

    [d] = mod.decidir([_guia()], parcelas, _regras(tmp_path, [TIPO_ALTERAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == ALTERAR
    assert d.parcela_id == "par-set"


DUAS_DA_RECORRENCIA = [
    {"id": "par-set", "tradePayableId": "tp-1", "plannedDate": "2026-09-20", "value": None, "remainingValue": 620.0, "sumOfPaidValues": 0, "documentNumber": ""},
    {"id": "par-out", "tradePayableId": "tp-1", "plannedDate": "2026-10-20", "value": None, "remainingValue": 620.0, "sumOfPaidValues": 0, "documentNumber": ""},
]


def test_recorrencia_sem_vencimento_nenhum_PERGUNTA_em_vez_de_chutar(tmp_path):
    """O caso normal da ficha de arrecadação.

    FGTS, INSS e contribuição não levam vencimento no código de barras, então
    o do PDF vem vazio. Com a janela de dois meses a recorrência tem uma
    parcela em cada mês, e pegar a primeira da lista alteraria o título do mês
    errado — que pode já estar pago, e que passa a pedir o valor do outro.
    """
    guia = _guia(vencimento=None)

    [d] = mod.decidir([guia], DUAS_DA_RECORRENCIA,
                      _regras(tmp_path, [TIPO_ALTERAR]), _registro(tmp_path),
                      COMP)

    assert d.acao == DECIDIR
    assert "vencimento" in d.motivo


def test_recorrencia_usa_o_vencimento_do_PORTAL_quando_o_pdf_nao_traz(tmp_path):
    """O dado existe: o portal diz o prazo. Não usá-lo transformaria em
    pergunta quase toda guia de imposto, que é o grosso da rodada."""
    guia = _guia(vencimento=None, vencimento_portal=date(2026, 10, 20))

    [d] = mod.decidir([guia], DUAS_DA_RECORRENCIA,
                      _regras(tmp_path, [TIPO_ALTERAR]), _registro(tmp_path),
                      COMP)

    assert d.acao == ALTERAR
    assert d.parcela_id == "par-out"


def test_recorrencia_com_UMA_parcela_nao_precisa_de_vencimento(tmp_path):
    """Sem ambiguidade não há o que perguntar: recorrência com uma parcela só
    na janela continua virando ALTERAR."""
    guia = _guia(vencimento=None)

    [d] = mod.decidir([guia], PARCELAS, _regras(tmp_path, [TIPO_ALTERAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == ALTERAR
    assert d.parcela_id == "par-1"


def test_empate_de_distancia_e_resolvido_pelo_MES_do_vencimento(tmp_path):
    """Empate não é caso de borda: o dia do prazo no portal e o dia da parcela
    no ERP são fixos por recorrência, então um offset de 15 dias empata em todo
    mês de intervalo par. A MESMA recorrência perguntaria em setembro e não
    perguntaria em agosto, sem nenhuma informação nova — e a resposta do dono
    seria sempre a mesma."""
    parcelas = [
        {"id": "par-set", "tradePayableId": "tp-1", "plannedDate": "2026-09-05",
         "value": None, "remainingValue": 620.00, "sumOfPaidValues": 0,
         "documentNumber": ""},
        {"id": "par-out", "tradePayableId": "tp-1", "plannedDate": "2026-10-05",
         "value": None, "remainingValue": 620.00, "sumOfPaidValues": 0,
         "documentNumber": ""},
    ]
    guia = _guia(vencimento=None, vencimento_portal=date(2026, 9, 20))

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_ALTERAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == ALTERAR
    assert d.parcela_id == "par-set"


def test_empate_de_verdade_PERGUNTA_em_vez_de_seguir_a_ordem_da_api(tmp_path):
    """Duas parcelas da mesma recorrência no MESMO mês, à mesma distância.
    Aí não há critério: `min` ficaria com a primeira da lista, que é a ordem
    em que o ERP devolveu — a mesma rodada com a lista invertida escolheria a
    outra."""
    parcelas = [
        {"id": "par-a", "tradePayableId": "tp-1", "plannedDate": "2026-09-05",
         "value": None, "remainingValue": 620.00, "sumOfPaidValues": 0,
         "documentNumber": ""},
        {"id": "par-b", "tradePayableId": "tp-1", "plannedDate": "2026-09-25",
         "value": None, "remainingValue": 620.00, "sumOfPaidValues": 0,
         "documentNumber": ""},
    ]
    guia = _guia(vencimento=date(2026, 9, 15))

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_ALTERAR]),
                      _registro(tmp_path), COMP)
    [invertida] = mod.decidir([guia], list(reversed(parcelas)),
                              _regras(tmp_path, [TIPO_ALTERAR]),
                              _registro(tmp_path), COMP)

    assert d.acao == DECIDIR and invertida.acao == DECIDIR
    assert "mesma distância" in d.motivo


def test_parcela_unica_de_OUTRO_mes_pergunta(tmp_path):
    """Uma parcela só na janela não é licença para alterar: alterar move a
    data e troca o valor dela, então a de setembro viraria a guia de outubro."""
    parcelas = [{"id": "par-set", "tradePayableId": "tp-1",
                 "plannedDate": "2026-09-05", "value": None,
                 "remainingValue": 620.00, "sumOfPaidValues": 0,
                 "documentNumber": ""}]
    guia = _guia(vencimento=date(2026, 10, 20))

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_ALTERAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == DECIDIR
    assert "outro mês" in d.motivo


def test_nosso_numero_CURTO_nao_perde_as_duas_protecoes(tmp_path):
    """Quando a linha digitável não fecha o dígito verificador, a leitura cai
    no número solto do texto e a guia sai com onze dígitos pontuados contra
    onze dígitos crus no ERP. Exigir o tamanho da linha digitável desligava o
    "já lançado" E a pergunta de uma vez — e o que sobra é criar por cima."""
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="123.456.789-01",
                 valor=Decimal("641.31"), vencimento=date(2026, 9, 12))
    parcelas = [{"id": "par-9", "tradePayableId": "tp-9",
                 "plannedDate": "2026-09-12", "value": None,
                 "remainingValue": 641.31, "sumOfPaidValues": 0,
                 "documentNumber": "12345678901"}]

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == DECIDIR
    assert d.trade_payable_id == "tp-9"


def test_a_pergunta_aponta_para_o_titulo_MAIS_PROXIMO_em_valor(tmp_path):
    """Quem lê a pergunta abre o título no ERP para responder. Apontar para um
    alheio que só cabe na faixa faz o dono responder "não é" olhando o título
    errado — e o certo fica lá, convidando o lançamento à mão."""
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="",
                 valor=Decimal("1000.00"), vencimento=date(2026, 9, 12))
    parcelas = [
        {"id": "par-alheio", "tradePayableId": "tp-alheio",
         "plannedDate": "2026-09-12", "value": None, "remainingValue": 700.00,
         "sumOfPaidValues": 0, "documentNumber": "OUTRO"},
        {"id": "par-certo", "tradePayableId": "tp-certo",
         "plannedDate": "2026-09-12", "value": None, "remainingValue": 1000.00,
         "sumOfPaidValues": 0, "documentNumber": ""},
    ]

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == DECIDIR
    assert d.trade_payable_id == "tp-certo"
    assert d.parcela_id == "par-certo"


def test_titulo_MAIS_BARATO_que_a_guia_tambem_segura_a_criacao(tmp_path):
    """Em título ainda em aberto o cadastro está pelo nominal e quem carrega
    multa e juros é a GUIA, reimpressa com o valor do dia: o título fica MENOR.
    Uma faixa só para cima deixava um título um centavo mais barato passar
    direto para CRIAR."""
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="",
                 valor=Decimal("1000.01"), vencimento=date(2026, 9, 12))
    parcelas = [{"id": "par-9", "tradePayableId": "tp-9",
                 "plannedDate": "2026-09-12", "value": None,
                 "remainingValue": 1000.00, "sumOfPaidValues": 0,
                 "documentNumber": ""}]

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == DECIDIR


def test_rotulo_curto_que_nao_bateu_e_OUTRO_documento_e_pode_criar(tmp_path):
    """O contrário do teste acima: quando a guia traz um rótulo curto de gente
    e ele não é igual a nenhum documento do mês, são dois documentos
    diferentes. Segurar aí encheria a lista de perguntas falsas, e pergunta
    falsa demais ensina o dono a aprovar sem ler."""
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="DOC-RET",
                 valor=Decimal("620.00"), vencimento=date(2026, 9, 12))

    [d] = mod.decidir([guia], PARCELAS, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == CRIAR


def test_ja_lancado_leva_a_PARCELA_para_o_botao_de_abrir_no_erp(tmp_path):
    """A linha em que o app acaba de afirmar que o título existe é a que mais
    precisa ser conferida a olho — e sem `parcela_id` o botão "Abrir no ERP"
    responde "esta linha ainda não tem parcela no ERP", que é falso."""
    guia = _guia(desc="BOLETO RET 62 UNIDADES", documento="DOC-RET")
    parcelas = PARCELAS + [{"id": "par-9", "tradePayableId": "tp-9",
                            "plannedDate": "2026-09-15", "value": None,
                            "remainingValue": 641.31, "sumOfPaidValues": 0,
                            "documentNumber": "DOC-RET"}]

    [d] = mod.decidir([guia], parcelas, _regras(tmp_path, [TIPO_CRIAR]),
                      _registro(tmp_path), COMP)

    assert d.acao == JA_LANCADO
    assert d.parcela_id == "par-9"


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
                 "plannedDate": "2026-09-12", "value": None,
                 "remainingValue": 641.31, "sumOfPaidValues": 0,
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
