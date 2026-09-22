# -*- coding: utf-8 -*-
"""Decide o que fazer com cada guia do mês. Não toca em rede.

Nenhuma decisão é tomada por valor: o valor da guia muda todo mês, e casar por
ele acertaria em fevereiro e erraria em março. O que casa é o
`trade_payable_id` que o dono confirmou uma vez e que a regra guardou.

Quando falta informação, a resposta é DECIDIR — nunca um palpite. Palpite aqui
vira parcela alterada na recorrência errada, e isso só se descobre no extrato.
"""
from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal

import util
from guias import regras as regras_mod
from guias.modelos import ALTERAR, CRIAR, DECIDIR, JA_LANCADO, Decisao


def _dec(valor) -> Decimal | None:
    if valor is None:
        return None
    try:
        return Decimal(str(valor)).quantize(Decimal("0.01"))
    except Exception:
        return None


def _brl(valor) -> str:
    return f"{_dec(valor):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def valor_da_parcela(p: dict):
    """O valor TOTAL da parcela, como a lista de pagamentos o entrega.

    `plannedValue` NÃO existe nesta lista — ele é campo de escrita, do detalhe
    do título (`installments[].plannedValue`, que é o que `lancar.alterar`
    grava). Na resposta de `payable-installments/paginated-result` o `value`
    vem NULL e o dinheiro está partido em dois: `remainingValue` (o que falta
    pagar) e `sumOfPaidValues` (o que já saiu). Contrato conferido em produção
    em 04/09/2026 sobre 2.576 parcelas e documentado em
    `conciliacao/erp/payments_api.py`.

    Somar os dois é o que faz um título PAGO EM PARTE ainda casar com a guia:
    a guia traz o valor cheio, e comparar só com `remainingValue` deixaria de
    reconhecer o título — e não reconhecer aqui significa criar um SEGUNDO
    lançamento para a mesma guia.

    O `value` fica como reserva porque o outro cliente desta rota (o vigia,
    por HTTP puro) já o viu preenchido; ler os dois não custa nada e ler só um
    custaria uma duplicata.
    """
    falta, pago = _dec(p.get("remainingValue")), _dec(p.get("sumOfPaidValues"))
    if falta is None and pago is None:
        # Os dois ausentes OU os dois ilegíveis. `or Decimal("0.00")` abaixo
        # transformaria "não consegui ler" em "li, e é zero" — um valor de
        # verdade, que depois aparece no aviso como se fosse do cadastro.
        return _dec(p.get("value"))
    return (falta or Decimal("0.00")) + (pago or Decimal("0.00"))


def _digitos(texto) -> str:
    return "".join(c for c in str(texto or "") if c.isdigit())


def documento_igual(a, b) -> bool:
    """O mesmo documento, escrito de dois jeitos.

    A guia que tem linha digitável traz o número FORMATADO
    (`00000.00000 00000.000000 00000.000000 0 00000000000000`), porque é assim
    que ele sai do boleto; quem lançou o título à mão no ERP digitou os dígitos
    crus. Comparar só o texto diz "não é o mesmo" para o mesmo documento — e
    não reconhecer aqui não dá erro nenhum: dá um SEGUNDO título para uma guia
    que já existe, e conta aberta em duplicata ninguém vê até pagar duas vezes.

    Seis dígitos é o piso para a comparação por dígitos: abaixo disso ela
    casaria números curtos de documentos diferentes.
    """
    ta = util.norm_espaco(str(a or "")).upper()
    tb = util.norm_espaco(str(b or "")).upper()
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    da, db = _digitos(ta), _digitos(tb)
    return len(da) >= 6 and da == db


def parcela_da_recorrencia(parcelas: list[dict], trade_payable_id: str,
                           vencimento=None) -> dict | None:
    """A parcela desta recorrência, a MAIS PRÓXIMA do vencimento da guia.

    A janela de leitura cobre dois meses de propósito (guia de competência 09
    que vence em outubro tem o título em outubro), e recorrência mensal tem uma
    parcela em cada um. Devolver a primeira da lista seria alterar o título do
    mês errado — e o mês errado já pode estar pago.
    """
    candidatas = [p for p in parcelas or []
                  if str(p.get("tradePayableId") or "") == str(trade_payable_id)]
    if not candidatas or vencimento is None:
        return candidatas[0] if candidatas else None

    def _distancia(p):
        try:
            d = date.fromisoformat(str(p.get("plannedDate") or "")[:10])
        except ValueError:
            return (1, 0)          # sem data legível fica por último
        return (0, abs((d - vencimento).days))

    return min(candidatas, key=_distancia)


