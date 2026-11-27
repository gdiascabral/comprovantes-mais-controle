# -*- coding: utf-8 -*-
"""O comprovante em PDF, montado do JSON que o Sicoob devolve.

Sem biblioteca nova (biblioteca nova = exe novo para todo mundo): um PDF de
texto escrito à mão, Helvetica, uma página. A descrição do HTML vai dentro do
PDF e no nome do arquivo. O JSON cru do convênio (o comprovante vem na própria
resposta do pagamento) fica gravado ao lado, para a retomada achar.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import date
from pathlib import Path

#: Campos que aparecem primeiro, nesta ordem, quando existem no JSON.
_PRIMEIROS = ("situacaoPagamento", "estado", "dataPagamento", "horario", "valorPagamento",
              "valor", "nomeRazaoSocialBeneficiario", "numeroCpfCnpjBeneficiario",
              "numeroLinhaDigitavel", "endToEndId", "numeroAutenticacaoPagamento", "nsu",
              "autenticacao")


def _ascii(t) -> str:
    return unicodedata.normalize("NFKD", str(t if t is not None else "")).encode(
        "latin-1", "ignore").decode("latin-1")


def _limpo_para_nome(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t)).encode("ascii", "ignore").decode()
    t = re.sub(r'[\\/:*?"<>|]+', " ", t)
    return " ".join(t.split())


def nome_do_arquivo(item, hoje: date) -> str:
    """Só a DESCRIÇÃO é cortada: o sufixo com valor, título e item é o que deixa
    o nome único (duas parcelas de descrição igual não se sobrescrevem)."""
    valor = f"{item.valor:.2f}".replace(".", ",")
    desc = _limpo_para_nome(item.descricao)[:70].rstrip()
    sufixo = _limpo_para_nome(f"R$ {valor} titulo {item.titulo} item {item.ordem}")
    return f"{hoje:%Y-%m-%d} {desc} {sufixo}".replace("  ", " ") + ".pdf"


def _achatar(d, prefixo="") -> list[tuple[str, str]]:
    linhas = []
    for k, v in (d or {}).items():
        chave = f"{prefixo}{k}"
        if isinstance(v, dict):
            linhas += _achatar(v, chave + ".")
        elif isinstance(v, list):
            linhas.append((chave, json.dumps(v, ensure_ascii=False, default=str)[:200]))
        elif k != "comprovante":          # o base64 do convênio não vai para o texto
            linhas.append((chave, str(v)))
    return linhas


def linhas_do_comprovante(item, dados: dict, hoje: date) -> list[str]:
    pares = _achatar(dados)
    ordem = {k: i for i, k in enumerate(_PRIMEIROS)}
    pares.sort(key=lambda kv: ordem.get(kv[0].rsplit(".", 1)[-1], len(ordem)))
    valor = f"{item.valor:.2f}".replace(".", ",")
    topo = ["COMPROVANTE DE PAGAMENTO - SICOOB (API)",
            f"Descricao: {item.descricao}",
            f"Favorecido: {item.favorecido}",
            f"Valor: R$ {valor}",
            f"Conta: {item.conta}",
            f"Gerado em {hoje:%d/%m/%Y}", ""]
    return topo + [f"{k}: {v}" for k, v in pares]


def _escapar_pdf(t: str) -> str:
    return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def pdf_de_texto(linhas: list[str]) -> bytes:
    """Uma página A4, Helvetica 10, uma linha por item (corta o que não cabe)."""
    corpo = ["BT", "/F1 10 Tf", "40 800 Td", "13 TL"]
    for ln in linhas[:58]:
        corpo.append(f"({_escapar_pdf(_ascii(ln)[:110])}) Tj T*")
    corpo.append("ET")
    stream = "\n".join(corpo).encode("latin-1")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    saida = bytearray(b"%PDF-1.4\n")
    posicoes = []
    for n, o in enumerate(objs, start=1):
        posicoes.append(len(saida))
        saida += f"{n} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(saida)
    saida += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for p in posicoes:
        saida += f"{p:010d} 00000 n \n".encode()
    saida += (f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n").encode()
    return bytes(saida)


def gerar_pdf(pasta: Path, item, dados: dict, hoje: date) -> Path:
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / nome_do_arquivo(item, hoje)
    destino.write_bytes(pdf_de_texto(linhas_do_comprovante(item, dados, hoje)))
    return destino


def _bruto(pasta: Path, item, tipo: str) -> Path:
    # A pasta é a do LOTE (o robô passa uma por lote): título + ordem não se
    # repetem dentro de um lote aprovado, que é imutável no banco.
    return Path(pasta) / _limpo_para_nome(f"bruto-{tipo}-{item.titulo}-{item.ordem}.json")


def salvar_bruto(pasta: Path, item, tipo: str, dados: dict) -> Path:
    """É a ÚNICA cópia do comprovante do convênio: grava inteiro ou não grava."""
    Path(pasta).mkdir(parents=True, exist_ok=True)
    p = _bruto(pasta, item, tipo)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(dados, ensure_ascii=False, default=str), encoding="utf-8")
    os.replace(tmp, p)
    return p


def ler_bruto(pasta: Path, item, tipo: str) -> dict | None:
    p = _bruto(pasta, item, tipo)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return None
