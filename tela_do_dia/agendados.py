# -*- coding: utf-8 -*-
"""Passo 6 ("Marcar agendados") e "Agendados a confirmar" — sem tela.

Regra do dono: tudo que foi marcado como agendado fica até o dono responder
(pago, não saiu com motivo, reagendado), no mesmo dia ou depois. O app
PRÉ-MARCA só o que prova — baixa no ERP (inteira, ou parcial batendo ao
centavo com o valor agendado) ou retorno do banco "ok" — e título que SUMIU do
ERP ou MUDOU de valor nunca se resolve sozinho: mostra a foto de quando foi
agendado ("era R$ X, agora R$ Y") e espera. Pré-marcar não é responder: a
resposta é sempre um clique do dono (`nuvem.pagamentos_do_dia.responder`).

Ponto de extensão: a prova "comprovante baixado" ainda não existe. Quando
existir, chega por `situacao(prova_extra=)`; nesta entrega ninguém a passa, e
mesmo passada ela nunca vence "sumiu" nem "mudou".

Remarcar no mesmo dia: o índice único (dia, alvo) da nuvem recusa marcar o
mesmo pagamento duas vezes no mesmo dia (a nuvem devolve essas linhas como
"repetidas"). Remarcar é responder "reagendado" com a data de hoje — por isso
`validar_resposta` aceita nova data = hoje, e `recado_das_repetidas` diz isso.

O app não manda `quem`/`quem_nome`/`quando`: o servidor carimba.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from pagamentos_dia import relatorio

from .valores import CENTAVO, brl, de_float

FINAIS = ("pago", "nao_saiu")
RESPOSTAS = ("pago", "nao_saiu", "reagendado")
FOLGA_DIAS = 31
PROVA_BAIXA, PROVA_BAIXA_PARCIAL, PROVA_RETORNO = (
    "baixa no ERP", "baixa parcial no ERP", "retorno do banco")
#: Quantos favorecidos o recado das repetidas cita pelo nome.
_CITADOS = 5


def _dinheiro(v) -> Decimal | None:
    if v in (None, "") or isinstance(v, bool):
        return None
    try:
        return Decimal(str(v).strip()).quantize(CENTAVO)
    except (InvalidOperation, ValueError):
        return None


def _data(v) -> date | None:
    return relatorio.para_data(v) if v else None


@dataclass(frozen=True)
class Agendado:
    id: int
    dia: date
    conta: str
    alvo: str
    lancamento_id: str
    favorecido: str
    valor: Decimal
    descricao: str = ""
    tipo: str = ""
    foto: dict = field(default_factory=dict)
    quem_nome: str = ""

    @classmethod
    def de_linha(cls, linha: dict) -> "Agendado":
        valor, dia = _dinheiro(linha.get("valor")), _data(linha.get("dia"))
        if valor is None or dia is None:
            # Linha da nuvem sem valor ou sem dia não vira agendado "de R$ 0":
            # levanta, e a tela diz que não leu a nuvem (falha fechada).
            raise ValueError(f"agendado {linha.get('id')!r} sem valor ou dia legível")
        return cls(id=int(linha["id"]), dia=dia, conta=str(linha.get("conta") or ""),
                   alvo=str(linha.get("alvo") or ""), lancamento_id=str(linha.get("lancamento_id") or ""),
                   favorecido=str(linha.get("favorecido") or ""), valor=valor,
                   descricao=str(linha.get("descricao") or ""), tipo=str(linha.get("tipo") or ""),
                   foto=dict(linha.get("foto") or {}), quem_nome=str(linha.get("quem_nome") or ""))


@dataclass(frozen=True)
class Resposta:
    id: int
    agendado_id: int
    resposta: str
    motivo: str = ""
    nova_data: date | None = None
    prova: str = ""
    quem_nome: str = ""
    quando: str = ""

    @classmethod
    def de_linha(cls, linha: dict) -> "Resposta":
        return cls(id=int(linha["id"]), agendado_id=int(linha["agendado_id"]),
                   resposta=str(linha["resposta"]), motivo=str(linha.get("motivo") or ""),
                   nova_data=_data(linha.get("nova_data")), prova=str(linha.get("prova") or ""),
                   quem_nome=str(linha.get("quem_nome") or ""), quando=str(linha.get("quando") or ""))


@dataclass(frozen=True)
class Situacao:
    tag: str
    frase: str
    pre_marca: bool = False
    prova: str = ""


def ultima_resposta(respostas) -> dict[int, Resposta]:
    """A última resposta de cada agendado, pelo id (ordem de gravação)."""
    ult: dict[int, Resposta] = {}
    for r in sorted(respostas, key=lambda r: r.id):
        ult[r.agendado_id] = r
    return ult


def pendentes(agendados, respostas) -> list[Agendado]:
    """Os que ainda esperam o dono: sem resposta, ou com a última não final
    ("reagendado"). Mesma regra da view `agendado_em_aberto`."""
    ult = ultima_resposta(respostas)
    return [a for a in sorted(agendados, key=lambda a: (a.dia, a.id))
            if a.id not in ult or ult[a.id].resposta not in FINAIS]


def situacao(ag, titulo, envio=None, *, relido=True, prova_extra="") -> Situacao:
    """O que a tela mostra para um pendente. `titulo` = o item do ERP relido
    (None = não está na releitura); `envio` = o `Envio` da remessa (pode ser
    None); `relido=False` = a releitura do ERP não aconteceu, e aí ausência
    não é "sumiu"."""
    pago_no_banco = getattr(envio, "retorno_estado", "") == "ok"
    # Lançamento dividido em N boletos (entrega 5): o "ok" do retorno é de UM
    # envio e não diz que todas as partes saíram — só a baixa no ERP prova.
    if len(ag.foto.get("partes") or ()) > 1:
        pago_no_banco = False
    if not ag.lancamento_id:
        if prova_extra:
            return Situacao("ok", prova_extra, True, prova_extra)
        return Situacao("atencao", "pagamento à mão sem lançamento no ERP — responda")
    if not relido:
        return Situacao("atencao", "não reli o título no ERP — responda")
    if titulo is None:
        extra = " · o retorno do banco diz pago" if pago_no_banco else ""
        return Situacao("erro", f"título sumiu do ERP — era {brl(ag.valor)}, "
                                f"favorecido {ag.favorecido or '?'}{extra}")
    if titulo.get("paid") or titulo.get("markedAsPaid"):
        return Situacao("ok", "pago no ERP (baixa)", True, PROVA_BAIXA)
    if titulo.get("remainingValue") is None:
        return Situacao("atencao", "o ERP não disse o valor em aberto — responda")
    agora = de_float(titulo.get("remainingValue"))
    if agora == 0:
        # Zerado sem `paid`/`markedAsPaid`: pode ser baixa, pode ser título
        # mexido. Não prova nada, nem com retorno "ok".
        return Situacao("atencao", "baixa sem confirmação — responda")
    antes = _dinheiro(ag.foto.get("em_aberto"))
    if antes is None:
        # Sem a foto não há como saber se o valor mudou: nada se prova.
        return Situacao("atencao", "sem a foto do valor de quando agendou — responda")
    if ag.valor < antes and agora == antes - ag.valor:
        return Situacao("ok", f"baixa parcial no ERP ({brl(antes)} → {brl(agora)})", True,
                        PROVA_BAIXA_PARCIAL)
    if agora != antes:
        return Situacao("erro", f"valor mudou no ERP — era {brl(antes)}, agora {brl(agora)}")
    if pago_no_banco:
        return Situacao("ok", "o retorno do banco diz pago", True, PROVA_RETORNO)
    if prova_extra:
        return Situacao("ok", prova_extra, True, prova_extra)
    return Situacao("", "aguardando — responda")


def intervalo_de_releitura(pend, hoje) -> tuple[date, date] | None:
    """O período a reler no ERP para achar os títulos dos pendentes: do
    vencimento mais antigo (com folga) até hoje + folga. None = nenhum tem
    lançamento (só à mão sem link): não há o que reler."""
    datas = [_data(a.foto.get("vencimento")) or a.dia for a in pend if a.lancamento_id]
    if not datas:
        return None
    folga = timedelta(days=FOLGA_DIAS)
    return min(datas) - folga, max(hoje, max(datas)) + folga


@dataclass
class ParaMarcar:
    alvo: str
    conta: str
    rotulo: str
    lancamento_id: str
    a_mao_id: int | None
    favorecido: str
    valor: Decimal
    descricao: str
    tipo: str
    foto: dict
    marcado: bool = True
    ja_marcado: bool = False


def foto_do_lancamento(item: dict, valor: Decimal) -> dict:
    """O que se guarda do título na hora de agendar, para comparar depois.
    Sem o item (ou sem `remainingValue`), `em_aberto` fica "" — sem foto, e
    `situacao` nunca pré-marca esse agendado. `valor` fica na assinatura por
    compatibilidade."""
    item = item or {}
    venc = relatorio.data_do_item(item) if item else None
    em_aberto = (str(de_float(item["remainingValue"])) if item.get("remainingValue") is not None
                 else "")
    return {"em_aberto": em_aberto, "vencimento": venc.isoformat() if venc else "",
            "favorecido": str(item.get("paidTo") or ""),
            "titulo": str(item.get("tradePayableId") or "")}


def dados_do_html(resultado) -> dict:
    """{id do lançamento (ou "<id>#mao:<n>" do à mão): {"linha", "dado",
    "descricao_colada"}} do `Resultado` que vai ao HTML: o que o dono COLA
    no banco. É o que o "Autenticar no banco" procura nos comprovantes
    (`autenticar`): o código de barras e a descrição colada. Lançamento
    dividido fica com a 1ª parte aqui; as linhas de cada parte já vão em
    `foto["partes"]`."""
    from pagamentos_dia.html_pagamentos import dado_para_colar, descricao_para_colar
    saida: dict[str, dict] = {}
    for nome, regs in (getattr(resultado, "contas", None) or {}).items():
        for r in regs or ():
            id_ = str(r.get("id") or "")
            a_mao = str(r.get("a_mao") or "")
            chave = (f"{id_}#{a_mao}" if id_ else a_mao) if a_mao else id_
            if not chave or chave in saida:
                continue
            tipo = str(r.get("tipo") or "")
            dado = dado_para_colar(tipo, r.get("dados"))
            saida[chave] = {"linha": dado if tipo == "Boleto" else "",
                            "dado": dado,
                            "descricao_colada": descricao_para_colar(r, nome)}
    return saida


def para_marcar(painel, fora, lancamentos, conferencia, ja_marcados,
                do_html=None) -> list[ParaMarcar]:
    """O que sai hoje (os `saem` de cada conta), na ordem do painel e depois
    os de fora. Nasce marcado; o já marcado hoje (`ja_marcados`, os alvos de
    `agendados_do_dia`) nasce desmarcado e não vai de novo. `do_html`
    (`dados_do_html`): a linha digitável e a descrição colada de cada um,
    guardadas na foto para o "Autenticar no banco"."""
    do_html = do_html or {}
    por_id = {str(i.get("id")): i for i in lancamentos or () if i.get("id")}
    a_mao = {p.alvo: p for p in conferencia.a_mao} if conferencia is not None else {}
    saida = []
    #: Lançamento dividido em N boletos (entrega 5): o índice único da nuvem
    #: é (dia, alvo), então vira UM agendado com a SOMA das partes que saem e
    #: a lista delas na foto (`foto["partes"]`: linha e valor de cada uma).
    divididos: dict[str, ParaMarcar] = {}
    for c in [*sorted(painel.values(), key=lambda c: c.linha), *fora]:
        for p in c.saem:
            if p.valor is None or p.valor <= 0:
                continue        # a constraint valor > 0 recusaria o lote inteiro
            parte = {"parte_linha": getattr(p, "parte_linha", "") or "", "valor": str(p.valor)}
            if getattr(p, "parte", "") and p.id in divididos:
                junto = divididos[p.id]
                junto.valor += p.valor
                junto.foto["partes"].append(parte)
                continue
            m = a_mao.get(p.id)
            if m is not None:
                item = ParaMarcar(p.id, m.conta, c.rotulo, m.lancamento_id, m.id, p.favorecido,
                                  p.valor, m.descricao, m.tipo,
                                  {"a_mao": True, "vencimento": "",
                                   "em_aberto": "" if m.valor_em_aberto is None else str(m.valor_em_aberto)})
            else:
                lanc = por_id.get(p.id) or {}
                item = ParaMarcar(p.id, p.conta_erp, c.rotulo, p.id, None, p.favorecido, p.valor,
                                  str(lanc.get("description") or "")[:200],
                                  str(lanc.get("tradePayablePaymentMethod") or ""),
                                  foto_do_lancamento(lanc, p.valor))
            # A mesma chave do HTML: à mão é "<lançamento>#<alvo>" (ou só o alvo).
            chave = (f"{m.lancamento_id}#{p.id}" if m.lancamento_id else p.id) if m else p.id
            extra = do_html.get(chave)
            if extra:
                item.foto = {**item.foto, **{k: v for k, v in extra.items() if v}}
            item.ja_marcado = p.id in ja_marcados
            item.marcado = not item.ja_marcado
            if getattr(p, "parte", "") and m is None:
                item.foto = {**item.foto, "partes": [parte]}
                divididos[p.id] = item
            saida.append(item)
    return saida


def linhas_para_nuvem(itens) -> list[dict]:
    """As linhas de `DiaNaNuvem.marcar_agendados`: só as marcadas e não
    marcadas antes. Sem `dia` (a nuvem põe) e sem carimbo (o servidor põe)."""
    return [{"conta": i.conta, "alvo": i.alvo, "lancamento_id": i.lancamento_id,
             "a_mao_id": i.a_mao_id, "favorecido": i.favorecido, "valor": str(i.valor),
             "descricao": i.descricao, "tipo": i.tipo, "foto": i.foto}
            for i in itens if i.marcado and not i.ja_marcado]


def recado_das_repetidas(repetidas) -> str:
    """O recado da tela para as linhas que a nuvem devolveu como já marcadas
    hoje (o índice único recusou). "" quando não há nenhuma."""
    if not repetidas:
        return ""
    nomes = []
    for r in list(repetidas)[:_CITADOS]:
        valor = _dinheiro(r.get("valor"))
        nome = str(r.get("favorecido") or r.get("alvo") or "?")
        nomes.append(f"{nome} {brl(valor)}" if valor is not None else nome)
    if len(repetidas) > _CITADOS:
        nomes.append(f"e mais {len(repetidas) - _CITADOS}")
    n = len(repetidas)
    cabeca = ("1 pagamento já estava marcado hoje" if n == 1
              else f"{n} pagamentos já estavam marcados hoje")
    return (f"{cabeca} (nesta ou em outra máquina): {'; '.join(nomes)}. "
            "Não se marca o mesmo pagamento duas vezes no mesmo dia. Para remarcar, "
            'responda "reagendado" com a data de hoje em "Agendados a confirmar".')


def validar_resposta(resposta, motivo, nova_data, hoje) -> str:
    """"" = pode gravar. As mesmas regras das constraints de
    `agendado_resposta`, mais a data: reagendar é para hoje ou depois (hoje
    = remarcar no mesmo dia)."""
    if resposta not in RESPOSTAS:
        return f"Resposta desconhecida: {resposta}."
    if resposta == "nao_saiu" and len((motivo or "").strip()) < 3:
        return "Diga o motivo de não ter saído (3 letras ou mais)."
    if len((motivo or "").strip()) > 200:
        return "O motivo passa de 200 letras; encurte."
    if resposta == "reagendado" and (nova_data is None or nova_data < hoje):
        return "Diga a nova data (hoje ou depois)."
    return ""
