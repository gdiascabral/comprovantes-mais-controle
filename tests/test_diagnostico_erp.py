# -*- coding: utf-8 -*-
"""A mensagem que o app dá quando a tela do ERP não carrega.

Ela não é enfeite: é a única coisa que quem está na frente do computador
recebe, e as duas causas pedem ações opostas. "Layout mudou" manda esperar
alguém mexer no código; "tela em branco" manda tentar de novo e conferir quem
mais está logado. Em 18/08/2026 uma tela em branco foi anunciada como mudança
de layout, e a investigação começou pelo lugar errado.
"""

from conciliacao.erp.browser import _diagnostico


class _Pagina:
    """Dublê de página: só o que o diagnóstico consulta."""

    def __init__(self, *, url="https://erp/x#/payable-installments",
                 elementos=0, texto="", quebrada=False):
        self.url = url
        self._elementos = elementos
        self._texto = texto
        self._quebrada = quebrada

    def locator(self, seletor):
        pagina = self

        class _Loc:
            def count(self):
                if pagina._quebrada:
                    raise RuntimeError("navegador foi embora")
                return pagina._elementos

            def inner_text(self, timeout=None):
                if pagina._quebrada:
                    raise RuntimeError("navegador foi embora")
                return pagina._texto

        return _Loc()


def test_tela_em_branco_nao_e_acusada_de_layout():
    msg = _diagnostico(_Pagina(elementos=3, texto=""), '[role="row"]', 45)
    assert "EM BRANCO" in msg
    assert "mudanca de layout" not in msg.replace("nao e mudanca de layout", "")
    # E aponta a causa mais provável, que é operacional e não de código.
    assert "UMA sessao por usuario" in msg


def test_tela_cheia_sem_o_seletor_e_layout():
    """Centenas de elementos e o seletor ausente: aí sim alguém precisa
    achar o seletor novo."""
    msg = _diagnostico(_Pagina(elementos=850, texto="Pagamentos" * 30),
                       '[role="row"]', 45)
    assert "mudanca de layout" in msg
    assert "850 elementos" in msg
    assert "EM BRANCO" not in msg


def test_navegador_inacessivel_pede_para_repetir():
    msg = _diagnostico(_Pagina(quebrada=True), '[role="row"]', 45)
    assert "inspecionar" in msg
    assert "Tente de novo" in msg


def test_a_mensagem_sempre_diz_onde_estava():
    """Sem o endereço, não dá para saber se ele ao menos chegou na tela
    certa — e a rota do ERP já mudou antes."""
    for pagina in (_Pagina(elementos=2), _Pagina(elementos=900),
                   _Pagina(quebrada=True)):
        assert "payable-installments" in _diagnostico(pagina, "x", 45)


def test_texto_longo_com_poucos_elementos_nao_e_branco():
    """Uma tela de erro do ERP tem pouco HTML e MUITO texto. Não é branca —
    e chamar de branca faria a pessoa tentar de novo em vez de ler o aviso."""
    msg = _diagnostico(
        _Pagina(elementos=8,
                texto="Sua sessao foi encerrada porque o usuario entrou "
                      "em outro dispositivo. Entre novamente."),
        '[role="row"]', 45)
    assert "EM BRANCO" not in msg
