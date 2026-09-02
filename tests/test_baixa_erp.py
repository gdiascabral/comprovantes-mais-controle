# -*- coding: utf-8 -*-
"""A baixa no Mais Controle do que o banco disse que pagou.

Sem rede e sem navegador: o transporte é falso e responde o que o teste
mandar. O que se prova aqui é dinheiro sendo dado como pago uma vez só, na
parcela certa, e o que NÃO dá para baixar aparecendo com o motivo.
"""
import datetime as _dt

import baixa_erp
from erp import hosts, pagina, sessao

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
def test_a_baixa_usa_o_corpo_do_ERP_e_o_endereco_medido():
    """A rota saiu do ERP, não do bundle: `/payables` deu 404 e
    `/payable-installments` deu 400 pedindo o parâmetro que falta."""
    t = TransporteFalso()
    r = baixa_erp.baixar_uma(t, LinhaFalsa(), HOJE, log=lambda _m: None)
    assert r.ok and not r.erro
    url, corpo = t.posts[0]
    assert "/payable-installments/parcela-1/paids" in url
    assert corpo["payingDate"] == "2026-08-20"
    assert corpo["account"] == {"id": "c1"}


def test_a_baixa_leva_o_valor_pago():
    """A primeira baixa aceita saiu R$ 0,00, com a parcela seguindo em aberto.

    O `default-paid` nao traz campo de valor: `account`, `documentNumber`,
    `payingDate`, `paymentMethod` e `responsible`, e mais nada. Mandar o corpo
    dele intacto e o pior desfecho possivel — o ERP responde 200 e nao paga.
    """
    t = TransporteFalso(padrao={"payingDate": "2026-08-31", "account": {"id": "c1"}})
    baixa_erp.baixar_uma(t, LinhaFalsa(valor=120.00), HOJE, log=lambda _m: None)
    _url, corpo = t.posts[0]
    assert corpo["value"] == 120.00 and corpo["paidValue"] == 120.00


def test_o_id_da_baixa_criada_volta_no_resultado():
    """Sem ele nao ha como desfazer o que acabou de ser gravado."""
    t = TransporteFalso(resposta_post={"id": "paid-99"})
    r = baixa_erp.baixar_uma(t, LinhaFalsa(), HOJE, log=lambda _m: None)
    assert r.ok and r.paid_id == "paid-99"


def test_o_parametro_que_o_ERP_exigiu_vai_na_query():
    """Sem ele: 400 "Required request parameter 'isWorkFilterApplied'"."""
    t = TransporteFalso()
    baixa_erp.baixar_uma(t, LinhaFalsa(), HOJE, log=lambda _m: None)
    assert "isWorkFilterApplied=false" in t.posts[0][0]


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


def test_404_na_rota_de_hoje_ainda_tenta_a_outra():
    """A rede para o dia em que o ERP mover a rota: 404 não encerra o assunto."""
    class So_payables(TransporteFalso):
        def postar(self, url, corpo):
            self.posts.append((url, corpo))
            if "/payable-installments/" in url:
                return {"__erro": "404"}
            return {"id": "paid-1"}

    t = So_payables()
    r = baixa_erp.baixar_uma(t, LinhaFalsa(), HOJE, log=lambda _m: None)
    assert r.ok
    assert "/payable-installments/" in t.posts[0][0]
    assert "/payables/" in t.posts[1][0]


def test_erro_que_nao_e_404_para_na_hora():
    """Repetir um POST que o servidor ENTENDEU baixaria o mesmo duas vezes."""
    t = TransporteFalso(resposta_post={"__erro": "500"})
    r = baixa_erp.baixar_uma(t, LinhaFalsa(), HOJE, log=lambda _m: None)
    assert not r.ok and len(t.posts) == 1


def test_o_recado_diz_a_url_e_o_que_o_ERP_respondeu():
    """"HTTP 404" sozinho obrigou a voltar ao bundle do ERP para diagnosticar."""
    t = TransporteFalso(resposta_post={"__erro": "400",
                                       "__corpo": {"message": "faltou o campo X"}})
    r = baixa_erp.baixar_uma(t, LinhaFalsa(), HOJE, log=lambda _m: None)
    assert "/paids" in r.erro and "faltou o campo X" in r.erro


# ------------------------------------------------------- os endereços e o erp/
def test_os_enderecos_vem_do_erp_hosts():
    """As mesmas quatro URLs estavam escritas em sete arquivos, e quem corrige
    uma cópia não sabe das outras.

    A ORDEM continua sendo parte da regra: o legado vem primeiro porque o
    `default-paid` é LEITURA, e descobrir errando ali não escreve nada."""
    assert baixa_erp.LEGADO == hosts.LEGACY
    assert baixa_erp.NOVA == hosts.ERP_API
    assert baixa_erp.HOSTS == (hosts.LEGACY, hosts.ERP_API)


class _PaginaFalsa:
    """A `page` do Playwright, do tamanho que o `TransportePagina` usa."""

    def __init__(self, padrao, resposta_post):
        self.padrao, self.resposta_post = padrao, resposta_post
        self.chamadas = []

    def evaluate(self, js, argumento):
        self.chamadas.append(argumento)
        return self.resposta_post if "corpo" in argumento else self.padrao


def test_o_transporte_do_erp_baixa_sem_adaptador_nenhum():
    """A migração inteira deste módulo cabe nesta frase: os dois métodos que
    ele exige são os que `erp/pagina.py` expõe.

    Não é o dublê do arquivo que está sendo exercitado aqui, e sim o
    `TransportePagina` de verdade — com o JS e o contrato de erro dele. Se um
    dia os nomes divergirem, é este teste que acusa, e não a primeira baixa
    real de um dia de pagamento."""
    falsa = _PaginaFalsa(
        padrao={"payingDate": "2026-08-31", "account": {"id": "c1"}},
        resposta_post={"id": "paid-7"})
    transporte = pagina.TransportePagina(
        falsa, {hosts.HOST_LEGACY: {"authorization": "Bearer legado",
                                    "user-id": "user-1"}})

    r = baixa_erp.baixar_uma(transporte, LinhaFalsa(), HOJE, log=lambda _m: None)

    assert r.ok and r.paid_id == "paid-7"
    assert falsa.chamadas[0]["url"].startswith(hosts.LEGACY)
    assert falsa.chamadas[-1]["corpo"]["value"] == 120.00
    # O cabeçalho do LEGADO foi escolhido pelo host da URL: reaproveitar o de
    # outro host devolveria 401.
    assert falsa.chamadas[-1]["headers"]["user-id"] == "user-1"


def test_a_baixa_nao_e_idempotente_e_por_isso_nao_relogia():
    """`erp.Sessao.pedir` relogia no 401 do legado, mas só em GET — e em
    PUT/POST que o CHAMADOR marcar como idempotentes.

    A baixa não é marcável: o `POST .../paids` CRIA um pagamento, e repeti-lo
    depois de perder a resposta baixa o mesmo título duas vezes. Este teste
    guarda a decisão pelo lado do `erp/`, que é onde a marca existiria —
    ninguém pode ligá-la sem passar por aqui."""
    logada = sessao.Sessao(jwt_token="j", access_token="a",
                           company_id="e1", user_id="u1")
    url = f"{hosts.LEGACY}/payable-installments/parcela-1/paids"
    assert logada._da_para_relogar(url, "POST", sessao.SessaoRecusada(
        "401", codigo=401), False) is False


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
