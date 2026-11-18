# -*- coding: utf-8 -*-
"""Dar baixa no ERP pelo arquivo de baixas do HTML das PF (etapa 3 da spec de
12/11/2026 do HTML das PF).

O HTML das PF tem o «já paguei» e o «Baixar lista das baixas», que salva
`baixas_pf_<data>.json`: um item por pagamento marcado, com `lancamento_id`
(a parcela do `payable-installments`), `parte`, `titulo_id`, `fornecedor`,
`valor`, `vencimento`, `conta`, `conta_id` e `data_pagamento`
(`html_pf.py`, o `baixarLista` do HTML). Até 18/11/2026 a baixa era feita
por um script avulso (`baixar.py` + `conferir_baixas.py`) — este módulo é a
regra dele, sem tela, para a aba PF.

AS CONFERÊNCIAS (spec, item 3), por item, ANTES de gravar qualquer coisa:
- o título ainda está em aberto e sem pagamento nenhum no ERP;
- o valor em aberto no ERP é IGUAL ao da lista, ao centavo;
- a conta do arquivo existe no ERP com o MESMO id e o MESMO nome;
- não foi baixado antes por este app (`Registro`), nem aparece duas vezes
  no arquivo;
- não é parte de lançamento dividido (`parte` "k/N"): a baixa de dividido
  nunca é automática (`baixa_erp.MOTIVO_DIVIDIDO`);
- a data do pagamento é uma data, não está no futuro, nem a mais de
  `DIAS_PARA_TRAS` dias, nem antes da abertura da conta.
Quem não passa fica vermelho, com o motivo, e não é baixado.

A BAIXA NÃO SE REPETE. `POST .../paids` CRIA um pagamento; repeti-lo depois
de perder a resposta baixa o mesmo título duas vezes (`baixa_erp.py`,
"Aporte não se repete" no CLAUDE.md). Por isso:
- o título é relido IMEDIATAMENTE antes do POST (outra pessoa pode ter
  baixado entre a conferência e o clique);
- o registro anota "em andamento" ANTES do POST e "ok" depois; um item que
  ficou "em andamento" (app fechou no meio) é vermelho na próxima carga
  até o ERP mostrar a baixa;
- o POST é feito UMA vez. Se ele falhar, o título é relido: com pagamento,
  a baixa entrou; sem pagamento, o item falhou (sem nova tentativa); sem
  conseguir reler, o estado é INCERTO e a rodada PARA ali.

O corpo vem do ERP (`default-paid`), com a conta, a data e o valor do
arquivo por cima — o `default-paid` não traz campo de valor, e sem ele a
baixa sai de R$ 0,00 com HTTP 200 (`baixa_erp.ESCREVER_VALOR`).

DEPOIS do POST o título é relido: só é "ok" com pagamento e nada em aberto.
O HTTP 200 não prova o valor (`baixa_erp.ESCREVER_VALOR`: já houve baixa de
R$ 0,00 com 200). Baixa que entrou e não fecha vira "confira no ERP", com o
registro "ok" mesmo assim — o POST não pode ser repetido.

O registro mora ao lado do exe: entre máquinas, quem segura é só a
releitura do título antes do POST.

`pedir(url, metodo="GET", corpo=None)` é o transporte: na tela, a
`SessaoPelaPagina` do porteiro (Chrome do app), nunca login HTTP.
"""
from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from erp import hosts as _hosts

from . import baixa_erp

LEGADO = _hosts.LEGACY
ARQ_REGISTRO = "baixas_pelo_arquivo.json"
#: Data de pagamento mais antiga aceita: o «já paguei» é do dia, e o ano
#: digitado errado no HTML baixaria no ano errado.
DIAS_PARA_TRAS = 45

M_REPETIDO = "aparece mais de uma vez no arquivo"
M_DIVIDIDO = "lançamento dividido em boletos ({parte}) — baixe no ERP"
M_DATA = "data do pagamento inválida ({data})"
M_FUTURO = "data do pagamento no futuro ({data})"
M_ANTIGA = "data do pagamento antiga demais ({data}) — confira o HTML"
M_ANTES_ABERTURA = "data do pagamento antes da abertura da conta ({abertura})"
M_VALOR = "valor inválido no arquivo ({valor})"
M_SEM_ID = "item sem lançamento"
M_JA_BAIXADO = "já baixado por este app em {quando}"
M_INCERTO = ("ficou sem resposta numa baixa anterior e o ERP não mostra a "
             "baixa — confira no ERP antes de baixar")