def titulo_igual(parcelas: list[dict], documento: str) -> dict | None:
    """Título que JÁ representa esta guia: mesmo número de documento.

    Só o documento, que é o que identifica a guia. O casamento por valor e
    vencimento mora em `titulo_parecido` e nunca vira "já lançado": ele vira
    pergunta, porque valor e vencimento iguais acontecem entre fornecedores
    diferentes.
    """
    for p in parcelas or []:
        if documento_igual(documento, p.get("documentNumber")):
            return p
    return None


#: Teto do casamento por valor quando a guia foi paga com atraso. A lista traz
#: `sumOfPaidValues` — o que SAIU, com multa e juros —, não o nominal, então o
#: título fica MAIOR que a guia. Multa e juros de uma guia com um ou dois meses
#: de atraso não chegam a metade do principal, e parar no meio evita casar a
#: guia com um título grande que só coincide na data.
TETO_DE_ACRESCIMO = Decimal("1.5")


def titulo_parecido(parcelas: list[dict], valor, vencimento) -> dict | None:
    """Título no MESMO vencimento que PODE ser esta guia — sem prova.

    Serve para uma coisa só: impedir que o app CRIE por cima de um título que
    já existe. Por isso é generoso de propósito, e por isso quem o usa devolve
    DECIDIR, nunca JA_LANCADO. O preço de casar demais é uma linha para o dono
    conferir; o de casar de menos é uma conta paga duas vezes.
    """
    alvo, data = _dec(valor), (vencimento.isoformat() if vencimento else "")
    if alvo is None or not data:
        return None
    for p in parcelas or []:
        if str(p.get("plannedDate") or "")[:10] != data:
            continue
        v = valor_da_parcela(p)
        if v is not None and alvo <= v <= alvo * TETO_DE_ACRESCIMO:
            return p
    return None


def sugerir_obra(texto: str, obras) -> str:
    """O id da obra cujo nome aparece no texto do documento. `""` se não houver
    exatamente uma.

    Casa por PALAVRA INTEIRA, com a mesma função que `guias/regras.py` usa para
    classificar o documento: nome de obra que seja pedaço de outra palavra
    sugeriria a obra errada, e obra errada leva a conta errada (a conta vem da
    obra). Duas obras citadas no mesmo texto não viram escolha: escolher uma
    seria palpite.
    """
    achadas = {str(o.get("id")) for o in (obras or [])
               if o.get("name") and regras_mod.tem_palavra(texto, str(o["name"]))}
    return achadas.pop() if len(achadas) == 1 else ""


def decidir(guias, parcelas, regras, registro, competencia: str,
            obras=None) -> list[Decisao]:
    # Duas guias do mesmo tipo na mesma empresa apontariam para a mesma
    # recorrência: a segunda gravação apagaria a primeira. Contar ANTES.
    marcas = Counter()
    for guia in guias:
        tipo = regras.classificar(guia.desc)
        if tipo and tipo.get("acao") == "alterar":
            marcas[(guia.vip_id, tipo.get("nome"))] += 1

    return [_uma(g, parcelas, regras, registro, competencia, marcas, obras)
            for g in guias]


