# tela_do_dia/controle_aportes.py
# -*- coding: utf-8 -*-
"""Controle de aportes: quanto cada aportador pôs em cada conta desde a
abertura, quanto deveria pela proporção e quem deve quanto para igualar.
Sem tela e sem rede — a aba (`controle_frame.py`) só mostra o que sai daqui.

A conta, numa frase: `aportou` = o já aportado antes da abertura + os
recebimentos de aporte do ERP desde a abertura; o NÍVEL é o maior
`aportou ÷ parte`; `deveria` = nível × parte; `para igualar` = deveria −
aportou. Com dois aportadores meio a meio, "A já pôs 40 mil a mais que B"
vira "B deve R$ 40.000,00 para igualar" — a conta que o dono faz de cabeça.

Quem é o aportador de um recebimento: o Cliente dele no ERP (`customerName`),
pelo nome COMPLETO (`util.norm_espaco`: sem acento, caixa e espaço dobrado),
contra os aportadores DAQUELA conta. Nunca por primeiro nome nem por pedaço:
dois aportadores com o mesmo primeiro nome são pessoas diferentes. Cliente
vazio: o caminho pelo id do Cliente no cadastro de contatos está DORMENTE (o
LISTAR medido em 22/10/2026 não traz customerId); ver `identificar_aportador`.
O que não casa vai para `sem_dono`, para o dono apontar — nunca some.
"""
from __future__ import annotations

import datetime
import re
from dataclasses import dataclass, field, replace
from decimal import (ROUND_CEILING, ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation,
                     localcontext)

import util
from aportes import rateio_subconta
from aportes.regras import (como_dinheiro, numero_da_conta, percentuais_dos_pesos, peso_de,
                            problema_dos_pesos)

from .valores import brl, ler_valor_editado

ZERO = Decimal("0.00")
CENTAVO = Decimal("0.01")
#: O horário de Brasília (UTC-3, sem horário de verão desde 2019). Data do ERP
#: que vem com fuso ("…T03:00:00Z") é convertida para ele ANTES de comparar
#: com a abertura e com hoje — ver `data_do_erp`. Fixo, e não o fuso da
#: máquina: o mesmo recebimento não pode cair em dias diferentes conforme o
#: relógio de quem abre o app.
BRASILIA = datetime.timezone(datetime.timedelta(hours=-3), "Brasilia")
#: O rótulo da data de abertura no formulário: o dia da abertura CONTA.
ROTULO_ABERTURA = "Abertura — primeiro dia contado (inclusive), DD/MM/AAAA"


@dataclass(frozen=True)
class Aportador:
    nome_erp: str                 # o Cliente no ERP, nome completo
    peso: Decimal                 # parte (peso: 1 e 1 = meio a meio)
    abertura: Decimal = ZERO      # já aportado ANTES da abertura (>= 0)
    id: int | None = None


@dataclass(frozen=True)
class ContaControlada:
    conta_erp: str                # nome da conta no ERP, letra por letra
    abertura: datetime.date       # primeiro dia contado (inclusive)
    aportadores: tuple = ()
    id: int | None = None
    ativa: bool = True


@dataclass(frozen=True)
class Recebimento:
    id: str
    data: datetime.date
    valor: Decimal
    cliente: str
    natureza: str = ""
    descricao: str = ""
    centro: str = ""
    cliente_id: str = ""          # o id do Cliente no ERP, quando o item traz
    cliente_cadastro: str = ""    # o nome do Cliente pelo cadastro de contatos (pelo id)
    #: O valor ORIGINAL da parcela (`plannedValue`); None quando não veio ou
    #: não se lê. Só serve ao alerta de recebimento parcial — nunca à soma.
    valor_original: Decimal | None = None


#: Chave que `controle_erp` acrescenta ao item cru quando o Cliente veio vazio
#: e o id dele foi achado no cadastro de contatos. Não é campo do ERP: o
#: prefixo "_" deixa claro que é anotação nossa, e o `customerName` cru nunca é
#: reescrito.
CHAVE_CLIENTE_DO_CADASTRO = "_clienteDoCadastro"


def nome_do_cliente(item) -> str:
    """O Cliente do item cru: `customerName`, ou `customer.name` quando o ERP
    o manda aninhado. "" quando vazio."""
    item = item if isinstance(item, dict) else {}
    nome = item.get("customerName")
    if isinstance(nome, str) and nome.strip():
        return nome.strip()
    cliente = item.get("customer")
    if isinstance(cliente, dict) and isinstance(cliente.get("name"), str):
        return cliente["name"].strip()
    return ""


def id_do_cliente(item) -> str:
    """O id do Cliente do item cru: `customerId` ou `customer.id`. "" quando
    não vem (NÃO medido em produção que `receipt-installments` o traga)."""
    item = item if isinstance(item, dict) else {}
    for v in (item.get("customerId"),
              (item.get("customer") or {}).get("id") if isinstance(item.get("customer"), dict)
              else None):
        if isinstance(v, (str, int)) and not isinstance(v, bool) and str(v).strip():
            return str(v).strip()
    return ""


@dataclass(frozen=True)
class Apontamento:
    recebimento_id: str
    aportador_id: int | None      # None = "não é aporte desta conta"
    valor: Decimal                # o valor do recebimento quando foi apontado
    motivo: str
    id: int | None = None


