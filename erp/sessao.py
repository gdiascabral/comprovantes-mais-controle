# -*- coding: utf-8 -*-
"""Quem fala com o ERP: os dois tokens, os cabeçalhos por host, e o transporte.

Tudo que os oito consumidores redescobriram por conta própria mora aqui, uma
vez só. O inventário que levantou cada regra — com a evidência em
`arquivo:linha` — está em `docs/ERP-CLIENTES.md`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import hosts

__all__ = ["USER_AGENT", "ErpErro", "Sessao", "SessaoRecusada"]

#: O `user-agent` é OBRIGATÓRIO, e é a única coisa que separa 200 de 403:
#:
#:     COM user-agent de Chrome ......... 200
#:     SEM user-agent (Python-urllib) ... 403, pagina HTML do WAF
#:
#: Medido em `conciliacao/erp/api.py:23-29`. O WAF nunca implicou com HTTP
#: puro — implica com quem se identifica como robô; é o mesmo guarda que
#: recusa o navegador em modo headless (`conciliacao/erp/browser.py:5-8`).
#: Se um dia ele apertar, é aqui que se mexe.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

#: Generoso porque a alternativa é pior: uma leitura que desiste cedo custa a
#: rodada inteira, e o ERP fica lento em lote.
ESPERA = 45


class ErpErro(RuntimeError):
    """Raiz de tudo que pode dar errado ao falar com o ERP."""


class SessaoRecusada(ErpErro):
    """O ERP recusou a identidade: senha errada, sessão vencida, 401.

    Nome próprio porque o desfecho é outro: aqui a pessoa precisa entrar de
    novo, e repetir a chamada não resolve.
    """


def _montar_sessao() -> requests.Session:
    """Uma conexão viva por execução, com nova tentativa automática em 5xx.

    **Só GET repete.** Reenviar um POST que criou algo e perdeu a resposta
    duplica o que foi criado — e aqui os POSTs criam lançamento, criam baixa e
    movem dinheiro (`aportes/mc_lancamentos.py`, `pagamentos_dia/baixa_erp.py`).
    Quem chama um POST vê a falha uma vez e decide se tenta de novo.

    `raise_on_status=False`: esgotadas as tentativas, a ÚLTIMA resposta 5xx
    volta como resposta comum, para quem chama traduzir status em exceção
    NOMEADA num lugar só — duplicar essa tradução aqui criaria duas fontes
    para a mesma regra.

    É a MESMA política de `nuvem/rest.py:_montar_sessao` (3 tentativas, 502 a
    504), e a repetição não é acaso: um 504 real do `prod-erp-api` já custou
    uma rodada de conciliação, e `conciliacao/erp/api.py:69-81` teve de
    escrevê-la à mão por falar via `urllib.request`. Aqui, falando por
    `requests`, o `Retry` vem pronto.
    """
    sessao = requests.Session()
    sessao.mount("https://", HTTPAdapter(max_retries=politica()))
    return sessao


def politica() -> Retry:
    """A política de novas tentativas, exposta para poder ser conferida.

    Sem isto, "GET repete e POST não" seria uma frase de comentário. Com ela,
    `politica().is_retry("POST", 504)` responde por escrito — é a mesma função
    que o urllib3 chama para decidir.
    """
    return Retry(
        total=3,
        backoff_factor=1,
        status_forcelist=[502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )


#: O pacote inteiro fala com o mesmo ERP, então uma sessão só basta — e é o
#: ponto único que os testes trocam para simular o transporte.
_SESSAO = _montar_sessao()


@dataclass
class Sessao:
    """Uma identidade no ERP: os dois tokens e os três campos de identidade.

    Nasce de `logar()` (que faz o `POST /users/login`) ou de `de_login()`, que
    recebe o corpo desse login já pronto — é o que permite testar sem rede e o
    que deixa o `conciliacao/erp/api.py`, que já loga, migrar sem relogar.
    """

    jwt_token: str = ""
    access_token: str = ""
    company_id: str = ""
    user_id: str = ""
    organization_unit_id: str = ""
    usuario: str = ""
    empresa: str | None = None
    #: Qualquer coisa com `.request(metodo, url, headers=…, json=…, timeout=…)`.
    #: `None` usa a sessão do módulo; os testes injetam a sua.
    transporte: object | None = field(default=None, repr=False)

    # ----------------------------------------------------------------- login

    @classmethod
    def de_login(cls, corpo: dict, *, transporte=None) -> "Sessao":
        """Monta a sessão a partir do corpo do `POST /users/login`.

        O login é UM só e devolve OS DOIS tokens, mais a identidade inteira —
        `companies[0].id`, `id` e `organizationUnitId`. É por isso que quem
        fala por HTTP direto não precisa de navegador para ter os quatro
        cabeçalhos que o legado exige: eles saem daqui
        (`fontes/vigia-boletos/mc_sessao.py:114-117`).
        """
        corpo = corpo or {}
        empresas = corpo.get("companies") or []
        if not empresas:
            raise ErpErro("o login nao devolveu nenhuma empresa (companies vazio).")
        if corpo.get("mfaEnabled"):
            raise SessaoRecusada(
                "esta conta passou a exigir segundo fator (MFA).\n"
                "O login automatico nao passa por MFA — me avise para ajustar."
            )
        if corpo.get("needsPasswordChange"):
            raise SessaoRecusada(
                "o ERP esta exigindo troca de senha deste usuario.\n"
                "Entre no site, troque a senha e guarde a nova."
            )
        primeira = empresas[0] or {}
        return cls(
            jwt_token=str(corpo.get("jwtToken") or ""),
            access_token=str(corpo.get("accessToken") or ""),
            company_id=str(primeira.get("id") or ""),
            user_id=str(corpo.get("id") or ""),
            organization_unit_id=str(corpo.get("organizationUnitId") or ""),
            usuario=str(corpo.get("username") or ""),
            empresa=primeira.get("tradeName") or primeira.get("name"),
            transporte=transporte,
        )

    @classmethod
    def logar(cls, email: str, senha: str, *, transporte=None) -> "Sessao":
        """`POST {legacy}/users/login`. É a única chamada sem token nenhum."""
        if not (email and senha):
            raise SessaoRecusada("sem credenciais para entrar no Mais Controle.")
        corpo = _pedir(
            hosts.URL_LOGIN,
            metodo="POST",
            corpo={"username": email, "password": senha},
            cabecalhos=cabecalhos_base(),
            transporte=transporte,
        )
        sessao = cls.de_login(corpo, transporte=transporte)
        if not sessao.usuario:
            sessao.usuario = email
        return sessao

    # ------------------------------------------------------- a regra central

    def token_para(self, url_ou_host: str) -> str:
        """O token que ESTE host aceita. Trocar os dois devolve 401.

        A regra, escrita uma vez:

            prod-erp-api  ->  jwtToken     (~348 chars, JWT, vale 24 h)
            legacy-api    ->  accessToken  (27 chars, nem é JWT, vive segundos)

        As duas evidências, cada uma no arquivo que a sustenta:

        1. `conciliacao/erp/api.py:33` — "O TOKEN E O `jwtToken` (~348 chars),
           NAO o `accessToken` (27 chars, que nem e JWT)". E o código faz isso:
           pega `jwtToken` do login (`:120`) e o usa só contra o `prod-erp-api`
           (`:175` contas, `:200` saldos).
        2. `fontes/vigia-boletos/mc_sessao.py:8-9` — "jwtToken (348 chars) ->
           API nova. **Na legada da 401 invalid_token.** accessToken (27
           chars) -> API legada." E o código faz isso: guarda `accessToken`
           (`:111-114`) e só chama o `legacy-api`.

        Os dois estavam certos, para back-ends diferentes, e nenhum dizia isso
        inteiro. Vale igual para o token capturado do navegador: reaproveitar
        o cabeçalho de um host noutro dá 401 — foi assim que o token da
        telemetria acabou usado contra o `prod-erp-api`
        (`aportes/mc_catalogos.py:124-127`).
        """
        if hosts.eh_legacy(url_ou_host):
            return self.access_token
        return self.jwt_token

    def cabecalhos_para(self, url_ou_host: str, extras: dict | None = None) -> dict:
        """Os cabeçalhos que ESTE host exige, prontos para sair.

        São conjuntos diferentes, e a diferença já custou duas falhas:

            prod-erp-api  ->  authorization, company-id
            legacy-api    ->  authorization, company-id, user-id,
                              organization-unit-id

        **Só o legado manda `user-id`** (`aportes/mc_catalogos.py:171-172`), e
        é ele o responsável pelo lançamento: sem o cabeçalho, o ERP recusa com
        "não achei o usuário responsável", que não aponta para lugar nenhum.
        A mesma divisão está medida fora do app, em
        `agua_energia/coletor/lancar_mc.py:76-77`.

        O `authorization` sai do `token_para`, então errar o host não é
        possível sem errar os dois juntos.
        """
        cabecalhos = cabecalhos_base()
        token = self.token_para(url_ou_host)
        if token:
            cabecalhos["authorization"] = f"Bearer {token}"
        if self.company_id:
            cabecalhos["company-id"] = self.company_id
        if hosts.eh_legacy(url_ou_host):
            if self.user_id:
                cabecalhos["user-id"] = self.user_id
            if self.organization_unit_id:
                cabecalhos["organization-unit-id"] = self.organization_unit_id
        cabecalhos.update(extras or {})
        return cabecalhos

    # ------------------------------------------------------------ transporte

    def pedir(self, url: str, *, metodo: str = "GET", corpo=None,
              extras: dict | None = None):
        """Chamada autenticada por HTTP direto, sem navegador.

        Quem repete é o transporte, e só em GET — ver `_montar_sessao`.
        """
        return _pedir(url, metodo=metodo, corpo=corpo,
                      cabecalhos=self.cabecalhos_para(url, extras),
                      transporte=self.transporte)


def cabecalhos_base() -> dict:
    """O que TODA chamada leva, com ou sem sessão.

    O `user-agent` é o que separa 200 de 403; `origin` e `referer` apontam
    para a TELA, que é de onde o ERP espera ser chamado.
    """
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "pt-BR",
        "content-type": "application/json",
        "origin": hosts.ACESSAR,
        "referer": hosts.ACESSAR + "/",
        "user-agent": USER_AGENT,
    }


def _pedir(url: str, *, metodo: str, corpo, cabecalhos: dict, transporte=None):
    """Uma chamada HTTP, com o status traduzido em exceção NOMEADA.

    A tradução mora aqui e só aqui: o transporte devolve a última resposta 5xx
    como resposta comum (`raise_on_status=False`), e duplicar a leitura de
    status criaria duas fontes para a mesma regra.
    """
    alvo = transporte if transporte is not None else _SESSAO
    try:
        resposta = alvo.request(metodo, url, headers=cabecalhos,
                                json=corpo, timeout=ESPERA)
    except requests.RequestException as e:
        raise ErpErro(f"nao deu para falar com o ERP: {e}") from e

    codigo = getattr(resposta, "status_code", 0)
    if codigo in (401, 403) and "/users/login" in url:
        raise SessaoRecusada(
            "o ERP recusou a senha guardada.\n"
            "Guarde a senha correta e tente de novo."
        )
    if codigo == 403:
        raise ErpErro(
            "403 do WAF do Mais Controle. Quase sempre e o cabecalho\n"
            "'user-agent' — confira a constante USER_AGENT em erp/sessao.py."
        )
    if codigo == 401:
        raise SessaoRecusada("a sessao do ERP foi recusada (401).")
    if codigo >= 400:
        detalhe = (getattr(resposta, "text", "") or "")[:200]
        raise ErpErro(f"HTTP {codigo} ao chamar {url.split('?')[0]}\n{detalhe}")
    try:
        return resposta.json()
    except ValueError as e:
        # 200 que não é JSON costuma ser página de manutenção, do WAF, ou
        # portal de wi-fi sequestrando a conexão. É problema de rede.
        raise ErpErro(f"o ERP respondeu algo que nao e JSON ({e})") from e
