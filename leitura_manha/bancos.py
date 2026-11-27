# -*- coding: utf-8 -*-
"""Os dois clientes de LEITURA: Sicoob Conta Corrente (v4) e Inter Banking (v2).

Só GET de saldo e de extrato (e o POST do token). Endereços e campos lidos nos
portais developers.sicoob.com.br e developers.inter.co em 27/11/2026. O que os
dois devolvem é cru: quem lê o número é `extrato.py`.
"""
from __future__ import annotations

from datetime import date
from typing import Callable

from pagamento_api.sicoob import USER_AGENT

from .transporte import Ritmo, TokenOAuth, pedir_json

SICOOB_PRODUCAO = "https://api.sicoob.com.br/conta-corrente/v4"
SICOOB_SANDBOX = "https://sandbox.sicoob.com.br/sicoob/sandbox/conta-corrente/v4"
SICOOB_TOKEN = "https://auth.sicoob.com.br/auth/realms/cooperado/protocol/openid-connect/token"
SICOOB_ESCOPO = "cco_consulta"
INTER_PRODUCAO = "https://cdpj.partners.bancointer.com.br"
INTER_SANDBOX = "https://cdpj-sandbox.partners.uatinter.co"
INTER_ESCOPO = "extrato.read"

#: Limites dos portais: Sicoob Conta Corrente 2/s; Inter saldo e extrato 10/min,
#: token do Inter 5/min. O ritmo fica um pouco abaixo de cada um.
INTERVALO_SICOOB = 0.55
INTERVALO_INTER = 6.5
INTERVALO_TOKEN_INTER = 13.0
#: Quanto esperar antes da única nova tentativa depois de um 429.
ESPERA_429_SICOOB = 2.0
ESPERA_429_INTER = 61.0


def token_sicoob(sessao, client_id: str, cert) -> TokenOAuth:
    """Produção: client_credentials com o certificado da empresa (mTLS)."""
    return TokenOAuth(sessao, SICOOB_TOKEN,
                      {"grant_type": "client_credentials", "client_id": client_id,
                       "scope": SICOOB_ESCOPO},
                      user_agent=USER_AGENT, cert=cert, espera_429=ESPERA_429_SICOOB)


def token_inter(sessao, base: str, client_id: str, client_secret: str, cert,
                ritmo: Ritmo) -> TokenOAuth:
    return TokenOAuth(sessao, base + "/oauth/v2/token",
                      {"client_id": client_id, "client_secret": client_secret,
                       "grant_type": "client_credentials", "scope": INTER_ESCOPO},
                      user_agent=USER_AGENT, cert=cert, ritmo=ritmo,
                      espera_429=ESPERA_429_INTER)


class ContaCorrenteSicoob:
    """GET /saldo e GET /extrato/{mes}/{ano} de uma empresa (um client_id)."""

    def __init__(self, sessao, base: str, client_id: str, token: Callable[[], str], *,
                 ritmo: Ritmo, cert=None, timeout: float = 30.0,
                 espera_429: float = ESPERA_429_SICOOB):
        self._s, self._base, self._cid, self._token = sessao, base, client_id, token
        self._ritmo, self._cert, self._timeout, self._429 = ritmo, cert, timeout, espera_429

    def _get(self, caminho: str, params: dict) -> dict:
        h = {"User-Agent": USER_AGENT, "Authorization": "Bearer " + self._token(),
             "client_id": self._cid, "Accept": "application/json"}
        return pedir_json(self._s, "GET", self._base + caminho, ritmo=self._ritmo,
                          headers=h, params=params, cert=self._cert,
                          timeout=self._timeout, espera_429=self._429)

    def saldo(self, numero: int) -> dict:
        return self._get("/saldo", {"numeroContaCorrente": int(numero)})

    def extrato(self, numero: int, dia: date) -> dict:
        return self._get(f"/extrato/{dia.month}/{dia.year}",
                         {"numeroContaCorrente": int(numero), "diaInicial": dia.day,
                          "diaFinal": dia.day})


class BankingInter:
    """GET /banking/v2/saldo e /banking/v2/extrato de UMA conta do Inter."""

    def __init__(self, sessao, base: str, token: Callable[[], str], *, ritmo: Ritmo,
                 cert=None, conta_corrente: str = "", timeout: float = 30.0,
                 espera_429: float = ESPERA_429_INTER):
        self._s, self._base, self._token = sessao, base, token
        self._ritmo, self._cert, self._timeout, self._429 = ritmo, cert, timeout, espera_429
        self._conta = str(conta_corrente or "")

    def _get(self, caminho: str, params: dict | None) -> dict:
        h = {"User-Agent": USER_AGENT, "Authorization": "Bearer " + self._token(),
             "Accept": "application/json"}
        if self._conta:  # só quando a integração tem mais de uma conta
            h["x-conta-corrente"] = self._conta
        return pedir_json(self._s, "GET", self._base + caminho, ritmo=self._ritmo,
                          headers=h, params=params, cert=self._cert,
                          timeout=self._timeout, espera_429=self._429)

    def saldo(self) -> dict:
        return self._get("/banking/v2/saldo", None)

    def extrato(self, dia: date) -> dict:
        return self._get("/banking/v2/extrato",
                         {"dataInicio": dia.isoformat(), "dataFim": dia.isoformat()})
