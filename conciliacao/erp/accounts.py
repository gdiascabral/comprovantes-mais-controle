"""Leitura dos saldos das contas bancarias.

DESDE 10/08/2026 ISTO NAO RASPA MAIS A TELA
-------------------------------------------
A tela #/accounts foi reescrita de AngularJS para React/MUI e a raspagem
quebrou inteira: `tr[ng-repeat]` deixou de existir, junto com o scope que
tinha `load()`, `pageSize` e `toggleCurrentBalance()`. O sintoma era cruel —
o programa logava, abria a tela certa, o print de erro mostrava a tela
perfeita, e mesmo assim falhava com "a tela do ERP nao carregou".

A leitura agora vai pela API REST que a propria tela consome (ver `api.py`).
O modulo continua com o mesmo nome e a mesma saida — `list[ErpAccount]` — para
o resto do programa nao precisar saber de nada disso.

O QUE ISSO ELIMINOU DE UMA VEZ
------------------------------
  - o valor mascarado ("R$ *******") e o clique no olho para revelar;
  - a espera pelos saldos assincronos chegarem celula a celula;
  - a paginacao (a tela mostra 10 por vez; a API traz as 36 juntas);
  - o parse de "R$ 1.234,56" — a API devolve numero;
  - a dependencia de layout, que ja quebrou duas vezes.

Se um dia a API sair do ar e for preciso voltar a raspar a tela, os seletores
da tela nova estao levantados e documentados em `browser.py`.
"""

from __future__ import annotations

from ..models import ErpAccount
from .api import coletar_contas_api

__all__ = ["coletar_contas"]


def coletar_contas(config, *, log=print) -> list[ErpAccount]:
    """Todas as contas ativas do ERP, com saldo.

    NAO recebe mais a pagina do navegador: a leitura de saldos deixou de
    precisar de browser. Quem chama continua recebendo a mesma lista.
    """
    return coletar_contas_api(config, log=log)
