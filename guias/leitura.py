# -*- coding: utf-8 -*-
"""Do texto de uma guia/boleto para valor, vencimento e número do documento.

`ler_texto` é pura de propósito: é nela que mora toda a regra, e é ela que o
teste exercita. `ler_pdf` só extrai o texto e delega — assim nenhum PDF real
precisa entrar no repositório, que é público.

Os boletos da contabilidade têm texto (não são imagem), então não há OCR aqui.
PDF sem texto devolve lista vazia, e quem chamou trata como "não consegui ler".
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import util
from pagamentos_dia import ocr_boleto

log = util.log(__name__)

#: Campos que o boleto zera e imprime ANTES do total. O valor deles nunca é o
#: valor do documento — e era o primeiro `NN,NN` da página, que é justamente o
#: que a busca genérica pegava (medido: "Desconto R$ 0,00 Valor da cobranca
#: R$ 1.234,56" devolvia 0,00).
DEDUCOES = ("DESCONTO", "ABATIMENTO", "MULTA", "JUROS", "MORA", "DEDUC",
            "ACRESCIMO", "OUTRAS")

#: Os rótulos que nomeiam o valor A PAGAR. Sem acento e em caixa alta, porque
#: é assim que o contexto é normalizado antes de comparar.
ROTULOS_TOTAL = ("VALOR DO DOCUMENTO", "VALOR DA COBRANCA", "VALOR COBRADO",
                 "VALOR A PAGAR", "VALOR TOTAL", "VALOR DA GUIA",
                 "VALOR DO TITULO", "VALOR DO BOLETO", "VALOR PRINCIPAL",
                 "TOTAL A PAGAR")

#: `1.234,56` e `641,31`. O milhar é opcional e os centavos não: valor sem
#: centavos num boleto é quase sempre outro número da página (código, conta).
RE_VALOR = re.compile(r"R?\$?\s*([0-9]{1,3}(?:\.[0-9]{3})*|[0-9]+),([0-9]{2})")
RE_VENCIMENTO = re.compile(
    r"vencimento\s*[:\-]?\s*([0-3]?[0-9])[/.-]([01]?[0-9])[/.-](20[0-9]{2})", re.I)
RE_DOCUMENTO = re.compile(
    r"(?:nosso\s*n[uú]mero|n[uú]mero\s*(?:do\s*)?documento|documento)\s*"
    r"[:\-]?\s*([0-9][0-9./\-]{2,})", re.I)


@dataclass
class ItemLido:
    valor: Decimal | None = None
    vencimento: date | None = None
    documento: str = ""
    pagina: int = 1

    @property
    def tem_cobranca(self) -> bool:
        """Página que vale um lançamento: tem valor E (vencimento ou documento)."""
        return self.valor is not None and bool(self.vencimento or self.documento)


def _decimal(inteiro: str, centavos: str) -> Decimal | None:
    try:
        return Decimal(f"{inteiro.replace('.', '')}.{centavos}")
    except InvalidOperation:
        return None


def _linha_digitavel(texto: str) -> str:
    """A linha digitável do texto, só se os dígitos verificadores fecharem.

    Usa `pagamentos_dia.ocr_boleto`, que já sabe os DOIS formatos e é o mesmo
    código que valida linha digitável no resto do app: boleto bancário (47
    dígitos) e ficha de arrecadação (48, começando em 8) — e a guia de FGTS,
    de INSS e de contribuição é ficha de arrecadação, que a regex anterior
    nem reconhecia. Reprovando o DV, devolve "" e quem chama cai no rótulo.
    """
    d = ocr_boleto.digitos(texto or "")
    for tamanho in (47, 48):
        for i in range(0, max(len(d) - tamanho, 0) + 1):
            trecho = d[i:i + tamanho]
            if ocr_boleto.valida(trecho):
                return trecho
    return ""


def _candidatos_de_valor(texto: str) -> list[tuple[str, Decimal]]:
    """(contexto de até 40 caracteres antes, valor) de cada `NN,NN` do texto."""
    saida = []
    for achado in RE_VALOR.finditer(texto or ""):
        valor = _decimal(achado.group(1), achado.group(2))
        if valor is None:
            continue
        inicio = max(0, achado.start() - 40)
        contexto = util.sem_acento(texto[inicio:achado.start()]).upper()
        saida.append((contexto, valor))
    return saida


def _valor_do_texto(texto: str) -> Decimal | None:
    """O valor A PAGAR, ou None.

    Três regras, nesta ordem: valor zero nunca conta (é campo de desconto ou
    de multa em branco); candidato cujo contexto traz um rótulo de total ganha;
    sem rótulo, descarta o que está num contexto de dedução e fica com o
    último, que num boleto é o total impresso depois das deduções.
    """
    candidatos = [(c, v) for c, v in _candidatos_de_valor(texto) if v > 0]
    if not candidatos:
        return None
    rotulados = [(c, v) for c, v in candidatos
                 if any(r in c for r in ROTULOS_TOTAL)]
    if rotulados:
        return rotulados[-1][1]
    limpos = [(c, v) for c, v in candidatos
              if not any(d in c for d in DEDUCOES)]
    return (limpos or candidatos)[-1][1]


def ler_texto(texto: str, pagina: int = 1) -> ItemLido:
    """Valor, vencimento e documento de UMA página. Função pura.

    A linha digitável, quando os dígitos verificadores fecham, é a fonte mais
    confiável do NÚMERO do documento — é ela que o banco cobra. Já para o
    VALOR ela entra só como último recurso: uma janela de 47 dígitos que passe
    no DV por acaso não pode sobrepor um valor que o texto nomeou.
    """
    texto = texto or ""
    item = ItemLido(pagina=pagina)
    linha = _linha_digitavel(texto)

    item.valor = _valor_do_texto(texto)
    if item.valor is None and linha:
        da_linha = ocr_boleto.valor_da_linha(linha)
        if da_linha:
            # float -> Decimal na fronteira: o valor da linha nasce de centavos
            # inteiros, então duas casas o recuperam exato.
            item.valor = Decimal(f"{da_linha:.2f}")

    venc = RE_VENCIMENTO.search(texto)
    if venc:
        dia, mes, ano = (int(g) for g in venc.groups())
        try:
            item.vencimento = date(ano, mes, dia)
        except ValueError:
            log.warning("vencimento fora do calendário numa guia")
    if item.vencimento is None and linha:
        item.vencimento = ocr_boleto.vencimento_da_linha(linha)

    if linha:
        item.documento = ocr_boleto.formatar(linha)
    else:
        doc = RE_DOCUMENTO.search(texto)
        if doc:
            item.documento = doc.group(1).strip()
    return item


def _paginas_de_texto(caminho: Path) -> list[str]:
    """O texto de cada página. Isolado para o teste não precisar de PDF."""
    import pdfplumber
    with pdfplumber.open(str(caminho)) as pdf:
        return [(p.extract_text() or "") for p in pdf.pages]


def ler_pdf(caminho: Path) -> list[ItemLido]:
    """Um item por página que tenha cobrança. Lista vazia = não deu para ler."""
    try:
        paginas = _paginas_de_texto(Path(caminho))
    except Exception:
        log.warning("não deu para abrir a guia com o pdfplumber", exc_info=True)
        return []
    itens = [ler_texto(t, i) for i, t in enumerate(paginas, start=1)]
    return [i for i in itens if i.tem_cobranca]
