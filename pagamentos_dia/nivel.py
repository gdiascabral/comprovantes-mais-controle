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

from . import leitura_ia as li
from . import ocr_boleto

PODE_PAGAR, OLHE, NAO_LI = "PODE_PAGAR", "OLHE", "NAO_LI"
ROTULO = {PODE_PAGAR: "PODE PAGAR", OLHE: "OLHE", NAO_LI: "NÃO LI"}
BATE, DIVERGE, NAO_CONFERIDO = "bate", "diverge", "nao"

#: Decisão 1 da spec: reembolso de sócio do cadastro fica em "Pode pagar".
REEMBOLSO_DE_SOCIO_PODE_PAGAR = True
#: Decisão 6 da spec: observação em título de parcela única só aparece.
OBS_DE_PARCELA_UNICA_LEVA_A_OLHE = False

#: Quem recebe uma conta de arrecadação está DENTRO do código de barras:
#: posição 2 = segmento (2 = saneamento) e 16–19 = código da empresa
#: (Febraban). O dígito verificador fecha, então não é leitura de OCR.
#: Sanesc = segmento 2, empresa 3742: conferido em 3 boletins reais com o CNPJ
#: dela impresso (24/11/2026). Só entra aqui código conferido em documento.
#: Prova a EMPRESA, não a casa: o código não traz a UC (traz vencimento e
#: código de baixa). Sem a UC conferida a linha vai para "Olhe".
CONVENIO_DE = {("2", "3742"): "sanesc"}
MOTIVO_UC_NAO_CONFERIDA = "UC não conferida no boleto: confira se a conta é da casa certa"

#: Estados da leitura por IA que dão um valor para comparar (a spec, parte 3,
#: fase 1: prova de valor vinda da IA fica no máximo em "Olhe").
_IA_UTILIZAVEL = (li.BATE, li.TOTAL_BATE_SOMA_NAO_FECHA, li.SEM_SEGUNDA_PROVA, li.DIVERGE)
_IA_TIPO = {"recibo": "recibo", "pedido_de_balcao": "pedido de balcão",
            "comprovante_de_cartao": "comprovante de cartão", "nota_fiscal": "nota fiscal",
            "comprovante_de_pagamento": "comprovante de pagamento",
            "boleto": "boleto", "outro": "outro papel"}
MOTIVO_COMPROVANTE = "parece comprovante de pagamento: já foi pago?"

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


def _convenio_prova_quem_recebe(r: dict) -> bool:
    """O código de barras de arrecadação é da empresa que o lançamento diz
    pagar (`CONVENIO_DE`), com a linha fechando o dígito verificador."""
    tipo, dados = str(r.get("tipo") or ""), str(r.get("dados") or "")
    if not tipo.upper().startswith("BOLETO") or not ocr_boleto.eh_arrecadacao(dados):
        return False
    barra = ocr_boleto.codigo_de_barras(dados)
    if len(barra) != 44:
        return False
    nome = CONVENIO_DE.get((barra[1], barra[15:19]))
    favorecido = re.sub(r"[^a-z]", "", str(r.get("favorecido") or "").lower())
    return bool(nome) and nome in favorecido


