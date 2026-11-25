# -*- coding: utf-8 -*-
"""O PDF do relatório de aportes e distribuições (`relatorio_aportes`),
desenhado com o Pillow que já vai no exe — a mesma escolha da Prova de saldos
(`prova_pdf`, spec de 27/10/2026: sem biblioteca de PDF nova). A4 em pé a
150 dpi; o texto não é selecionável, então o que importa conferir sai de
funções puras (`linhas_do_documento`) e é testado ali.

Página 1: o resumo (por sócio, quando há mais de um, e mês a mês). Depois o
detalhe dos aportes e o das distribuições. Sem saldo, sem "para igualar" e
sem nota interna: é o que vai para o sócio.
"""
from __future__ import annotations

import datetime
import os
from pathlib import Path

from PIL import Image, ImageDraw

from . import relatorio_aportes as ra
from .prova_pdf import _cortar, _escrever, fonte
from .valores import brl

DPI = 150
LARGURA, ALTURA = 1240, 1754            # A4 em pé a 150 dpi
MARGEM = 90
RODAPE = 70
BRANCO = (255, 255, 255)
PRETO = (20, 20, 20)
CINZA = (110, 110, 110)
FAIXA = (238, 241, 246)
QUALIDADE_JPEG = 95

#: (tipo, altura em px) de cada linha do documento.
ALTURAS = {"titulo": 70, "sub": 40, "secao": 80, "cab": 46, "linha": 40, "total": 50,
           "vazio": 40, "espaco": 30}
#: Colunas (x inicial, alinhamento) de cada tabela; valores alinham à direita.
DIREITA = LARGURA - MARGEM
COLUNAS = {
    "socio": ((MARGEM, "e"), (DIREITA - 260, "d"), (DIREITA, "d")),
    "mes": ((MARGEM, "e"), (DIREITA - 260, "d"), (DIREITA, "d")),
    "mov": ((MARGEM, "e"), (MARGEM + 170, "e"), (MARGEM + 470, "e"), (DIREITA, "d")),
}
_CORTE = {"socio": (48, 20, 20), "mes": (30, 20, 20), "mov": (16, 26, 34, 20)}


def linhas_do_documento(rel: ra.Relatorio, gerado: datetime.datetime) -> list:
    """[(tipo, tabela, células)] na ordem em que vão ao papel. `cab` repete
    no alto da página quando a tabela continua."""
    doc = [("titulo", "", ("Aportes e distribuições de lucros",)),
           ("sub", "", (rel.empresa,)),
           ("sub", "", (f"Sócio: {ra.titulo_dos_socios(rel)}",)),
           ("sub", "", (f"Período: {rel.de:%d/%m/%Y} a {rel.ate:%d/%m/%Y}  ·  "
                        f"gerado em {gerado:%d/%m/%Y %H:%M}",))]
    if len(rel.socios) > 1:
        doc += [("secao", "", ("Por sócio",)),
                ("cab", "socio", ("SÓCIO", "APORTOU", "RECEBEU"))]
        doc += [("linha", "socio", (s, brl(a), brl(d))) for s, a, d in ra.resumo_por_socio(rel)]
        doc.append(("total", "socio", ("Total", brl(rel.total_aportes),
                                       brl(rel.total_distribuicoes))))
    doc += [("secao", "", ("Mês a mês",)),
            ("cab", "mes", ("MÊS", "APORTES", "DISTRIBUIÇÕES"))]
    meses = ra.resumo_mensal(rel)
    doc += [("linha", "mes", (ra.nome_do_mes(m), brl(a), brl(d))) for m, a, d in meses]
    if not meses:
        doc.append(("vazio", "", ("Nenhum aporte nem distribuição no período.",)))
    doc.append(("total", "mes", ("Total", brl(rel.total_aportes), brl(rel.total_distribuicoes))))
    for titulo, lista, quem in (("Aportes", rel.aportes, "QUEM APORTOU"),
                                ("Distribuições de lucros", rel.distribuicoes, "PARA")):
        doc += [("pagina", "", ()),
                ("secao", "", (f"{titulo} ({len(lista)})",)),
                ("cab", "mov", ("DATA", "CONTA" if lista is rel.aportes else "SAIU DE",
                                quem, "VALOR"))]
        doc += [("linha", "mov", (f"{m.data:%d/%m/%Y}", ra.banco_da_conta(m.conta) or "—",
                                  m.socio, brl(m.valor))) for m in lista]
        if not lista:
            doc.append(("vazio", "", ("Nenhum no período.",)))
        total = rel.total_aportes if lista is rel.aportes else rel.total_distribuicoes
        doc.append(("total", "mov", ("Total", "", "", brl(total))))
    return doc


