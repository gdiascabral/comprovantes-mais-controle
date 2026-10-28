# -*- coding: utf-8 -*-
"""O LOGIN PRINCIPAL do Chrome central: um caminho só, sempre primeiro.

Decisão do dono (28/10/2026), depois do diagnostico.log de 22 a 28/10: a aba
de leitura (`SessaoPelaPagina`) nascia na tela de login, em CORRIDA com o login
que a aba do Anexar fazia ao mesmo tempo, e desistia ("o porteiro precisa
entrar") — na abertura (conferência de contas novas) e no "Buscar pagamentos e
saldos". Agora, antes de qualquer trabalho no ERP, todos pedem AQUI:

    garantir_logado(acesso, log=...) -> bool   # True = entrou agora

- Logado (o porteiro de pé no servidor, ou outra aba já entrou): ninguém loga.
- Fora: UMA aba própria (marcada por `window.name`, reaproveitada na vez
  seguinte) entra pela tela com o login guardado — o caminho provado do
  MCClient, `erp.login_tela` — e termina PARADA em `#/app/dashboard`.
- Os outros pedidos ESPERAM: no processo, por uma trava por acesso; entre
  processos (o água e energia, outra janela do app), pela trava de arquivo
  `<perfil>/../.<nome>.login.trava` (`central.trava`). Quem esperava encontra
  o login feito e não loga de novo.
- Sessão que cai no meio do dia: quem percebe pede `caiu=True`; os pedidos
  que chegam juntos fazem UM relogin só (quem esperava vê que a verificação
  é posterior ao seu pedido).

Nunca `POST /users/login` por HTTP: derrubaria a sessão do Chrome.

PLAYWRIGHT: sync só serve na thread que o criou, e quem pede (a vaga do
Anexar, a dona da aba de leitura) já tem o seu. Por isso o trabalho na aba do
login roda numa thread PRÓPRIA, de vida curta, com Playwright próprio, e
quem pediu só espera o resultado.
"""
from __future__ import annotations

import contextlib
import threading
import time

from . import central, login_tela
from .sessao import ErpErro

URL_DASHBOARD = "https://acessar.maiscontroleerp.com.br/#/app/dashboard"
URL_LOGIN = "https://acessar.maiscontroleerp.com.br/#/login"
#: Marca da aba do login principal (sobrevive às navegações da aba).
MARCA = "mc-login-principal"
#: Depois do recarregar, quanto esperar antes de olhar a tela (o Firebase
#: devolve o token do IndexedDB de forma assíncrona; o MCClient espera 2,5 s).
CARENCIA = 3.0
#: Depois do `login()`, quanto esperar a tela de login sumir.
PRAZO_LOGIN = 90.0
#: Quanto esperar a trava de arquivo de outro processo.
ESPERA_TRAVA = 180.0
#: Verificação recente vale para quem não viu a sessão cair.
VALIDADE = 30.0

_TRAVAS: dict[str, threading.Lock] = {}
_TRAVA_DAS_TRAVAS = threading.Lock()
#: Quando a sessão foi vista de pé (ou o login terminou), por acesso.
_ULTIMO_OK: dict[str, float] = {}


def _trava_do_processo(nome: str) -> threading.Lock:
    with _TRAVA_DAS_TRAVAS:
        return _TRAVAS.setdefault(nome, threading.Lock())


def esquecer() -> None:
    """Zera as verificações guardadas (testes)."""
    with _TRAVA_DAS_TRAVAS:
        _ULTIMO_OK.clear()


def garantir_logado(acesso, *, caiu: bool = False, log=None, abrir_pagina=None,
                    credencial=None, trava_arquivo=None, dormir=time.sleep,
                    relogio=time.monotonic) -> bool:
    """Garante a sessão do Chrome central do `acesso`. True = entrou agora.

    `caiu=True`: quem chama viu a tela de login; a verificação recente não
    vale, a não ser que tenha sido feita DEPOIS deste pedido (outro já
    relogou enquanto este esperava). Levanta `ErpErro` com o motivo.

    `abrir_pagina`, `credencial`, `trava_arquivo`, `dormir` e `relogio` são
    para os dublês dos testes."""
    log = log or (lambda _m: None)
    nome = acesso.nome
    pedido = relogio()
    with _trava_do_processo(nome):
        ultimo = _ULTIMO_OK.get(nome)
        if ultimo is not None and (ultimo >= pedido or
                                   (not caiu and relogio() - ultimo < VALIDADE)):
            return False
        abrir_pagina = abrir_pagina or (lambda: _AbaPrincipal(acesso))
        credencial = credencial or (lambda: login_tela.credencial_do_acesso(acesso, log))
        trava_arquivo = trava_arquivo or (lambda: central.trava(
            login_tela.caminho_da_trava(acesso), espera=ESPERA_TRAVA,
            velha=login_tela.VELHA_TRAVA))
        entrou = _na_thread_propria(
            lambda: _verificar_e_entrar(nome, abrir_pagina, credencial,
                                        trava_arquivo, log, dormir, relogio))
        _ULTIMO_OK[nome] = relogio()
        return entrou


