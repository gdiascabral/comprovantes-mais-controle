# -*- coding: utf-8 -*-
"""Código de barras do boleto: o identificador EXATO do casamento.

Pedido do dono (08/10/2026): boleto pago por conta de pessoa física não leva
descrição nenhuma, e o casamento ficava só com valor e data. O código de
barras está nos DOIS lados -- no comprovante (Sicoob, PagBank, Next, Neon) e no
boleto anexado ao título no Mais Controle --, carrega o valor e o vencimento e
se confere sozinho pelos dígitos verificadores.

Medido antes de escrever (só leitura, 08/10/2026): os comprovantes de boleto
do Sicoob trazem a linha digitável inteira na camada de texto, numa linha só
ou partida em duas; dos prints de PF lidos por OCR, 59 de 60 a trazem partida
em DUAS linhas seguidas. O PDF do Inter não mostra o código do boleto -- ali este
módulo não acha nada, e não achar é neutro.

ONDE O CÓDIGO PODE ESTAR
------------------------
Com TODOS os dígitos verificadores fechando (quatro no boleto bancário,
quatro na ficha de arrecadação), em três degraus -- o seguinte só se o
anterior não achou nada:
  1. numa linha do texto;
  2. em duas linhas seguidas coladas (o OCR do print quebra a linha digitável
     ao meio);
  3. no texto inteiro colado, e só com o valor embutido igual a um dos
     `valores` esperados (centavos) -- o cerco duplo do `ocr_boleto`.
Os degraus existem porque cada junção multiplica as janelas, e com elas a
chance de um falso: medido em 08/10/2026, colar a linha digitável verdadeira
com a linha de baixo deu um SEGUNDO "código" em 2 de 124 comprovantes do
Sicoob.

O mapa de confusões do OCR (O->0, S->5, B->8...) só vale para texto que veio
de OCR (`ocr=True`). Na camada de texto ele inventa dígitos: um comprovante
Pix com bloco de assinatura em base64 virou "código de barras" na medição.

O QUE SE GUARDA
---------------
O código de barras de 44 dígitos (`ocr_boleto.codigo_de_barras`), nunca a
linha digitável: é a forma única do boleto, a mesma que a remessa CNAB usa, e
comparar 44 com 44 não depende de como cada lado escreveu a linha.
"""
from __future__ import annotations

import io
import re

from pagamentos_dia import ocr_boleto

#: Arquivo do título que vale ler: PDF ou foto. O boleto às vezes vem dentro do
#: PDF da nota (ver o PR do "boleto dentro da NF"), então a NF também é lida.
_EXT_PDF = (".pdf",)
_EXT_IMAGEM = (".jpg", ".jpeg", ".png")
#: Teto de arquivos lidos por título: cada um é um download (e talvez um OCR).
MAX_ARQUIVOS_POR_TITULO = 6
#: Anexo do título que é COMPROVANTE (etiqueta ou nome): o pagamento de uma
#: parcela anterior anexado no título, e não no sub-pagamento, não é boleto
#: desta parcela -- o mesmo critério do `pagamentos_dia/relatorio.py`.
_COMPROVANTE = re.compile(r"comprovante", re.I)


def _e_comprovante(f: dict) -> bool:
    rotulo = " ".join(str(f.get(k) or "") for k in
                      ("tagName", "tag", "filename", "name", "description"))
    tags = f.get("tags")
    if isinstance(tags, list):
        rotulo += " " + " ".join(str(t.get("name") if isinstance(t, dict) else t)
                                 for t in tags)
    return bool(_COMPROVANTE.search(rotulo))


def _janelas(digitos: str) -> list[str]:
    """Toda linha digitável de 47 ou 48 dígitos dentro de `digitos` que fecha."""
    achadas = []
    for tamanho in (47, 48):
        for i in range(0, max(len(digitos) - tamanho, -1) + 1):
            trecho = digitos[i:i + tamanho]
            if ocr_boleto.valida(trecho):
                achadas.append(trecho)
    return achadas


def _centavos(linha: str) -> int | None:
    v = ocr_boleto.valor_da_linha(linha)
    return None if v is None else round(v * 100)


def _no_bloco(blocos, ocr: bool, aceitos=None) -> set[str]:
    achados: set[str] = set()
    for bloco in blocos:
        tentativas = (bloco, bloco.translate(ocr_boleto._CONFUSOES)) if ocr else (bloco,)
        for tentativa in tentativas:
            for linha in _janelas(ocr_boleto.digitos(tentativa)):
                if aceitos is None or _centavos(linha) in aceitos:
                    achados.add(ocr_boleto.codigo_de_barras(linha))
    return achados


def codigos_no_texto(texto: str, valores=(), ocr: bool = False) -> set[str]:
    """Os códigos de barras (44 dígitos) que o texto traz, ou vazio.

    `valores` (centavos) só serve para o último degrau -- o texto inteiro
    colado, quando o OCR espalhou o código por mais de duas linhas. `ocr`
    liga o mapa de confusões: só para texto que veio de OCR.
    """
    if not texto:
        return set()
    linhas = [l for l in texto.splitlines() if any(c.isdigit() for c in l)]
    achados = (_no_bloco(linhas, ocr)
               or _no_bloco([a + b for a, b in zip(linhas, linhas[1:])], ocr))
    if achados or not valores:
        return achados
    return _no_bloco([texto], ocr, {int(v) for v in valores if v})


