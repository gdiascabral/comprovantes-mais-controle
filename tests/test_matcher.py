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
            _pend_conta("B", 7000, origem=SICOOB_1, doc="8888", desc="outro")]
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
    assert matcher.mesmo_favorecido("Beltrana Modelo", "BELTRANA MODELO")
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
    # nome de duas palavras só vale IGUAL (segunda revisão do #94)
    assert not matcher.mesmo_favorecido("FULANO EXEMPLO", "FULANO BELTRANO EXEMPLO")
    assert not matcher.mesmo_favorecido("CONSTRUTORA EXEMPLO", "CONSTRUTORA EXEMPLO 2")


def test_nf_com_a_mesma_conta_nao_fecha_se_ha_rival_sem_nr_do_documento():
    """Segunda revisão do #94: com outro pendente de mesmo valor SEM nº do
    documento no ERP, a NF do PDF pode ser dele (número de outro fornecedor que
    coincide) -- não se sabe, então não fecha."""
    pdfs = [_pdf("900,00 - CIMENTO NF 1234 - 11-09.pdf", origem=SICOOB_1),
            _pdf("900,00 - SERVICO - 11-09.pdf", origem=SICOOB_1)]
    pend = [_pend_conta("A", 90000, origem=SICOOB_1, doc="1234", data="1109"),
            _pend_conta("B", 90000, origem=SICOOB_1, doc="", desc="compra", data="1109")]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and len(duvidas) == 2


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


# ------------------------------------------- identificadores exatos (14/09/2026)
# Na primeira rodada com a conta de origem (v2.0.202), 21 dúvidas; o dono
# apontou três que o app podia decidir sozinho, cada uma com um dado EXATO que
# o casamento não olhava: o nº da UC na descrição, a OC que só existe no
# overview do ERP e o CPF/CNPJ de quem recebeu. Tudo fictício abaixo.

def test_numero_longo_igual_na_descricao_desempata():
    """Seis contas de luz de mesmo valor, mesma conta e mesmo lote: só a UC
    (número longo) diz qual é qual."""
    pdfs = [_pdf("44,87 - OBRA QD 01 LT 21 UC 111111111111 REF AGO CASA 2 - 08-09.pdf", origem=SICOOB_1),
            _pdf("44,87 - OBRA QD 01 LT 21 UC 222222222222 REF AGO CASA 1 - 08-09.pdf", origem=SICOOB_1)]
    pend = [_pend_conta("A", 4487, origem=SICOOB_1, data="0809", works=["OBRA QD 01 LT 21"],
                        desc="UC 222222222222 REF AGO CASA 1"),
            _pend_conta("B", 4487, origem=SICOOB_1, data="0809", works=["OBRA QD 01 LT 21"],
                        desc="UC 111111111111 REF AGO CASA 2")]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not duvidas
    por_id = {c["paidId"]: c["pdf"] for c in certezas}
    assert por_id["A"].startswith("44,87 - OBRA QD 01 LT 21 UC 222222222222")
    assert por_id["B"].startswith("44,87 - OBRA QD 01 LT 21 UC 111111111111")
    assert "nº longo" in {c["paidId"]: c["motivo"] for c in certezas}["A"]


def test_numero_longo_sozinho_sem_conta_nem_centro_de_custo_nao_fecha():
    """Um número de 6+ dígitos pode coincidir (telefone, CEP colado); sem a
    conta ou o centro de custo junto, não fecha."""
    pdfs = [_pdf("44,87 - UC 111111111111 - 08-09.pdf"),
            _pdf("44,87 - OUTRA - 08-09.pdf")]
    pend = [_pend_conta("A", 4487, data="0809", desc="UC 111111111111"),
            _pend_conta("B", 4487, data="0809", desc="outra")]
    certezas, _, _ = matcher.casar(pend, pdfs)
    assert not certezas


def test_oc_que_so_existe_no_erp_casa_com_a_oc_do_pdf():
    """A OC estava no lançamento (overview), não na descrição."""
    pdfs = [_pdf("1950,00 - OBRA QD 99 LT 99 OC 2222 - 09-09.pdf", origem=SICOOB_1),
            _pdf("1950,00 - OBRA QD 99 LT 99 OC 1111 - 09-09.pdf", origem=SICOOB_1)]
    pend = [_pend_conta("A", 195000, origem=SICOOB_1, data="0909", desc="areia",
                        works=["OBRA QD 99 LT 99"]),
            _pend_conta("B", 195000, origem=SICOOB_1, data="0909", desc="areia",
                        works=["OBRA QD 99 LT 99"])]
    pend[0]["ocs_erp"] = {"1111"}
    pend[1]["ocs_erp"] = {"2222"}
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not duvidas
    por_id = {c["paidId"]: c["pdf"] for c in certezas}
    assert por_id == {"A": "1950,00 - OBRA QD 99 LT 99 OC 1111 - 09-09.pdf",
                      "B": "1950,00 - OBRA QD 99 LT 99 OC 2222 - 09-09.pdf"}


