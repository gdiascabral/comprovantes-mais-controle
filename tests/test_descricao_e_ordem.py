# -*- coding: utf-8 -*-
"""Ordem das linhas e descrição para colar no banco (pedido do dono, 14/09/2026).

Puro: só `relatorio` e `html_pagamentos`, sem janela, sem ERP e sem rede.
Nenhum nome, lote, OC, NF ou valor aqui é de verdade — o repositório é público.
"""
import re

from pagamentos_dia import html_pagamentos as hp
from pagamentos_dia import relatorio


def anexo(nome, tag=None, ext=".pdf", url=None):
    return {"filename": nome, "tagName": tag, "extension": ext,
            "downloadUrl": url or f"https://exemplo.invalid/{nome}"}


# ------------------------------------------------- REEMBOLSO não é número de NF
def test_reembolso_no_documento_do_detalhe_nao_vira_nf():
    """O `documentNumber` do item já era filtrado, mas o do detalhe (que traz o
    mesmo texto) não: saía "NF REEMBOLSO FULANO", e a conferência procurava
    uma nota que não existe."""
    item = {"documentNumber": "REEMBOLSO FULANO MODELO",
            "costCentreDetails": [{"workName": "QD 99 LT 99"}]}
    overview = {"documentNumber": "REEMBOLSO FULANO MODELO",
                "purchaseOrder": {"number": 1234}}
    assert relatorio.achar_doc(item, [], overview) == ""
    assert relatorio.monta_descricao(item, [], "", overview) == "QD 99 LT 99 OC 1234"


def test_reembolso_no_nome_do_anexo_nao_apaga_a_nf_de_verdade():
    """Do nome do anexo só se tiram DÍGITOS: "REEMBOLSO" nunca saía dali, e o
    número ao lado de "NF" num arquivo de reembolso é a nota da compra."""
    item = {"costCentreDetails": [{"workName": "QD 99 LT 99"}]}
    files = [anexo("Reembolso Fulano Modelo NF 5678")]
    assert relatorio.achar_doc(item, files) == "5678"


def _boleto_sem_anexo(**mudancas):
    """A forma no ERP é Boleto, não há boleto anexado e o cadastro tem Pix."""
    return dict({"id": "1", "tradePayableId": "t1", "paid": False,
                 "tradePayableAccount": {"name": CONTA},
                 "paidTo": "Fornecedor Modelo Ltda", "remainingValue": 10.0,
                 "tradePayablePaymentMethod": "Boleto",
                 "paidToBankAccount": "PIX EMAIL fornecedor@exemplo.com",
                 "documentNumber": "REEMBOLSO FULANO MODELO",
                 "costCentreDetails": [{"workName": "QD 99 LT 99"}]}, **mudancas)


def test_documento_de_reembolso_continua_valendo_como_compra_documentada():
    """Em 73c52ce o detalhe devolvia "REEMBOLSO FULANO" como NF, e isso fazia a
    linha ser paga pela chave do cadastro. Tirar a falsa NF da descrição não
    pode tirar a linha da planilha: o desfecho tem de ser o mesmo de antes
    (tipo, dados, obs e status conferidos contra a base, não inventados)."""
    detalhe = {"1": {"documentNumber": "REEMBOLSO FULANO MODELO"}}
    res = relatorio.montar_registros([_boleto_sem_anexo()], {}, detalhe, {})
    assert not res.omitidos
    linha = res.contas[CONTA][0]
    assert (linha["tipo"], linha["dados"], linha["obs"], linha["status"]) == (
        "Pix", "fornecedor@exemplo.com",
        "Sem boleto anexado — pagar pela chave Pix do cadastro",
        "ATENÇÃO — sem anexo")
    assert linha["descricao"] == "QD 99 LT 99" and linha["nf"] == ""


def test_reembolso_declarado_so_no_lancamento_tambem_vale():
    """Sem o detalhe carregado, o mesmo lançamento não pode ter outro desfecho."""
    res = relatorio.montar_registros([_boleto_sem_anexo()], {}, {}, {})
    assert not res.omitidos
    assert res.contas[CONTA][0]["tipo"] == "Pix"


def test_sem_nf_sem_oc_e_sem_reembolso_continua_fora():
    """A exceção é o reembolso declarado, e não "qualquer documento"."""
    res = relatorio.montar_registros([_boleto_sem_anexo(documentNumber="")],
                                     {}, {}, {})
    assert not res.contas and len(res.omitidos) == 1


def test_nf_de_verdade_no_nome_do_anexo_continua_valendo():
    item = {"costCentreDetails": [{"workName": "QD 99 LT 99"}]}
    files = [anexo("REEMBOLSO FULANO MODELO"), anexo("NF 5678 Fornecedor Modelo")]
    assert relatorio.achar_doc(item, files) == "5678"


# ------------------------------------------------------------------- a ordem
CONTA = "CONTA MODELO - INTER"