M_SEM_CONTA = "a conta «{conta}» não está entre as contas ativas do ERP"
M_NOME_CONTA = "a conta do arquivo («{arquivo}») tem outro nome no ERP («{erp}»)"
M_NAO_LI = "não consegui ler o título no ERP ({erro})"
M_JA_PAGO = "já tem pagamento no ERP"
M_EM_ABERTO = "em aberto no ERP {erp} ≠ arquivo {arquivo}"
M_SEM_EM_ABERTO = "o ERP não disse o valor em aberto"


def _dinheiro(v) -> str:
    texto = f"R$ {v:,.2f}"
    return texto.replace(",", "X").replace(".", ",").replace("X", ".")


@dataclass(frozen=True)
class Item:
    lancamento_id: str
    valor: Decimal | None
    conta: str
    conta_id: str
    data: _dt.date | None
    fornecedor: str = ""
    parte: str = ""
    vencimento: str = ""
    titulo_id: str = ""
    #: o texto como veio, para o motivo quando valor/data não se leem
    valor_cru: str = ""
    data_cru: str = ""


@dataclass
class Conferido:
    item: Item
    motivo: str = ""             # vazio = apto
    em_aberto: Decimal | None = None

    @property
    def apto(self) -> bool:
        return not self.motivo


@dataclass
class Baixado:
    item: Item
    ok: bool
    recado: str = ""
    paid_id: str = ""
    incerto: bool = False


@dataclass
class Rodada:
    resultados: list = field(default_factory=list)   # [Baixado]
    parou: bool = False                               # incerto: parou ali

    @property
    def ok(self) -> int:
        return sum(1 for r in self.resultados if r.ok)


# ------------------------------------------------------------------ arquivo

def _valor(texto) -> Decimal | None:
    try:
        v = Decimal(str(texto).strip())
    except (InvalidOperation, ValueError):
        return None
    if not v.is_finite() or v <= 0:
        return None
    return v.quantize(Decimal("0.01")) if v == v.quantize(Decimal("0.01")) else None


def _data(texto) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat(str(texto).strip()[:10])
    except ValueError:
        return None


def ler_arquivo(texto: str) -> list[Item]:
    """Os itens do `baixas_pf_<data>.json`. `ValueError` com o recado da tela
    quando o arquivo não é o do HTML das PF."""
    try:
        dados = json.loads(texto)
    except ValueError as e:
        raise ValueError("o arquivo não é um JSON válido") from e
    baixas = dados.get("baixas") if isinstance(dados, dict) else None
    if not isinstance(baixas, list):
        raise ValueError("o arquivo não é a lista de baixas do HTML das PF "
                         "(falta a lista «baixas»)")
    itens = []
    for b in baixas:
        if not isinstance(b, dict):
            raise ValueError("a lista de baixas tem um item que não é um pagamento")
        txt = lambda k: str(b.get(k) or "").strip()          # noqa: E731
        itens.append(Item(
            lancamento_id=txt("lancamento_id"), valor=_valor(b.get("valor")),
            conta=txt("conta"), conta_id=txt("conta_id"),
            data=_data(b.get("data_pagamento")), fornecedor=txt("fornecedor"),
            parte=txt("parte"), vencimento=txt("vencimento"),
            titulo_id=txt("titulo_id"), valor_cru=txt("valor"),
            data_cru=txt("data_pagamento")))
    if not itens:
        raise ValueError("a lista de baixas está vazia")
    return itens


# ------------------------------------------------------------------ registro

