# -*- coding: utf-8 -*-
"""Pedidos do dono de 22/10/2026 (itens B e C) nos pagamentos do dia.

B. **Reembolso de sócio sem chave**: o documento diz "REEMBOLSO <pessoa>" e a
   pessoa está no cadastro local de reembolso (`pix_reembolso.json`, com a
   chave dela). A linha sai paga pelo Pix DA PESSOA, com a observação
   "reembolso a <pessoa> — chave do cadastro", e deixa de ser "ATENÇÃO —
   documento declara reembolso". Fora do cadastro, continua ATENÇÃO.
C. **Pagamento autorizado**: o anexo "PAGAMENTO AUTORIZADO - <nome>" não é
   boleto; é a autorização de pagar pelo Pix dos Dados Bancários do próprio
   lançamento (`paidToBankAccount`). E `"pix_dos_dados_bancarios": true` no
   `regras_fornecedor.json` faz o mesmo para o favorecido sem o anexo.

Puro: sem janela, sem ERP e sem rede. Nomes, chaves e valores inventados —
os CPFs são fictícios com DV válido. O repositório é público.
"""
import json

from pagamentos_dia import regras_pagamento as regras
from pagamentos_dia import reembolso, relatorio, remessa_dia

CONTA = "CONTA MODELO - SICOOB"
#: CPFs fictícios, DV válido.
CPF_SOCIO_UM = "12345678909"
CPF_SOCIO_DOIS = "98765432100"
CPF_FAVORECIDA = "11144477735"
#: Onze dígitos que NÃO fecham o DV de CPF.
CPF_QUEBRADO = "12345678900"
CNPJ_LOJA = "11222333000181"


def anexo(nome, tag=None, ext=".pdf", url=None):
    return {"filename": nome, "tagName": tag, "extension": ext,
            "downloadUrl": url or f"https://exemplo.invalid/{nome}"}


def _lanc(**mudancas):
    return dict({"id": "1", "tradePayableId": "t1", "paid": False,
                 "tradePayableAccount": {"name": CONTA},
                 "paidTo": "MADEIREIRA MODELO LTDA", "remainingValue": 410.0,
                 "plannedDate": "2026-10-22",
                 "tradePayablePaymentMethod": "Pix",
                 "paidToBankAccount": "",
                 "documentNumber": "REEMBOLSO SOCIO UM",
                 "costCentreDetails": [{"workName": "QD 99 LT 99"}]}, **mudancas)


def _cadastro(tmp_path, dados):
    """Grava o `pix_reembolso.json` e lê pelo carregador de verdade: o
    formato que o coordenador preenche é o que o teste usa."""
    (tmp_path / reembolso.ARQ_REEMBOLSO).write_text(
        json.dumps(dados, ensure_ascii=False), encoding="utf-8")
    return reembolso.carregar(tmp_path)


SOCIOS = {
    "SOCIO UM": {"nome": "SOCIO UM SOBRENOME", "documento": CPF_SOCIO_UM,
                 "chave": "123.456.789-09"},
    "SOCIO DOIS": {"nome": "SOCIO DOIS SOBRENOME", "documento": CPF_SOCIO_DOIS,
                   "chave": CPF_SOCIO_DOIS},
}

OC = {"t1": [anexo("7297")]}


def _linha(res):
    linha, = res.contas[CONTA]
    return linha


def _candidato(res, participantes=None):
    c, = remessa_dia.preparar(res.contas, participantes=participantes or {
        "MADEIREIRA MODELO LTDA": CNPJ_LOJA})[CONTA]
    return c


# ==========================================================================
# B. Reembolso de sócio: chave do cadastro
# ==========================================================================
def test_reembolso_de_socio_cadastrado_sai_pago_pela_chave_dele(tmp_path):
    cad = _cadastro(tmp_path, SOCIOS)
    res = relatorio.montar_registros([_lanc()], OC, {}, {},
                                     cadastro_reembolso=cad)
    linha = _linha(res)
    assert linha["tipo"] == "Pix"
    assert linha["dados"] == "123.456.789-09"
    assert linha["status"] == "APTO* (reembolso)"
    assert "reembolso a SOCIO UM SOBRENOME — chave do cadastro" in linha["obs"]
    assert "documento declara" not in linha["status"]
    assert "o documento declara REEMBOLSO" not in linha["obs"]
    # A remessa declara a PESSOA no segmento B (nome e CPF do cadastro), não
    # a loja — e o reembolso nasce desmarcado, como todo reembolso.
    assert linha["reembolso"] is True
    assert linha["reembolso_nome"] == "SOCIO UM SOBRENOME"
    assert linha["reembolso_documento"] == CPF_SOCIO_UM
    assert linha["reembolso_para"] == "SOCIO UM"
    c = _candidato(res)
    assert c.impedimento == "" and c.reembolso and not c.marcado


