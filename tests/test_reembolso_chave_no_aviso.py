# -*- coding: utf-8 -*-
"""A chave Pix do reembolso quando o aviso é SÓ a chave.

O defeito de 14/09/2026: quatro reembolsos da mesma pessoa saíram do HTML como
"chave não cadastrada; abrir o aviso", com a chave em três lugares — no aviso,
no lançamento e no cadastro de Contatos. Três causas em fila:

1. o anexo `PAGAR PARA <NOME>.pdf` tinha como TEXTO apenas `PIX: <cpf>`. A
   frase "PAGAR PARA" morava só no nome do arquivo, e a janela de leitura só
   abria quando a frase estava no texto — nenhum dos dois leitores (chave e
   documento) chegava a olhar o papel;
2. o cadastro de Contatos tinha DUAS pessoas com o mesmo primeiro nome, e o
   nome do aviso é só o primeiro nome — o desempate por começo único desistiu,
   como deve;
3. em duas das quatro linhas o favorecido do lançamento ERA a pessoa, com a
   chave dela no `paidToBankAccount` — e o ramo do reembolso ignora esse campo
   de propósito, porque na maioria das vezes ele é a chave do FORNECEDOR.

O conserto abre caminhos novos para achar a chave, e a revisão mostrou que
cada um deles, aberto demais, paga a pessoa errada. Por isso metade destes
testes é do lado de FORA: o recibo, o comprovante e a DANFE renomeados como
aviso, a homônima no título, o cadastro de Contatos que não carregou.

Sem rede, sem tkinter, sem Excel. Nenhum dado real: nomes inventados e
documentos sintéticos que fecham o dígito verificador.
"""
from pagamentos_dia import reembolso, relatorio, remessa_dia

CPF_DA_PESSOA = "529.982.247-25"
CPF_DA_PESSOA_DIGITOS = "52998224725"
#: O mesmo CPF com o último dígito trocado — o erro de OCR que paga outra pessoa.
CPF_DV_ERRADO = "529.982.247-26"
CPF_DE_OUTRA = "111.444.777-35"
CPF_DE_OUTRA_DIGITOS = "11144477735"
CNPJ_DO_FORNECEDOR = "11.222.333/0001-81"
CNPJ_DO_FORNECEDOR_DIGITOS = "11222333000181"
CELULAR = "(62) 99999-8888"

PESSOA = "Fulana de Tal Souza"
HOMONIMA = "Fulana Beltrana Costa"
FORNECEDOR = "Estacionamento Modelo Ltda"

#: `{nome normalizado: documento}`, como `mc_api.listar_participantes` devolve.
#: A segunda Fulana é a homônima: mesmo primeiro nome, outra pessoa, outro CPF.
CONTATOS = {"FULANA DE TAL SOUZA": CPF_DA_PESSOA_DIGITOS,
            "FULANA BELTRANA COSTA": CPF_DE_OUTRA_DIGITOS,
            "ESTACIONAMENTO MODELO LTDA": CNPJ_DO_FORNECEDOR_DIGITOS}

URL_AVISO = "https://exemplo/anexo/aviso"
CONTA = "CONTA TESTE"


def aviso(url=URL_AVISO, filename="PAGAR PARA FULANA ", tag="Reembolso"):
    """O anexo como o ERP o devolve: nome SEM extensão (com espaço no fim) e a
    etiqueta "Reembolso", que não diz "pagar para"."""
    return {"filename": filename, "tagName": tag, "extension": ".pdf",
            "downloadUrl": url}


def textos_do_aviso(texto, url=URL_AVISO):
    return {url: texto}


def leitura(texto):
    """(chave, documento) que os dois leitores tiram do aviso com este texto."""
    files, textos = [aviso()], textos_do_aviso(texto)
    return (relatorio.chave_pix_do_aviso(files, textos),
            reembolso.documento_do_aviso(files, textos))


# ==========================================================================
# 1. O aviso que é só a chave
# ==========================================================================
def test_aviso_so_com_a_chave_tem_a_chave_e_o_documento_lidos():
    assert leitura(f"PIX: {CPF_DA_PESSOA}") == (CPF_DA_PESSOA,
                                                CPF_DA_PESSOA_DIGITOS)


