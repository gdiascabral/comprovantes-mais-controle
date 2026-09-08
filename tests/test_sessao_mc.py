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
from anexar import mc_client


class AbaFalsa:
    """Só o que a detecção consulta."""

    def __init__(self, url, sinais=(), opener=None):
        self.url = url
        self._sinais = set(sinais)
        self._pedido = None
        self._opener = opener
        self.ouvindo = []                 # eventos em que alguém se inscreveu

    def opener(self):
        return self._opener

    def on(self, evento, _handler):
        self.ouvindo.append(evento)

    def is_closed(self):
        return False

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


def cliente(abas, atual=None, da_pessoa=()):
    """Um MCClient sem navegador. Toda aba é do robô, menos as em `da_pessoa`."""
    c = mc_client.MCClient.__new__(mc_client.MCClient)
    c.ctx = CtxFalso(abas)
    c.page = atual if atual is not None else (abas[0] if abas else None)
    c._minhas = {a for a in abas if a not in da_pessoa}
    c.log = lambda *_: None
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


# ------------------------------------------------------------ a aba da pessoa
# A pessoa pode usar o Mais Controle numa aba dela, no mesmo Chrome, enquanto
# o robô trabalha. A condição para isso funcionar é uma só: o robô NUNCA
# adota uma aba que não seja dele — adotá-la faria o passo seguinte navegar
# a aba em que a pessoa está.

def test_aba_da_pessoa_logada_nao_conta_como_sessao_do_robo():
    """O caso perigoso: a do robô caiu no login e a da pessoa está no painel.
    Antes, o robô adotava a da pessoa e seguia trabalhando NELA."""
    do_robo = AbaFalsa(f"{BASE}/#/login", sinais=[SENHA])
    da_pessoa = AbaFalsa(f"{BASE}/#/payable-installments")
    c = cliente([do_robo, da_pessoa], atual=do_robo, da_pessoa=[da_pessoa])
    assert c._esta_logado() is False
    assert c.page is do_robo               # continua na dele, sem adotar a outra


def test_aba_aberta_a_partir_da_do_robo_e_do_robo():
    """O ERP abre aba nova a partir da do robô (stateGoNewTab): essa é dele,
    e continua sendo adotada como antes."""
    do_robo = AbaFalsa(f"{BASE}/#/login", sinais=[SENHA])
    c = cliente([do_robo])
    filha = AbaFalsa(f"{BASE}/#/cash-flow", opener=do_robo)
    c.ctx.pages.append(filha)
    c._nova_aba(filha)                      # o evento "page" do contexto
    assert filha in c._minhas
    assert filha.ouvindo == []              # nada de download: aba de trabalho
    assert c._esta_logado() is True
    assert c.page is filha


def test_aba_sem_opener_e_da_pessoa_e_so_os_downloads_dela_sao_ouvidos():
    """Ctrl+T, o botão "Minha aba" e o chrome.exe por fora chegam sem opener."""
    do_robo = AbaFalsa(f"{BASE}/#/payable-installments")
    c = cliente([do_robo])
    sua = AbaFalsa(f"{BASE}/#/accounts")
    c.ctx.pages.append(sua)
    c._nova_aba(sua)
    assert sua not in c._minhas
    assert sua.ouvindo == ["download"]
    assert c._abas_da_pessoa() == [sua]
    assert c._abas_do_robo() == [do_robo]


def test_aba_da_pessoa_no_login_nao_derruba_a_sessao_do_robo():
    """A pessoa pode ter deixado a aba dela na tela de login; isso não é sinal
    de que a sessão do robô caiu."""
    do_robo = AbaFalsa(f"{BASE}/#/payable-installments")
    sua = AbaFalsa(f"{BASE}/#/login", sinais=[SENHA])
    c = cliente([do_robo, sua], da_pessoa=[sua])
    assert c._esta_logado() is True
    assert c.page is do_robo


def test_diagnostico_diz_de_quem_e_cada_aba():
    do_robo = AbaFalsa(f"{BASE}/#/login", sinais=[SENHA])
    sua = AbaFalsa(f"{BASE}/#/accounts")
    c = cliente([do_robo, sua], da_pessoa=[sua])
    texto = c._diagnostico_sessao()
    assert "aba0 (robô)" in texto and "aba1 (pessoa)" in texto


def test_pulsar_com_navegador_morto_nao_estoura():
    """O pulso roda a cada segundo com o navegador livre; o Chrome pode ter
    sido fechado no X entre um pulso e outro."""
    class CtxMorto:
        @property
        def pages(self):
            raise RuntimeError("Target closed")
    c = cliente([])
    c.ctx = CtxMorto()
    c.pulsar()                              # não pode levantar
