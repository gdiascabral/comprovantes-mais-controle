# -*- coding: utf-8 -*-
"""O nível de cada linha do HTML dos pagamentos (spec de 19/11/2026).

"Pode pagar", "Olhe" ou "Não li", com os motivos e a lista do que foi
conferido. Só CLASSIFICA o que `relatorio.montar_registros` já decidiu
(`status`, `conferencia`) e o que a leitura acrescentou (`parcela`,
`obs_parcela`); não confere nada de novo e não libera nem trava o Copiar.

Os essenciais são dois, valor e quem recebe (medido em 3.946 linhas de
set–nov/2026: exigir "nenhum ?" deixaria 4 em 5 linhas fora do verde).
Endereço, nota e ordem de compra aparecem, mas não derrubam o nível.
Peça de conferência que este módulo não reconhece é ignorada: os
essenciais nascem "não conferido", então o desconhecido nunca vira verde.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from . import ocr_boleto

PODE_PAGAR, OLHE, NAO_LI = "PODE_PAGAR", "OLHE", "NAO_LI"
ROTULO = {PODE_PAGAR: "PODE PAGAR", OLHE: "OLHE", NAO_LI: "NÃO LI"}
BATE, DIVERGE, NAO_CONFERIDO = "bate", "diverge", "nao"

#: Decisão 1 da spec: reembolso de sócio do cadastro fica em "Pode pagar".
REEMBOLSO_DE_SOCIO_PODE_PAGAR = True
#: Decisão 6 da spec: observação em título de parcela única só aparece.
OBS_DE_PARCELA_UNICA_LEVA_A_OLHE = False

_STATUS_NAO_LI = ("anexo não lido", "sem dados de pgto", "QR Code sem valor")
_PREFIXO = re.compile(r"^ATENÇÃO\s+—\s+")
_CENTAVO = Decimal("0.01")


@dataclass
class Nivel:
    nome: str
    motivos: list = field(default_factory=list)
    conferido: list = field(default_factory=list)        # [(item, estado)]


def _pecas(conferencia) -> list[str]:
    if isinstance(conferencia, (list, tuple)):
        conferencia = " · ".join(str(x) for x in conferencia)
    return [p.strip() for p in str(conferencia or "").split(" · ") if p.strip()]


def _marcar(estado: dict, chave: str, novo: str) -> None:
    """Diverge fica; bate só ocupa o lugar de "não conferido"."""
    atual = estado.get(chave)
    if atual == DIVERGE:
        return
    if novo == DIVERGE or atual in (None, NAO_CONFERIDO):
        estado[chave] = novo


def _dinheiro(valor) -> Decimal | None:
    try:
        return Decimal(str(valor)).quantize(_CENTAVO)
    except (InvalidOperation, ValueError, TypeError):
        return None


def _valor_do_pix(copia: str) -> Decimal | None:
    """O campo 54 (valor) do copia-e-cola, ou None. Só o nível de cima do TLV."""
    i, s = 0, str(copia or "")
    while i + 4 <= len(s):
        tag, tam = s[i:i + 2], s[i + 2:i + 4]
        if not tam.isdigit():
            return None
        valor = s[i + 4:i + 4 + int(tam)]
        if tag == "54":
            return _dinheiro(valor)
        i += 4 + int(tam)
    return None


def _valor_pelo_codigo(r: dict) -> bool:
    """O código conferido prova o valor: linha digitável com DV fechando e o
    valor embutido igual ao da linha; ou Pix copia-e-cola com o campo 54."""
    tipo, dados, valor = str(r.get("tipo") or ""), str(r.get("dados") or ""), _dinheiro(r.get("valor"))
    if valor is None or not dados:
        return False
    if tipo.upper().startswith("BOLETO"):
        embutido = ocr_boleto.valor_embutido(dados) if ocr_boleto.codigo_de_barras(dados) else None
        return embutido is not None and embutido.quantize(_CENTAVO) == valor
    if dados.startswith("000201"):
        return _valor_do_pix(dados) == valor
    return False


def conferido(r: dict) -> dict:
    estado = {"valor": NAO_CONFERIDO, "quem recebe": NAO_CONFERIDO}
    for p in _pecas(r.get("conferencia")):
        if p.startswith("valor ✓"):
            _marcar(estado, "valor", BATE)
        elif p.startswith("VALOR DIVERGE"):
            _marcar(estado, "valor", DIVERGE)
        if p.startswith(("fornecedor ✓", "beneficiário ✓", "CNPJ ✓")) or re.match(r"UC \S+ ✓", p):
            _marcar(estado, "quem recebe", BATE)
        elif p.startswith(("BENEFICIÁRIO DIVERGE", "CNPJ DIVERGE", "UC DIVERGE")):
            _marcar(estado, "quem recebe", DIVERGE)
        if re.match(r"OC \S+ ✓", p):
            _marcar(estado, "ordem de compra", BATE)
        elif p.startswith("OC DIVERGE"):
            _marcar(estado, "ordem de compra", DIVERGE)
        if re.match(r"NF \S+ ✓", p):
            _marcar(estado, "nota", BATE)
        elif p.startswith("NF DIVERGE"):
            _marcar(estado, "nota", DIVERGE)
        elif p.startswith("NF ?"):
            _marcar(estado, "nota", NAO_CONFERIDO)
        if "LOTE DIFERENTE" in p:
            _marcar(estado, "endereço", DIVERGE)
        elif p.startswith("endereço ✓"):
            _marcar(estado, "endereço", BATE)
        elif p.startswith("endereço ?"):
            _marcar(estado, "endereço", NAO_CONFERIDO)
    if _valor_pelo_codigo(r):
        _marcar(estado, "valor", BATE)
    if REEMBOLSO_DE_SOCIO_PODE_PAGAR and str(r.get("status") or "").startswith("APTO* (reembolso)"):
        # A chave é a do cadastro de sócios, com o CPF fechando o DV
        # (`reembolso.socio_do_documento`): quem recebe está provado.
        _marcar(estado, "quem recebe", BATE)
    return estado


def _sem_prefixo(status: str) -> str:
    return _PREFIXO.sub("", status).strip()


def nivel_da_linha(r: dict, *, bloqueio: str = "", vencido: bool = False) -> Nivel:
    status = str(r.get("status") or "")
    estado = conferido(r)
    nao_li, olhe = [], []
    if any(x in status for x in _STATUS_NAO_LI):
        nao_li.append(_sem_prefixo(status))
    parcela = r.get("parcela") or {}
    total = int(parcela.get("total") or 0)
    if total > 1 and not parcela.get("numero"):
        nao_li.append(f"parcelado em {total} — número da parcela não lido")
    if estado["valor"] == NAO_CONFERIDO:
        nao_li.append("valor não conferido em documento nenhum")
    if estado["quem recebe"] == NAO_CONFERIDO:
        nao_li.append("quem recebe não conferido")
    if not status.startswith("APTO"):
        olhe.append(_sem_prefixo(status) or "sem situação")
    elif status.startswith("APTO* (reembolso)") and not REEMBOLSO_DE_SOCIO_PODE_PAGAR:
        olhe.append("reembolso de sócio")
    if bloqueio:
        olhe.append(bloqueio)
    if vencido:
        olhe.append("vencido — confira se já não foi pago")
    for item, e in estado.items():
        if e == DIVERGE:
            olhe.append(f"{item} diverge")
    if r.get("obs_parcela") and (total > 1 or OBS_DE_PARCELA_UNICA_LEVA_A_OLHE):
        olhe.append("a parcela tem observação: leia antes de pagar")
    nome = NAO_LI if nao_li else OLHE if olhe else PODE_PAGAR
    return Nivel(nome, list(dict.fromkeys(nao_li + olhe)), list(estado.items()))


def para_o_html(n: Nivel, r: dict) -> dict:
    parcela = r.get("parcela") or {}
    total = int(parcela.get("total") or 0)
    return {"nivel": n.nome, "nivel_rotulo": ROTULO[n.nome], "motivos": list(n.motivos),
            "conferido": [[item, estado] for item, estado in n.conferido],
            "parcela": (f"{parcela.get('numero') or '?'} de {total}" if total > 1 else ""),
            "obs_parcela": str(r.get("obs_parcela") or "")}


def rebaixar_no_html(e: dict, motivo: str) -> None:
    """Aviso que o HTML acrescenta depois (mesma cobrança em dois lançamentos):
    "Pode pagar" desce para "Olhe"; "Não li" continua "Não li"."""
    if e.get("nivel") == PODE_PAGAR:
        e["nivel"], e["nivel_rotulo"] = OLHE, ROTULO[OLHE]
    e.setdefault("motivos", []).append(motivo)
