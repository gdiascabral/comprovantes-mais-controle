# -*- coding: utf-8 -*-
"""Quais casas tiveram o financiamento recebido no mês.

Entra a lista crua de recebimentos do ERP, sai uma lista de IMÓVEIS. Sem
navegador e sem tkinter: roda inteiro em teste.

Dois nomes da API enganam, e é por isso que eles são traduzidos logo na
entrada:

    readjustmentType  é a coluna "Condição" da tela — onde mora "1ª FINANCIAMENTO"
    workName          é o "Centro de Custo", que é o NOME da obra

A igualdade entre `workName` e o `name` da obra é a ponte entre as duas metades
do trabalho (achar quem financiou, e achar o contrato daquela obra).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

#: A condição que interessa. Comparada sem acento e sem caixa.
MARCA_FINANCIAMENTO = "FINANCIAMENTO"

#: A linha de juros cai na MESMA data, obra e casa do financiamento: é um
#: lançamento só, separado por controle interno. Some no agrupamento, mas os
#: valores ficam distintos — o contrato confere contra o financiamento puro.
MARCA_JUROS = "JUROS"

#: `CASA 01`, `CS 3`, `cs1`, `C12` são todas unidade. O `\b` no fim evita que
#: "CS 1" engula o "12" de um "CS 12" quando a descrição continua em número.
RE_UNIDADE = re.compile(r"\b(?:CASA|CS|C)\s*0*(\d{1,3})\b", re.I)


def numero_da_unidade(texto: str) -> int | None:
    """O número da casa em `texto`, ou None.

    Aceita as quatro grafias que aparecem no cadastro real, com ou sem espaço
    e com ou sem zero à esquerda."""
    m = RE_UNIDADE.search(util.sem_acento(texto or ""))
    return int(m.group(1)) if m else None


def rotulo_da_unidade(numero: int) -> str:
    """1 -> "CS 01". Dois dígitos, como no nome dos arquivos do ERP."""
    return f"CS {numero:02d}"


def partes_da_descricao(descricao: str) -> tuple[int | None, str]:
    """(unidade, comprador) de "VENDA CASA 01 - ISABELLA RENATA GONÇALVES".

    A unidade é procurada SÓ na parte antes do primeiro " - ". Sem isso, um
    comprador chamado "CARLOS" viraria a casa 0 e um "ANA CASA NOVA" viraria
    outra — o nome do comprador é texto livre e não pode alimentar o
    reconhecedor de casa."""
    texto = (descricao or "").strip()
    if " - " in texto:
        cabeca, cauda = texto.split(" - ", 1)
    else:
        cabeca, cauda = texto, ""
    return numero_da_unidade(cabeca), cauda.strip()


def _dinheiro(valor) -> Decimal:
    """Para Decimal com 2 casas. Dinheiro em float erra, e daqui ele vai para
    a conferência do contrato."""
    if isinstance(valor, Decimal):
        d = valor
    elif isinstance(valor, float):
        d = Decimal(str(valor))
    else:
        d = Decimal(valor or 0)
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def eh_financiamento(condicao: str) -> bool:
    return MARCA_FINANCIAMENTO in util.norm(condicao)


def eh_juros(condicao: str) -> bool:
    return MARCA_JUROS in util.norm(condicao)


@dataclass
class Imovel:
    """Uma casa cujo financiamento entrou no mês."""

    obra: str                       # workName, igual ao name da obra
    unidade: int                    # 1, 2...
    comprador: str
    valor_financiamento: Decimal = Decimal("0.00")
    juros: Decimal = Decimal("0.00")
    data: str = ""                  # aaaa-mm-dd do recebimento
    condicoes: list[str] = field(default_factory=list)
    ids: list[str] = field(default_factory=list)
    revisao: str = ""               # motivo, quando não dá para seguir

    @property
    def chave(self) -> tuple[str, int]:
        """O que identifica o imóvel: obra + unidade.

        O lote tem mais de uma casa — a obra `TB 21 QD 46 LT 18` é do tipo
        "2 casas". Agrupar só por obra juntaria dois contratos diferentes."""
        return (util.norm_espaco(self.obra), self.unidade)

    @property
    def rotulo(self) -> str:
        return rotulo_da_unidade(self.unidade)


def imoveis_do_mes(registros: list[dict], log=print) -> list[Imovel]:
    """Recebimentos crus -> imóveis financiados, agrupados por obra + casa.

    Natureza e status já vieram filtrados do servidor, mas a condição é
    reconferida aqui: filtro que o servidor ignora em SILÊNCIO já aconteceu
    neste ERP (`pageSize` no endpoint de recebimentos), e um filtro ignorado
    sem aviso é pior do que filtro nenhum."""
    por_chave: dict[tuple[str, int], Imovel] = {}
    sem_unidade = 0

    for r in registros:
        condicao = r.get("readjustmentType") or ""
        if not eh_financiamento(condicao):
            continue

        obra = (r.get("workName") or "").strip()
        if not obra:
            sem_unidade += 1
            continue

        unidade, comprador = partes_da_descricao(r.get("description"))
        if unidade is None:
            # Sem casa não dá para escolher o contrato: são vários por obra.
            sem_unidade += 1
            continue

        chave = (util.norm_espaco(obra), unidade)
        imovel = por_chave.get(chave)
        if imovel is None:
            imovel = Imovel(obra=obra, unidade=unidade, comprador=comprador)
            por_chave[chave] = imovel
        # O comprador vem da linha do financiamento; a de juros costuma
        # repetir, mas se vier vazia não pode apagar o que já se sabe.
        if comprador and not imovel.comprador:
            imovel.comprador = comprador

        valor = _dinheiro(r.get("sumOfReceivedValues"))
        if eh_juros(condicao):
            imovel.juros += valor
        else:
            imovel.valor_financiamento += valor
            imovel.data = imovel.data or (r.get("dateOfReceipt") or "")[:10]

        imovel.condicoes.append(condicao)
        if r.get("id"):
            imovel.ids.append(r["id"])

    if sem_unidade:
        log(f"  [aviso] {sem_unidade} recebimento(s) de financiamento sem obra "
            "ou sem casa na descrição — fora da lista")

    imoveis = sorted(por_chave.values(), key=lambda i: (i.obra, i.unidade))
    for imovel in imoveis:
        if imovel.valor_financiamento <= 0:
            # Só a linha de juros no mês: o financiamento caiu em outro mês e
            # aqui não há contrato novo a buscar.
            imovel.revisao = ("só a parcela de JUROS entrou neste mês; o "
                              "financiamento foi recebido em outro mês")
    return imoveis