class Registro:
    """O que este app já baixou: {lancamento_id: {estado, quando, ...}}.

    `estado` "em_andamento" (anotado antes do POST) ou "ok". Arquivo
    estragado LEVANTA: sem ele não se sabe o que já foi baixado, e seguir
    seria arriscar a baixa em dobro."""

    def __init__(self, caminho):
        self.caminho = caminho
        try:
            texto = caminho.read_text(encoding="utf-8")
        except FileNotFoundError:
            self.dados = {}
            return
        try:
            dados = json.loads(texto)
        except ValueError as e:
            raise ValueError(f"o registro das baixas ({caminho.name}) está "
                             "estragado — não dá para saber o que já foi baixado") from e
        if not isinstance(dados, dict):
            raise ValueError(f"o registro das baixas ({caminho.name}) está estragado")
        self.dados = dados

    def de(self, lancamento_id: str) -> dict | None:
        d = self.dados.get(lancamento_id)
        return d if isinstance(d, dict) else None

    def anotar(self, item: Item, estado: str, agora: str, **extra) -> None:
        self.dados[item.lancamento_id] = {
            "estado": estado, "quando": agora, "valor": str(item.valor),
            "conta": item.conta, "data_pagamento": item.data_cru, **extra}
        tmp = self.caminho.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.dados, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        tmp.replace(self.caminho)

    def esquecer(self, lancamento_id: str) -> None:
        """Só para o "em andamento" que o ERP confirmou SEM baixa."""
        if self.dados.pop(lancamento_id, None) is not None:
            tmp = self.caminho.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.dados, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(self.caminho)


# ------------------------------------------------------------------ conferir

def _url_titulo(lid: str) -> str:
    return f"{LEGADO}/payable-installments/{lid}"


def em_aberto_do_titulo(t: dict) -> Decimal | None:
    for campo in ("remainingValue", "pendingValue"):
        if t.get(campo) is not None:
            try:
                return Decimal(str(t[campo])).quantize(Decimal("0.01"))
            except InvalidOperation:
                return None
    return None


def _soma_paga(t: dict) -> Decimal:
    try:
        return Decimal(str(t.get("sumOfPaidValues") or 0))
    except InvalidOperation:
        return Decimal("0")


def tem_pagamento(t: dict) -> bool:
    """Qualquer sinal de pagamento — inclusive parcial (`sumOfPaidValues`)."""
    return bool(t.get("paid") or t.get("markedAsPaid") or (t.get("paids") or [])
                or _soma_paga(t) > 0)


def baixa_fechou(t: dict) -> bool:
    """Relido depois do POST: tem pagamento e nada ficou em aberto."""
    if not tem_pagamento(t):
        return False
    aberto = em_aberto_do_titulo(t)
    return aberto is None or aberto == 0


def _conferir_sem_erp(itens, contas_por_id, registro, hoje):
    """Os motivos que não precisam do ERP; {índice: motivo}."""
    vistos: dict[str, int] = {}
    for i, it in enumerate(itens):
        if it.lancamento_id:
            vistos[it.lancamento_id] = vistos.get(it.lancamento_id, 0) + 1
    saida = {}
    for i, it in enumerate(itens):
        reg = registro.de(it.lancamento_id) if it.lancamento_id else None
        if not it.lancamento_id:
            m = M_SEM_ID
        elif vistos[it.lancamento_id] > 1:
            m = M_REPETIDO
        elif it.parte:
            m = M_DIVIDIDO.format(parte=it.parte)
        elif it.valor is None:
            m = M_VALOR.format(valor=it.valor_cru or "vazio")
        elif it.data is None:
            m = M_DATA.format(data=it.data_cru or "vazia")
        elif it.data > hoje:
            m = M_FUTURO.format(data=it.data.strftime("%d/%m/%Y"))
        elif (hoje - it.data).days > DIAS_PARA_TRAS:
            m = M_ANTIGA.format(data=it.data.strftime("%d/%m/%Y"))
        elif reg and reg.get("estado") == "ok":
            m = M_JA_BAIXADO.format(quando=str(reg.get("quando") or "?")[:16])
        else:
            c = contas_por_id.get(it.conta_id)
            if c is None:
                m = M_SEM_CONTA.format(conta=it.conta or it.conta_id or "vazia")
            elif str(c.get("name") or "").strip() != it.conta:
                m = M_NOME_CONTA.format(arquivo=it.conta, erp=str(c.get("name") or "").strip())
            else:
                abertura = _data(c.get("openingBalanceDate") or "")
                m = (M_ANTES_ABERTURA.format(abertura=abertura.strftime("%d/%m/%Y"))
                     if abertura and it.data < abertura else "")
        if m:
            saida[i] = m
    return saida