def _uma(guia, parcelas, regras, registro, competencia, marcas,
         obras=None) -> Decisao:
    if guia.erro:
        return Decisao(guia, DECIDIR, motivo=guia.erro)
    if guia.pdf is None:
        return Decisao(guia, DECIDIR, motivo="sem o PDF da guia")
    if guia.valor is None:
        return Decisao(guia, DECIDIR, motivo="não li o valor no PDF")

    feito = registro.ja_feito(guia.vip_id, guia.anx_id, competencia)
    if feito:
        # O estado anterior viaja no motivo: "anexo_pendente" é um título SEM
        # PDF, e escondê-lo atrás de um "já lançado" genérico faz essa guia
        # voltar toda rodada como pronta — e o PDF nunca mais é cobrado de
        # ninguém.
        return Decisao(guia, JA_LANCADO,
                       motivo=f"esta rodada já lançou ({feito.get('estado')})",
                       trade_payable_id=str(feito.get("tpid") or ""))

    tipo = regras.classificar(guia.desc)
    if tipo is None:
        return Decisao(guia, DECIDIR,
                       motivo=f"não conheço este documento: {guia.desc[:60]}")

    nome = str(tipo.get("nome") or "")
    categoria = str(tipo.get("categoria") or "")

    if tipo.get("acao") == "alterar":
        if marcas[(guia.vip_id, nome)] > 1:
            return Decisao(guia, DECIDIR, tipo=nome, categoria=categoria,
                           motivo="mais de uma guia deste tipo nesta empresa "
                                  "no mês: qual é a parcela da recorrência?")
        conhecida = regras.recorrencia(nome, guia.vip_id)
        tpid = str(conhecida.get("trade_payable_id") or "")
        if not tpid:
            return Decisao(guia, DECIDIR, tipo=nome, categoria=categoria,
                           motivo="ainda não sei qual é a recorrência desta "
                                  "empresa para este documento")
        parcela = parcela_da_recorrencia(parcelas, tpid,
                                         guia.vencimento)
        if parcela is None:
            return Decisao(guia, DECIDIR, tipo=nome, categoria=categoria,
                           motivo="a recorrência que eu conhecia não tem "
                                  "parcela neste mês")
        decisao = Decisao(guia, ALTERAR, tipo=nome, categoria=categoria,
                          obra_id=str(conhecida.get("obra") or ""),
                          trade_payable_id=tpid,
                          parcela_id=str(parcela.get("id") or ""))
        antes = valor_da_parcela(parcela)
        if antes is not None and antes != _dec(guia.valor):
            decisao.aviso = (f"a parcela está {_brl(antes)} e a guia diz "
                             f"{_brl(guia.valor)}; vale a guia")
        return decisao

    achado = titulo_igual(parcelas, guia.documento)
    if achado is not None:
        return Decisao(guia, JA_LANCADO, tipo=nome, categoria=categoria,
                       motivo="já existe título com este documento",
                       trade_payable_id=str(achado.get("tradePayableId") or ""))

    # Nada com o mesmo documento. Antes de mandar CRIAR, olhar se já existe
    # título no mesmo vencimento: o documento pode estar escrito de um jeito
    # que não reconheço (ou não estar escrito), e criar por cima é a única
    # coisa aqui que ninguém desfaz sozinho.
    parecido = titulo_parecido(parcelas, guia.valor, guia.vencimento)
    if parecido is not None:
        sem_doc = not str(guia.documento or "").strip()
        return Decisao(
            guia, DECIDIR, tipo=nome, categoria=categoria,
            motivo=("existe título com este valor e vencimento, e esta guia "
                    "não traz número de documento: confirme se é o mesmo"
                    if sem_doc else
                    "existe título neste vencimento com valor compatível, mas "
                    "com outro número de documento ("
                    + str(parecido.get("documentNumber") or "sem número")
                    + "): confirme se é o mesmo"),
            trade_payable_id=str(parecido.get("tradePayableId") or ""))

    # A regra é o que o dono já confirmou; a sugestão é palpite sobre o texto.
    # A regra ganha sempre, e o palpite viaja marcado como palpite.
    obra_id, sugerida = regras.obra(nome, guia.vip_id), False
    if not obra_id:
        obra_id = sugerir_obra(f"{guia.desc} {guia.documento}", obras)
        sugerida = bool(obra_id)
    if not obra_id:
        # Sem obra não há conta (a conta vem da obra), e sem conta não há
        # lançamento. Perguntar é a única saída honesta.
        return Decisao(guia, DECIDIR, tipo=nome, categoria=categoria,
                       motivo="não sei em que obra este documento entra")

    molde = str(tipo.get("descricao") or "{documento}")
    return Decisao(
        guia, CRIAR, tipo=nome, categoria=categoria,
        obra_id=obra_id, obra_sugerida=sugerida,
        favorecido=str(tipo.get("favorecido") or ""),
        descricao=molde.format(documento=guia.documento,
                               competencia=competencia, desc=guia.desc),
        parcelas=int(tipo.get("parcelas") or 1))
