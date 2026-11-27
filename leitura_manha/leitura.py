# -*- coding: utf-8 -*-
"""A leitura das 07:30, sem rede própria: os clientes chegam pela `fabrica`.

Três regras de dinheiro moram aqui:
1. saldo que não se leu é `valor=None` com motivo — NUNCA zero;
2. a falha de uma conta (ou do token de uma empresa) não derruba as outras:
   cada conta é lida no seu próprio `try`, e o motivo vai para a nuvem;
3. a conta só entra no casamento (`lidas`) quando o extrato da janela
   (`JANELA_DIAS` dias até ontem) veio INTEIRO legível e sem débito devolvido;
   senão vai para `falhas` e nenhum agendado dela é pré-marcado
   ("banco não lido: ...").

O casamento vê a janela inteira (o `autenticar` olha de dia-1 a dia+FOLGA de
cada agendado): pagamento em dobro em dias seguidos fica ambíguo, e o dia que
o servidor perdeu desligado entra na rodada seguinte. O `extrato_lido` resume
só ONTEM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Callable

from pagamento_api.robo import FUSO_SP
from tela_do_dia.agendados import Agendado
from tela_do_dia.autenticar import Autenticacao, autenticar

from . import extrato as ext
from .transporte import ErroLeitura

ERP = "erp"
SEM_NOME = "(sem nome no ERP)"   # `conta` do saldo_lido tem de ter 1 a 200 caracteres
TAMANHO_CONTA = 200
NOME_REPETIDO = "nome repetido no ERP: confira o cadastro"
#: Quantos dias de extrato (até ontem, dias de São Paulo) o casamento vê.
JANELA_DIAS = 7
ANTIGO = f"agendado antigo: fora dos {JANELA_DIAS} dias lidos do extrato"
#: A Conta Corrente v4 não lista pendência de assinatura: a prova diz isso.
AVISO_PENDENCIA = " · pendências de assinatura não conferidas"
TAMANHO_PROVA = 300


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
    inicio: date | None = None                      # 1º dia da janela lida
    sicoob: set = field(default_factory=set)        # contas (do ERP) que são do Sicoob


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


def inicio_da_janela(ontem: date) -> date:
    return ontem - timedelta(days=JANELA_DIAS - 1)


def faixas_do_mes(inicio: date, fim: date) -> list[tuple[date, date]]:
    """[inicio, fim] cortado nas viradas de mês (a API do Sicoob é por mês)."""
    faixas, a = [], inicio
    while a <= fim:
        proximo = (a.replace(day=28) + timedelta(days=4)).replace(day=1)
        b = min(fim, proximo - timedelta(days=1))
        faixas.append((a, b))
        a = b + timedelta(days=1)
    return faixas


def com_aviso_de_pendencia(prova: str) -> str:
    """A prova do Sicoob com o aviso no fim, dentro do corte de 300."""
    if not prova:
        return prova
    return prova[:TAMANHO_PROVA - len(AVISO_PENDENCIA)] + AVISO_PENDENCIA


def _devolvido(movimentos, creditos) -> date | None:
    """O 1º dia em que uma SAÍDA tem ENTRADA de mesmo valor no mesmo dia."""
    voltas = {(c.data, c.valor) for c in creditos}
    dias = sorted(m.data for m in movimentos if (m.data, m.valor) in voltas)
    return dias[0] if dias else None


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
    inicio = inicio_da_janela(ontem)
    if conta.banco == "sicoob":
        le.sicoob.add(conta.conta_erp)
    try:
        if conta.banco == "sicoob":
            cliente = cache.sicoob(empresa)
            ler_saldo = lambda: cliente.saldo(conta.numero)  # noqa: E731
            ler_extrato = lambda a, b: cliente.extrato(conta.numero, a, b)  # noqa: E731
            faixas = faixas_do_mes(inicio, ontem)
            do_saldo, do_extrato = ext.saldo_sicoob, ext.movimentos_sicoob
        else:
            cliente = fabrica.inter(empresa, conta)
            ler_saldo, ler_extrato = cliente.saldo, cliente.extrato
            faixas = [(inicio, ontem)]
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
    movs, creditos, ilegiveis, fora, motivos = [], [], 0, 0, []
    try:   # qualquer pedaço da janela que falhe tira a conta inteira do casamento
        for a, b in faixas:
            x = do_extrato(ler_extrato(a, b), conta.conta_erp, a, b)
            movs.extend(x.movimentos)
            creditos.extend(x.creditos)
            ilegiveis, fora = ilegiveis + x.ilegiveis, fora + x.fora_do_dia
            motivos.extend(x.motivos)
    except Exception as e:  # noqa: BLE001
        m = motivo_de(e, banco)
        le.extratos.append(ExtratoLido(conta.conta_erp, conta.banco, empresa.nome, ontem, motivo=m, lido=False))
        le.falhas[conta.conta_erp] = m
        return
    motivo = ""
    devolvido = _devolvido(movs, creditos)
    if ilegiveis:
        motivo = (f"{banco}: {ilegiveis} linha(s) ilegível(is) no extrato — "
                  + "; ".join(motivos[:ext.MOTIVOS_GUARDADOS]))[:200]
        le.falhas[conta.conta_erp] = motivo
    elif devolvido is not None:   # falha fechada: o par saída+volta engana o casamento
        motivo = f"débito devolvido no extrato de {devolvido:%d/%m}: confira à mão"
        le.falhas[conta.conta_erp] = motivo
    else:
        le.lidas.add(conta.conta_erp)
        le.movimentos.extend(movs)
    # o resumo é só de ONTEM; `fora_do_dia` = o que veio fora da janela pedida
    le.extratos.append(ExtratoLido(conta.conta_erp, conta.banco, empresa.nome, ontem,
                                   sum(m.data == ontem for m in movs),
                                   sum(c.data == ontem for c in creditos), ilegiveis, fora,
                                   motivo))


def ler_bancos(config, fabrica, ontem: date, agora: Callable[[], datetime]) -> LeituraDosBancos:
    """Saldo e extrato da janela (até ontem) de cada conta do arquivo, uma de cada vez."""
    le, cache = LeituraDosBancos(inicio=inicio_da_janela(ontem)), _Cache(fabrica)
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
    nomes = [(c.name if c.name and c.name.strip() else SEM_NOME)[:TAMANHO_CONTA] for c in contas]
    quantos: dict = {}
    for nome in nomes:
        quantos[nome] = quantos.get(nome, 0) + 1
    saida, vistas, usados, vez = [], set(nomes), set(nomes), {}
    for c, nome in zip(contas, nomes):
        if quantos[nome] > 1:
            # Nome repetido: não dá para saber qual saldo é de qual conta. Nenhum
            # vale, e a 2ª em diante ganha " #k" para não colidir na nuvem.
            vez[nome] = vez.get(nome, 0) + 1
            rotulo, k = nome, vez[nome]
            if k > 1:
                while True:
                    sufixo = f" #{k}"
                    rotulo = nome[:TAMANHO_CONTA - len(sufixo)] + sufixo
                    if rotulo not in usados:
                        break
                    k += 1
                usados.add(rotulo)
            saida.append(SaldoLido(rotulo, ERP, "", None, NOME_REPETIDO, hora))
        elif isinstance(c.balance, Decimal):
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
    """O casamento da janela pela regra pura de 29/10 (`autenticar`): só
    PRÉ-MARCA. Linha da nuvem ilegível fica fora (contada no log); agendado de
    conta fora do arquivo só é contado; agendado cuja janela começa antes da
    lida (`dia - 1 < inicio`) disputa o pagamento mas nunca prova."""
    pendentes, ruins = [], 0
    for linha in linhas_em_aberto:
        try:
            pendentes.append(Agendado.de_linha(linha))
        except (ValueError, KeyError, TypeError):
            ruins += 1
    if ruins:
        log(f"  {ruins} agendado(s) em aberto ilegível(is) na nuvem: ficaram fora")
    fora = sum(1 for a in pendentes if a.conta not in leitura.lidas and a.conta not in leitura.falhas)
    if fora:
        log(f"  {fora} agendado(s) de conta fora do arquivo do servidor")
    conta_de = {a.id: a.conta for a in pendentes}
    res = autenticar(pendentes, leitura.movimentos, lidas=leitura.lidas,
                     falhas=leitura.falhas, hoje=hoje)
    if leitura.inicio is not None:
        # O antigo continua no `autenticar` de propósito: ele disputa o pagamento
        # (falha fechada), mas a janela dele não foi lida inteira e ele não prova.
        for a in pendentes:
            if a.conta in leitura.lidas and a.dia - timedelta(days=1) < leitura.inicio:
                res[a.id] = Autenticacao("", ANTIGO)
    saida = []
    for i, a in sorted(res.items()):
        if not (a.prova or a.nota):
            continue
        prova = com_aviso_de_pendencia(a.prova) if conta_de[i] in leitura.sicoob else a.prova
        saida.append(PreMarca(i, conta_de[i], prova, a.nota))
    return saida