def paginar(doc) -> list:
    """As linhas em páginas. Quebra no "pagina" e onde não cabe; a tabela que
    continua na página seguinte leva o cabeçalho de novo."""
    paginas, atual, y = [], [], MARGEM
    limite = ALTURA - MARGEM - RODAPE
    cab_vigente = None
    for item in doc:
        tipo, tabela, _ = item
        if tipo == "pagina":
            if atual:
                paginas.append(atual)
            atual, y, cab_vigente = [], MARGEM, None
            continue
        if tipo == "cab":
            cab_vigente = item
        elif tipo in ("secao", "titulo"):
            cab_vigente = None
        altura = ALTURAS[tipo]
        if y + altura > limite and atual:
            paginas.append(atual)
            atual, y = [], MARGEM
            if tipo in ("linha", "total") and cab_vigente is not None:
                atual.append(cab_vigente)
                y += ALTURAS["cab"]
        atual.append(item)
        y += altura
    if atual:
        paginas.append(atual)
    return paginas or [[]]


def _desenhar(itens, numero: int, total: int, rel: ra.Relatorio) -> Image.Image:
    img = Image.new("RGB", (LARGURA, ALTURA), BRANCO)
    d = ImageDraw.Draw(img)
    y = MARGEM
    for tipo, tabela, celulas in itens:
        altura = ALTURAS[tipo]
        if tipo == "titulo":
            _escrever(d, (MARGEM, y), celulas[0], font=fonte(40, True), fill=PRETO)
        elif tipo == "sub":
            _escrever(d, (MARGEM, y), _cortar(celulas[0], 90), font=fonte(22), fill=CINZA)
        elif tipo == "secao":
            _escrever(d, (MARGEM, y + 30), celulas[0], font=fonte(28, True), fill=PRETO)
        elif tipo == "vazio":
            _escrever(d, (MARGEM, y + 8), celulas[0], font=fonte(20), fill=CINZA)
        else:
            negrito = tipo in ("cab", "total")
            if tipo == "cab":
                d.rectangle((MARGEM - 10, y, DIREITA + 10, y + altura - 6), fill=FAIXA)
            if tipo == "total":
                d.line((MARGEM, y + 4, DIREITA, y + 4), fill=CINZA, width=2)
            f = fonte(18 if tipo == "cab" else 20, negrito)
            for (x, alinhar), texto, corte in zip(COLUNAS[tabela], celulas, _CORTE[tabela]):
                texto = _cortar(str(texto), corte)
                if alinhar == "d":
                    x = x - d.textlength(texto, font=f)
                _escrever(d, (x, y + (14 if tipo == "total" else 10)), texto, font=f,
                          fill=PRETO)
        y += altura
    rodape = f"{rel.empresa}  ·  página {numero} de {total}"
    _escrever(d, (MARGEM, ALTURA - MARGEM), _cortar(rodape, 100), font=fonte(16), fill=CINZA)
    return img


def gerar(rel: ra.Relatorio, destino, gerado: datetime.datetime | None = None) -> Path:
    destino = Path(destino)
    gerado = gerado or datetime.datetime.now()
    blocos = paginar(linhas_do_documento(rel, gerado))
    paginas = [_desenhar(b, i, len(blocos), rel) for i, b in enumerate(blocos, 1)]
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_name(destino.name + ".tmp")
    paginas[0].save(tmp, "PDF", resolution=float(DPI), save_all=True,
                    append_images=paginas[1:], quality=QUALIDADE_JPEG, subsampling=0)
    os.replace(tmp, destino)
    return destino
