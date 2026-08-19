# -*- coding: utf-8 -*-
"""Quem recebe o reembolso.

O aviso "PAGAR PARA <pessoa>" manda o dinheiro para quem NÃO é o favorecido do
lançamento, e o segmento B do CNAB carrega um só par nome/documento. O que se
testa aqui é a decisão que desfaz esse empate — e, principalmente, os casos em
que ela se RECUSA a decidir: quando não se sabe quem recebe, o certo é a linha
ficar de fora, não sair com o documento de alguém.

Sem rede, sem tkinter, sem Excel.

Nenhum dado real: o repositório é público. Os documentos abaixo são sintéticos,
escolhidos por fecharem o dígito verificador, e os nomes são inventados.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pagamentos_dia"))

import reembolso                                     # noqa: E402

CPF_A = "52998224725"
CPF_B = "11144477735"
CNPJ_A = "11222333000181"
#: Onze dígitos que NÃO fecham o DV — é telefone, não CPF. É o caso que separa
#: "achei um documento" de "achei onze dígitos".
NAO_E_CPF = "62999998888"

URL = "https://exemplo/anexo/1"


def anexo(filename, url=URL, tag=""):
    return {"filename": filename, "tagName": tag, "downloadUrl": url}


def aviso(texto, filename="PAGAR PARA FULANO DE TAL.pdf"):
    """Um anexo de reembolso e o texto que se leu dele."""
    return [anexo(filename)], {URL: texto}


# --------------------------------------------------------- nome no rótulo
def test_nome_sai_do_rotulo():
    assert reembolso.nome_do_aviso([anexo("PAGAR PARA FULANO DE TAL.pdf")]) \
        == "fulano de tal"


def test_nome_com_separador_e_sem_extensao():
    for rotulo in ("pagar_para_fulano de tal.jpg", "PAGAR PARA - FULANO DE TAL",
                   "Pagar Para: Fulano de Tal.png"):
        assert reembolso.nome_do_aviso([anexo(rotulo)]) == "fulano de tal", rotulo


def test_anexo_que_nao_e_aviso_nao_tem_nome():
    assert reembolso.nome_do_aviso([anexo("BOLETO 123.pdf")]) == ""
    assert reembolso.nome_do_aviso([]) == ""


# ------------------------------------------------ documento dentro do aviso
def test_documento_e_lido_na_janela_do_aviso():
    files, textos = aviso(f"PAGAR PARA FULANO DE TAL\nCPF {CPF_A}\nvalor 630,00")
    assert reembolso.documento_do_aviso(files, textos) == CPF_A


def test_documento_pontuado_tambem_e_lido():
    bonito = f"{CPF_A[:3]}.{CPF_A[3:6]}.{CPF_A[6:9]}-{CPF_A[9:]}"
    files, textos = aviso(f"PAGAR PARA FULANO DE TAL\nCPF {bonito}")
    assert reembolso.documento_do_aviso(files, textos) == CPF_A


def test_documento_fora_da_janela_nao_entra():
    """O aviso traz o CNPJ da empresa e o valor; varrer o papel inteiro
    pegaria o primeiro número parecido, não o certo."""
    longe = "x" * (reembolso.TAMANHO_DA_JANELA + 20)
    files, textos = aviso(f"PAGAR PARA FULANO DE TAL{longe}CPF {CPF_A}")
    assert reembolso.documento_do_aviso(files, textos) == ""


def test_onze_digitos_que_nao_fecham_o_dv_nao_sao_cpf():
    files, textos = aviso(f"PAGAR PARA FULANO DE TAL\ncelular {NAO_E_CPF}")
    assert reembolso.documento_do_aviso(files, textos) == ""


def test_dois_documentos_sem_rotulo_nao_se_resolvem_no_chute():
    """O CPF da pessoa e o CNPJ da empresa, os dois válidos, sem dizer qual é
    qual. Escolher um é escolher para quem o dinheiro vai."""
    files, textos = aviso(f"PAGAR PARA FULANO DE TAL\n{CPF_A}\n{CNPJ_A}")
    assert reembolso.documento_do_aviso(files, textos) == ""


def test_o_rotulo_cpf_desempata_dois_documentos():
    files, textos = aviso(
        f"PAGAR PARA FULANO DE TAL\nempresa {CNPJ_A}\nCPF: {CPF_A}")
    assert reembolso.documento_do_aviso(files, textos) == CPF_A


def test_documentos_vizinhos_nao_se_perdem_numa_captura_so():
    """Sem separador entre eles, um regex ganancioso juntaria os dois num
    número que não fecha DV nenhum — e os dois sumiriam calados."""
    files, textos = aviso(f"PAGAR PARA FULANO DE TAL\nCPF: {CPF_A} {CNPJ_A}")
    assert reembolso.documento_do_aviso(files, textos) == CPF_A


# ------------------------------------------------------- cadastro local
def escrever(tmp_path, conteudo):
    (tmp_path / reembolso.ARQ_REEMBOLSO).write_text(conteudo, encoding="utf-8")
    return tmp_path


def test_formato_antigo_continua_sendo_lido(tmp_path):
    """`{nome: chave}` já está em uso na máquina de quem trabalha."""
    base = escrever(tmp_path, '{"FULANO DE TAL": "fulano@exemplo.com"}')
    cadastro = reembolso.carregar(base)
    assert cadastro["fulano de tal"]["chave"] == "fulano@exemplo.com"
    assert cadastro["fulano de tal"]["documento"] == ""
    assert reembolso.chaves(cadastro) == {"fulano de tal": "fulano@exemplo.com"}


def test_formato_novo_traz_nome_e_documento(tmp_path):
    base = escrever(tmp_path, '{"FULANO": {"nome": "Fulano de Tal", '
                              f'"documento": "{CPF_A}", "chave": "(62) 99999-8888"}}}}')
    cadastro = reembolso.carregar(base)
    assert cadastro["fulano"]["nome"] == "FULANO DE TAL"
    assert cadastro["fulano"]["documento"] == CPF_A


def test_documento_invalido_no_cadastro_nao_vira_documento(tmp_path):
    """Digitar errado no arquivo local não pode virar dinheiro saindo."""
    base = escrever(tmp_path, f'{{"FULANO": {{"documento": "{NAO_E_CPF}"}}}}')
    assert reembolso.carregar(base)["fulano"]["documento"] == ""


def test_cadastro_ausente_ou_ilegivel_nao_derruba_o_dia(tmp_path):
    assert reembolso.carregar(tmp_path) == {}
    assert reembolso.carregar(escrever(tmp_path, "{isto nao e json")) == {}


# ------------------------------------------------------------- identificar
def identificar(texto="PAGAR PARA FULANO DE TAL", participantes=None,
                cadastro=None, chave="", filename="PAGAR PARA FULANO DE TAL.pdf"):
    files, textos = aviso(texto, filename)
    return reembolso.identificar(files, textos, participantes, cadastro, chave)


def test_sem_nome_no_rotulo_nao_ha_favorecido_a_declarar():
    p = reembolso.identificar([anexo("BOLETO.pdf")], {})
    assert p.impedimento == reembolso.MOTIVO_SEM_NOME
    assert not p.resolvida


def test_sem_documento_em_lugar_nenhum_fica_de_fora():
    p = identificar()
    assert not p.resolvida
    assert "FULANO DE TAL" in p.impedimento
    assert reembolso.ARQ_REEMBOLSO in p.impedimento


def test_documento_vem_dos_contatos_do_erp():
    p = identificar(participantes={"FULANO DE TAL": CPF_A})
    assert p.resolvida
    assert (p.nome, p.documento, p.origem) == ("FULANO DE TAL", CPF_A,
                                               reembolso.ORIGEM_ERP)


def test_documento_vem_do_cadastro_local():
    p = identificar(cadastro={"fulano de tal": {"nome": "FULANO DE TAL",
                                                "documento": CPF_A, "chave": ""}})
    assert p.resolvida and p.origem == reembolso.ORIGEM_CADASTRO_LOCAL


def test_documento_vem_do_proprio_aviso():
    p = identificar(texto=f"PAGAR PARA FULANO DE TAL\nCPF {CPF_A}")
    assert p.resolvida
    assert (p.nome, p.documento, p.origem) == ("FULANO DE TAL", CPF_A,
                                               reembolso.ORIGEM_AVISO)


def test_o_cadastro_local_passa_na_frente_do_erp():
    """Concordando, ganha a fonte mais declarada — é ela que fica na tela."""
    p = identificar(participantes={"FULANO DE TAL": CPF_A},
                    cadastro={"fulano de tal": {"nome": "FULANO DE TAL",
                                                "documento": CPF_A, "chave": ""}})
    assert p.origem == reembolso.ORIGEM_CADASTRO_LOCAL


def test_fontes_que_discordam_seguram_o_pagamento():
    p = identificar(texto=f"PAGAR PARA FULANO DE TAL\nCPF {CPF_B}",
                    participantes={"FULANO DE TAL": CPF_A})
    assert not p.resolvida
    assert "DIFERENTES" in p.impedimento


def test_nome_ambiguo_no_erp_nao_resolve():
    """"FULANO DE TAL" está dentro de dois cadastros, com dois CPFs. São duas
    pessoas — e aqui a dúvida não se resolve por chute."""
    p = identificar(participantes={"FULANO DE TAL SOUZA": CPF_A,
                                   "FULANO DE TAL LIMA": CPF_B})
    assert not p.resolvida


def test_nome_incompleto_com_um_so_cadastro_possivel_resolve():
    p = identificar(participantes={"FULANO DE TAL SOUZA": CPF_A,
                                   "OUTRA PESSOA": CPF_B})
    assert p.resolvida
    assert (p.nome, p.documento) == ("FULANO DE TAL SOUZA", CPF_A)


def test_a_chave_que_e_documento_de_outro_segura_o_pagamento():
    """O dinheiro iria para o dono da chave; o arquivo declararia esta pessoa.

    A chave não é FONTE do documento — seria uma fonte que se confirma
    sozinha. Ela é conferente, e este é o caso em que ela contradiz o resto.
    """
    p = identificar(participantes={"FULANO DE TAL": CPF_A}, chave=CPF_B)
    assert not p.resolvida
    assert p.impedimento == reembolso.MOTIVO_CHAVE_DE_OUTRO.format(
        nome="FULANO DE TAL")


def test_a_chave_que_e_o_mesmo_documento_confirma():
    p = identificar(participantes={"FULANO DE TAL": CPF_A}, chave=CPF_A)
    assert p.resolvida and p.documento == CPF_A


def test_chave_que_nao_e_documento_nao_atrapalha():
    """Celular, e-mail e aleatória não têm o que conferir — e não impedem."""
    for chave in ("(62) 99999-8888", "fulano@exemplo.com", NAO_E_CPF):
        p = identificar(participantes={"FULANO DE TAL": CPF_A}, chave=chave)
        assert p.resolvida, chave
