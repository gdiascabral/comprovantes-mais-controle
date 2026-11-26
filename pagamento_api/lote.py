# -*- coding: utf-8 -*-
"""O lote do dia que vai para aprovação: o que pode ir pela API e o que fica fora.

Módulo puro: sem tela, sem rede. Entra a lista de
`html_pagamentos.contas_do_html_geral` (o mesmo dado que o HTML do dia mostra) e
sai a lista de `ItemLote`, mais a lista do que fica FORA com o motivo. Dinheiro em
Decimal, sempre a partir dos centavos.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Decimal

from pagamentos_dia import nivel, ocr_boleto
from pagamentos_dia import regras_pagamento as regras

BOLETO, PIX_CHAVE, PIX_QR, CONVENIO = "boleto", "pix_chave", "pix_qr", "convenio"
TIPOS = (BOLETO, PIX_CHAVE, PIX_QR, CONVENIO)
#: Teto da descrição nos bancos que não são o Inter (decisão de 14/09/2026).
LIMITE_DESCRICAO = 100


@dataclass(frozen=True)
class ItemLote:
    ordem: int
    titulo: str              # id do lançamento no ERP (sem o "#parte")
    alvo: str                # id da linha do HTML (chave do "já paguei")
    conta: str               # nome da conta pagadora, como no ERP
    tipo: str                # um de TIPOS
    dados: str               # código de barras de 44 | chave | copia-e-cola
    valor: Decimal
    favorecido: str
    documento_esperado: str  # CPF/CNPJ só dígitos ("" quando o cadastro não tem)
    descricao: str


@dataclass(frozen=True)
class Fora:
    alvo: str
    conta: str
    valor: Decimal
    favorecido: str
    motivo: str


def _norm(texto) -> str:
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(t.upper().split())


def e_sicoob(conta) -> bool:
    return "SICOOB" in _norm(conta)


def tipo_api(tipo_html: str, dados) -> tuple[str, str]:
    """(tipo da API, dado pronto) ou ("", motivo) quando não dá para pagar pela API."""
    d = str(dados or "").strip()
    if not d:
        return "", "sem dado de pagamento"
    if tipo_html == "Pix":
        if regras.PIX_COPIA_COLA.search(re.sub(r"\s+", "", d)):
            return PIX_QR, re.sub(r"\s+", "", d)
        return PIX_CHAVE, d
    if tipo_html == "Boleto":
        dig = ocr_boleto.digitos(d)
        barras = ocr_boleto.codigo_de_barras(dig) if len(dig) in (47, 48) else ""
        if len(barras) != 44:
            return "", "linha digitável não confere"
        return (CONVENIO if barras.startswith("8") else BOLETO), barras
    return "", f"tipo {tipo_html or '?'} não vai pela API"


def itens_do_html(contas: list[dict], documento_de) -> tuple[list[ItemLote], list[Fora]]:
    """As entradas do HTML do dia viram itens do lote ou linhas de fora.

    Entra só o que o HTML diz "PODE PAGAR", sem bloqueio, em conta Sicoob, com
    lançamento do ERP e que não seja parte de lançamento dividido (o mesmo título
    em mais de uma linha) nem pagamento à mão. `documento_de(favorecido)` devolve
    o CPF/CNPJ do cadastro ("" se não houver)."""
    itens: list[ItemLote] = []
    fora: list[Fora] = []
    por_titulo: dict[str, int] = {}
    for c in contas:
        for e in c.get("entries", ()):
            t = str(e.get("id") or "").split("#", 1)[0]
            if t:
                por_titulo[t] = por_titulo.get(t, 0) + 1
    for c in contas:
        conta = str(c.get("nome") or "")
        for e in c.get("entries", ()):
            alvo = str(e.get("id") or "")
            valor = (Decimal(int(e.get("centavos") or 0)) / 100).quantize(Decimal("0.01"))
            fav = str(e.get("favorecido") or "")
            titulo, _, resto = alvo.partition("#")
            motivo = ""
            tipo = dado = ""
            if not e_sicoob(conta):
                motivo = "conta não é Sicoob"
            elif not titulo or resto.startswith("mao:"):
                motivo = "pagamento à mão, sem lançamento"
            elif por_titulo.get(titulo, 0) > 1:
                motivo = "lançamento dividido em mais de uma linha"
            elif e.get("bloqueio"):
                motivo = str(e["bloqueio"])
            elif e.get("nivel") != nivel.PODE_PAGAR:
                motivo = f"nível {e.get('nivel_rotulo') or e.get('nivel') or '?'}"
            elif valor <= 0:
                motivo = "valor zero"
            else:
                tipo, dado = tipo_api(str(e.get("tipo") or ""), e.get("dados_limpo"))
                if not tipo:
                    motivo = dado
            doc = re.sub(r"\D", "", str(documento_de(fav) or "")) if not motivo else ""
            if not motivo and tipo == PIX_CHAVE and len(doc) not in (11, 14):
                motivo = "Pix sem CPF/CNPJ do favorecido no cadastro"
            if motivo:
                fora.append(Fora(alvo, conta, valor, fav, motivo))
                continue
            itens.append(ItemLote(len(itens) + 1, titulo, alvo, conta, tipo, dado, valor,
                                  fav, doc, str(e.get("descricao") or "")[:LIMITE_DESCRICAO]))
    return itens, fora


def total(itens) -> Decimal:
    return sum((i.valor for i in itens), Decimal("0.00"))
