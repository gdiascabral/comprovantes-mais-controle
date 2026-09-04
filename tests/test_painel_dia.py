# -*- coding: utf-8 -*-
"""A visão do dia e as duas regras de transição — puras, sem tela e sem rede.

O que se testa aqui é o que decide dinheiro: a contagem por `retorno_estado`
(que é o que responde "esta conta fechou?"), a ORDEM das perguntas da
`situacao` e, principalmente, as duas travas do descarte. Descartar tira a
remessa de `ESTADOS_VIVOS`, e `remessa_dia._ja_enviado` só enxerga item de
remessa viva: descartar uma remessa com pagamento PAGO devolve àquele dinheiro
o direito de sair de novo.

Nomes de empresa e valores aqui são inventados — este repositório é público.
"""
import datetime as _dt
from decimal import Decimal

from pagamentos_dia import painel_dia


def _item(estado="", valor="100.00", retorno_em=None):
    return {"valor": valor, "retorno_estado": estado, "retorno_em": retorno_em}


def _remessa(estado="gerado", itens=(), **campos):
    linha = {"convenio": "1814", "nsa": 7, "empresa": "EXEMPLO LTDA",
             "agencia": "3067", "conta": "12345-6", "estado": estado,
             "observacao": "", "gerado_em": "2026-09-04T13:05:00-03:00",
             "arquivo": "C:/saida/REM_EXEMPLO_3067-12345-6_000007.REM",
             "remessa_item": list(itens)}
    linha.update(campos)
    return linha


def _uma(estado="gerado", itens=(), **campos):
    linha, = painel_dia.linhas_do_dia([_remessa(estado, itens, **campos)])
    return linha


# ------------------------------------------------------------- contagens

def test_conta_por_retorno_estado_e_soma_o_valor():
    linha = _uma("enviado", [
        _item("ok", "100.00"), _item("ok", "50.50"),
        _item("pendente", "10.00"),
        _item("rejeitado", "1.00"),
        _item("?", "2.00"), _item("", "3.00")])

    assert (linha.pagos, linha.aguardando, linha.rejeitados) == (2, 1, 1)
    # "?" é "o banco não citou este pagamento" e "" é "nenhum retorno lido
    # ainda": os dois são a mesma pergunta em aberto.
    assert linha.sem_resposta == 2
    assert linha.total == Decimal("166.50")
    assert linha.itens == 6 and linha.respondidos == 4


def test_o_total_e_decimal_e_nao_float():
    """O PostgREST devolve `numeric` como STRING de propósito. Somar centavos
    em base 2 é como o total da tela deixa de bater com o do arquivo."""
    linha = _uma("enviado", [_item("ok", "0.10"), _item("ok", "0.20")])
    assert isinstance(linha.total, Decimal)
    assert linha.total == Decimal("0.30")


def test_valor_ilegivel_nao_derruba_a_linha():
    """A tela existe para dizer o que falta fechar; um valor torto não pode
    custar a linha inteira."""
    linha = _uma("enviado", [_item("ok", None), _item("ok", "nada")])
    assert linha.total == Decimal("0") and linha.pagos == 2


def test_remessa_sem_item_nao_estoura():
    linha = _uma("gerado", [])
    assert linha.itens == 0 and linha.total == Decimal("0")
    assert linha.retorno_lido_em is None


def test_lista_vazia_e_none_devolvem_lista_vazia():
    assert painel_dia.linhas_do_dia([]) == []
    assert painel_dia.linhas_do_dia(None) == []


def test_o_retorno_lido_e_o_MAIS_RECENTE():
    """A mesma remessa é lida duas vezes: a primeira volta `PD` (pendente de
    assinatura), a segunda `00`. O que interessa é a última."""
    linha = _uma("enviado", [
        _item("pendente", retorno_em="2026-09-04T10:00:00+00:00"),
        _item("ok", retorno_em="2026-09-04T18:30:00+00:00"),
        _item("ok", retorno_em="2026-09-04T12:00:00+00:00")])
    assert linha.retorno_lido_em == _dt.datetime.fromisoformat(
        "2026-09-04T18:30:00+00:00").astimezone()


def test_gerado_em_vira_hora_local():
    """`gerado_em` é `timestamptz` e o banco o devolve em UTC. Quem lê a tela
    quer a hora do relógio dela, não a de Greenwich."""
    linha = _uma("gerado", [], gerado_em="2026-09-04T16:05:00+00:00")
    esperado = _dt.datetime.fromisoformat("2026-09-04T16:05:00+00:00").astimezone()
    assert linha.gerado_em == esperado
    assert linha.gerado_em.utcoffset() == esperado.utcoffset()


def test_data_ilegivel_vira_none_sem_derrubar():
    linha = _uma("gerado", [], gerado_em="ontem de tarde")
    assert linha.gerado_em is None and linha.nsa == 7


def test_a_ordem_que_chega_e_preservada():
    """Quem ordena é a consulta (`order=gerado_em.asc`). Reordenar aqui daria
    duas regras de ordenação para a mesma lista."""
    linhas = painel_dia.linhas_do_dia(
        [_remessa(nsa=9), _remessa(nsa=3), _remessa(nsa=5)])
    assert [l.nsa for l in linhas] == [9, 3, 5]


# -------------------------------------------------------------- situação

