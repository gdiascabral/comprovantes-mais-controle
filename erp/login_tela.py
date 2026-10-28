# -*- coding: utf-8 -*-
"""Entrar no ERP pela TELA — o caminho provado do MCClient, num lugar só.

Até 28/10/2026 isto morava só em `anexar/mc_client.py`, e a aba de leitura do
Chrome central (`erp/sessao_pagina.py`) não sabia entrar: quando a página caía
no login ela desistia com "o porteiro precisa entrar", e no notebook não há
porteiro (diagnostico.log do dono, 22 a 28/10). Agora os dois entram pelo
MESMO código:

- `SINAIS_DE_LOGIN`: o que diz que a tela de login está à vista;
- `JS_LOGIN_ANGULAR` + `entrar_pelo_controller`: escreve no scope do AngularJS
  e chama `login()` (preencher o input não propaga para o ng-model, e o
  clique em ENTRAR chamava `login()` com credencial vazia, em silêncio);
- `credencial_do_acesso`: o login guardado (DPAPI) — o do acesso, se houver,
  senão o do app (`login.dat`). Nunca é impresso nem vai para o diagnóstico;
- `caminho_da_trava`: a trava de login entre processos, a mesma do água e
  energia (`<perfil>/../.<nome>.login.trava`).

Nunca `POST /users/login` por HTTP: o ERP aceita UMA sessão por usuário, e o
login por fora derruba a do Chrome. Entrar pela tela do próprio Chrome
central é o que o porteiro e o MCClient já fazem.
"""
from __future__ import annotations

import json
from pathlib import Path

#: Sinais de que a tela de LOGIN está à vista. A sessão é detectada pela
#: AUSÊNCIA deles, não pela presença de algo da área logada (o ERP é
#: single-spa, AngularJS no login e React no resto, e migra tela por tela).
SINAIS_DE_LOGIN = (
    'input[type="password"]',
    "text=Entre na sua conta",
    "text=não tem permissão",            # aparece enquanto o token não volta
)

#: Espera e `velha` da trava de login. `velha` acima do pior caso de um login
#: (cada `goto` tem 60 s, mais a espera de 90 s e as tentativas de rede): com
#: menos, a trava seria dada como abandonada no meio do uso.
VELHA_TRAVA = 600

JS_LOGIN_ANGULAR = r"""
(dados) => {
  if (typeof angular === 'undefined') return {ok: false, motivo: 'AngularJS ausente'};
  const campo = document.querySelector('#username')
             || document.querySelector('#userpassword')
             || document.querySelector('input[type=password]');
  if (!campo) return {ok: false, motivo: 'campos de login não encontrados'};
  let escopo = null;
  try { escopo = angular.element(campo).scope(); } catch (e) {
    return {ok: false, motivo: 'scope inacessível: ' + e.message};
  }
  while (escopo && !escopo.$ctrl) escopo = escopo.$parent;
  if (!escopo || !escopo.$ctrl || typeof escopo.$ctrl.login !== 'function') {
    return {ok: false, motivo: 'controller de login não encontrado'};
  }
  const ctrl = escopo.$ctrl;
  escopo.$apply(() => {
    ctrl.credentials = ctrl.credentials || {};
    ctrl.credentials.username = dados.email;
    ctrl.credentials.password = dados.senha;
  });
  if (!ctrl.credentials.username || !ctrl.credentials.password) {
    return {ok: false, motivo: 'não consegui gravar as credenciais no scope'};
  }
  try { ctrl.login(); } catch (e) {
    return {ok: false, motivo: 'login() lançou: ' + e.message};
  }
  return {ok: true};
}
"""


def _calado(_msg: str) -> None:
    pass


def tem_sinal_de_login(page) -> bool:
    """A tela de login está à vista nesta aba? Erro ao olhar = "não"."""
    for seletor in SINAIS_DE_LOGIN:
        try:
            if page.locator(seletor).first.is_visible(timeout=1200):
                return True
        except Exception:
            continue
    return False


def entrar_pelo_controller(page, email: str, senha: str, diag=None) -> bool:
    """Grava as credenciais no scope do AngularJS e chama `login()`.

    True se conseguiu DISPARAR o login (quem confirma que entrou é quem
    chamou, esperando a área logada); False com o motivo no `diag` — nunca a
    senha."""
    diag = diag or _calado
    try:
        page.fill("#username", email, timeout=3000)
        page.fill("#userpassword", senha, timeout=3000)
    except Exception:
        pass            # a tela é secundária: o que vale é o scope abaixo
    try:
        r = page.evaluate(JS_LOGIN_ANGULAR, {"email": email, "senha": senha})
    except Exception as e:
        diag(f"login pelo controller falhou: {type(e).__name__}: {str(e)[:120]}")
        return False
    if isinstance(r, dict) and r.get("ok"):
        return True
    motivo = r.get("motivo") if isinstance(r, dict) else r
    diag(f"login pelo controller não rodou: {motivo}")
    return False


def credencial_do_acesso(acesso, diag=None) -> tuple[str, str] | None:
    """(email, senha) para entrar no acesso, ou None.

    O acesso pode ter credencial própria (`credencial` no acessos.json, o
    mesmo JSON cifrado com DPAPI do login do app, noutro arquivo); sem ela,
    vale o login guardado do app (`login.dat`, botão "Minha aba no ERP")."""
    diag = diag or _calado
    arq = getattr(acesso, "credencial", None) if acesso is not None else None
    if arq is None or not Path(arq).exists():
        from anexar import credenciais          # tarde: só o app tem login.dat
        return credenciais.carregar()
    try:
        import util
        d = json.loads(util.revelar_bytes(Path(arq).read_bytes()).decode("utf-8"))
        return (d["email"], d["senha"])
    except Exception as e:
        # Só o tipo do erro: a mensagem de um JSON quebrado pode carregar um
        # pedaço do texto decifrado — e ali dentro está a senha.
        diag(f"credencial do acesso '{acesso.nome}' não pôde ser lida "
             f"({type(e).__name__}) — vai pedir login manual. "
             f"Arquivo: {Path(arq).name}")
        return None


def caminho_da_trava(acesso) -> Path:
    """`<perfil>/../.<nome>.login.trava` — a trava de login entre processos."""
    return Path(acesso.perfil).parent / f".{acesso.nome}.login.trava"
