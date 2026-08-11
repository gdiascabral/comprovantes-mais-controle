# -*- coding: utf-8 -*-
"""
Testes da detecção de sessão do Mais Controle.

Nasceram de dois casos reais em 10/08/2026:

1. o app apagou a senha salva porque não "detectou a área logada" — com o
   painel aberto na tela;
2. depois de corrigido isso, seguiu não detectando, e a Conciliação parou.

A causa dos dois era a mesma: procurar um sinal POSITIVO ("Pagamentos") numa
tela que o ERP está redesenhando aos poucos. A regra correta, herdada do
projeto da Conciliação Diária, é procurar a TELA DE LOGIN e concluir sessão
pela ausência dela.
"""
import mc_client


class AbaFalsa:
    """Só o que a detecção consulta."""

    def __init__(self, url, sinais=()):
        self.url = url
        self._sinais = set(sinais)
        self._pedido = None

    def locator(self, seletor):
        self._pedido = seletor
        return self

    @property
    def first(self):
        return self

    def is_visible(self, timeout=None):
        return self._pedido in self._sinais


class CtxFalso:
    def __init__(self, abas):
        self.pages = abas


def cliente(abas, atual=None):
    c = mc_client.MCClient.__new__(mc_client.MCClient)
    c.ctx = CtxFalso(abas)
    c.page = atual if atual is not None else (abas[0] if abas else None)
    return c


BASE = "https://acessar.maiscontroleerp.com.br"
SENHA = 'input[type="password"]'


def test_painel_sem_o_texto_esperado_conta_como_logado():
    """O caso que quebrou: React no painel, nenhum sinal de login à vista."""
    aba = AbaFalsa(f"{BASE}/#/app/dashboard")
    assert cliente([aba])._esta_logado() is True


def test_campo_de_senha_significa_nao_logado():
    aba = AbaFalsa(f"{BASE}/#/login", sinais=[SENHA])
    assert cliente([aba])._esta_logado() is False


def test_sem_permissao_significa_nao_logado():
    """O Firebase mostra isso enquanto o token não volta do IndexedDB."""
    aba = AbaFalsa(f"{BASE}/#/app/dashboard", sinais=["text=não tem permissão"])
    assert cliente([aba])._esta_logado() is False


def test_entre_na_sua_conta_significa_nao_logado():
    aba = AbaFalsa(f"{BASE}/#/", sinais=["text=Entre na sua conta"])
    assert cliente([aba])._esta_logado() is False


def test_acha_a_sessao_em_outra_aba_e_adota_ela():
    """O ERP abre aba nova (stateGoNewTab); o cliente nascia preso na pages[0]."""
    presa = AbaFalsa(f"{BASE}/#/login", sinais=[SENHA])
    viva = AbaFalsa(f"{BASE}/#/cash-flow")
    c = cliente([presa, viva], atual=presa)
    assert c._esta_logado() is True
    assert c.page is viva          # adotou a aba certa para seguir o trabalho


def test_fora_do_erp_nao_conta():
    for url in ("about:blank", "https://www.google.com", ""):
        assert cliente([AbaFalsa(url)])._esta_logado() is False


def test_sem_aba_nenhuma_nao_quebra():
    assert cliente([])._esta_logado() is False


def test_rotas_internas_variadas_contam_como_logado():
    for rota in ("#/app/dashboard", "#/cash-flow", "#/payable-installments",
                 "#/accounts"):
        assert cliente([AbaFalsa(f"{BASE}/{rota}")])._esta_logado() is True, rota
