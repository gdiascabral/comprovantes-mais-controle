# -*- coding: utf-8 -*-
"""O link do lançamento do ERP colado no pagamento à mão (aba "Pagamentos do dia").

Por enquanto só o `LancamentoLido`, que a conferência (`conferencia.nova_a_mao`)
usa para não pagar mais que o em aberto nem título já pago. A leitura pelo
Chrome do app (`id_do_link`, `do_item`, `ler`) chega na Tarefa 7 da entrega 2,
neste mesmo arquivo.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True)
class LancamentoLido:
    id: str
    conta: str = ""
    favorecido: str = ""
    centro_custo: str = ""
    nf: str = ""
    oc: str = ""
    descricao: str = ""
    em_aberto: Decimal | None = None
    vencimento: date | None = None
    pago: bool = False
    avisos: tuple = ()
