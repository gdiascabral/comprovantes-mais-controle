# -*- coding: utf-8 -*-
"""Casamento sem passar nada errado (dono, 01/10/2026).

"Aprimore o casamento de informações para não passar nada de errado": cada
teste guarda um caminho em que a linha saía APTA com dado de pagamento que
podia não ser do lançamento. Tudo passa por `montar_registros`, que é onde o
dono vê o resultado. Dados e CNPJs inventados — o repo é público; os CNPJs são
gerados aqui com DV que fecha, porque a régua os confere.
"""
from pagamentos_dia import ocr_boleto
from pagamentos_dia import relatorio
from pagamentos_dia import regras_pagamento as regras


# --------------------------------------------------------------------------
# Material de teste
# --------------------------------------------------------------------------
def gera_linha(fator=9999, valor=100000, livre="1570700024434375241770100"):
    """Linha digitável bancária com os três DVs e o DV geral FECHANDO."""
    b43 = "3419" + f"{fator:04d}" + f"{valor:010d}" + livre
    b = b43[:4] + str(ocr_boleto._mod11_geral(b43)) + b43[4:]
    campos = [b[0:4] + b[19:24], b[24:34], b[34:44]]
    c = [x + str(ocr_boleto._mod10(x)) for x in campos]
    nova = (f"{c[0][:5]}.{c[0][5:]} {c[1][:5]}.{c[1][5:]} "
            f"{c[2][:5]}.{c[2][5:]} {b[4]} {b[5:19]}")
    assert ocr_boleto.valida(nova)
    return nova