def _dinheiro_do_erp(valor) -> Decimal:
    if valor is None or isinstance(valor, bool) or str(valor).strip() == "":
        raise ValueError("sem valor recebido")
    try:
        d = Decimal(str(valor))
    except InvalidOperation:
        raise ValueError(f"valor ilegível: {valor!r}") from None
    if not d.is_finite():
        raise ValueError(f"valor ilegível: {valor!r}")
    return d.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def data_do_erp(texto) -> datetime.date:
    """A data de recebimento do ERP. Só a data ("2026-10-22") ou data e hora
    SEM fuso ("2026-10-22T00:00:00"): a data como veio. Com fuso ("…Z",
    "…+00:00", "…-03:00"): convertida para o horário de Brasília (`BRASILIA`)
    antes de virar data — "2026-10-22T02:00:00Z" é 23h do dia 21 aqui.
    Ilegível levanta `ValueError`."""
    t = str(texto or "").strip()
    if len(t) == 10:
        return datetime.date.fromisoformat(t)
    if t[-1:] in ("Z", "z"):
        t = t[:-1] + "+00:00"
    momento = datetime.datetime.fromisoformat(t)
    if momento.tzinfo is not None:
        momento = momento.astimezone(BRASILIA)
    return momento.date()


def _valor_original(item) -> Decimal | None:
    try:
        return _dinheiro_do_erp(item.get("plannedValue"))
    except ValueError:
        return None


def recebimento_do_erp(item: dict, natureza: str = "") -> Recebimento:
    """Um item de `receipt-installments`, com os campos que a aba Contratos já
    lê em produção (`contratos/regras.py:183-212`). Levanta `ValueError` sem
    id, data ou valor: recebimento que não se lê não pode virar zero."""
    item = item if isinstance(item, dict) else {}
    ident = str(item.get("id") or "").strip()
    if not ident:
        raise ValueError("recebimento sem id")
    try:
        data = data_do_erp(item.get("dateOfReceipt"))
    except ValueError:
        raise ValueError(f"recebimento {ident} sem data de recebimento") from None
    try:
        valor = _dinheiro_do_erp(item.get("sumOfReceivedValues"))
    except ValueError as e:
        raise ValueError(f"recebimento {ident}: {e}") from None
    cadastro = item.get(CHAVE_CLIENTE_DO_CADASTRO)
    return Recebimento(id=ident, data=data, valor=valor,
                       cliente=nome_do_cliente(item),
                       natureza=natureza,
                       descricao=str(item.get("description") or "").strip(),
                       centro=str(item.get("workName") or "").strip(),
                       cliente_id=id_do_cliente(item),
                       cliente_cadastro=cadastro.strip() if isinstance(cadastro, str) else "",
                       valor_original=_valor_original(item))


def problemas_da_conta(conta: ContaControlada, hoje: datetime.date, outras=()) -> list[str]:
    """[] quando a conta pode ser gravada e apurada; senão, os motivos."""
    erros: list[str] = []
    nome = (conta.conta_erp or "").strip()
    if not nome:
        erros.append("Falta o nome da conta, como está no Mais Controle.")
    elif any(util.norm_espaco(o.conta_erp) == util.norm_espaco(nome) and o.id != conta.id
             for o in outras):
        erros.append(f'A conta "{nome}" já está no controle.')
    if not isinstance(conta.abertura, datetime.date):
        erros.append("Falta a data de abertura.")
    elif conta.abertura > hoje:
        erros.append("A abertura não pode ser depois de hoje.")
    nomes = [(a.nome_erp or "").strip() for a in conta.aportadores]
    if not nomes or not all(nomes):
        erros.append("Falta aportador: o nome COMPLETO, como está no Contato do Mais Controle.")
    elif len({util.norm_espaco(n) for n in nomes}) != len(nomes):
        erros.append("Aportador repetido.")
    elif any(a.peso is None for a in conta.aportadores):
        erros.append("Proporção: falta a parte de alguém.")
    else:
        problema = problema_dos_pesos(nomes, {n: a.peso for n, a in zip(nomes, conta.aportadores)})
        if problema:
            erros.append(f"Proporção: {problema}.")
    for a in conta.aportadores:
        ab = a.abertura
        if (not isinstance(ab, Decimal) or not ab.is_finite() or ab < 0
                or ab != ab.quantize(CENTAVO)):
            erros.append(f"Já aportado antes da abertura de {a.nome_erp}: valor inválido.")
    return erros


def _corta(valor: Decimal) -> Decimal:
    """Para baixo, no centavo (os valores aqui nunca são negativos)."""
    return valor.quantize(CENTAVO, rounding=ROUND_DOWN)


def _sobe(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO, rounding=ROUND_CEILING)


def _lider(valores_e_pesos) -> int:
    """O índice de quem tem o maior `valor ÷ peso`, comparado por produto
    cruzado (`v_i × p_l > v_l × p_i`): sem divisão, sem dízima, sem empate
    falso. No empate fica o primeiro."""
    lider = 0
    for i, (v, p) in enumerate(valores_e_pesos):
        v_l, p_l = valores_e_pesos[lider]
        if v * p_l > v_l * p:
            lider = i
    return lider


def _peso_valido(aportador) -> Decimal:
    peso = aportador.peso
    if peso is None or isinstance(peso, bool):
        raise ValueError(f"Proporção: falta a parte de {aportador.nome_erp}.")
    try:
        peso = Decimal(peso)
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Proporção: a parte de {aportador.nome_erp} não é número.") from None
    if not peso.is_finite() or peso <= 0:
        raise ValueError(f"Proporção: a parte de {aportador.nome_erp} tem de ser maior que zero.")
    return peso