def test_rotulo_com_o_tipo_e_chave_na_linha_de_baixo_tambem_valem():
    assert leitura(f"PIX CPF: {CPF_DA_PESSOA}")[0] == CPF_DA_PESSOA
    assert leitura(f"CHAVE PIX:\n{CPF_DA_PESSOA}")[0] == CPF_DA_PESSOA


def test_celular_depois_do_rotulo_e_chave_e_nao_e_documento():
    assert leitura(f"CHAVE PIX: {CELULAR}") == (CELULAR, "")


def test_vale_o_primeiro_item_depois_do_rotulo():
    """O que vem depois da chave, na mesma linha, não entra na chave."""
    assert leitura(f"PIX: {CPF_DA_PESSOA} (conta da Fulana)")[0] == CPF_DA_PESSOA


def test_aviso_so_com_a_chave_de_digito_trocado_continua_recusado():
    """A foto lida por OCR não ganha confiança só por mudar de caminho."""
    assert leitura(f"PIX: {CPF_DV_ERRADO}") == ("", "")


def test_anexo_que_nao_e_aviso_nao_abre_janela():
    """A nota fiscal com a chave do fornecedor no rodapé não é aviso."""
    nf = {"filename": "NF 123", "tagName": "Nota Fiscal", "extension": ".pdf",
          "downloadUrl": URL_AVISO}
    textos = textos_do_aviso(f"PIX: {CPF_DA_PESSOA}")
    assert list(reembolso.janelas_do_aviso([nf], textos)) == []
    assert relatorio.chave_pix_do_aviso([nf], textos) == ""


def test_so_a_etiqueta_pagar_para_nao_basta_sem_a_frase_no_texto():
    """Sem a frase no texto, quem diz que o papel é o aviso é o NOME do arquivo
    — o mesmo lugar de onde sai o nome da pessoa. A etiqueta vem de lista fixa
    e vai para qualquer anexo do título, a nota fiscal inclusive."""
    nf = aviso(filename="NF 123", tag="PAGAR PARA")
    textos = textos_do_aviso(f"PIX: {CPF_DA_PESSOA}")
    assert list(reembolso.janelas_do_aviso([nf], textos)) == []


def test_recibo_renomeado_como_aviso_nao_empresta_o_cnpj_da_loja():
    """O papel do aviso sem a frase e sem rótulo de chave é outro documento —
    o recibo da loja renomeado, por exemplo. Ler o começo dele pegaria o CNPJ
    DA LOJA como chave e como documento de quem recebe o reembolso."""
    assert leitura(f"ESTACIONAMENTO MODELO\nCNPJ {CNPJ_DO_FORNECEDOR}\n"
                   "VALOR 60,00") == ("", "")


def test_cnpj_nunca_e_chave_nem_documento_de_quem_recebe_o_reembolso():
    """Sem a frase no texto, reembolso é para PESSOA: CNPJ depois do rótulo é
    a loja, e a leitura antiga (padrão de CNPJ antes do de CPF, numa janela de
    300) o declarava como chave e como documento, APTO e aceito na remessa."""
    assert leitura(f"PIX: {CNPJ_DO_FORNECEDOR}") == ("", "")
    assert leitura(f"PIX: {CNPJ_DO_FORNECEDOR_DIGITOS}") == ("", "")
    assert leitura(f"PIX CNPJ: {CNPJ_DO_FORNECEDOR}") == ("", "")


def test_cnpj_da_loja_perto_do_rotulo_nao_vira_chave():
    assert leitura(f"PAGAMENTO VIA PIX\nCNPJ {CNPJ_DO_FORNECEDOR}\n"
                   "VALOR 60,00") == ("", "")
    assert leitura(f"CHAVE PIX:\nCNPJ {CNPJ_DO_FORNECEDOR}") == ("", "")


