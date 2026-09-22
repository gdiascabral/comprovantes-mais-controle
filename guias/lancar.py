# -*- coding: utf-8 -*-
"""Grava a guia no Mais Controle: altera a parcela da recorrência, ou cria.

Tudo pela API, de dentro da página logada (`erp/pagina.py`). Um
`POST /users/login` por HTTP derrubaria a sessão do dono — o ERP aceita uma
por usuário.

Três regras que não se negociam aqui:

1. **Backup antes do PUT.** O objeto que vai ser trocado é gravado em disco
   primeiro. Sem isso, uma alteração errada não tem volta.
2. **Releitura depois de gravar.** O que o ERP diz ter guardado é comparado
   campo a campo com o que foi pedido. Não batendo, o desfecho é DIVERGE.
3. **O anexo só é "anexado" com a listagem provando.** E o POST do batch nunca
   se repete: batch reenviado é um segundo registro de anexo no mesmo título.
"""
from __future__ import annotations

import calendar
import datetime as dt
import json
import re
from decimal import Decimal
from pathlib import Path

import util
from anexar.mc_api import primeira_url_s3
from erp import hosts
from guias.modelos import (ALTERADO, ANEXO_PENDENTE, CRIADO, DIVERGE, ERRO,
                           Resultado)

log = util.log(__name__)

#: "Quem paga" nos nossos lançamentos, como nos aportes.
QUEM_PAGA = "CLIENT"


def _num(valor) -> float:
    """Decimal -> float SÓ na fronteira do JSON (a conta é feita em Decimal)."""
    return float(Decimal(str(valor)).quantize(Decimal("0.01")))


def _erro_de(resposta) -> str:
    if isinstance(resposta, dict) and resposta.get("__erro"):
        return f"o ERP recusou (HTTP {resposta['__erro']})"
    return ""


def _mesmo(a, b) -> bool:
    return abs(float(a or 0) - float(b or 0)) < 0.005


def _nome_de_arquivo(texto: str) -> str:
    """Nome de anexo sem separador de caminho.

    A descrição vem do portal do escritório e traz competência com barra
    ("HONORARIO 09/2026"). Barra e contrabarra em nome de objeto viram
    separador de caminho no armazenamento: o anexo sai com nome estranho, ou
    é recusado — e isso só apareceria na primeira rodada real.
    """
    return re.sub(r"[\\/]+", "-", str(texto or "")).strip()


# --------------------------------------------------------------- conta e obra

def referencia_da_obra(transporte, obra_id: str, parcelas) -> dict | None:
    """Conta e forma de pagamento que o ERP usaria nesta obra, lidas de um
    título que já existe nela. `None` = não há título de referência.

    A conta NÃO é escolhida por ninguém: pela tela, selecionar a obra já a
    preenche, e a equipe deixa a que vem (decisão do dono, 21/09/2026). Pela
    API ela é campo obrigatório, então o jeito de mandar a MESMA é perguntar a
    um título daquela obra. A forma de pagamento vem junto pelo mesmo motivo:
    o nome dela é cadastro de cada instalação, e escrever "Boleto" em literal
    é palpite sobre um cadastro que este código não conhece.

    Só título da obra pedida serve. Copiar a conta da obra errada produz um
    lançamento que o ERP aceita e que paga pelo lugar errado.
    """
    for p in parcelas or []:
        detalhes = p.get("costCentreDetails") or []
        obras = [str((d.get("work") or {}).get("id") or "") for d in detalhes]
        if str(obra_id) not in obras:
            continue
        tpid = str(p.get("tradePayableId") or "")
        if not tpid:
            continue
        titulo = transporte.buscar(f"{hosts.LEGACY}/trade-payables/{tpid}")
        if _erro_de(titulo):
            continue
        conta = (titulo or {}).get("account")
        if conta and conta.get("id"):
            return {"account": conta,
                    "paymentMethod": (titulo or {}).get("paymentMethod") or {}}
    return None


# ------------------------------------------------------------------- anexo