def aberturas_para_divida(aportadores, devedor: str, valor) -> dict:
    """"FULANO deve R$ V para igualar" -> o já aportado antes da abertura de
    cada um, de modo que a `apurar` mostre o devedor devendo EXATAMENTE V.

    Cada outro aportador fica com V × parte dele ÷ parte do devedor, ARREDONDADO
    PARA CIMA no centavo. Como a `apurar` corta a dívida no centavo (ver
    `_linhas`), com partes que não dividem exato a dívida sairia um centavo ou
    mais acima de V; a diferença vai para o próprio devedor, como "já aportado"
    (sempre >= 0 e menor que alguns centavos). Com 3 ou mais aportadores e
    partes desiguais, o arredondamento para cima pode deixar um outro abaixo do
    nível do líder (3:1:100 devendo 1,00 deixaria o terceiro "devendo" 0,66):
    por isso cada outro é levado até o nível do líder cortado no centavo
    (`aportou do líder × parte dele ÷ parte do líder`). Resultado: só o
    devedor deve, e deve exatamente V.

    Peso ausente, zero, negativo ou que não é número levanta `ValueError` —
    nunca `DivisionByZero`."""
    valor = como_dinheiro(valor)
    if valor < 0:
        raise ValueError("A dívida não pode ser negativa.")
    aportadores = tuple(aportadores)
    alvo = util.norm_espaco(devedor)
    achados = [a for a in aportadores if util.norm_espaco(a.nome_erp) == alvo]
    if len(achados) != 1:
        raise ValueError("Escolha o devedor entre os aportadores, pelo nome completo.")
    quem = achados[0]
    pesos = [_peso_valido(a) for a in aportadores]
    outros = [(a, p) for a, p in zip(aportadores, pesos) if a is not quem]
    if not outros:
        if valor > 0:
            raise ValueError("Com um aportador só, ninguém deve para igualar.")
        return {quem.nome_erp: ZERO}
    p_dev = pesos[aportadores.index(quem)]
    with localcontext() as ctx:
        ctx.prec = 60
        saida = {a.nome_erp: _sobe(valor * p / p_dev) for a, p in outros}
        l = _lider([(saida[a.nome_erp], p) for a, p in outros])
        lider, p_lider = outros[l]
        for a, p in outros:      # ninguém além do devedor fica abaixo do líder
            saida[a.nome_erp] = max(saida[a.nome_erp],
                                    _corta(saida[lider.nome_erp] * p / p_lider))
        deveria_dev = _corta(saida[lider.nome_erp] * p_dev / p_lider)
    saida[quem.nome_erp] = deveria_dev - valor
    return {a.nome_erp: saida[a.nome_erp] for a in aportadores}


def aportador_do_apontamento(conta: ContaControlada, aportador_id):
    """O aportador a quem um recebimento desta conta vai ser apontado — só
    aportador DESTA conta (a FK do banco é composta: conta + aportador).
    `None` = "não é aporte desta conta". Outro id levanta `ValueError`."""
    if aportador_id is None:
        return None
    if isinstance(aportador_id, bool):
        raise ValueError("Aportador inválido.")
    try:
        ident = int(aportador_id)
    except (TypeError, ValueError):
        raise ValueError("Aportador inválido.") from None
    for a in conta.aportadores:
        if a.id is not None and a.id == ident:
            return a
    raise ValueError("Esse aportador não é desta conta: escolha um dos aportadores dela.")


@dataclass(frozen=True)
class LinhaAportador:
    nome: str
    parte: Decimal        # % com 2 casas, só para mostrar
    abertura: Decimal
    do_erp: Decimal
    aportou: Decimal      # abertura + do_erp
    deveria: Decimal      # nível × parte, CORTADO no centavo (ver `_linhas`)
    diferenca: Decimal    # deveria − aportou (>= 0): quanto falta para igualar


@dataclass(frozen=True)
class SemDono:
    recebimento: Recebimento
    motivo: str


@dataclass
class Apuracao:
    conta: ContaControlada
    linhas: list = field(default_factory=list)
    sem_dono: list = field(default_factory=list)
    #: [(Recebimento, Apontamento, nome do aportador ou "" = não é aporte)]
    apontados: list = field(default_factory=list)
    alertas: list = field(default_factory=list)
    erro: str = ""

    @property
    def total(self) -> Decimal:
        return sum((l.aportou for l in self.linhas), ZERO)


def com_aberturas(conta: ContaControlada, aberturas: dict) -> ContaControlada:
    por_chave = {util.norm_espaco(n): como_dinheiro(v) for n, v in aberturas.items()}
    return replace(conta, aportadores=tuple(
        replace(a, abertura=por_chave.get(util.norm_espaco(a.nome_erp), a.abertura))
        for a in conta.aportadores))


