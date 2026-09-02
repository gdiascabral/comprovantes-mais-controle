# -*- coding: utf-8 -*-
"""A cópia local do cadastro — que são os arquivos de sempre.

A escolha que sustenta este módulo: o cache **não é um formato novo**. É o
mesmo `contas_sicoob.json`, o mesmo `contas.csv`, nos mesmos lugares. Assim
`sicoob_contas.carregar`, `contas_mc.carregar` e `dados.carregar_contas`
continuam lendo o que sempre leram, e o banco entra como ORIGEM sem que
nenhum deles precise saber que ele existe.

Um formato próprio de cache teria criado duas verdades sobre a mesma conta —
que é exatamente o problema que a nuvem veio resolver.

Dois cuidados que não são óbvios:

- **Gravar é atômico.** Escreve num arquivo ao lado e só então troca. Queda de
  luz no meio de um `write_text` deixa o arquivo pela metade, e um
  `contas_sicoob.json` truncado é pior que nenhum: o app abre, lê meia lista
  de contas e arquiva o mês só até a letra M.
- **A ajuda é preservada.** As chaves `_leia_me`, `_ajuda` e `_campos` são
  para quem abre o arquivo no Bloco de Notas. Elas não vêm do banco, então
  são lidas do arquivo antigo e recolocadas.
"""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path

import util


def caminho(nome: str, pasta=None) -> Path:
    return Path(pasta or util.pasta_base()) / nome


def existe(nome: str, pasta=None) -> bool:
    return caminho(nome, pasta).exists()


def ler_json(nome: str, pasta=None) -> dict:
    """O que está no disco hoje. {} se não houver ou não der para ler."""
    p = caminho(nome, pasta)
    if not p.exists():
        return {}
    try:
        dados = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def _ajuda_de(nome: str, pasta=None) -> dict:
    """As chaves que começam com `_`: explicação para quem abre o arquivo."""
    return {k: v for k, v in ler_json(nome, pasta).items() if k.startswith("_")}


def _trocar(p: Path, conteudo: bytes) -> None:
    """Grava ao lado e troca. `os.replace` é atômico no mesmo volume."""
    temp = p.with_suffix(p.suffix + ".novo")
    temp.write_bytes(conteudo)
    os.replace(temp, p)


def gravar_json(nome: str, dados: dict, pasta=None) -> None:
    """Regrava o arquivo, mantendo a ajuda que já estava nele."""
    saida = dict(_ajuda_de(nome, pasta))
    saida.update(dados)
    _trocar(caminho(nome, pasta),
            (json.dumps(saida, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def gravar_csv(nome: str, colunas: list[str], linhas: list[dict],
               pasta=None) -> None:
    """Regrava um CSV com `;`, como o Excel brasileiro espera.

    `utf-8-sig` porque é o que `dados.carregar_contas` lê — sem o BOM, o
    Excel abre "MORAIS" como "MORAIS" com acento quebrado."""
    buf = io.StringIO(newline="")
    escritor = csv.DictWriter(buf, fieldnames=colunas, delimiter=";",
                              extrasaction="ignore", lineterminator="\r\n")
    escritor.writeheader()
    escritor.writerows(linhas)
    _trocar(caminho(nome, pasta), buf.getvalue().encode("utf-8-sig"))