def test_descartada_vem_antes_de_tudo():
    """A remessa saiu de conta: o que os itens dela dizem já não pesa em
    decisão nenhuma — nem o rejeitado, nem o pago."""
    linha = _uma("descartado", [_item("rejeitado"), _item("ok")])
    assert painel_dia.situacao(linha) == ("info", "descartada")


def test_gerada_pede_o_sicoobnet():
    assert painel_dia.situacao(_uma("gerado", [_item()])) == (
        "atencao", "gerada — falta subir no SicoobNet")


def test_enviada_sem_retorno_pede_o_retorno():
    linha = _uma("enviado", [_item(), _item("?")])
    assert painel_dia.situacao(linha) == (
        "atencao", "enviada — falta ler o retorno")


def test_pendente_e_aguardando_assinatura():
    linha = _uma("enviado", [_item("ok"), _item("pendente")])
    assert painel_dia.situacao(linha) == ("atencao", "aguardando assinatura")


def test_rejeitado_ganha_de_pendente():
    """Item recusado é o que faz alguém abrir o detalhe HOJE; escondê-lo
    atrás de "aguardando assinatura" adiaria isso até alguém estranhar a
    falta do dinheiro. Mesma ordem do `_situacao_do_retorno`."""
    linha = _uma("enviado", [_item("rejeitado"), _item("pendente"),
                             _item("rejeitado")])
    assert painel_dia.situacao(linha) == ("erro", "2 rejeitado(s)")


def test_tudo_pago_e_paga():
    linha = _uma("processado", [_item("ok"), _item("ok")])
    assert painel_dia.situacao(linha) == ("ok", "paga")


def test_pago_em_parte_com_o_resto_calado_nao_e_paga():
    """Um item pago e outro que o banco não citou não fecha a conta — e não é
    "aguardando assinatura", porque ninguém está esperando assinatura de um
    pagamento sobre o qual o banco não disse nada."""
    linha = _uma("enviado", [_item("ok"), _item("?")])
    assert painel_dia.situacao(linha) == (
        "info", "sem resposta do banco por todos")


def test_a_tag_e_sempre_uma_das_quatro_do_widgets():
    """A cor sai da tag pelo `estilo_tabela`; uma tag inventada aqui viraria
    linha sem cor nenhuma, em silêncio."""
    import widgets

    casos = [_uma("descartado", [_item("ok")]),
             _uma("gerado", [_item()]),
             _uma("enviado", []),
             _uma("enviado", [_item("pendente")]),
             _uma("enviado", [_item("rejeitado")]),
             _uma("processado", [_item("ok")]),
             _uma("enviado", [_item("ok"), _item("?")])]
    for linha in casos:
        tag, frase = painel_dia.situacao(linha)
        assert tag in widgets.MARCAS_ESTADO, tag
        assert frase and frase == frase.strip()


# ------------------------------------------- as duas regras de transição

def test_so_gerado_pode_ser_marcada_enviada():
    """De qualquer outro estado a marca não acrescenta nada e pode TIRAR:
    sobre uma remessa `processado`, apagaria o desfecho do retorno."""
    assert painel_dia.pode_marcar_enviada(_uma("gerado", [_item()]))
    for estado in ("enviado", "processado", "rejeitado", "descartado"):
        assert not painel_dia.pode_marcar_enviada(_uma(estado, [_item()])), estado


def test_descartar_com_item_pago_e_recusado():
    """Descartar devolve os pagamentos à fila. Numa remessa em que o banco já
    pagou alguém, isso é autorizar o mesmo dinheiro a sair duas vezes."""
    linha = _uma("rejeitado", [_item("ok"), _item("rejeitado"),
                               _item("rejeitado")])
    pode, recusa = painel_dia.pode_descartar(linha)
    assert not pode
    assert "PAGOU" in recusa and "1 pagamento" in recusa


def test_descartar_a_ja_descartada_e_recusado():
    pode, recusa = painel_dia.pode_descartar(_uma("descartado", [_item()]))
    assert not pode and "já está descartada" in recusa


def test_sem_motivo_pergunta_so_o_estado():
    """`motivo=None` é a pergunta do BOTÃO: dá para habilitar? O texto entra
    na conferência só na chamada de quem vai descartar de verdade."""
    linha = _uma("gerado", [_item("pendente"), _item("rejeitado")])
    assert painel_dia.pode_descartar(linha) == (True, "")


def test_motivo_curto_ou_em_branco_e_recusado():
    linha = _uma("gerado", [_item()])
    for motivo in ("", "   ", "x", "erro", "  ok  "):
        pode, recusa = painel_dia.pode_descartar(linha, motivo)
        assert not pode, motivo
        assert str(painel_dia.MOTIVO_MINIMO) in recusa


def test_motivo_escrito_passa():
    linha = _uma("gerado", [_item(), _item("pendente")])
    assert painel_dia.pode_descartar(linha, "gerei sem querer") == (True, "")


def test_o_item_pago_ganha_do_motivo_bem_escrito():
    """A ordem das travas importa: motivo perfeito não compra o direito de
    devolver à fila um pagamento que já saiu."""
    linha = _uma("enviado", [_item("ok")])
    pode, recusa = painel_dia.pode_descartar(linha, "arquivo trocado por engano")
    assert not pode and "PAGOU" in recusa


def test_a_observacao_do_descarte_leva_o_motivo_e_tem_teto():
    assert painel_dia.observacao_do_descarte("  subi o arquivo errado  ") == (
        "descartada: subi o arquivo errado")
    assert len(painel_dia.observacao_do_descarte("x" * 900)) == 400