def _linhas(conta: ContaControlada, do_erp: dict) -> list:
    """A conta da proporção. Só roda com a conta sem problema (pesos > 0).

    O LÍDER é quem tem o maior `aportou ÷ parte` (por produto cruzado, sem
    divisão). `deveria` de cada um = aportou do líder × parte dele ÷ parte do
    líder — uma divisão só, em 60 dígitos.

    O CENTAVO QUE SOBRA: quando a parte não divide exato (3:7, 1:3…), a dívida
    de cada devedor é o exato CORTADO no centavo (arredonda para baixo, a
    fração fica a favor do devedor). Não há centavo redistribuído entre
    aportadores: a soma das diferenças da conta é a soma, devedor a devedor,
    do exato cortado — nunca acima do exato, e abaixo dele menos de R$ 0,01
    por devedor. Cortar (e não arredondar meio para cima) é o que impede o
    vaivém: pago exatamente o que a tela mandou, o devedor fica no nível ou
    uma fração de centavo abaixo dele, e o líder continua líder e em dia. Com
    meio para cima, 7:3 com 100,00 × 0 mandaria pagar 42,86, e o líder
    passaria a "dever R$ 0,01"."""
    nomes = [a.nome_erp for a in conta.aportadores]
    pesos = {a.nome_erp: Decimal(a.peso) for a in conta.aportadores}
    aportou = {a.nome_erp: como_dinheiro(a.abertura) + do_erp[a.nome_erp]
               for a in conta.aportadores}
    partes = percentuais_dos_pesos(nomes, pesos)
    saida = []
    with localcontext() as ctx:
        ctx.prec = 60
        lider = nomes[_lider([(aportou[n], pesos[n]) for n in nomes])]
        for a, parte in zip(conta.aportadores, partes):
            n = a.nome_erp
            # `max`: ninguém "deve" para si mesmo (o líder e quem empata com ele).
            deveria = max(aportou[n], _corta(aportou[lider] * pesos[n] / pesos[lider]))
            saida.append(LinhaAportador(nome=n, parte=parte, abertura=como_dinheiro(a.abertura),
                                        do_erp=do_erp[n], aportou=aportou[n], deveria=deveria,
                                        diferenca=deveria - aportou[n]))
    return saida


def identificar_aportador(conta: ContaControlada, recebimento: Recebimento) -> tuple:
    """(Aportador, "") ou (None, motivo) para um recebimento SEM apontamento.

    É o ÚNICO ponto que decide de quem é um recebimento pelos campos do ERP.
    Só entram campos que dizem QUEM é a pessoa, e sempre pelo nome COMPLETO
    normalizado, contra os aportadores desta conta:

    1. o Cliente do recebimento (`customerName`, ou `customer.name`);
    2. quando o Cliente vem vazio, o nome que o cadastro de contatos dá ao id do
       Cliente (`cliente_cadastro`, resolvido em `controle_erp`). Caminho
       DORMENTE: o LISTAR medido em 22/10/2026 não traz customerId, então
       hoje Cliente vazio vai direto para sem dono.

    Os dois presentes e diferentes: sem dono (o ERP se contradiz). Nunca se
    chuta: nem quando a conta tem um aportador só, nem pela descrição, nem
    pelo centro de custo, nem por primeiro nome — mesmo que contenham o nome
    completo. Sem nenhum dos dois, vai para sem dono, e o dono aponta."""
    cliente = (recebimento.cliente or "").strip()
    cadastro = (recebimento.cliente_cadastro or "").strip()
    if (util.norm_espaco(cliente) and util.norm_espaco(cadastro)
            and util.norm_espaco(cliente) != util.norm_espaco(cadastro)):
        return None, (f'o Cliente "{cliente}" diverge do cadastro do Cliente no Mais Controle '
                      f'("{cadastro}") — confira e aponte o aportador')
    nome, pelo_cadastro = (cliente, False) if util.norm_espaco(cliente) else (cadastro, True)
    if not util.norm_espaco(nome):
        return None, ("recebimento sem Cliente no Mais Controle — não identificado; "
                      "preencha o Cliente no ERP ou aponte o aportador")
    alvo = util.norm_espaco(nome)
    achados = [a for a in conta.aportadores if util.norm_espaco(a.nome_erp) == alvo]
    if len(achados) != 1:
        if pelo_cadastro:
            return None, (f'o Cliente veio vazio e o cadastro do id dele diz "{nome}", que '
                          "não é aportador desta conta")
        return None, f'o Cliente "{nome}" não é aportador desta conta'
    return achados[0], ""


def _quem_no_texto(conta: ContaControlada, r: Recebimento) -> str:
    dono, _motivo = identificar_aportador(conta, r)
    if dono is not None:
        return f" ({dono.nome_erp})"
    return f' (Cliente "{r.cliente}")' if (r.cliente or "").strip() else " (sem Cliente)"


def conflito_do_apontamento(conta: ContaControlada, r: Recebimento, aportador_id) -> str:
    """"" quando apontar `r` para `aportador_id` (None = "não é aporte") não
    contradiz o Cliente do ERP; senão, o recado. Contradiz quando o Cliente
    identifica um aportador desta conta (`identificar_aportador`) e a escolha
    é outro aportador ou "não é aporte". Vale ao APONTAR (`controle_nuvem.apontar`
    recusa) e ao APURAR (o apontamento volta para sem dono)."""
    pelo_cliente, _motivo = identificar_aportador(conta, r)
    if pelo_cliente is None:
        return ""
    if aportador_id is not None and not isinstance(aportador_id, bool):
        try:
            if pelo_cliente.id is not None and int(aportador_id) == pelo_cliente.id:
                return ""
        except (TypeError, ValueError):
            pass
    return (f"o Cliente no ERP aponta para {pelo_cliente.nome_erp} — corrija o Cliente no "
            "ERP ou aponte para ele")


#: Quantas vezes (de 50 ms) a releitura depois de gravar espera a leitura em
#: curso terminar antes de tentar assim mesmo (~2 s).
ESPERAS_PARA_RELER = 40


