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

Sem rede, sem tkinter, sem Excel. Nenhum dado real: nomes inventados e
documentos sintéticos que fecham o dígito verificador.
"""
from pagamentos_dia import reembolso, relatorio

CPF_DA_PESSOA = "529.982.247-25"
CPF_DA_PESSOA_DIGITOS = "52998224725"
#: O mesmo CPF com o último dígito trocado — o erro de OCR que paga outra pessoa.
CPF_DV_ERRADO = "529.982.247-26"
CPF_DE_OUTRA = "111.444.777-35"
CPF_DE_OUTRA_DIGITOS = "11144477735"
CNPJ_DO_FORNECEDOR = "11.222.333/0001-81"
CNPJ_DO_FORNECEDOR_DIGITOS = "11222333000181"

PESSOA = "Fulana de Tal Souza"
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


# ==========================================================================
# 1. O aviso que é só a chave
# ==========================================================================
def test_aviso_so_com_a_chave_tem_a_chave_lida():
    files = [aviso()]
    textos = textos_do_aviso(f"PIX: {CPF_DA_PESSOA}")
    assert relatorio.chave_pix_do_aviso(files, textos) == CPF_DA_PESSOA


def test_aviso_so_com_a_chave_tem_o_documento_lido():
    files = [aviso()]
    textos = textos_do_aviso(f"PIX: {CPF_DA_PESSOA}")
    assert reembolso.documento_do_aviso(files, textos) == CPF_DA_PESSOA_DIGITOS


def test_aviso_so_com_a_chave_de_digito_trocado_continua_recusado():
    """A foto lida por OCR não ganha confiança só por mudar de caminho."""
    files = [aviso()]
    textos = textos_do_aviso(f"PIX: {CPF_DV_ERRADO}")
    assert relatorio.chave_pix_do_aviso(files, textos) == ""
    assert reembolso.documento_do_aviso(files, textos) == ""


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
    files = [aviso()]
    textos = textos_do_aviso(f"ESTACIONAMENTO MODELO\nCNPJ {CNPJ_DO_FORNECEDOR}\n"
                             "VALOR 60,00")
    assert relatorio.chave_pix_do_aviso(files, textos) == ""
    assert reembolso.documento_do_aviso(files, textos) == ""


def test_com_a_frase_no_texto_a_janela_continua_depois_dela():
    """Nada muda para o aviso que escreve a frase: vale o que vem DEPOIS dela,
    e não um "PIX" que apareça antes."""
    files = [aviso()]
    textos = textos_do_aviso(f"LOJA PIX: {CPF_DE_OUTRA}\n"
                             f"PAGAR PARA FULANA\nCPF {CPF_DA_PESSOA}")
    assert reembolso.documento_do_aviso(files, textos) == CPF_DA_PESSOA_DIGITOS
    assert relatorio.chave_pix_do_aviso(files, textos) == CPF_DA_PESSOA