def _pix(ident, favorecido):
    return {"id": ident, "tradePayableId": f"t{ident}", "paid": False,
            "tradePayableAccount": {"name": CONTA}, "paidTo": favorecido,
            "remainingValue": 10.0, "tradePayablePaymentMethod": "Pix",
            "paidToBankAccount": "PIX EMAIL fornecedor@exemplo.com",
            "documentNumber": "5678",
            "costCentreDetails": [{"workName": "QD 99 LT 99"}]}


def _boleto(ident, favorecido):
    item = dict(_pix(ident, favorecido), tradePayablePaymentMethod="Boleto")
    item.pop("paidToBankAccount")
    return item


def _ids(lancamentos, anexos=None):
    res = relatorio.montar_registros(lancamentos, anexos or {}, {}, {})
    return [(r["tipo"], r["id"]) for r in res.contas[CONTA]]


def test_boleto_antes_de_pix_e_o_ultimo_do_sistema_primeiro():
    """Pedido do dono: continua boleto antes de Pix; dentro do tipo, a ordem em
    que aparecem no sistema, invertida — o último vem primeiro."""
    lancamentos = [_pix("1", "Fornecedor A"), _boleto("2", "Fornecedor B"),
                   _pix("3", "Fornecedor C"), _boleto("4", "Fornecedor D"),
                   _pix("5", "Fornecedor E")]
    anexos = {f"t{i}": [anexo(f"boleto {i}", "Boleto")] for i in ("2", "4")}
    assert _ids(lancamentos, anexos) == [
        ("Boleto", "4"), ("Boleto", "2"),
        ("Pix", "5"), ("Pix", "3"), ("Pix", "1")]


def test_o_favorecido_nao_decide_mais_a_ordem():
    """Até aqui a segunda chave era o favorecido em ordem alfabética, e a lista
    do HTML não conversava com a tela do sistema."""
    lancamentos = [_pix("1", "Zeta Modelo"), _pix("2", "Alfa Modelo"),
                   _pix("3", "Alfa Modelo")]
    assert _ids(lancamentos) == [("Pix", "3"), ("Pix", "2"), ("Pix", "1")]
    # a mesma entrada dá sempre a mesma saída
    assert _ids(lancamentos) == _ids(list(lancamentos))


# ------------------------------------- as partes da descrição viajam no registro
def _registro(overview=None, **mudancas):
    item = dict(_pix("1", "Fornecedor Modelo Ltda"), **mudancas)
    res = relatorio.montar_registros([item], {}, {"1": overview or {}}, {})
    return res.contas[CONTA][0]


def test_o_registro_leva_nf_e_oc_ja_ajustadas():
    """O HTML monta a descrição do banco a partir destas partes, e não
    reparseando a frase pronta — a mesma armadilha que o cabeçalho do módulo
    avisa."""
    r = _registro(documentNumber="5678", description="Material de obra",
                  overview={"purchaseOrder": {"number": 1234}})
    assert (r["nf"], r["oc_da_descricao"]) == ("5678", "1234")
    assert r["descricao_lancamento"] == "Material de obra"
    assert r["utilidade"] is False
    assert r["centro_custo"] == "QD 99 LT 99"


def test_oc_escrita_no_documento_vai_como_oc_e_nao_como_nf():
    """Sem o ajuste, "OC1234" no campo do documento viraria "NF OC1234" no
    banco. O `oc` de sempre continua como estava: é o que a remessa lê."""
    r = _registro(documentNumber="OC1234")
    assert (r["nf"], r["oc_da_descricao"]) == ("", "1234")
    assert r["oc"] == ""


def test_conta_de_agua_e_luz_e_marcada_no_registro(monkeypatch):
    # A lista de concessionárias é de nomes reais; aqui entra uma fictícia.
    monkeypatch.setattr(relatorio, "_UTILIDADES",
                        re.compile("concessionaria modelo", re.I))
    r = _registro(paidTo="Concessionaria Modelo", documentNumber="2026000000001",
                  description="UC 000000001 REF SET 2026")
    assert r["utilidade"] is True


# -------------------------------------------- a descrição para colar no banco
INTER = "CONTA MODELO - INTER"
SICOOB = "CONTA MODELO - SICOOB"


def _partes(nf="", oc="", descricao="", cc="QD 99 LT 99", utilidade=False):
    return {"centro_custo": cc, "nf": nf, "oc_da_descricao": oc,
            "descricao_lancamento": descricao, "utilidade": utilidade,
            "descricao": "a frase da planilha, que o HTML não usa"}


def test_nf_e_oc_vao_as_duas():
    r = _partes(nf="5678", oc="1234", descricao="Material de obra")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 NF 5678 OC 1234"


def test_so_oc_vai_so_a_oc():
    r = _partes(oc="1234", descricao="Material de obra")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 OC 1234"


def test_so_nf_vai_so_a_nf():
    r = _partes(nf="5678", descricao="Material de obra")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 NF 5678"