def gera_cnpj(base8, filial="0001"):
    """CNPJ fictício com os dois DVs corretos."""
    d = base8 + filial

    def dv(txt, pesos):
        r = sum(int(x) * p for x, p in zip(txt, pesos)) % 11
        return "0" if r < 2 else str(11 - r)
    d += dv(d, (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    d += dv(d, (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2))
    assert len(regras.documento_valido(d)) == 14
    return d


def fmt(c):
    return f"{c[0:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:14]}"


def anexo(nome, tag=None, ext=".pdf", url=None):
    return {"filename": nome, "tagName": tag, "extension": ext,
            "downloadUrl": url or f"https://exemplo.invalid/{nome}"}


def item(**extra):
    base = {"id": "x1", "tradePayableId": "x1", "paidTo": "Atacado Modelo",
            "remainingValue": 1000.0, "tradePayablePaymentMethod": "Boleto",
            "documentNumber": "64000",
            "tradePayableAccount": {"name": "CONTA TESTE"},
            "costCentreDetails": [{"workName": "OBRA X"}]}
    base.update(extra)
    return base


def linhas(res):
    return next(iter(res.contas.values()))


# --------------------------------------------------------------------------
# C1: parcelas do mesmo título dividem os anexos
# --------------------------------------------------------------------------
def duas_parcelas(l1, l2):
    """Duas parcelas (mesmo título) vencendo no dia de cada linha."""
    anexos = {"t": [anexo("boleto parcela 1.pdf", "Boleto", url="u1"),
                    anexo("boleto parcela 2.pdf", "Boleto", url="u2")]}
    textos = {"u1": f"Banco Exemplo {l1}\n", "u2": f"Banco Exemplo {l2}\n"}
    p1 = item(id="p1", tradePayableId="t",
              plannedDate=ocr_boleto.vencimento_da_linha(l1).isoformat())
    p2 = item(id="p2", tradePayableId="t",
              plannedDate=ocr_boleto.vencimento_da_linha(l2).isoformat())
    return [p1, p2], anexos, textos


def test_c1_parcelas_com_dois_boletos_cada_uma_leva_o_seu():
    l1, l2 = gera_linha(fator=9000), gera_linha(fator=9030)
    itens, anexos, textos = duas_parcelas(l1, l2)
    res = relatorio.montar_registros(itens, anexos, {}, textos)
    por_id = {r["id"]: r for r in linhas(res)}
    assert ocr_boleto.digitos(por_id["p1"]["dados"]) == ocr_boleto.digitos(l1)
    assert ocr_boleto.digitos(por_id["p2"]["dados"]) == ocr_boleto.digitos(l2)
    assert por_id["p1"]["status"] == "APTO" and por_id["p2"]["status"] == "APTO"


def test_c1_dois_boletos_iguais_em_valor_e_vencimento_nao_decidem():
    # Mesmo valor e mesmo vencimento: só o campo livre muda.
    l1 = gera_linha(fator=9000)
    l2 = gera_linha(fator=9000, livre="1570700024434375241770199")
    anexos = {"t": [anexo("boleto a.pdf", "Boleto", url="u1"),
                    anexo("boleto b.pdf", "Boleto", url="u2")]}
    textos = {"u1": l1, "u2": l2}
    it = item(id="p1", tradePayableId="t",
              plannedDate=ocr_boleto.vencimento_da_linha(l1).isoformat())
    res = relatorio.montar_registros([it], anexos, {}, textos)
    assert res.omitidos == []
    linha = linhas(res)[0]
    assert linha["dados"] == ""
    assert linha["status"].startswith("ATENÇÃO")
    assert "2 boletos no título" in linha["obs"]
    assert "qual é desta parcela" in linha["obs"]


def test_c1_um_boleto_so_continua_como_antes():
    l1 = gera_linha(fator=9000)
    anexos = {"t": [anexo("boleto.pdf", "Boleto", url="u1")]}
    res = relatorio.montar_registros([item(tradePayableId="t")], anexos, {},
                                     {"u1": l1})
    linha = linhas(res)[0]
    assert ocr_boleto.digitos(linha["dados"]) == ocr_boleto.digitos(l1)
    assert linha["status"] == "APTO"


# --------------------------------------------------------------------------
# C3: observação que manda pagar outra pessoa
# --------------------------------------------------------------------------
def test_c3_pagar_para_outra_pessoa_vira_atencao_pagar_a_mao():
    it = item(tradePayablePaymentMethod="Pix",
              paidToBankAccount="PIX CNPJ: " + fmt(gera_cnpj("11222333")))
    ov = {"x1": {"comment": "PAGAR 800,00 PARA FULANO PIX 11999998888"}}
    anexos = {"x1": [anexo("NF 64000.pdf", "Nota Fiscal", url="un")]}
    res = relatorio.montar_registros([it], anexos, ov, {"un": "DANFE 64000"})
    linha = linhas(res)[0]
    assert "PAGAR À MÃO" in linha["obs"]
    assert linha["status"] == "ATENÇÃO — pagar à mão"


# --------------------------------------------------------------------------
# I1: pagamento parcial
# --------------------------------------------------------------------------
def test_i1_pagamento_parcial_vira_atencao_e_mantem_o_dado():
    linha_cheia = gera_linha(fator=9000, valor=100000)
    it = item(remainingValue=400.0, sumOfPaidValues=600.0, tradePayableId="t")
    anexos = {"t": [anexo("boleto.pdf", "Boleto", url="u1")]}
    res = relatorio.montar_registros([it], anexos, {}, {"u1": linha_cheia})
    linha = linhas(res)[0]
    assert linha["parcial"] is True
    assert linha["status"] == "ATENÇÃO — pagamento parcial"
    assert ocr_boleto.digitos(linha["dados"]) == ocr_boleto.digitos(linha_cheia)


# --------------------------------------------------------------------------
# I2: linha "por texto" confere DV e recusa comprovante
# --------------------------------------------------------------------------
def test_i2_47_digitos_que_nao_fecham_nao_viram_linha():
    anexos = {"x1": [anexo("boleto.pdf", "Boleto", url="u1")]}
    texto = "protocolo " + "1" * 47
    assert not ocr_boleto.valida("1" * 47)
    res = relatorio.montar_registros([item()], anexos, {}, {"u1": texto})
    linha = linhas(res)[0]
    assert linha["dados"] == ""
    assert linha["status"].startswith("ATENÇÃO")
    assert "dígito verificador" in linha["obs"]


def test_i2_boleto_pago_com_texto_de_comprovante_nao_entrega_a_linha():
    anexos = {"x1": [anexo("boleto pago.pdf", "Boleto", url="u1")]}
    texto = (f"Comprovante de pagamento\nData do pagamento 04/09/2026\n"
             f"{gera_linha()}\nValor pago 1.000,00\n")
    res = relatorio.montar_registros([item()], anexos, {}, {"u1": texto})
    linha = linhas(res)[0]
    assert linha["dados"] == ""
    assert "comprovante de pagamento" in linha["obs"]
    assert linha["status"].startswith("ATENÇÃO")


# --------------------------------------------------------------------------
# I3: CNPJ do texto da nota x cadastro
# --------------------------------------------------------------------------
def nota_pix(emitente, tomador, cadastro, **extra):
    texto = (f"DANFE Nota Fiscal Eletronica 64000\nEmitente CNPJ {fmt(emitente)}\n"
             f"Destinatario/Tomador CNPJ {fmt(tomador)}\nValor 1.000,00\n"
             if emitente else "DANFE Nota Fiscal Eletronica 64000\nValor 1.000,00\n")
    it = item(tradePayablePaymentMethod="Pix",
              paidToBankAccount="PIX CNPJ: " + fmt(cadastro), **extra)
    anexos = {"x1": [anexo("NF 64000.pdf", "Nota Fiscal", url="un")]}
    return linhas(relatorio.montar_registros([it], anexos, {}, {"un": texto}))[0]


def test_i3_cnpj_da_nota_diferente_do_cadastro_vira_atencao():
    emit, tom, cad = (gera_cnpj("11222333"), gera_cnpj("55666777"),
                      gera_cnpj("99888777"))
    linha = nota_pix(emit, tom, cad)
    assert linha["status"] == "ATENÇÃO — CNPJ da nota diferente do cadastro"
    assert fmt(emit) in linha["obs"] and fmt(cad) in linha["obs"]


def test_i3_cnpj_igual_ao_cadastro_continua_apto():
    emit, tom = gera_cnpj("11222333"), gera_cnpj("55666777")
    linha = nota_pix(emit, tom, emit)
    assert linha["status"] == "APTO"
    assert "CNPJ ✓" in linha["conferencia"]


def test_i3_filial_com_a_mesma_raiz_e_ok_com_nota():
    matriz, filial = gera_cnpj("11222333"), gera_cnpj("11222333", "0002")
    linha = nota_pix(filial, gera_cnpj("55666777"), matriz)
    assert linha["status"] == "APTO"
    assert "filial" in linha["conferencia"]


def test_i3_cnpj_do_pagador_nao_conta_como_emitente():
    # Só o CNPJ do tomador (a empresa que paga) está no texto: nada a dizer.
    tom, cad = gera_cnpj("55666777"), gera_cnpj("99888777")
    linha = nota_pix(None, tom, cad)  # sem emitente no texto
    assert linha["status"] == "APTO"
    texto = f"Tomador CNPJ {fmt(tom)}"
    assert relatorio.cnpjs_do_emitente(texto) == []


def test_i3_sem_cnpj_no_texto_ou_sem_documento_nada_muda():
    cad = gera_cnpj("99888777")
    assert nota_pix(None, None, cad)["status"] == "APTO"
    # sem documento no cadastro (Pix é e-mail): não há com o que comparar
    texto = f"DANFE Nota Fiscal\nEmitente CNPJ {fmt(gera_cnpj('11222333'))}\n"
    it = item(tradePayablePaymentMethod="Pix", paidToBankAccount="PIX: a@b.com")
    anexos = {"x1": [anexo("NF 64000.pdf", "Nota Fiscal", url="un")]}
    linha = linhas(relatorio.montar_registros([it], anexos, {}, {"un": texto}))[0]
    assert linha["status"] == "APTO"


def test_i3_documento_vem_dos_contatos_tambem():
    emit, cad = gera_cnpj("11222333"), gera_cnpj("99888777")
    texto = f"DANFE Nota Fiscal\nEmitente CNPJ {fmt(emit)}\n"
    it = item(tradePayablePaymentMethod="Pix", paidToBankAccount="PIX: a@b.com")
    anexos = {"x1": [anexo("NF 64000.pdf", "Nota Fiscal", url="un")]}
    res = relatorio.montar_registros(
        [it], anexos, {}, {"un": texto},
        participantes={"ATACADO MODELO": cad})
    assert linhas(res)[0]["status"] == "ATENÇÃO — CNPJ da nota diferente do cadastro"


# --------------------------------------------------------------------------
# I4: "valor ✓" com fronteira de dígito, sem a observação
# --------------------------------------------------------------------------
def test_i4_500_nao_casa_com_1500():
    assert not relatorio._valor_nos_textos(500.0, ["Total 1.500,00"])
    assert not relatorio._valor_nos_textos(500.0, ["Total 1500,00"])
    assert not relatorio._valor_nos_textos(500.0, ["Total 500,005"])
    assert relatorio._valor_nos_textos(500.0, ["Total R$ 500,00."])
    assert relatorio._valor_nos_textos(1500.0, ["Total 1.500,00"])


def test_i4_pelo_montar_registros_e_sem_usar_a_observacao():
    it = item(remainingValue=500.0, tradePayablePaymentMethod="Pix",
              paidToBankAccount="PIX: a@b.com")
    anexos = {"x1": [anexo("NF 64000.pdf", "Nota Fiscal", url="un")]}
    nf = "DANFE Nota Fiscal Eletronica 64000 Atacado Modelo Total 1.500,00"
    linha = linhas(relatorio.montar_registros([it], anexos, {}, {"un": nf}))[0]
    assert "valor ?" in linha["conferencia"]
    # A observação do lançamento dizendo o valor também não é prova.
    ov = {"x1": {"comment": "pagar 500,00 na entrega"}}
    linha = linhas(relatorio.montar_registros([it], anexos, ov, {"un": nf}))[0]
    assert "valor ?" in linha["conferencia"]
    ok = nf.replace("1.500,00", "500,00")
    linha = linhas(relatorio.montar_registros([it], anexos, {}, {"un": ok}))[0]
    assert "valor ✓" in linha["conferencia"]


# --------------------------------------------------------------------------
# M1: mesma_chave é igualdade
# --------------------------------------------------------------------------
def test_m1_mesma_chave_exige_igualdade():
    assert relatorio.mesma_chave("111.222.333-44", "Fulano 11122233344")
    assert relatorio.mesma_chave("a@b.com", "A@B.COM")
    assert relatorio.mesma_chave("11999998888", "+55 11 99999-8888")
    assert not relatorio.mesma_chave("x1@a.com", "x12@a.com")
    assert not relatorio.mesma_chave("a1@x.com", "b1@x.com")
    assert not relatorio.mesma_chave("11122233344", "11122233344556")
    assert not relatorio.mesma_chave("a1@x.com", "11122233344")


# --------------------------------------------------------------------------
# Rodada de conserto 1/5: falsos alarmes em massa
# --------------------------------------------------------------------------
def test_i2_fatura_com_valor_pago_no_historico_nao_e_recusada():
    """"Valor pago" e "data do pagamento" aparecem no histórico de fatura e
    em boleto comum; "Autenticação mecânica" está em todo boleto."""
    anexos = {"x1": [anexo("boleto.pdf", "Boleto", url="u1")]}
    linha_ok = gera_linha()
    texto = ("Historico: valor pago 950,00 data do pagamento 10/08/2026\n"
             f"{linha_ok}\nAutenticacao Mecanica - Ficha de Compensacao\n")
    linha = linhas(relatorio.montar_registros([item()], anexos, {}, {"u1": texto}))[0]
    assert ocr_boleto.digitos(linha["dados"]) == ocr_boleto.digitos(linha_ok)
    assert linha["status"] == "APTO"


def test_i2_comprovante_de_pagamento_com_linha_e_recusado():
    anexos = {"x1": [anexo("boleto.pdf", "Boleto", url="u1")]}
    texto = f"Comprovante de pagamento\n{gera_linha()}\n"
    linha = linhas(relatorio.montar_registros([item()], anexos, {}, {"u1": texto}))[0]
    assert linha["dados"] == ""


def danfe(emit, tomador):
    return (f"DANFE Documento Auxiliar da Nota Fiscal Eletronica 64000\n"
            f"Emitente: Atacado Modelo CNPJ {fmt(emit)}\n"
            "Chave de acesso 0000\nNATUREZA DA OPERACAO VENDA\n" + "x " * 80 +
            "\nDESTINATARIO / REMETENTE\nNome Cliente Exemplo\n" + "y " * 80 +
            f"\nCNPJ / CPF {fmt(tomador)}\nValor 1.000,00\n")


def test_i3_danfe_com_emitente_e_tomador_longe_do_rotulo():
    emit, tom = gera_cnpj("11222333"), gera_cnpj("55666777")
    assert relatorio.cnpjs_do_emitente(danfe(emit, tom)) == [emit]
    anexos = {"x1": [anexo("NF 64000.pdf", "Nota Fiscal", url="un")]}

    def roda(cadastro):
        it = item(tradePayablePaymentMethod="Pix",
                  paidToBankAccount="PIX CNPJ: " + fmt(cadastro))
        return linhas(relatorio.montar_registros(
            [it], anexos, {}, {"un": danfe(emit, tom)}))[0]
    assert roda(emit)["status"] == "APTO"
    assert roda(gera_cnpj("99888777"))["status"] == \
        "ATENÇÃO — CNPJ da nota diferente do cadastro"


def test_i3_cnpj_do_banco_no_boleto_nao_conta():
    banco, benef = gera_cnpj("12345678"), gera_cnpj("11222333")
    texto = (f"Banco Exemplo S.A. CNPJ {fmt(banco)}\n"
             f"Beneficiario Atacado CNPJ {fmt(benef)}\nFicha de Compensacao\n")
    assert relatorio.cnpjs_do_emitente(texto) == [benef]


def test_i4_valor_com_pontos_de_preenchimento():
    assert relatorio._valor_nos_textos(500.0, ["Valor......500,00"])
    assert not relatorio._valor_nos_textos(500.0, ["Valor 1.500,00"])


def test_cliente_de_atendimento_nao_abre_o_bloco_do_comprador():
    emit = gera_cnpj("11222333")
    for cab in ("SAC cliente 0800", "Central do cliente 0800", "Atendimento ao cliente"):
        texto = f"{cab}\nEmitente Atacado CNPJ {fmt(emit)}\n"
        assert relatorio.cnpjs_do_emitente(texto) == [emit], cab


def test_bloco_do_cliente_termina_em_300_caracteres():
    emit, tom = gera_cnpj("11222333"), gera_cnpj("55666777")
    perto = f"Dados do cliente CNPJ {fmt(tom)}\n"
    assert relatorio.cnpjs_do_emitente(perto) == []
    longe = "Dados do cliente\n" + "x " * 200 + f"\nCNPJ {fmt(emit)}\n"
    assert relatorio.cnpjs_do_emitente(longe) == [emit]


def test_banco_longe_do_cnpj_ou_antes_do_beneficiario_nao_descarta():
    benef = gera_cnpj("11222333")
    longe = (f"Banco Exemplo S.A. 001 - atendimento e informacoes gerais pelo telefone"
             f" CNPJ {fmt(benef)}\nFicha de Compensacao\n")
    assert relatorio.cnpjs_do_emitente(longe) == [benef]
    junto = f"Banco Exemplo Beneficiario CNPJ {fmt(benef)}\nFicha de Compensacao\n"
    assert relatorio.cnpjs_do_emitente(junto) == [benef]


def test_comprovante_forte_aceita_transferencia_e_pix_enviado():
    for t in ("Comprovante de transferencia", "PIX enviado com sucesso"):
        assert relatorio._COMPROVANTE_FORTE.search(t), t