def test_oc_do_erp_nao_casa_com_nf_de_mesmo_numero():
    pdfs = [_pdf("1950,00 - MATERIAL NF 1111 - 09-09.pdf", origem=SICOOB_1),
            _pdf("1950,00 - OUTRO - 09-09.pdf", origem=SICOOB_1)]
    pend = [_pend_conta("A", 195000, origem=SICOOB_1, data="0909", desc="x"),
            _pend_conta("B", 195000, origem=SICOOB_1, data="0909", desc="y", doc="1")]
    pend[0]["ocs_erp"] = {"1111"}
    certezas, _, _ = matcher.casar(pend, pdfs)
    assert not certezas


def _pdf_doc(nome, doc, origem=SICOOB_1):
    p = _pdf(nome, origem=origem)
    p["doc_recebedor"] = doc
    return p


def test_documento_de_quem_recebeu_com_a_data_desempata():
    """O aporte: dois Pix de mesmo valor e dia saindo da mesma conta, um para
    a SPE do título e outro para a própria empresa -- o CNPJ diz qual."""
    pdfs = [_pdf_doc("10000,00 - EMPRESA A PARA Empresa - 08-09.pdf", "11111111000111"),
            _pdf_doc("10000,00 - EMPRESA A PARA Empresa A - 08-09.pdf", "22222222000122"),
            _pdf_doc("10000,00 - EMPRESA A PARA Empresa - 10-09.pdf", "11111111000111")]
    pend = [_pend_conta("A", 1000000, origem=SICOOB_1, data="0809", desc="APORTE",
                        favorecido="EMPRESA SPE ALFA")]
    pend[0]["doc_favorecido"] = "11111111000111"
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not duvidas and len(certezas) == 1
    assert certezas[0]["pdf"] == "10000,00 - EMPRESA A PARA Empresa - 08-09.pdf"
    assert "documento" in certezas[0]["motivo"]


def test_mesmo_documento_e_mesma_data_em_dois_pdfs_nao_escolhe():
    """Dois boletos do mesmo fornecedor, mesmo valor e dia: o documento não
    separa, e continua dúvida (é o caso da OC, que resolve de outro jeito)."""
    pdfs = [_pdf_doc("1950,00 - AREIA - 09-09.pdf", "33333333000133"),
            _pdf_doc("1950,00 - AREIA - 09-09 (2).pdf", "33333333000133")]
    pend = [_pend_conta("A", 195000, origem=SICOOB_1, data="0909", desc="areia"),
            _pend_conta("B", 195000, origem=SICOOB_1, data="0909", desc="areia")]
    for pe in pend:
        pe["doc_favorecido"] = "33333333000133"
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and len(duvidas) == 2


def test_disputados_sao_os_que_tem_dois_pdfs_ou_mais_de_mesmo_valor():
    """É para esses que vale ler o overview do ERP: um pedido por lançamento, e
    ler os 250 de uma rodada seria pagar por quem já casa sozinho."""
    pdfs = [_pdf("10,00 - A - 01-09.pdf"), _pdf("10,00 - B - 01-09.pdf"),
            _pdf("20,00 - C - 01-09.pdf")]
    pend = [_pend("X", 1000), _pend("Y", 2000), _pend("Z", 3000),
            _pend("W", 1500, valores=[1500, 2000])]
    assert [pe["paidId"] for pe in matcher.disputados(pend, pdfs)] == ["X"]


# ------------------------------------------------ revisão do PR #95
# Um identificador do IMÓVEL, do FORNECEDOR ou da OC não identifica o
# PAGAMENTO: a parcela anterior ou o mês anterior, com PDF ainda na pasta,
# carregam o mesmo número. Por isso as três regras exigem a MESMA data.