def _na_thread_propria(trabalho):
    """Roda `trabalho` numa thread nova (Playwright próprio) e devolve o
    resultado, ou levanta a exceção dela na thread de quem pediu."""
    caixa: dict = {}

    def rodar():
        try:
            caixa["ok"] = trabalho()
        except BaseException as e:            # vai para quem pediu
            caixa["erro"] = e
    t = threading.Thread(target=rodar, daemon=True, name="erp-login-principal")
    t.start()
    t.join()
    if "erro" in caixa:
        raise caixa["erro"]
    return caixa.get("ok", False)


def _fora(page, dormir) -> bool:
    """A tela de login está à vista, passada a carência?"""
    dormir(CARENCIA)
    return login_tela.tem_sinal_de_login(page)


def _recarregar(page, url: str) -> None:
    try:
        page.goto(url, wait_until="commit")
    except Exception:
        pass                       # quem decide é o que a tela mostra depois
    try:
        page.reload(wait_until="commit")
    except Exception:
        pass


def _verificar_e_entrar(nome, abrir_pagina, credencial, trava_arquivo, log,
                        dormir, relogio) -> bool:
    with abrir_pagina() as page:
        _recarregar(page, URL_DASHBOARD)
        if not _fora(page, dormir):
            return False                              # o porteiro, ou outra aba
        try:
            with trava_arquivo():
                # Quem tinha a trava pode ter acabado de entrar.
                _recarregar(page, URL_DASHBOARD)
                if not _fora(page, dormir):
                    return False
                _entrar(nome, page, credencial, log, dormir, relogio)
        except TimeoutError as e:
            log(f"trava de login do acesso '{nome}': {e}")
            raise ErpErro("outro robô está entrando no ERP há muito tempo pelo "
                          f"Chrome central '{nome}'; tente de novo") from e
        return True


def _entrar(nome, page, credencial, log, dormir, relogio) -> None:
    try:
        page.goto(URL_LOGIN, wait_until="commit")
    except Exception:
        pass
    creds = credencial()
    if not creds:
        raise ErpErro(
            f"o Chrome central '{nome}' está fora do ERP e não há login "
            "guardado: entre no ERP pelo app uma vez (Minha aba no ERP) para "
            "guardar o login")
    disparou = login_tela.entrar_pelo_controller(page, creds[0], creds[1], diag=log)
    del creds                                     # a senha não fica guardada
    if not disparou:
        raise ErpErro(
            f"o login automático no Chrome central '{nome}' não rodou (a tela "
            "de login do ERP pode ter mudado) — entre no ERP pelo app (Minha "
            "aba no ERP) e tente de novo")
    limite = relogio() + PRAZO_LOGIN
    while login_tela.tem_sinal_de_login(page):
        if relogio() >= limite:
            raise ErpErro(
                f"entrei com o login guardado no Chrome central '{nome}', mas o "
                "ERP continuou na tela de login — se a senha mudou, guarde de "
                "novo em Minha aba no ERP")
        dormir(1.0)
    try:
        page.goto(URL_DASHBOARD, wait_until="commit")   # termina parada aqui
    except Exception:
        pass
    log(f"login principal: entrei no ERP pelo Chrome central '{nome}'")


class _AbaPrincipal:
    """A aba do login principal no Chrome central, marcada por `window.name`.

    Reaproveitada de uma vez para a outra (não acumula abas) e DEIXADA
    aberta na saída, parada no painel: só desconecta. Nunca fecha o Chrome
    nem o contexto (derrubaria todo mundo)."""

    def __init__(self, acesso):
        self.acesso = acesso
        self._pw = None

    def __enter__(self):
        from playwright.sync_api import sync_playwright   # tarde: módulo leve
        self._pw = sync_playwright().start()
        try:
            browser = self._pw.chromium.connect_over_cdp(
                central.garantir_chrome(self.acesso))
            ctx = browser.contexts[0]
            for p in list(ctx.pages):
                with contextlib.suppress(Exception):
                    if p.evaluate("() => window.name") == MARCA:
                        return p
            p = ctx.new_page()
            with contextlib.suppress(Exception):
                p.goto(URL_DASHBOARD, wait_until="commit")
            with contextlib.suppress(Exception):
                p.evaluate("(m) => { window.name = m; }", MARCA)
            return p
        except Exception:
            self._pw.stop()
            raise

    def __exit__(self, *exc):
        self._pw.stop()
        return False