def anexar(transporte, tpid: str, pdf: Path, nome: str) -> list[str]:
    """Sobe o PDF para o TÍTULO. Devolve os nomes que a listagem de prova traz.

    Lista vazia = não provou. O chamador trata como anexo pendente — nunca
    repete o batch, que criaria um segundo registro de anexo.
    """
    dados = Path(pdf).read_bytes()
    corpo = {"entityOrigin": "TRADE_PAYABLE", "entityId": tpid,
             "attachmentsItem": [{"name": nome, "contentType": "application/pdf",
                                  "extension": "pdf", "sizeInBytes": len(dados)}]}
    resposta = transporte.postar(f"{hosts.ERP_API}/attachments/v2/batch", corpo)
    if _erro_de(resposta):
        log.warning("o batch do anexo foi recusado pelo ERP")
        return []
    url_s3 = primeira_url_s3(resposta)
    if not url_s3:
        # O nome do campo varia na resposta do batch, e é por isso que quem
        # acha a URL é a função do `anexar/mc_api.py`, provada em produção, e
        # não uma regex própria: cópia mais estreita falha sem dizer por quê.
        log.warning("o batch do anexo voltou sem URL pré-assinada")
        return []
    subida = transporte.subir(url_s3, dados)
    if int((subida or {}).get("status") or 0) >= 300:
        return []
    prova = transporte.buscar(
        f"{hosts.ERP_API}/attachments/v2?entityIds={tpid}"
        f"&entityOrigin=TRADE_PAYABLE")
    if not isinstance(prova, list):
        return []
    return [str(a.get("filename") or "") for a in prova]


def _fechar(transporte, decisao, tpid: str, estado_ok: str,
            conferido: bool) -> Resultado:
    """Anexa e devolve o desfecho. Ordem: título primeiro, anexo depois."""
    nome = _nome_de_arquivo(f"{decisao.guia.desc[:60]} "
                            f"{decisao.guia.competencia}") + ".pdf"
    anexos = anexar(transporte, tpid, decisao.guia.pdf, nome)
    if nome not in anexos:
        # A listagem traz TODOS os anexos do título, e o ALTERAR reusa o
        # mesmo título todo mês: "a lista não está vazia" prova o PDF do mês
        # passado, não este. A prova é o nome DESTE arquivo estar lá.
        return Resultado(ANEXO_PENDENTE, tpid=tpid,
                         motivo="o título está gravado; o PDF não subiu")
    return Resultado(estado_ok if conferido else DIVERGE, tpid=tpid,
                     anexos=anexos,
                     motivo="" if conferido else
                            "gravou, mas a releitura não bateu")


# ----------------------------------------------------------------- alterar

