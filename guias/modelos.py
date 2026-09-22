# -*- coding: utf-8 -*-
"""Os tipos que atravessam o módulo `guias`, num lugar só.

Ficam separados porque `casamento` e `lancar` não podem importar `painel`
(tkinter) nem `calendario` (Playwright) para saber com o que trabalham — é o
que deixa os dois testáveis sem tela e sem navegador.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

#: As quatro ações possíveis para uma guia do mês.
ALTERAR = "alterar"
CRIAR = "criar"
JA_LANCADO = "ja_lancado"
DECIDIR = "decidir"


@dataclass
class Guia:
    """Uma linha do calendário do portal, já com o PDF lido (ou o motivo de não)."""
    vip_id: str
    empresa: str
    desc: str
    anx_id: str
    competencia: str                     # "2026-09"
    vencimento: date | None = None
    pdf: Path | None = None
    valor: Decimal | None = None
    documento: str = ""
    erro: str = ""
    #: O vencimento como o PORTAL informa (`prz` do calendário). Segundo dado
    #: autoritativo, de graça: a ficha de arrecadação (FGTS, INSS/IRRF,
    #: contribuição) não carrega vencimento no código de barras, e sem isto o
    #: lançamento nasceria com a data de hoje.
    vencimento_portal: date | None = None


@dataclass
class Decisao:
    """O que fazer com uma guia, antes de o dono confirmar."""
    guia: Guia
    acao: str
    motivo: str = ""
    tipo: str = ""
    categoria: str = ""
    obra_id: str = ""
    favorecido: str = ""
    descricao: str = ""
    parcelas: int = 1
    trade_payable_id: str = ""
    parcela_id: str = ""
    aviso: str = ""                      # divergência que não impede lançar
    #: A obra saiu de palpite sobre o texto do documento, e não da regra que o
    #: dono confirmou. A tela marca a linha para ele olhar antes de mandar.
    obra_sugerida: bool = False


@dataclass
class Resultado:
    """O desfecho de UMA gravação. `estado` nunca é "feito" sem prova."""
    estado: str
    tpid: str = ""
    motivo: str = ""
    anexos: list[str] = field(default_factory=list)


#: Os desfechos de `lancar`. "diverge" gravou mas não bateu na releitura;
#: "anexo_pendente" criou/alterou o título e o PDF não subiu.
ALTERADO = "alterado"
CRIADO = "criado"
DIVERGE = "diverge"
ANEXO_PENDENTE = "anexo_pendente"
ERRO = "erro"
