# -*- coding: utf-8 -*-
"""Cliente mínimo da API de mensagens da Anthropic, por `requests`.

Decisão do dono (25/11/2026): SEM o pacote `anthropic` no exe (exigiria exe
novo em todas as máquinas). O `leitura_ia.pedir_leitura` só usa
`cliente.beta.messages.create(**kw)` e lê `.content[*].type/.text`,
`.usage.input_tokens/.output_tokens` e `.stop_reason`; é só isso que este
módulo oferece. Erro de rede, de prazo, HTTP fora de 2xx ou corpo que não é
JSON levantam `LeituraFalhou` — a linha cai em "IA não respondeu", nunca em
"sem anexo" nem em apta.

A chave só viaja no cabeçalho `x-api-key`; nunca entra em mensagem de erro,
log nem exceção.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import requests

from .leitura_ia import LeituraFalhou

URL = "https://api.anthropic.com/v1/messages"
VERSAO_DA_API = "2023-06-01"
PRAZO = 90          # segundos: leitura de imagem com raciocínio demora


def _objeto(no):
    """dict/list do JSON → objetos com atributos (`.type`, `.text`, ...)."""
    if isinstance(no, dict):
        return SimpleNamespace(**{k: _objeto(v) for k, v in no.items()
                                  if isinstance(k, str) and k.isidentifier()})
    if isinstance(no, list):
        return [_objeto(x) for x in no]
    return no


class _Mensagens:
    def __init__(self, cliente):
        self._c = cliente

    def create(self, **kw):
        betas = kw.pop("betas", None)
        return self._c._enviar(kw, betas)


class ClienteAnthropic:
    def __init__(self, chave: str, *, sessao=None, timeout: int = PRAZO, url: str = URL):
        if not chave or not str(chave).strip():
            raise ValueError("sem chave da API")
        self._chave = str(chave).strip()
        self._sessao = sessao if sessao is not None else requests.Session()
        self._timeout, self._url = timeout, url
        self.beta = SimpleNamespace(messages=_Mensagens(self))

    def _enviar(self, corpo: dict, betas):
        cab = {"x-api-key": self._chave, "anthropic-version": VERSAO_DA_API,
               "content-type": "application/json"}
        if betas:
            cab["anthropic-beta"] = ",".join(betas)
        try:
            r = self._sessao.post(self._url, headers=cab, timeout=self._timeout,
                                  data=json.dumps(corpo).encode("utf-8"))
        except requests.Timeout as e:
            raise LeituraFalhou("a IA demorou demais para responder") from e
        except requests.RequestException as e:
            raise LeituraFalhou(f"sem conexão com a IA ({type(e).__name__})") from e
        if not 200 <= int(r.status_code) < 300:
            raise LeituraFalhou(f"a IA respondeu HTTP {r.status_code}: {self._motivo(r)}")
        try:
            return _objeto(json.loads(r.text))
        except ValueError as e:
            raise LeituraFalhou("a resposta da IA não é JSON") from e

    def _motivo(self, r) -> str:
        """A mensagem de erro da API, sem a chave e curta."""
        try:
            m = (json.loads(r.text).get("error") or {}).get("message") or ""
        except (ValueError, AttributeError):
            m = ""
        return str(m).replace(self._chave, "***")[:120]
