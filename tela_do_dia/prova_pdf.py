# -*- coding: utf-8 -*-
"""O PDF da Prova de saldos, desenhado com o Pillow que já vai no exe.

Sem biblioteca de PDF nova (decisão do spec de 27/10/2026): cada página é uma
imagem A4 deitada a 150 dpi e o PDF sai de `Image.save(save_all=True)`. Por
isso o texto do PDF não é selecionável — o que importa conferir é montado por
funções puras (`titulo`, `textos_da_conta`, `ps.celulas`) e testado ali.

**Prints legíveis no celular** (revisão de 27/10/2026): o grupo abre o PDF
no WhatsApp, e o zoom de lá não recupera o que foi reamostrado aqui. Cada
print entra a 1:1 e só é reduzido o que passa da `LARGURA_UTIL` (nunca
ampliado); ERP em cima, banco embaixo, cada um na largura toda; o que não
couber continua em outra página. A página vai em JPEG de qualidade alta e
cor sem subamostragem (`QUALIDADE_JPEG`): o Pillow grava página RGB em DCT,
e a qualidade padrão punha halo no texto pequeno.

As cores são tuplas RGB DAQUI e não da `widgets.PALETA`: isto é papel
impresso, não tema da tela (o dark mode não vale para PDF).

A situação sai em palavra colorida (BATE / NÃO BATE / NÃO LIDA): a Arial e a
Segoe UI não têm os glifos ✅/❌, que ficam no Registro da aba.
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import prova_saldos as ps
from .valores import brl

DPI = 150
LARGURA, ALTURA = 1754, 1240            # A4 deitado a 150 dpi
MARGEM = 60
LINHAS_POR_PAGINA = 18
ALTURA_LINHA = 52
LARGURA_UTIL = LARGURA - 2 * MARGEM      # 1634 px: print mais largo é reduzido a isto
#: Medidas pelo `test_colunas_do_resumo_cabem_na_pagina`: HORA BANCO em
#: negrito começava em 1600 e passava da margem direita.
COLUNAS_X = (MARGEM, 540, 760, 980, 1190, 1380, 1530)
QUALIDADE_JPEG = 95
ALTURA_TITULO = 70
ALTURA_LEGENDA = 40
ALTURA_SEM_PRINT = 90
ESPACO = 30
BRANCO = (255, 255, 255)
PRETO = (20, 20, 20)
CINZA = (110, 110, 110)
COR = {ps.BATE: (22, 128, 61), ps.NAO_BATE: (185, 28, 28), ps.NAO_LIDA: (180, 83, 9)}
_PASTA_FONTES = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
_NOMES = {False: ("arial.ttf", "segoeui.ttf"), True: ("arialbd.ttf", "segoeuib.ttf")}


def fonte(tamanho: int, negrito: bool = False):
    """A fonte do Windows; sem ela, a padrão do Pillow. Sem o FreeType no
    exe (`_imagingft`), `truetype` levanta ImportError, e não OSError: aí
    sobra a fonte de bitmap, pequena mas legível — o PDF sai do mesmo jeito."""
    for nome in _NOMES[negrito]:
        caminho = _PASTA_FONTES / nome
        if caminho.is_file():
            try:
                return ImageFont.truetype(str(caminho), tamanho)
            except (OSError, ImportError):
                continue
    try:
        return ImageFont.load_default(size=tamanho)
    except (OSError, ImportError):
        return ImageFont.load_default_imagefont()


_TROCAS_LATIN1 = {"—": "-", "–": "-", "…": "...", "✅": "", "❌": "", "⚠": "!"}


def _escrever(d, xy, texto, font, fill) -> None:
    """`d.text`, mas a fonte de bitmap (exe sem FreeType) só tem latin-1: o
    travessão e as reticências viram ASCII em vez de derrubar o PDF."""
    if not isinstance(font, ImageFont.FreeTypeFont):
        for de, para in _TROCAS_LATIN1.items():
            texto = texto.replace(de, para)
        texto = texto.encode("latin-1", "replace").decode("latin-1")
    d.text(xy, texto, font=font, fill=fill)


def _cortar(texto: str, n: int) -> str:
    return texto if len(texto) <= n else texto[: n - 1] + "…"


def _pagina() -> Image.Image:
    return Image.new("RGB", (LARGURA, ALTURA), BRANCO)


def titulo(quando) -> str:
    return f"Prova de saldos — {quando:%d/%m/%Y %H:%M}"


def paginas_do_resumo(linhas) -> list:
    linhas = list(linhas)
    if not linhas:
        return [[]]
    return [linhas[i:i + LINHAS_POR_PAGINA] for i in range(0, len(linhas), LINHAS_POR_PAGINA)]


def _desenhar_resumo(bloco, quando, pagina: int, total: int, contagem: str) -> Image.Image:
    img = _pagina()
    d = ImageDraw.Draw(img)
    _escrever(d, (MARGEM, MARGEM), titulo(quando), font=fonte(40, True), fill=PRETO)
    sufixo = f" · página {pagina} de {total}" if total > 1 else ""
    _escrever(d, (MARGEM, MARGEM + 60), contagem + sufixo, font=fonte(24), fill=CINZA)
    y = MARGEM + 120
    cabecalho = fonte(20, True)
    for x, nome in zip(COLUNAS_X, ps.COLUNAS):
        _escrever(d, (x, y), nome, font=cabecalho, fill=PRETO)
    y += 36
    d.line((MARGEM, y, LARGURA - MARGEM, y), fill=CINZA, width=2)
    y += 10
    corpo, nota = fonte(20), fonte(16)
    for linha in bloco:
        for i, (x, valor) in enumerate(zip(COLUNAS_X, ps.celulas(linha, com_marca=False))):
            texto = _cortar(valor, 38) if i == 0 else valor
            if i == 4:
                texto = texto.upper()
            _escrever(d, (x, y), texto, font=corpo,
                      fill=COR[linha.situacao] if i == 4 else PRETO)
        if linha.motivo:
            _escrever(d, (MARGEM + 20, y + 26), _cortar(linha.motivo, 150), font=nota,
                      fill=CINZA)
        y += ALTURA_LINHA
    return img


def legenda(lado: str, leitura) -> str:
    if leitura.saldo is None:
        return f"{lado}: não lido — {leitura.motivo or ps.NAO_LIDO}"
    return f"{lado}: {brl(leitura.saldo)} · lido às {ps.hora(leitura)}"


def textos_da_conta(linha) -> list:
    banco = "Sicoob" if linha.conta.banco == ps.SICOOB else "Inter"
    textos = [f"{linha.conta.rotulo} — {ps.PALAVRA[linha.situacao].upper()}",
              legenda("ERP (Mais Controle)", linha.erp),
              legenda(f"Banco ({banco})", linha.banco)]
    if linha.motivo:
        textos.append(linha.motivo)
    return textos


def _abrir_print(leitura):
    """O print em RGB, ou None (sem print ou arquivo que não abre)."""
    if leitura.imagem is None:
        return None
    try:
        with Image.open(leitura.imagem) as aberta:
            return aberta.convert("RGB")
    except (OSError, ValueError):
        return None                # arquivo que não abre vira a caixa com o porquê


def escala_do_print(largura: int, altura: int, altura_max: int) -> float:
    """Nunca amplia; reduz só o que passa da largura útil (ou de uma página
    inteira de altura — print mais alto que a página não tem outro jeito)."""
    return min(1.0, LARGURA_UTIL / largura, altura_max / altura)


def paginas_da_conta(linha) -> list:
    """As páginas de UMA conta: título, ERP em cima e banco embaixo, cada
    print na largura toda; o bloco que não cabe vai para outra página."""
    textos = textos_da_conta(linha)
    paginas: list = []
    altura_max = ALTURA - 2 * MARGEM - ALTURA_TITULO - ALTURA_LEGENDA

    def nova():
        img = _pagina()
        d = ImageDraw.Draw(img)
        sufixo = " (continuação)" if paginas else ""
        _escrever(d, (MARGEM, MARGEM), _cortar(textos[0], 70) + sufixo, font=fonte(34, True),
               fill=COR[linha.situacao])
        paginas.append(img)
        return img, d, MARGEM + ALTURA_TITULO

    img, d, y = nova()
    topo = y
    for texto, leitura in zip(textos[1:3], (linha.erp, linha.banco)):
        foto = _abrir_print(leitura)
        if foto is not None:
            escala = escala_do_print(foto.width, foto.height, altura_max)
            tamanho = (max(1, round(foto.width * escala)), max(1, round(foto.height * escala)))
            if tamanho != foto.size:
                foto = foto.resize(tamanho, Image.Resampling.LANCZOS)
        altura = foto.height if foto is not None else ALTURA_SEM_PRINT
        if y > topo and y + ALTURA_LEGENDA + altura > ALTURA - MARGEM:
            img, d, y = nova()
        _escrever(d, (MARGEM, y), _cortar(texto, 130), font=fonte(22), fill=PRETO)
        y += ALTURA_LEGENDA
        if foto is not None:
            img.paste(foto, (MARGEM, y))
        else:
            d.rectangle((MARGEM, y, MARGEM + LARGURA_UTIL, y + altura), outline=CINZA,
                        width=2)
            porque = leitura.sem_imagem or "sem print"
            _escrever(d, (MARGEM + 20, y + 30), _cortar(f"Sem print: {porque}", 130),
                   font=fonte(20), fill=CINZA)
        y += altura + ESPACO
    if len(textos) > 3:
        if y + ALTURA_LEGENDA > ALTURA - MARGEM:
            img, d, y = nova()
        _escrever(d, (MARGEM, y), _cortar(textos[3], 140), font=fonte(18), fill=CINZA)
    return paginas


def gerar(linhas, quando, destino) -> Path:
    destino = Path(destino)
    linhas = list(linhas)
    blocos = paginas_do_resumo(linhas)
    contagem = ps.texto_da_contagem(linhas)
    paginas = [_desenhar_resumo(b, quando, i, len(blocos), contagem)
               for i, b in enumerate(blocos, 1)]
    for linha in linhas:
        paginas += paginas_da_conta(linha)
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".tmp")
    paginas[0].save(tmp, "PDF", resolution=float(DPI), save_all=True,
                    append_images=paginas[1:], quality=QUALIDADE_JPEG, subsampling=0)
    os.replace(tmp, destino)
    return destino
