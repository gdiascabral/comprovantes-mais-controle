# -*- coding: utf-8 -*-
"""Trocar de aba sem fechar o app, e ver a tela de login quando é o caso.

Dois relatos do dono em 18/08/2026, e os dois vinham de tratar como iguais
coisas que não são:

1. **"toda vez abre na tela de sessão encerrada, entra, sai, entra"** — o app
   tentava logar de dentro de uma rota interna. Com o token vencido, o
   single-spa repinta a casca, descobre que não pode e devolve para o login,
   às vezes duas vezes. Indo direto para `#/login` quando já se sabe que a
   sessão caiu, a tela que aparece é a de login.

2. **"uso uma aba e para usar outra preciso fechar o app"** — navegador MORTO
   (janela fechada no X) era tratado como sessão caída. `esta_logado()` num
   contexto que não existe mais estoura, e não havia caminho de volta.
"""
import sys
from pathlib import Path

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))
sys.path.insert(0, str(_RAIZ / "anexar"))


class _Pagina:
    def __init__(self, morta=False):
        self.morta = morta

    def title(self):
        if self.morta:
            raise RuntimeError("Target page, context or browser has been closed")
        return "Mais Controle"


class _Ctx:
    def __init__(self, paginas):
        self._paginas = paginas

    @property
    def pages(self):
        if self._paginas is None:
            raise RuntimeError("contexto fechado")
        return self._paginas


def _cliente(ctx):
    """Um MCClient sem abrir navegador nenhum: só o `vivo()` interessa."""
    from mc_client import MCClient
    cli = MCClient.__new__(MCClient)
    cli.ctx = ctx
    return cli


def test_navegador_aberto_esta_vivo():
    assert _cliente(_Ctx([_Pagina()])).vivo() is True


def test_janela_fechada_no_x_nao_esta_viva():
    """O caso do relato: a pessoa fecha o Chrome e a próxima aba do app
    tomava erro de Playwright sem caminho de volta."""
    assert _cliente(_Ctx([_Pagina(morta=True)])).vivo() is False


def test_contexto_derrubado_nao_esta_vivo():
    assert _cliente(_Ctx(None)).vivo() is False


def test_sem_contexto_nao_esta_vivo():
    assert _cliente(None).vivo() is False


def test_sem_abas_nao_esta_vivo():
    """Contexto de pé e zero páginas: não há onde trabalhar."""
    assert _cliente(_Ctx([])).vivo() is False


def test_vivo_fala_de_verdade_com_o_navegador():
    """`is_closed()` responde sem sair do processo, e um contexto morto
    passaria por vivo. Por isso o `vivo()` chama `title()`."""
    chamou = {"title": False}

    class _P(_Pagina):
        def title(self):
            chamou["title"] = True
            return "x"

    _cliente(_Ctx([_P()])).vivo()
    assert chamou["title"]


def test_a_url_de_login_existe_e_aponta_para_o_login():
    """É ela que evita o vaivém: com a sessão caída, o app vai para a porta
    de entrada em vez de insistir numa rota interna."""
    import config
    assert config.MC_URL_LOGIN.endswith("/#/login")
    assert config.MC_URL_LOGIN.startswith(config.MC_URL_BASE)