def test_reembolso_de_socio_ganha_do_pix_da_loja_no_cadastro(tmp_path):
    """O cadastro do lançamento tem o Pix da LOJA: o dinheiro é do sócio."""
    cad = _cadastro(tmp_path, SOCIOS)
    res = relatorio.montar_registros(
        [_lanc(paidToBankAccount="PIX EMAIL loja@exemplo.com",
               documentNumber="REEMBOLSO SOCIO DOIS")], OC, {}, {},
        cadastro_reembolso=cad)
    linha = _linha(res)
    assert linha["dados"] == CPF_SOCIO_DOIS
    assert "loja@exemplo.com" not in linha["dados"]
    assert linha["status"] == "APTO* (reembolso)"


def test_reembolso_declarado_no_detalhe_tambem_vale(tmp_path):
    cad = _cadastro(tmp_path, SOCIOS)
    res = relatorio.montar_registros(
        [_lanc(documentNumber="")], OC,
        {"1": {"documentNumber": "REEMBOLSO SOCIO UM"}}, {},
        cadastro_reembolso=cad)
    assert _linha(res)["status"] == "APTO* (reembolso)"


def test_socio_fora_do_cadastro_continua_conferir(tmp_path):
    cad = _cadastro(tmp_path, SOCIOS)
    res = relatorio.montar_registros(
        [_lanc(documentNumber="REEMBOLSO FULANO MODELO")], OC, {}, {},
        cadastro_reembolso=cad)
    linha = _linha(res)
    assert linha["status"] == "ATENÇÃO — documento declara reembolso"
    assert linha["dados"] == ""


def test_sem_cadastro_continua_conferir():
    res = relatorio.montar_registros([_lanc()], OC, {}, {})
    assert _linha(res)["status"] == "ATENÇÃO — documento declara reembolso"


def test_nome_que_so_comeca_igual_nao_casa(tmp_path):
    """"SOCIO UMBERTO" não é "SOCIO UM": casa por PALAVRA, não por letra."""
    cad = _cadastro(tmp_path, SOCIOS)
    res = relatorio.montar_registros(
        [_lanc(documentNumber="REEMBOLSO SOCIO UMBERTO")], OC, {}, {},
        cadastro_reembolso=cad)
    assert _linha(res)["status"] == "ATENÇÃO — documento declara reembolso"


def test_nome_que_casa_com_dois_do_cadastro_nao_escolhe(tmp_path):
    cad = _cadastro(tmp_path, SOCIOS)
    res = relatorio.montar_registros(
        [_lanc(documentNumber="REEMBOLSO SOCIO")], OC, {}, {},
        cadastro_reembolso=cad)
    assert _linha(res)["status"] == "ATENÇÃO — documento declara reembolso"


def test_nome_completo_no_documento_casa_com_o_cadastro_curto(tmp_path):
    cad = _cadastro(tmp_path, SOCIOS)
    res = relatorio.montar_registros(
        [_lanc(documentNumber="REEMBOLSO SÓCIO UM SOBRENOME")], OC, {}, {},
        cadastro_reembolso=cad)
    assert _linha(res)["status"] == "APTO* (reembolso)"


def test_chave_do_cadastro_com_cpf_que_nao_fecha_continua_conferir(tmp_path):
    cad = _cadastro(tmp_path, {"SOCIO UM": {"nome": "SOCIO UM", "chave": CPF_QUEBRADO}})
    res = relatorio.montar_registros([_lanc()], OC, {}, {},
                                     cadastro_reembolso=cad)
    assert _linha(res)["status"] == "ATENÇÃO — documento declara reembolso"