def reler_ou_esperar(terminou: bool, tentativas: int) -> str:
    """"reler" quando a leitura anterior já terminou (ou a espera estourou o
    limite — aí o `atualizar` diz se o navegador está ocupado); senão
    "esperar" mais um pouco."""
    return "reler" if terminou or tentativas >= ESPERAS_PARA_RELER else "esperar"


def _leitura_que_nao_se_soma(conta: ContaControlada, r: Recebimento, hoje) -> str:
    """"" quando o recebimento pode entrar na conta; senão, o motivo pelo qual
    a CONTA INTEIRA não se calcula. Fora do período pedido: o ERP não
    respeitou o filtro de data — descartar em silêncio esconderia isso.
    Zero ou negativo (estorno): somar reduziria o aportado no escuro, e
    deixar "sem dono" o esconderia para sempre (não se aponta valor assim)."""
    if r.data < conta.abertura or r.data > hoje:
        return (f"o ERP devolveu recebimento fora do período pedido ({brl(r.valor)} em "
                f"{r.data:%d/%m/%Y}{_quem_no_texto(conta, r)}; o período é "
                f"{conta.abertura:%d/%m/%Y} a {hoje:%d/%m/%Y}) — leitura não confiável, "
                "confira no ERP")
    if r.valor < 0:
        return (f"estorno/recebimento negativo de {brl(r.valor)} em {r.data:%d/%m}"
                f"{_quem_no_texto(conta, r)} — a conta não pode ser calculada; confira no ERP")
    if r.valor == 0:
        return (f"recebimento zerado ({brl(r.valor)}) em {r.data:%d/%m}"
                f"{_quem_no_texto(conta, r)} — a conta não pode ser calculada; confira no ERP")
    return ""


def apurar(conta: ContaControlada, recebimentos, apontamentos, hoje: datetime.date) -> Apuracao:
    """A conta de UMA conta. Conta com cadastro ruim ou leitura duvidosa sai
    com `erro` e SEM linhas — nunca números pela metade. Leitura duvidosa:
    parcela repetida, recebimento fora do período pedido ou de valor zero ou
    negativo (`_leitura_que_nao_se_soma`)."""
    ap = Apuracao(conta=conta)
    problemas = problemas_da_conta(conta, hoje)
    if problemas:
        ap.erro = " ".join(problemas)
        return ap
    # Só aportador DESTA conta: apontamento para id de outra conta (ou de quem
    # saiu) não acha dono aqui e volta para sem dono.
    por_id = {a.id: a for a in conta.aportadores if a.id is not None}
    do_erp = {a.nome_erp: ZERO for a in conta.aportadores}
    apontado = {p.recebimento_id: p for p in apontamentos}
    ordenados = sorted(recebimentos, key=lambda x: (x.data, x.id))
    vistos: set = set()
    for r in ordenados:
        if r.id in vistos:
            ap.erro = (f"o recebimento {r.id} veio duas vezes do Mais Controle — leitura "
                       "não confiável, nenhum número desta conta foi mostrado")
            return ap
        vistos.add(r.id)
    falhas = [f for f in (_leitura_que_nao_se_soma(conta, r, hoje) for r in ordenados) if f]
    if falhas:
        ap.erro = " · ".join(falhas) + " — nenhum número desta conta foi mostrado"
        return ap
    for r in ordenados:
        if r.valor_original is not None and r.valor_original != r.valor:
            ap.alertas.append(f"recebimento parcial — confira: {brl(r.valor)} de "
                              f"{brl(r.valor_original)} em {r.data:%d/%m/%Y}"
                              f"{_quem_no_texto(conta, r)} (a conta soma o recebido)")
        p = apontado.get(r.id)
        if p is not None:
            if como_dinheiro(p.valor) != r.valor:
                ap.sem_dono.append(SemDono(r, f"apontado com {brl(p.valor)}; agora é "
                                              f"{brl(r.valor)} no Mais Controle — aponte de novo"))
                continue
            # O Cliente do ERP manda sobre o apontamento quando identifica
            # OUTRO aportador (ou um aportador, num "não é aporte"): o banco
            # não guarda o Cliente da hora do apontamento — compara-se com a
            # identificação pelo nome feita agora (`conflito_do_apontamento`).
            conflito = conflito_do_apontamento(conta, r, p.aportador_id)
            if conflito:
                ap.sem_dono.append(SemDono(r, conflito))
                continue
            if p.aportador_id is None:
                ap.apontados.append((r, p, ""))
                continue
            dono = por_id.get(p.aportador_id)
            if dono is None:
                ap.sem_dono.append(SemDono(r, "apontado para quem não é mais aportador "
                                              "desta conta — aponte de novo"))
                continue
            do_erp[dono.nome_erp] += r.valor
            ap.apontados.append((r, p, dono.nome_erp))
            continue
        dono, motivo = identificar_aportador(conta, r)
        if dono is None:
            ap.sem_dono.append(SemDono(r, motivo))
            continue
        do_erp[dono.nome_erp] += r.valor
    for p in apontamentos:
        if p.recebimento_id not in vistos:
            ap.alertas.append(f"apontamento de um recebimento de {brl(p.valor)} que não veio "
                              "do Mais Controle — foi apagado ou mudou de conta? confira")
    ap.linhas = _linhas(conta, do_erp)
    return ap


def situacao_do_aportador(linha: LinhaAportador) -> str:
    return "em dia" if linha.diferenca <= 0 else f"deve {brl(linha.diferenca)} para igualar"


