# -*- coding: utf-8 -*-
"""
Testes da detecção de sessão do Mais Controle.

Nasceram de um caso real (10/08/2026): o login funcionou, o painel abriu, e
mesmo assim o app disse "não detectei a área logada" e APAGOU a senha salva —
levando junto a leitura de saldos da Conciliação, que usa a mesma credencial.

A detecção não pode depender de um texto da tela: o ERP está migrando de
AngularJS para React uma tela por vez.
"""
import mc_client


class PaginaFalsa:
    """Só o que `_esta_logado` consulta."""

    def __init__(self, url, texto_visivel=False, campo_senha=False):
        self.url = url
        self._texto = texto_visivel
        self.campo_senha = campo_senha

    def locator(self, _seletor):
        return self

    @property
    def first(self):
        return self

    def is_visible(self, timeout=None):
        return self._texto


def cliente(pagina):
    c = mc_client.MCClient.__new__(mc_client.MCClient)
    c.page = pagina
    c._tem_campo_senha = lambda: pagina.campo_senha
    return c


BASE = "https://acessar.maiscontroleerp.com.br"


def test_painel_novo_sem_o_texto_esperado_conta_como_logado():
    """O caso que quebrou: React no painel, texto fora do alcance do .first."""
    p = PaginaFalsa(f"{BASE}/#/app/dashboard", texto_visivel=False)
    assert cliente(p)._esta_logado() is True


def test_texto_da_area_logada_ainda_vale_quando_existe():
    p = PaginaFalsa(f"{BASE}/#/payable-installments", texto_visivel=True)
    assert cliente(p)._esta_logado() is True


def test_tela_de_login_nao_e_logado():
    p = PaginaFalsa(f"{BASE}/#/login", texto_visivel=False, campo_senha=True)
    assert cliente(p)._esta_logado() is False


def test_campo_de_senha_na_tela_nao_e_logado():
    # Sem "login" na URL, mas ainda pedindo senha: não entrou.
    p = PaginaFalsa(f"{BASE}/#/", texto_visivel=False, campo_senha=True)
    assert cliente(p)._esta_logado() is False


def test_fora_do_erp_nao_e_logado():
    for url in ("about:blank", "https://www.google.com", ""):
        assert cliente(PaginaFalsa(url))._esta_logado() is False


def test_rotas_internas_variadas_contam_como_logado():
    # #/cash-flow não tem "/app"; a regra não pode depender de um prefixo.
    for rota in ("#/app/dashboard", "#/cash-flow", "#/payable-installments",
                 "#/accounts"):
        p = PaginaFalsa(f"{BASE}/{rota}")
        assert cliente(p)._esta_logado() is True, rota
