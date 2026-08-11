# -*- coding: utf-8 -*-
"""Captura dos cabeçalhos de autenticação do ERP, num lugar só.

O Mais Controle bloqueia chamada HTTP feita de fora do navegador (403), então
tudo aqui depende de copiar os cabeçalhos que a PRÓPRIA página logada envia.
Esta regra de "quais cabeçalhos" e "de quais hosts" vivia em três cópias —
`aportes_frame.py`, `conferir_contas.py` e `teste_lancamento.py`.

Três cópias de uma regra de AUTENTICAÇÃO é pior do que parece: quando um host
novo entra (ou um de telemetria precisa sair), quem corrige uma cópia não sabe
das outras, e a que ficou para trás falha com 401 — erro que não aponta para
lugar nenhum.
"""
from __future__ import annotations

from urllib.parse import urlsplit

#: Os únicos cabeçalhos que interessam. O resto o navegador completa sozinho.
CABECALHOS = {"authorization", "company-id", "user-id", "organization-unit-id"}

#: Telemetria: carrega token PRÓPRIO. Misturar com os demais fez o
#: prod-erp-api devolver 401 numa rodada anterior.
HOSTS_IGNORAR = ("api-data-event", "faro.", "satismeter", "datadog", "google")


def host_util(host: str) -> bool:
    """Hosts do ERP dos quais vale copiar a autenticação.

    Inclui os `execute-api` (GraphQL): é neles que moram as obras, e sem o
    token deles o catálogo de obras volta vazio.
    """
    if any(x in host for x in HOSTS_IGNORAR):
        return False
    return host.endswith("maiscontroleerp.com.br") or "execute-api" in host


def cabecalhos_da_requisicao(req) -> tuple[str, dict] | None:
    """(host, cabeçalhos) de uma requisição que sirva; None se não servir.

    Serve quando o host é do ERP e a requisição carrega `authorization` — sem
    ele os cabeçalhos são inúteis."""
    try:
        host = urlsplit(req.url).netloc
    except Exception:
        return None
    if not host_util(host):
        return None
    cab = {k: v for k, v in req.headers.items() if k.lower() in CABECALHOS}
    if not any(k.lower() == "authorization" for k in cab):
        return None
    return host, cab


def ouvinte(destino: dict):
    """Devolve o callback para `pagina.on("request", ...)`.

    `destino` é o dicionário {host: cabeçalhos} que vai sendo preenchido.
    """
    def ao_requisitar(req):
        achado = cabecalhos_da_requisicao(req)
        if achado:
            destino[achado[0]] = achado[1]
    return ao_requisitar