def situacao_da_conta(ap: Apuracao) -> str:
    if ap.erro:
        return f"erro: {ap.erro}"
    partes = [f"desde {ap.conta.abertura:%d/%m/%Y}"]
    if ap.sem_dono:
        partes.append(f"{len(ap.sem_dono)} sem dono")
    if ap.alertas:
        partes.append(f"{len(ap.alertas)} alerta(s) — veja o Registro")
    return " · ".join(partes)


def status_da_leitura(apuracoes) -> str:
    """A frase da barra depois de uma leitura: "atualizado" só quando alguma
    conta saiu com números."""
    if not apuracoes:
        return "Nenhuma conta no controle."
    com_erro = sum(1 for ap in apuracoes if ap.erro)
    if com_erro == len(apuracoes):
        return "Li, mas nenhuma conta pôde ser calculada — veja os erros na tabela."
    if com_erro:
        return f"Controle de aportes atualizado — {com_erro} conta(s) com erro, veja a tabela."
    return "Controle de aportes atualizado."


def resumo(ap: Apuracao, pode_apontar: bool = True) -> list:
    """`pode_apontar`: quem está vendo pode apontar (admin). Sem isso, o
    texto não manda ninguém "apontar"."""
    nome = ap.conta.conta_erp
    if ap.erro:
        return [f"{nome}: {ap.erro}"]
    devem = [l for l in ap.linhas if l.diferenca > 0]
    saida = ([f"{nome}: {l.nome} deve {brl(l.diferenca)} para igualar." for l in devem]
             or [f"{nome}: todos em dia pela proporção."])
    if ap.sem_dono:
        soma = sum((s.recebimento.valor for s in ap.sem_dono), ZERO)
        saida.append(f"{nome}: {len(ap.sem_dono)} recebimento(s) sem dono ({brl(soma)}) "
                     + ("fora da conta até você apontar." if pode_apontar else
                        "fora da conta — o administrador aponta de quem são."))
    return saida


# ---- a orquestração pura da leitura (Tarefa 4): quem se lê e como se apura
@dataclass(frozen=True)
class Par:
    rotulo: str            # conta_erp como está no controle (chave dos resultados)
    conta_id: str          # `ErpAccount.id`
    nome_no_erp: str       # `ErpAccount.name`
    inicio: datetime.date


def pares_para_ler(contas, contas_erp) -> tuple:
    """([Par], {rótulo: motivo}) — a conta do controle casa com UMA conta
    ativa do ERP pelo nome inteiro (`util.norm_espaco`)."""
    pares, erros = [], {}
    for c in contas:
        alvo = util.norm_espaco(c.conta_erp)
        achadas = [e for e in contas_erp if util.norm_espaco(e.name) == alvo]
        if len(achadas) == 1:
            pares.append(Par(c.conta_erp, achadas[0].id, achadas[0].name, c.abertura))
        elif not achadas:
            erros[c.conta_erp] = ("não está entre as contas ativas do Mais Controle (o nome "
                                  "tem de ser o de lá, letra por letra)")
        else:
            erros[c.conta_erp] = ("há duas contas ativas no Mais Controle com esse nome — "
                                  "não dá para saber qual")
    return pares, erros


def conta_de_contraprova(contas_erp, pares):
    """Uma conta ativa FORA do controle, para provar que o filtro de conta vale."""
    usadas = {p.conta_id for p in pares}
    livres = sorted((e for e in contas_erp if e.id and e.id not in usadas),
                    key=lambda e: util.norm_espaco(e.name))
    if not livres or not pares:
        return None
    return Par("", livres[0].id, livres[0].name, min(p.inicio for p in pares))


def recebimentos_de(itens_por_natureza: dict) -> list:
    return [recebimento_do_erp(item, natureza)
            for natureza, itens in itens_por_natureza.items() for item in itens]


def apurar_tudo(contas, erros: dict, crus: dict, apontamentos: dict, hoje) -> list:
    """Uma `Apuracao` por conta; o erro de uma não apaga as outras."""
    saida = []
    for c in contas:
        if c.conta_erp in erros:
            saida.append(Apuracao(conta=c, erro=erros[c.conta_erp]))
            continue
        if c.conta_erp not in crus:      # não lida não é "zero aportado"
            saida.append(Apuracao(conta=c, erro="os recebimentos desta conta não foram lidos "
                                                "do Mais Controle — nenhum número foi mostrado"))
            continue
        try:
            recs = recebimentos_de(crus[c.conta_erp] or {})
        except ValueError as e:
            saida.append(Apuracao(conta=c, erro=f"recebimento que não se lê no Mais Controle "
                                                f"({e}) — nenhum número desta conta foi mostrado"))
            continue
        saida.append(apurar(c, recs, apontamentos.get(c.id) or [], hoje))
    return saida


# ---- formulário, sugestão da subconta e nomes conhecidos ---------------------

_PARTE_COM_MILHAR = re.compile(r"\d{1,3}(\.\d{3})+")
NAO_E_APORTE = "Não é aporte desta conta (fica fora da conta)"


def ler_data(texto) -> datetime.date:
    t = str(texto or "").strip()
    for formato in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(t, formato).date()
        except ValueError:
            pass
    raise ValueError(f'Data inválida: "{t}". Use DD/MM/AAAA, ex.: 21/10/2026.')


def ler_abertura(texto) -> Decimal:
    """O já aportado antes da abertura: vazio é zero; negativo é recusado."""
    t = str(texto or "").strip()
    if not t:
        return ZERO
    valor = ler_valor_editado(t)
    if valor < 0:
        raise ValueError("O já aportado antes da abertura não pode ser negativo.")
    return valor


