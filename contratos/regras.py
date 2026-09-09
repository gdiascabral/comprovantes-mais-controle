# -*- coding: utf-8 -*-
"""Quais casas receberam dinheiro de venda no mês.

Entra a lista crua de recebimentos do ERP, sai uma lista de IMÓVEIS. Sem
navegador e sem tkinter: roda inteiro em teste.

Até 09/09/2026 só entrava a casa cuja Condição fosse FINANCIAMENTO, porque o
escritório contábil pedia o contrato da Caixa. A apuração dos impostos passou
a ser sobre TODO recebimento, e o documento que prova cada um é o contrato de
compra e venda entre a SPE e o comprador — o mesmo para o sinal, a entrada, o
financiamento e a intermediação. Por isso aqui não se filtra mais por
Condição: toda venda recebida no mês vira uma casa na lista, e a casa carrega
os seus recebimentos, que o resumo mostra ao contábil um a um.

Três nomes da API enganam, e é por isso que eles são traduzidos logo na
entrada:

    readjustmentType  é a coluna "Condição" da tela: Sinal, Entrada,
                      1ª FINANCIAMENTO, JUROS FINANCIAMENTO, Reembolso
                      Vistoria, FGTS (as seis vistas em 20 vendas de 2026)
    workName          é o "Centro de Custo", que é o NOME da obra
    saleValue         é o valor da VENDA, não do recebimento — e é ele que se
                      procura no contrato, nunca a parcela

A igualdade entre `workName` e o `name` da obra é a ponte entre as duas metades
do trabalho (achar quem recebeu, e achar o contrato daquela obra).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal, ROUND_HALF_UP

import util

#: Condições que ainda interessam distinguir no resumo (não filtram nada).
MARCA_FINANCIAMENTO = "FINANCIAMENTO"
MARCA_JUROS = "JUROS"

#: `CASA 01`, `CS 3`, `cs1` são a grafia normal; `C12` é a curta. A curta só
#: vale quando a normal não aparece: um centro de custo como `LT 8 C 259 M 5`
#: tem um `C 259` que não é casa nenhuma, e o `CS 01` do fim é que manda.
RE_UNIDADE = re.compile(r"\b(?:CASA|CS)\s*0*(\d{1,3})\b", re.I)
RE_UNIDADE_CURTA = re.compile(r"\bC\s*0*(\d{1,3})\b", re.I)


def numero_da_unidade(texto: str) -> int | None:
    """O número da casa em `texto`, ou None.

    Aceita as quatro grafias que aparecem no cadastro real, com ou sem espaço
    e com ou sem zero à esquerda."""
    t = util.sem_acento(texto or "")
    m = RE_UNIDADE.search(t) or RE_UNIDADE_CURTA.search(t)
    return int(m.group(1)) if m else None


def rotulo_da_unidade(numero: int | None) -> str:
    """1 -> "CS 01". Dois dígitos, como no nome dos arquivos do ERP."""
    if not numero:
        return "CS ??"
    return f"CS {numero:02d}"


def partes_da_descricao(descricao: str) -> tuple[int | None, str]:
    """(unidade, comprador) de "VENDA CASA 01 - ISABELLA RENATA GONÇALVES".

    A unidade é procurada SÓ na parte antes do primeiro " - ". Sem isso, um
    comprador chamado "CARLOS" viraria a casa 0 e um "ANA CASA NOVA" viraria
    outra — o nome do comprador é texto livre e não pode alimentar o
    reconhecedor de casa."""
    texto = (descricao or "").strip()
    if " - " in texto:
        cabeca, cauda = texto.split(" - ", 1)
    else:
        cabeca, cauda = texto, ""
    return numero_da_unidade(cabeca), cauda.strip()


def _dinheiro(valor) -> Decimal:
    """Para Decimal com 2 casas. Dinheiro em float erra, e daqui ele vai para
    a conferência do contrato e para o resumo do contábil."""
    if isinstance(valor, Decimal):
        d = valor
    elif isinstance(valor, float):
        d = Decimal(str(valor))
    else:
        d = Decimal(valor or 0)
    return d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def eh_financiamento(condicao: str) -> bool:
    return MARCA_FINANCIAMENTO in util.norm(condicao)


def eh_juros(condicao: str) -> bool:
    return MARCA_JUROS in util.norm(condicao)


@dataclass
class Recebimento:
    """Um recebimento do mês, como o contábil vai querer ver no resumo."""

    data: str                       # aaaa-mm-dd
    condicao: str                   # Sinal, Entrada, 1ª FINANCIAMENTO...
    valor: Decimal
    id: str = ""


@dataclass
class Imovel:
    """Uma casa que recebeu dinheiro de venda no mês."""

    obra: str                       # workName, igual ao name da obra
    unidade: int | None             # 1, 2... None quando a descrição não diz
    comprador: str                  # quem comprou: o Cliente do ERP quando é
                                    # pessoa, senão o nome da descrição
    descricao: str = ""             # a descrição crua, para a linha em revisão
    #: O campo Cliente do recebimento (`customerName`). Regra do dono
    #: (09/09/2026): "sempre o cliente do contrato" — mas em agosto/2026 ele
    #: era a própria SPE em 20 das 25 linhas (as de financiamento nascem com
    #: a empresa como cliente), então quem decide se ele vale como comprador
    #: é o pipeline, que conhece o cadastro das empresas.
    cliente: str = ""
    comprador_descricao: str = ""   # o nome depois do " - " da descrição
    recebido: Decimal = Decimal("0.00")     # soma do mês, todas as condições
    valor_venda: Decimal | None = None      # saleValue, quando o ERP manda
    recebimentos: list[Recebimento] = field(default_factory=list)
    revisao: str = ""               # motivo, quando não dá para seguir

    @property
    def chave(self) -> tuple[str, object]:
        """O que identifica o imóvel: obra + unidade.

        O lote tem mais de uma casa — a obra `TB 21 QD 46 LT 18` é do tipo
        "2 casas". Agrupar só por obra juntaria dois contratos diferentes.
        Sem unidade, a descrição crua faz o papel dela, para linhas iguais
        não se multiplicarem na tabela."""
        if self.unidade is None:
            return (util.norm_espaco(self.obra), util.norm_espaco(self.descricao))
        return (util.norm_espaco(self.obra), self.unidade)

    @property
    def rotulo(self) -> str:
        return rotulo_da_unidade(self.unidade)

    @property
    def condicoes(self) -> list[str]:
        vistas: list[str] = []
        for r in self.recebimentos:
            if r.condicao and r.condicao not in vistas:
                vistas.append(r.condicao)
        return vistas

    @property
    def data(self) -> str:
        return self.recebimentos[0].data if self.recebimentos else ""

    @property
    def ids(self) -> list[str]:
        return [r.id for r in self.recebimentos if r.id]


def _sem_obra(descricao: str) -> str:
    return ("recebimento sem centro de custo (obra) no ERP — "
            f'"{descricao or "(sem descrição)"}"')


def _sem_casa(descricao: str) -> str:
    return (f'a descrição "{descricao}" não diz a casa; corrija no ERP para '
            '"VENDA CASA 01 - NOME" e busque de novo')


def imoveis_do_mes(registros: list[dict], log=print) -> list[Imovel]:
    """Recebimentos crus -> imóveis, agrupados por obra + casa.

    Natureza e status já vieram filtrados do servidor. Nada é descartado em
    silêncio: recebimento sem obra ou sem casa na descrição vira uma linha em
    REVISÃO, com o motivo — com imposto sobre todo recebimento, cada um
    precisa aparecer para alguém, e quem corrige o cadastro é o dono."""
    por_chave: dict[tuple, Imovel] = {}

    for r in registros:
        obra = (r.get("workName") or "").strip()
        descricao = (r.get("description") or "").strip()
        unidade, comprador = partes_da_descricao(descricao)
        condicao = (r.get("readjustmentType") or "").strip()

        if not obra:
            revisao = _sem_obra(descricao)
        elif unidade is None:
            revisao = _sem_casa(descricao)
        else:
            revisao = ""

        cliente = (r.get("customerName") or "").strip()
        candidato = Imovel(obra=obra, unidade=unidade, comprador=comprador,
                           descricao=descricao, cliente=cliente,
                           comprador_descricao=comprador, revisao=revisao)
        imovel = por_chave.setdefault(candidato.chave, candidato)
        # O comprador vem da linha da venda; uma condição pode vir sem ele,
        # e vazio não pode apagar o que já se sabe.
        if comprador and not imovel.comprador:
            imovel.comprador = comprador
            imovel.comprador_descricao = comprador
        if cliente and not imovel.cliente:
            imovel.cliente = cliente

        valor = _dinheiro(r.get("sumOfReceivedValues"))
        imovel.recebido += valor
        imovel.recebimentos.append(Recebimento(
            data=(r.get("dateOfReceipt") or "")[:10], condicao=condicao,
            valor=valor, id=str(r.get("id") or "")))

        venda = r.get("saleValue")
        if venda and imovel.valor_venda is None:
            try:
                v = _dinheiro(venda)
                if v > 0:
                    imovel.valor_venda = v
            except Exception:
                pass

    imoveis = sorted(por_chave.values(),
                     key=lambda i: (i.obra, i.unidade or 0, i.descricao))
    for imovel in imoveis:
        imovel.recebimentos.sort(key=lambda x: (x.data, x.condicao))

    em_revisao = sum(1 for i in imoveis if i.revisao)
    if em_revisao:
        log(f"  [aviso] {em_revisao} linha(s) sem obra ou sem casa na "
            "descrição — ficam na lista, em revisão")
    return imoveis
