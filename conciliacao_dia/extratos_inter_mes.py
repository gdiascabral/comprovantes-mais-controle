# -*- coding: utf-8 -*-
"""Os OFX do mês inteiro das contas do Inter, para o fechamento mensal
(aba Acessórias, Task 8 do plano de 29/10/2026). Nada vai ao ERP.

Um login do `contas_inter.json` por vez, cada um com o seu QR. O arquivo cai
primeiro numa pasta de espera e só vai para a pasta do mês depois de conferido
(`ofx_regras.conferir_ofx`): ACCTID = o número da conta que a TELA mostrou e
o período = o mês pedido. OFX que não confere não chega à pasta do mês — é a
pasta que o "Gerar os .zip" manda ao escritório.

Destino: `<mês>/<MÊS ANO - EMPRESA>/<pasta do login>/<dígitos da conta>.ofx`,
a mesma árvore dos extratos do Sicoob (`sicoob_pastas.caminho_do_mes`)."""
from __future__ import annotations

import datetime as _dt
import shutil
from dataclasses import dataclass
from pathlib import Path

import util

from . import ofx_regras as r


@dataclass(frozen=True)
class ExtratoInter:
    apelido: str
    arquivo: Path | None = None
    lancamentos: int | None = None
    motivo: str = ""


def nomes_do_login(login, empresas) -> tuple:
    """(nomes, razões) que conferem a conta aberta: o nome curto da empresa
    do login e a razão social inteira do cadastro, quando houver."""
    empresa = util.norm_espaco(login.empresa)
    razoes = tuple(dict.fromkeys(
        getattr(e, "razao_social", "") for e in empresas or ()
        if util.norm_espaco(getattr(e, "nome", "")) == empresa
        and (getattr(e, "razao_social", "") or "").strip()))
    nomes = tuple(dict.fromkeys(n for n in (login.empresa, *razoes) if (n or "").strip()))
    return nomes, razoes


def destino(pasta_do_mes: Path, ano: int, mes: int, login, numero: str) -> Path:
    from extratos_sicoob import sicoob_config as cfg
    digitos = "".join(ch for ch in str(numero or "") if ch.isdigit())
    return (Path(pasta_do_mes) / cfg.nome_pasta_empresa(ano, mes, login.empresa)
            / (login.pasta or "INTER") / f"{digitos or login.apelido}.ofx")


def baixar_mes(logins, ano: int, mes: int, pasta_do_mes: Path, espera: Path, *,
               empresas=(), baixar=None, log=print, avisar_qr=lambda a: None,
               parar=lambda: False) -> list[ExtratoInter]:
    """Um `ExtratoInter` por login válido, na ordem do cadastro. Nunca
    levanta por causa de uma conta: o desfecho vem na linha dela."""
    if baixar is None:
        from baixar_comprovantes.inter_ofx import baixar_conta as baixar
    ini, fim = r.periodo_do_mes(ano, mes)
    hoje = _dt.date.today()
    fim = min(fim, hoje)                     # mês corrente: até hoje
    saida: list[ExtratoInter] = []
    for login in logins:
        if not login.valida:
            continue
        if parar():
            saida.append(ExtratoInter(login.apelido, motivo="parado antes desta conta"))
            continue
        nomes, razoes = nomes_do_login(login, empresas)
        tmp = Path(espera) / f"{login.apelido}.ofx"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        try:
            res = baixar(login.apelido, "", nomes, razoes, ini, fim, tmp, log=log,
                         avisar_qr=avisar_qr, parar=parar)
        except Exception as e:                               # noqa: BLE001
            saida.append(ExtratoInter(login.apelido, motivo=f"erro inesperado: {e}"))
            continue
        if res.arquivo is None:
            saida.append(ExtratoInter(login.apelido, motivo=res.motivo or "o OFX não veio"))
            continue
        try:
            texto = Path(res.arquivo).read_text(encoding="cp1252", errors="replace")
        except OSError as e:
            saida.append(ExtratoInter(login.apelido, motivo=f"não li o arquivo baixado: {e}"))
            continue
        porque = r.conferir_ofx(texto, res.numero_na_tela, ini, fim)
        if porque:
            saida.append(ExtratoInter(login.apelido, motivo=f"não gravado: {porque}"))
            continue
        alvo = destino(pasta_do_mes, ano, mes, login, res.numero_na_tela)
        alvo.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(res.arquivo), str(alvo))
        saida.append(ExtratoInter(login.apelido, alvo, r.lancamentos(texto)))
    return saida
