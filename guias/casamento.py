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


#: Piso para casar documento pelos dígitos. É a mesma régua de
#: `guias/leitura._linha_digitavel`: 47 dígitos no boleto bancário, 48 na ficha
#: de arrecadação.
PISO_DE_DIGITOS = 20


def vencimento_da(guia):
    """O vencimento do PDF ou, na falta dele, o do portal.

    A ficha de arrecadação não traz vencimento no código de barras, então para
    FGTS, INSS e contribuição o do PDF costuma vir vazio — e é justamente onde
    o vencimento decide tudo: qual parcela da recorrência é esta guia, e se já
    existe título no dia. `guias/lancar.criar` já lê o par nesta ordem; ao ALTERAR ele usa só o do PDF e cai na data da parcela.
    """
    return guia.vencimento or guia.vencimento_portal


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

    O piso é o tamanho do caso REAL, e não um número de conveniência: quem
    motiva a comparação por dígitos é a linha digitável, que tem 47 ou 48
    deles dos dois lados. Um piso baixo compraria falso positivo de graça
    ("123456" com "NF 123456", "092026" com "09/2026"), e o preço dos dois
    erros é muito diferente: não reconhecer vira uma pergunta na lista;
    reconhecer errado vira JA_LANCADO, a linha sai da lista de trabalho e a
    conta NUNCA é criada — e conta que não existe ninguém vê.
    """
    ta = util.norm_espaco(str(a or "")).upper()
    tb = util.norm_espaco(str(b or "")).upper()
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    da, db = _digitos(ta), _digitos(tb)
    return len(da) >= PISO_DE_DIGITOS and da == db


def _data_de(parcela: dict):
    try:
        return date.fromisoformat(str(parcela.get("plannedDate") or "")[:10])
    except ValueError:
        return None


def _mesmo_mes(parcela: dict, vencimento) -> bool:
    d = _data_de(parcela)
    return d is not None and (d.year, d.month) == (vencimento.year,
                                                   vencimento.month)


def parcela_da_recorrencia(parcelas: list[dict], trade_payable_id: str,
                           vencimento=None) -> tuple[dict | None, str]:
    """(parcela, dúvida) — a parcela desta recorrência no vencimento da guia.

    A janela de leitura cobre dois meses de propósito (guia de competência 09
    que vence em outubro tem o título em outubro), e recorrência mensal tem uma
    parcela em cada um. Escolher a errada é alterar o título do mês errado — e
    o mês errado já pode estar pago, ou passa a pedir o valor do outro.

    O MÊS do vencimento é filtro, não desempate. Como desempate ele respondia
    coisas opostas para o mesmo formato de dado: recusava a parcela única de
    outro mês e aceitava, sem perguntar, a mais próxima entre duas quando
    nenhuma era do mês — justamente o caso com MAIS ambiguidade. A distância só
    entra para escolher entre as que já são do mês certo.

    E ela não chuta: quando não dá para saber qual é, devolve a dúvida escrita,
    e quem chama transforma isso em pergunta.
    """
    candidatas = [p for p in parcelas or []
                  if str(p.get("tradePayableId") or "") == str(trade_payable_id)]
    if not candidatas:
        return None, "a recorrência que eu conhecia não tem parcela na janela"
    if vencimento is None:
        if len(candidatas) == 1:
            return candidatas[0], ""
        # Não é caso raro: a ficha de arrecadação — FGTS, INSS/IRRF,
        # contribuição — não carrega vencimento no código de barras.
        return None, ("não consegui ler o vencimento desta guia, e a "
                      "recorrência tem parcela em mais de um mês: qual delas "
                      "é esta guia?")

    sem_data = [p for p in candidatas if _data_de(p) is None]
    no_mes = [p for p in candidatas if _mesmo_mes(p, vencimento)]
    if not no_mes:
        if sem_data:
            # "De outro mês" seria afirmar sobre um dado que eu não li, e o
            # dono iria ao ERP procurar uma diferença de mês que não existe.
            return None, ("não consegui ler a data de uma parcela desta "
                          "recorrência: qual delas é esta guia?")
        return None, ("a recorrência não tem parcela no mês do vencimento "
                      "desta guia: é alguma destas?")
    if len(no_mes) == 1:
        return no_mes[0], ""

    def _distancia(p):
        return abs((_data_de(p) - vencimento).days)

    ordenadas = sorted(no_mes, key=_distancia)
    if _distancia(ordenadas[0]) == _distancia(ordenadas[1]):
        return None, ("a recorrência tem duas parcelas à mesma distância do "
                      "vencimento desta guia: qual delas é ela?")
    return ordenadas[0], ""


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


#: Quanto os dois valores podem divergir e ainda serem a mesma conta.
#:
#: Os dois lados, porque o acréscimo aparece ora num ora noutro: em título já
#: pago, `sumOfPaidValues` traz o que SAIU, com multa e juros, e o título fica
#: MAIOR que a guia; em título em aberto o cadastro está pelo nominal e quem
#: carrega o acréscimo é a GUIA, reimpressa com o valor do dia — aí o título
#: fica MENOR. Uma faixa só para cima deixava um título um centavo mais barato
#: passar direto para CRIAR, que é o erro caro.
#:
#: Metade é o bastante: multa e juros de uma guia com um ou dois meses de
#: atraso não chegam lá, e parar aqui evita casar a guia com um título grande
#: que só coincide na data.
TETO = Decimal("1.5")


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
    perto = []
    for p in parcelas or []:
        if str(p.get("plannedDate") or "")[:10] != data:
            continue
        v = valor_da_parcela(p)
        if v is not None and v > 0 and max(alvo, v) <= min(alvo, v) * TETO:
            perto.append((abs(v - alvo), p))
    if not perto:
        return None
    # O MAIS PRÓXIMO em valor, e não o primeiro que a lista trouxer: quem lê
    # esta resposta pergunta ao dono "é este?" e abre o título no ERP. Apontar
    # para um alheio que só cabe na faixa faz o dono responder "não é" olhando
    # o título errado — e o certo fica lá, convidando o lançamento à mão.
    return min(perto, key=lambda par: par[0])[1]


def quantos_parecidos(parcelas: list[dict], valor, vencimento) -> int:
    """Quantos títulos cabem na pergunta. Mais de um e a pergunta tem de dizer
    isso: apontar um só faria o dono responder olhando metade do caso."""
    alvo, data = _dec(valor), (vencimento.isoformat() if vencimento else "")
    if alvo is None or not data:
        return 0
    n = 0
    for p in parcelas or []:
        if str(p.get("plannedDate") or "")[:10] != data:
            continue
        v = valor_da_parcela(p)
        if v is not None and v > 0 and max(alvo, v) <= min(alvo, v) * TETO:
            n += 1
    return n


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
        parcela, duvida = parcela_da_recorrencia(parcelas, tpid,
                                                 vencimento_da(guia))
        if parcela is None:
            return Decisao(guia, DECIDIR, tipo=nome, categoria=categoria,
                           motivo=duvida)
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
                       trade_payable_id=str(achado.get("tradePayableId") or ""),
                       parcela_id=str(achado.get("id") or ""))

    # Nada com o mesmo documento. Antes de mandar CRIAR, olhar se já existe
    # título no mesmo vencimento: o documento pode estar escrito de um jeito
    # que não reconheço (ou não estar escrito), e criar por cima é a única
    # coisa aqui que ninguém desfaz sozinho.
    # Vale para TODA guia, com documento ou sem. Cheguei a tentar isentar o
    # "rótulo de gente, sem dígito nenhum" — e era conceito morto: o número da
    # guia só nasce em `guias/leitura`, onde os dois caminhos (linha digitável
    # e `RE_DOCUMENTO`) começam por dígito. A isenção não era alcançável e o
    # único teste que a guardava usava uma entrada que o leitor não produz.
    parecido = titulo_parecido(parcelas, guia.valor, vencimento_da(guia))
    if parecido is not None:
        sem_doc = not str(guia.documento or "").strip()
        quantos = quantos_parecidos(parcelas, guia.valor, vencimento_da(guia))
        # Dois títulos com o mesmo valor no mesmo dia acontecem (a mesma guia
        # lançada duas vezes à mão, dois impostos iguais). Apontar um e calar
        # sobre o outro faria o dono responder olhando metade do caso.
        mais = f" (e mais {quantos - 1} neste dia)" if quantos > 1 else ""
        return Decisao(
            guia, DECIDIR, tipo=nome, categoria=categoria,
            motivo=("existe título com este valor e vencimento" + mais +
                    ", e esta guia não traz número de documento: confirme se "
                    "é o mesmo"
                    if sem_doc else
                    "existe título neste vencimento com valor compatível, mas "
                    "com outro número de documento ("
                    + str(parecido.get("documentNumber") or "sem número")
                    + ")" + mais + ": confirme se é o mesmo"),
            trade_payable_id=str(parecido.get("tradePayableId") or ""),
            parcela_id=str(parecido.get("id") or ""))

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