def test_sem_nf_nem_oc_vai_a_descricao_do_lancamento():
    r = _partes(descricao="Material de obra")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 Material de obra"


def test_sem_nada_sobra_o_centro_de_custo():
    assert hp.descricao_para_colar(_partes(), INTER) == "QD 99 LT 99"
    assert hp.descricao_para_colar(_partes(cc=""), INTER) == ""


def test_hifen_acento_e_pontuacao_saem():
    r = _partes(descricao="Instalação elétrica - CASA 2 / fase 1 (etapa nº3).",
                cc="QD 99 LT 01 | QD 99 LT 02")
    assert hp.descricao_para_colar(r, INTER) == (
        "QD 99 LT 01 QD 99 LT 02 Instalacao eletrica CASA 2 fase 1 etapa no3")


def test_o_reembolso_nao_vai_para_o_banco():
    casos = {
        "Cimento e areia (Reembolso Fulano Modelo)": "QD 99 LT 99 Cimento e areia",
        "REEMBOLSO FULANO MODELO - CIMENTO E AREIA": "QD 99 LT 99 CIMENTO E AREIA",
        "Reembolso: Fulano Modelo": "QD 99 LT 99",
        "Pintura / reembolsos Fulano Modelo": "QD 99 LT 99 Pintura",
    }
    for descricao, esperado in casos.items():
        obtido = hp.descricao_para_colar(_partes(descricao=descricao), INTER)
        assert obtido == esperado, descricao


def test_nf_de_reembolso_nao_vira_nf():
    """O `achar_doc` já não devolve isso; o HTML também não confia."""
    r = _partes(nf="REEMBOLSO FULANO MODELO", oc="1234")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 OC 1234"


def test_nao_repete_o_centro_de_custo_que_a_descricao_ja_traz():
    r = _partes(descricao="qd 99 lt 99 - Pintura externa")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 Pintura externa"
    # "QD 9" não é o começo de "QD 99": só palavra inteira conta
    r = _partes(cc="QD 9", descricao="QD 99 LT 1 pintura")
    assert hp.descricao_para_colar(r, INTER) == "QD 9 QD 99 LT 1 pintura"


def test_agua_e_luz_mantem_a_descricao_e_nao_usam_o_numero_da_fatura():
    r = _partes(nf="2026000000001", descricao="UC 000000001 - REF SET/2026",
                utilidade=True)
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 UC 000000001 REF SET 2026"
    r = _partes(nf="2026000000001", oc="1234", descricao="UC 000000001",
                utilidade=True)
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 UC 000000001 OC 1234"


_ITENS = " ".join(f"ITEM{n:02d}" for n in range(1, 40))


def test_sicoob_corta_em_100_e_as_outras_em_140_na_fronteira_de_palavra():
    r = _partes(descricao=_ITENS)
    sicoob = hp.descricao_para_colar(r, SICOOB)
    inter = hp.descricao_para_colar(r, INTER)
    assert sicoob == "QD 99 LT 99 " + " ".join(f"ITEM{n:02d}" for n in range(1, 13))
    assert inter == "QD 99 LT 99 " + " ".join(f"ITEM{n:02d}" for n in range(1, 19))
    assert len(sicoob) == 95 and len(inter) == 137
    assert hp.descricao_para_colar(r, "conta modelo sicoob") == sicoob


_RATEIO = " | ".join(f"QD {n:02d} LT {n:02d}" for n in range(1, 12))


def _blocos(ate):
    return " ".join(f"QD {n:02d} LT {n:02d}" for n in range(1, ate + 1))


def test_nf_e_oc_nunca_sao_cortadas_quem_cede_e_o_centro_de_custo():
    r = _partes(nf="5678", oc="1234", cc=_RATEIO)
    assert hp.descricao_para_colar(r, SICOOB) == _blocos(7) + " NF 5678 OC 1234"


def test_a_descricao_cede_antes_do_centro_de_custo():
    r = _partes(descricao="Material eletrico", cc=_RATEIO)
    assert hp.descricao_para_colar(r, INTER) == _blocos(11) + " Material"
    assert hp.descricao_para_colar(r, SICOOB) == _blocos(8) + " QD"


def test_o_html_geral_usa_a_descricao_para_colar():
    linha = dict(_partes(oc="1234", descricao="Material (Reembolso Fulano Modelo)"),
                 tipo="Pix", dados="fornecedor@exemplo.com", valor=10.0,
                 favorecido="Fornecedor Modelo - Ltda.", status="APTO",
                 conferencia="", obs="", id="1")
    contas = hp.contas_do_html_geral(relatorio.Resultado({SICOOB: [linha]}, []))
    entrada = contas[0]["entries"][0]
    assert entrada["descricao"] == "QD 99 LT 99 OC 1234"
    assert entrada["favorecido"] == "Fornecedor Modelo - Ltda."
