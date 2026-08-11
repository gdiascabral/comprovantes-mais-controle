"""Descoberta de contas: propoe e aplica os UUIDs no mapping.yaml.

Ninguem transcreve 24 UUIDs a mao sem errar. Este modulo le o ERP, casa cada
conta com a linha do painel e grava o `account.id` no mapping.yaml preservando
todos os comentarios do arquivo (por isso a edicao e textual, nao via YAML).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from ..mapping import AccountMapping
from ..models import ErpAccount
from ..parsing import format_brl


@dataclass
class Descoberta:
    #: linha do painel -> conta do ERP casada
    casadas: dict[int, ErpAccount]
    #: linhas do painel que nao encontraram conta
    sem_correspondencia: list[int]
    #: contas do ERP fora do painel e fora da lista de ignoradas
    desconhecidas: list[ErpAccount]

    @property
    def uuids(self) -> dict[int, str]:
        return {linha: c.id for linha, c in self.casadas.items() if c.id}


def descobrir(contas: list[ErpAccount], mapping: AccountMapping) -> Descoberta:
    """Casa contas do ERP com linhas do painel, para propor os uuids.

    ATENCAO: contas ignoradas saem da disputa ANTES do match (mesmo motivo
    explicado em `rules.resolve_balances`). Sem isso, a conta "APLICACAO FUNDO
    INVESTIMENTOS - ... BURITIS - CAIXA ECONOMICA FEDERAL" casava com a linha
    27 por continencia e, como aqui a PRIMEIRA vence, era o uuid dela que
    seria gravado — travando o painel na conta errada para sempre.
    """
    casadas: dict[int, ErpAccount] = {}
    desconhecidas: list[ErpAccount] = []

    for conta in contas:
        if mapping.is_ignored(conta.name):
            continue

        linha = mapping.resolve_account(conta)
        if linha is not None and linha.exists_in_erp:
            casadas.setdefault(linha.row, conta)
        else:
            desconhecidas.append(conta)

    sem = [r.row for r in mapping.live_rows if r.row not in casadas]
    return Descoberta(casadas=casadas, sem_correspondencia=sem, desconhecidas=desconhecidas)


def aplicar_uuids(caminho: str | Path, uuids: dict[int, str]) -> int:
    """Escreve `uuid:` de cada linha no mapping.yaml, mantendo os comentarios.

    Devolve quantas entradas foram alteradas.
    """
    caminho = Path(caminho)
    linhas = caminho.read_text(encoding="utf-8").splitlines()

    padrao_row = re.compile(r"^\s*-\s*row:\s*(\d+)\s*$")
    padrao_uuid = re.compile(r"^(\s*)uuid:\s*.*$")

    atual: int | None = None
    alteradas = 0
    saida: list[str] = []

    for linha in linhas:
        achou_row = padrao_row.match(linha)
        if achou_row:
            atual = int(achou_row.group(1))
            saida.append(linha)
            continue

        achou_uuid = padrao_uuid.match(linha)
        if achou_uuid and atual is not None and atual in uuids:
            saida.append(f'{achou_uuid.group(1)}uuid: "{uuids[atual]}"')
            alteradas += 1
            atual = None
            continue

        saida.append(linha)

    caminho.write_text("\n".join(saida) + "\n", encoding="utf-8")
    return alteradas


def relatorio(descoberta: Descoberta, mapping: AccountMapping) -> str:
    partes = ["DESCOBERTA DE CONTAS NO ERP", "=" * 64, ""]

    partes.append(f"Casadas: {len(descoberta.casadas)} de {len(mapping.live_rows)} linhas")
    for linha in sorted(descoberta.casadas):
        conta = descoberta.casadas[linha]
        modelo = mapping.by_row(linha)
        partes.append(f"  linha {linha:>2}  {modelo.label[:38]:<38} <- {conta.name[:40]}")
        partes.append(f"            uuid: {conta.id or '(sem id)'}  saldo: {format_brl(conta.balance)}")

    if descoberta.sem_correspondencia:
        partes += ["", f"SEM CORRESPONDENCIA ({len(descoberta.sem_correspondencia)})", "-" * 64]
        for linha in descoberta.sem_correspondencia:
            modelo = mapping.by_row(linha)
            partes.append(f"  linha {linha:>2}  {modelo.label}")
        partes.append("  -> confira o erp_name/account_number destas linhas no mapping.yaml")

    if descoberta.desconhecidas:
        partes += ["", f"CONTAS DO ERP FORA DO PAINEL ({len(descoberta.desconhecidas)})", "-" * 64]
        for conta in descoberta.desconhecidas:
            partes.append(f"  {conta.name[:52]:<52} {format_brl(conta.balance):>16}")
        partes.append("  -> se alguma deveria entrar no painel, me avise")

    return "\n".join(partes)