def conferido(r: dict, com_ia: bool = True) -> dict:
    estado = {"valor": NAO_CONFERIDO, "quem recebe": NAO_CONFERIDO}
    for p in _pecas(r.get("conferencia")):
        if p.startswith("valor ✓") and _total(r) <= 1:
            # Em título parcelado o anexo pode ser o comprovante de OUTRA
            # parcela, do mesmo valor: lá só o código prova (abaixo).
            _marcar(estado, "valor", BATE)
        elif p.startswith("VALOR DIVERGE"):
            _marcar(estado, "valor", DIVERGE)
        # "fornecedor ✓" só vale quando o nome está num ANEXO: a peça também
        # sai quando o nome está só na observação do lançamento (revisão de
        # dinheiro, 20/11/2026). Registro sem a marca não conta.
        if (p.startswith(("beneficiário ✓", "CNPJ ✓")) or re.match(r"UC \S+ ✓", p)
                or (p.startswith("fornecedor ✓") and r.get("fornecedor_no_anexo"))):
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
    if _convenio_prova_quem_recebe(r):
        _marcar(estado, "quem recebe", BATE)
        if not any(re.match(r"UC \S+ ✓", p) for p in _pecas(r.get("conferencia"))):
            _marcar(estado, "conta da casa", NAO_CONFERIDO)
    ia = (r.get("leitura_ia") or {}) if com_ia else {}
    if ia.get("tipo_papel") == "comprovante_de_pagamento":
        pass                       # comprovante de quem já pagou não prova o valor a pagar
    elif ia.get("estado") == li.DIVERGE:
        _marcar(estado, "valor", DIVERGE)
    elif ia.get("estado") in _IA_UTILIZAVEL and _total(r) <= 1:
        # Só preenche o que está "não conferido", e não em título parcelado
        # (a leitura pode ser de outra parcela do mesmo valor).
        _marcar(estado, "valor", BATE)
    if REEMBOLSO_DE_SOCIO_PODE_PAGAR and r.get("reembolso_socio"):
        # Só o sócio do cadastro: a chave é a dele, com o CPF fechando o DV
        # (`reembolso.socio_do_documento`). O aviso "PAGAR PARA" também sai
        # "APTO* (reembolso)", mas quem o escreveu é quem vai receber.
        _marcar(estado, "quem recebe", BATE)
    return estado


def _total(r: dict) -> int:
    """Total de parcelas do título: o da parcela lida ou o da lista do ERP."""
    try:
        return max(int((r.get("parcela") or {}).get("total") or 0),
                   int(r.get("total_parcelas") or 0))
    except (TypeError, ValueError):
        return 0


def _brl(valor) -> str:
    v = _dinheiro(valor)
    return "?" if v is None else f"{v:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def motivo_da_ia(r: dict) -> str:
    """"lido por IA: R$ 435,00 × lançamento R$ 410,00 — diverge" (e as provas,
    quando houver): o motivo que acompanha toda linha cujo valor veio da IA."""
    ia = r.get("leitura_ia") or {}
    lido = f"R$ {_brl(ia['total_lido'])}" if ia.get("total_lido") else "total não lido"
    provas = (f" ({', '.join(ia['provas'])})"
              if ia.get("provas") and ia.get("estado") != li.DIVERGE else "")
    return f"lido por IA: {lido} × lançamento R$ {_brl(r.get('valor'))} — {ia.get('estado')}{provas}"


def etiqueta_da_ia(r: dict) -> dict | None:
    """O que os dois HTML mostram de `registro["leitura_ia"]`:
    `{"titulo": "lido por IA: recibo · total R$ 410,00 · bate", "linhas": [...]}`."""
    ia = r.get("leitura_ia")
    if not ia:
        return None
    if ia.get("falhou"):
        return {"titulo": "lido por IA: não respondeu", "linhas": list(ia.get("motivos") or [])}
    if ia.get("pulado"):
        return {"titulo": "lido por IA: não lido", "linhas": list(ia.get("motivos") or [])}
    partes = [_IA_TIPO.get(ia.get("tipo_papel"), "papel"),
              f"total R$ {_brl(ia['total_lido'])}" if ia.get("total_lido") else "total não lido",
              ia.get("estado") or ""]
    linhas = []
    if ia.get("provas"):
        linhas.append("provas: " + ", ".join(ia["provas"]))
    linhas += [m for m in ia.get("motivos") or [] if m]
    linhas += [x for x in (ia.get("oc"), ia.get("endereco")) if x]
    if ia.get("duvidas"):
        linhas.append("a IA duvidou de: " + ", ".join(ia["duvidas"]))
    if ia.get("nao_lidos") and int(ia.get("anexos") or 0) > 1:
        linhas.append(f"{ia['nao_lidos']} anexo(s) não lido(s) pela IA")
    return {"titulo": "lido por IA: " + " · ".join(p for p in partes if p), "linhas": linhas}


def _sem_prefixo(status: str) -> str:
    return _PREFIXO.sub("", status).strip()


