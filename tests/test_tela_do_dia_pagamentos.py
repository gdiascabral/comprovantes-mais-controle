"""Pagamentos por conta: vão sair × bloqueados. Linhas fictícias."""
from decimal import Decimal as D

import pytest

from conciliacao.mapping import AccountMapping
from pagamentos_dia import confirmacao
from tela_do_dia import pagamentos as pg

MAPA = ("model_rows:\n"
        "- row: 8\n  label: Conta Alfa - Banco\n  uuid: uuid-alfa\n  erp_name: ALFA LTDA - BANCO\n"
        "- row: 9\n  label: Conta Beta - Banco\n  uuid: uuid-beta\n  erp_name: BETA LTDA - BANCO\n"
        "- row: 10\n  label: Conta Delta - Banco\n  exists_in_erp: false\n  erp_name: DELTA LTDA - BANCO\n"
        "ignored_erp_accounts:\n- CONTA DE AJUSTE\n")


@pytest.fixture
def mapa(tmp_path):
    caminho = tmp_path / "mapping.yaml"
    caminho.write_text(MAPA, encoding="utf-8")
    return AccountMapping.load(caminho)


class _JaEnviado:
    ja_enviado = "remessa nº 7"


def _ln(secao, ident, conta, valor, candidato=None, rejeitado=False):
    return confirmacao.Linha(secao=secao, id=ident, conta=conta, valor=valor,
                             favorecido=f"Fornecedor {ident}", tipo="Pix", dados="",
                             por_onde="", vencimento=None, oc="", centro_custo="",
                             descricao="", situacao="motivo ficticio", estado="ok",
                             olhar=False, candidato=candidato, envio_rejeitado=rejeitado)


def _grupos():
    alfa = "ALFA LTDA - BANCO"
    return [
        confirmacao.Grupo(alfa, entram=[_ln("entra", "A1", alfa, 100.1),
                                        _ln("entra", "A2", alfa, 50.0, candidato=_JaEnviado()),
                                        _ln("entra", "A3", alfa, 25.0, candidato=_JaEnviado(), rejeitado=True)],
                          nao_aptos=[_ln("nao_apto", "A4", alfa, 9.99)]),
        confirmacao.Grupo("GAMA SPE - BANCO", entram=[_ln("entra", "G1", "GAMA SPE - BANCO", 10.0)], nao_aptos=[]),
        confirmacao.Grupo("CONTA DE AJUSTE", entram=[_ln("entra", "X1", "CONTA DE AJUSTE", 1.0)], nao_aptos=[]),
    ]


def test_vai_sair_e_o_que_entra_marcado_e_bloqueado_o_resto(mapa):
    painel, _fora = pg.por_conta(_grupos(), mapa)
    alfa = painel[8]
    assert [p.id for p in alfa.vao_sair] == ["A1", "A3"]        # rejeitado volta a sair
    assert [p.id for p in alfa.bloqueados] == ["A2", "A4"]      # já enviado e não apto
    assert alfa.valor_bloqueado == D("59.99")


def test_a_pagar_e_decimal_exato(mapa):
    painel, _fora = pg.por_conta(_grupos(), mapa)
    assert painel[8].a_pagar == D("125.10") and painel[8].qtd_a_pagar == 2
    assert pg.totais_para_o_painel(painel) == {8: (D("125.10"), 2)}


def test_conta_fora_do_painel_aparece_com_o_motivo(mapa):
    _painel, fora = pg.por_conta(_grupos(), mapa)
    motivos = {c.rotulo: c.motivo_fora for c in fora}
    assert motivos["GAMA SPE - BANCO"] == pg.SEM_LINHA
    assert motivos["CONTA DE AJUSTE"] == pg.FORA_POR_CONFIGURACAO


def test_linha_do_painel_marcada_como_fora_do_erp_tem_motivo_proprio(mapa):
    delta = "DELTA LTDA - BANCO"
    grupos = [confirmacao.Grupo(delta, entram=[_ln("entra", "D1", delta, 7.0)], nao_aptos=[])]
    painel, fora = pg.por_conta(grupos, mapa)
    assert painel == {}
    assert [(c.rotulo, c.motivo_fora, c.linha) for c in fora] == [(delta, pg.LINHA_FORA_DO_ERP, None)]
    assert pg.LINHA_FORA_DO_ERP not in (pg.SEM_LINHA, pg.FORA_POR_CONFIGURACAO)
    assert fora[0].a_pagar == D("7.00")        # aparece, nunca some


def test_liberados_e_a_mao_somam_no_a_pagar(mapa):
    painel, _ = pg.por_conta(_grupos(), mapa)
    alfa = painel[8]
    alfa.a_mao.append(pg.Pagamento("M1", "ALFA LTDA - BANCO", "Fulano Ficticio", D("30.00"), "à mão", "ok"))
    assert alfa.a_pagar == D("155.10")


def test_ids_que_nao_saem_sao_so_os_ja_enviados():
    assert pg.ids_que_nao_saem(_grupos()) == {"A2"}
