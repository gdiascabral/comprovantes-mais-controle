"""Primeira leva (19/11/2026): saldo que falha nao derruba a leitura, as contas
guardadas da aba PF e o periodo "em aberto ate hoje". Nomes ficticios."""
from datetime import date

import pytest

from conciliacao.errors import ErpError
from conciliacao.models import Periodo
from tela_do_dia import decisoes as dc

HOJE = date(2026, 11, 19)          # quinta-feira


# ---------------------------------------------------------- tentar de novo
def test_a_segunda_tentativa_que_passa_devolve_o_valor():
    chamadas, falhas, sonos = [], [], []

    def acao():
        chamadas.append(1)
        if len(chamadas) == 1:
            raise ErpError("porta muda")
        return "saldos"

    assert dc.tentar_de_novo(acao, erros=(ErpError,), espera=60, dormir=sonos.append,
                             ao_falhar=lambda n, e: falhas.append((n, str(e)))) == "saldos"
    assert len(chamadas) == 2 and falhas == [(1, "porta muda")] and sum(sonos) == 60


def test_esgotadas_as_tentativas_sobe_o_ultimo_erro():
    n = []

    def acao():
        n.append(1)
        raise ErpError(f"falha {len(n)}")

    with pytest.raises(ErpError, match="falha 3"):
        dc.tentar_de_novo(acao, erros=(ErpError,), tentativas=3, dormir=lambda s: None)
    assert len(n) == 3


def test_erro_de_outro_tipo_nao_tenta_de_novo():
    n = []

    def acao():
        n.append(1)
        raise ValueError("cadastro estragado")

    with pytest.raises(ValueError):
        dc.tentar_de_novo(acao, erros=(ErpError,), dormir=lambda s: None)
    assert len(n) == 1


def test_parar_durante_a_espera_sobe_o_erro_sem_tentar_de_novo():
    n = []

    def acao():
        n.append(1)
        raise ErpError("porta muda")

    with pytest.raises(ErpError):
        dc.tentar_de_novo(acao, erros=(ErpError,), dormir=lambda s: None,
                          cancelar=lambda: True)
    assert len(n) == 1


def test_saldo_lido_em_nova_tentativa_manda_reler_os_lancamentos():
    aviso = dc.aviso_de_saldo_atrasado(190)
    assert "3 min" in aviso and "Reler só os lançamentos" in aviso
    assert "1 min" in dc.aviso_de_saldo_atrasado(5)


# ------------------------------------------------- contas guardadas (PF)
GUARDADAS = [{"id": "c1", "nome": "PESSOA FISICA - CONTA MODELO", "saldo": 10.0}]


def test_contas_lidas_valem_e_nao_sao_as_guardadas():
    lidas = [{"id": "c1", "nome": "PESSOA FISICA - CONTA MODELO", "saldo": 99.0}]
    assert dc.contas_ou_as_guardadas(lambda: lidas, GUARDADAS, erros=(ErpError,)) == (lidas, False)


def test_falha_do_erp_usa_as_guardadas_sem_saldo_velho():
    def ler():
        raise ErpError("porta muda")
    avisos = []
    contas, guardadas = dc.contas_ou_as_guardadas(ler, GUARDADAS, erros=(ErpError,),
                                                  log=avisos.append)
    assert guardadas and contas == [{"id": "c1", "nome": "PESSOA FISICA - CONTA MODELO",
                                     "saldo": None}]
    assert GUARDADAS[0]["saldo"] == 10.0 and avisos


def test_sem_lista_guardada_a_falha_sobe():
    def ler():
        raise ErpError("porta muda")
    with pytest.raises(ErpError):
        dc.contas_ou_as_guardadas(ler, [], erros=(ErpError,))


def test_erro_que_nao_e_do_erp_sobe_mesmo_com_lista_guardada():
    def ler():
        raise RuntimeError("acessos.json estragado")
    with pytest.raises(RuntimeError):
        dc.contas_ou_as_guardadas(ler, GUARDADAS, erros=(ErpError,))


# ------------------------------------------------- em aberto ate hoje
def test_em_aberto_vai_de_n_dias_atras_ate_hoje():
    assert dc.textos_em_aberto(HOJE, 7) == ("12/11/2026", "19/11/2026")


def test_em_aberto_respeita_o_maximo_do_buscar_e_o_minimo_de_um_dia():
    ini, fim = dc.textos_em_aberto(HOJE, 400)
    periodo = dc.periodo_da_busca(ini, fim, None, HOJE)        # nao levanta
    assert (periodo.fim - periodo.inicio).days + 1 == dc.MAXIMO_DE_DIAS
    assert dc.textos_em_aberto(HOJE, 0) == ("18/11/2026", "19/11/2026")
    assert dc.textos_em_aberto(HOJE, "lixo") == dc.textos_em_aberto(HOJE, dc.DIAS_EM_ABERTO)


def test_lembra_os_dias_so_de_quem_recuou_ate_hoje():
    assert dc.dias_a_lembrar(Periodo(date(2026, 11, 9), HOJE), HOJE) == 10
    assert dc.dias_a_lembrar(Periodo(HOJE, HOJE), HOJE) is None                  # a sugestao
    assert dc.dias_a_lembrar(Periodo(date(2026, 11, 9), date(2026, 11, 18)), HOJE) is None


def test_os_dias_ficam_guardados_e_arquivo_estragado_vira_o_padrao(tmp_path):
    assert dc.ler_dias_em_aberto(tmp_path) == dc.DIAS_EM_ABERTO
    dc.gravar_dias_em_aberto(tmp_path, 12)
    assert dc.ler_dias_em_aberto(tmp_path) == 12
    dc.gravar_dias_em_aberto(tmp_path, 20, chave="dias_em_aberto_pf")
    assert dc.ler_dias_em_aberto(tmp_path) == 12                    # uma nao apaga a outra
    assert dc.ler_dias_em_aberto(tmp_path, chave="dias_em_aberto_pf") == 20
    (tmp_path / dc.ARQ_PREFERENCIAS_DO_DIA).write_text("{quebrado", encoding="utf-8")
    assert dc.ler_dias_em_aberto(tmp_path) == dc.DIAS_EM_ABERTO
