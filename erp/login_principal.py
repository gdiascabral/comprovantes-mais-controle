# -*- coding: utf-8 -*-
"""O LOGIN PRINCIPAL do Chrome central: um caminho só, sempre primeiro.

Decisão do dono (28/10/2026), depois do diagnostico.log de 22 a 28/10: a aba
de leitura (`SessaoPelaPagina`) nascia na tela de login, em CORRIDA com o login
que a aba do Anexar fazia ao mesmo tempo, e desistia ("o porteiro precisa
entrar") — na abertura (conferência de contas novas) e no "Buscar pagamentos e
saldos". Agora, antes de qualquer trabalho no ERP, todos pedem AQUI:

    garantir_logado(acesso, log=...) -> bool   # True = entrou agora

- A decisão "está fora" é tomada na MESMA rota que o MCClient e a leitura
  usam (`#/payable-installments`, recarregada) e só com sinal FORTE de tela
  de login (campo de senha, "Entre na sua conta"). "não tem permissão"
  sozinho NUNCA dispara login: o ERP o mostra também com sessão boa.
- Logado (o porteiro de pé no servidor, ou outra aba já entrou): ninguém loga.
- Fora: UMA aba própria entra pela tela com o login guardado — o caminho
  provado do MCClient, `erp.login_tela` — e termina PARADA em
  `#/app/dashboard`. A aba nasce por `PUT /json/new` (não vem para a frente,
  ao contrário do `new_page()`), o id dela fica em `.<nome>.login.aba` ao
  lado do perfil e ela é achada de novo pelo targetId (CDP), nunca rodando
  JS nas abas dos outros.
- Os outros pedidos ESPERAM: no processo, por uma trava por acesso (com
  prazo); entre processos, pela trava de arquivo `.<nome>.login.trava`
  (`central.trava`, que recupera na hora a trava de pid morto). Quem
  esperava encontra o login feito e não loga de novo.
- Sessão que cai no meio do dia: quem percebe pede `caiu=True`; os pedidos
  que chegam juntos fazem UM relogin só.
- Login que FALHA fica em carência (`CARENCIA_FALHA`): durante ela, todo
  pedido recebe o mesmo `ErpErro` sem tentar de novo — falha não vira login
  a cada pedido.

Nunca `POST /users/login` por HTTP: derrubaria a sessão do Chrome.

PLAYWRIGHT: sync só serve na thread que o criou, e quem pede (a vaga do
Anexar, a dona da aba de leitura) já tem o seu. Por isso o trabalho na aba do
login roda numa thread PRÓPRIA, de vida curta, com Playwright próprio, e
quem pediu espera o resultado — com prazo (`PRAZO_TOTAL`).
"""
from __future__ import annotations

import contextlib
import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import central, login_tela
from .sessao import ErpErro
from .sessao_pagina import URL_CAPTURA

URL_DASHBOARD = "https://acessar.maiscontroleerp.com.br/#/app/dashboard"
URL_LOGIN = "https://acessar.maiscontroleerp.com.br/#/login"
#: Depois do recarregar, quanto esperar antes de olhar a tela (o Firebase
#: devolve o token do IndexedDB de forma assíncrona; o MCClient espera 2,5 s).
CARENCIA = 3.0
#: Depois do `login()`, quanto esperar a tela de login sumir.
PRAZO_LOGIN = 90.0
#: Quanto esperar a trava de arquivo de outro processo. Menor que a `velha`
#: (600 s) de propósito: trava de processo MORTO é recuperada na hora pelo
#: pid (`central.trava`); a de processo vivo é alguém entrando de verdade.
ESPERA_TRAVA = 180.0
#: Verificação recente vale para quem não viu a sessão cair.
VALIDADE = 30.0
#: Login que falhou: quanto tempo devolver o mesmo erro sem tentar de novo.
CARENCIA_FALHA = 60.0
#: Teto do trabalho inteiro na thread própria (trava + login + folga).
PRAZO_TOTAL = ESPERA_TRAVA + PRAZO_LOGIN + 60.0
#: Teto para esperar a vez dentro do processo (alguém já está no login).
PRAZO_TRAVA_PROCESSO = PRAZO_TOTAL + 30.0
#: Prazo de cada pedido HTTP ao endpoint de depuração do Chrome.
_PRAZO_HTTP = 5

