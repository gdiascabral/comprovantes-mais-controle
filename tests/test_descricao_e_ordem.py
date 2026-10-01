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


def _partes(nf="", oc="", descricao="", cc="QD 99 LT 99", utilidade=False,
            nf_anexada=True):
    """Por padrão a linha tem NF anexada (o "NF x" depende disso desde 01/10/2026)."""
    return {"centro_custo": cc, "nf": nf, "oc_da_descricao": oc,
            "nf_anexada": nf_anexada,
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
    # Documento sem OC leva a descrição do lançamento (dono, 01/10/2026).
    r = _partes(nf="5678", descricao="Material de obra")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 Material de obra NF 5678"


#: Ficha de arrecadação de verdade (48 dígitos, começa em 8, DV fecha) — o
#: mesmo exemplo fictício de `tests/test_pagamentos_melhorias.py`.
_LINHA_ARRECADACAO = "86860000026-5 70860161209-4 22026081001-8 61001177300-1"
#: Boleto bancário comum (47 dígitos), para provar que ele CONTINUA com "NF".
_LINHA_BANCARIA = "34191.57007 00024.924375 24177.010006 9 15340000115000"


def test_arrecadacao_nao_rotula_nf():
    """Ficha de arrecadação (tributo, taxa, órgão público — ex.: guia da
    Receita Federal) não tem cedente nem Nota Fiscal atrás: escrever "NF x"
    inventaria uma nota que não existe. O número do documento continua na
    descrição, sozinho (dono, 22/09/2026)."""
    r = _partes(nf="123456789012", descricao="Guia DARF")
    r["tipo"], r["dados"] = "Boleto", _LINHA_ARRECADACAO
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 Guia DARF 123456789012"


def test_arrecadacao_com_oc_mantem_a_oc_rotulada():
    """Só a NF perde o rótulo; a OC, quando existir, continua "OC y"."""
    r = _partes(nf="123456789012", oc="1234")
    r["tipo"], r["dados"] = "Boleto", _LINHA_ARRECADACAO
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 123456789012 OC 1234"


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


# ------------------------------------- "NF" só com nota fiscal anexada (01/10/2026)
_ITEM_NF = {"id": "1", "documentNumber": "1234",
            "costCentreDetails": [{"workName": "QD 99 LT 99"}]}


def _com_anexos(files, textos=None, oc=""):
    reg = relatorio.partes_no_registro(
        _ITEM_NF, files, "", {"purchaseOrder": {"number": oc}} if oc else None,
        textos)
    reg["centro_custo"] = relatorio.centro_de_custo(_ITEM_NF)
    return reg


def test_anexo_nf_com_numero_no_nome_rotula_nf():
    r = _com_anexos([anexo("NF 123.pdf")])
    assert r["nf_anexada"] is True
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 NF 1234"


def test_nf_colada_ao_numero_e_nfse_e_danfe_valem():
    for nome in ("nf1234.pdf", "NFS-e 55.pdf", "NF-e 9.pdf", "DANFE.pdf",
                 "Nota Fiscal obra.pdf"):
        assert relatorio.tem_nf_anexada([anexo(nome)]), nome


def test_so_boleto_anexado_numero_sem_nf():
    r = _com_anexos([anexo("boleto 1234.pdf", tag="Boleto")], oc="55")
    assert r["nf_anexada"] is False
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 1234 OC 55"


def test_merge_etiquetado_recibo_com_danfe_no_texto_vale_nf():
    f = anexo("merge-1.pdf", tag="Recibo")
    assert relatorio.tem_nf_anexada([f], {f["downloadUrl"]: "DANFE ... chave"})
    assert relatorio.tem_nf_anexada([f], {f["downloadUrl"]: "chave de acesso " + "1" * 44})
    assert not relatorio.tem_nf_anexada([f], {f["downloadUrl"]: "boleto 34191"})
    assert not relatorio.tem_nf_anexada([f])
    r = _com_anexos([f], {f["downloadUrl"]: "NOTA FISCAL ELETRONICA"})
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 NF 1234"


def test_comprovante_com_nf_no_nome_nao_e_nf():
    for nome in ("Comprovante NF 1234.pdf", "contrato NF.pdf", "medicao NF 3.pdf"):
        assert not relatorio.tem_nf_anexada([anexo(nome)]), nome
    r = _com_anexos([anexo("comprovante NF 1234.pdf")])
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 1234"


def test_registro_sem_a_chave_nf_anexada_fica_sem_rotulo():
    r = _partes(nf="5678", oc="1234")
    del r["nf_anexada"]
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 5678 OC 1234"


def test_monta_descricao_com_e_sem_nf_anexada():
    ov = {"purchaseOrder": {"number": 7}}
    assert relatorio.monta_descricao(_ITEM_NF, [anexo("NF 1234.pdf")], "", ov) \
        == "QD 99 LT 99 NF 1234 OC 7"
    assert relatorio.monta_descricao(_ITEM_NF, [anexo("boleto.pdf", tag="Boleto")],
                                     "", ov) == "QD 99 LT 99 1234 OC 7"
    assert relatorio.monta_descricao(_ITEM_NF, [], "", None) == "QD 99 LT 99 1234"


def test_pelo_pai_a_chave_chega_ao_registro_e_a_descricao_para_colar():
    """`montar_registros` leva `nf_anexada` até o registro e dele ao HTML."""
    nf = anexo("NF 1234.pdf", tag="Nota fiscal")
    bol = anexo("boleto.pdf", tag="Boleto")
    item = {"id": "1", "tradePayableId": "t1", "paid": False,
            "tradePayableAccount": {"name": CONTA}, "paidTo": "Fornecedor Modelo",
            "remainingValue": 10.0, "tradePayablePaymentMethod": "Boleto",
            "documentNumber": "1234",
            "costCentreDetails": [{"workName": "QD 99 LT 99"}]}
    for files, esperado, nota in (([nf, bol], "QD 99 LT 99 NF 1234", True),
                                  ([bol], "QD 99 LT 99 1234", False)):
        res = relatorio.montar_registros([item], {"t1": files}, {}, {})
        linha = res.contas[CONTA][0]
        assert linha["nf_anexada"] is nota
        assert hp.descricao_para_colar(linha, INTER) == esperado


# ---------------------------------------- conserto 1/5: boleto com "NF" no nome
def test_boleto_com_nf_no_nome_nao_e_nota():
    for f in (anexo("boleto NF 5909.pdf", tag="Boleto"),
              anexo("boleto nf 1234.pdf"),
              anexo("[Boleto] boleto NF 5909", tag="Boleto"),
              anexo("fatura NF 12.pdf")):
        assert not relatorio.tem_nf_anexada([f]), f["filename"]
        texto_de_boleto = {f["downloadUrl"]: "34191 57007 beneficiario valor"}
        assert not relatorio.tem_nf_anexada([f], texto_de_boleto), f["filename"]


def test_boleto_com_nf_no_nome_vale_se_o_texto_confirma_a_nota():
    f = anexo("boleto NF 5909.pdf", tag="Boleto")
    for texto in ("DANFE documento auxiliar", "NOTA FISCAL ELETRONICA", "NFS-e 5909",
                  "NF-e", "chave de acesso " + "1" * 44):
        assert relatorio.tem_nf_anexada([f], {f["downloadUrl"]: texto}), texto


def test_marca_forte_no_rotulo_vale_ate_em_boleto():
    assert relatorio.tem_nf_anexada([anexo("boleto e DANFE.pdf", tag="Boleto")])
    assert relatorio.tem_nf_anexada([anexo("x.pdf", tag="Nota fiscal boleto")])


def test_44_digitos_soltos_nao_confirmam_nota():
    """O código de barras de boleto também tem 44 dígitos."""
    f = anexo("merge-1.pdf", tag="Recibo")
    assert not relatorio.tem_nf_anexada([f], {f["downloadUrl"]: "boleto " + "1" * 44})
    agrupada = " ".join(["1234"] * 11)
    assert relatorio.tem_nf_anexada([f], {f["downloadUrl"]: agrupada})


def test_nfs_sem_e_conta_como_nota_e_palavras_parecidas_nao():
    assert relatorio.tem_nf_anexada([anexo("NFS 123.pdf")])
    for nome in ("confirmacao.pdf", "INFO.pdf", "conf 12.pdf"):
        assert not relatorio.tem_nf_anexada([anexo(nome)]), nome


# ------------------------------- B2: documento sem OC leva a descrição (01/10/2026)
def test_b2_doc_sem_oc_leva_a_descricao_com_e_sem_nf():
    r = _partes(nf="123", descricao="Material de obra")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 Material de obra NF 123"
    r["nf_anexada"] = False
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 Material de obra 123"


def test_b2_doc_com_oc_fica_sem_descricao():
    r = _partes(nf="123", oc="55", descricao="Material de obra")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 NF 123 OC 55"
    r["nf_anexada"] = False
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 123 OC 55"


def test_b2_limite_de_100_corta_a_descricao_e_preserva_o_numero():
    longa = " ".join(["cimento"] * 30)
    r = _partes(nf="987654", descricao=longa)
    saida = hp.descricao_para_colar(r, "CONTA SICOOB")
    assert len(saida) <= 100
    assert saida.startswith("QD 99 LT 99 cimento")
    assert saida.endswith("NF 987654")


def test_b2_descricao_que_ja_traz_o_numero_nao_o_repete():
    r = _partes(nf="1234", descricao="Cimento 1234 obra")
    saida = hp.descricao_para_colar(r, INTER)
    assert saida == "QD 99 LT 99 Cimento obra NF 1234"
    r = _partes(nf="123", descricao="Cimento 1234")  # 123 não é palavra de 1234
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 Cimento 1234 NF 123"


def test_b2_nao_repete_o_centro_de_custo_e_medicao_e_utilidade_ficam():
    r = _partes(nf="55", descricao="QD 99 LT 99 Reboco")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 Reboco NF 55"
    m = _partes(nf="55", descricao="X - 7 - Medição: 3")
    assert hp.descricao_para_colar(m, INTER) == "QD 99 LT 99 NF 55"
    u = _partes(nf="55", descricao="UC 1 jan", utilidade=True)
    assert hp.descricao_para_colar(u, INTER) == "QD 99 LT 99 UC 1 jan"


def test_b2_monta_descricao_doc_sem_oc_leva_a_descricao():
    item = dict(_ITEM_NF, description="Material de obra")
    com = [anexo("NF 1234.pdf")]
    assert relatorio.monta_descricao(item, com) == "QD 99 LT 99 Material de obra NF 1234"
    assert relatorio.monta_descricao(item, []) == "QD 99 LT 99 Material de obra 1234"
    ov = {"purchaseOrder": {"number": 7}}
    assert relatorio.monta_descricao(item, com, "", ov) == "QD 99 LT 99 NF 1234 OC 7"
    rep_ = dict(item, description="Cimento 1234")
    assert relatorio.monta_descricao(rep_, com) == "QD 99 LT 99 Cimento NF 1234"


# ------------------------------------------------ B2 conserto 1/5
def test_b2c_limite_de_140_no_inter_com_descricao_longa():
    longa = " ".join(f"palavra{i}" for i in range(40))
    r = _partes(nf="987654", descricao=longa)
    saida = hp.descricao_para_colar(r, INTER)
    esperado = "QD 99 LT 99 " + " ".join(f"palavra{i}" for i in range(12)) + " NF 987654"
    assert saida == esperado and len(saida) <= 140


def test_b2c_limite_de_100_com_texto_exato():
    longa = " ".join(["cimento"] * 30)
    r = _partes(nf="987654", descricao=longa)
    assert hp.descricao_para_colar(r, "CONTA SICOOB") == \
        "QD 99 LT 99 " + " ".join(["cimento"] * 9) + " NF 987654"


def test_b2c_cc_e_documento_estourando_o_limite_corta_o_cc():
    cc = " ".join(["BLOCO"] + [f"TORRE{i}" for i in range(20)])
    r = _partes(nf="987654", descricao="cimento", cc=cc)
    saida = hp.descricao_para_colar(r, "CONTA SICOOB")
    assert len(saida) <= 100 and saida.endswith("NF 987654")
    assert saida.startswith("BLOCO TORRE0") and "cimento" not in saida


def test_b2c_reembolso_e_caractere_especial_na_descricao_com_documento():
    r = _partes(nf="987654",
                descricao="Reembolso Fulano - Cimento & areia (obra) #5")
    assert hp.descricao_para_colar(r, INTER) == \
        "QD 99 LT 99 Cimento areia obra 5 NF 987654"


def test_b2c_documento_com_barra_passa_pela_remocao():
    r = _partes(nf="5678/5679", descricao="Cimento 5678 5679 obra")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 Cimento obra NF 5678 5679"
    item = dict(_ITEM_NF, documentNumber="5678/5679",
                description="Cimento 5678 5679 obra")
    assert relatorio.monta_descricao(item, [anexo("NF 1.pdf")]) == \
        "QD 99 LT 99 Cimento obra NF 5678/5679"


def test_b2c_numero_curto_nao_sai_da_descricao_porque_pode_ser_lote():
    r = _partes(nf="10", descricao="Cimento LT 10")
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 Cimento LT 10 NF 10"
    item = dict(_ITEM_NF, documentNumber="10", description="Cimento LT 10")
    assert relatorio.monta_descricao(item, [anexo("NF 1.pdf")]) == \
        "QD 99 LT 99 Cimento LT 10 NF 10"


def test_b2c_planilha_cc_por_palavra_inteira_e_corte_em_palavra():
    item = {"documentNumber": "5678", "description": "LT 10 obra",
            "costCentreDetails": [{"workName": "LT 1"}]}
    assert relatorio.monta_descricao(item, []) == "LT 1 LT 10 obra 5678"
    item = dict(_ITEM_NF, documentNumber="987654",
                description=" ".join(["cimento"] * 30))
    saida = relatorio.monta_descricao(item, [anexo("NF 1.pdf")])
    miolo = saida[len("QD 99 LT 99 "):-len(" NF 987654")]
    assert saida.endswith("NF 987654") and len(miolo) <= 110
    assert set(miolo.split()) == {"cimento"} and miolo.startswith("cimento")
    assert len(miolo.split()) == 13  # 13*7 + 12 = 103; a 14a estouraria 110


def test_b2c_planilha_prefixo_parcial_de_cc_nao_e_cortado():
    item = {"documentNumber": "5678", "description": "QD 99 reboco",
            "costCentreDetails": [{"workName": "QD 99 LT 99"}]}
    assert relatorio.monta_descricao(item, []) == "QD 99 LT 99 QD 99 reboco 5678"


# ---- revisão final: sem nota anexada o "NF" do texto livre não sobra
def test_sem_nf_anexada_tira_o_nf_do_texto_livre_antes_do_numero():
    r = _partes(nf="1234", descricao="COMPRA CIMENTO NF 1234", nf_anexada=False)
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 COMPRA CIMENTO 1234"
    for rotulo in ("NF-E", "NFE", "NOTA", "nf"):
        r = _partes(nf="1234", descricao=f"COMPRA CIMENTO {rotulo} 1234",
                    nf_anexada=False)
        assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 COMPRA CIMENTO 1234", rotulo
    # com a nota anexada o texto livre fica como está (o documento sai do fim)
    r = _partes(nf="1234", descricao="COMPRA CIMENTO NF 1234", nf_anexada=True)
    assert hp.descricao_para_colar(r, INTER) == "QD 99 LT 99 COMPRA CIMENTO NF 1234", "sem NF NF"


def test_monta_descricao_sem_nf_anexada_tira_o_nf_do_texto_livre():
    item = dict(_ITEM_NF, description="COMPRA CIMENTO NF 1234")
    assert relatorio.monta_descricao(item, []) == "QD 99 LT 99 COMPRA CIMENTO 1234"
