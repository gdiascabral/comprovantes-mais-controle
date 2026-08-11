# -*- coding: utf-8 -*-
"""
Testes da conferência que roda antes de salvar o PDF do Mais Controle.

As duas regras nasceram de erro real: extrato da conta errada arquivado com o
nome certo, e PDF gerado antes de a paginação terminar — este último exibindo
"Saldo final" como se estivesse completo.
"""
import extrato_mc


def estado(conta="ALFA SPE - SICOOB", tem_mais=False, transacoes=10):
    return {"conta": conta, "tem_mais": tem_mais, "transacoes": transacoes,
            "carregando": False, "saldo_final": 123.45}


def test_estado_correto_passa():
    assert extrato_mc.conferir_antes_de_salvar(estado(), "ALFA SPE - SICOOB") == []


def test_acento_e_caixa_nao_reprovam():
    e = estado(conta="Morais Participações - MÃE - 55.694-7 - SICOOB")
    assert extrato_mc.conferir_antes_de_salvar(
        e, "MORAIS PARTICIPACOES - MAE - 55.694-7 - SICOOB") == []


def test_conta_trocada_e_recusada():
    p = extrato_mc.conferir_antes_de_salvar(estado(conta="BETA - INTER"),
                                            "ALFA SPE - SICOOB")
    assert p and "BETA - INTER" in p[0]


def test_paginacao_inacabada_e_recusada():
    p = extrato_mc.conferir_antes_de_salvar(estado(tem_mais=True), "ALFA SPE - SICOOB")
    assert any("paginação" in x for x in p)


def test_conta_certa_mas_paginacao_aberta_ainda_recusa():
    # O caso perigoso: tudo parece bem, o modal já mostra "Saldo final".
    p = extrato_mc.conferir_antes_de_salvar(estado(tem_mais=True), "ALFA SPE - SICOOB")
    assert len(p) == 1 and "paginação" in p[0]


def test_extrato_sem_conta_e_recusado():
    p = extrato_mc.conferir_antes_de_salvar(estado(conta=None), "ALFA SPE - SICOOB")
    assert any("não informa" in x for x in p)


def test_estado_ausente_e_recusado():
    assert extrato_mc.conferir_antes_de_salvar(None, "ALFA SPE - SICOOB")


def test_nome_de_arquivo_tira_caracteres_proibidos():
    assert "/" not in extrato_mc.nome_de_arquivo("ALFA / BETA: conta*")
    assert extrato_mc.nome_de_arquivo("") == "conta"