def test_chave_cpf_diferente_do_documento_continua_conferir(tmp_path):
    """Chave e documento do cadastro apontando para pessoas diferentes: o
    Pix iria para um e o segmento B declararia o outro."""
    cad = _cadastro(tmp_path, {"SOCIO UM": {"nome": "SOCIO UM", "documento": CPF_SOCIO_UM,
                                            "chave": CPF_SOCIO_DOIS}})
    res = relatorio.montar_registros([_lanc()], OC, {}, {},
                                     cadastro_reembolso=cad)
    assert _linha(res)["status"] == "ATENÇÃO — documento declara reembolso"


def test_cadastro_so_com_a_chave_cpf_usa_ela_como_documento(tmp_path):
    """O formato antigo (`{"NOME": "chave"}`): a chave é o CPF (dono)."""
    cad = _cadastro(tmp_path, {"SOCIO UM": CPF_SOCIO_UM})
    res = relatorio.montar_registros([_lanc()], OC, {}, {},
                                     cadastro_reembolso=cad)
    linha = _linha(res)
    assert linha["status"] == "APTO* (reembolso)"
    assert linha["reembolso_documento"] == CPF_SOCIO_UM
    assert _candidato(res).impedimento == ""


def test_cadastro_com_chave_cnpj_nao_vale_para_reembolso(tmp_path):
    cad = _cadastro(tmp_path, {"SOCIO UM": {"nome": "SOCIO UM", "chave": CNPJ_LOJA}})
    res = relatorio.montar_registros([_lanc()], OC, {}, {},
                                     cadastro_reembolso=cad)
    assert _linha(res)["status"] == "ATENÇÃO — documento declara reembolso"


def test_com_boleto_anexado_o_socio_nao_entra(tmp_path):
    """Boleto anexado ganha: o reembolso não é decidido no lugar dele."""
    cad = _cadastro(tmp_path, SOCIOS)
    res = relatorio.montar_registros(
        [_lanc(tradePayablePaymentMethod="Boleto")],
        {"t1": [anexo("boleto 7297", "Boleto")]}, {}, {},
        cadastro_reembolso=cad)
    linha = _linha(res)
    assert linha["tipo"] == "Boleto"
    assert linha["dados"] != "123.456.789-09"
    assert not linha["status"].startswith("APTO")


def test_ja_pago_nao_muda(tmp_path):
    cad = _cadastro(tmp_path, SOCIOS)
    res = relatorio.montar_registros(
        [_lanc(paid=True, sumOfPaidValues=410.0, remainingValue=0.0)], OC, {}, {},
        cadastro_reembolso=cad)
    assert _linha(res)["status"].startswith("JÁ PAGO")
    assert not _linha(res)["reembolso"]


# ==========================================================================
# C. Pagamento autorizado: Pix dos Dados Bancários do lançamento
# ==========================================================================
AUTORIZACAO = {"t1": [anexo("PAGAMENTO AUTORIZADO - FULANO")]}
OBS_AUTORIZADO = "pagamento autorizado (anexo) — Pix dos dados bancários do lançamento"


def _autorizado(**mudancas):
    return _lanc(**dict({"paidTo": "FAVORECIDA MODELO", "remainingValue": 500.0,
                         "documentNumber": "",
                         "paidToBankAccount": "111.444.777-35"}, **mudancas))


def test_autorizacao_paga_pelo_pix_dos_dados_bancarios():
    res = relatorio.montar_registros([_autorizado()], AUTORIZACAO, {}, {})
    linha = _linha(res)
    assert linha["tipo"] == "Pix"
    assert linha["dados"] == "111.444.777-35"
    assert linha["status"] == "APTO (autorizado)"
    assert OBS_AUTORIZADO in linha["obs"]
    assert "Boleto em imagem" not in linha["obs"]
    c = _candidato(res, {"FAVORECIDA MODELO": CPF_FAVORECIDA})
    assert c.impedimento == ""


def test_autorizacao_com_forma_de_pagar_vazia_nao_vira_boleto_em_imagem():
    """O caso do print: a autorização era o único PDF e virava "Boleto em
    imagem — preencher manual"."""
    for forma in (None, "", "Boleto"):
        res = relatorio.montar_registros(
            [_autorizado(tradePayablePaymentMethod=forma)], AUTORIZACAO, {}, {})
        linha = _linha(res)
        assert linha["tipo"] == "Pix", forma
        assert linha["dados"] == "111.444.777-35", forma
        assert linha["status"] == "APTO (autorizado)", forma
        assert "Boleto em imagem" not in linha["obs"], forma


