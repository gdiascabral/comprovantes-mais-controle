# -*- coding: utf-8 -*-
"""OFX do Sicoob de um período curto (aba Conciliação, "Baixar OFX").

O caminho é o da ferramenta `ferramentas/ofx-periodo/baixar_ofx.py`, provado
em 23/10/2026 (OFX de 22/10 a 23/10, todas as contas dos dois logins): entra
na conta pelos dígitos (`saldo.entrar`, que confere o cabeçalho), abre o
extrato, marca o período no calendário e exporta o OFX. Recebe o
`SicoobClient` JÁ logado: quem abre o Chrome e espera o login é quem chama.

**O período marcado é conferido antes de exportar** (o texto do campo tem
de ser "DD/MM/AAAA - DD/MM/AAAA"): o OFX de outro período importado no ERP
seria lançamento de outro dia. A conta e o período do arquivo são
conferidos de novo depois, contra o próprio OFX (`conciliacao_dia.
ofx_regras.conferir_ofx`).
"""
from __future__ import annotations

import json
from pathlib import Path

import util

from . import saldo
from .sicoob_client import TEMPO_PADRAO

#: Regra do dono (23/10/2026): uma conta que aparece num login do Sicoob e não
#: existe no Mais Controle é sempre ignorada. O NÚMERO mora no cadastro, fora
#: do repositório (público): `conciliacao_ofx.json` na pasta do app,
#: `{"ignorar": ["12345-6", ...]}`.
ARQUIVO_IGNORAR = "conciliacao_ofx.json"
PARADO = "parado pelo botão Parar antes desta conta"


def ignoradas(pasta=None) -> frozenset:
    """Os dígitos das contas que nunca se baixam. Arquivo ausente ou torto =
    nenhuma (a lista sai das contas do ERP, onde a ignorada não existe: a
    regra é só a segunda trava)."""
    alvo = Path(pasta or util.pasta_base()) / ARQUIVO_IGNORAR
    try:
        dados = json.loads(alvo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    lista = dados.get("ignorar") if isinstance(dados, dict) else None
    return frozenset(saldo.so_digitos(n) for n in lista or () if saldo.so_digitos(n))


class PeriodoNaoMarcou(RuntimeError):
    """O calendário do Sicoob não ficou com o período pedido."""


def _primeira_linha(erro) -> str:
    texto = (str(erro or "").strip().splitlines() or [""])[0].strip()
    return texto[:160] or type(erro).__name__


def definir_intervalo(cli, ini, fim) -> None:
    """Marca `ini` a `fim` no calendário do extrato e confere o que ficou."""
    page = cli.page
    page.locator("p-calendar input").first.click()
    cal = page.locator(".ui-datepicker").first
    cal.wait_for(state="visible", timeout=TEMPO_PADRAO)
    for d in (ini, fim):
        # O `select` do mês conta de 0 (janeiro = "0").
        cal.locator("select.ui-datepicker-month").select_option(str(d.month - 1))
        cal.locator("select.ui-datepicker-year").select_option(str(d.year))
        page.wait_for_timeout(300)
        cli._clicar_dia(cal, d.day)
    cal.get_by_text("Confirmar", exact=True).click()
    page.wait_for_timeout(1500)
    esperado = f"{ini:%d/%m/%Y} - {fim:%d/%m/%Y}"
    obtido = cli.texto_periodo() or ""
    if esperado not in obtido:
        raise PeriodoNaoMarcou(f"o período ficou '{obtido}', e o pedido era '{esperado}'")


def baixar(cli, contas, ini, fim, pasta, *, lista: dict, parar=lambda: False,
           log=print, progresso=lambda feitas, total: None,
           entrar=saldo.entrar, definir=definir_intervalo, ignorar=None) -> dict:
    """{dígitos da conta: (arquivo, "") ou (None, porquê)} para cada conta
    pedida (menos as `ignoradas()`). Uma conta que falha não derruba as outras;
    sessão caída para a fila e marca as que faltavam. A que não está neste
    login leva `saldo.FORA_DESTE_LOGIN` (quem chama oferece o outro acesso)."""
    pasta = Path(pasta)
    ignorar = ignoradas() if ignorar is None else frozenset(ignorar)
    fila = [n for n in contas if saldo.so_digitos(n) not in ignorar]
    saida: dict = {}
    for i, numero in enumerate(fila):
        d = saldo.so_digitos(numero)
        if parar():
            for n in fila[i:]:
                saida[saldo.so_digitos(n)] = (None, PARADO)
            break
        progresso(i, len(fila))
        try:
            entrar(cli, numero, lista)
            cli.abrir_extrato()
            cli.definir_ordenacao()
            definir(cli, ini, fim)
            arquivo = pasta / f"{d}.ofx"
            pasta.mkdir(parents=True, exist_ok=True)
            cli.exportar_ofx(arquivo)
            saida[d] = (arquivo, "")
            log(f"{numero}: OFX baixado")
        except saldo.SessaoPerdida:
            log(saldo.SESSAO_CAIU)
            for n in fila[i:]:
                saida[saldo.so_digitos(n)] = (None, saldo.SESSAO_CAIU)
            break
        except Exception as e:                               # noqa: BLE001
            saida[d] = (None, _primeira_linha(e))
            log(f"{numero}: OFX não baixado — {_primeira_linha(e)}")
    progresso(len(fila), len(fila))
    return saida
