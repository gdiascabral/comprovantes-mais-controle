# -*- coding: utf-8 -*-
"""O motor do Inter, na parte que não depende do banco estar no ar.

O que dá para provar aqui é o que o script de terminal NÃO tinha: as recusas
que acontecem antes do QR, a regra de parada e a separação de perfis. O
caminho de navegador não tem dublê de propósito — um dublê do site do Inter
provaria só que o dublê concorda com o código, e o que precisa concordar é o
banco. A prova daquele lado é a rodada com QR de verdade.
"""
import sys
from pathlib import Path

import pytest

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))

from baixar_comprovantes import inter_baixar as inter  # noqa: E402


# ------------------------------------------------------------- o período

def test_periodo_de_tras_para_frente_e_recusado_antes_do_QR():
    """Recusar aqui, e não na tela: o erro só apareceria depois de a pessoa
    ter ido buscar o celular e escaneado."""
    with pytest.raises(inter.InterFalhou):
        inter.conferir_periodo("30/08/2026", "01/08/2026")


def test_periodo_maior_que_noventa_dias_e_recusado():
    """O Inter só consulta 90 dias. Pedir mais devolve tela vazia — que se lê
    como "não houve pagamento nenhum", e é a leitura errada."""
    with pytest.raises(inter.InterFalhou) as e:
        inter.conferir_periodo("01/01/2026", "30/08/2026")
    assert "90" in str(e.value)


@pytest.mark.parametrize("inicio,fim", [("", "30/08/2026"),
                                        ("30-08-2026", "31/08/2026"),
                                        ("31/02/2026", "01/03/2026")])
def test_data_que_nao_e_data_e_recusada(inicio, fim):
    with pytest.raises(inter.InterFalhou):
        inter.conferir_periodo(inicio, fim)


def test_periodo_bom_volta_normalizado():
    assert inter.conferir_periodo(" 01/08/2026 ", "30/08/2026") == (
        "01/08/2026", "30/08/2026")


def test_o_chip_da_tela_e_conferido_contra_o_que_se_pediu():
    """A única confirmação que o Inter dá é esse texto. Sem conferi-lo, dava
    para baixar o mês errado inteiro achando que se filtrou."""
    assert inter.periodo_confere("01/08/2026 - 30/08/2026",
                                 "01/08/2026", "30/08/2026")
    assert not inter.periodo_confere("01/07/2026 - 30/08/2026",
                                     "01/08/2026", "30/08/2026")
    assert not inter.periodo_confere("", "01/08/2026", "30/08/2026")


# --------------------------------------------------------- nome repetido

def test_comprovante_de_nome_repetido_nao_sobrescreve(tmp_path):
    """Dois Pix do mesmo valor, para o mesmo favorecido, no mesmo dia: o Inter
    sugere o MESMO nome para os dois. Sobrescrever apagaria o comprovante de
    um pagamento que aconteceu."""
    (tmp_path / "comprovante.pdf").write_bytes(b"o primeiro")
    segundo = inter.nome_livre(tmp_path, "comprovante.pdf")
    assert segundo.name == "comprovante_1.pdf"
    segundo.write_bytes(b"o segundo")
    assert inter.nome_livre(tmp_path, "comprovante.pdf").name == "comprovante_2.pdf"


# ----------------------------------------------------------- quando parar

def test_falhas_seguidas_param_o_lote():
    """Cinco seguidas é o site dizendo alguma coisa — bloqueio, mudança de
    tela, sessão caindo. Insistir a partir daí piora o bloqueio."""
    assert inter.deve_parar([10, 11, 12, 13, 14], 14)


def test_falha_esparsa_nao_para_nada():
    """Comprovante problemático é normal, e o lote tem de seguir."""
    assert not inter.deve_parar([1, 10, 11, 12, 14], 14)
    assert not inter.deve_parar([3], 3)
    assert not inter.deve_parar([], 0)


# ------------------------------------------------------ um perfil por conta

def test_cada_conta_tem_o_seu_perfil_de_chrome():
    """No Inter cada conta é um login. Um perfil só faria a segunda conta
    entrar como a primeira — e baixar os comprovantes da errada, sem nada na
    tela dizendo isso."""
    a = inter.pasta_do_perfil("MORAIS ENG 50022")
    b = inter.pasta_do_perfil("OUTRA EMPRESA 90011")
    assert a != b
    assert a.name.startswith(".chrome_profile_inter_")


def test_nome_de_conta_com_barra_nao_vira_subpasta():
    """`/` e `\\` num nome de conta criariam pasta dentro de pasta — e o perfil
    do Chrome nasceria no lugar errado."""
    p = inter.pasta_do_perfil("MORAIS ENG / 50022 \\ PIX")
    assert "/" not in p.name and "\\" not in p.name


def test_conta_sem_nome_ainda_tem_perfil():
    assert inter.pasta_do_perfil("").name.endswith("conta")


# ------------------------------------------------------------ o desfecho

def test_sem_lancamentos_nao_e_falha():
    """Segunda-feira sem Pix é um dia normal. Era o caso que o script antigo
    lia como "login não concluído", depois de 60 s parado."""
    r = inter.Resultado(conta="X", total_na_tela=0)
    assert r.ok
    assert "sem lançamentos" in r.resumo()


def test_o_resumo_conta_o_que_deu_e_o_que_faltou(tmp_path):
    r = inter.Resultado(conta="X", total_na_tela=10,
                        baixados=[tmp_path / f"{i}.pdf" for i in range(8)],
                        falhas=[3, 7])
    assert r.ok and r.quantos == 8
    assert "8 de 10" in r.resumo() and "2 falharam" in r.resumo()


def test_motivo_preenchido_e_o_que_a_tela_mostra():
    r = inter.Resultado(conta="X", motivo="não consegui ligar o filtro 'Saída'")
    assert not r.ok
    assert r.resumo() == "não consegui ligar o filtro 'Saída'"


def test_a_marca_de_tela_e_por_conteudo_e_nao_exata():
    """Basta UMA marca: o Inter troca rótulo sem avisar, e exigir todas faria
    uma palavra nova derrubar o motor."""
    assert inter.tela_diz("Extrato de Pix — Saída", inter.MARCAS_DE_EXTRATO)
    assert not inter.tela_diz("carregando...", inter.MARCAS_DE_EXTRATO)
    assert inter.tela_diz("Acesse sua conta com o QR Code",
                          inter.MARCAS_DE_LOGIN)