def conta_do_formulario(conta_erp, abertura, linhas, *, id=None, ativa=True) -> ContaControlada:
    """`linhas`: [(nome, parte, já aportado)] como digitadas. Linha toda
    vazia é pulada; partes vazias em TODOS = partes iguais."""
    nome_conta = str(conta_erp or "").strip()
    if not nome_conta:
        raise ValueError("Escolha a conta, com o nome que ela tem no Mais Controle.")
    data = ler_data(abertura)
    preenchidas = []
    for nome, parte, ja in linhas:
        nome, parte, ja = (str(x or "").strip() for x in (nome, parte, ja))
        if not (nome or parte or ja):
            continue
        if not nome:
            raise ValueError("Há uma linha com parte ou valor e sem o nome do aportador.")
        if _PARTE_COM_MILHAR.fullmatch(parte):
            raise ValueError(f'A parte "{parte}" é ambígua: use vírgula para decimais '
                             f'(ex.: 1,5) ou escreva só o número (ex.: 1500).')
        preenchidas.append((nome, rateio_subconta.ler_parte(parte), ler_abertura(ja)))
    if not preenchidas:
        raise ValueError("Falta pelo menos um aportador.")
    partes = [p for _n, p, _a in preenchidas]
    if all(p is None for p in partes):
        partes = ["1"] * len(preenchidas)
    elif any(p is None for p in partes):
        raise ValueError("Preencha a parte de todos os aportadores, ou de nenhum "
                         "(partes iguais).")
    problema = problema_dos_pesos([n for n, _p, _a in preenchidas],
                                  {n: p for (n, _p0, _a), p in zip(preenchidas, partes)})
    if problema:
        raise ValueError(f"Partes dos aportadores: {problema}.")
    return ContaControlada(conta_erp=nome_conta, abertura=data, id=id, ativa=ativa,
                           aportadores=tuple(Aportador(nome_erp=n, peso=Decimal(p), abertura=a)
                                             for (n, _p, a), p in zip(preenchidas, partes)))


def do_rateio_da_subconta(conta_erp: str, subcontas: dict):
    """Os aportadores do rateio da subconta (aba Aportes), quando a conta é
    uma subconta de investidor com rateio; senão None. Só SUGESTÃO."""
    numero = numero_da_conta(conta_erp)
    cfg = (subcontas or {}).get(numero) if numero else None
    if not isinstance(cfg, dict) or not cfg.get("investidores"):
        return None
    nomes = [str(n).strip() for n in cfg["investidores"]]
    pesos = cfg.get("pesos") or {}
    try:   # o cache pode trazer "abc", NaN, zero: nada disso derruba a tela
        if problema_dos_pesos(nomes, pesos):
            return None            # parcial/ inválido: sem sugestão, nunca chute
        valores = [peso_de(pesos, n) for n in nomes]
    except (ArithmeticError, ValueError):
        return None
    if all(v is None for v in valores):
        valores = [Decimal(1)] * len(nomes)       # nenhum tem parte: iguais
    return tuple(Aportador(nome_erp=n, peso=v) for n, v in zip(nomes, valores))


def _proporcao(aportadores) -> frozenset:
    soma = sum((Decimal(a.peso) for a in aportadores), Decimal(0))
    return frozenset((util.norm_espaco(a.nome_erp),
                      (Decimal(a.peso) / soma).quantize(Decimal("0.000001")))
                     for a in aportadores)


def divergencia_do_rateio(conta: ContaControlada, subcontas: dict) -> str:
    vindos = do_rateio_da_subconta(conta.conta_erp, subcontas)
    if not vindos or not conta.aportadores or any(a.peso is None for a in conta.aportadores):
        return ""
    if _proporcao(vindos) == _proporcao(conta.aportadores):
        return ""
    return (f"a proporção do controle não é a do rateio da subconta "
            f"{numero_da_conta(conta.conta_erp)} (aba Aportes) — confira qual vale")


def nomes_conhecidos(entidades: dict, subcontas: dict, recebimentos=()) -> list:
    """Sugestões para o nome do aportador: o nome oficial da Pagou/Recebeu
    (é o Cliente que a aba Aportes lança), os investidores das subcontas e os
    Clientes que vieram do ERP. Sem repetir, sem vazio. Nomes diferentes
    (mesmo primeiro nome) ficam todos: a comparação é pelo nome completo."""
    nomes = [str((d or {}).get("nome_oficial") or "") for d in (entidades or {}).values()]
    for cfg in (subcontas or {}).values():
        if isinstance(cfg, dict):
            nomes += [str(n) for n in cfg.get("investidores") or []]
    for r in recebimentos:
        nomes += [r.cliente, r.cliente_cadastro]
    vistos, saida = set(), []
    for n in sorted((n.strip() for n in nomes if n and n.strip()), key=util.norm_espaco):
        k = util.norm_espaco(n)
        if k not in vistos:
            vistos.add(k)
            saida.append(n)
    return saida


def opcoes_de_apontamento(conta: ContaControlada) -> list:
    return ([(a.nome_erp, a.id) for a in conta.aportadores if a.id is not None]
            + [(NAO_E_APORTE, None)])


