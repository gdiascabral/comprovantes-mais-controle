# -*- coding: utf-8 -*-
"""O HTTP das leituras: ritmo (rate limit), uma nova tentativa no 429 e a
recusa de resposta que não é JSON. Não decide nada sobre dinheiro.

Só GET de leitura e POST de token passam por aqui: repetir uma vez depois do
429 é seguro porque nada aqui move dinheiro.
"""
from __future__ import annotations

import json
import time
from decimal import Decimal
from typing import Callable


class ErroLeitura(RuntimeError):
    """O banco não respondeu, respondeu fora de 2xx, ou respondeu 2xx com algo
    que não serve (HTML do firewall, JSON que não é objeto). `status` None =
    não houve resposta. Nunca carrega token nem certificado."""

    def __init__(self, status, corpo: str):
        super().__init__(f"HTTP {status}: {corpo[:200]}")
        self.status = status
        self.corpo = corpo


class Ritmo:
    """No máximo uma chamada a cada `intervalo` segundos. Um objeto só para
    todos os clientes do mesmo banco: o limite do banco não sabe de empresa."""

    def __init__(self, intervalo: float, relogio: Callable[[], float] = time.monotonic,
                 esperar: Callable[[float], None] = time.sleep):
        self.intervalo = float(intervalo)
        self.relogio, self.esperar = relogio, esperar
        self._ultimo = None

    def vez(self) -> None:
        if self._ultimo is not None:
            falta = self.intervalo - (self.relogio() - self._ultimo)
            if falta > 0:
                self.esperar(falta)
        self._ultimo = self.relogio()


def pedir_json(sessao, metodo: str, url: str, *, ritmo: Ritmo, headers: dict,
               params=None, data=None, cert=None, timeout: float = 30.0,
               espera_429: float = 0.0) -> dict:
    """O corpo JSON (números em Decimal) de uma resposta 2xx, ou ErroLeitura.
    429 na 1ª tentativa: espera `espera_429` e tenta UMA vez de novo."""
    for tentativa in (1, 2):
        ritmo.vez()
        try:
            r = sessao.request(metodo, url, headers=headers, params=params, data=data,
                               cert=cert, timeout=timeout)
        except Exception as e:  # rede caiu: o motivo é só o tipo (a URL leva a conta)
            raise ErroLeitura(None, f"sem resposta ({type(e).__name__})") from None
        if r.status_code == 429 and tentativa == 1:
            ritmo.esperar(espera_429)
            continue
        break
    texto = r.text or ""
    if not 200 <= r.status_code < 300:
        raise ErroLeitura(r.status_code, texto)
    try:
        corpo = json.loads(texto, parse_float=Decimal)
    except ValueError:
        # 200 com HTML = recusa do firewall do Sicoob (medido em 26 e 27/11/2026).
        raise ErroLeitura(r.status_code, "resposta não é JSON: " + texto[:80]) from None
    if not isinstance(corpo, dict):
        raise ErroLeitura(r.status_code, "resposta não é um objeto JSON")
    return corpo


class TokenOAuth:
    """Token client_credentials (com mTLS) guardado até 60 s antes de vencer.

    Falhou uma vez, falha de novo nesta rodada sem pedir outra vez: N contas da
    mesma empresa não viram N pedidos de token (o do Inter aceita 5 por minuto).
    O `form` leva o segredo: nunca vai para mensagem de erro nem para log."""

    def __init__(self, sessao, url: str, form: dict, *, user_agent: str, cert=None,
                 ritmo: Ritmo | None = None, relogio: Callable[[], float] = time.monotonic,
                 espera_429: float = 0.0):
        self._s, self._url, self._form = sessao, url, dict(form)
        self._ua, self._cert = user_agent, cert
        self._ritmo = ritmo or Ritmo(0)
        self._relogio = relogio
        self._429 = espera_429
        self._token, self._vence, self._erro = "", 0.0, None

    def __repr__(self) -> str:
        return f"TokenOAuth({self._url!r})"

    def __call__(self) -> str:
        if self._erro is not None:
            raise self._erro
        if self._token and self._relogio() < self._vence:
            return self._token
        try:
            corpo = pedir_json(self._s, "POST", self._url, ritmo=self._ritmo,
                               headers={"User-Agent": self._ua, "Accept": "application/json",
                                        "Content-Type": "application/x-www-form-urlencoded"},
                               data=self._form, cert=self._cert, espera_429=self._429)
            tok = corpo.get("access_token")
            if not isinstance(tok, str) or not tok:
                raise ErroLeitura(200, "token sem access_token")
        except ErroLeitura as e:
            # O corpo de erro do servidor de token não volta para a nuvem.
            self._erro = ErroLeitura(e.status, "token recusado")
            raise self._erro from None
        dura = corpo.get("expires_in")
        segundos = int(dura) if isinstance(dura, (int, Decimal)) and not isinstance(dura, bool) else 300
        self._token, self._vence = tok, self._relogio() + max(0, segundos - 60)
        return tok
