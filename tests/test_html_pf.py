# -*- coding: utf-8 -*-
"""HTML das contas PF e Moura Dantas (aba Pagamentos do dia › PF). Nomes fictícios."""
from datetime import date

from pagamentos_dia import html_pf, qr_pix
from pagamentos_dia.relatorio import Resultado

CPF_OK = "52998224725"          # CPF de exemplo, DV válido


def reg(**k):
    base = {"id": "L1", "tipo": "Pix", "dados": "", "valor": 150.0, "favorecido": "LOJA MODELO",
            "status": "APTO", "centro_custo": "OBRA X QD 1 LT 2", "oc": "", "nf": "",
            "nf_anexada": False, "oc_da_descricao": "", "descricao_lancamento": "MATERIAL",
            "utilidade": False, "vencimento": "2026-11-10", "reembolso": False,
            "reembolso_nome": "", "reembolso_para": "", "pix_qr": ""}
    base.update(k)
    return base


def test_contas_da_aba_sao_pf_e_moura_dantas():
    nomes = ["PESSOA FISICA - APENAS LANÇAMENTO", "MOURA DANTAS SICOOB 1",
             "EMPRESA X - INTER", "Moura  Dantas Bradesco", "pessoa física - outra"]
    assert html_pf.contas_da_aba(nomes) == ["Moura  Dantas Bradesco", "MOURA DANTAS SICOOB 1",
                                            "PESSOA FISICA - APENAS LANÇAMENTO",
                                            "pessoa física - outra"]


def test_pedaco_casa_por_palavra_inteira():
    r = html_pf.RegrasPF(favorecidos_fora=["ANA"])
    res = Resultado(contas={"PF": [reg(id="1", favorecido="MARIANA LTDA"),
                                   reg(id="2", favorecido="Ana Souza")]}, omitidos=[])
    sep = html_pf.separar(res, r)
    assert [x[1]["id"] for x in sep.entram] == ["1"]


def test_regras_do_dono_tiram_direto_com_motivo():
    res = Resultado(contas={"PF": [
        reg(id="a", centro_custo="POS OBRA FULANO"),
        reg(id="b", favorecido="Beltrana da Silva"),
        reg(id="c", tipo="Cartão de crédito"),
        reg(id="d")]}, omitidos=[{"conta": "PF", "favorecido": "SEM ANEXO LTDA",
                                  "valor": 10.0, "motivo": "sem anexo"}])
    r = html_pf.RegrasPF(cc_fora=["pós-obra fulano"], favorecidos_fora=["BELTRANA"])
    sep = html_pf.separar(res, r)
    assert [x[1]["id"] for x in sep.entram] == ["d"]
    motivos = sorted(m for _c, _r, m in sep.fora)
    assert any("POS" in m.upper() or "PÓS" in m.upper() for m in motivos)
    assert any("BELTRANA" in m for m in motivos)
    assert any("cartão" in m for m in motivos)
    assert "sem anexo" in motivos


def test_reembolso_do_socio_sai_so_com_a_caixa_desligada():
    res = Resultado(contas={"PF": [reg(id="r", reembolso=True, reembolso_para="FULANO",
                                       reembolso_nome="FULANO DE TAL")]}, omitidos=[])
    ligada = html_pf.separar(res, html_pf.RegrasPF(), ["FULANO DE TAL"], reembolso_ligado=True)
    desligada = html_pf.separar(res, html_pf.RegrasPF(), ["FULANO DE TAL"], reembolso_ligado=False)
    assert len(ligada.entram) == 1 and not ligada.reembolsos
    assert not desligada.entram and len(desligada.reembolsos) == 1


def test_qr_montado_pela_chave_leva_a_descricao_e_fecha_o_crc():
    it = html_pf.item_do_registro("PF", reg(dados=f"PIX CPF: {CPF_OK}"))
    assert it.grupo == "PIX" and not it.alertas
    _rot, br, cl, _t = it.codigos[0]
    assert cl == "qr" and qr_pix.valido(br)
    assert qr_pix.valor(br) == 150.0
    assert "0202" not in br[:4]
    desc = html_pf.descricao_do_pix(reg(), CPF_OK)
    assert desc and desc in br and "OBRA X" in desc
    assert len(br.split("26", 2)[1]) > 0
    mai = br[br.index("26") + 4: br.index("26") + 4 + int(br[br.index("26") + 2: br.index("26") + 4])]
    assert len(mai) <= 99


def test_copia_e_cola_pronto_nao_e_refeito():
    pronto = html_pf.pix_estatico(CPF_OK, 150.0, "LOJA", "")
    it = html_pf.item_do_registro("PF", reg(dados=pronto))
    assert it.codigos[0][1] == pronto


