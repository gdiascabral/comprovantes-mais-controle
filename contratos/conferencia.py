# -*- coding: utf-8 -*-
"""O texto do contrato bate com o que o ERP disse da venda?

Puro: entra o texto do PDF e o esperado, sai um resultado por ponto. Sem
navegador e sem tkinter.

O arquivo certo pelo NOME ainda pode ser o documento errado por dentro. Antes
de gravar na pasta do fechamento, cinco pontos são conferidos — rua,
quadra/lote, casa, comprador e valor do financiamento.

Cada ponto tem TRÊS resultados, não dois: CONFERE, DIVERGE (o documento
contradiz) e `?` (não deu para verificar). A distinção é a mesma dos
Pagamentos do Dia, e existe porque alarme falso ensina a ignorar alarme: um
contrato ilegível não é um contrato errado.
"""
from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    import sys as _sys
    _sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

CONFERE = "CONFERE"
DIVERGE = "DIVERGE"
ILEGIVEL = "?"

#: Abaixo disto o PDF não tem texto aproveitável (nem depois do OCR): tudo
#: vira `?`, e `?` não retém arquivo.
MINIMO_DE_TEXTO = 40

#: Palavras que são a mesma coisa nos dois lados. O contrato escreve por
#: extenso, o cadastro abrevia.
SINONIMOS = ((r"\bQUADRA\b", "QD"), (r"\bLOTE\b", "LT"),
             (r"\bCASA\b", "CS"), (r"\bRUA\b", ""), (r"\bAVENIDA\b", "AV"))


#: Pontuação que gruda no código e atrapalha, MENOS a que está entre dígitos.
#: `QD46LT18,` precisa soltar a vírgula para o espaçador reconhecer o código;
#: `248.000,00` não pode perder nem o ponto nem a vírgula, senão o valor deixa
#: de ser encontrado. O olhar para frente/para trás separa os dois casos.
RE_PONTUACAO_SOLTA = re.compile(r"(?<!\d)[.,;:]|[.,;:](?!\d)")


def _preparar(texto: str) -> str:
    """Texto comparável: sem acento, maiúsculo, sinônimos resolvidos e com os
    espaços do código de obra devolvidos.

    O OCR come os espaços do centro de custo (`TB 21 QD 46` sai `TB21QD46`).
    Sem devolvê-los, quadra e lote divergiriam em quase todo contrato
    digitalizado — divergência falsa, e das que retêm arquivo bom.

    A ordem importa: soltar a pontuação ANTES de espaçar, porque o espaçador
    trabalha por palavra e `QD46LT18,` com a vírgula colada não tem cara de
    centro de custo para ele."""
    t = util.norm(texto)
    t = RE_PONTUACAO_SOLTA.sub(" ", t)
    t = _com_espacos(" ".join(t.split()))
    for padrao, troca in SINONIMOS:
        t = re.sub(padrao, troca, t)
    return " ".join(t.split())


def _com_espacos(texto: str) -> str:
    """Aplica o `_espacar_codigo` do separar_renomear quando ele existir.

    Import tardio e opcional: este módulo é puro e roda em teste sem o pacote
    de OCR carregado."""
    try:
        from separar_renomear import _espacar_codigo
        return _espacar_codigo(texto)
    except Exception:
        return texto


def _texto_util(texto: str) -> str | None:
    """O texto preparado, ou None quando não há o que conferir."""
    if not texto or len(texto.strip()) < MINIMO_DE_TEXTO:
        return None
    return _preparar(texto)


def _tem(trecho: str, texto: str) -> str:
    """CONFERE se o trecho aparece; DIVERGE se não."""
    alvo = _preparar(trecho)
    if not alvo:
        return ILEGIVEL
    return CONFERE if alvo in texto else DIVERGE


def conferir_rua(texto: str, rua: str) -> str:
    if not (rua or "").strip():
        return ILEGIVEL
    return _tem(rua, texto)


def conferir_quadra_lote(texto: str, complemento: str) -> str:
    """"QD 46 LT 18" — aceita "QUADRA 46 LOTE 18" pelo mesmo caminho."""
    if not (complemento or "").strip():
        return ILEGIVEL
    return _tem(complemento, texto)


