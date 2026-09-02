# -*- coding: utf-8 -*-
"""Novas tentativas em `conciliacao/erp/api.py`, sem tela e sem rede.

Este módulo fala com o ERP por `urllib.request`, não por `requests` — não há
`Session`/`HTTPAdapter` aqui para montar um `Retry` pronto (ver o comentário
de `_TENTATIVAS_GET` em `erp/api.py`). O laço de novas tentativas foi escrito
à mão, em cima do MESMO `urlopen`, e é isso que estes dois testes provam: um
504 passageiro do gateway não pode virar rodada perdida em GET, e um POST
(hoje só o login) nunca insiste — reenviá-lo depois de perder a resposta
poderia repetir uma autenticação que talvez já tivesse valido.

O ponto único que se troca é `urllib.request.urlopen`: é o que `_requisitar`
chama de verdade, então um dublê ali exercita o laço de tentativas inteiro,
não só o resultado final.
"""
import io
import urllib.error
import urllib.request

import pytest

from conciliacao.erp import api


class _RespostaFalsa:
    """O bastante de `http.client.HTTPResponse` para `_requisitar`: só
    `read()`, usado dentro de um `with`."""

    def __init__(self, corpo: bytes):
        self._corpo = corpo

    def read(self):
        return self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _urlopen_falso(sequencia):
    """Fabrica um `urlopen` de mentira que consome `sequencia` na ordem: um
    `int` vira `HTTPError` com aquele código; `bytes` vira uma resposta 200
    com aquele corpo. `chamadas` guarda quantas vezes foi chamado e por qual
    método — o que os testes conferem."""
    chamadas = {"n": 0, "metodos": []}

    def falso(req, timeout=None):
        chamadas["n"] += 1
        chamadas["metodos"].append(req.get_method())
        item = sequencia[chamadas["n"] - 1]
        if isinstance(item, int):
            raise urllib.error.HTTPError(
                req.full_url, item, "erro de mentira", {}, io.BytesIO(b""))
        return _RespostaFalsa(item)

    return falso, chamadas


@pytest.fixture(autouse=True)
def _sem_espera_de_verdade(monkeypatch):
    """O que importa aqui é QUANTAS vezes e COM QUE MÉTODO, não a espera
    real entre tentativas (1s, depois 2s) — sem isto a suíte pagaria esse
    tempo a cada rodada."""
    monkeypatch.setattr(api.time, "sleep", lambda *_a, **_k: None)


def test_get_repete_5xx_ate_o_sucesso(monkeypatch):
    """Um 504 real do prod-erp-api (visto no diagnostico.log de produção,
    gateway openresty/apisix) não pode custar a rodada inteira: GET insiste,
    até 3 vezes, e devolve o que veio na terceira."""
    falso, chamadas = _urlopen_falso([504, 504, b'{"ok": true}'])
    monkeypatch.setattr(urllib.request, "urlopen", falso)

    assert api._requisitar("https://x/y") == {"ok": True}
    assert chamadas["n"] == 3
    assert chamadas["metodos"] == ["GET", "GET", "GET"]


def test_post_nao_repete_5xx(monkeypatch):
    """Reenviar um POST que talvez já tenha valido (hoje, o login) não pode
    virar uma segunda tentativa por conta própria — só GET insiste, e o 504
    único vira a mesma exceção nomeada de sempre."""
    falso, chamadas = _urlopen_falso([504])
    monkeypatch.setattr(urllib.request, "urlopen", falso)

    with pytest.raises(api.ErpError):
        api._requisitar("https://x/y", metodo="POST", corpo={"a": 1})
    assert chamadas["n"] == 1
    assert chamadas["metodos"] == ["POST"]


def test_401_no_login_continua_virando_sessao_expirada(monkeypatch):
    """O laço de tentativas não pode atropelar a tradução que já existia:
    401 na URL de login é `SessaoExpirada`, não `ErpError` genérico — e
    401/403 não estão na lista de códigos transitórios, então nem tentam
    de novo."""
    falso, chamadas = _urlopen_falso([401])
    monkeypatch.setattr(urllib.request, "urlopen", falso)

    with pytest.raises(api.SessaoExpirada):
        api._requisitar("https://x/users/login", metodo="POST",
                        corpo={"username": "a", "password": "b"})
    assert chamadas["n"] == 1
