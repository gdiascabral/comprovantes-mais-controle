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

#: Medidos ao vivo em 29/10/2026 na Home do SicoobNet novo. O print de
#: 27/10 saiu com o "carregando" escuro por cima e sem o saldo: agora ele
#: espera o carregando sumir e EMPILHA o cabeçalho (empresa e número da
#: conta) em cima do card "Conta corrente" (o "Saldo da conta").
SEL_CARREGANDO = ".block-ui-wrapper.block-ui-main"
SEL_CABECALHO = ".conteudo-conta"          # o nome da empresa + ".info-cliente-chave"
SEL_CARD_SALDO = "ib-sicoob-card-atalho"
TEXTO_DO_CARD = "Saldo da conta"
TEMPO_TELA_MS = 20000
#: Botão "mostrar saldo" (o olho): em 29/10 o saldo veio à mostra; "" = não
#: clica.
SELETOR_MOSTRAR_SALDO = ""
SEM_LEITURA = "a conta não foi lida, então não há print"


def nome_do_print(numero: str) -> str:
    from extratos_sicoob import saldo
    return f"sicoob {saldo.so_digitos(numero)}.png"


def fotografar_saldo(page, arquivo) -> str:
    """Espera a Home parar de carregar e grava o cabeçalho + o card do saldo.
    Sem os dois pedaços, fica o print da tela como estiver. "" = saiu."""
    try:
        page.locator(SEL_CARREGANDO).first.wait_for(state="hidden", timeout=TEMPO_TELA_MS)
    except Exception:                                        # noqa: BLE001
        pass                                 # o print sai como estiver
    util.revelar(page, SELETOR_MOSTRAR_SALDO)
    try:
        card = page.locator(SEL_CARD_SALDO).filter(has_text=TEXTO_DO_CARD).first
        card.wait_for(state="visible", timeout=TEMPO_TELA_MS)
        page.evaluate("window.scrollTo(0, 0)")
        pedacos = [util.recorte_da_tela(page, page.locator(SEL_CABECALHO).first),
                   util.recorte_da_tela(page, card)]
        if all(pedacos):
            imagem = util.empilhar([p[0] for p in pedacos])
            Path(arquivo).parent.mkdir(parents=True, exist_ok=True)
            imagem.save(arquivo)
            return ""
    except Exception:                                        # noqa: BLE001
        pass                                 # cai no print da tela inteira
    return util.fotografar(page, arquivo)


def ler_com_prints(abrir, numeros, pasta, *, perguntar, parar, log,
                   progresso=lambda feitas, total: None,
                   agora=_dt.datetime.now) -> dict:
    """{dígitos da conta: ps.Leitura}, uma por conta pedida."""
    from extratos_sicoob import saldo

    pasta = Path(pasta)
    imagens: dict = {}

    def ao_ler(page, numero):
        arquivo = pasta / nome_do_print(numero)
        motivo = fotografar_saldo(page, arquivo)
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
