# -*- coding: utf-8 -*-
"""A baixa no Mais Controle do que o banco disse que pagou.

Sem rede e sem navegador: o transporte é falso e responde o que o teste
mandar. O que se prova aqui é dinheiro sendo dado como pago uma vez só, na
parcela certa, e o que NÃO dá para baixar aparecendo com o motivo.
"""
import datetime as _dt

import baixa_erp

HOJE = _dt.date(2026, 8, 20)


class LinhaFalsa:
    """O bastante de `retorno_dia.Linha` para esta regra."""

    def __init__(self, seu_numero="260820-0012", estado="ok",
                 referencia="parcela-1", valor=120.00,
                 favorecido="FORNECEDOR SA"):
        self.seu_numero = seu_numero
        self.estado = estado
        self.referencia = referencia
        self.valor = valor
        self.favorecido = favorecido


class ResumoFalso:
    def __init__(self, *linhas):
        self.linhas = list(linhas)


class TransporteFalso:
    """Responde o que o teste mandar, e ANOTA o que foi pedido."""

    def __init__(self, padrao=None, resposta_post=None, erros_get=None):
        self.padrao = padrao if padrao is not None else {
            "payingDate": "2026-08-31", "value": 120.00, "account": {"id": "c1"}}
        self.resposta_post = resposta_post if resposta_post is not None else {"id": "paid-1"}
        self.erros_get = erros_get or {}
        self.buscas: list[str] = []
        self.posts: list[tuple[str, dict]] = []

    def _buscar(self, url):
        self.buscas.append(url)
        for pedaco, erro in self.erros_get.items():
            if pedaco in url:
                return {"__erro": erro}
        return self.padrao

    def postar(self, url, corpo):
        self.posts.append((url, corpo))
        return self.resposta_post


# --------------------------------------------------------------- separar
def test_so_o_que_o_banco_pagou_entra():
    """Pendente de assinatura é o estado NORMAL do mesmo dia.

    Baixar ali seria dizer que saiu dinheiro que ainda não saiu — falta o
    master assinar no SicoobNet.
    """
    s = baixa_erp.separar(ResumoFalso(
        LinhaFalsa(seu_numero="a", estado="ok"),
        LinhaFalsa(seu_numero="b", estado="pendente"),
        LinhaFalsa(seu_numero="c", estado="rejeitado"),
        LinhaFalsa(seu_numero="d", estado="?")))
    assert [l.seu_numero for l in s.baixaveis] == ["a"]
    assert s.de_fora == []


def test_pago_sem_lancamento_ligado_aparece_com_motivo():
    """Sumir com ele esconderia um pagamento real em aberto no ERP."""
    s = baixa_erp.separar(ResumoFalso(LinhaFalsa(referencia="")))
    assert s.baixaveis == []
    linha, motivo = s.de_fora[0]
    assert "baixe à mão" in motivo


# ---------------------------------------------------------- corpo e valor
def test_a_data_do_banco_substitui_a_que_o_ERP_sugeriu():
    corpo, aviso = baixa_erp.corpo_da_baixa({"payingDate": "2026-08-31"}, HOJE)
    assert corpo["payingDate"] == "2026-08-20" and aviso == ""


def test_sem_campo_de_data_a_baixa_sai_avisando():
    """A baixa vale, mas com a data do ERP — e isso tem de estar escrito."""
    corpo, aviso = baixa_erp.corpo_da_baixa({"value": 10}, HOJE)
    assert corpo == {"value": 10}
    assert "data" in aviso


def test_o_resto_do_corpo_do_ERP_e_devolvido_intacto():
    """O corpo vem dele: fixar o formato aqui quebraria calado quando mudasse."""
    padrao = {"payingDate": "x", "account": {"id": "c1"}, "responsible": {"id": "u"}}
    corpo, _ = baixa_erp.corpo_da_baixa(padrao, HOJE)
    assert corpo["account"] == {"id": "c1"} and corpo["responsible"] == {"id": "u"}


def test_valor_que_nao_bate_barra_a_baixa():
    """O banco pagou parcial e o ERP propõe o total: fechar seria mentir."""
    assert baixa_erp.conferir_valor({"value": 500.00}, 120.00)


def test_valor_igual_passa():
    assert baixa_erp.conferir_valor({"value": 120.00}, 120.00) == ""


def test_sem_campo_de_valor_nao_se_inventa_conferencia():
    assert baixa_erp.conferir_valor({"outro": 1}, 120.00) == ""


# ----------------------------------------------------------------- baixar
def test_a_baixa_usa_o_corpo_do_ERP_e_o_endereco_certo():
    t = TransporteFalso()
    r = baixa_erp.baixar_uma(t, LinhaFalsa(), HOJE, log=lambda _m: None)
    assert r.ok and not r.erro
    url, corpo = t.posts[0]
    assert url.endswith("/payables/parcela-1/paids")
    assert corpo["payingDate"] == "2026-08-20"
    assert corpo["account"] == {"id": "c1"}


def test_404_no_primeiro_host_tenta_o_segundo():
    """O `default-paid` é LEITURA: descobrir errando não escreve nada."""
    t = TransporteFalso(erros_get={"legacy-api": "404"})
    r = baixa_erp.baixar_uma(t, LinhaFalsa(), HOJE, log=lambda _m: None)
    assert r.ok and "prod-erp-api" in r.host
    assert len(t.buscas) == 2


def test_erro_que_nao_e_404_nao_tenta_o_vizinho():
    """403 é problema de verdade; insistir no outro host só confunde o relato."""
    t = TransporteFalso(erros_get={"legacy-api": "403"})
    r = baixa_erp.baixar_uma(t, LinhaFalsa(), HOJE, log=lambda _m: None)
    assert not r.ok and "403" in r.erro and len(t.buscas) == 1


def test_ERP_recusando_a_baixa_vira_resultado_e_nao_excecao():
    t = TransporteFalso(resposta_post={"__erro": "422", "__corpo": {}})
    r = baixa_erp.baixar_uma(t, LinhaFalsa(), HOJE, log=lambda _m: None)
    assert not r.ok and "422" in r.erro


def test_uma_que_falha_nao_impede_as_outras():
    """Parar no terceiro deixaria doze pagos sem baixa, sem ninguém saber."""
    class Alternado(TransporteFalso):
        def postar(self, url, corpo):
            self.posts.append((url, corpo))
            return {"__erro": "500"} if "parcela-2" in url else {"id": "ok"}

    t = Alternado()
    linhas = [LinhaFalsa(seu_numero="a", referencia="parcela-1"),
              LinhaFalsa(seu_numero="b", referencia="parcela-2"),
              LinhaFalsa(seu_numero="c", referencia="parcela-3")]
    rs = baixa_erp.baixar(t, linhas, HOJE, log=lambda _m: None)
    assert [r.ok for r in rs] == [True, False, True]
    assert "500" in rs[1].erro