def test_comprovante_de_pix_renomeado_nao_empresta_a_chave_de_quem_recebeu():
    """O comprovante traz a chave de QUEM RECEBEU o pagamento — a loja, ou
    qualquer um. Renomeado "PAGAR PARA", ele não diz para quem é o reembolso."""
    assert leitura("Comprovante de Pix\nPix enviado\n"
                   "Chave Pix: loja@exemplo.com\nValor R$ 60,00") == ("", "")
    assert leitura("Comprovante de transferência\n"
                   f"Chave Pix: {CPF_DE_OUTRA}\nValor pago R$ 60,00") == ("", "")


def test_danfe_renomeada_nao_abre_janela():
    """"CHAVE DE ACESSO" não é chave Pix, e os 44 dígitos dela têm pedaços
    com cara de celular. Nota fiscal renomeada é recusada inteira, até com
    uma chave Pix escrita no rodapé."""
    danfe = ("DANFE\nDOCUMENTO AUXILIAR DA NOTA FISCAL ELETRONICA\n"
             "CHAVE DE ACESSO\n5226 0911 2223 3300 0181 5500 1000 0012 3410 "
             "0001 2345")
    assert leitura(danfe) == ("", "")
    assert leitura(f"{danfe}\nPIX: {CELULAR}") == ("", "")
    files = [aviso()]
    assert list(reembolso.janelas_do_aviso(files, textos_do_aviso(danfe))) == []


def test_dois_rotulos_de_chave_nao_se_resolvem_no_chute():
    assert leitura(f"PIX: {CPF_DA_PESSOA}\nPIX: {CPF_DE_OUTRA}") == ("", "")


def test_com_a_frase_no_texto_a_janela_continua_depois_dela():
    """Nada muda para o aviso que escreve a frase: vale o que vem DEPOIS dela,
    e não um "PIX" que apareça antes."""
    assert leitura(f"LOJA PIX: {CPF_DE_OUTRA}\n"
                   f"PAGAR PARA FULANA\nCPF {CPF_DA_PESSOA}") == (
        CPF_DA_PESSOA, CPF_DA_PESSOA_DIGITOS)


# ==========================================================================
# 2. O favorecido que é a própria pessoa do aviso
# ==========================================================================
def test_o_nome_do_aviso_no_comeco_do_favorecido_e_a_pessoa():
    files = [aviso()]
    assert reembolso.pessoa_e_o_favorecido(files, PESSOA, CONTATOS)
    assert reembolso.pessoa_e_o_favorecido(files, "  fulana   de tal souza ",
                                           CONTATOS)
    assert reembolso.pessoa_e_o_favorecido(files, "FULANA",
                                           {"FULANA": CPF_DA_PESSOA_DIGITOS})


def test_acento_e_caixa_nao_separam_a_pessoa_do_favorecido():
    files = [aviso(filename="PAGAR PARA JOSÉ")]
    assert reembolso.pessoa_e_o_favorecido(
        files, "Jose Beltrano Exemplo",
        {"JOSE BELTRANO EXEMPLO": CPF_DA_PESSOA_DIGITOS})


def test_comeco_sem_fronteira_de_palavra_nao_e_a_pessoa():
    """"FULANA" está dentro de "FULANARIA", e não é o mesmo nome."""
    assert not reembolso.pessoa_e_o_favorecido(
        [aviso()], "Fulanaria Comercio",
        {"FULANARIA COMERCIO": CPF_DA_PESSOA_DIGITOS})


def test_fornecedor_nao_e_a_pessoa():
    assert not reembolso.pessoa_e_o_favorecido([aviso()], FORNECEDOR, CONTATOS)
    assert not reembolso.pessoa_e_o_favorecido([aviso()], "", CONTATOS)


def test_sem_aviso_nao_ha_pessoa_para_comparar():
    nf = {"filename": "NF 123", "tagName": "", "downloadUrl": URL_AVISO}
    assert not reembolso.pessoa_e_o_favorecido([nf], PESSOA, CONTATOS)