def conferir_casa(texto: str, unidade: int) -> str:
    """A casa aparece como CS 02, CS 2, CASA 02, C2..."""
    if not unidade:
        return ILEGIVEL
    padrao = re.compile(rf"\bCS\s*0*{unidade}\b")
    return CONFERE if padrao.search(texto) else DIVERGE


def conferir_nome(texto: str, comprador: str) -> str:
    """Todos os sobrenomes do esperado aparecem no texto?

    Não se compara a string inteira: o contrato traz o nome completo e a
    descrição do ERP às vezes abrevia. Exigir os sobrenomes acha o mesmo
    comprador sem exigir a mesma grafia."""
    partes = [p for p in _preparar(comprador).split()
              if len(p) > 2 and p not in ("DOS", "DAS", "DER", "DEL")]
    if not partes:
        return ILEGIVEL
    return CONFERE if all(p in texto for p in partes) else DIVERGE


#: 248.000,00 | R$ 248.000,00 | 248000,00
RE_VALOR = re.compile(r"(?<![\d.,])(\d{1,3}(?:\.\d{3})+|\d+),(\d{2})(?![\d])")


def valores_no_texto(texto: str) -> set[Decimal]:
    achados = set()
    for inteiro, centavos in RE_VALOR.findall(texto or ""):
        try:
            achados.add(Decimal(inteiro.replace(".", "") + "." + centavos))
        except Exception:
            continue
    return achados


def conferir_valor(texto: str, valor: Decimal) -> str:
    """O valor do FINANCIAMENTO (sem os juros) aparece no contrato?

    Valor por extenso NÃO é divergência — é `?`. Escrever um leitor de numeral
    por extenso em português para depois errar nele só fabricaria alarme
    falso, e alarme falso aqui retém contrato bom."""
    if not valor or Decimal(valor) <= 0:
        return ILEGIVEL
    achados = valores_no_texto(texto)
    if not achados:
        return ILEGIVEL          # contrato que só escreve por extenso
    return CONFERE if Decimal(valor) in achados else DIVERGE


def conferir(texto: str, esperado: dict) -> dict:
    """Os cinco pontos. `esperado` traz rua, complemento, unidade, comprador
    e valor_financiamento.

    Texto vazio ou curto demais não é divergência: são cinco `?`, e `?` nunca
    retém o arquivo."""
    preparado = _texto_util(texto)
    if preparado is None:
        motivo = "PDF sem texto aproveitável (nem com OCR)"
        return {"rua": ILEGIVEL, "quadra_lote": ILEGIVEL, "casa": ILEGIVEL,
                "comprador": ILEGIVEL, "valor": ILEGIVEL, "motivo": motivo}

    return {
        "rua": conferir_rua(preparado, esperado.get("rua", "")),
        "quadra_lote": conferir_quadra_lote(preparado,
                                            esperado.get("complemento", "")),
        "casa": conferir_casa(preparado, esperado.get("unidade")),
        "comprador": conferir_nome(preparado, esperado.get("comprador", "")),
        "valor": conferir_valor(preparado,
                                esperado.get("valor_financiamento")),
        "motivo": "",
    }


def divergencias(resultado: dict) -> list[str]:
    """Os pontos que DIVERGIRAM. Lista vazia = pode gravar."""
    return [ponto for ponto, r in resultado.items()
            if ponto != "motivo" and r == DIVERGE]


def ressalvas(resultado: dict) -> list[str]:
    """Os pontos que ficaram em `?`. Não retêm, mas vão para o relatório."""
    return [ponto for ponto, r in resultado.items()
            if ponto != "motivo" and r == ILEGIVEL]


def pode_gravar(resultado: dict) -> bool:
    """Qualquer DIVERGE retém o arquivo.

    Contrato errado na pasta do fechamento é o defeito mais caro daqui, e nada
    no disco denuncia depois — a mesma razão pela qual o OFX do Sicoob é
    conferido contra o ACCTID antes de ser arquivado."""
    return not divergencias(resultado)
