# -*- coding: utf-8 -*-
"""Qual dos anexos da obra é o contrato de compra e venda daquela casa.

Puro: entra a lista de anexos e o número da casa, sai o anexo (ou o motivo de
não ter dado). Sem navegador e sem tkinter.

A obra examinada no mapeamento tem 52 anexos. Os que interessam agora são os
que dizem COMPRA E VENDA e a casa certa:

    ✓ CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01
    ✓ CONTRATO DE COMPRA E VENDA TB 21 QD46 LT18 CS 01     (mesma casa, outra grafia)
    ✓ CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 02
    ✗ CONTRATO TB 21 QD 46 LT 18 CS 01                    (contrato da Caixa)
    ✗ CONTRATO EMPREITA - FULANO - TB 21 QD 46 LT 18
    ✗ DISTRATO TB 21 QD 46 LT 18 C1

Até 09/09/2026 a regra era a inversa — o contrato da Caixa entrava e o de
compra e venda ficava de fora — porque o contábil apurava imposto só no
financiamento. Com imposto em todo recebimento, o documento é o contrato
entre a SPE e o comprador.

**O nome da obra dentro do arquivo é ignorado, de propósito.** Três anexos
dessa obra dizem `TB 21 QD 26 LT 18` numa obra que é `QD 46`, e um escreve
`QD46 LT18` sem espaço. Como os anexos são pedidos por `entityIds`, já se sabe
em que obra se está: casar pelo texto do nome só importaria o erro de digitação
de quem subiu o arquivo.

**Duas grafias da mesma casa é revisão, não escolha.** A obra real tem
`QD 46 LT 18 CS 01` e `QD46 LT18 CS 01`: podem ser o mesmo arquivo subido duas
vezes, ou uma minuta e a versão assinada. Só quem abre sabe — a exceção é
quando exatamente um deles se declara ASSINADO no nome.
"""
from __future__ import annotations

import re

import util

from .regras import numero_da_unidade, rotulo_da_unidade

#: "COMPRA E VENDA", "COMPRA & VENDA", "COMPRAEVENDA", "COMPRA-E-VENDA", "CCV"
#: — e "COMRPA E VENDA", que em agosto/2026 estava em três obras de verdade.
#: `COM[A-Z]{2,3}` aceita COMPRA, COMRPA e COMPA sem aceitar qualquer palavra.
RE_COMPRA_E_VENDA = re.compile(r"\bCOM[A-Z]{2,3}\s*(?:E|&)\s*VENDA\b|\bCCV\b")

#: Palavras que, no nome, dizem que o arquivo NÃO é o contrato de compra e
#: venda vigente — mesmo dizendo "compra e venda". É uma PROTEÇÃO, não a
#: regra: um tipo novo que ninguém previu sobrevive à lista, concorre com o
#: verdadeiro e os dois caem em revisão pelo passo do "sobrou mais de um".
#: Em nenhum caminho o arquivo errado é baixado calado.
EXCLUSOES = (
    "DISTRATO", "ADITIVO", "RESCIS", "MINUTA", "CANCELAMENTO", "RENEGOCIA",
    "CESSAO", "PROCURACAO",
    # o contrato da Caixa também é "de compra e venda" no título oficial
    "CAIXA", "CEF", "FINANCIAMENTO", "MUTUO",
)

MARCA_ASSINADO = "ASSINADO"


def _nome(anexo: dict) -> str:
    return (anexo.get("filename") or "").strip()


def _norm(nome: str) -> str:
    """Comparável: sem acento, maiúsculo, hífen e ponto viram espaço."""
    return util.norm_espaco(re.sub(r"[-_.]", " ", nome or ""))


def eh_compra_e_venda(nome: str) -> bool:
    return bool(RE_COMPRA_E_VENDA.search(_norm(nome)))


def excluido_por(nome: str) -> str:
    """A palavra que tira o arquivo da disputa, ou ""."""
    n = _norm(nome)
    for palavra in EXCLUSOES:
        if re.search(rf"\b{palavra}", n):
            return palavra
    return ""


def candidatos(anexos: list[dict], unidade: int | None) -> list[dict]:
    """Anexos que dizem COMPRA E VENDA, são da casa pedida e não têm
    palavra de exclusão. Sem casa não há candidato: são vários por obra."""
    if not unidade:
        return []
    achados = []
    for a in anexos or []:
        nome = _nome(a)
        if not eh_compra_e_venda(nome):
            continue
        if excluido_por(nome):
            continue
        if numero_da_unidade(nome) != unidade:
            continue
        achados.append(a)
    return achados


def candidatos_distintos(anexos: list[dict], unidade: int | None) -> list[dict]:
    """Os candidatos com nomes diferentes entre si (cópias de nome idêntico
    contam como uma), na ordem em que o ERP os devolveu."""
    vistos: dict[str, dict] = {}
    for a in candidatos(anexos or [], unidade):
        vistos.setdefault(_norm(_nome(a)), a)
    return list(vistos.values())


def motivo_da_disputa(distintos: list[dict], unidade: int | None) -> str:
    nomes = ", ".join(sorted(f'"{_nome(a)}"' for a in distintos))
    return (f"{len(distintos)} anexos disputam a "
            f"{rotulo_da_unidade(unidade)}: {nomes}")


def contrato_de(anexos: list[dict], unidade: int | None) -> tuple[dict | None, str]:
    """(anexo, motivo). Anexo None significa revisão, e o motivo explica.

    Cópias de nome idêntico contam como uma: a obra examinada tem anexos
    repetidos de fato (o mesmo `HIDROSSANITARIO … CS 01` aparece duas vezes).
    Nomes DIFERENTES sobrando é ambiguidade de verdade, e vira revisão — a
    não ser que exatamente um se diga ASSINADO. Quem ainda pode desempatar é
    o pipeline, baixando os candidatos e comparando o conteúdo: em agosto/2026
    metade das disputas era o mesmo arquivo subido duas vezes com outro nome."""
    if not unidade:
        return None, "sem o número da casa não dá para escolher o contrato"
    achados = candidatos(anexos or [], unidade)
    if not achados:
        return None, (f"nenhum anexo de COMPRA E VENDA para a "
                      f"{rotulo_da_unidade(unidade)}")

    distintos = candidatos_distintos(anexos, unidade)
    if len(distintos) == 1:
        return achados[0], "único contrato de compra e venda da casa"

    assinados = [a for a in distintos if MARCA_ASSINADO in _norm(_nome(a))]
    if len(assinados) == 1:
        return assinados[0], "o único que se diz ASSINADO entre os candidatos"

    return None, motivo_da_disputa(distintos, unidade)


def ordenar_para_escolha(anexos: list[dict],
                         unidade: int | None) -> list[tuple[dict, bool]]:
    """[(anexo, é candidato)] para a janela de escolha à mão.

    Candidatos primeiro, o resto depois, os dois em ordem de nome. A obra
    examinada tem 52 anexos: mostrar a lista crua obrigaria a pessoa a
    procurar o contrato no meio de memorial, RCPM e manual do proprietário
    justamente na hora em que o app já admitiu não saber decidir.

    A lista INTEIRA aparece de propósito. Quando nenhum anexo diz COMPRA E
    VENDA, os candidatos são zero — e é exatamente aí que a pessoa precisa
    ver o resto para achar o arquivo que foi salvo com outro nome."""
    marcados = {_norm(_nome(a)) for a in candidatos(anexos or [], unidade)}
    return sorted(((a, _norm(_nome(a)) in marcados) for a in (anexos or [])),
                  key=lambda par: (not par[1], _norm(_nome(par[0]))))