def test_favorecido_com_cnpj_no_cadastro_nao_e_a_pessoa():
    """"PAGAR PARA FULANA" num título da "Fulana Materiais Ltda": o nome bate,
    mas quem tem CNPJ é empresa — pagar a chave dela é pagar o fornecedor de
    novo, e não devolver o dinheiro a quem comprou."""
    contatos = {"FULANA MATERIAIS LTDA": CNPJ_DO_FORNECEDOR_DIGITOS}
    assert not reembolso.pessoa_e_o_favorecido(
        [aviso()], "Fulana Materiais Ltda", contatos)


def test_favorecido_fora_dos_contatos_nao_e_a_pessoa():
    """Falha FECHADA. Cadastro que não carregou (`listar_participantes` falhou
    e devolveu `{}`) ou nome ambíguo que saiu do mapa não provam nada — e sem
    prova a empresa de mesmo começo passaria por pessoa."""
    for contatos in ({}, None, {"OUTRA PESSOA": CPF_DE_OUTRA_DIGITOS}):
        assert not reembolso.pessoa_e_o_favorecido(
            [aviso()], "Fulana Materiais Ltda", contatos)
        assert not reembolso.pessoa_e_o_favorecido([aviso()], PESSOA, contatos)


def test_favorecido_com_cpf_que_nao_fecha_nao_e_a_pessoa():
    assert not reembolso.pessoa_e_o_favorecido(
        [aviso()], PESSOA, {"FULANA DE TAL SOUZA": "52998224726"})


def test_homonimos_se_desempatam_pelo_favorecido_confirmado_pelo_aviso():
    """O aviso diz o CPF, e ele é o do favorecido: aí o nome completo vale."""
    files = [aviso()]
    p = reembolso.identificar(files, textos_do_aviso(f"PIX: {CPF_DA_PESSOA}"),
                              CONTATOS, {}, CPF_DA_PESSOA, favorecido=PESSOA)
    assert p.resolvida
    assert (p.nome, p.documento, p.origem) == (
        "FULANA DE TAL SOUZA", CPF_DA_PESSOA_DIGITOS, reembolso.ORIGEM_ERP)


def test_favorecido_sem_confirmacao_do_aviso_nao_identifica_ninguem():
    """"PAGAR PARA FULANA" sem nada legível no aviso, num título da HOMÔNIMA:
    o começo do nome bate com as duas, e só o título diz qual. Sem o aviso
    confirmar, o nome completo do favorecido não decide para quem vai."""
    files = [aviso()]
    p = reembolso.identificar(files, textos_do_aviso(""), CONTATOS, {}, "",
                              favorecido=HOMONIMA)
    assert not p.resolvida


def test_aviso_que_confirma_outra_pessoa_nao_vira_o_favorecido():
    files = [aviso()]
    p = reembolso.identificar(files, textos_do_aviso(f"PIX: {CPF_DA_PESSOA}"),
                              CONTATOS, {}, CPF_DA_PESSOA, favorecido=HOMONIMA)
    assert p.documento != CPF_DE_OUTRA_DIGITOS


def test_favorecido_que_nao_e_a_pessoa_nao_desempata_homonimos():
    """No título do estacionamento o favorecido é a loja: o nome completo dela
    não diz nada sobre qual das duas Fulanas é a do aviso."""
    files = [aviso()]
    p = reembolso.identificar(files, textos_do_aviso(""), CONTATOS, {}, "",
                              favorecido=FORNECEDOR)
    assert not p.resolvida


# ==========================================================================
# 3. A linha inteira, do lançamento à remessa
# ==========================================================================
def lancamento(id_, favorecido, pix_do_lancamento):
    return {"id": id_, "tradePayableId": f"t{id_}", "paidTo": favorecido,
            "paidToBankAccount": pix_do_lancamento, "remainingValue": 60.0,
            "documentNumber": "REEMBOLSO FULANA ",
            "tradePayableAccount": {"name": CONTA},
            "costCentreDetails": [{"workName": "ESCRITORIO"}]}