def test_autorizacao_com_numeros_de_boleto_no_texto_continua_autorizacao():
    """A linha digitável que porventura esteja DENTRO da autorização não faz
    dela um boleto."""
    linha_valida = "34191.57007 00024.924375 24177.010006 9 15340000115000"
    autorizacao = {"t1": [anexo("PAGAMENTO AUTORIZADO - FULANO", url="u1")]}
    res = relatorio.montar_registros(
        [_autorizado(tradePayablePaymentMethod=None)], autorizacao, {},
        {"u1": f"PAGAMENTO AUTORIZADO\nref. {linha_valida}"})
    linha = _linha(res)
    assert linha["tipo"] == "Pix"
    assert linha["dados"] == "111.444.777-35"
    assert OBS_AUTORIZADO in linha["obs"]


def test_autorizacao_pelo_texto_do_anexo():
    neutro = {"t1": [anexo("documento 123", url="u1")]}
    res = relatorio.montar_registros(
        [_autorizado(tradePayablePaymentMethod=None)], neutro, {},
        {"u1": "Declaro que o PAGAMENTO AUTORIZADO à favorecida acima."})
    linha = _linha(res)
    assert linha["dados"] == "111.444.777-35"
    assert OBS_AUTORIZADO in linha["obs"]


def test_autorizacao_sem_chave_valida_continua_conferir():
    for dados in ("", CPF_QUEBRADO, "VER COMENTÁRIO"):
        res = relatorio.montar_registros(
            [_autorizado(paidToBankAccount=dados, tradePayablePaymentMethod=None)],
            AUTORIZACAO, {}, {})
        linhas = res.contas.get(CONTA, [])
        for linha in linhas:
            assert not linha["status"].startswith("APTO"), dados
            assert OBS_AUTORIZADO not in linha["obs"], dados


def test_autorizacao_nao_ganha_de_boleto_anexado():
    anexos = {"t1": [anexo("PAGAMENTO AUTORIZADO - FULANO"),
                     anexo("boleto 55", "Boleto")]}
    res = relatorio.montar_registros(
        [_autorizado(tradePayablePaymentMethod="Boleto")], anexos, {}, {})
    linha = _linha(res)
    assert linha["tipo"] == "Boleto"
    assert OBS_AUTORIZADO not in linha["obs"]


def test_regra_do_favorecido_autoriza_sem_o_anexo_dizer():
    regras_forn = {"FAVORECIDA MODELO": {"pix_dos_dados_bancarios": True}}
    res = relatorio.montar_registros(
        [_autorizado(tradePayablePaymentMethod=None)],
        {"t1": [anexo("orcamento 1", url="o")]},
        {}, {"o": "ORCAMENTO 1 - madeira"}, regras_fornecedor=regras_forn)
    linha = _linha(res)
    assert linha["tipo"] == "Pix"
    assert linha["dados"] == "111.444.777-35"
    assert linha["status"].startswith("APTO")
    assert ("pagamento autorizado (regra do favorecido) — Pix dos dados "
            "bancários do lançamento") in linha["obs"]


def test_sem_regra_e_sem_autorizacao_nada_muda():
    res = relatorio.montar_registros(
        [_autorizado(tradePayablePaymentMethod=None)], {"t1": [anexo("foto 1")]},
        {}, {})
    linha = _linha(res)
    assert "pagamento autorizado" not in linha["obs"]
    assert linha["status"] == "ATENÇÃO — sem dados de pgto"


def test_regra_lida_do_regras_fornecedor_json(tmp_path):
    (tmp_path / regras.ARQ_FORNECEDORES).write_text(json.dumps(
        {"FAVORECIDA MODELO": {"pix_dos_dados_bancarios": True}}), encoding="utf-8")
    cad = regras.carregar_fornecedores(tmp_path)
    assert regras.pix_dos_dados_bancarios("FAVORECIDA MODELO DE TAL", cad)
    assert not regras.pix_dos_dados_bancarios("OUTRA PESSOA", cad)
    assert not regras.pix_dos_dados_bancarios("FAVORECIDA MODELO", {})


# ==========================================================================
# Revisão de dinheiro de 22/10/2026 — A1 e A2
# ==========================================================================
LINHA_VALIDA = "34191.57007 00024.924375 24177.010006 9 15340000115000"
REGRA_FAVORECIDA = {"FAVORECIDA MODELO": {"pix_dos_dados_bancarios": True}}


