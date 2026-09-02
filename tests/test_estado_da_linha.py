# -*- coding: utf-8 -*-
"""`widgets.estado_de` — o de-para entre o estado escrito em português e a
tag da linha ('ok'/'atencao'/'erro'/'info').

Até 02/09/2026 ela devolvia "info" para QUALQUER texto: `util.norm` põe em
MAIÚSCULAS e as chaves de `ESTADOS` são minúsculas, então "rejeitado" nunca
estava em "REJEITADO". A regra "nas tabelas, só atenção e erro se pintam"
estava escrita, medida e testada em `test_visual.py` — e nenhuma linha de
tabela nenhuma ficava âmbar ou vermelha, porque o casamento do estado
falhava um passo antes da cor.

Os casos usam os textos que as telas ESCREVEM de verdade (o relatório da
Remessa, o rótulo do retorno do banco, o `atividade.jsonl`), não as chaves
do dicionário: é para a tabela ficar colorida sem nenhuma aba precisar
passar a escrever "erro" no lugar de "REJEITADO".

Os testes puros não abrem janela. O único que abre usa a `raiz` do conftest
e pula onde não há display.
"""
import pytest

import widgets


# ------------------------------------------------------------ por família
# Um bloco por tag, cada um com as chaves do dicionário E os textos reais.

VERDE = [
    "APTO (autorizado)",             # relatório da Remessa
    "APTO* (reembolso)",             # idem, o caso especial
    "JÁ PAGO em 12/08/2026",         # idem, com a data atrás
    "PAGO",                          # rótulo do retorno do banco
    "apto", "completa", "baixado", "anexado", "ok", "Conferido",
]

AMBAR = [
    "ATENÇÃO — sem anexo",           # relatório da Remessa
    "ATENÇÃO — valor do boleto diverge",
    "ATENÇÃO — documento não bate",
    "em dúvida", "duvida", "Baixando…", "parcial", "SEM PDF", "aguardando",
    "atencao",                       # o que o atividade.jsonl grava
]

VERMELHO = [
    "REJEITADO",                     # rótulo do retorno do banco
    "erro",                          # o que o atividade.jsonl grava
    "Falhou", "FALTA", "SEM ANEXO",
]

AZUL = [
    # "Aguarda assinatura" é o estado NORMAL logo depois de enviar: o master
    # assina à parte, e treze linhas âmbar pareceriam falha — é o susto que
    # o aviso da própria tela de retorno existe para evitar.
    "AGUARDA ASSINATURA",
    "SEM RESPOSTA",
    "fora", "fica de fora", "na fila", "pulado", "info",
]


@pytest.mark.parametrize("texto", VERDE)
def test_apto_e_pago_dao_ok(texto):
    assert widgets.estado_de(texto) == "ok"


@pytest.mark.parametrize("texto", AMBAR)
def test_duvida_e_atencao_dao_atencao(texto):
    assert widgets.estado_de(texto) == "atencao"


@pytest.mark.parametrize("texto", VERMELHO)
def test_rejeitado_e_erro_dao_erro(texto):
    assert widgets.estado_de(texto) == "erro"


@pytest.mark.parametrize("texto", AZUL)
def test_fora_e_na_fila_dao_info(texto):
    assert widgets.estado_de(texto) == "info"


@pytest.mark.parametrize("texto", ["", None, "   "])
def test_vazio_e_informacao(texto):
    assert widgets.estado_de(texto) == "info"


# ------------------------------------------------------------- a regressão
def test_a_caixa_do_texto_nao_muda_o_estado():
    """O defeito exato: cada chave do dicionário tem de casar em MAIÚSCULAS,
    em minúsculas e como está — a tela escreve como quiser."""
    for chave, esperado in widgets.ESTADOS.items():
        assert widgets.estado_de(chave) == esperado, chave
        assert widgets.estado_de(chave.upper()) == esperado, chave.upper()
        assert widgets.estado_de(chave.title()) == esperado, chave.title()


@pytest.mark.parametrize("texto", ["Divergência de valor", "CONFERIR o boleto",
                                   "3 pagamentos para conferir"])
def test_as_palavras_do_meio_da_frase_tambem_em_maiusculas(texto):
    assert widgets.estado_de(texto) == "atencao"


def test_o_estado_escrito_primeiro_manda():
    """"ATENÇÃO — sem anexo" é atenção com o motivo atrás. "sem anexo" sozinho
    é erro. Escolher só pelo pedaço mais longo pintava a primeira de vermelho
    — e a Remessa trata ATENÇÃO como "olhe antes de marcar", não como falha."""
    assert widgets.estado_de("ATENÇÃO — sem anexo") == "atencao"
    assert widgets.estado_de("sem anexo") == "erro"
    assert widgets.estado_de("SEM ANEXO — falta o comprovante") == "erro"


def test_todo_estado_tem_marca():
    """Cor não é o único sinal: cada tag que `estado_de` pode devolver tem o
    símbolo que vai junto do texto (a regra da trilha de passos)."""
    for texto in VERDE + AMBAR + VERMELHO + AZUL:
        assert widgets.estado_de(texto) in widgets.MARCAS_ESTADO


# ------------------------------------------------------- na tabela de verdade
def test_na_tabela_so_atencao_e_erro_se_pintam(raiz):
    """De ponta a ponta: o texto da tela vira tag, a tag vira cor — e só as
    duas que a regra manda pintar têm fundo próprio. Uma tabela em que ok e
    info também ganhassem fundo viraria faixas coloridas alternadas, que é o
    que o comentário de `estilo_tabela` existe para evitar."""
    import tkinter as tk
    from tkinter import ttk

    widgets.aplicar_estilos(False)
    tabela = ttk.Treeview(raiz, columns=("situacao",), show="headings")
    tabela.heading("situacao", text="Situação")
    widgets.estilo_tabela(tabela)
    try:
        textos = ["APTO (autorizado)", "ATENÇÃO — sem anexo", "REJEITADO",
                  "AGUARDA ASSINATURA"]
        for i, texto in enumerate(textos):
            estado = widgets.estado_de(texto)
            tabela.insert("", "end", iid=str(i), values=(texto,),
                          tags=widgets.linha_zebrada(i, estado))
        raiz.update()

        c = widgets.cores()
        tags = {iid: tabela.item(iid, "tags") for iid in tabela.get_children()}
        assert "ok" in tags["0"] and "atencao" in tags["1"]
        assert "erro" in tags["2"] and "info" in tags["3"]

        # As duas que se pintam, com a cor da paleta.
        assert str(tabela.tag_configure("atencao", "background")) == \
            c["atencao_fundo"]
        assert str(tabela.tag_configure("erro", "background")) == c["erro_fundo"]
        # As duas que NÃO se pintam: sem fundo próprio, a zebra decide.
        assert str(tabela.tag_configure("ok", "background")) == ""
        assert str(tabela.tag_configure("info", "background")) == ""
    finally:
        try:
            tabela.destroy()
        except tk.TclError:
            pass
        raiz.update()
