"""As tabelas cabem a 1280x800 com o Windows a 125% e o menu aberto.

O Treeview não encolhe coluna para caber: ele CORTA as da direita (a
SITUAÇÃO do "Por conta" do Controle de aportes sumia). A medida é a soma das
larguras a 100% (o `estilo_tabela` escala todas juntas, e a fonte junto, então
a conta vale em qualquer escala). Sem janela: só importa os módulos.
"""
from datetime import date
from types import SimpleNamespace

import pytest

from tela_do_dia import controle_aportes as ca
from tela_do_dia.controle_frame import ControleAportesFrame as Controle
from tela_do_dia.frame import TelaDoDiaFrame as Dia

#: Largura útil de uma tabela a 100%: 1280/1,25 = 1024, menos o menu (232),
#: as margens da aba (2x20), a folga do cartão (2x16) e as duas barras de
#: rolagem. Medido na galeria de 22/10/2026: as tabelas de 680 cabiam.
ORCAMENTO = 680


def _soma(colunas, arvore_com=0):
    return arvore_com + sum(c[2] for c in colunas)


@pytest.mark.parametrize("nome,colunas,conta", [
    ("controle: por conta", Controle.COLS_CONTAS, Controle.LARGURA_CONTA),
    ("controle: sem dono", Controle.COLS_SEM_DONO, 0),
    ("controle: apontados", Controle.COLS_APONTADOS, 0),
    ("dia: saldos", Dia.COLS_SALDOS, 0),
    ("dia: pagamentos", Dia.COLS_PAG, Dia.LARGURA_CONTA),
    ("dia: aportes", Dia.COLS_APT, Dia.LARGURA_CONTA),
    ("dia: à mão", Dia.COLS_MAO, 0),
])
def test_tabela_cabe_a_1280(nome, colunas, conta):
    assert _soma(colunas, conta) <= ORCAMENTO, nome


def _ap(sem_dono=0, alertas=0, erro=""):
    return SimpleNamespace(erro=erro, conta=SimpleNamespace(abertura=date(2026, 1, 1)),
                           sem_dono=[object()] * sem_dono, alertas=["x"] * alertas)


#: Letras que cabem na SITUAÇÃO do "Por conta" (145 px a 100%, ~5,5 px por letra).
MAX_SITUACAO = 26


@pytest.mark.parametrize("ap", [_ap(), _ap(sem_dono=12), _ap(alertas=3),
                                _ap(sem_dono=12, alertas=30)])
def test_situacao_da_conta_cabe_na_coluna(ap):
    assert len(ca.situacao_da_conta(ap)) <= MAX_SITUACAO


def test_situacao_da_conta_diz_o_que_ha_e_a_abertura_quando_nao_ha_nada():
    assert ca.situacao_da_conta(_ap()) == "desde 01/01/2026"
    assert ca.situacao_da_conta(_ap(sem_dono=2, alertas=1)) == "2 sem dono · 1 alerta(s)"
    assert ca.situacao_da_conta(_ap(erro="boom")) == "erro: boom"


def test_situacao_do_aportador_cabe_na_coluna():
    linha = SimpleNamespace(diferenca=__import__("decimal").Decimal("1234567.89"))
    assert ca.situacao_do_aportador(linha) == "deve R$ 1.234.567,89"
    assert len(ca.situacao_do_aportador(linha)) <= MAX_SITUACAO