def montar(itens, texto_do_aviso, contatos=CONTATOS, pix_reembolso=None):
    anexos = {f"t{i['id']}": [aviso(url=f"u{i['id']}")] for i in itens}
    textos = {f"u{i['id']}": texto_do_aviso for i in itens}
    res = relatorio.montar_registros(itens, anexos, {}, textos,
                                     participantes=contatos,
                                     pix_reembolso=pix_reembolso or {},
                                     cadastro_reembolso={})
    return {linha["id"]: linha for linha in res.contas[CONTA]}


def na_remessa(linhas, contatos=CONTATOS):
    c, = remessa_dia.preparar({CONTA: list(linhas.values())},
                              participantes=contatos)[CONTA]
    return c


def test_o_caso_do_dia_as_quatro_linhas_ganham_a_chave():
    """A forma do dia 14/09: duas linhas com a pessoa de favorecido, duas com o
    estacionamento; o aviso de todas é só `PIX: <cpf>`."""
    itens = [lancamento("1", FORNECEDOR, f"Pix CNPJ: {CNPJ_DO_FORNECEDOR}"),
             lancamento("2", PESSOA, CPF_DA_PESSOA),
             lancamento("3", FORNECEDOR, f"Pix CNPJ: {CNPJ_DO_FORNECEDOR}"),
             lancamento("4", PESSOA, CPF_DA_PESSOA)]
    linhas = montar(itens, f"PIX: {CPF_DA_PESSOA}")
    for id_, linha in linhas.items():
        assert linha["dados"] == CPF_DA_PESSOA, id_
        assert linha["status"] == "APTO* (reembolso)", id_
        assert linha["reembolso_documento"] == CPF_DA_PESSOA_DIGITOS, id_
        assert not linha["reembolso_impedimento"], id_
        assert "chave não cadastrada" not in linha["obs"], id_
    # o favorecido confirmado pelo aviso desempata o nome: sai o nome inteiro
    assert linhas["2"]["reembolso_nome"] == "FULANA DE TAL SOUZA"
    assert linhas["2"]["reembolso_origem"] == reembolso.ORIGEM_ERP
    assert "confere com a do lançamento" in linhas["2"]["obs"]
    # no título da loja só o aviso diz quem é
    assert linhas["1"]["reembolso_origem"] == reembolso.ORIGEM_AVISO


def test_o_caso_do_dia_sai_na_remessa_declarando_a_pessoa():
    linhas = montar([lancamento("9", PESSOA, CPF_DA_PESSOA)],
                    f"PIX: {CPF_DA_PESSOA}")
    c = na_remessa(linhas)
    assert c.pode, c.impedimento
    assert c.favorecido == "FULANA DE TAL SOUZA"
    assert c.documento_favorecido == CPF_DA_PESSOA_DIGITOS
    assert c.reembolso and not c.marcado            # continua pedindo o clique


def test_chave_so_do_lancamento_nao_e_apta_e_fica_visivel_na_obs():
    """O aviso é uma foto que o OCR não leu. A chave do lançamento é a do
    cadastro do FAVORECIDO — e só o título diz que ele é a pessoa do aviso.
    Sozinha ela não paga ninguém: fica na obs, a linha fica em ATENÇÃO e a
    remessa recusa."""
    linhas = montar([lancamento("9", PESSOA, CPF_DA_PESSOA)], "")
    linha = linhas["9"]
    assert linha["dados"] == ""
    assert linha["status"].startswith("ATENÇÃO")
    assert CPF_DA_PESSOA in linha["obs"]
    assert "não confirmada pelo aviso" in linha["obs"]
    assert not linha["reembolso_documento"]
    assert not na_remessa(linhas).pode


def test_homonima_no_titulo_sem_aviso_legivel_nao_recebe():
    """O achado da revisão: "PAGAR PARA FULANA" sem chave legível num título
    cuja favorecida é a OUTRA Fulana saía APTO*, com a chave e o CPF dela, e a
    remessa aceitava."""
    linhas = montar([lancamento("9", HOMONIMA, CPF_DE_OUTRA)], "")
    linha = linhas["9"]
    assert linha["dados"] == ""
    assert not linha["status"].startswith("APTO")
    assert not linha["reembolso_documento"]
    assert not linha["reembolso_nome"]
    c = na_remessa(linhas)
    assert not c.pode


