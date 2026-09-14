# -*- coding: utf-8 -*-
"""Testes do matcher: parse do NOME do PDF e casamento PDF↔pagamento.

Módulo sem dependências pesadas — roda sempre. Os pagamentos pendentes são
construídos à mão (sem tocar na API); os PDFs vêm de nomes de arquivo, como
o app recebe da pasta de renomeados."""
from anexar import matcher


# ------------------------------------------------------------ parse_pdf
def test_parse_pdf_padrao():
    p = matcher.parse_pdf("70,00 - RPB 24 QD 26A LT 12 OC 5979 - 20-07.pdf")
    assert p is not None
    assert p["valor"] == 7000
    assert p["data"] == "2007"
    assert p["desc"] == "RPB 24 QD 26A LT 12 OC 5979"
    assert "5979" in p["ocs"]


def test_parse_pdf_valor_com_milhar():
    p = matcher.parse_pdf("1.890,00 - CONDOMINIO OC 5428 - 01-07.pdf")
    assert p["valor"] == 189000
    assert "5428" in p["ocs"]


def test_parse_pdf_ignora_sufixo_duplicado():
    p = matcher.parse_pdf("70,00 - FORNECEDOR EXEMPLO - 20-07 (2).pdf")
    assert p is not None
    assert p["valor"] == 7000


def test_parse_pdf_valor_e_data_em_qualquer_posicao():
    # modelo personalizado: DATA - VALOR - RECEBEDOR
    p = matcher.parse_pdf("20-07 - 70,00 - FORNECEDOR EXEMPLO.pdf")
    assert p["valor"] == 7000
    assert p["data"] == "2007"
    assert p["desc"] == "FORNECEDOR EXEMPLO"


def test_parse_pdf_sem_valor_retorna_none():
    assert matcher.parse_pdf("FORNECEDOR EXEMPLO - 20-07.pdf") is None


def test_parse_pdf_nao_e_pdf():
    assert matcher.parse_pdf("70,00 - X - 20-07.txt") is None


# ------------------------------------------------------------ casar
def _pend(paid_id, valor, doc="", desc="", works=None, data="", valores=None):
    """Monta um pagamento pendente no formato que montar_pagos() produziria."""
    return {
        "paidId": paid_id, "launchId": "L-" + paid_id, "valor": valor,
        "valores": valores or [valor], "doc": doc, "desc": desc,
        "works": works or [], "data": data,
    }


