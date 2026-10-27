# -*- coding: utf-8 -*-
"""O saldo do Sicoob com print, para a Prova de saldos.

O MESMO caminho do "Reler Sicoob" (`extratos_sicoob.saldo.
ler_em_dois_acessos`: confere a conta no cabeçalho, pede o saldo de dentro
da página, pergunta pelo outro acesso). O print sai pelo gancho `ao_ler`,
com a conta ainda aberta na tela inicial — a mesma em que o saldo foi lido.
Roda na thread de quem chama (a `prova-saldos`); o `SicoobClient` nasce e
morre dentro de `abrir()`.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path

import util

from . import prova_saldos as ps

#: Seletor da área do saldo na Home do SicoobNet (medir ao vivo, Tarefa 8);
#: "" = fotografa a parte visível da tela.
SELETOR_AREA_SALDO = ""
#: Botão "mostrar saldo" (o olho) da Home, se o saldo vier mascarado —
#: medir ao vivo (Tarefa 8). "" = não clica (revisão de 27/10/2026).
SELETOR_MOSTRAR_SALDO = ""
SEM_LEITURA = "a conta não foi lida, então não há print"


def nome_do_print(numero: str) -> str:
    from extratos_sicoob import saldo
    return f"sicoob {saldo.so_digitos(numero)}.png"


def ler_com_prints(abrir, numeros, pasta, *, perguntar, parar, log,
                   progresso=lambda feitas, total: None,
                   agora=_dt.datetime.now) -> dict:
    """{dígitos da conta: ps.Leitura}, uma por conta pedida."""
    from extratos_sicoob import saldo

    pasta = Path(pasta)
    imagens: dict = {}

    def ao_ler(page, numero):
        util.revelar(page, SELETOR_MOSTRAR_SALDO)
        alvo = page
        if SELETOR_AREA_SALDO:
            area = page.locator(SELETOR_AREA_SALDO).first
            if area.count():
                alvo = area
        arquivo = pasta / nome_do_print(numero)
        motivo = util.fotografar(alvo, arquivo)
        imagens[saldo.so_digitos(numero)] = (None, motivo) if motivo else (arquivo, "")

    lidos = saldo.ler_em_dois_acessos(abrir, numeros, perguntar=perguntar, agora=agora,
                                      parar=parar, log=log, progresso=progresso,
                                      ao_ler=ao_ler)
    saida = {}
    for lido in lidos:
        d = saldo.so_digitos(lido.numero)
        imagem, sem = imagens.get(d, (None, SEM_LEITURA))
        saida[d] = ps.Leitura(lido.saldo, lido.lido_em, lido.motivo, imagem, sem)
    return saida