def test_empresa_de_mesmo_comeco_com_contatos_vazio_nao_recebe():
    """O outro achado: sem Contatos (a carga falhou) a guarda do CNPJ sumia, e
    a "Fulana Materiais Ltda" saía APTO* com o CNPJ da empresa no HTML."""
    for contatos in ({}, {"OUTRA PESSOA": CPF_DE_OUTRA_DIGITOS}):
        linhas = montar([lancamento("9", "Fulana Materiais Ltda",
                                    f"Pix CNPJ: {CNPJ_DO_FORNECEDOR}")], "",
                        contatos=contatos)
        linha = linhas["9"]
        assert linha["dados"] == ""
        assert CNPJ_DO_FORNECEDOR not in linha["obs"]
        assert not linha["status"].startswith("APTO")
        assert not na_remessa(linhas, contatos).pode


def test_chave_cnpj_no_lancamento_nunca_e_chave_de_reembolso():
    linhas = montar([lancamento("9", PESSOA, f"Pix CNPJ: {CNPJ_DO_FORNECEDOR}")],
                    "")
    assert linhas["9"]["dados"] == ""
    assert CNPJ_DO_FORNECEDOR not in linhas["9"]["obs"]


def test_favorecido_fornecedor_nunca_empresta_a_chave_dele():
    """A regra que o ramo do reembolso sempre teve continua de pé: no título
    da loja, a chave do lançamento é a da LOJA."""
    linha = montar([lancamento("9", FORNECEDOR,
                               f"Pix CNPJ: {CNPJ_DO_FORNECEDOR}")], "")["9"]
    assert linha["dados"] == ""
    assert linha["status"] == "ATENÇÃO — sem dados de pgto"
    assert "chave não cadastrada" in linha["obs"]
    assert not linha["reembolso_documento"]


def test_aviso_e_lancamento_com_chaves_diferentes_viram_divergencia():
    linha = montar([lancamento("9", PESSOA, CPF_DE_OUTRA)],
                   f"PIX: {CPF_DA_PESSOA}")["9"]
    assert linha["status"] == "ATENÇÃO — chave do reembolso divergente"
    assert linha["dados"] == CPF_DA_PESSOA          # o aviso é o papel do dia
    assert CPF_DA_PESSOA in linha["obs"] and CPF_DE_OUTRA in linha["obs"]


def test_aviso_e_lancamento_com_a_mesma_chave_escrita_diferente_confirmam():
    linha = montar([lancamento("9", PESSOA, CPF_DA_PESSOA_DIGITOS)],
                   f"PIX: {CPF_DA_PESSOA}")["9"]
    assert linha["status"] == "APTO* (reembolso)"
    assert "próprio aviso" in linha["obs"]
    assert "confere com a do lançamento" in linha["obs"]


def test_cadastro_local_e_lancamento_com_chaves_diferentes_viram_divergencia():
    linha = montar([lancamento("9", PESSOA, CPF_DE_OUTRA)], "",
                   pix_reembolso={"FULANA": CPF_DA_PESSOA})["9"]
    assert linha["status"] == "ATENÇÃO — chave do reembolso divergente"
    assert CPF_DA_PESSOA in linha["obs"] and CPF_DE_OUTRA in linha["obs"]


def test_lancamento_sem_cara_de_chave_nao_vira_chave():
    """"VER COMENTÁRIO" no campo da chave é recado, não chave."""
    linha = montar([lancamento("9", PESSOA, "VER COMENTARIO")], "")["9"]
    assert linha["dados"] == ""
    assert "não confirmada pelo aviso" not in linha["obs"]


def test_reembolso_sem_pessoa_continua_impedido_na_remessa():
    """O que a remessa decide para quem NÃO se resolveu não muda."""
    linhas = montar([lancamento("9", FORNECEDOR,
                                f"Pix CNPJ: {CNPJ_DO_FORNECEDOR}")], "")
    c = na_remessa(linhas)
    assert not c.pode
    assert "CPF de quem recebe não foi encontrado" in c.impedimento
