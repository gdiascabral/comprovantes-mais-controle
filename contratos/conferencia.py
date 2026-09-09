# -*- coding: utf-8 -*-
"""O texto do contrato bate com o que o ERP disse da venda?

Puro: entra o texto do PDF e o esperado, sai um resultado por ponto. Sem
navegador e sem tkinter.

O arquivo certo pelo NOME ainda pode ser o documento errado por dentro. Antes
de gravar na pasta do fechamento, sete pontos são conferidos:

    tipo         é um contrato entre COMPRADOR e VENDEDOR, e não o da Caixa
    rua          a rua da obra
    quadra_lote  o complemento da obra ("QD 46 LT 18")
    casa         a casa do OBJETO do contrato ("LT 18 CASA 02")
    comprador    os sobrenomes do comprador da descrição do ERP
    vendedora    o CNPJ (ou a razão social) da empresa dona da pasta
    valor        o valor da VENDA que o ERP informou (`saleValue`)

Cada ponto tem TRÊS resultados, não dois: CONFERE, DIVERGE (o documento
contradiz) e `?` (não deu para verificar). A distinção é a mesma dos
Pagamentos do Dia, e existe porque alarme falso ensina a ignorar alarme: um
contrato ilegível não é um contrato errado.

**Vendedora é o ponto que protege do pior defeito**: contrato anexado na obra
errada, ou obra mapeada na empresa errada, acaba na pasta de outra empresa —
e nada no disco denuncia depois. O CNPJ da SPE no PDF é o que amarra.

**Valor nunca retém.** `saleValue` é o valor da venda no ERP, mas o contábil
apura pelo que entrou no banco, e o preço do contrato pode ter sido
renegociado. Achar o valor é confirmação a mais; não achar é `?`.
"""
from __future__ import annotations

import re
from decimal import Decimal

import util

CONFERE = "CONFERE"
DIVERGE = "DIVERGE"
ILEGIVEL = "?"

PONTOS = ("tipo", "rua", "quadra_lote", "casa", "comprador", "vendedora",
          "valor")

#: Abaixo disto o PDF não tem texto aproveitável (nem depois do OCR): tudo
#: vira `?`, e `?` não retém arquivo.
MINIMO_DE_TEXTO = 40

#: Palavras que são a mesma coisa nos dois lados. O contrato escreve por
#: extenso, o cadastro abrevia.
SINONIMOS = ((r"\bQUADRA\b", "QD"), (r"\bLOTE\b", "LT"),
             (r"\bCASA\b", "CS"), (r"\bRUA\b", ""), (r"\bAVENIDA\b", "AV"))

#: Palavras de razão social que não identificam ninguém.
PARTICULAS_DE_EMPRESA = {"LTDA", "SPE", "EIRELI", "EPP", "ME", "SA", "S/A",
                         "CIA", "E", "DE", "DA", "DO", "DAS", "DOS"}


#: Pontuação que gruda no código e atrapalha, MENOS a que está entre dígitos.
#: `QD46LT18,` precisa soltar a vírgula para o espaçador reconhecer o código;
#: `248.000,00` não pode perder nem o ponto nem a vírgula, senão o valor deixa
#: de ser encontrado. O olhar para frente/para trás separa os dois casos.
RE_PONTUACAO_SOLTA = re.compile(r"(?<!\d)[.,;:]|[.,;:](?!\d)")

#: `QD26A` / `LT14` / `CS02` colados, como saem do OCR e de quem digita rápido.
RE_CODIGO_COLADO = re.compile(r"\b(QD|LT|CS)(\d)")

#: `QD 26 - A LT 14` e `QD 26 A LT 14` são o `QD 26A LT 14` do cadastro.
RE_LETRA_DO_LOTE = re.compile(r"(\d)\s*-?\s*([A-Z])\b(?=\s*LT\b)")