def test_chave_que_nao_fecha_vira_alerta_e_nao_qr():
    it = html_pf.item_do_registro("PF", reg(dados="PIX: 12345678900"))
    assert not it.codigos
    assert any("chave não reconhecida" in a for a in it.alertas)


def test_boleto_vira_codigo_de_barras():
    from pagamentos_dia import ocr_boleto
    barras = "34191" + "1" * 39
    # monta uma linha válida a partir de um código de barras com DV geral certo
    b = list("3419" + "0" + "1" * 39)
    dv = ocr_boleto._mod11_geral("".join(b[:4] + b[5:]))
    b[4] = str(dv)
    barras = "".join(b)
    f1, f2, f3 = barras[0:4] + barras[19:24], barras[24:34], barras[34:44]
    m = ocr_boleto._mod10
    linha = f"{f1}{m(f1)}{f2}{m(f2)}{f3}{m(f3)}{barras[4]}{barras[5:19]}"
    it = html_pf.item_do_registro("PF", reg(tipo="Boleto", dados=linha, valor=0.0))
    assert it.grupo == "BOLETO" and it.codigos and it.codigos[0][2] == "barras"
    assert it.codigos[0][1] == barras


def test_mesmo_qr_em_dois_lancamentos_alerta_nos_dois():
    pronto = html_pf.pix_estatico(CPF_OK, 150.0, "LOJA", "")
    lista = html_pf.itens([("PF", reg(id="1", dados=pronto)), ("PF", reg(id="2", dados=pronto))])
    assert all(any("MESMO CÓDIGO" in a for a in i.alertas) for i in lista)


def test_status_atencao_vira_alerta():
    it = html_pf.item_do_registro("PF", reg(dados=f"PIX CPF: {CPF_OK}",
                                            status="ATENÇÃO — documento não bate"))
    assert "ATENÇÃO — documento não bate" in it.alertas


def test_gravar_escreve_a_pagina_com_o_titulo_para_a_baixa(tmp_path):
    res = Resultado(contas={"PF": [reg(id="L1", dados=f"PIX CPF: {CPF_OK}")]}, omitidos=[])
    g = html_pf.gravar(res, [{"id": "L1", "tradePayableId": "T1"}], tmp_path,
                       date(2026, 11, 1), date(2026, 11, 12), regras_pf=html_pf.RegrasPF(),
                       contas_pagadoras=[{"id": "c1", "nome": "CONTA DE PESSOA", "saldo": 10.0}],
                       contas_lidas=["PF"], hoje=date(2026, 11, 12))
    texto = g.caminho.read_text(encoding="utf-8")
    assert g.entram == 1 and g.caminho.name == "pagamentos_pf_2026-11-01_a_2026-11-12.html"
    assert 'data-tpid="T1"' in texto and "CONTA DE PESSOA" in texto
    assert "__" not in texto.replace("__proto__", "")
    assert "venc. 10/11/2026" in texto and "vencido" in texto


def test_regras_ausentes_nao_quebram(tmp_path):
    r = html_pf.carregar_regras(tmp_path)
    assert r.cc_fora == [] and r.favorecidos_fora == []


def test_conta_apenas_lancamento_entra_quando_escolhida():
    """A régua das PJ ignora a "APENAS LANÇAMENTO"; na aba PF ela é escolhida."""
    from pagamentos_dia import relatorio
    item = {"id": "x1", "tradePayableId": "x1", "paidTo": "Fornecedor Exemplo",
            "remainingValue": 100.0, "tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": f"PIX CPF: {CPF_OK}",
            "tradePayableAccount": {"name": "PESSOA FISICA - APENAS LANÇAMENTO"},
            "costCentreDetails": [{"workName": "OBRA X"}]}
    anexos = {"x1": [{"filename": "documento", "tagName": "Nota Fiscal", "extension": ".pdf",
                      "downloadUrl": "u1"}]}
    sempre = relatorio.montar_registros([item], anexos, {}, {"u1": ""})
    assert sempre.contas == {}
    pf = relatorio.montar_registros([item], anexos, {}, {"u1": ""},
                                    contas_escolhidas=frozenset(
                                        {relatorio.chave("PESSOA FISICA - APENAS LANÇAMENTO")}))
    assert list(pf.contas) == ["PESSOA FISICA - APENAS LANÇAMENTO"]
    outra = relatorio.montar_registros([item], anexos, {}, {"u1": ""},
                                       contas_escolhidas=frozenset({relatorio.chave("OUTRA")}))
    assert outra.contas == {} and outra.omitidos
