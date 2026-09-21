# -*- coding: utf-8 -*-
"""Varre o calendário do portal e baixa as guias do mês.

Uma ida ao portal por empresa: a página do calendário já traz o mês inteiro.
Baixar marca o documento como lido no portal (some o "Novo") — efeito
conhecido e aceito, porque é o mesmo que a pessoa faria à mão.
"""
from __future__ import annotations

from pathlib import Path

import util
from acessorias import config as cfg
from guias import leitura
from guias.modelos import Guia

log = util.log(__name__)

#: Certidão não é conta a pagar. É o único descarte por assunto.
PREFIXOS_FORA = ("CND",)


def itens_do_mes(cal: dict | None) -> list[dict]:
    """Os documentos do mês que têm pagamento, em ordem de dia."""
    saida = []
    for _dia, itens in sorted((cal or {}).items()):
        for item in itens or []:
            desc = str(item.get("desc") or "")
            if item.get("TemVcto") != "S":
                continue
            if desc.upper().startswith(PREFIXOS_FORA):
                continue
            saida.append(item)
    return saida


def _nome_do_arquivo(vip_id: str, item: dict) -> str:
    dia = str(item.get("prz") or "")[:2] or "00"
    return f"{vip_id}_{dia}_{item.get('AnxID')}.pdf"


def varrer(cliente, mapa, ano: int, mes: int, *, pasta_de, log=print,
           parar=None) -> list[Guia]:
    """As guias do mês, já baixadas e lidas.

    `pasta_de(empresa)` devolve a pasta onde o PDF daquela empresa vai. `parar`
    é consultado ENTRE empresas: interromper no meio de uma deixaria metade
    das guias baixadas sem ninguém saber quais.
    """
    competencia = f"{ano:04d}-{mes:02d}"
    por_vip = {e.vip_id: e for e in mapa.empresas if getattr(e, "vip_id", "")}
    guias: list[Guia] = []

    for vip_id, nome_na_tela in cliente.empresas():
        if parar and parar():
            log("Parado a pedido.")
            return guias
        empresa = por_vip.get(vip_id)
        if empresa is None:
            guias.append(Guia(
                vip_id=vip_id, empresa=nome_na_tela, desc="", anx_id="",
                competencia=competencia,
                erro="empresa do portal sem cadastro aqui: sem pasta para o "
                     "PDF e sem obra para o lançamento"))
            continue

        pasta = Path(pasta_de(empresa)) / cfg.SUBPASTA_GUIAS
        itens = itens_do_mes(cliente.calendario(vip_id, ano, mes))
        log(f"{empresa.nome}: {len(itens)} documento(s) a pagar em {competencia}.")

        for item in itens:
            guias.extend(_uma_guia(cliente, empresa, item, competencia, pasta))
    return guias


def _uma_guia(cliente, empresa, item: dict, competencia: str,
              pasta: Path) -> list[Guia]:
    base = Guia(vip_id=empresa.vip_id, empresa=empresa.nome,
                desc=str(item.get("desc") or ""),
                anx_id=str(item.get("AnxID") or ""), competencia=competencia)
    destino = pasta / _nome_do_arquivo(empresa.vip_id, item)
    # A pasta da empresa no mês pode não existir ainda: quem sabe onde o PDF
    # vai é este módulo, não o portal — criar aqui vale para qualquer cliente,
    # de verdade ou de teste.
    destino.parent.mkdir(parents=True, exist_ok=True)

    # Duas tentativas, e não mais: o link do iframe expira em 120 s e a
    # segunda passada pede um link novo. Insistir além disso só demora.
    ultimo = ""
    for _ in range(2):
        try:
            cliente.baixar_guia(item.get("lnk") or "", destino)
            ultimo = ""
            break
        except Exception as e:
            ultimo = str(e)[:200]
            log.warning("não deu para baixar uma guia do portal", exc_info=True)
    if ultimo:
        base.erro = ultimo
        return [base]

    itens = leitura.ler_pdf(destino)
    if not itens:
        base.pdf = destino
        base.erro = "não consegui ler valor nem vencimento no PDF"
        return [base]

    saida = []
    for lido in itens:
        guia = Guia(vip_id=base.vip_id, empresa=base.empresa, desc=base.desc,
                    anx_id=base.anx_id, competencia=competencia, pdf=destino,
                    valor=lido.valor, vencimento=lido.vencimento,
                    documento=lido.documento)
        if len(itens) > 1:
            # Duas cobranças no mesmo arquivo: o `anx_id` deixa de ser único,
            # e a trava do registro depende dele.
            guia.anx_id = f"{base.anx_id}p{lido.pagina}"
        saida.append(guia)
    return saida
