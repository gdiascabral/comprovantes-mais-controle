# -*- coding: utf-8 -*-
"""Um lugar só para falar com o Mais Controle.

POR QUE ESTE PACOTE EXISTE
--------------------------
Oito lugares do app falavam com o ERP por conta própria, cada um tendo
redescoberto qual token pedir, quais cabeçalhos copiar, qual `user-agent` passa
pelo WAF e como paginar. O conhecimento se contradizia POR ESCRITO:

    conciliacao/erp/api.py:33      "o token E o jwtToken, NAO o accessToken"
    fontes/vigia-boletos/
        mc_sessao.py:9             "accessToken -> API legada"

Os dois estão certos, para back-ends diferentes — e nenhum arquivo dizia isso
inteiro. O inventário completo, com uma linha por consumidor e a evidência de
cada afirmação, está em `docs/ERP-CLIENTES.md`; a regra que ele destilou mora
em `erp/sessao.py:token_para`.

O DESENHO, EM UMA FRASE POR MÓDULO
----------------------------------
    hosts.py    ONDE. Só endereços — não sabe falar com ninguém.
    sessao.py   QUEM. O login, os DOIS tokens, os cabeçalhos por host, o
                user-agent de navegador, e o transporte HTTP direto.
    pagina.py   COMO, quando é pelo navegador. O `page.evaluate(fetch)` que
                estava duplicado em `anexar/` e `aportes/`.

NENHUM CONSUMIDOR USA ISTO AINDA, e é de propósito: o pacote nasce sozinho,
com teste próprio, e cada aba migra no seu PR — do mais simples
(`nuvem/contas_novas.py`, que já é HTTP direto) ao mais delicado
(`anexar/mc_api.py`, que tira o token do cabeçalho da página logada e é a porta
de quatro abas). A ordem inteira está no fim do `docs/ERP-CLIENTES.md`.
"""
from __future__ import annotations

from .hosts import ACESSAR, ERP_API, LEGACY, URL_LOGIN
from .pagina import TransportePagina
from .sessao import USER_AGENT, ErpErro, Sessao, SessaoRecusada

__all__ = [
    "ACESSAR",
    "ERP_API",
    "LEGACY",
    "URL_LOGIN",
    "USER_AGENT",
    "ErpErro",
    "Sessao",
    "SessaoRecusada",
    "TransportePagina",
]