def test_oc_do_erp_nao_leva_o_pdf_da_parcela_anterior():
    pdfs = [_pdf("1950,00 - AREIA OC 1111 - 10-08.pdf", origem=SICOOB_1),
            _pdf("1950,00 - FORNECEDOR EXEMPLO - 10-09.pdf", origem=SICOOB_1)]
    pend = [_pend_conta("A", 195000, origem=SICOOB_1, data="1009", desc="areia")]
    pend[0]["ocs_erp"] = {"1111"}
    certezas, _, _ = matcher.casar(pend, pdfs)
    assert len(certezas) == 1
    assert certezas[0]["pdf"] == "1950,00 - FORNECEDOR EXEMPLO - 10-09.pdf"


def test_numero_longo_nao_leva_o_pdf_do_mes_anterior():
    pdfs = [_pdf("44,87 - LUZ UC 111111111111 REF JUL - 08-08.pdf", origem=SICOOB_1),
            _pdf("44,87 - DISTRIBUIDORA EXEMPLO - 08-09.pdf", origem=SICOOB_1)]
    pend = [_pend_conta("A", 4487, origem=SICOOB_1, data="0809",
                        desc="UC 111111111111 REF AGO")]
    certezas, _, _ = matcher.casar(pend, pdfs)
    assert len(certezas) == 1
    assert certezas[0]["pdf"] == "44,87 - DISTRIBUIDORA EXEMPLO - 08-09.pdf"


def test_numero_longo_nao_fura_a_trava_do_rival_sem_nr_do_documento():
    """O nº do documento não entra no número longo: a NF pode ser do rival
    que não tem nº do documento (2ª revisão do #94)."""
    pdfs = [_pdf("900,00 - MATERIAL NF 123456 - 11-09.pdf", origem=SICOOB_1),
            _pdf("900,00 - OUTRO - 11-09.pdf", origem=SICOOB_1)]
    pend = [_pend_conta("A", 90000, origem=SICOOB_1, doc="123456", data="1109"),
            _pend_conta("B", 90000, origem=SICOOB_1, doc="", desc="compra", data="1109")]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and len(duvidas) == 2


def test_documento_de_quem_recebeu_exige_a_conta_conhecida():
    """Sem saber a conta do lançamento, o CNPJ sozinho não fecha: o mesmo
    fornecedor recebe de várias empresas o mesmo valor no mesmo dia."""
    pdfs = [_pdf_doc("641,31 - HONORARIO - 10-09.pdf", "33333333000133", origem=SICOOB_2),
            _pdf_doc("641,31 - OUTRO - 10-09.pdf", "55555555000155", origem=SICOOB_1)]
    pend = [_pend_conta("A", 64131, origem=None, data="1009", desc="honorario")]
    pend[0]["doc_favorecido"] = "33333333000133"
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and len(duvidas) == 1


# 2ª revisão do #95: na MESMA data, com o rival já anexado (fora dos
# pendentes), só o PDF DELE traz o identificador -- e a pendente o levava.
# As três regras só fecham se todo PDF daquela data trouxer o identificador.

def test_numero_longo_nao_fecha_se_outro_pdf_da_data_nao_tem_numero():
    pdfs = [_pdf("44,87 - LUZ UC 111111111111 REF JUL - 08-09.pdf", origem=SICOOB_1),
            _pdf("44,87 - DISTRIBUIDORA EXEMPLO - 08-09.pdf", origem=SICOOB_1)]
    pend = [_pend_conta("A", 4487, origem=SICOOB_1, data="0809",
                        desc="UC 111111111111 REF AGO")]
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and len(duvidas) == 1


def test_oc_do_erp_nao_fecha_se_outro_pdf_da_data_nao_tem_oc():
    pdfs = [_pdf("1950,00 - AREIA OC 1111 - 10-09.pdf", origem=SICOOB_1),
            _pdf("1950,00 - FORNECEDOR EXEMPLO - 10-09.pdf", origem=SICOOB_1)]
    pend = [_pend_conta("A", 195000, origem=SICOOB_1, data="1009", desc="areia")]
    pend[0]["ocs_erp"] = {"1111"}
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and len(duvidas) == 1


def test_documento_nao_fecha_se_outro_pdf_da_data_nao_tem_documento():
    pdfs = [_pdf_doc("641,31 - HONORARIO - 10-09.pdf", "33333333000133"),
            _pdf_doc("641,31 - HONORARIO - 10-09 (2).pdf", None)]
    pend = [_pend_conta("A", 64131, origem=SICOOB_1, data="1009", desc="honorario")]
    pend[0]["doc_favorecido"] = "33333333000133"
    certezas, duvidas, _ = matcher.casar(pend, pdfs)
    assert not certezas and len(duvidas) == 1