def alterar(transporte, decisao, catalogos, *, pasta_backup: Path) -> Resultado:
    tpid = decisao.trade_payable_id
    url = f"{hosts.LEGACY}/trade-payables/{tpid}"
    titulo = transporte.buscar(url)
    recusa = _erro_de(titulo)
    if recusa:
        return Resultado(ERRO, motivo=recusa)

    parcelas = [i for i in (titulo.get("installments") or [])
                if str(i.get("id")) == str(decisao.parcela_id)]
    if not parcelas:
        return Resultado(ERRO, motivo="a parcela não está mais neste título")
    parcela = parcelas[0]
    if parcela.get("paid") or parcela.get("paids"):
        return Resultado(ERRO, motivo="a parcela já tem baixa — não mexo")

    # O ERP casa a categoria pelo ID. Mandar só o nome guarda a categoria
    # VELHA sem reclamar — e a categoria velha é justamente a genérica com que
    # a recorrência nasce, que é o que esta rotina existe para corrigir.
    categoria = None
    if decisao.categoria:
        categoria = catalogos.categoria(decisao.categoria)
        if not categoria:
            return Resultado(ERRO, motivo=f"categoria não cadastrada no ERP: "
                                          f"{decisao.categoria!r}")

    pasta_backup.mkdir(parents=True, exist_ok=True)
    (pasta_backup / f"{tpid}_{decisao.parcela_id}.json").write_text(
        json.dumps(titulo, ensure_ascii=False), encoding="utf-8")

    data = decisao.guia.vencimento.isoformat() if decisao.guia.vencimento else \
        str(parcela.get("plannedDate") or "")[:10]
    valor = _num(decisao.guia.valor)

    # A descrição fica INTACTA: é o padrão da equipe ao alterar recorrência.
    # A conta e a obra também: vieram do título, e conta vem da obra.
    titulo["value"] = valor
    titulo["documentNumber"] = decisao.guia.documento
    if categoria:
        titulo["category"] = {"id": categoria["id"],
                              "name": categoria.get("name") or decisao.categoria}
    if isinstance(titulo.get("recurring"), dict):
        titulo["recurring"]["plannedDate"] = data
    for detalhe in titulo.get("costCentreDetails") or []:
        detalhe["value"] = _num(valor * float(detalhe.get("percentage") or 100) / 100)
    parcela["plannedDate"] = data
    parcela["plannedValue"] = valor

    resposta = transporte.trocar(
        f"{url}?removeAllEntryItems=false&userApprovesSaleCreation=true"
        "&updateNext=false", titulo)
    recusa = _erro_de(resposta)
    if recusa:
        return Resultado(ERRO, motivo=recusa)

    depois = transporte.buscar(url)
    conferido = False
    if not _erro_de(depois):
        nova = [i for i in (depois.get("installments") or [])
                if str(i.get("id")) == str(decisao.parcela_id)]
        categoria_ok = (not categoria or
                        str((depois.get("category") or {}).get("id") or "")
                        == str(categoria["id"]))
        conferido = bool(nova) and categoria_ok and (
            str(nova[0].get("plannedDate") or "")[:10] == data
            and _mesmo(nova[0].get("plannedValue"), valor)
            and str(depois.get("documentNumber") or "") == decisao.guia.documento)
    return _fechar(transporte, decisao, tpid, ALTERADO, conferido)


# ------------------------------------------------------------------- criar

def _parcelas_mensais(primeira, quantas: int, total) -> list[dict]:
    """`quantas` parcelas no mesmo dia dos meses seguintes. A última fecha o
    total, para a soma bater com o valor do documento."""
    valor = (Decimal(str(total)) / quantas).quantize(Decimal("0.01"))
    saida, somado = [], Decimal("0")
    for i in range(quantas):
        mes = primeira.month - 1 + i
        ano = primeira.year + mes // 12
        mes = mes % 12 + 1
        # Dia 31 não existe em todo mês: sem prender ao último dia, a 2ª
        # parcela de um vencimento em 31/03 levanta ValueError e derruba o
        # resto da rodada, sem dizer quais linhas ficaram sem lançar.
        dia = min(primeira.day, calendar.monthrange(ano, mes)[1])
        data = dt.date(ano, mes, dia)
        parte = valor if i < quantas - 1 else Decimal(str(total)) - somado
        somado += parte
        saida.append({"plannedDate": data.isoformat(), "plannedValue": _num(parte),
                      "markedAsPaid": False, "order": i})
    return saida


