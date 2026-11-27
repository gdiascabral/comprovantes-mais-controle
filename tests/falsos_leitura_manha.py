# -*- coding: utf-8 -*-
"""Dublês da leitura das 07:30: sessão HTTP, relógio e ERP. Sem rede."""
from __future__ import annotations

import json
from collections import deque


class Resp:
    def __init__(self, status: int, corpo):
        self.status_code = status
        self.text = corpo if isinstance(corpo, str) else json.dumps(corpo)


class SessaoFalsa:
    """Devolve as respostas na ordem; acabou a fila = AssertionError (chamada a mais
    derruba o teste em vez de repetir a última resposta)."""

    def __init__(self, *respostas):
        self.fila = deque(respostas)
        self.pedidos = []

    def request(self, metodo, url, **k):
        self.pedidos.append((metodo, url, k))
        if not self.fila:
            raise AssertionError(f"chamada a mais: {metodo} {url}")
        r = self.fila.popleft()
        if isinstance(r, Exception):
            raise r
        return r


class Relogio:
    def __init__(self):
        self.t = 0.0
        self.esperas = []

    def __call__(self) -> float:
        return self.t

    def esperar(self, s: float) -> None:
        self.esperas.append(round(s, 3))
        self.t += s