def _preparar(texto: str) -> str:
    """Texto comparável: sem acento, maiúsculo, sinônimos resolvidos e com os
    espaços do código de obra devolvidos.

    O OCR come os espaços do centro de custo (`TB 21 QD 46` sai `TB21QD46`).
    Sem devolvê-los, quadra e lote divergiriam em quase todo contrato
    digitalizado — divergência falsa, e das que retêm arquivo bom.

    A ordem importa: soltar a pontuação ANTES de espaçar, porque o espaçador
    trabalha por palavra e `QD46LT18,` com a vírgula colada não tem cara de
    centro de custo para ele. Os sinônimos vêm antes das regras de código
    ("QUADRA 26 - A LOTE 14" só vira "QD 26A LT 14" depois de LOTE virar LT),
    e a letra do lote é juntada por último, porque o espaçador é quem separa
    `QD26A` em `QD 26 A` nos códigos longos."""
    t = util.norm(texto)
    t = RE_PONTUACAO_SOLTA.sub(" ", t)
    t = _com_espacos(" ".join(t.split()))
    for padrao, troca in SINONIMOS:
        t = re.sub(padrao, troca, t)
    t = RE_CODIGO_COLADO.sub(r"\1 \2", t)
    t = RE_LETRA_DO_LOTE.sub(r"\1\2", t)
    return " ".join(t.split())


def _com_espacos(texto: str) -> str:
    """Aplica o `_espacar_codigo` do separar_renomear quando ele existir.

    Import tardio e opcional: este módulo é puro e roda em teste sem o pacote
    de OCR carregado."""
    try:
        from separar_renomear.separar_renomear import _espacar_codigo
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


# ------------------------------------------------------------------ tipo
RE_CAIXA = re.compile(r"CAIXA ECONOMICA FEDERAL")
RE_FIDUCIANTE = re.compile(r"DEVEDOR\W*(?:ES)?\W*FIDUCIANTE")


def conferir_tipo(texto: str) -> str:
    """Contrato entre COMPRADOR e VENDEDOR, e não o instrumento da Caixa.

    O contrato da Caixa também chama a SPE de VENDEDOR e também traz a casa,
    o comprador e o valor — passaria em todos os outros pontos. O que só ele
    tem é o par "Caixa Econômica Federal" + "devedor fiduciante"."""
    if RE_CAIXA.search(texto) and RE_FIDUCIANTE.search(texto):
        return DIVERGE
    if "COMPRADOR" in texto and "VENDEDOR" in texto:
        return CONFERE
    return ILEGIVEL


# --------------------------------------------------------------- endereço
def conferir_rua(texto: str, rua: str) -> str:
    if not (rua or "").strip():
        return ILEGIVEL
    return _tem(rua, texto)


def conferir_quadra_lote(texto: str, complemento: str) -> str:
    """"QD 46 LT 18" — aceita "QUADRA 46 LOTE 18" e "QD 26 - A" pelo mesmo
    caminho de preparação dos dois lados."""
    if not (complemento or "").strip():
        return ILEGIVEL
    return _tem(complemento, texto)


#: `LT 18 CS 02`: a casa logo depois do lote é o OBJETO do contrato. Um
#: contrato de lote com duas casas cita a outra nas confrontações ("com a
#: casa 02"), e o endereço de quem assina pela SPE pode ter "Casa 22" — só o
#: par lote+casa diz de qual casa o contrato é.
RE_LOTE_CASA = re.compile(r"\bLT\s*\d+[A-Z]?\s*-?\s*CS\s*(?:NO?\s*)?0*(\d{1,3})\b")


def conferir_casa(texto: str, unidade: int | None) -> str:
    if not unidade:
        return ILEGIVEL
    objeto = {int(n) for n in RE_LOTE_CASA.findall(texto)}
    if objeto:
        return CONFERE if unidade in objeto else DIVERGE
    # Sem o par lote+casa, vale a presença da casa — é o que o contrato da
    # Caixa e os mais antigos oferecem.
    padrao = re.compile(rf"\bCS\s*(?:NO?\s*)?0*{unidade}\b")
    return CONFERE if padrao.search(texto) else DIVERGE


# ------------------------------------------------------------------ nomes
def _palavras(nome: str, particulas=frozenset()) -> list[str]:
    return [p for p in _preparar(nome).split()
            if len(p) > 2 and p not in particulas]