def _nao_autorizou(res):
    """Sem certeza, a linha volta ao caminho de antes: ATENÇÃO na planilha
    ou NÃO ENTRARAM — nunca APTO pelo Pix dos Dados Bancários."""
    for linha in res.contas.get(CONTA, []):
        assert "pagamento autorizado" not in linha["obs"]
        assert not linha["status"].startswith("APTO")
        assert linha["dados"] != "111.444.777-35"


def test_a1_regra_nao_passa_por_cima_do_boleto_dentro_da_nf():
    """A1: boleto achado DENTRO da NF (a etiqueta não o anuncia) ganha do Pix
    dos Dados Bancários, mesmo com a regra do favorecido — senão a remessa
    pagava o boleto em aberto E o Pix (pagamento em dobro)."""
    anexos = {"t1": [anexo("NF 5909", "Nota Fiscal", url="nf")]}
    textos = {"nf": f"NOTA FISCAL 5909\nRecibo do pagador\n{LINHA_VALIDA}"}
    for forma in ("Pix", None):
        res = relatorio.montar_registros(
            [_autorizado(tradePayablePaymentMethod=forma)], anexos, {}, textos,
            regras_fornecedor=REGRA_FAVORECIDA)
        linha = _linha(res)
        assert linha["tipo"] == "Boleto", forma
        assert "pagamento autorizado" not in linha["obs"], forma
        assert linha["dados"] != "111.444.777-35", forma


def test_a1_autorizacao_nao_passa_por_cima_do_boleto_dentro_da_nf():
    anexos = {"t1": [anexo("PAGAMENTO AUTORIZADO - FULANO", url="a"),
                     anexo("NF 5909", "Nota Fiscal", url="nf")]}
    textos = {"a": "PAGAMENTO AUTORIZADO",
              "nf": f"NOTA FISCAL 5909\n{LINHA_VALIDA}"}
    res = relatorio.montar_registros([_autorizado()], anexos, {}, textos)
    linha = _linha(res)
    assert linha["tipo"] == "Boleto"
    assert OBS_AUTORIZADO not in linha["obs"]


def test_a2_autorizacao_com_anexo_em_imagem_fica_atencao():
    """Uma foto ao lado da autorização pode ser o boleto escaneado: sem ler
    com certeza, não autoriza (fica como antes, ATENÇÃO)."""
    anexos = {"t1": [anexo("PAGAMENTO AUTORIZADO - FULANO", url="a"),
                     anexo("scan 01", ext=".jpg", url="img")]}
    res = relatorio.montar_registros(
        [_autorizado(tradePayablePaymentMethod=None)], anexos, {},
        {"a": "PAGAMENTO AUTORIZADO", "img": "texto qualquer do ocr"},
        urls_ocr={"img"})
    linha = _linha(res)
    assert OBS_AUTORIZADO not in linha["obs"]
    assert not linha["status"].startswith("APTO")


def test_a2_autorizacao_com_pdf_sem_texto_ou_so_ocr_fica_atencao():
    for textos, ocr in (({}, set()),                         # PDF não lido
                        ({"p": "texto borrado sem linha"}, {"p"})):  # OCR não fechou
        anexos = {"t1": [anexo("PAGAMENTO AUTORIZADO - FULANO"),
                         anexo("documento 2", url="p")]}
        res = relatorio.montar_registros(
            [_autorizado(tradePayablePaymentMethod=None)], anexos, {}, textos,
            urls_ocr=ocr)
        _nao_autorizou(res)


def test_a2_regra_com_anexo_nao_lido_fica_atencao():
    res = relatorio.montar_registros(
        [_autorizado(tradePayablePaymentMethod=None)],
        {"t1": [anexo("scan 01", ext=".jpg")]}, {}, {},
        regras_fornecedor=REGRA_FAVORECIDA)
    _nao_autorizou(res)


def test_a2_autoriza_solto_no_nome_nao_e_autorizacao():
    for nome in ("OC 5909 AUTORIZADA", "orçamento autorizado",
                 "AUTORIZAÇÃO DE FORNECIMENTO", "autorizacao de compra"):
        assert not relatorio.eh_autorizacao(anexo(nome)), nome