def conferir_titulo(t: dict, item: Item, incerto: bool) -> tuple[str, Decimal | None]:
    """(motivo, em aberto) de um título lido do ERP."""
    aberto = em_aberto_do_titulo(t)
    if tem_pagamento(t):
        return M_JA_PAGO, aberto
    if incerto:
        return M_INCERTO, aberto
    if aberto is None:
        return M_SEM_EM_ABERTO, None
    if aberto != item.valor:
        return M_EM_ABERTO.format(erp=_dinheiro(aberto), arquivo=_dinheiro(item.valor)), aberto
    return "", aberto


def conferir(pedir, itens, contas, registro: Registro, *, hoje: _dt.date,
             log=print) -> list[Conferido]:
    """Uma linha por item, na ordem do arquivo. `contas` = as contas ativas
    CRUAS do ERP ({id, name, ...}). Só leitura no ERP."""
    contas_por_id = {str(c.get("id")): c for c in contas or () if c.get("id")}
    sem_erp = _conferir_sem_erp(itens, contas_por_id, registro, hoje)
    saida = []
    for i, it in enumerate(itens):
        if i in sem_erp:
            saida.append(Conferido(it, sem_erp[i]))
            continue
        reg = registro.de(it.lancamento_id)
        incerto = bool(reg and reg.get("estado") != "ok")
        try:
            t = pedir(_url_titulo(it.lancamento_id))
        except Exception as e:                                  # noqa: BLE001
            saida.append(Conferido(it, M_NAO_LI.format(erro=type(e).__name__)))
            continue
        if not isinstance(t, dict):
            saida.append(Conferido(it, M_NAO_LI.format(erro="resposta vazia")))
            continue
        motivo, aberto = conferir_titulo(t, it, incerto)
        saida.append(Conferido(it, motivo, aberto))
    return saida


# ------------------------------------------------------------------ baixar

def corpo(padrao: dict, item: Item, conta: dict) -> dict:
    """O `default-paid` com a conta, a data e o valor do arquivo por cima.
    Só para item apto (data e valor lidos — `conferir` garante)."""
    if item.data is None or item.valor is None:
        raise ValueError("item sem data ou valor não se baixa")
    c, _aviso = baixa_erp.corpo_da_baixa(padrao, item.data, item.valor)
    c["account"] = {"id": str(conta.get("id")), "name": str(conta.get("name") or "").strip(),
                    "openingBalanceDate": str(conta.get("openingBalanceDate") or "")[:10]}
    c["payingDate"] = item.data.strftime("%Y-%m-%d")
    for campo in baixa_erp.ESCREVER_VALOR:
        c[campo] = float(item.valor)
    return c


def _id_criado(r) -> str:
    if isinstance(r, dict):
        return str(r.get("id") or "")
    return ""