_TRAVAS: dict[str, threading.Lock] = {}
_TRAVA_DAS_TRAVAS = threading.Lock()
#: Quando a sessão foi vista de pé (ou o login terminou), por acesso.
_ULTIMO_OK: dict[str, float] = {}
#: A última falha, por acesso: (instante, mensagem).
_FALHA: dict[str, tuple[float, str]] = {}


def _trava_do_processo(nome: str) -> threading.Lock:
    with _TRAVA_DAS_TRAVAS:
        return _TRAVAS.setdefault(nome, threading.Lock())


def esquecer() -> None:
    """Zera as verificações e as falhas guardadas (testes)."""
    with _TRAVA_DAS_TRAVAS:
        _ULTIMO_OK.clear()
        _FALHA.clear()


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
    trava = _trava_do_processo(nome)
    if not trava.acquire(timeout=PRAZO_TRAVA_PROCESSO):
        raise ErpErro(f"outro pedido de login no Chrome central '{nome}' está "
                      "demorando demais; tente de novo")
    try:
        falha = _FALHA.get(nome)
        if falha is not None and relogio() - falha[0] < CARENCIA_FALHA:
            raise ErpErro(falha[1])
        ultimo = _ULTIMO_OK.get(nome)
        if ultimo is not None and (ultimo >= pedido or
                                   (not caiu and relogio() - ultimo < VALIDADE)):
            return False
        abrir_pagina = abrir_pagina or (lambda: _AbaPrincipal(acesso))
        credencial = credencial or (lambda: login_tela.credencial_do_acesso(acesso, log))
        trava_arquivo = trava_arquivo or (lambda: central.trava(
            login_tela.caminho_da_trava(acesso), espera=ESPERA_TRAVA,
            velha=login_tela.VELHA_TRAVA))
        try:
            entrou = _na_thread_propria(
                lambda: _verificar_e_entrar(nome, abrir_pagina, credencial,
                                            trava_arquivo, log, dormir, relogio))
        except ErpErro as e:
            _FALHA[nome] = (relogio(), str(e))
            raise
        except Exception as e:
            erro = ErpErro(f"o login principal no Chrome central '{nome}' "
                           f"falhou: {type(e).__name__}: {str(e)[:160]}")
            _FALHA[nome] = (relogio(), str(erro))
            raise erro from e
        _FALHA.pop(nome, None)
        _ULTIMO_OK[nome] = relogio()
        return entrou
    finally:
        trava.release()


def _na_thread_propria(trabalho):
    """Roda `trabalho` numa thread nova (Playwright próprio) e devolve o
    resultado, ou levanta a exceção dela na thread de quem pediu. Passado
    `PRAZO_TOTAL`, desiste com `ErpErro` (a thread, daemon, segue sozinha)."""
    caixa: dict = {}

    def rodar():
        try:
            caixa["ok"] = trabalho()
        except BaseException as e:            # vai para quem pediu
            caixa["erro"] = e
    t = threading.Thread(target=rodar, daemon=True, name="erp-login-principal")
    t.start()
    t.join(PRAZO_TOTAL)
    if t.is_alive():
        raise ErpErro(f"o login principal não terminou em {PRAZO_TOTAL:.0f} s; "
                      "tente de novo")
    if "erro" in caixa:
        raise caixa["erro"]
    return caixa.get("ok", False)


