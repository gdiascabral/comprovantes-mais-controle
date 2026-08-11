"""Sessao do browser.

DUAS RESTRICOES DO ERP DESCOBERTAS NA PRATICA
---------------------------------------------
1. NAO da para rodar sem janela. O WAF do Mais Controle recusa o navegador em
   modo headless: a chamada de login para `legacy-api.../users/login` volta como
   `net::ERR_FAILED` e o app quebra em `null.accessToken`. Com janela visivel a
   mesma chamada passa. Por isso o padrao e `visivel=True`.

2. NAO existe sessao reaproveitavel entre execucoes — o token vive so na memoria
   da aba (ver `auth.py`). O perfil persistente serve apenas para guardar
   preferencias e o autofill do navegador, nao a sessao.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from ..errors import ErpError, SessaoExpirada

__all__ = [
    "ErpError",
    "SessaoExpirada",
    "abrir_erp",
    "aguardar_sistema",
    "esta_logado",
    "exigir_sessao",
    "ir_para",
    "salvar_screenshot",
]

#: Marcadores de que caimos na tela de login em vez do sistema. O ERP tambem
#: mostra "nao tem permissao" quando a sessao morreu.
_SINAIS_DE_LOGIN = (
    'input[type="password"]',
    "text=Entre na sua conta",
    "text=não tem permissão",
)

# SELETORES DA TELA DE CONTAS (#/accounts) — levantados na tela real em
# 10/08/2026. O programa NAO usa mais nada disso: os saldos vem da API (ver
# `api.py`). Ficam registrados para o caso de um dia ser preciso voltar a
# raspar a tela, e para poupar a proxima investigacao.
#
# O ERP virou single-spa, com dois front-ends convivendo:
#     #single-spa-application:@mc/legacy-app  -> AngularJS 1.5.7 (tela de LOGIN)
#     #single-spa-application:@mc/react-app   -> React + MUI (tela de CONTAS)
#
# Por isso a tela de login continua respondendo ao truque do scope do Angular
# (ver `auth.py`) enquanto a de contas virou outro mundo.
SEL_CONTAS_LINHA = ".MuiDataGrid-row"          # cada linha tem data-id = UUID
SEL_CONTAS_OLHO = 'button[aria-label="Exibir valores"]'   # revela "R$ *******"
SEL_CONTAS_CELULA_NOME = '[data-field="name"]'
SEL_CONTAS_CELULA_SALDO = '[data-field="currentBalance"]'
# A grade mostra 10 por vez (opcoes 10/25/50) e a paginacao e do servidor.


@contextmanager
def abrir_erp(config, *, visivel: bool = False, timeout_ms: int | None = None):
    """Abre o ERP num perfil persistente e entrega a pagina pronta."""
    perfil = config.caminho("perfil_browser")
    perfil.mkdir(parents=True, exist_ok=True)
    timeout = timeout_ms or int(config.erp.get("timeout_ms", 30000))

    with sync_playwright() as p:
        contexto = p.chromium.launch_persistent_context(
            user_data_dir=str(perfil),
            headless=not visivel,
            viewport={"width": 1600, "height": 1000},
            locale="pt-BR",
            timezone_id="America/Sao_Paulo",
            args=[
                # Evita balões do Chrome (Windows Hello, "salvar senha?") que
                # roubam foco da janela durante a coleta.
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-features=PasswordManagerOnboarding,"
                "PasswordManagerRedesign,AutofillEnableAccountWalletStorage",
                "--disable-save-password-bubble",
            ],
        )
        contexto.set_default_timeout(timeout)
        pagina = contexto.pages[0] if contexto.pages else contexto.new_page()
        try:
            yield pagina
        finally:
            contexto.close()


def ir_para(pagina: Page, config, rota: str, *, assentar_ms: int = 2500) -> None:
    """Navega para uma rota do ERP.

    IMPORTANTE: nao usamos `wait_for_load_state("networkidle")`. O app mantem
    uma conexao Firebase aberta em tempo real, entao a rede NUNCA fica ociosa e
    a espera estoura por timeout mesmo com a pagina pronta. Quem espera de
    verdade sao os coletores, cada um pelo seu proprio seletor.
    """
    base = str(config.erp["base_url"]).rstrip("/")
    pagina.goto(f"{base}/{rota}", wait_until="domcontentloaded")
    pagina.wait_for_timeout(assentar_ms)


def esta_logado(pagina: Page) -> bool:
    for seletor in _SINAIS_DE_LOGIN:
        try:
            if pagina.locator(seletor).first.is_visible(timeout=1200):
                return False
        except Exception:
            continue
    return True


_MENSAGEM_SESSAO = (
    "a sessao do ERP expirou.\n"
    "Rode o comando de configuracao de sessao (ou o atalho "
    "'1 - Configurar acesso'), faca login na janela que abrir e feche-a."
)


def exigir_sessao(pagina: Page) -> None:
    if not esta_logado(pagina):
        raise SessaoExpirada(_MENSAGEM_SESSAO)


def aguardar_sistema(pagina: Page, seletor_sucesso: str, *, timeout_s: float = 45.0) -> None:
    """Espera o ERP assumir a sessao salva e renderizar a tela pedida.

    IMPORTANTE: o Firebase Auth restaura o token do IndexedDB de forma
    ASSINCRONA. Nos primeiros segundos o ERP mostra a tela de login (as vezes
    com "seu usuario nao tem permissao") mesmo com a sessao perfeitamente
    valida. Por isso NAO desistimos na primeira olhada — so declaramos sessao
    expirada se, esgotado o prazo, a tela de login continuar la.
    """
    # Conta elementos em vez de checar visibilidade do primeiro: a tabela de
    # contas tem uma <tr> extra oculta, e `first.is_visible()` dava sempre
    # False mesmo com a tela inteira carregada.
    limite = time.monotonic() + timeout_s
    while time.monotonic() < limite:
        try:
            if pagina.locator(seletor_sucesso).count() > 0:
                return
        except Exception:
            pass
        pagina.wait_for_timeout(500)

    if not esta_logado(pagina):
        raise SessaoExpirada(_MENSAGEM_SESSAO)
    raise ErpError(
        f"a tela do ERP nao carregou o esperado ({seletor_sucesso}) em {timeout_s:.0f}s.\n"
        "Pode ser lentidao do ERP ou mudanca de layout — veja o print em screenshots."
    )


def salvar_screenshot(pagina: Page, config, nome: str) -> Path:
    """Screenshot de diagnostico — a tela do ERP muda e erro cego nao ajuda."""
    pasta = config.caminho("screenshots")
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{nome}.png"
    try:
        pagina.screenshot(path=str(caminho), full_page=True)
    except Exception:
        return caminho
    return caminho