def criar(transporte, decisao, catalogos, *, id_usuario: str,
          referencia: dict | None, obra: dict) -> Resultado:
    # A conta é a primeira coisa conferida, e nada sai antes dela: sem o
    # título de referência da obra não há conta, e inventar uma manda o
    # pagamento sair do lugar errado.
    conta = (referencia or {}).get("account") or {}
    if not conta.get("id"):
        return Resultado(ERRO, motivo="sem título de referência nesta obra, "
                                      "não sei qual conta o ERP usaria; "
                                      "lance este pela tela do ERP")
    if not obra.get("id"):
        # `_obra_do_erp` falha FECHADO (devolve `{}`) quando a obra não está
        # no catálogo — o gatilho mais comum é a listagem de obras ter
        # falhado em silêncio na abertura da sessão. Criar título sem centro
        # de custo é pior que recusar.
        return Resultado(ERRO, motivo="não achei a obra no cadastro do ERP; "
                                      "o catálogo de obras veio vazio?")
    categoria = catalogos.categoria(decisao.categoria)
    if not categoria:
        return Resultado(ERRO, motivo=f"categoria não cadastrada no ERP: "
                                      f"{decisao.categoria!r}")
    participante = catalogos.participante(decisao.favorecido)
    if not participante:
        return Resultado(ERRO, motivo=f"favorecido não cadastrado no ERP: "
                                      f"{decisao.favorecido!r}")

    parcelado = int(decisao.parcelas or 1) > 1
    condicao = catalogos.condicao_de_pagamento(
        "FINANCING" if parcelado else "IN_CASH")
    if not condicao:
        return Resultado(ERRO, motivo="o ERP não tem a condição de pagamento "
                                      + ("parcelada" if parcelado else "à vista"))
    # O prz do portal é o segundo dado autoritativo, de graça: sem ele, uma
    # ficha de arrecadação (que não carrega vencimento no código de barras)
    # nasceria vencendo HOJE.
    primeira = (decisao.guia.vencimento or decisao.guia.vencimento_portal
                or dt.date.today())
    total = _num(decisao.guia.valor)
    parcelas = _parcelas_mensais(primeira, int(decisao.parcelas or 1), total)
    forma = (referencia or {}).get("paymentMethod") or {}

    corpo = {
        "paymentCondition": {"id": condicao["id"], "type": condicao["type"],
                             "financing": parcelado, "recurring": False},
        "installments": parcelas,
        "numberOfInstallments": len(parcelas),
        "responsible": {"id": id_usuario},
        "value": total,
        "description": decisao.descricao,
        "documentNumber": decisao.guia.documento,
        "participant": {"id": participante["id"]},
        "referenceDate": primeira.isoformat(),
        "date": dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "category": {"id": categoria["id"]},
        "whoPays": QUEM_PAGA,
        "costCentreType": "WORK",
        "costCentreDetails": [{"value": total, "percentage": 100, "work": obra}],
        "paymentMethod": {"id": forma.get("id")},
        "numberPrecision": 2,
        "markedAsPaid": False,             # é conta A PAGAR, não baixa
        "account": conta,
        "freightageValue": 0, "otherValue": 0, "ipiValue": 0, "discountValue": 0,
        "_saveAndAddNew": False,
    }
    if parcelado:
        corpo["numberOfFinancingInstallments"] = len(parcelas)

    resposta = transporte.postar(
        f"{hosts.LEGACY}/trade-payables?userApprovesSaleCreation=true", corpo)
    recusa = _erro_de(resposta)
    if recusa:
        return Resultado(ERRO, motivo=recusa)
    tpid = str((resposta or {}).get("id") or "")
    if not tpid:
        return Resultado(ERRO, motivo="o ERP respondeu sem o id do título")

    depois = transporte.buscar(f"{hosts.LEGACY}/trade-payables/{tpid}")
    conferido = False
    if not _erro_de(depois):
        criadas = sorted((str(i.get("plannedDate") or "")[:10],
                          round(float(i.get("plannedValue") or 0), 2))
                         for i in (depois.get("installments") or []))
        pedidas = sorted((p["plannedDate"], round(p["plannedValue"], 2))
                         for p in parcelas)
        # Obra e categoria entram na conferência: são o centro de custo e a
        # classificação do lançamento, e o spec exige os dois — conferir só
        # parcela, conta e documento deixaria os dois passarem sem prova.
        detalhes = depois.get("costCentreDetails") or []
        obra_ok = bool(detalhes) and str(
            (detalhes[0].get("work") or {}).get("id") or "") == str(
                obra.get("id") or "")
        categoria_ok = str((depois.get("category") or {}).get("id") or "") == \
            str(categoria["id"])
        conferido = (criadas == pedidas
                     and str((depois.get("account") or {}).get("id")) == str(conta["id"])
                     and str(depois.get("documentNumber") or "") == decisao.guia.documento
                     and obra_ok and categoria_ok)
    return _fechar(transporte, decisao, tpid, CRIADO, conferido)