def test_a2_pagamento_autorizado_sem_acento_nem_caixa():
    for nome in ("PAGAMENTO AUTORIZADO - FULANO", "pagamento autorizado",
                 "Pagamento_Autorizado julio", "PAGAMENTO  AUTORIZADO"):
        assert relatorio.eh_autorizacao(anexo(nome)), nome
    assert relatorio.eh_autorizacao(anexo("doc 9", url="u"),
                                    {"u": "Pagamento Autorizado pela diretoria"})
    assert not relatorio.eh_autorizacao(anexo("doc 9", url="u"),
                                        {"u": "Ordem de compra autorizada"})


# ==========================================================================
# Revisão de dinheiro de 22/10/2026 — A6
# ==========================================================================
def test_a6_dois_documentos_nos_dados_bancarios_nao_escolhe():
    for texto in ("PIX CPF 111.444.777-35 / CNPJ 11.222.333/0001-81",
                  "CNPJ 11.222.333/0001-81 ou CPF 111.444.777-35"):
        assert relatorio.chave_dos_dados_bancarios(texto) == "", texto


def test_a6_dados_de_ted_nao_viram_chave():
    for texto in ("BANCO 756 AG 3001 CC 12345-6 CPF/CNPJ DO TITULAR 111.444.777-35",
                  "TED - Agência 3001 Conta 12345-6 - titular 111.444.777-35"):
        assert relatorio.chave_dos_dados_bancarios(texto) == "", texto


def test_a6_chave_unica_continua_valendo():
    assert relatorio.chave_dos_dados_bancarios("111.444.777-35") == "111.444.777-35"
    assert relatorio.chave_dos_dados_bancarios("PIX CPF 111.444.777-35") == "111.444.777-35"
    assert relatorio.chave_dos_dados_bancarios(
        "PIX EMAIL fulano@exemplo.com") == "fulano@exemplo.com"
    assert relatorio.chave_dos_dados_bancarios(
        "CHAVE PIX CNPJ 11.222.333/0001-81") == "11.222.333/0001-81"


# ==========================================================================
# Revisão de dinheiro de 22/10/2026 — A3
# ==========================================================================
def test_a3_entrada_de_uma_palavra_nunca_casa(tmp_path):
    """"FULANO" no cadastro (toda pessoa de aviso PAGAR PARA mora lá) não
    pode pagar "REEMBOLSO FULANO OUTRAPESSOA" com a chave do Fulano."""
    cad = _cadastro(tmp_path, {"FULANO": {"nome": "FULANO", "chave": CPF_SOCIO_UM}})
    for quem in ("FULANO OUTRAPESSOA", "FULANO"):
        assert reembolso.socio_do_documento(quem, cad) is None, quem


def test_a3_todas_as_palavras_do_cadastro_tem_de_estar_no_documento(tmp_path):
    cad = _cadastro(tmp_path, SOCIOS)
    # Documento mais curto que o cadastro: "SOCIO" sozinho não é "SOCIO UM".
    assert reembolso.socio_do_documento("SOCIO", cad) is None
    # Primeira palavra igual, segunda diferente.
    assert reembolso.socio_do_documento("SOCIO TRES", cad) is None
    # Fora de ordem não vale.
    assert reembolso.socio_do_documento("UM SOCIO", cad) is None
    achado = reembolso.socio_do_documento("SOCIO UM SOBRENOME", cad)
    assert achado and achado[0].nome == "SOCIO UM SOBRENOME"


def test_a3_documento_que_so_comeca_pelo_nome_do_cadastro_nao_casa(tmp_path):
    """O caso da revisão: "REEMBOLSO <primeiro nome> <outra pessoa>"."""
    cad = _cadastro(tmp_path, {"FULANO DE TAL": {"nome": "FULANO DE TAL",
                                                 "chave": CPF_SOCIO_UM}})
    res = relatorio.montar_registros(
        [_lanc(documentNumber="REEMBOLSO FULANO OUTRAPESSOA")], OC, {}, {},
        cadastro_reembolso=cad)
    assert _linha(res)["status"] == "ATENÇÃO — documento declara reembolso"


def test_a3_documento_mais_curto_que_o_cadastro_nao_casa(tmp_path):
    cad = _cadastro(tmp_path, {"SOCIO UM": SOCIOS["SOCIO UM"]})
    assert reembolso.socio_do_documento("SOCIO", cad) is None
