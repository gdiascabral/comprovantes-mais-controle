"""Modelos que atravessam o programa.

Dinheiro e sempre `Decimal`; float aparece so na fronteira com o openpyxl.
Um `Snapshot` e o contrato entre a coleta (browser) e todo o resto (offline).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal


@dataclass(frozen=True)
class Periodo:
    """Intervalo de vencimentos que entra no painel (inclusivo nas duas pontas).

    Existe porque numa segunda-feira os titulos de sabado e domingo continuam em
    aberto e precisam ser somados junto com os de segunda.
    """

    inicio: date
    fim: date

    def __post_init__(self) -> None:
        if self.inicio > self.fim:
            raise ValueError(f"periodo invertido: {self.inicio} > {self.fim}")

    @classmethod
    def de_um_dia(cls, dia: date) -> "Periodo":
        return cls(inicio=dia, fim=dia)

    @classmethod
    def normalizar(cls, valor: "Periodo | date") -> "Periodo":
        """Aceita um `date` solto e trata como periodo de um dia."""
        return valor if isinstance(valor, Periodo) else cls.de_um_dia(valor)

    def contem(self, dia: date | None) -> bool:
        return dia is not None and self.inicio <= dia <= self.fim

    @property
    def dias(self) -> list[date]:
        total = (self.fim - self.inicio).days
        return [self.inicio + timedelta(days=n) for n in range(total + 1)]

    @property
    def um_dia_so(self) -> bool:
        return self.inicio == self.fim

    def descrever(self) -> str:
        if self.um_dia_so:
            return f"{self.fim:%d/%m/%Y}"
        return f"{self.inicio:%d/%m/%Y} a {self.fim:%d/%m/%Y}"


def sugerir_periodo(hoje: date) -> Periodo:
    """Periodo padrao: hoje mais os dias nao-uteis imediatamente anteriores.

    Numa segunda devolve sabado..segunda; nos outros dias, so o proprio dia.
    Feriados nao sao considerados (o programa nao tem calendario) — nesses casos
    o usuario informa o intervalo na mao.
    """
    inicio = hoje
    while True:
        anterior = inicio - timedelta(days=1)
        # weekday(): 5 = sabado, 6 = domingo
        if anterior.weekday() >= 5:
            inicio = anterior
        else:
            break
    return Periodo(inicio=inicio, fim=hoje)


@dataclass(frozen=True)
class ErpAccount:
    """Conta bancaria como o ERP expoe em #/accounts."""

    id: str  # account.id (UUID) — chave estavel de match
    name: str
    is_active: bool = True
    bank_code: str | None = None
    agency: str | None = None
    account_number: str | None = None
    raw_balance: str | None = None  # texto do span, ex. "R$ - 1.179,29"
    balance: Decimal | None = None  # None = mascarado ou nao lido, NUNCA zero


@dataclass(frozen=True)
class ErpPayment:
    """Parcela a pagar como a grade MUI expoe em #/payable-installments."""

    due_date: date | None
    status: str
    amount: Decimal | None
    payee: str = ""
    account_label: str = ""  # celula "Condicao e Conta", sem o prefixo
    raw: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Snapshot:
    """Foto bruta do ERP num instante. Reprocessavel sem abrir o browser."""

    reference_date: date
    collected_at: str
    accounts: list[ErpAccount] = field(default_factory=list)
    payments: list[ErpPayment] = field(default_factory=list)
    # Agregado "Em aberto" do rodape da grade, usado para validacao cruzada.
    page_aggregate_open: Decimal | None = None
    #: Intervalo de vencimentos pedido nesta coleta (None = so a data de
    #: referencia). Guardado para auditoria e para reprocessar do jeito certo.
    periodo: Periodo | None = None

    @property
    def intervalo(self) -> Periodo:
        """Periodo efetivo do snapshot."""
        return self.periodo or Periodo.de_um_dia(self.reference_date)


@dataclass(frozen=True)
class ModelRow:
    """Uma das 24 linhas de conta do painel (linhas 8 a 31)."""

    row: int
    label: str  # coluna B do modelo
    uuid: str | None = None
    account_number: str | None = None  # normalizado (so digitos)
    erp_name: str | None = None
    exists_in_erp: bool = True


@dataclass(frozen=True)
class RowFill:
    """O que sera escrito numa linha. None significa CELULA VAZIA, nao zero."""

    row: int
    balance: Decimal | None  # D
    total: Decimal | None  # E
    count: int | None  # I
    bank_count: int | None  # J