def conferir_nome(texto: str, comprador: str) -> str:
    """Todos os sobrenomes do esperado aparecem no texto?

    Não se compara a string inteira: o contrato traz o nome completo e a
    descrição do ERP às vezes abrevia. Exigir os sobrenomes acha o mesmo
    comprador sem exigir a mesma grafia. Casal ("FULANO E BELTRANA") passa
    pelo mesmo caminho: os sobrenomes dos dois têm de estar lá."""
    partes = _palavras(comprador, frozenset({"DOS", "DAS", "DER", "DEL"}))
    if not partes:
        return ILEGIVEL
    return CONFERE if all(p in texto for p in partes) else DIVERGE


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def conferir_vendedora(texto: str, cnpj: str, nomes: list[str]) -> str:
    """A empresa da pasta é a vendedora do contrato?

    Pelo CNPJ primeiro: 14 dígitos seguidos no texto sem pontuação não
    aparecem por acaso, e sobrevivem à maioria dos erros de OCR. Faltando o
    CNPJ (no cadastro ou no texto), a razão social e o nome do cliente no ERP
    valem pelo mesmo critério do comprador: todas as palavras que identificam.
    Sem nada para comparar, `?`."""
    cnpj = _so_digitos(cnpj)
    candidatos = [n for n in (nomes or []) if (n or "").strip()]
    if not cnpj and not candidatos:
        return ILEGIVEL
    if cnpj and len(cnpj) == 14 and cnpj in _so_digitos(texto):
        return CONFERE
    for nome in candidatos:
        partes = _palavras(nome, PARTICULAS_DE_EMPRESA)
        if partes and all(p in texto for p in partes):
            return CONFERE
    return DIVERGE


# ------------------------------------------------------------------ valor
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


def conferir_valor(texto: str, valor) -> str:
    """O valor da VENDA aparece no contrato? CONFERE ou `?` — nunca DIVERGE.

    O contábil apura pelo que entrou no banco, e o preço do contrato pode ter
    sido renegociado depois do ERP: reter por isso seguraria contrato bom.
    Valor por extenso também é `?`: escrever um leitor de numeral por extenso
    em português para depois errar nele só fabricaria alarme falso."""
    try:
        if not valor or Decimal(valor) <= 0:
            return ILEGIVEL
    except Exception:
        return ILEGIVEL
    return CONFERE if Decimal(valor) in valores_no_texto(texto) else ILEGIVEL


# ---------------------------------------------------------------- conjunto
def conferir(texto: str, esperado: dict) -> dict:
    """Os sete pontos. `esperado` traz rua, complemento, unidade, comprador,
    cnpj, vendedora (lista de nomes) e valor_venda.

    Texto vazio ou curto demais não é divergência: são sete `?`, e `?` nunca
    retém o arquivo."""
    preparado = _texto_util(texto)
    if preparado is None:
        r = {p: ILEGIVEL for p in PONTOS}
        r["motivo"] = "PDF sem texto aproveitável (nem com OCR)"
        return r

    return {
        "tipo": conferir_tipo(preparado),
        "rua": conferir_rua(preparado, esperado.get("rua", "")),
        "quadra_lote": conferir_quadra_lote(preparado,
                                            esperado.get("complemento", "")),
        "casa": conferir_casa(preparado, esperado.get("unidade")),
        "comprador": conferir_nome(preparado, esperado.get("comprador", "")),
        "vendedora": conferir_vendedora(preparado, esperado.get("cnpj", ""),
                                        esperado.get("vendedora") or []),
        "valor": conferir_valor(preparado, esperado.get("valor_venda")),
        "motivo": "",
    }


def divergencias(resultado: dict) -> list[str]:
    """Os pontos que DIVERGIRAM. Lista vazia = pode gravar."""
    return [ponto for ponto in PONTOS if resultado.get(ponto) == DIVERGE]


def ressalvas(resultado: dict) -> list[str]:
    """Os pontos que ficaram em `?`. Não retêm, mas vão para o relatório."""
    return [ponto for ponto in PONTOS if resultado.get(ponto) == ILEGIVEL]


def pode_gravar(resultado: dict) -> bool:
    """Qualquer DIVERGE retém o arquivo.

    Contrato errado na pasta do fechamento é o defeito mais caro daqui, e nada
    no disco denuncia depois — a mesma razão pela qual o OFX do Sicoob é
    conferido contra o ACCTID antes de ser arquivado."""
    return not divergencias(resultado)
