# -*- coding: utf-8 -*-
"""
Mapa conta do Mais Controle -> pasta de destino do extrato.

A LISTA de contas não sai daqui: ela é lida do ERP a cada execução, para que
conta nova apareça sozinha. Este mapa responde só uma pergunta — "onde salvo o
extrato desta conta?" — e admite não saber: conta sem destino vira aviso antes
de qualquer download, nunca arquivo no lugar errado.

O arquivo `contas_mc.json` fica FORA do repositório (nome de empresa e número
de conta), como o `contas_sicoob.json` e o `pix_reembolso.json`.

Sem navegador e sem tkinter: roda inteiro em teste.
"""
from __future__ import annotations

import json
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

MESES = ("JANEIRO", "FEVEREIRO", "MARÇO", "ABRIL", "MAIO", "JUNHO",
         "JULHO", "AGOSTO", "SETEMBRO", "OUTUBRO", "NOVEMBRO", "DEZEMBRO")

# Limite prático do Windows. Os caminhos daqui são longos (empresa + subconta
# com descrição), e o .zip do fechamento ainda entra por cima.
LIMITE_CAMINHO = 260


if getattr(sys, "frozen", False):
    _AQUI = Path(sys.executable).resolve().parent
else:
    _AQUI = Path(__file__).resolve().parent

ARQUIVO_MAPA = _AQUI / "contas_mc.json"


class MapaInvalido(RuntimeError):
    """O JSON não existe, não é JSON, ou não descreve um mapa utilizável."""


@dataclass
class Destino:
    erp: str                    # nome exato da conta no Mais Controle
    empresa: str                # "BURITIS"
    pasta: str                  # "SICOOB" ou "CAIXA/APLICAÇÃO"
    banco: str                  # entra no nome do arquivo
    sufixo: str = ""            # desempate quando várias contas dividem a pasta


@dataclass
class Mapa:
    raiz: Path
    destinos: list[Destino]

    def de(self, nome_erp: str) -> Destino | None:
        alvo = _chave(nome_erp)
        return next((d for d in self.destinos if _chave(d.erp) == alvo), None)


def _chave(texto: str) -> str:
    """Compara nomes de conta sem tropeçar em acento, caixa ou espaço duplo.

    O nome vem do cadastro do ERP e é digitado por gente: "Morais Participações"
    e "MORAIS PARTICIPACOES" são a mesma conta."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().split())


# ---------------------------------------------------------------- leitura

def carregar(caminho: Path | None = None) -> Mapa:
    caminho = caminho or ARQUIVO_MAPA
    if not caminho.exists():
        raise MapaInvalido(
            f"O mapa de contas não existe:\n{str(caminho).replace(chr(92), '/')}\n\n"
            "Ele diz em que pasta cada conta do Mais Controle deve ser salva.")
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise MapaInvalido(f"Não consegui ler {caminho.name}: {e}") from e
    if not isinstance(dados, dict) or not dados.get("contas"):
        raise MapaInvalido(f"{caminho.name} não tem a lista 'contas'.")

    destinos = []
    for i, c in enumerate(dados["contas"], 1):
        faltando = [k for k in ("erp", "empresa", "pasta", "banco") if not c.get(k)]
        if faltando:
            raise MapaInvalido(
                f"A conta nº {i} está sem: {', '.join(faltando)}.")
        destinos.append(Destino(erp=c["erp"].strip(), empresa=c["empresa"].strip(),
                                pasta=c["pasta"].strip(), banco=c["banco"].strip(),
                                sufixo=(c.get("sufixo") or "").strip()))
    return Mapa(raiz=Path(dados.get("raiz") or "C:/Arquivos Morais/EXTRATOS"),
                destinos=destinos)


# -------------------------------------------------------------- caminhos

def nome_arquivo(destino: Destino, ano: int, mes: int) -> str:
    """`202607 SICOOB MAIS CONTROLE.pdf`, com o número da conta no fim quando
    várias contas dividem a mesma pasta (caso da Moura Dantas)."""
    base = f"{ano}{mes:02d} {destino.banco} MAIS CONTROLE"
    if destino.sufixo:
        base += f" {destino.sufixo}"
    return base + ".pdf"


def caminho_do_mes(mapa: Mapa, ano: int, mes: int) -> Path:
    return mapa.raiz / str(ano) / MESES[mes - 1]


def caminho_do_arquivo(mapa: Mapa, destino: Destino, ano: int, mes: int) -> Path:
    pasta = (caminho_do_mes(mapa, ano, mes)
             / f"{MESES[mes - 1]} {ano} - {destino.empresa}"
             / destino.pasta)
    return pasta / nome_arquivo(destino, ano, mes)


def resolver(mapa: Mapa, contas: list[dict], ano: int, mes: int) -> tuple[list[tuple], list[str]]:
    """Casa as contas lidas do ERP com o mapa.

    Devolve (pares, desconhecidas): cada par é (conta, destino, caminho). As
    desconhecidas travam o lote antes do primeiro download — é preferível não
    baixar nada a espalhar PDF sem destino certo."""
    pares, desconhecidas = [], []
    for conta in contas:
        d = mapa.de(conta.get("nome", ""))
        if d is None:
            desconhecidas.append(conta.get("nome", "?"))
        else:
            pares.append((conta, d, caminho_do_arquivo(mapa, d, ano, mes)))
    return pares, desconhecidas


def caminhos_longos(mapa: Mapa, ano: int, mes: int) -> list[tuple[str, int]]:
    """Destinos que passam do limite do Windows, com o tamanho de cada um.

    Vale conferir antes de rodar: o erro de caminho longo aparece como falha de
    escrita no meio do lote, e a causa não é óbvia para quem está olhando."""
    fora = []
    for d in mapa.destinos:
        n = len(str(caminho_do_arquivo(mapa, d, ano, mes)))
        if n > LIMITE_CAMINHO:
            fora.append((d.erp, n))
    return fora
