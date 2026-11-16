# -*- coding: utf-8 -*-
"""O que já foi importado no ERP, por conta, para nunca importar duas vezes
(revisão de dinheiro de 16/11/2026).

O período padrão é "ontem a hoje" (dono, 29/10/2026), então o "hoje" de um
dia é o "ontem" do seguinte; e uma rodada parada no meio, clicada de novo,
mandaria outra vez as contas que já tinham entrado. Não se sabe ainda se o ERP
descarta lançamento repetido (é medido na primeira rodada ao vivo), então o
app não confia nele: guarda a CHAVE de cada lançamento enviado e, antes de
mandar, tira do OFX os que já foram.

A chave é o FITID (o identificador que o banco dá ao lançamento, único na
conta); lançamento sem FITID usa data + valor + histórico, e dois desses
iguais no mesmo arquivo continuam DOIS (o segundo leva `#2`) — nunca se junta
o que o banco mandou separado.

O que foi enviado e o ERP não confirmou também entra no registro (`incerto`):
o app nunca reenvia; a pessoa confere no extrato do ERP. Arquivo do registro:
`<pasta>/importados.json`, `{erp_id: {"chaves": [...], "incertas": [...]}}`.
Ilegível = LEVANTA (sem ele não se sabe o que já entrou).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

ARQUIVO = "importados.json"
_RE_BLOCO = re.compile(r"<STMTTRN>.*?(?:</STMTTRN>\s*|(?=<STMTTRN>|</BANKTRANLIST>))",
                       re.S | re.I)


class RegistroIlegivel(RuntimeError):
    """O registro do que já foi importado existe e não se lê."""


def _campo(bloco: str, nome: str) -> str:
    m = re.search(rf"<{nome}>([^<\r\n]*)", bloco, re.I)
    return (m.group(1) if m else "").strip()


def _chave(bloco: str) -> str:
    fitid = _campo(bloco, "FITID")
    if fitid:
        return f"fitid:{fitid}"
    return "sem:" + "|".join(_campo(bloco, n) for n in ("DTPOSTED", "TRNAMT", "MEMO"))


def chaves(texto: str) -> list[str]:
    """Uma chave por lançamento, na ordem do arquivo (repetidas ganham #n)."""
    vistas: dict[str, int] = {}
    saida = []
    for bloco in _RE_BLOCO.findall(texto or ""):
        k = _chave(bloco)
        vistas[k] = vistas.get(k, 0) + 1
        saida.append(k if vistas[k] == 1 else f"{k}#{vistas[k]}")
    return saida


def sem_os_ja_importados(texto: str, ja: set) -> tuple[str, list[str], int]:
    """(o OFX só com os lançamentos novos, as chaves deles, quantos saíram)."""
    blocos = _RE_BLOCO.findall(texto or "")
    todas = chaves(texto)
    novas, tirados = [], 0
    pos, partes = 0, []
    for bloco, k in zip(blocos, todas):
        i = texto.index(bloco, pos)
        partes.append(texto[pos:i])
        pos = i + len(bloco)
        if k in ja:
            tirados += 1
        else:
            partes.append(bloco)
            novas.append(k)
    partes.append(texto[pos:])
    return "".join(partes), novas, tirados


def ler(pasta) -> dict[str, set]:
    """{erp_id: chaves já enviadas (confirmadas ou incertas)}."""
    alvo = Path(pasta) / ARQUIVO
    if not alvo.exists():
        return {}
    try:
        dados = json.loads(alvo.read_text(encoding="utf-8"))
        return {str(k): set(v.get("chaves", [])) | set(v.get("incertas", []))
                for k, v in dados.items()}
    except (OSError, ValueError, AttributeError, TypeError) as e:
        raise RegistroIlegivel(f"não li {ARQUIVO} ({e}) — sem ele não sei o que já "
                               "entrou no ERP; nada é importado") from None


def registrar(pasta, erp_id: str, novas, *, incerto: bool) -> None:
    """Acrescenta as chaves enviadas (gravação atômica: arquivo novo e troca)."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / ARQUIVO
    dados = {}
    if alvo.exists():
        try:
            dados = json.loads(alvo.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            raise RegistroIlegivel(f"não li {ARQUIVO} ({e})") from None
    item = dados.setdefault(str(erp_id), {"chaves": [], "incertas": []})
    lado = "incertas" if incerto else "chaves"
    item[lado] = sorted(set(item.get(lado, [])) | set(novas))
    tmp = alvo.with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, alvo)
