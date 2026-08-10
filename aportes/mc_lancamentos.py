# -*- coding: utf-8 -*-
"""
Cria lançamentos de aporte/distribuição direto no Mais Controle.

Substitui o caminho antigo — gerar duas planilhas e importar na mão — pelas
mesmas chamadas que a tela "Novo Lançamento" faz. A diferença que importa:
a importação casa tudo por TEXTO e trava em "Validando Arquivo" sem dizer
qual linha errou; aqui vai UUID em todo campo, resolvido e conferido ANTES
de qualquer envio.

Formato das chamadas levantado por captura de tráfego do próprio ERP;
documentado no repositório privado do projeto de aportes.

Sem dado da empresa neste arquivo — o repositório é público.
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass, field

LEGACY = "https://legacy-api.maiscontroleerp.com.br/maiscontrole/services"

# "Quem Paga" — sempre Cliente nos nossos lançamentos. É o valor que faz o ERP
# oferecer todas as contas, não só as da unidade.
QUEM_PAGA = "CLIENT"


class ErroLancamento(RuntimeError):
    """Falha ao criar um lançamento. A mensagem é para o usuário final ler."""


@dataclass
class Resultado:
    ok: bool
    descricao: str
    tipo: str                      # "pagamento" | "recebimento"
    id_criado: str | None = None
    erro: str | None = None
    detalhes: dict = field(default_factory=dict)


def _exigir(valor, o_que: str, procurado: str, catalogos=None, onde=None):
    """Traduz 'não achei' em recado útil, com sugestão de nome parecido.

    Vale a pena porque o motivo real quase sempre é acento, abreviação ou uma
    conta que simplesmente não existe no ERP — e o ERP, pela tela, oferece
    criar na hora; pela API, não. Sem esta mensagem o usuário só veria falhar."""
    if valor:
        return valor
    recado = f'{o_que} não encontrado no Mais Controle: "{procurado}"'
    if catalogos and onde:
        parecidos = catalogos.parecidos(procurado, onde)
        if parecidos:
            recado += ". Parecido(s) no ERP: " + ", ".join(f'"{p}"' for p in parecidos)
        else:
            recado += ". Nada parecido no cadastro — talvez precise ser criado lá."
    raise ErroLancamento(recado)


def _agora() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S")


def _iso(data: datetime.date) -> str:
    return data.strftime("%Y-%m-%d")


def criar_pagamento(
    catalogos,
    *,
    data: datetime.date,
    valor: float,
    descricao: str,
    conta_pagadora: str,
    favorecido: str,
    categoria: str,
    forma: str,
    obra: str,
    id_usuario: str,
) -> Resultado:
    """POST /trade-payables — pagamento já marcado como pago na data."""
    conta = _exigir(catalogos.conta(conta_pagadora), "Conta bancária",
                    conta_pagadora, catalogos, "contas")
    participante = _exigir(catalogos.participante(favorecido),
                           "Favorecido", favorecido, catalogos, "participantes")
    cat = _exigir(catalogos.categoria(categoria), "Categoria",
                  categoria, catalogos, "categorias")
    metodo = _exigir(catalogos.forma_pagamento(forma), "Forma de pagamento",
                     forma, catalogos, "formas_pagamento")
    trabalho = _exigir(catalogos.obra(obra), "Obra", obra, catalogos, "obras")
    condicao = _exigir(catalogos.condicao_a_vista_pagamento(),
                       "Condição de pagamento à vista", "À Vista")

    corpo = {
        "paymentCondition": {"id": condicao["id"], "type": "IN_CASH",
                             "financing": False, "recurring": False},
        "installments": [{"plannedDate": _iso(data), "plannedValue": valor,
                          "markedAsPaid": False}],
        "numberOfInstallments": 1,
        "responsible": {"id": id_usuario},
        "value": valor,
        "description": descricao,
        "participant": {"id": participante["id"]},
        "referenceDate": _iso(data),
        "date": _agora(),
        "category": {"id": cat["id"]},
        "whoPays": QUEM_PAGA,
        "costCentreType": "WORK",
        # percentage 100 numa obra só. É aqui que caberia um rateio real por
        # obra, se um dia substituir a expansão em várias linhas da planilha.
        "costCentreDetails": [{
            "value": valor, "percentage": 100,
            "work": {"id": trabalho["id"], "name": trabalho.get("name"),
                     "status": trabalho.get("status", "IN_PROGRESS"),
                     "__typename": "Work"},
        }],
        "paymentMethod": {"id": metodo["id"]},
        "numberPrecision": 2,
        "markedAsPaid": True,
        "markedPayingDate": _iso(data),
        "account": {"id": conta["id"], "name": conta.get("name"),
                    "openingBalanceDate": conta.get("openingBalanceDate")},
        "freightageValue": 0, "otherValue": 0, "ipiValue": 0, "discountValue": 0,
        "_saveAndAddNew": False,
    }

    resposta = catalogos.postar(
        f"{LEGACY}/trade-payables?userApprovesSaleCreation=true", corpo)
    if isinstance(resposta, dict) and resposta.get("__erro"):
        return Resultado(False, descricao, "pagamento",
                         erro=f"o ERP recusou (HTTP {resposta['__erro']})",
                         detalhes=resposta.get("__corpo") or {})
    return Resultado(True, descricao, "pagamento",
                     id_criado=(resposta or {}).get("id"))


def criar_recebimento(
    catalogos,
    *,
    data: datetime.date,
    valor: float,
    descricao: str,
    conta_recebedora: str,
    cliente: str,
    natureza: str,
    forma: str,
    obra: str,
    id_usuario: str,
    nome_usuario: str = "",
) -> Resultado:
    """POST /sales e, em seguida, a baixa em /receipt-installments/{id}/receipts.

    São duas chamadas porque a venda nasce em aberto: sem a segunda, o
    recebimento aparece como previsto e não como recebido."""
    conta = _exigir(catalogos.conta(conta_recebedora), "Conta bancária",
                    conta_recebedora, catalogos, "contas")
    participante = _exigir(catalogos.participante(cliente), "Cliente",
                           cliente, catalogos, "participantes")
    nat = _exigir(catalogos.natureza(natureza), "Natureza",
                  natureza, catalogos, "naturezas")
    metodo = _exigir(catalogos.forma_recebimento(forma), "Forma de recebimento",
                     forma, catalogos, "formas_recebimento")
    trabalho = _exigir(catalogos.obra(obra), "Obra", obra, catalogos, "obras")
    condicao = _exigir(catalogos.condicao_a_vista_recebimento(),
                       "Condição de recebimento à vista", "À Vista")

    corpo = {
        "date": _agora(),
        "interestRateAccumulateStrategy": "SIMPLE",
        "work": {"id": trabalho["id"], "name": trabalho.get("name")},
        "customer": {"id": participante["id"], "name": ""},
        "description": descricao,
        "tradeReceivable": {
            "grossValue": valor, "taxWithhold": 0, "value": valor,
            "referenceDate": _iso(data),
            "numberOfInstallments": 1,
            "receivingCondition": {"id": condicao["id"], "deferred": False},
            "nature": {"id": nat["id"], "name": nat.get("name")},
            "defaultAccount": {"id": conta["id"], "name": conta.get("name"),
                               "openingBalanceDate": conta.get("openingBalanceDate")},
            "defaultReceivingMethod": {"id": metodo["id"]},
            "responsible": {"id": id_usuario, "name": nome_usuario,
                            "person": {"name": nome_usuario}},
            "installments": [{"plannedValue": valor, "plannedDate": _iso(data),
                              "receipts": [], "billings": [],
                              "withholdType": None}],
            "isReceived": True,
            "receivingDate": _iso(data),
        },
        "withholds": [],
    }

    resposta = catalogos.postar(f"{LEGACY}/sales", corpo)
    if isinstance(resposta, dict) and resposta.get("__erro"):
        return Resultado(False, descricao, "recebimento",
                         erro=f"o ERP recusou (HTTP {resposta['__erro']})",
                         detalhes=resposta.get("__corpo") or {})

    # A baixa pode já ter acontecido: o próprio POST /sales leva
    # isReceived=true e receivingDate. Se ela já veio feita, chamar o endpoint
    # de baixa DE NOVO lançaria a entrada duas vezes — R$ 2,00 no lugar de
    # R$ 1,00. Por isso conferimos antes em vez de sempre chamar.
    parcela = _achar_parcela(resposta)
    if parcela and _ja_baixada(parcela):
        return Resultado(True, descricao, "recebimento",
                         id_criado=(resposta or {}).get("id"),
                         detalhes={"baixa": "já veio feita no próprio lançamento"})

    id_parcela = (parcela or {}).get("id")
    if not id_parcela:
        # A venda existe, mas ficou EM ABERTO. Avisar é obrigatório: silenciar
        # deixaria o usuário achando que o dinheiro entrou.
        return Resultado(
            False, descricao, "recebimento",
            id_criado=(resposta or {}).get("id"),
            erro="recebimento criado, mas NÃO foi possível dar a baixa "
                 "(não achei a parcela na resposta). Confira no ERP.")

    baixa = catalogos.postar(
        f"{LEGACY}/receipt-installments/{id_parcela}/receipts",
        {"value": valor, "receivedValue": valor, "receivingDate": _iso(data),
         "account": {"id": conta["id"]}, "responsible": {"id": id_usuario}})
    if isinstance(baixa, dict) and baixa.get("__erro"):
        return Resultado(
            False, descricao, "recebimento", id_criado=(resposta or {}).get("id"),
            erro=f"recebimento criado, mas a baixa falhou (HTTP {baixa['__erro']}). "
                 "Ele está em aberto no ERP.")
    return Resultado(True, descricao, "recebimento",
                     id_criado=(resposta or {}).get("id"))


def _achar_parcela(resposta) -> dict | None:
    """A primeira parcela dentro da resposta da venda.

    O caminho exato não foi confirmado por captura (a resposta do POST /sales
    não chegou a ser gravada), então procuramos em vez de fixar um caminho que
    poderia não existir e falhar em silêncio."""
    if not isinstance(resposta, dict):
        return None
    for caminho in (("tradeReceivable", "installments"), ("installments",)):
        no = resposta
        for parte in caminho:
            no = (no or {}).get(parte) if isinstance(no, dict) else None
        if isinstance(no, list) and no and isinstance(no[0], dict) and no[0].get("id"):
            return no[0]

    # Varredura geral, para o caso de a resposta mudar de formato. Uma parcela
    # se reconhece por ter id e algum campo "planned...".
    pilha = [resposta]
    while pilha:
        atual = pilha.pop()
        if isinstance(atual, dict):
            if atual.get("id") and any("planned" in k.lower() for k in atual):
                return atual
            pilha.extend(atual.values())
        elif isinstance(atual, list):
            pilha.extend(atual)
    return None


def _ja_baixada(parcela: dict) -> bool:
    """A parcela já nasceu recebida?

    Conservador de propósito: na dúvida devolve False e a baixa é tentada. Um
    erro para o lado do "não baixou" deixa o lançamento em aberto, visível e
    fácil de corrigir; para o outro lado, duplicaria a entrada de dinheiro."""
    if not isinstance(parcela, dict):
        return False
    recebimentos = parcela.get("receipts")
    if isinstance(recebimentos, list) and recebimentos:
        return True
    for campo in ("isReceived", "received", "settled"):
        if parcela.get(campo) is True:
            return True
    return False
