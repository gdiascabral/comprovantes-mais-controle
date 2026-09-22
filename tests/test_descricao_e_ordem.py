# -*- coding: utf-8 -*-
"""Ordem das linhas e descrição para colar no banco (pedido do dono, 14/09/2026).

Puro: só `relatorio` e `html_pagamentos`, sem janela, sem ERP e sem rede.
Nenhum nome, lote, OC, NF ou valor aqui é de verdade — o repositório é público.
"""
import re

from pagamentos_dia import html_pagamentos as hp
from pagamentos_dia import relatorio
from pagamentos_dia import remessa_dia


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
    pode tirar a linha da planilha: tipo, dados e a Obs da forma de pagar são
    os que a base produz para o mesmo lançamento. O status deixou de ser o da
    base de propósito — ver `test_reembolso_declarado_sem_aviso_vira_atencao…`."""
    detalhe = {"1": {"documentNumber": "REEMBOLSO FULANO MODELO"}}
    res = relatorio.montar_registros([_boleto_sem_anexo()], {}, detalhe, {})
    assert not res.omitidos
    linha = res.contas[CONTA][0]
    assert (linha["tipo"], linha["dados"]) == ("Pix", "fornecedor@exemplo.com")
    assert "Sem boleto anexado — pagar pela chave Pix do cadastro" in linha["obs"]
    assert linha["status"].startswith("ATENÇÃO")
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


# ------------------------ reembolso declarado sem aviso: quem recebe está em dúvida
#: O mesmo CNPJ sintético de tests/test_remessa_dia.py (o exemplo de manual).
CNPJ_SINTETICO = "11222333000181"
CUPOM = {"t1": [anexo("cupom", ext=".jpg")]}
DETALHE_REEMBOLSO = {"1": {"documentNumber": "REEMBOLSO FULANA MODELO"}}
AVISO = ("o documento declara REEMBOLSO FULANA MODELO: conferir se o "
         "favorecido é mesmo quem recebe")


def _loja(**mudancas):
    """A loja é o favorecido, a forma é Boleto, o anexo é a foto do cupom e o
    cadastro tem o Pix DA LOJA — mas o documento diz que o dinheiro é da Fulana."""
    return _boleto_sem_anexo(**dict({"paidTo": "LOJA MODELO SA",
                                     "paidToBankAccount": "PIX EMAIL loja@exemplo.com",
                                     "documentNumber": "REEMBOLSO FULANA MODELO"},
                                    **mudancas))


def _candidato(res):
    c, = remessa_dia.preparar(res.contas,
                              participantes={"LOJA MODELO SA": CNPJ_SINTETICO})[CONTA]
    return c


def test_reembolso_declarado_sem_aviso_vira_atencao_e_nasce_desmarcado():
    """Sem o "NF REEMBOLSO FULANA" na descrição, nada dizia que o dinheiro era
    da Fulana: a linha pagava o Pix da loja como APTO e ia MARCADA para a
    remessa. Agora é ATENÇÃO, com o nome na Obs, e a remessa pede um clique."""
    res = relatorio.montar_registros([_loja()], CUPOM, DETALHE_REEMBOLSO, {})
    linha = res.contas[CONTA][0]
    assert linha["status"] == "ATENÇÃO — documento declara reembolso"
    assert AVISO in linha["obs"]
    c = _candidato(res)
    assert c.impedimento == "" and not c.marcado


def test_reembolso_declarado_so_no_lancamento_tambem_vira_atencao():
    res = relatorio.montar_registros([_loja()], CUPOM, {}, {})
    linha = res.contas[CONTA][0]
    assert linha["status"] == "ATENÇÃO — documento declara reembolso"
    assert AVISO in linha["obs"]
    assert not _candidato(res).marcado


def test_a_mesma_linha_com_nf_de_verdade_continua_apta_e_marcada():
    """O controle: sem isto, o desmarcado acima poderia vir de outra trava."""
    res = relatorio.montar_registros([_loja(documentNumber="5678")], CUPOM, {}, {})
    assert res.contas[CONTA][0]["status"] == "APTO"
    c = _candidato(res)
    assert c.impedimento == "" and c.marcado


def test_aviso_pagar_para_nao_ganha_este_alarme():
    """Com o aviso "PAGAR PARA", quem recebe já é decidido pelo aviso."""
    aviso = {"t1": [anexo("PAGAR PARA FULANA MODELO")]}
    res = relatorio.montar_registros([_loja()], aviso, DETALHE_REEMBOLSO, {})
    linhas = res.contas.get(CONTA, []) + res.omitidos
    assert linhas
    for linha in res.contas.get(CONTA, []):
        assert "documento declara reembolso" not in linha["status"]
        assert "o documento declara REEMBOLSO" not in linha["obs"]


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


def test_nf_e_oc_nao_se_partem_no_ponto_de_milhar():
    """"NF 1 234" não bate com a nota nem com o casamento do Anexar: dentro do
    número, o ponto entre dígitos some sem virar espaço."""
    r = _partes(nf="1.234", oc="000.123")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 NF 1234 OC 000123"


def test_barra_e_hifen_entre_numeros_da_nf_separam_dois_numeros():
    """"5678/5679" são duas notas; juntas viravam "56785679", que não existe."""
    r = _partes(nf="5678/5679", oc="000.123-4")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 NF 5678 5679 OC 000123 4"
    r = _partes(nf="5678-5679")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 NF 5678 5679"


def test_separador_que_nao_esta_entre_digitos_continua_virando_espaco():
    r = _partes(nf="12.345/B - 2", oc="1234")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 NF 12345 B 2 OC 1234"


def test_so_oc_vai_so_a_oc():
    r = _partes(oc="1234", descricao="Material de obra")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 OC 1234"


def test_so_nf_vai_so_a_nf():
    r = _partes(nf="5678", descricao="Material de obra")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 NF 5678"


#: Ficha de arrecadação de verdade (48 dígitos, começa em 8, DV fecha) — o
#: mesmo exemplo fictício de `tests/test_pagamentos_melhorias.py`.
_LINHA_ARRECADACAO = "86860000026-5 70860161209-4 22026081001-8 61001177300-1"
#: Boleto bancário comum (47 dígitos), para provar que ele CONTINUA com "NF".
_LINHA_BANCARIA = "34191.57007 00024.924375 24177.010006 9 15340000115000"


def test_arrecadacao_nao_rotula_nf():
    """Ficha de arrecadação (tributo, taxa, órgão público) não tem cedente
    nem Nota Fiscal atrás: escrever "NF x" inventaria uma nota que não
    existe. O número do documento continua na descrição, sozinho — é o
    caso real da Receita Federal, 22/09/2026."""
    r = _partes(nf="262641912489", descricao="Guia DARF")
    r["tipo"], r["dados"] = "Boleto", _LINHA_ARRECADACAO
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 262641912489"


def test_arrecadacao_com_oc_mantem_a_oc_rotulada():
    """Só a NF perde o rótulo; a OC, quando existir, continua "OC y"."""
    r = _partes(nf="262641912489", oc="1234")
    r["tipo"], r["dados"] = "Boleto", _LINHA_ARRECADACAO
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 262641912489 OC 1234"


def test_boleto_comum_continua_rotulando_nf():
    """A régua é do CONTEÚDO da linha digitável, não do tipo "Boleto"
    sozinho: boleto bancário comum continua dizendo "NF x"."""
    r = _partes(nf="5678")
    r["tipo"], r["dados"] = "Boleto", _LINHA_BANCARIA
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 NF 5678"


def test_sem_nf_nem_oc_vai_a_descricao_do_lancamento():
    r = _partes(descricao="Material de obra")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 Material de obra"


def test_mao_de_obra_sem_nf_nem_oc_sai_contrato_e_medicao():
    """A forma curta que a planilha já mostra: o dono pediu sempre enxugar."""
    r = _partes(descricao="Servico de pintura - 1234 - Medição: 7")
    assert hp.descricao_para_colar(r, SICOOB) == "QD 99 LT 99 C 1234 M 7"


def test_mao_de_obra_com_nf_continua_saindo_pela_nf():
    r = _partes(nf="5678", descricao="Servico de pintura - 1234 - Medição: 7")
    assert hp.descricao_para_colar(r, SICOOB) == "QD 99 LT 99 NF 5678"


def test_sem_nada_sobra_o_centro_de_custo():
    assert hp.descricao_para_colar(_partes(), INTER) == "QD 99 LT 99"
    assert hp.descricao_para_colar(_partes(cc=""), INTER) == ""


def test_hifen_acento_e_pontuacao_saem():
    r = _partes(descricao="Instalação elétrica - CASA 2 / fase 1 (etapa nº3).",
                cc="QD 99 LT 01 | QD 99 LT 02")
    assert hp.descricao_para_colar(r, INTER) == (
        "QD 99 LT 01 QD 99 LT 02 Instalacao eletrica CASA 2 fase 1 etapa no3")


def test_hifen_entre_digitos_fica_e_o_que_separa_palavras_sai():
    """"LT 10-11" partido em "LT 10 11" faz o Anexar ler "LT 10" e anexar no
    lote errado. O hífen colado entre dígitos fica; o que separa palavras sai."""
    r = _partes(cc="QD 99 LT 10-11", descricao="Muro de divisa 3-4 - ESCRITORIO-X")
    assert hp.descricao_para_colar(r, INTER) == (
        "QD 99 LT 10-11 Muro de divisa 3-4 ESCRITORIO X")
    r = _partes(cc="QD 99 LT 10 - 11")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 10 11"


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


def test_o_filtro_do_reembolso_nao_apaga_o_lote_nem_o_que_tem_numero():
    """Tira "reembolso" e as palavras só de letras depois dela (o nome de quem
    recebe), até cinco; para em palavra com dígito, de imóvel ou de documento."""
    casos = {
        "Reembolso material QD 98 LT 97 casa 2": "QD 99 LT 99 QD 98 LT 97 casa 2",
        "Reembolso Fulana 3 parcelas": "QD 99 LT 99 3 parcelas",
        "reembolso lote 5 muro": "QD 99 LT 99 lote 5 muro",
        "Reembolso Fulana CASA 2": "QD 99 LT 99 CASA 2",
        "Reembolso Fulana cs 2": "QD 99 LT 99 cs 2",
    }
    for descricao, esperado in casos.items():
        obtido = hp.descricao_para_colar(_partes(descricao=descricao), INTER)
        assert obtido == esperado, descricao


def test_o_filtro_do_reembolso_para_no_rotulo_do_documento():
    """"Reembolso NF 1234 material" perdia o "NF", que o Anexar usa."""
    casos = {
        "Reembolso NF 1234 material": "QD 99 LT 99 NF 1234 material",
        "Reembolso Fulana OC 1234": "QD 99 LT 99 OC 1234",
        "reembolso fulana nfe 5678": "QD 99 LT 99 nfe 5678",
        "Reembolso Fulana NFS 5678": "QD 99 LT 99 NFS 5678",
        "Reembolso OS 12 pintura": "QD 99 LT 99 OS 12 pintura",
    }
    for descricao, esperado in casos.items():
        obtido = hp.descricao_para_colar(_partes(descricao=descricao), INTER)
        assert obtido == esperado, descricao


def test_o_nome_inteiro_de_quem_recebe_sai_ate_cinco_palavras():
    """"Reembolso Fulana Sicrana de Tal" deixava "Tal": o nome tem mais de três
    palavras. O teto passa a cinco, e o que vem depois dele fica."""
    r = _partes(descricao="Reembolso Fulana Sicrana de Tal")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99"
    r = _partes(descricao="Reembolso Fulana Sicrana de Tal Modelo cimento")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 cimento"


def test_o_centro_de_custo_nao_passa_pelo_filtro_do_reembolso():
    r = _partes(cc="REEMBOLSOS DIVERSOS", descricao="Material")
    assert hp.descricao_para_colar(r, INTER) == "REEMBOLSOS DIVERSOS Material"


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


def test_inter_corta_em_140_e_qualquer_outra_em_100_na_fronteira_de_palavra():
    """O lado seguro é o curto: conta Sicoob cujo nome não diga SICOOB levava
    140, e o banco podia cortar justamente a NF e a OC do fim."""
    r = _partes(descricao=_ITENS)
    curta = "QD 99 LT 99 " + " ".join(f"ITEM{n:02d}" for n in range(1, 13))
    longa = "QD 99 LT 99 " + " ".join(f"ITEM{n:02d}" for n in range(1, 19))
    assert len(curta) == 95 and len(longa) == 137
    assert hp.descricao_para_colar(r, INTER) == longa
    assert hp.descricao_para_colar(r, "conta modelo inter") == longa
    for conta in (SICOOB, "CONTA MODELO", "CONTA INTERNA MODELO", ""):
        assert hp.descricao_para_colar(r, conta) == curta, conta


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


def _linha_do_html(**mudancas):
    return dict(dict(_partes(descricao="Material"), tipo="Pix",
                     dados="fulana@exemplo.com", valor=10.0, status="APTO",
                     conferencia="", obs="", id="1",
                     favorecido="Fornecedor Modelo Ltda", reembolso=False,
                     reembolso_nome=""), **mudancas)


def test_no_html_geral_o_reembolso_mostra_quem_recebe():
    """O HTML é o caminho de pagar à mão: com o fornecedor na coluna, quem
    paga pelo HTML manda o dinheiro do reembolso para a pessoa errada."""
    linhas = [_linha_do_html(reembolso=True, reembolso_nome="FULANA MODELO"),
              _linha_do_html(id="2", reembolso=True, reembolso_nome=""),
              _linha_do_html(id="3")]
    contas = hp.contas_do_html_geral(relatorio.Resultado({INTER: linhas}, []))
    assert [e["favorecido"] for e in contas[0]["entries"]] == [
        "FULANA MODELO (reembolso de Fornecedor Modelo Ltda)",
        "? (reembolso de Fornecedor Modelo Ltda)",
        "Fornecedor Modelo Ltda"]


def test_o_quem_recebe_do_html_e_o_da_janela_de_confirmacao():
    """A mesma forma da coluna QUEM RECEBE (`confirmacao.Linha.quem_recebe`):
    duas telas dizendo quem recebe de dois jeitos é o começo de discordarem."""
    from dataclasses import MISSING, fields
    from pagamentos_dia import confirmacao
    obrigatorios = {f.name: None for f in fields(confirmacao.Linha)
                    if f.default is MISSING and f.default_factory is MISSING}
    for reembolso, nome, favorecido in ((True, "FULANA MODELO", "Fornecedor Modelo"),
                                        (True, "", "Fornecedor Modelo"),
                                        (True, "FULANA MODELO", ""),
                                        (False, "", "Fornecedor Modelo")):
        janela = confirmacao.Linha(**dict(obrigatorios, favorecido=favorecido,
                                          reembolso=reembolso, reembolso_nome=nome))
        registro = {"favorecido": favorecido, "reembolso": reembolso,
                    "reembolso_nome": nome}
        assert hp.quem_recebe(registro) == janela.quem_recebe


def test_o_html_geral_usa_a_descricao_para_colar():
    linha = dict(_partes(oc="1234", descricao="Material (Reembolso Fulano Modelo)"),
                 tipo="Pix", dados="fornecedor@exemplo.com", valor=10.0,
                 favorecido="Fornecedor Modelo - Ltda.", status="APTO",
                 conferencia="", obs="", id="1")
    contas = hp.contas_do_html_geral(relatorio.Resultado({SICOOB: [linha]}, []))
    entrada = contas[0]["entries"][0]
    assert entrada["descricao"] == "QD 99 LT 99 OC 1234"
    assert entrada["favorecido"] == "Fornecedor Modelo - Ltda."
