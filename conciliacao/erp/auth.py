"""Login no ERP.

POR QUE O LOGIN ACONTECE A CADA EXECUCAO
----------------------------------------
O Mais Controle nao persiste sessao em disco: nao ha cookie de autenticacao,
nao ha token em localStorage nem em sessionStorage, e o unico registro do
Firebase no perfil e do projeto de notificacoes. O token de acesso vive apenas
na memoria da aba. Logo, fechar o navegador encerra a sessao — e nao existe
"logar uma vez hoje e coletar amanha".

POR QUE ENTRAMOS PELA TELA DE LOGIN
-----------------------------------
Pedir uma rota interna (#/accounts) sem sessao faz o ERP exibir
"Seu usuario nao tem permissao para acessar esta pagina". Isso e o guard de
rota reagindo a falta de sessao, NAO um problema de permissao da conta. Por
isso o fluxo comeca em #/login e so navega para as telas depois de entrar.

ORDEM DAS ESTRATEGIAS DE LOGIN
------------------------------
  1. credenciais no cofre do Windows / variaveis de ambiente;
  2. preenchimento automatico do proprio navegador — se o perfil ja tem a
     senha salva, basta clicar ENTRAR e nada precisa ser guardado por nos;
  3. login manual, com a janela aberta (o programa espera e segue sozinho).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from playwright.sync_api import Page

from ..errors import ErpError, SessaoExpirada

try:                                     # utilitarios compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando a Conciliacao isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    import util

#: O diagnostico do modulo. `entrar()` e `garantir_login()` recebem um `log`
#: PROPRIO — o recado que aparece na tela de quem esta olhando — e o parametro
#: SOMBREIA este nome la dentro; nesses dois o diagnostico sai por `_diag`, que
#: e este mesmo logger com outro nome. Traceback vai para o arquivo, nunca para
#: a tela de quem so quer saber se entrou.
log = util.log(__name__)
_diag = log

#: Nome do servico no cofre de credenciais do Windows.
SERVICO_KEYRING = "conciliacao-mais-controle"

# IDs reais da tela de login. Nao usar seletores genericos por tipo: a pagina
# tem um segundo formulario ("esqueci a senha", input #fgtemail) que fica oculto
# e seria preenchido por engano.
_SEL_EMAIL = "#username"
_SEL_SENHA = "#userpassword"
_SEL_ENTRAR = 'button:has-text("ENTRAR"):visible'

# Login pelo controller AngularJS, nao pela UI.
#
# POR QUE NAO BASTA PREENCHER E CLICAR: preencher os inputs com o Playwright
# altera o DOM mas nao propaga para o `ng-model`, entao `$ctrl.credentials`
# continua vazio. O botao ENTRAR ainda assim fica habilitado, porque o
# ng-disabled dele aceita `$ctrl.getAutoFill()` como alternativa:
#
#   ng-disabled="$ctrl.waiting || !((credentials.username && credentials.password)
#                                    || $ctrl.getAutoFill())"
#
# Resultado: o clique chamava `$ctrl.login()` com credenciais vazias e falhava
# em silencio — sem requisicao de rede e sem mensagem de erro na tela.
# Escrever direto no scope e chamar login() elimina esse buraco.
_JS_LOGIN = """
(dados) => {
  if (typeof angular === 'undefined') return {ok: false, motivo: 'AngularJS ausente'};
  const campo = document.querySelector('#username')
             || document.querySelector('#userpassword');
  if (!campo) return {ok: false, motivo: 'campos de login nao encontrados'};

  let escopo = null;
  try { escopo = angular.element(campo).scope(); } catch (e) {
    return {ok: false, motivo: 'scope inacessivel: ' + e.message};
  }
  while (escopo && !escopo.$ctrl) escopo = escopo.$parent;
  if (!escopo || !escopo.$ctrl || typeof escopo.$ctrl.login !== 'function') {
    return {ok: false, motivo: 'controller de login nao encontrado'};
  }

  const ctrl = escopo.$ctrl;
  escopo.$apply(() => {
    ctrl.credentials = ctrl.credentials || {};
    ctrl.credentials.username = dados.email;
    ctrl.credentials.password = dados.senha;
  });
  if (!ctrl.credentials.username || !ctrl.credentials.password) {
    return {ok: false, motivo: 'nao consegui gravar as credenciais no scope'};
  }
  try { ctrl.login(); } catch (e) {
    return {ok: false, motivo: 'login() lancou: ' + e.message};
  }
  return {ok: true};
}
"""


def obter_credenciais() -> tuple[str | None, str | None]:
    """E-mail/senha do ERP, na ordem: ambiente, login do app, cofre do Windows.

    Dentro do app a credencial vem do `login.dat` (DPAPI), a mesma que o Anexar
    já usa: o ERP aceita uma sessao por usuario, entao ter duas senhas
    guardadas em lugares diferentes so cria a chance de uma envelhecer e o erro
    aparecer como "login invalido" sem motivo aparente.

    O keyring continua no fim da fila para os `.bat`, que rodam fora do app.
    """
    email = os.environ.get("MC_EMAIL")
    senha = os.environ.get("MC_SENHA")
    if email and senha:
        return email, senha

    try:                              # login salvo do app (cifrado pela DPAPI)
        import credenciais as _cred_app

        guardado = _cred_app.carregar()
        if guardado and guardado[0] and guardado[1]:
            return guardado
    except Exception:
        pass                          # fora do app, ou sem login salvo

    try:
        import keyring
    except ImportError:
        return email, None

    try:
        email = email or keyring.get_password(SERVICO_KEYRING, "email")
        if email:
            senha = keyring.get_password(SERVICO_KEYRING, email)
    except Exception:
        # Nem o e-mail nem a senha entram na mensagem: sao a credencial do ERP,
        # e o `diagnostico.log` e um arquivo comum na pasta do exe.
        log.warning("lendo as credenciais no cofre do Windows", exc_info=True)
        return email, None
    return email, senha


def salvar_credenciais(email: str, senha: str) -> None:
    """Guarda as credenciais no Gerenciador de Credenciais do Windows."""
    try:
        import keyring
    except ImportError as exc:  # pragma: no cover - depende do ambiente
        raise ErpError(
            "o pacote 'keyring' nao esta instalado; rode:\n"
            "  .venv\\Scripts\\python.exe -m pip install keyring"
        ) from exc

    keyring.set_password(SERVICO_KEYRING, "email", email)
    keyring.set_password(SERVICO_KEYRING, email, senha)


def na_tela_de_login(pagina: Page) -> bool:
    try:
        return pagina.locator(_SEL_SENHA).first.is_visible(timeout=1500)
    except Exception:
        log.warning("olhando se a tela de login do ERP esta na frente",
                    exc_info=True)
        return False


def _dispensar_aviso(pagina: Page) -> None:
    """Fecha o modal "sem permissao" que o guard de rota deixa na tela."""
    try:
        pagina.keyboard.press("Escape")
        pagina.wait_for_timeout(300)
    except Exception:
        log.warning("fechando o aviso 'sem permissao' que o guard de rota "
                    "deixa na tela de login", exc_info=True)


def _saiu_do_login(pagina: Page, timeout_s: float) -> bool:
    """True quando o campo de senha desaparece — sinal de que entramos."""
    limite = time.monotonic() + timeout_s
    while time.monotonic() < limite:
        if not na_tela_de_login(pagina):
            pagina.wait_for_timeout(1500)  # deixa o app assentar
            return True
        pagina.wait_for_timeout(500)
    return False


def _campos_ja_preenchidos(pagina: Page) -> bool:
    """O navegador preencheu e-mail e senha sozinho?"""
    try:
        return bool(
            pagina.evaluate(
                """() => {
                  const email = document.querySelector('input[type=email], input[name=email]');
                  const senha = document.querySelector('input[type=password]');
                  return !!(email && senha && email.value && senha.value);
                }"""
            )
        )
    except Exception:
        log.warning("perguntando a tela se o navegador ja preencheu o login",
                    exc_info=True)
        return False


def _clicar_entrar(pagina: Page) -> None:
    pagina.locator(_SEL_ENTRAR).first.click()


def _autenticar(pagina: Page, email: str, senha: str) -> None:
    """Preenche os campos e dispara o login pelo controller do AngularJS."""
    # Preenche tambem os inputs para a tela refletir o que esta acontecendo.
    try:
        pagina.fill(_SEL_EMAIL, email)
        pagina.fill(_SEL_SENHA, senha)
    except Exception:
        pass  # o que vale e o scope, preenchido abaixo

    resultado = pagina.evaluate(_JS_LOGIN, {"email": email, "senha": senha})
    if not resultado.get("ok"):
        raise ErpError(f"nao consegui acionar o login: {resultado.get('motivo')}")


def entrar(
    pagina: Page,
    config,
    *,
    visivel: bool,
    espera_manual_s: float = 300.0,
    log=print,
) -> None:
    """Entra no ERP. Chame ANTES de navegar para qualquer tela interna."""
    base = str(config.erp["base_url"]).rstrip("/")
    pagina.goto(f"{base}/#/login", wait_until="domcontentloaded")
    pagina.wait_for_timeout(3000)
    _dispensar_aviso(pagina)

    if not na_tela_de_login(pagina):
        return

    # 1. Credenciais que nos guardamos.
    email, senha = obter_credenciais()
    if email and senha:
        log("Entrando com a senha guardada no cofre do Windows...")
        _autenticar(pagina, email, senha)

        if _saiu_do_login(pagina, 45.0):
            log("  login efetuado.")
            return
        raise SessaoExpirada(
            "o ERP nao aceitou a senha guardada.\n"
            "Rode o atalho '1 - Salvar senha' de novo para corrigi-la."
        )

    # 2. O proprio navegador ja preencheu: basta clicar ENTRAR.
    if _campos_ja_preenchidos(pagina):
        log("O navegador ja preencheu o login; clicando em ENTRAR...")
        try:
            _clicar_entrar(pagina)
        except Exception:
            _diag.warning("clicando em ENTRAR com o login que o navegador "
                          "preencheu", exc_info=True)
        if _saiu_do_login(pagina, 45.0):
            log("  login efetuado.")
            return
        log("  nao funcionou; vou esperar voce entrar na janela.")

    # 3. Login manual.
    if not visivel:
        raise SessaoExpirada(
            "o ERP pediu login e nao ha credenciais guardadas.\n"
            "Como o Mais Controle nao mantem sessao salva, o login e necessario\n"
            "a cada execucao. Escolha um dos dois:\n"
            "  - guardar a senha no cofre do Windows (atalho '1 - Salvar senha')\n"
            "    para o programa entrar sozinho; ou\n"
            "  - rodar com a janela aberta e clicar em ENTRAR."
        )

    log("")
    log("  >>> CLIQUE EM 'ENTRAR' NA JANELA DO NAVEGADOR.")
    log("      A senha costuma vir preenchida. Nao feche a janela:")
    log("      o programa continua sozinho assim que voce entrar.")
    log("")

    if _saiu_do_login(pagina, espera_manual_s):
        log("  login detectado, seguindo com a coleta.")
        return

    raise SessaoExpirada(f"nao detectei o login em {espera_manual_s / 60:.0f} minuto(s).")


def garantir_login(
    pagina: Page,
    config,
    *,
    seletor_sucesso: str,
    visivel: bool,
    log=print,
) -> None:
    """Salvaguarda para o meio do caminho: se cair no login, entra de novo."""
    limite = time.monotonic() + 12.0
    while time.monotonic() < limite:
        try:
            if pagina.locator(seletor_sucesso).first.is_visible(timeout=500):
                return
        except Exception:
            _diag.warning("procurando %s para saber se a sessao do ERP "
                          "continua de pe", seletor_sucesso, exc_info=True)
        if na_tela_de_login(pagina):
            entrar(pagina, config, visivel=visivel, log=log)
            return
        pagina.wait_for_timeout(500)
