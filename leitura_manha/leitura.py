# -*- coding: utf-8 -*-
"""A leitura das 07:30, sem rede própria: os clientes chegam pela `fabrica`.

Três regras de dinheiro moram aqui:
1. saldo que não se leu é `valor=None` com motivo — NUNCA zero;
2. a falha de uma conta (ou do token de uma empresa) não derruba as outras:
   cada conta é lida no seu próprio `try`, e o motivo vai para a nuvem;
3. a conta só entra no casamento (`lidas`) quando o extrato de ontem veio
   INTEIRO legível; senão vai para `falhas` e nenhum agendado dela é
   pré-marcado ("banco não lido: ...").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from pagamento_api.robo import FUSO_SP
from tela_do_dia.agendados import Agendado
from tela_do_dia.autenticar import autenticar

from . import extrato as ext
from .transporte import ErroLeitura

ERP = "erp"
SEM_NOME = "(sem nome no ERP)"   # `conta` do saldo_lido tem de ter 1 a 200 caracteres


@dataclass(frozen=True)
class SaldoLido:
    conta: str
    fonte: str                  # "sicoob" | "inter" | "erp"
    empresa: str
    valor: Decimal | None       # None = não lido (motivo diz por quê), NUNCA zero
    motivo: str
    hora: datetime

    def __post_init__(self):
        if (self.valor is None) != bool(self.motivo):
            raise ValueError("saldo lido não tem motivo; saldo não lido tem de ter")


@dataclass(frozen=True)
class ExtratoLido:
    conta: str
    fonte: str
    empresa: str
    dia: date
    saidas: int = 0
    entradas: int = 0
    ilegiveis: int = 0
    fora_do_dia: int = 0
    motivo: str = ""            # "" = lido inteiro e usado no casamento
    lido: bool = True           # False = extrato não lido: contagens NÃO valem (NULL, nunca 0)

    def __post_init__(self):
        if not self.lido and not self.motivo:
            raise ValueError("extrato não lido tem de ter motivo")


@dataclass
class LeituraDosBancos:
    saldos: list = field(default_factory=list)
    extratos: list = field(default_factory=list)
    movimentos: list = field(default_factory=list)
    lidas: set = field(default_factory=set)
    falhas: dict = field(default_factory=dict)


@dataclass(frozen=True)
class PreMarca:
    agendado_id: int
    conta: str
    prova: str                  # "" = não provou (a `nota` diz o que o banco disse)
    nota: str


def dias_sp(agora: datetime) -> tuple[date, date]:
    """(hoje, ontem) no fuso de São Paulo. `agora` tem de ter fuso: o relógio
    do servidor pode estar em UTC, e às 00:30 UTC ainda é ontem em SP."""
    if agora.tzinfo is None:
        raise ValueError("agora sem fuso")
    hoje = agora.astimezone(FUSO_SP).date()
    return hoje, hoje - timedelta(days=1)


def motivo_de(e: Exception, banco: str) -> str:
    if isinstance(e, ErroLeitura):
        if e.status is None:
            return f"{banco}: {e.corpo}"[:200]
        if e.status == 200:
            return f"{banco}: {e.corpo[:120]}"
        return f"{banco} respondeu HTTP {e.status}"
    if isinstance(e, ext.ExtratoIlegivel):
        return f"{banco}: {e}"[:200]
    return f"{banco}: erro inesperado ({type(e).__name__})"


class _Cache:
    """Um cliente por empresa (Sicoob) ou por conta (Inter); falha da fábrica
    vira o motivo de cada conta daquela empresa, sem levantar."""

    def __init__(self, fabrica):
        self._f, self._sicoob = fabrica, {}

    def sicoob(self, empresa):
        if empresa.nome not in self._sicoob:
            try:
                self._sicoob[empresa.nome] = self._f.sicoob(empresa)
            except Exception as e:  # noqa: BLE001 — vira motivo, não derruba
                self._sicoob[empresa.nome] = e
        c = self._sicoob[empresa.nome]
        if isinstance(c, Exception):
            raise c
        return c


def _uma_conta(le: LeituraDosBancos, cache: _Cache, fabrica, empresa, conta, ontem, agora):
    banco = "Sicoob" if conta.banco == "sicoob" else "Inter"
    try:
        if conta.banco == "sicoob":
            cliente = cache.sicoob(empresa)
            ler_saldo, ler_extrato = (lambda: cliente.saldo(conta.numero),
                                      lambda: cliente.extrato(conta.numero, ontem))
            do_saldo, do_extrato = ext.saldo_sicoob, ext.movimentos_sicoob
        else:
            cliente = fabrica.inter(empresa, conta)
            ler_saldo, ler_extrato = cliente.saldo, (lambda: cliente.extrato(ontem))
            do_saldo, do_extrato = ext.saldo_inter, ext.movimentos_inter
    except Exception as e:  # noqa: BLE001
        m = motivo_de(e, banco)
        le.saldos.append(SaldoLido(conta.conta_erp, conta.banco, empresa.nome, None, m, agora()))
        le.extratos.append(ExtratoLido(conta.conta_erp, conta.banco, empresa.nome, ontem, motivo=m, lido=False))
        le.falhas[conta.conta_erp] = m
        return
    try:
        valor, m = do_saldo(ler_saldo())
    except Exception as e:  # noqa: BLE001
        valor, m = None, motivo_de(e, banco)
    le.saldos.append(SaldoLido(conta.conta_erp, conta.banco, empresa.nome, valor, m, agora()))
    try:
        x = do_extrato(ler_extrato(), conta.conta_erp, ontem)
    except Exception as e:  # noqa: BLE001
        m = motivo_de(e, banco)
        le.extratos.append(ExtratoLido(conta.conta_erp, conta.banco, empresa.nome, ontem, motivo=m, lido=False))
        le.falhas[conta.conta_erp] = m
        return
    motivo = ""
    if x.ilegiveis:
        motivo = (f"{banco}: {x.ilegiveis} linha(s) ilegível(is) no extrato — "
                  + "; ".join(x.motivos))[:200]
        le.falhas[conta.conta_erp] = motivo
    else:
        le.lidas.add(conta.conta_erp)
        le.movimentos.extend(x.movimentos)
    le.extratos.append(ExtratoLido(conta.conta_erp, conta.banco, empresa.nome, ontem,
                                   len(x.movimentos), x.entradas, x.ilegiveis, x.fora_do_dia,
                                   motivo))


def ler_bancos(config, fabrica, ontem: date, agora: Callable[[], datetime]) -> LeituraDosBancos:
    """Saldo e extrato de ontem de cada conta do arquivo, uma de cada vez."""
    le, cache = LeituraDosBancos(), _Cache(fabrica)
    for empresa in config.empresas:
        for conta in empresa.contas:
            _uma_conta(le, cache, fabrica, empresa, conta, ontem, agora)
    return le


def ler_erp(ler: Callable[[], list], contas_do_arquivo, agora: Callable[[], datetime]) -> list:
    """Saldo de cada conta ATIVA do ERP (`ler` = `ler_saldos` pelo porteiro).
    Falha do ERP: cada conta do arquivo sai "não lido" com o motivo."""
    hora = agora()
    try:
        contas = list(ler())
    except Exception as e:  # noqa: BLE001 — o ERP fora não derruba os bancos
        m = f"ERP não lido: {str(e).strip().splitlines()[0][:150] if str(e).strip() else type(e).__name__}"
        return [SaldoLido(c, ERP, "", None, m, hora) for c in contas_do_arquivo]
    saida, vistas = [], set()
    for c in contas:
        nome = c.name if c.name and c.name.strip() else SEM_NOME
        vistas.add(nome)
        if isinstance(c.balance, Decimal):
            saida.append(SaldoLido(nome, ERP, "", c.balance.quantize(ext.CENTAVO, ROUND_HALF_UP), "", hora))
        else:
            bruto = f" (tela: {c.raw_balance[:30]!r})" if c.raw_balance else ""
            saida.append(SaldoLido(nome, ERP, "", None, "o ERP não mostrou o saldo" + bruto, hora))
    for nome in contas_do_arquivo:
        if nome not in vistas:
            saida.append(SaldoLido(nome, ERP, "", None, "conta não encontrada entre as ativas do ERP",
                                   hora))
    return saida


def pre_marcas(linhas_em_aberto, leitura: LeituraDosBancos, hoje: date,
               log=print) -> list[PreMarca]:
    """O casamento de ontem pela regra pura de 29/10 (`autenticar`): só
    PRÉ-MARCA. Linha da nuvem ilegível fica fora (contada no log)."""
    pendentes, ruins = [], 0
    for linha in linhas_em_aberto:
        try:
            pendentes.append(Agendado.de_linha(linha))
        except (ValueError, KeyError, TypeError):
            ruins += 1
    if ruins:
        log(f"  {ruins} agendado(s) em aberto ilegível(is) na nuvem: ficaram fora")
    conta_de = {a.id: a.conta for a in pendentes}
    res = autenticar(pendentes, leitura.movimentos, lidas=leitura.lidas,
                     falhas=leitura.falhas, hoje=hoje)
    return [PreMarca(i, conta_de[i], a.prova, a.nota) for i, a in sorted(res.items())
            if a.prova or a.nota]