def nivel_da_linha(r: dict, *, bloqueio: str = "", vencido: bool = False) -> Nivel:
    status = str(r.get("status") or "")
    estado = conferido(r)
    nao_li, olhe = [], []
    if any(x in status for x in _STATUS_NAO_LI):
        nao_li.append(_sem_prefixo(status))
    parcela = r.get("parcela") or {}
    total = _total(r)
    if total > 1 and not parcela.get("numero"):
        nao_li.append(f"parcelado em {total} — número da parcela não lido")
    if estado["valor"] == NAO_CONFERIDO:
        nao_li.append("valor não conferido em documento nenhum")
    if estado["quem recebe"] == NAO_CONFERIDO:
        nao_li.append("quem recebe não conferido")
    ia = r.get("leitura_ia") or {}
    if ia:
        # A IA só pesa onde ela é a prova: linha cujo valor já está provado por
        # outro anexo ou pelo código nunca piora por causa dela (revisão de
        # dinheiro, 25/11/2026) — a não ser que diverja.
        aberto = conferido(r, com_ia=False)["valor"] == NAO_CONFERIDO
        diverge = ia.get("estado") == li.DIVERGE
        if ia.get("tipo_papel") == "comprovante_de_pagamento":
            olhe.append(MOTIVO_COMPROVANTE)
        elif ia.get("falhou"):
            if aberto:
                nao_li.append("IA não respondeu")
        elif ia.get("estado") not in _IA_UTILIZAVEL:
            if aberto:
                nao_li.append(f"IA não leu: {ia['motivos'][0]}" if ia.get("pulado") and ia.get("motivos")
                              else "lido por IA: não conseguiu ler o documento")
        elif aberto or diverge:
            olhe.append(motivo_da_ia(r))
        if (aberto or diverge) and ia.get("nao_lidos") and int(ia.get("anexos") or 0) > 1:
            olhe.append(f"{ia['nao_lidos']} anexo(s) não lido(s) pela IA")
    if not status.startswith("APTO"):
        olhe.append(_sem_prefixo(status) or "sem situação")
    elif status.startswith("APTO* (reembolso)"):
        if not r.get("reembolso_socio"):
            olhe.append('reembolso por aviso "PAGAR PARA": confira para quem vai')
        elif not REEMBOLSO_DE_SOCIO_PODE_PAGAR:
            olhe.append("reembolso de sócio")
    if bloqueio:
        olhe.append(bloqueio)
    if vencido:
        olhe.append("vencido — confira se já não foi pago")
    for item, e in estado.items():
        if e == DIVERGE:
            olhe.append(f"{item} diverge")
    if estado.get("conta da casa") == NAO_CONFERIDO:
        olhe.append(MOTIVO_UC_NAO_CONFERIDA)
    if r.get("obs_parcela") and (total > 1 or OBS_DE_PARCELA_UNICA_LEVA_A_OLHE):
        olhe.append("a parcela tem observação: leia antes de pagar")
    nome = NAO_LI if nao_li else OLHE if olhe else PODE_PAGAR
    return Nivel(nome, list(dict.fromkeys(nao_li + olhe)), list(estado.items()))


def para_o_html(n: Nivel, r: dict) -> dict:
    parcela = r.get("parcela") or {}
    total = _total(r)
    return {"nivel": n.nome, "nivel_rotulo": ROTULO[n.nome], "motivos": list(n.motivos),
            "conferido": [[item, estado] for item, estado in n.conferido],
            "parcela": (f"{parcela.get('numero') or '?'} de {total}" if total > 1 else ""),
            "obs_parcela": str(r.get("obs_parcela") or ""),
            "leitura_ia": etiqueta_da_ia(r)}


def rebaixar_no_html(e: dict, motivo: str) -> None:
    """Aviso que o HTML acrescenta depois (mesma cobrança em dois lançamentos):
    "Pode pagar" desce para "Olhe"; "Não li" continua "Não li"."""
    if e.get("nivel") == PODE_PAGAR:
        e["nivel"], e["nivel_rotulo"] = OLHE, ROTULO[OLHE]
    e.setdefault("motivos", []).append(motivo)
