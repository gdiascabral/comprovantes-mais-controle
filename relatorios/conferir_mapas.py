# -*- coding: utf-8 -*-
"""Confere se os DOIS mapas de pastas concordam sobre a mesma conta.

Por que isto existe
-------------------
O mês de uma conta é montado por duas abas diferentes:

  Relatório Mensal  -> `contas_mc.json`      -> grava "202607 SICOOB MAIS CONTROLE.pdf"
  Extratos Sicoob   -> `contas_sicoob.json`  -> grava "202607 SICOOB.ofx" e ".pdf"

Cada uma decide a pasta de destino pelo SEU mapa. Enquanto os dois
concordarem, os três arquivos caem juntos. Quando divergem — e divergiram, em
julho/2026, em três subcontas — cada aba cria a sua pasta e o mês fica
partido ao meio, com metade dos arquivos em cada uma. Nada no disco denuncia:
as duas pastas existem, as duas têm arquivo dentro, e só quem abre percebe
que falta a outra metade.

Comparar os mapas é barato e responde antes do primeiro download.
"""
from __future__ import annotations

import json
from pathlib import Path

import util


def _so_digitos(texto) -> str:
    return "".join(c for c in str(texto or "") if c.isdigit())


def _pastas_do_contas_mc(dados: dict) -> dict[str, str]:
    """{numero da conta -> pasta}. A conta sai do nome do ERP ou da pasta."""
    saida: dict[str, str] = {}
    for c in dados.get("contas") or []:
        pasta = (c.get("pasta") or "").strip()
        numero = _numero_na_string(c.get("erp")) or _numero_na_string(pasta)
        if numero and pasta:
            saida[numero] = pasta
    return saida


def _pastas_do_contas_sicoob(dados: dict) -> dict[str, str]:
    saida: dict[str, str] = {}
    for empresa in dados.get("empresas") or []:
        for conta in empresa.get("contas") or []:
            numero = _so_digitos(conta.get("numero"))
            pasta = (conta.get("pasta") or "").strip()
            if numero and pasta:
                saida[numero] = pasta
    return saida


def _numero_na_string(texto) -> str | None:
    """Extrai um número de conta (6+ dígitos, com ou sem pontuação) do texto."""
    import re
    m = re.search(r"\b(\d{1,3}[.\s]?\d{3}[-\s]?\d)\b", str(texto or ""))
    return _so_digitos(m.group(1)) if m else None


def divergencias(caminho_mc: Path, caminho_sicoob: Path) -> list[str]:
    """Contas que os dois mapas mandam para pastas DIFERENTES.

    Devolve uma lista de recados prontos. Lista vazia = tudo alinhado.
    Mapa ausente não é divergência: cada aba funciona sozinha."""
    try:
        mc = _pastas_do_contas_mc(
            json.loads(Path(caminho_mc).read_text(encoding="utf-8")))
        sicoob = _pastas_do_contas_sicoob(
            json.loads(Path(caminho_sicoob).read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return []

    recados = []
    for numero in sorted(set(mc) & set(sicoob)):
        a, b = mc[numero], sicoob[numero]
        if util.norm_espaco(a) != util.norm_espaco(b):
            recados.append(
                f"conta {numero}: contas_mc.json manda para \"{a}\" e "
                f"contas_sicoob.json para \"{b}\" — o mês desta conta vai "
                f"ficar partido entre as duas pastas.")
    return recados


def avisar(caminho_mc: Path, caminho_sicoob: Path, log=print) -> int:
    """Registra as divergências no log da aba. Devolve quantas achou."""
    recados = divergencias(caminho_mc, caminho_sicoob)
    for r in recados:
        log(f"  [aviso] {r}")
    return len(recados)