def test_casar_certeza_por_ocnf():
    # OC ROTULADA na descrição do lançamento: é o sinal forte.
    pdfs = [matcher.parse_pdf("70,00 - RPB QD 26A LT 12 OC 5979 - 20-07.pdf")]
    pend = [_pend("A", 7000, desc="pagamento fornecedor OC 5979")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert len(certezas) == 1 and not duvidas and not sem_par
    assert certezas[0]["pdf"] == "70,00 - RPB QD 26A LT 12 OC 5979 - 20-07.pdf"
    assert "OC/NF" in certezas[0]["motivo"]


def test_ocnf_do_lancamento_exige_rotulo():
    """Número solto na descrição não é OC/NF.

    Um ano ("2026"), um CEP ou um telefone casavam com um PDF chamado
    "OC 2026" e fechavam CERTEZA sozinhos. Com dois pagamentos de mesmo valor
    disputando, o certo é DÚVIDA — não escolher no chute."""
    pdfs = [matcher.parse_pdf("70,00 - OBRA OC 2026 - 20-07.pdf"),
            matcher.parse_pdf("70,00 - OUTRA COISA - 21-07.pdf")]
    pend = [_pend("A", 7000, desc="SERVICO REFERENTE A 2026"),
            _pend("B", 7000, desc="OUTRO SERVICO")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert not certezas, "número solto na descrição não pode fechar CERTEZA"
    assert len(duvidas) == 2


def test_documento_cru_sozinho_nao_fecha_certeza():
    """`documentNumber` cru é sinal FRACO: com concorrente de mesmo valor,
    não basta para casar (mas continua valendo como desempate)."""
    pdfs = [matcher.parse_pdf("70,00 - FORNECEDOR OC 5979 - 20-07.pdf"),
            matcher.parse_pdf("70,00 - OUTRO FORNECEDOR - 21-07.pdf")]
    pend = [_pend("A", 7000, doc="5979", desc="sem rotulo aqui"),
            _pend("B", 7000, desc="outro")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert not certezas
    assert len(duvidas) == 2


def test_documento_cru_com_centro_de_custo_fecha_certeza():
    """Acompanhado do centro de custo, o nº do documento volta a valer."""
    pdfs = [matcher.parse_pdf("70,00 - RPB 24 QD 26A LT 12 OC 5979 - 20-07.pdf"),
            matcher.parse_pdf("70,00 - OUTRO FORNECEDOR - 21-07.pdf")]
    pend = [_pend("A", 7000, doc="5979", desc="x",
                  works=["RPB 24 QD 26A LT 12"]),
            _pend("B", 7000, desc="outro")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert len(certezas) == 1
    assert certezas[0]["paidId"] == "A"


def test_casar_certeza_por_data_sem_concorrente():
    pdfs = [matcher.parse_pdf("70,00 - FORNECEDOR EXEMPLO - 20-07.pdf")]
    pend = [_pend("A", 7000, desc="algo", data="2007")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert len(certezas) == 1
    assert certezas[0]["motivo"] == "data"


def test_casar_duvida_quando_ambiguo():
    # dois pagamentos e dois PDFs de mesmo valor, nada os distingue -> DÚVIDA
    pdfs = [matcher.parse_pdf("70,00 - FORNECEDOR A - 20-07.pdf"),
            matcher.parse_pdf("70,00 - FORNECEDOR B - 21-07.pdf")]
    pend = [_pend("A", 7000, desc="x"), _pend("B", 7000, desc="y")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert not certezas
    assert len(duvidas) == 2


def test_casar_sem_par_quando_nao_ha_valor_igual():
    pdfs = [matcher.parse_pdf("50,00 - OUTRO - 20-07.pdf")]
    pend = [_pend("A", 7000, desc="x")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert len(sem_par) == 1 and not certezas


def test_casar_aceita_valor_pago_com_juros():
    # PDF tem o valor PAGO (com juros); o pagamento guarda nominal e pago
    pdfs = [matcher.parse_pdf("105,00 - BOLETO OC 5428 - 20-07.pdf")]
    pend = [_pend("A", 10000, doc="5428", valores=[10000, 10500])]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert len(certezas) == 1
    assert certezas[0]["pdf"] == "105,00 - BOLETO OC 5428 - 20-07.pdf"


# ------------------------------------------- de onde saiu x conta cadastrada
# Regra do dono (14/09/2026): quando a OC não casa, olhar o nº do documento,
# DE ONDE SAIU o pagamento e QUAL A CONTA cadastrada no ERP. Medido nas 33
# dúvidas de 14/09: a conta sozinha resolveu 6 e cortou o candidato errado em
# outras 6 (título de conta de pessoa física casado com Pix de empresa).
# `origem` é (banco, identificador da conta) — quem monta é o Anexar, a partir
# do registro da baixa (PDF) e do cadastro de contas (título). None = não sei.

def _pdf(nome, origem=None, recebedor=None):
    p = matcher.parse_pdf(nome)
    p["origem"] = origem
    p["recebedor"] = recebedor
    return p


def _pend_conta(paid_id, valor, origem=None, favorecido="", **kw):
    pe = _pend(paid_id, valor, **kw)
    pe["origem"] = origem
    pe["favorecido"] = favorecido
    return pe


SICOOB_1 = ("SICOOB", "111111")
SICOOB_2 = ("SICOOB", "222222")


def test_pdf_que_saiu_de_outra_conta_nao_e_candidato():
    pdfs = [_pdf("60,00 - REEMBOLSO - 11-09.pdf", origem=SICOOB_2),
            _pdf("60,00 - REEMBOLSO - 11-09 (2).pdf", origem=SICOOB_1)]
    pend = [_pend_conta("A", 6000, origem=SICOOB_1, data="1109")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert len(certezas) == 1 and not duvidas
    assert certezas[0]["pdf"] == "60,00 - REEMBOLSO - 11-09 (2).pdf"


def test_banco_diferente_exclui_mesmo_sem_o_numero_da_conta():
    """O registro antigo do Inter não guarda a conta, só o banco -- e isso já
    basta para dizer que um título de conta de outro banco não é dele."""
    pdfs = [_pdf("60,00 - REEMBOLSO - 11-09.pdf", origem=("INTER", ""))]
    pend = [_pend_conta("A", 6000, origem=("PAGBANK", "PESSOAS FISICAS"),
                        data="1109")]
    certezas, duvidas, sem_par = matcher.casar(pend, pdfs)
    assert not certezas and not duvidas
    assert len(sem_par) == 1
    assert "outra conta" in sem_par[0]["motivo_sem_par"]


def test_sem_par_sem_pdf_de_mesmo_valor_diz_isso():
    pdfs = [_pdf("50,00 - OUTRO - 20-07.pdf", origem=SICOOB_1)]
    pend = [_pend_conta("A", 7000, origem=SICOOB_1)]
    _, _, sem_par = matcher.casar(pend, pdfs)
    assert "nenhum PDF" in sem_par[0]["motivo_sem_par"]


def test_origem_desconhecida_nao_exclui_ninguem():
    """PDF posto à mão na pasta (sem registro) ou conta fora do cadastro: não
    se sabe de onde saiu, então a conta não pode tirar ninguém da disputa."""
    pdfs = [_pdf("60,00 - REEMBOLSO - 11-09.pdf", origem=None)]
    pend = [_pend_conta("A", 6000, origem=SICOOB_1, data="1109")]
    certezas, _, _ = matcher.casar(pend, pdfs)
    assert len(certezas) == 1


def test_nr_do_documento_com_a_mesma_conta_fecha_certeza():
    """Sozinho o nº do documento é fraco (`test_documento_cru_sozinho...`);
    com a conta de onde saiu batendo, ele fecha."""
    pdfs = [_pdf("70,00 - FORNECEDOR NF 5979 - 20-07.pdf", origem=SICOOB_1),
            _pdf("70,00 - OUTRO FORNECEDOR - 20-07.pdf", origem=SICOOB_1)]
    pend = [_pend_conta("A", 7000, origem=SICOOB_1, doc="5979", desc="sem rotulo"),
            _pend_conta("B", 7000, origem=SICOOB_1, desc="outro")]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    por_id = {c["paidId"]: c for c in certezas}
    assert por_id["A"]["pdf"] == "70,00 - FORNECEDOR NF 5979 - 20-07.pdf"
    assert "conta" in por_id["A"]["motivo"]


def test_favorecido_conta_e_data_juntos_fecham_certeza():
    pdfs = [_pdf("900,00 - SERVICO - 11-09.pdf", origem=SICOOB_1,
                 recebedor="FULANO EXEMPLO TESTE"),
            _pdf("900,00 - SERVICO - 11-09 (2).pdf", origem=SICOOB_1,
                 recebedor="BELTRANA MODELO FICTICIA")]
    pend = [_pend_conta("A", 90000, origem=SICOOB_1, data="1109",
                        favorecido="Beltrana de Modelo Fictícia"),
            _pend_conta("B", 90000, origem=SICOOB_1, data="1109",
                        favorecido="Fulano Exemplo Teste")]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not duvidas
    por_id = {c["paidId"]: c["pdf"] for c in certezas}
    assert por_id == {"A": "900,00 - SERVICO - 11-09 (2).pdf",
                      "B": "900,00 - SERVICO - 11-09.pdf"}


def test_favorecido_sem_conta_conhecida_nao_fecha():
    """Nome parecido é sinal fraco: sem saber de onde saiu, fica em dúvida."""
    pdfs = [_pdf("900,00 - SERVICO - 11-09.pdf", recebedor="FULANO EXEMPLO TESTE"),
            _pdf("900,00 - SERVICO - 11-09 (2).pdf", recebedor="BELTRANA MODELO FICTICIA")]
    pend = [_pend_conta("A", 90000, data="1109", favorecido="Beltrana de Modelo Fictícia"),
            _pend_conta("B", 90000, data="1109", favorecido="Fulano Exemplo Teste")]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and len(duvidas) == 2


def test_um_nome_em_comum_nao_basta_para_o_favorecido():
    """"FULANO" em comum não é a mesma pessoa."""
    assert not matcher.mesmo_favorecido("Fulano Exemplo Teste", "FULANO OUTRO NOME")
    assert matcher.mesmo_favorecido("Beltrana de Modelo Fictícia", "BELTRANA MODELO FICTICIA")
    assert matcher.mesmo_favorecido("Ferragens Exemplo Ltda", "FERRAGENS EXEMPLO LTDA ME")
    assert matcher.mesmo_favorecido("Beltrana M Ficticia", "BELTRANA MODELO FICTICIA")
    assert not matcher.mesmo_favorecido("", "QUALQUER")


def test_sobrenome_ou_grupo_em_comum_nao_e_o_mesmo_favorecido():
    """Achado da revisão do PR #94: duas palavras em comum aceitavam irmãos e
    empresas do mesmo grupo. Agora o nome menor tem de estar INTEIRO no maior,
    com pelo menos duas palavras -- e numeral romano conta como palavra."""
    assert not matcher.mesmo_favorecido("JOAO PEREIRA DOS SANTOS", "MARIA PEREIRA DOS SANTOS")
    assert not matcher.mesmo_favorecido("ANA PAULA SILVA", "ANA PAULA SOUZA")
    assert not matcher.mesmo_favorecido("EXEMPLO ENGENHARIA ALFA SPE", "EXEMPLO ENGENHARIA BETA SPE")
    assert not matcher.mesmo_favorecido("EXEMPLO EMPREENDIMENTOS I", "EXEMPLO EMPREENDIMENTOS II")
    assert not matcher.mesmo_favorecido("CARTORIO", "CARTORIO DE REGISTRO")


def test_nr_do_documento_com_oc_no_pdf_nao_fecha_nem_com_a_mesma_conta():
    """Achado da revisão do PR #94 (bloqueava o merge): numa empresa de uma
    conta só, "nº do documento + mesma conta" era o nº do documento sozinho de
    novo -- e trocava dois anexos. O nº do documento do ERP é o da NOTA: só
    vale contra NF escrita no nome do PDF, nunca contra OC."""
    pdfs = [_pdf("1.500,00 - MATERIAL OC 5979 - 11-09.pdf", origem=SICOOB_1),
            _pdf("1.500,00 - SERVICO - 11-09.pdf", origem=SICOOB_1)]
    pend = [_pend_conta("A", 150000, origem=SICOOB_1, doc="5979", data="1109"),
            _pend_conta("B", 150000, origem=SICOOB_1, desc="compra", data="1109")]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and len(duvidas) == 2


def test_centro_de_custo_ganha_do_nr_do_documento_com_conta():
    """A ordem de antes: centro de custo vem ANTES do nº do documento."""
    pdfs = [_pdf("1.500,00 - RPB 24 QD 26A LT 12 NF 5979 - 11-09.pdf", origem=SICOOB_1),
            _pdf("1.500,00 - SERVICO - 11-09.pdf", origem=SICOOB_1)]
    pend = [_pend_conta("A", 150000, origem=SICOOB_1, doc="5979", data="1109"),
            _pend_conta("B", 150000, origem=SICOOB_1, desc="compra", data="1109",
                        works=["RPB 24 QD 26A LT 12"])]
    certezas, _, _ = matcher.casar(pend, pdfs)
    por_id = {c["paidId"]: c["pdf"] for c in certezas}
    assert por_id.get("B") == "1.500,00 - RPB 24 QD 26A LT 12 NF 5979 - 11-09.pdf"
    assert "A" not in por_id or por_id["A"] != por_id["B"]


def test_com_pdf_de_outra_conta_fora_sobra_desconhecido_nao_fecha_sozinho():
    """Achado da revisão do PR #94: tirar da disputa o PDF de outra conta não
    pode transformar em CERTEZA, por "valor único", um PDF de origem
    DESCONHECIDA que sobrou -- o certo pode ser o excluído (baixa lançada na
    conta errada do ERP). Fica em dúvida, dizendo que houve exclusão."""
    pdfs = [_pdf("60,00 - REEMBOLSO - 11-09.pdf", origem=SICOOB_2),
            _pdf("60,00 - REEMBOLSO - 11-09 (2).pdf", origem=None)]
    pend = [_pend_conta("A", 6000, origem=SICOOB_1, data="1109")]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and len(duvidas) == 1
    assert duvidas[0]["fora_da_conta"] == 1

