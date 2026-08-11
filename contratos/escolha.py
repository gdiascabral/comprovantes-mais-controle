# -*- coding: utf-8 -*-
"""Qual dos anexos da obra é o contrato de financiamento daquela casa.

Puro: entra a lista de anexos e o número da casa, sai o anexo (ou o motivo de
não ter dado). Sem navegador e sem tkinter.

A obra examinada no mapeamento tem 52 anexos, seis começando com `CONTRATO`.
O que separa é o que vem LOGO DEPOIS da palavra:

    ✓ CONTRATO TB 21 QD 46 LT 18 CS 02
    ✓ CONTRATO TB 21 QD 46 LT 18 CS 01
    ✗ CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 01
    ✗ CONTRATO DE COMPRA E VENDA TB 21 QD46 LT18 CS 01
    ✗ CONTRATO DE COMPRA E VENDA TB 21 QD 46 LT 18 CS 02
    ✗ CONTRATO EMPREITA - CARLOS MARTINS BARROS - TB 21 QD 46 LT 18

Os quase-parecidos (`DISTRATO … C1`, `TERMO DE ENTREGA … CS 02`, `RCPM CS2`,
`CERTIDÃO CS 01`, `MEMORIAL CS1`, `MANUAL DO PROPRIETARIO CS2`) caem fora
sozinhos por não COMEÇAREM com `CONTRATO`.

**O nome da obra dentro do arquivo é ignorado, de propósito.** Três anexos
dessa obra dizem `TB 21 QD 26 LT 18` numa obra que é `QD 46`, e um escreve
`QD46 LT18` sem espaço. Como os anexos são pedidos por `entityIds`, já se sabe
em que obra se está: casar pelo texto do nome só importaria o erro de digitação
de quem subiu o arquivo.
"""
from __future__ import annotations

from pathlib import Path

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

from .regras import numero_da_unidade

#: Qualificadores que aparecem logo depois de `CONTRATO` e mudam o documento.
#: É uma PROTEÇÃO, não a regra: um qualificador novo que ninguém previu
#: ("CONTRATO DE GAVETA … CS 01") sobrevive a esta lista, mas aí concorre com o
#: verdadeiro e os dois caem em revisão pelo passo do "sobrou mais de um" — que
#: é o desfecho certo. Em nenhum caminho o arquivo errado é baixado calado.
QUALIFICADORES = (
    "DE COMPRA E VENDA",
    "COMPRA E VENDA",
    "DE EMPREITA",
    "EMPREITA",
    "DE GAVETA",
    "DE LOCACAO",
    "DE PRESTACAO",
)


def _nome(anexo: dict) -> str:
    return (anexo.get("filename") or "").strip()


def comeca_com_contrato(nome: str) -> bool:
    return util.norm_espaco(nome).startswith("CONTRATO")


def tem_qualificador(nome: str) -> bool:
    """O que vem depois de `CONTRATO` desqualifica o arquivo?"""
    n = util.norm_espaco(nome)
    if not n.startswith("CONTRATO"):
        return False
    resto = n[len("CONTRATO"):].strip()
    return any(resto.startswith(q) for q in QUALIFICADORES)


def candidatos(anexos: list[dict], unidade: int) -> list[dict]:
    """Anexos que começam com CONTRATO, são da casa pedida e não têm
    qualificador."""
    achados = []
    for a in anexos:
        nome = _nome(a)
        if not comeca_com_contrato(nome):
            continue
        if tem_qualificador(nome):
            continue
        if numero_da_unidade(nome) != unidade:
            continue
        achados.append(a)
    return achados


def contrato_de(anexos: list[dict], unidade: int) -> tuple[dict | None, str]:
    """(anexo, motivo). Anexo None significa revisão, e o motivo explica.

    Cópias de nome idêntico contam como uma: a obra examinada tem anexos
    repetidos de fato (o mesmo `HIDROSSANITARIO … CS 01` aparece duas vezes).
    Nomes DIFERENTES sobrando é ambiguidade de verdade, e vira revisão."""
    achados = candidatos(anexos or [], unidade)
    if not achados:
        return None, (f"nenhum anexo começando com CONTRATO para a "
                      f"{_rotulo(unidade)}")

    distintos = {util.norm_espaco(_nome(a)): a for a in achados}
    if len(distintos) == 1:
        return achados[0], "único CONTRATO da casa"

    nomes = ", ".join(sorted(f'"{_nome(a)}"' for a in distintos.values()))
    return None, (f"{len(distintos)} anexos disputam a {_rotulo(unidade)}: "
                  f"{nomes}")


def ordenar_para_escolha(anexos: list[dict],
                         unidade: int) -> list[tuple[dict, bool]]:
    """[(anexo, é candidato)] para a janela de escolha à mão.

    Candidatos primeiro, o resto depois, os dois em ordem de nome. A obra
    examinada tem 52 anexos: mostrar a lista crua obrigaria a pessoa a
    procurar o contrato no meio de memorial, RCPM e manual do proprietário
    justamente na hora em que o app já admitiu não saber decidir.

    A lista INTEIRA aparece de propósito. Quando nenhum anexo começa com
    CONTRATO, os candidatos são zero — e é exatamente aí que a pessoa precisa
    ver o resto para achar o arquivo que foi salvo com outro nome."""
    marcados = {util.norm_espaco(_nome(a))
                for a in candidatos(anexos or [], unidade)}
    return sorted(((a, util.norm_espaco(_nome(a)) in marcados)
                   for a in (anexos or [])),
                  key=lambda par: (not par[1], util.norm_espaco(_nome(par[0]))))


def _rotulo(unidade: int) -> str:
    return f"CS {unidade:02d}"