def texto_de_pdf(dados: bytes) -> str:
    """Camada de texto de um PDF; vazio se não houver ou não abrir."""
    if not dados:
        return ""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(dados)) as pl:
            return "\n".join((pg.extract_text() or "") for pg in pl.pages[:3])
    except Exception:                                        # noqa: BLE001
        return ""


def texto_do_arquivo(nome: str, dados: bytes,
                     log=lambda *_: None) -> tuple[str, bool]:
    """(texto, veio_de_ocr) de um PDF -- camada de texto, OCR se ela vier
    vazia -- ou de uma foto.

    OCR só no que não tem texto: é ele que custa. Falha aqui devolve vazio --
    sem código, o casamento segue com as regras de sempre.
    """
    n = (nome or "").lower()
    if n.endswith(_EXT_IMAGEM):
        return ocr_boleto.texto_ocr_imagem(dados), True
    if not n.endswith(_EXT_PDF):
        return "", False
    texto = texto_de_pdf(dados)
    if sum(c.isdigit() for c in texto) >= 30:
        return texto, False
    lido = ocr_boleto.texto_ocr_pdf(dados, log, limite_paginas=2)
    return (lido, True) if lido else (texto, False)


def _nome_do_anexo(f: dict) -> str:
    nome = str(f.get("filename") or f.get("name") or "")
    ext = str(f.get("extension") or "").strip().lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    return nome if (not ext or nome.lower().endswith(ext)) else nome + ext


def _vals(pe: dict) -> set:
    return set(pe.get("valores") or [pe.get("valor")])


def preencher(pendentes: list[dict], pdfs: list[dict], *, ler_pdf,
              anexos_de, baixar, ler_anexo=texto_do_arquivo,
              cancelar=lambda: False) -> dict:
    """Põe `barras` (conjunto de códigos de 44) nos PDFs e nos pendentes.

    Só lê o que pode mudar um casamento:
      - PDF cujo VALOR é de algum pendente (os outros nem entram na disputa);
      - pendente que tem, entre os PDFs do seu valor, um com código -- sem
        isso, o código do título não teria com quem comparar, e cada título é
        um download (e talvez um OCR) a mais.

    Do título só valem os códigos cujo valor embutido é um dos valores do
    pagamento: título parcelado guarda o boleto de TODAS as parcelas no mesmo
    lugar, e o da parcela vizinha não pode vetar nem casar esta.

    As funções de fora chegam por argumento (a API do ERP só existe dentro da
    página logada): `ler_pdf(pd) -> (texto, ocr)`, `anexos_de(ids) -> {id:
    [anexos]}`, `baixar(url) -> bytes`, `ler_anexo(nome, bytes) -> (texto, ocr)`.
    """
    contagem = {"pdfs_lidos": 0, "pdfs_com_codigo": 0, "titulos_lidos": 0,
                "lancamentos_com_codigo": 0, "sem_titulo": 0}
    valores_pendentes = set().union(*(_vals(pe) for pe in pendentes)) if pendentes else set()
    for pd in pdfs:
        pd.setdefault("barras", set())
        if pd["valor"] not in valores_pendentes or cancelar():
            continue
        contagem["pdfs_lidos"] += 1
        texto, ocr = ler_pdf(pd)
        pd["barras"] = codigos_no_texto(texto, {pd["valor"]}, ocr)
        contagem["pdfs_com_codigo"] += bool(pd["barras"])

    por_valor: dict[int, list] = {}
    for pd in pdfs:
        por_valor.setdefault(pd["valor"], []).append(pd)
    alvos = []
    for pe in pendentes:
        pe.setdefault("barras", set())
        if any(pd["barras"] for v in _vals(pe) for pd in por_valor.get(v, [])):
            alvos.append(pe)
    ids = sorted({str(pe["tradePayableId"]) for pe in alvos if pe.get("tradePayableId")})
    # Sem o id do título a regra não roda -- e não rodar em silêncio parece
    # "nenhum boleto com código". Quem chama avisa.
    contagem["sem_titulo"] = sum(1 for pe in alvos if not pe.get("tradePayableId"))
    if not ids or cancelar():
        return contagem
    anexos = anexos_de(ids) or {}
    lidos: dict[str, tuple] = {}             # url -> (texto, ocr): um download por arquivo
    for pe in alvos:
        if cancelar():
            break
        arquivos = [f for f in (anexos.get(str(pe.get("tradePayableId"))) or [])
                    if f.get("downloadUrl") and not _e_comprovante(f)
                    and _nome_do_anexo(f).lower().endswith(_EXT_PDF + _EXT_IMAGEM)]
        codigos: set[str] = set()
        for f in arquivos[:MAX_ARQUIVOS_POR_TITULO]:
            url = f["downloadUrl"]
            if url not in lidos:
                dados = baixar(url)
                lidos[url] = ler_anexo(_nome_do_anexo(f), dados) if dados else ("", False)
            texto, ocr = lidos[url]
            codigos |= codigos_no_texto(texto, _vals(pe), ocr)
        aceitos = {int(v) for v in _vals(pe) if v}
        pe["barras"] = {c for c in codigos if _valor_das_barras(c) in aceitos}
        contagem["lancamentos_com_codigo"] += bool(pe["barras"])
    contagem["titulos_lidos"] = len(ids)
    return contagem


def _valor_das_barras(barras: str) -> int | None:
    """Centavos embutidos no código de barras de 44 dígitos."""
    if not re.fullmatch(r"\d{44}", barras or ""):
        return None
    if barras[0] == "8":
        return int(barras[4:15])
    return int(barras[9:19])