def descrever_conta(conta: ContaControlada) -> str:
    nomes = [a.nome_erp for a in conta.aportadores]
    pcts = percentuais_dos_pesos(nomes, {a.nome_erp: a.peso for a in conta.aportadores})
    linhas = [f"Conta: {conta.conta_erp}", f"Abertura: {conta.abertura:%d/%m/%Y}"]
    linhas += [f"• {a.nome_erp} — parte {str(p).replace('.', ',')}% — já aportado antes "
               f"da abertura: {brl(a.abertura)}" for a, p in zip(conta.aportadores, pcts)]
    return "\n".join(linhas)


# ---- o que a tela mostra e manda (Tarefa 7): a aba só pendura isto em widgets ----

def texto_da_parte(parte) -> str:
    return f"{str(parte).replace('.', ',')}%"


def texto_de_dinheiro(valor) -> str:
    """O valor como se digita no formulário ("40.000,00"): `ler_abertura` o lê igual."""
    return brl(valor).replace("R$", "").strip()


def valores_da_conta(ap: Apuracao) -> tuple:
    """A linha-mãe da tabela "Por conta". Conta com erro: NENHUM número."""
    return ("", "—" if ap.erro else brl(ap.total), "", "", situacao_da_conta(ap))


def valores_do_aportador(linha: LinhaAportador) -> tuple:
    return (texto_da_parte(linha.parte), brl(linha.aportou), brl(linha.deveria),
            brl(linha.diferenca) if linha.diferenca > 0 else "—",
            situacao_do_aportador(linha))


def vistos_do_formulario(conta):
    """Os aportadores que o formulário CARREGOU — id, nome, parte e já
    aportado (o `vistos` de `controle_nuvem.gravar_conta`, que recusa se o
    banco mudou algum deles depois). Conta nova: None. Lista vazia continua
    sendo lista: "carreguei e não havia ninguém" não é "não sei"."""
    if conta is None or conta.id is None:
        return None
    return [a for a in conta.aportadores if a.id is not None]


def linhas_do_rateio(digitadas, vindos) -> tuple:
    """([(nome, parte, já aportado)], [nomes descartados com já aportado]).

    "Trazer do rateio da subconta" troca os nomes e as partes pelos do rateio.
    O já aportado acompanha o NOME, nunca a posição (a ordem do rateio não é
    a do formulário); quem sai e tinha valor digitado é devolvido para a tela
    avisar. O resultado tem pelo menos uma linha por aportador do rateio —
    o formulário cresce em vez de cortar alguém."""
    digitadas = list(digitadas)
    ja = {}
    for nome, _parte, valor in digitadas:
        if util.norm_espaco(nome):
            ja[util.norm_espaco(nome)] = (nome.strip(), str(valor or "").strip())
    ficam = {util.norm_espaco(a.nome_erp) for a in vindos}
    linhas = [(a.nome_erp, format(Decimal(a.peso).normalize(), "f"),
               ja.get(util.norm_espaco(a.nome_erp), ("", ""))[1]) for a in vindos]
    linhas += [("", "", "")] * (len(digitadas) - len(linhas))
    descartados = [nome for k, (nome, valor) in ja.items() if k not in ficam and valor]
    return linhas, descartados


def aberturas_nas_linhas(digitadas, aberturas: dict) -> list:
    """O "já aportado" de `aberturas_para_divida` posto nas linhas pelo nome
    COMPLETO (`util.norm_espaco`); linha de outro nome fica como estava."""
    por_chave = {util.norm_espaco(n): v for n, v in aberturas.items()}
    saida = []
    for nome, parte, valor in digitadas:
        k = util.norm_espaco(nome)
        if k and k in por_chave:
            valor = texto_de_dinheiro(por_chave[k])
        saida.append((nome, parte, valor))
    return saida


def escolha_do_apontamento(opcoes, rotulo: str, motivo: str) -> tuple:
    """(aportador_id ou None, motivo) a partir do que o dono escolheu no
    diálogo; `opcoes` é `opcoes_de_apontamento(conta)`. Fora da lista ou sem
    motivo levanta `ValueError`."""
    rotulos = dict(opcoes)
    if rotulo not in rotulos:
        raise ValueError("Escolha de quem é o recebimento, na lista.")
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Escreva o motivo.")
    return rotulos[rotulo], motivo


def estado_dos_botoes_do_dono(pode_editar: bool, lendo: bool, leu_bem: bool) -> str:
    """"+ Conta", "Editar", "Apontar" e "Desfazer": só para admin, com a
    ÚLTIMA leitura inteira na tela e nenhuma rodando. Sem leitura boa, a
    tela não sabe as contas que já existem (o "já está no controle" de
    `problemas_da_conta`) nem os ids que o formulário carregaria."""
    return "normal" if (pode_editar and leu_bem and not lendo) else "disabled"


def depois_de_gravar(lendo: bool) -> str:
    """Gravou na nuvem: a tela relê JÁ, ou — com uma leitura em curso, que
    pode ter começado antes da gravação — no fim dela. Nunca fica com os
    números de antes da gravação como se fossem os de agora."""
    return "reler_no_fim" if lendo else "reler"


def depois_da_nuvem(erro: bool, lendo: bool) -> tuple:
    """(recado da tela, `depois_de_gravar(lendo)`) quando a thread da nuvem
    termina. COM ERRO também apaga os números e relê: a gravação pode ter
    parado no meio, e a nuvem já não é a que a tela mostrava."""
    recado = ("Não gravou (ou gravou só uma parte) — veja o Registro; relendo a nuvem…"
              if erro else "Gravado — atualizando…")
    return recado, depois_de_gravar(lendo)
