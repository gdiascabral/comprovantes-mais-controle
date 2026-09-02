# -*- coding: utf-8 -*-
"""Onde o Mais Controle mora. Só endereços — este módulo não fala com ninguém.

As mesmas quatro URLs estavam escritas em sete arquivos, e a repetição já tinha
custo: quem corrige uma cópia não sabe das outras. O inventário está em
`docs/ERP-CLIENTES.md`; aqui ficam os endereços que ele levantou.

    acessar.        a TELA (single-spa: AngularJS no login, React no resto).
                    É dela que saem `origin` e `referer` das chamadas HTTP.
    prod-erp-api.   o back-end NOVO (REST): contas, saldos, participantes,
                    anexos, obras.
    legacy-api.     o back-end LEGADO: login, parcelas, recebimentos,
                    categorias, formas e condições de pagamento.

A raiz `/maiscontrole/services` faz parte do endereço do legado, e não é
detalhe: sem ela o caminho não existe.
"""
from __future__ import annotations

from urllib.parse import urlsplit

#: A tela. Origem e referência de toda chamada HTTP direta — o WAF confere.
ACESSAR = "https://acessar.maiscontroleerp.com.br"

#: Back-end novo (REST). Quer `jwtToken` — ver `sessao.token_para`.
ERP_API = "https://prod-erp-api.maiscontroleerp.com.br"

#: Back-end legado, com a raiz de serviço já embutida. Quer `accessToken`.
LEGACY = "https://legacy-api.maiscontroleerp.com.br/maiscontrole/services"

HOST_ACESSAR = "acessar.maiscontroleerp.com.br"
HOST_ERP_API = "prod-erp-api.maiscontroleerp.com.br"
HOST_LEGACY = "legacy-api.maiscontroleerp.com.br"

#: O login mora no LEGADO e é a única chamada que não leva token nenhum.
#: Ele devolve os dois tokens de uma vez (ver `sessao.Sessao.de_login`).
URL_LOGIN = f"{LEGACY}/users/login"

#: Os dois back-ends de cadastro, e quem captura cabeçalhos precisa dos DOIS.
#: O `prod-erp-api` serve contas e participantes; o `legacy-api` serve
#: categorias, formas e condições — e é o único que manda o `user-id`, que é o
#: responsável pelo lançamento. Esperar só pelo primeiro dava 401 no segundo e,
#: logo depois, "não achei o usuário responsável" — dois sintomas de uma causa.
#: (Veio de `aportes/erp_sessao.py:25-32`.)
HOSTS_CADASTRO = (HOST_ERP_API, HOST_LEGACY)

#: Telemetria: carrega token PRÓPRIO. Misturar com os demais fez o
#: `prod-erp-api` devolver 401 numa rodada anterior — o token de um host NÃO
#: vale noutro. (Veio de `aportes/erp_sessao.py:21-23`.)
HOSTS_IGNORAR = ("api-data-event", "faro.", "satismeter", "datadog", "google")


def host_de(url_ou_host: str) -> str:
    """O host de uma URL. Recebendo um host, devolve o próprio.

    Aceita os dois porque quem chama às vezes tem a URL inteira (o transporte)
    e às vezes só o host (o dicionário de cabeçalhos capturados do navegador,
    que é indexado por host).
    """
    texto = (url_ou_host or "").strip()
    if "//" in texto:
        return urlsplit(texto).netloc
    return texto.split("/")[0]


def eh_erp_api(url_ou_host: str) -> bool:
    """É o back-end novo (`prod-erp-api`)?"""
    return host_de(url_ou_host) == HOST_ERP_API


def eh_legacy(url_ou_host: str) -> bool:
    """É o back-end legado (`legacy-api`)?"""
    return host_de(url_ou_host) == HOST_LEGACY


def vale_a_pena(host: str) -> bool:
    """Host do ERP de que vale copiar a autenticação do navegador.

    Inclui os `execute-api` (GraphQL): é neles que moram as obras, e sem o
    token deles o catálogo de obras volta vazio. Exclui os de telemetria, que
    trazem token próprio. (Veio de `aportes/erp_sessao.py:49-57`.)
    """
    host = host_de(host)
    if any(x in host for x in HOSTS_IGNORAR):
        return False
    return host.endswith("maiscontroleerp.com.br") or "execute-api" in host