def _fora(page, dormir) -> bool:
    """A tela de login está à vista, de CERTEZA, passada a carência?"""
    dormir(CARENCIA)
    return login_tela.tem_sinal_forte(page)


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
        # A MESMA rota do MCClient e da leitura, recarregada: é nela que a
        # queda aparece como tela de login (o single-spa repinta a casca sem
        # recarregar).
        _recarregar(page, URL_CAPTURA)
        if not _fora(page, dormir):
            return False                              # o porteiro, ou outra aba
        try:
            with trava_arquivo():
                # Quem tinha a trava pode ter acabado de entrar.
                _recarregar(page, URL_CAPTURA)
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
    while login_tela.tem_sinal_forte(page):
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


# ------------------------------------------------- a aba do login principal


def _arquivo_da_aba(acesso) -> Path:
    """Onde fica o targetId da aba do login principal deste acesso."""
    return Path(acesso.perfil).parent / f".{acesso.nome}.login.aba"


def _ids_abertos(endereco: str, abrir) -> set:
    pedido = urllib.request.Request(f"{endereco}/json/list")
    with abrir(pedido, timeout=_PRAZO_HTTP) as r:
        alvos = json.loads(r.read() or b"[]")
    return {t.get("id") for t in alvos
            if isinstance(t, dict) and t.get("type", "page") == "page"}


def _alvo_da_aba(acesso, endereco: str, *, abrir=urllib.request.urlopen) -> str:
    """O targetId da aba do login principal: a guardada, se ainda está
    aberta; senão uma nova, por `PUT /json/new` (o Chrome 111+ recusa GET; a
    URL vai escapada para o `#` não ser cortado), que não vem para a frente."""
    arq = _arquivo_da_aba(acesso)
    try:
        guardado = arq.read_text(encoding="utf-8").strip()
    except OSError:
        guardado = ""
    if guardado and guardado in _ids_abertos(endereco, abrir):
        return guardado
    url = f"{endereco}/json/new?{urllib.parse.quote(URL_CAPTURA, safe='')}"
    with abrir(urllib.request.Request(url, method="PUT"), timeout=_PRAZO_HTTP) as r:
        alvo = json.loads(r.read())["id"]
    with contextlib.suppress(OSError):
        arq.parent.mkdir(parents=True, exist_ok=True)
        arq.write_text(alvo, encoding="utf-8")
    return alvo


def _pagina_do_alvo(ctx, alvo: str):
    """A página do Playwright com esse targetId (por CDP, sem rodar JS nas
    abas — que podem ser da pessoa ou de outro robô), ou None."""
    for p in list(ctx.pages):
        try:
            sessao = ctx.new_cdp_session(p)
            try:
                info = sessao.send("Target.getTargetInfo")
            finally:
                with contextlib.suppress(Exception):
                    sessao.detach()
            if (info.get("targetInfo") or {}).get("targetId") == alvo:
                return p
        except Exception:
            continue
    return None


class _AbaPrincipal:
    """A aba do login principal no Chrome central.

    Reaproveitada de uma vez para a outra (não acumula abas) e DEIXADA
    aberta na saída, parada no painel: só desconecta. Nunca fecha o Chrome
    nem o contexto (derrubaria todo mundo)."""

    def __init__(self, acesso):
        self.acesso = acesso
        self._pw = None

    def __enter__(self):
        endereco = central.garantir_chrome(self.acesso)
        alvo = _alvo_da_aba(self.acesso, endereco)
        from playwright.sync_api import sync_playwright   # tarde: módulo leve
        self._pw = sync_playwright().start()
        try:
            browser = self._pw.chromium.connect_over_cdp(endereco)
            pagina = _pagina_do_alvo(browser.contexts[0], alvo)
            if pagina is None:
                raise ErpErro("a aba do login principal não apareceu no Chrome "
                              f"central '{self.acesso.nome}'; tente de novo")
            return pagina
        except BaseException:
            self._pw.stop()
            raise

    def __exit__(self, *exc):
        self._pw.stop()
        return False
