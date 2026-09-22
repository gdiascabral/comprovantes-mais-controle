# -*- coding: utf-8 -*-
"""O bloco de guias da aba Acessórias.

Usa a fixture `raiz` do conftest (UM `Tk()` para a sessão inteira): módulo que
cria e destrói o próprio faz os seguintes pularem com "sem display".
"""
from datetime import date
from decimal import Decimal

import pytest

from guias import painel as mod
from guias.modelos import ALTERAR, CRIAR, DECIDIR, JA_LANCADO, Decisao, Guia


def _decisao(acao, **campos):
    guia = Guia(vip_id="701", empresa="EMPRESA UM", desc="HONORARIO",
                anx_id=campos.pop("anx_id", "111"), competencia="2026-09",
                valor=Decimal("641.31"), vencimento=date(2026, 9, 12),
                documento="DOC-1")
    return Decisao(guia=guia, acao=acao, categoria="Honorários", **campos)


@pytest.fixture
def bloco(raiz):
    p = mod.GuiasPainel(raiz, aba=None, anx=None)
    yield p
    p.destroy()


def test_as_secoes_aparecem_na_ordem_do_trabalho(bloco):
    """Primeiro o que vai ser gravado, depois o que precisa de decisão, por
    último o que já está pronto."""
    assert mod.SECOES == (ALTERAR, CRIAR, DECIDIR, JA_LANCADO)


def test_mostrar_separa_as_linhas_por_secao(bloco):
    bloco.mostrar([_decisao(ALTERAR, anx_id="1"),
                   _decisao(CRIAR, anx_id="2"),
                   _decisao(DECIDIR, anx_id="3", motivo="não conheço")])

    assert bloco.quantas(ALTERAR) == 1
    assert bloco.quantas(CRIAR) == 1
    assert bloco.quantas(DECIDIR) == 1
    assert bloco.quantas(JA_LANCADO) == 0


def test_alterar_e_criar_nascem_marcados_e_decidir_nao(bloco):
    """Decidir não pode ser lançado por distração: nasce desmarcado e o botão
    nem o considera."""
    bloco.mostrar([_decisao(ALTERAR, anx_id="1"),
                   _decisao(CRIAR, anx_id="2"),
                   _decisao(DECIDIR, anx_id="3"),
                   _decisao(JA_LANCADO, anx_id="4")])

    marcadas = [d.acao for d in bloco.marcadas()]
    assert sorted(marcadas) == sorted([ALTERAR, CRIAR])


def test_desmarcar_uma_linha_tira_ela_do_lancamento(bloco):
    bloco.mostrar([_decisao(ALTERAR, anx_id="1"), _decisao(ALTERAR, anx_id="2")])
    iid = bloco.linhas_de(ALTERAR)[0]

    bloco.alternar(iid)

    assert len(bloco.marcadas()) == 1


def test_aviso_de_divergencia_aparece_na_linha(bloco):
    """Review Focus 2: a divergência de valor tem de estar visível."""
    bloco.mostrar([_decisao(ALTERAR, anx_id="1",
                            aviso="a parcela está 620,00 e a guia diz 641,31")])
    iid = bloco.linhas_de(ALTERAR)[0]

    assert "620,00" in bloco.texto_da_linha(iid)


def test_lancar_sem_nada_marcado_nao_chama_o_executor(bloco):
    bloco.mostrar([_decisao(DECIDIR, anx_id="1")])
    chamadas = []
    bloco._executar = lambda *a, **k: chamadas.append(a)

    bloco.lancar()

    assert chamadas == []


def test_o_mes_padrao_e_o_ATUAL(bloco):
    """O bloco de envio de conciliações abre no mês ANTERIOR (fechamento); este
    abre no mês corrente, que é onde estão as guias a pagar."""
    hoje = date.today()

    assert bloco.periodo == (hoje.year, hoje.month)


def test_linha_com_obra_sugerida_e_marcada_para_o_dono_olhar(bloco):
    """Sugestão não é confirmação: a linha diz que aquilo é palpite."""
    bloco.mostrar([_decisao(CRIAR, anx_id="1", obra_id="obra-2",
                            obra_sugerida=True)])
    iid = bloco.linhas_de(CRIAR)[0]

    assert "?" in bloco.texto_da_linha(iid)


def test_editar_a_obra_troca_a_decisao_e_tira_a_marca_de_palpite(bloco):
    bloco.mostrar([_decisao(CRIAR, anx_id="1", obra_id="obra-2",
                            obra_sugerida=True)])
    iid = bloco.linhas_de(CRIAR)[0]

    bloco.editar(iid, "obra", "obra-7")

    assert bloco.decisoes[iid].obra_id == "obra-7"
    assert bloco.decisoes[iid].obra_sugerida is False
    assert "?" not in bloco.texto_da_linha(iid)


def test_duas_obras_de_mesmo_nome_nao_colapsam_na_escolha(bloco):
    """A obra decide a conta que paga. Duas obras homônimas guardadas num
    dicionário por nome deixariam só a última, e a escolha apontaria para a
    outra em silêncio."""
    bloco.obras = [{"id": "obra-1", "name": "CONDOMINIO IGUAL"},
                   {"id": "obra-2", "name": "CONDOMINIO IGUAL"},
                   {"id": "obra-3", "name": "CONDOMINIO UNICO"}]

    opcoes = bloco._opcoes_de("obra")

    assert sorted(opcoes.values()) == ["obra-1", "obra-2", "obra-3"]
    assert "CONDOMINIO UNICO" in opcoes


def test_editar_a_categoria_troca_a_decisao(bloco):
    bloco.mostrar([_decisao(ALTERAR, anx_id="1")])
    iid = bloco.linhas_de(ALTERAR)[0]

    bloco.editar(iid, "categoria", "Outra Categoria")

    assert bloco.decisoes[iid].categoria == "Outra Categoria"
    assert "Outra Categoria" in bloco.texto_da_linha(iid)


def test_editar_campo_que_nao_se_edita_nao_muda_nada(bloco):
    bloco.mostrar([_decisao(ALTERAR, anx_id="1")])
    iid = bloco.linhas_de(ALTERAR)[0]
    antes = bloco.texto_da_linha(iid)

    bloco.editar(iid, "valor", "999,99")

    assert bloco.texto_da_linha(iid) == antes


def test_abrir_pdf_de_linha_sem_pdf_nao_explode(bloco):
    """Linha de "você decide" costuma ser justamente a que não tem PDF."""
    bloco.mostrar([_decisao(DECIDIR, anx_id="1")])
    iid = bloco.linhas_de(DECIDIR)[0]

    bloco.abrir_pdf(iid)          # não levanta


def test_parar_pede_parada_sem_derrubar_a_tela(bloco):
    bloco.parar()                 # sem rodada em pé: não faz nada e não quebra
