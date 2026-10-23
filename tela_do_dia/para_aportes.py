# -*- coding: utf-8 -*-
"""Os aportes definidos na tela do dia viram operações da aba Aportes.

Nada vai ao ERP daqui: as operações entram na lista "A lançar" e o dono confere
e clica "Lançar no Mais Controle" lá, como sempre. Quatro regras de dinheiro:

- **nome não se chuta.** O rótulo da aba Regras e o cadastro da aba Aportes
  (`contas.csv`) são vocabulários diferentes; casa pelo NOME COMPLETO via
  `normalize_name` (sem acento, caixa ou pontuação) ou pelo NÚMERO da conta, e
  só com UM candidato. Dois aportadores com o mesmo primeiro nome são pessoas
  diferentes: nome pela metade não casa com ninguém. Sobrou dúvida, vira
  pendência;
- **subconta de investidor é UMA operação** ("INVESTIDOR SUBCONTA 00000-0"),
  porque a aba Aportes rateia pelo `subcontas.json`. Se a divisão digitada não
  for a do cadastro, é pendência — a outra aba lançaria a dela, não a sua;
- **o que já foi mandado hoje não vai de novo** sem o dono pedir. A chave é
  só destino e aportador (`chave_de_envio`), e o valor mandado fica guardado
  ao lado dela: corrigir 300,00 para 350,00 e mandar de novo NÃO gera segunda
  operação — vira pendência "já mandado R$ 300,00 hoje; agora R$ 350,00",
  porque a primeira pode já estar lançada e o ERP somaria 650,00. Aporte em
  dobro se desfaz à mão no ERP;
- **conta sem saldo do sistema** (o ERP não trouxe; `AporteDaConta.sem_saldo`)
  não sai calada: a operação vai em `itens`, mas ganha o AVISO
  `MOTIVO_SEM_SALDO` (em `Envio.avisos`, não em `pendentes`) e entra em
  `Envio.sem_saldo`. Quem decide se trava é a tela.

`Envio.pendentes` = o que NÃO foi (bloqueia: já mandado, nome não achado,
divisão diferente…); `Envio.avisos` = o que foi, mas pede conferência;
`Envio.informativos` = o que não vai e está CERTO não ir (transferência entre
contas da mesma empresa: lança-se no banco, não é aporte).

Item A (22/10/2026), duas entradas novas:

- **aportador composto da aba Regras** ("Fulano/Beltrano", dois investidores
  numa linha só): nunca se casa pelo primeiro nome. Se o DESTINO é subconta de
  investidor no cadastro (pelo número no rótulo ou na conta do cadastro), vai
  como "Aporte de Investidor" daquela subconta, dividido pelo cadastro, com um
  aviso que mostra os investidores de lá — desde que o número de nomes bata.
  Senão é pendência que diz o que cadastrar;
- **distribuição de lucros** feita à mão na tela (conta do painel → sócio ou
  investidor do cadastro): vira "Distribuição de Lucro", e o modo sai do
  cadastro (sócio sem conta → "Só pagamento"). A chave de envio é própria
  (`chave_da_distribuicao`) e o mesmo par no dia vira UMA operação somada.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

import util
from aportes.dados import INVESTIDOR_PREFIXO
from aportes.regras import (TIPO_INVESTIDOR, Operacao, como_dinheiro,
                            dividir_por_peso, e_da_subconta, numero_da_conta)
from conciliacao.parsing import normalize_name

from .valores import brl

ZERO = Decimal("0.00")

MOTIVO_SEM_SALDO = "conta sem saldo do sistema — confira antes de lançar"
#: O já mandado que não está mais na lista da aba Aportes (app fechado,
#: "Limpar tudo" ou já lançado e retirado): "confira lá" mandaria procurar
#: onde não há nada, e digitar de novo pode ser o segundo aporte.
FORA_DA_ABA = "não está mais na aba Aportes"
_CONFIRA_NO_ERP = f"{FORA_DA_ABA} — já lançou? confira no ERP antes de digitar de novo"


@dataclass(frozen=True)
class Pendente:
    destino: str
    aportador: str
    valor: Decimal
    motivo: str


@dataclass
class Envio:
    #: [(Operacao, [chave_de_envio])] — o que pode ir para a aba Aportes.
    itens: list = field(default_factory=list)
    #: [Pendente] que BLOQUEIAM: estes pares NÃO estão em `itens`.
    pendentes: list = field(default_factory=list)
    #: [Pendente] que NÃO bloqueiam: o par está em `itens`, mas confira.
    avisos: list = field(default_factory=list)
    #: [Pendente] que não vão e está certo não irem (transferência entre
    #: contas): só para o Registro, sem cara de erro.
    informativos: list = field(default_factory=list)
    #: chave_de_envio -> valor daquele aportador (o que `marcar_enviados` guarda).
    valores: dict = field(default_factory=dict)
    #: As OPERAÇÕES de `itens` (os mesmos objetos) com conta sem saldo do
    #: sistema, no destino ou no aportador. Objeto, não índice: a tela pode
    #: filtrar `itens` e índice deslizaria.
    sem_saldo: list = field(default_factory=list)


def chave_de_envio(destino: str, aportador: str) -> str:
    """Sem o valor, de propósito: o valor mandado é o VALOR do dicionário
    `enviados_aportes`, e mudar o número não abre a porta para mandar de novo."""
    return f"{destino}|{aportador}"


#: O que distingue a chave de uma distribuição da de um aporte da aba Regras
#: ("destino|aportador"): sem o prefixo, distribuir para quem também aporta
#: noutra linha dividiria o mesmo registro de "já mandado".
PREFIXO_DISTRIBUICAO = "distribuição→"

#: O recado da transferência da aba Regras: informa, não acusa.
TRANSFERENCIA = "transferência entre contas: lance no banco; não é aporte"


def chave_da_distribuicao(origem: str, socio: str) -> str:
    return chave_de_envio(PREFIXO_DISTRIBUICAO + socio, origem)


#: A chave de "já mandado" de uma subconta de investidor é pelo NÚMERO dela
#: (revisão de dinheiro de 22/10/2026, A4): a linha composta da aba Regras
#: ("destino|Fulano/Beltrano") e as linhas por investidor ("destino|Fulano")
#: são a MESMA operação na aba Aportes, e chaves diferentes deixavam a segunda
#: porta mandar outro Aporte de Investidor da mesma subconta no mesmo dia.
PREFIXO_SUBCONTA = "subconta:"


def chave_da_subconta(numero: str, destino: str) -> str:
    return f"{PREFIXO_SUBCONTA}{numero}|{destino}"


def _ja_da_subconta(numero, enviados, entidades, subcontas):
    """As chaves de `enviados` que já mandaram a subconta `numero` hoje: a
    nova (`chave_da_subconta`, qualquer destino) e as antigas, gravadas antes
    desta correção no JSON do dia — "destino|Fulano/Beltrano" (composto) e
    "destino|<investidor>" —, quando o destino é aquela subconta. Devolve
    (chaves, valor somado ou None quando algum valor não se sabe)."""
    investidores = {util.norm_espaco(i)
                    for i in (subcontas.get(numero) or {}).get("investidores") or ()}
    achadas = []
    for chave in enviados:
        if chave.startswith(PREFIXO_SUBCONTA):
            if chave[len(PREFIXO_SUBCONTA):].partition("|")[0] == numero:
                achadas.append(chave)
            continue
        destino, sep, aportador = chave.partition("|")
        if not sep or not (nomes_do_composto(aportador)
                           or util.norm_espaco(aportador) in investidores):
            continue
        recebedor = nome_no_cadastro(destino, entidades)
        if _subconta_do_destino(destino, recebedor, entidades, subcontas) == numero:
            achadas.append(chave)
    valores = [enviados[c] for c in achadas]
    soma = None if any(v is None for v in valores) else sum(
        (como_dinheiro(v) for v in valores), ZERO)
    return achadas, soma


def nomes_do_composto(aportador: str) -> list[str]:
    """Os nomes de um rótulo composto da aba Regras ("Fulano/Beltrano") —
    [] quando não é composto. Só para CONTAR: nome pela metade não casa."""
    partes = [p.strip() for p in re.split(r"[/&+]", aportador or "")]
    partes = [p for p in partes if p]
    return partes if len(partes) > 1 else []


def _subconta_do_destino(destino: str, recebedor, entidades: dict, subcontas: dict) -> str:
    """O número da subconta de investidor que é o destino, ou ""."""
    numero = numero_da_conta(destino)
    if not numero and recebedor is not None:
        numero = numero_da_conta((entidades.get(recebedor) or {}).get("conta") or "")
    return numero if numero and numero in subcontas else ""


def _o_que_cadastrar(aportador: str, destino: str) -> str:
    return (f"{aportador!r} junta mais de um aportador numa linha da aba Regras e "
            f"{destino!r} não é subconta de investidor no cadastro da aba Aportes — "
            "cadastre a subconta de investidor dessa conta (aba Aportes → Novo "
            "cadastro → Subconta de investidor, com cada investidor pelo nome "
            "completo) ou ponha na aba Regras um aportador por linha, com o nome "
            "completo como está no cadastro")


def operacoes_recusadas(mandadas, recusas) -> list:
    """Traduz as recusas de `AportesFrame.receber_operacoes` — [(índice,
    motivo)], índice na lista que FOI passada a ela — nas operações recusadas.
    `mandadas` tem de ser exatamente essa lista, na mesma ordem: é o único
    ponto em que índice e operação ainda se correspondem."""
    return [mandadas[i] for i, _motivo in recusas]


def marcar_enviados(envio: Envio, mandadas, recusadas, enviados: dict) -> list[str]:
    """Guarda em `enviados` (chave -> valor mandado, Decimal) as chaves das
    operações que FORAM para a aba Aportes e ela ACEITOU; devolve as chaves
    marcadas.

    - `mandadas`: as operações efetivamente passadas a `receber_operacoes`
      (os mesmos objetos de `envio.itens`; a tela pode ter segurado algumas
      e mudado a ordem);
    - `recusadas`: as que a aba recusou (`operacoes_recusadas`).

    Casa por IDENTIDADE do objeto `Operacao`, nunca por posição nem por
    igualdade de valor: item segurado pela tela não é marcado (não foi),
    recusado não é marcado (a aba não o tem), e ordem trocada não desliza.
    Operação que não é de `envio.itens` não marca nada."""
    foram = {id(op) for op in mandadas} - {id(op) for op in recusadas}
    marcadas = []
    for op, chaves in envio.itens:
        if id(op) not in foram:
            continue
        for chave in chaves:
            enviados[chave] = envio.valores[chave]
            marcadas.append(chave)
    return marcadas


def enviados_apos(antes: dict, envio: Envio, mandadas, recusadas) -> dict:
    """Um `enviados_aportes` NOVO: `antes` mais as chaves das `mandadas` que
    não estão em `recusadas` (por identidade, como `marcar_enviados`). `antes`
    não muda.

    A tela usa duas vezes: com `recusadas=[]`, para gravar o registro ANTES de
    entregar à aba Aportes (gravação que falha = nada vai; o contrário — mandar
    e não conseguir anotar — fazia o próximo Buscar esquecer o envio e o aporte
    ir em dobro); e depois da entrega, com as recusadas, para desmarcá-las."""
    novo = dict(antes)
    marcar_enviados(envio, mandadas, recusadas, novo)
    return novo


def nome_no_cadastro(rotulo: str, entidades: dict) -> str | None:
    alvo = normalize_name(rotulo)
    if not alvo:
        return None
    iguais = [n for n, d in entidades.items()
              if alvo in (normalize_name(n), normalize_name((d or {}).get("nome_oficial") or ""))]
    if len(iguais) == 1:
        return iguais[0]
    if iguais:
        return None
    numero = numero_da_conta(rotulo)
    if not numero:
        return None
    pelo_numero = [n for n, d in entidades.items() if e_da_subconta(n, d or {}, numero)]
    return pelo_numero[0] if len(pelo_numero) == 1 else None


def _da_conta_no_cadastro(rotulo: str, entidades: dict) -> str | None:
    """`nome_no_cadastro` e, se ele não achar, a conta do painel pela CONTA
    do ERP no cadastro (o nome do cadastro pode ser outro) — um só candidato.
    Só para a distribuição: as duas pontas dela podem ser contas do painel."""
    achado = nome_no_cadastro(rotulo, entidades)
    if achado is not None:
        return achado
    alvo = normalize_name(rotulo)
    if not alvo:
        return None
    pela_conta = [n for n, d in entidades.items()
                  if normalize_name((d or {}).get("conta") or "") == alvo]
    return pela_conta[0] if len(pela_conta) == 1 else None


def _tipo(tipo_regra: str) -> str:
    t = util.sem_acento(tipo_regra or "Aporte").casefold().strip()
    if t.startswith("aporte"):
        return "Aporte de Capital"
    if t.startswith("distribui"):
        return "Distribuição de Lucro"
    return ""


def _modo(pagador: str, recebedor: str, entidades: dict) -> str:
    if (entidades[pagador] or {}).get("conta") is None:
        return "Só recebimento"
    if (entidades[recebedor] or {}).get("conta") is None:
        return "Só pagamento"
    return "Pagamento + Recebimento"


def ainda_na_aba(pagador, recebedor, data, na_aba) -> bool | None:
    """Se a aba Aportes ainda tem, na lista "A lançar", uma operação de
    `pagador` para `recebedor` na `data`. None = não se sabe (a tela não
    passou a lista, ou o nome não casou no cadastro): fica o recado de antes.
    Casa por pagador, recebedor e data, sem o valor: a de lá tem o valor
    MANDADO, e a pergunta é se ela ainda está lá, não se o número bate."""
    if na_aba is None or not pagador or not recebedor:
        return None
    return any(op.pagador == pagador and op.recebedor == recebedor and op.data == data
               for op in na_aba)


def _ja_mandado(anterior, valor, fora_da_aba: bool = False) -> str:
    if fora_da_aba:
        quanto = "" if anterior is None else f" {brl(como_dinheiro(anterior))}"
        return f"já mandado{quanto} hoje, mas {_CONFIRA_NO_ERP}"
    if anterior is None:
        return ("já mandado para a aba Aportes hoje — confira lá antes de "
                "mandar de novo")
    if como_dinheiro(anterior) == como_dinheiro(valor):
        return (f"já mandado {brl(como_dinheiro(anterior))} hoje para a aba Aportes — "
                "confira lá antes de mandar de novo")
    return (f"já mandado {brl(como_dinheiro(anterior))} hoje; agora "
            f"{brl(como_dinheiro(valor))} — confira a aba Aportes (a de antes pode "
            "já estar lançada; corrija lá, não mande outra)")


def operacoes(definidos, regras, entidades, subcontas, data, enviados=None,
              sem_saldo=(), na_aba_aportes=None, distribuicoes=(),
              contas_do_painel=()) -> Envio:
    """`enviados`: {chave_de_envio: valor mandado} do dia (um conjunto de
    chaves também serve, com o valor desconhecido). `sem_saldo`: rótulos das
    contas do dia cujo saldo o sistema não trouxe. `na_aba_aportes`: as
    operações que a aba Aportes tem AGORA na lista (None = não se sabe); o já
    mandado que não está mais lá ganha o recado `FORA_DA_ABA`.
    `distribuicoes`: [(conta de origem, quem recebe, valor)] feitas à mão
    na tela; quem recebe é nome do cadastro ou OUTRA conta do painel
    (`contas_do_painel`: os rótulos, para exigir a conta do ERP no cadastro
    dela também — o dinheiro entra nela)."""
    if enviados is None:
        enviados = {}
    elif not isinstance(enviados, dict):
        enviados = dict.fromkeys(enviados)
    sem_saldo = set(sem_saldo or ())
    envio = Envio()
    regra_do_par = {(r.destino, r.aportador): r for r in regras}
    da_subconta: dict[tuple[str, str], dict] = {}
    compostos: list[tuple] = []

    def pendente(destino, aportador, valor, motivo):
        envio.pendentes.append(Pendente(destino, aportador, valor, motivo))

    def aviso(destino, aportador, valor, motivo):
        envio.avisos.append(Pendente(destino, aportador, valor, motivo))

    def incluir(op, pares, subconta=""):
        if subconta:
            # A subconta é UMA operação e UMA chave, com o total.
            chaves = [chave_da_subconta(subconta, pares[0][0])]
            envio.valores[chaves[0]] = como_dinheiro(op.valor)
        else:
            chaves = [chave_de_envio(d, a) for d, a, _v in pares]
            for chave, (_d, _a, v) in zip(chaves, pares):
                envio.valores[chave] = como_dinheiro(v)
        envio.itens.append((op, chaves))
        if any(d in sem_saldo or a in sem_saldo for d, a, _v in pares):
            envio.sem_saldo.append(op)
            for d, a, v in pares:
                aviso(d, a, v, MOTIVO_SEM_SALDO)

    for (destino, aportador), valor in definidos.items():
        if not valor or valor <= 0:
            continue
        regra = regra_do_par.get((destino, aportador))
        if regra is None:
            pendente(destino, aportador, valor, "não está na aba Regras do modelo")
            continue
        numero = numero_da_conta(destino)
        # Transferência primeiro: com destino em subconta ela cairia na
        # pendência dos investidores, que não é o assunto dela.
        if util.sem_acento(regra.tipo or "").casefold().strip().startswith("transf"):
            envio.informativos.append(Pendente(destino, aportador, valor, TRANSFERENCIA))
            continue
        if (nomes_do_composto(aportador) and not regra.do_painel
                and nome_no_cadastro(aportador, entidades) is None):
            compostos.append((destino, aportador, valor, regra))
            continue
        if numero and numero in subcontas and not regra.do_painel:
            da_subconta.setdefault((destino, numero), {})[aportador] = valor
            continue
        chave = chave_de_envio(destino, aportador)
        if chave in enviados:
            la = ainda_na_aba(nome_no_cadastro(aportador, entidades),
                              nome_no_cadastro(destino, entidades), data, na_aba_aportes)
            pendente(destino, aportador, valor,
                     _ja_mandado(enviados[chave], valor, fora_da_aba=la is False))
            continue
        tipo = _tipo(regra.tipo)
        pagador, recebedor = nome_no_cadastro(aportador, entidades), nome_no_cadastro(destino, entidades)
        if not tipo:
            pendente(destino, aportador, valor, f"tipo {regra.tipo!r} da aba Regras não é aporte nem distribuição")
            continue
        if pagador is None or recebedor is None:
            falta = aportador if pagador is None else destino
            pendente(destino, aportador, valor, f"não achei {falta!r} (um só) no cadastro da aba Aportes")
            continue
        op = Operacao(data=data, pagador=pagador, recebedor=recebedor, valor=como_dinheiro(valor),
                      tipo=tipo, modo=_modo(pagador, recebedor, entidades))
        erros = op.validar(entidades, subcontas)
        if erros:
            pendente(destino, aportador, valor, "; ".join(erros))
            continue
        incluir(op, [(destino, aportador, valor)])

    for (destino, numero), valores in da_subconta.items():
        def todos(motivo):
            for a, v in valores.items():
                pendente(destino, a, v, motivo)
        ja, anterior = _ja_da_subconta(numero, enviados, entidades, subcontas)
        if ja:
            # A subconta é UMA operação: já mandada por qualquer porta (linha
            # composta ou por investidor), segura todos os investidores.
            fora = ainda_na_aba(INVESTIDOR_PREFIXO + numero, nome_no_cadastro(destino, entidades),
                                data, na_aba_aportes) is False
            total = sum(valores.values(), ZERO)
            for a, v in valores.items():
                pendente(destino, a, v,
                         f"{_ja_mandado(anterior, total, fora_da_aba=fora)} (subconta "
                         f"{numero}, numa operação só)")
            continue
        cfg = subcontas[numero]
        investidores = cfg.get("investidores") or []
        total = sum(valores.values(), ZERO)
        recebedor = nome_no_cadastro(destino, entidades)
        por_nome = {util.norm_espaco(a): v for a, v in valores.items()}
        if recebedor is None:
            todos(f"não achei {destino!r} (um só) no cadastro da aba Aportes")
            continue
        if (len(por_nome) != len(valores)
                or set(por_nome) != {util.norm_espaco(i) for i in investidores}):
            todos(f"os investidores digitados não são os da subconta {numero} no cadastro")
            continue
        try:
            partes = dividir_por_peso(total, investidores, cfg.get("pesos") or {})
        except ValueError as e:
            todos(str(e))
            continue
        if any(por_nome[util.norm_espaco(i)] != p for i, p in zip(investidores, partes)):
            todos(f"a divisão digitada difere da do cadastro da subconta {numero} "
                  "(a aba Aportes divide pelo cadastro)")
            continue
        op = Operacao(data=data, pagador=INVESTIDOR_PREFIXO + numero, recebedor=recebedor,
                      valor=como_dinheiro(total), tipo=TIPO_INVESTIDOR, modo="Só recebimento")
        erros = op.validar(entidades, subcontas)
        if erros:
            todos("; ".join(erros))
            continue
        incluir(op, [(destino, a, v) for a, v in valores.items()], subconta=numero)

    subcontas_por_investidor = {n for (_d, n) in da_subconta}
    for destino, aportador, valor, regra in compostos:
        nomes = nomes_do_composto(aportador)
        if _tipo(regra.tipo) != "Aporte de Capital":
            # O composto só sabe ir como Aporte de Investidor (A5): outro tipo
            # viraria aporte sem ninguém pedir.
            pendente(destino, aportador, valor,
                     f"tipo {regra.tipo!r} da aba Regras com {aportador!r} (mais de um "
                     "nome numa linha): a linha composta só vai como aporte da subconta "
                     "de investidor — lance este à mão na aba Aportes ou ponha um nome "
                     "por linha na aba Regras")
            continue
        recebedor = nome_no_cadastro(destino, entidades)
        if recebedor is None:
            pendente(destino, aportador, valor,
                     f"não achei {destino!r} (um só) no cadastro da aba Aportes")
            continue
        numero = _subconta_do_destino(destino, recebedor, entidades, subcontas)
        if not numero:
            pendente(destino, aportador, valor, _o_que_cadastrar(aportador, destino))
            continue
        if numero in subcontas_por_investidor:
            pendente(destino, aportador, valor,
                     f"a subconta {numero} tem valor no grupo {aportador!r} e também por "
                     "investidor — digite num lugar só (a subconta vai numa operação só)")
            continue
        pagador = INVESTIDOR_PREFIXO + numero
        ja, anterior = _ja_da_subconta(numero, enviados, entidades, subcontas)
        if ja:
            la = ainda_na_aba(pagador, recebedor, data, na_aba_aportes)
            pendente(destino, aportador, valor,
                     _ja_mandado(anterior, valor, fora_da_aba=la is False))
            continue
        investidores = [str(i).strip() for i in (subcontas[numero].get("investidores") or [])
                        if str(i).strip()]
        if len(nomes) != len(investidores):
            pendente(destino, aportador, valor,
                     f"{aportador!r} tem {len(nomes)} nomes e a subconta {numero} tem "
                     f"{len(investidores)} investidores no cadastro "
                     f"({', '.join(investidores) or 'nenhum'}) — confira a aba Regras ou "
                     "o cadastro da subconta (aba Aportes → Novo cadastro)")
            continue
        op = Operacao(data=data, pagador=pagador, recebedor=recebedor,
                      valor=como_dinheiro(valor), tipo=TIPO_INVESTIDOR, modo="Só recebimento")
        erros = op.validar(entidades, subcontas)
        if erros:
            pendente(destino, aportador, valor, "; ".join(erros))
            continue
        incluir(op, [(destino, aportador, valor)], subconta=numero)
        aviso(destino, aportador, valor,
              f"vai como {TIPO_INVESTIDOR} da subconta {numero}, dividido pelo cadastro "
              f"entre {', '.join(investidores)} — confira na aba Aportes")

    # Distribuição de lucros feita à mão: o mesmo par no dia é UMA operação.
    somadas: dict[tuple[str, str], Decimal] = {}
    for origem, socio, valor in (distribuicoes or ()):
        if valor is None or valor <= 0:
            continue
        somadas[(origem, socio)] = somadas.get((origem, socio), ZERO) + valor
    for (origem, socio), valor in somadas.items():
        rotulo = f"{socio} (distribuição de lucros)"
        chave = chave_da_distribuicao(origem, socio)
        pagador = _da_conta_no_cadastro(origem, entidades)
        recebedor = socio if socio in entidades else _da_conta_no_cadastro(socio, entidades)
        if chave in enviados:
            la = ainda_na_aba(pagador, recebedor, data, na_aba_aportes)
            pendente(rotulo, origem, valor,
                     _ja_mandado(enviados[chave], valor, fora_da_aba=la is False))
            continue
        if pagador is None or recebedor is None:
            falta = origem if pagador is None else socio
            pendente(rotulo, origem, valor,
                     f"não achei {falta!r} (um só) no cadastro da aba Aportes")
            continue
        if (entidades[pagador] or {}).get("conta") is None:
            # A origem é conta do painel: o dinheiro SAI dela. Sem a conta no
            # cadastro, o modo sairia "Só recebimento" e lançaria só a entrada
            # do sócio (revisão geral de 22/10/2026).
            pendente(rotulo, origem, valor,
                     f"{pagador!r} está no cadastro da aba Aportes sem a conta do ERP, "
                     "e a distribuição SAI dela — complete a conta no cadastro (aba "
                     "Aportes) e mande de novo")
            continue
        destino_no_painel = any(socio.casefold() == r.casefold()
                                for r in contas_do_painel or ())
        if destino_no_painel and (entidades[recebedor] or {}).get("conta") is None:
            # Conta do painel (a empresa sócia, dono 23/10/2026): o dinheiro
            # ENTRA nela. "Só pagamento" lançaria só a saída da origem.
            pendente(rotulo, origem, valor,
                     f"{recebedor!r} está no cadastro da aba Aportes sem a conta do ERP, "
                     "e a distribuição ENTRA nela — complete a conta no cadastro (aba "
                     "Aportes) e mande de novo")
            continue
        op = Operacao(data=data, pagador=pagador, recebedor=recebedor,
                      valor=como_dinheiro(valor), tipo="Distribuição de Lucro",
                      modo=_modo(pagador, recebedor, entidades))
        erros = op.validar(entidades, subcontas)
        if erros:
            pendente(rotulo, origem, valor, "; ".join(erros))
            continue
        envio.itens.append((op, [chave]))
        envio.valores[chave] = como_dinheiro(valor)
        if origem in sem_saldo or socio in sem_saldo:
            envio.sem_saldo.append(op)
            aviso(rotulo, origem, valor, MOTIVO_SEM_SALDO)
    return envio