def baixar(pedir, conferidos, contas, registro: Registro, *, agora, log=print,
           cancelar=lambda: False) -> Rodada:
    """Baixa os aptos, um por um. `agora()` devolve o carimbo do registro."""
    contas_por_id = {str(c.get("id")): c for c in contas or () if c.get("id")}
    rodada = Rodada()
    for cf in conferidos:
        if not cf.apto:
            continue
        if cancelar():
            log("  Parado a pedido — os que faltam não foram baixados.")
            break
        it = cf.item
        nome = f"{it.fornecedor[:30]} {_dinheiro(it.valor)}"
        # 1. relê já antes do POST
        try:
            t = pedir(_url_titulo(it.lancamento_id))
        except Exception as e:                                  # noqa: BLE001
            rodada.resultados.append(Baixado(it, False, M_NAO_LI.format(erro=type(e).__name__)))
            log(f"  NÃO BAIXEI {nome}: não consegui reler o título")
            continue
        motivo, _ = conferir_titulo(t if isinstance(t, dict) else {}, it, False)
        if motivo:
            rodada.resultados.append(Baixado(it, False, motivo))
            log(f"  NÃO BAIXEI {nome}: {motivo}")
            continue
        try:
            padrao = pedir(f"{LEGADO}/payable-installments/{it.lancamento_id}/default-paid")
        except Exception as e:                                  # noqa: BLE001
            rodada.resultados.append(Baixado(it, False, f"o ERP não devolveu o corpo da baixa ({type(e).__name__})"))
            log(f"  NÃO BAIXEI {nome}: o ERP não devolveu o corpo da baixa")
            continue
        if not isinstance(padrao, dict):
            rodada.resultados.append(Baixado(it, False, "o ERP não devolveu o corpo da baixa"))
            continue
        conta = contas_por_id.get(it.conta_id)
        if conta is None or str(conta.get("name") or "").strip() != it.conta:
            rodada.resultados.append(Baixado(it, False, M_SEM_CONTA.format(conta=it.conta)))
            log(f"  NÃO BAIXEI {nome}: a conta mudou no ERP desde a conferência")
            continue
        c = corpo(padrao, it, conta)
        # 2. anota ANTES do POST
        registro.anotar(it, "em_andamento", agora())
        url = (f"{LEGADO}/payable-installments/{it.lancamento_id}/paids?"
               f"{baixa_erp.PARAMS_BAIXA}")
        try:
            r = pedir(url, metodo="POST", corpo=c)
        except Exception as e:                                  # noqa: BLE001
            # 3. sem resposta: só o ERP diz o que aconteceu
            try:
                t2 = pedir(_url_titulo(it.lancamento_id))
            except Exception:                                   # noqa: BLE001
                rodada.resultados.append(Baixado(it, False, (
                    f"a baixa deu erro ({type(e).__name__}) e não consegui reler o "
                    "título — confira no ERP antes de qualquer nova tentativa"), incerto=True))
                rodada.parou = True
                log(f"  INCERTO {nome}: confira no ERP. Parei aqui.")
                break
            if isinstance(t2, dict) and tem_pagamento(t2):
                pid = _id_criado((t2.get("paids") or [{}])[-1])
                _anotar_ok(registro, it, agora, pid, log)
                rodada.resultados.append(Baixado(it, True, "a gravação deu erro, mas a baixa entrou "
                                                           "(conferido relendo)", pid))
                log(f"  ok {nome} (conferido relendo)")
                continue
            registro.esquecer(it.lancamento_id)
            rodada.resultados.append(Baixado(it, False, (
                f"o ERP respondeu erro ({e}) e, relendo agora, não mostra a baixa — "
                "carregue o arquivo de novo para conferir antes de baixar à mão")))
            log(f"  FALHOU {nome}: erro do ERP ({e}); relendo, sem baixa. Não tentei de novo.")
            continue
        pid = _id_criado(r)
        _anotar_ok(registro, it, agora, pid, log)
        # 4. a prova é o título relido, não o 200
        try:
            t3 = pedir(_url_titulo(it.lancamento_id))
        except Exception:                                       # noqa: BLE001
            t3 = None
        if not isinstance(t3, dict):
            rodada.resultados.append(Baixado(it, True, "baixa enviada, mas não consegui "
                                                       "reler o título — confira no ERP", pid))
            log(f"  ok? {nome}: baixa enviada, não consegui reler — confira no ERP")
        elif not baixa_fechou(t3):
            aberto = em_aberto_do_titulo(t3)
            rodada.resultados.append(Baixado(it, False, (
                "o ERP aceitou a baixa, mas o título "
                + ("continua sem pagamento" if not tem_pagamento(t3)
                   else f"ficou com {_dinheiro(aberto)} em aberto")
                + " — confira no ERP (não baixo de novo)"), pid))
            log(f"  CONFIRA {nome}: o ERP aceitou, mas o título não fechou")
        else:
            rodada.resultados.append(Baixado(it, True, "", pid))
            log(f"  ok {nome} · {it.conta}")
    return rodada


def _anotar_ok(registro, it, agora, pid, log) -> None:
    """A baixa já entrou: falha do disco não pode derrubar a rodada. O
    registro fica "em_andamento", que a próxima carga trata como confira."""
    try:
        registro.anotar(it, "ok", agora(), paid_id=pid)
    except OSError as e:
        log(f"  [!] a baixa de {it.fornecedor[:30]} entrou, mas o registro local "
            f"não gravou ({e}) — ela continua protegida pela releitura do ERP")
