"""Apólice de seguro: o valor do lançamento é o PRÊMIO TOTAL (dono, 25/11/2026).

A apólice (RCPM) tem dezenas de valores. Com a régua de "o valor aparece em
algum lugar", o reembolso lançado pelo prêmio LÍQUIDO saía "valor ✓", e o
lançado com outro valor saía só "valor ?". Medido em 29 apólices reais de
09 a 11/2026: 25 batem com o prêmio total; das 4 que não batem, uma foi
lançada pelo líquido. Textos fictícios no leiaute medido.
"""
from pagamentos_dia import relatorio

from test_leitura_do_dia import _lanc


def _apolice(liquido="1.219,51", total="1.309,51", parcelas=(("1", "1.309,51", "04/01/2027"),)):
    linhas = "\n".join(f"{n} R$ {v} {d}" for n, v, d in parcelas)
    return (
        "SEGURADORA MODELO S/A\nAPÓLICE DE SEGURO SUSEP - 0000000000\n"
        "RAMO PRODUTO Nº DA PROPOSTA\n78 - RESPONSABILIDADE CIVIL PROFISSIONAL\n"
        "CONDIÇÕES\nÂMBITO DE COBERTURA BASE DE CONTRATAÇÃO\n"
        "DEMONSTRATIVO DE PRÊMIO\n"
        "PRÊMIO LÍQUIDO CUSTO DA APÓLICE TAXA DE JUROS (0,00%) IOF (%) PRÊMIO TOTAL MOEDA\n"
        f"R$ {liquido} R$ 0,00 R$ 0,00 7,380 R$ {total} Real\n"
        "PARCELAMENTO DO PRÊMIO\nFORMA DE PAGAMENTO\nFICHA DE COMPENSAÇÃO\n"
        f"PARC. VALOR VENC.\n{linhas}\n"
        "COBERTURAS\nLIMITE MÁXIMO DE INDENIZAÇÃO R$370.000,00 FRANQUIA R$1.000,00\n")


def _item(valor, parcelas=1, **extra):
    return _lanc("L1", remainingValue=valor, paidTo="Seguradora Modelo S/A", documentNumber="",
                 numberOfFinancingInstallments=parcelas, **extra)


def test_le_o_premio_total_e_as_parcelas():
    assert relatorio.premio_da_apolice(_apolice()) == (1309.51, [1309.51])


def test_texto_que_nao_e_apolice_nao_le_nada():
    assert relatorio.premio_da_apolice("NOTA FISCAL\nPRÊMIO TOTAL\nR$ 10,00") is None


def test_parcelas_que_nao_somam_o_total_nao_afirmam_nada():
    texto = _apolice(parcelas=(("1", "500,00", "04/01/2027"),))
    assert relatorio.premio_da_apolice(texto) is None


def test_premio_total_na_mesma_linha():
    assert relatorio.premio_da_apolice("Apólice nº 1\nPrêmio Total: R$ 2.000,00\n") == (2000.0, [])


def test_lancamento_igual_ao_premio_total_e_valor_ok():
    resumo, divergiu = relatorio.conferir_documento(_item(1309.51), [], [_apolice()])
    assert "valor ✓ (prêmio total da apólice)" in resumo and divergiu is False


def test_lancamento_com_outro_valor_diverge():
    resumo, divergiu = relatorio.conferir_documento(_item(2151.26), [], [_apolice()])
    assert divergiu is True
    assert "VALOR DIVERGE: prêmio total da apólice R$ 1.309,51" in resumo
    assert "2.151,26" in resumo


def test_lancado_pelo_premio_liquido_diverge_mesmo_com_o_numero_na_apolice():
    # O caso de 03/09/2026: 1.125,31 é o líquido e aparece no texto.
    texto = _apolice(liquido="1.125,31", total="1.208,36",
                     parcelas=(("1", "1.208,36", "04/01/2027"),))
    resumo, divergiu = relatorio.conferir_documento(_item(1125.31), [], [texto])
    assert divergiu is True and "VALOR DIVERGE" in resumo and "valor ✓" not in resumo


def test_diferenca_de_centavos_diverge():
    resumo, divergiu = relatorio.conferir_documento(_item(604.18), [], [_apolice(
        liquido="562,67", total="604,20", parcelas=(("1", "604,20", "04/01/2027"),))])
    assert divergiu is True and "604,20" in resumo


def test_titulo_parcelado_aceita_uma_parcela_do_premio():
    texto = _apolice(total="1.200,00", parcelas=(("1", "600,00", "04/01/2027"),
                                                  ("2", "600,00", "04/02/2027")))
    resumo, divergiu = relatorio.conferir_documento(_item(600.0, parcelas=2), [], [texto])
    assert "parcela do prêmio" in resumo and divergiu is False


def test_lancamento_avulso_de_uma_parcela_do_premio_parcelado_nao_diverge():
    # Cada boleto da seguradora lançado à parte: 600 é uma parcela do prêmio.
    texto = _apolice(total="1.200,00", parcelas=(("1", "600,00", "04/01/2027"),
                                                  ("2", "600,00", "04/02/2027")))
    resumo, divergiu = relatorio.conferir_documento(_item(600.0), [], [texto])
    assert "parcela do prêmio" in resumo and divergiu is False


def test_titulo_parcelado_sem_tabela_de_parcelas_nao_acusa():
    # Seguro de obra em 4 vezes: a apólice só diz "Prêmio Total" e o
    # lançamento é a parcela. Vale a regra de sempre (o boleto prova).
    texto = "APÓLICE Nº 1\nPrêmio Líquido: R$ 6.959,72\nPrêmio Total: R$ 7.473,35\n"
    resumo, divergiu = relatorio.conferir_documento(_item(1868.34, parcelas=4), [], [texto])
    assert "DIVERGE" not in resumo and divergiu is False


def test_sem_o_numero_de_parcelas_e_sem_tabela_nao_acusa():
    texto = "APÓLICE Nº 1\nPrêmio Total: R$ 7.473,35\n"
    item = _lanc("L1", remainingValue=1868.34, paidTo="Seguradora Modelo S/A", documentNumber="")
    item.pop("numberOfFinancingInstallments", None)
    resumo, divergiu = relatorio.conferir_documento(item, [], [texto])
    assert "DIVERGE" not in resumo and divergiu is False


def test_observacao_nao_prova_o_premio():
    # Só os anexos provam o valor: a apólice copiada na observação não conta.
    resumo, divergiu = relatorio.conferir_documento(
        _item(2151.26), [], [_apolice(), "obs"], textos_valor=["obs"])
    assert "prêmio" not in resumo and divergiu is False


def test_sem_apolice_a_regra_de_sempre_continua():
    resumo, _ = relatorio.conferir_documento(_item(50.0), [], ["RECIBO R$ 50,00 FORNECEDOR"])
    assert "valor ✓" in resumo and "prêmio" not in resumo
