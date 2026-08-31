# -*- coding: utf-8 -*-
"""Quais contas do Inter a fila percorre, e onde os PDFs de cada uma caem.

**Por que isto existe, sendo que o Sicoob não precisa de nada parecido.** Lá um
login enumera as contas sozinho: basta entrar e perguntar. No Inter cada conta
é um login separado, então ninguém tem como descobri-las — alguém precisa
declarar quais são, e é este arquivo.

Ele mora FORA do repositório, ao lado do `contas_sicoob.json` e pela mesma
razão: carrega nome de empresa real, e o repositório é público.

    {
      "contas": [
        {"apelido": "MORAIS ENG", "empresa": "MORAIS ENG", "pasta": "INTER"},
        {"apelido": "BURITIS",    "empresa": "BURITIS",    "pasta": "INTER"},
        {"apelido": "VXZ",        "empresa": "VXZ",        "pasta": "INTER"}
      ]
    }

`apelido` é o que dá nome à pasta de perfil do Chrome daquela conta, e por isso
não pode mudar sem motivo: mudou, o QR daquela conta é pedido do zero.
`empresa` e `pasta` dizem onde arquivar, e devem casar com os nomes que o
`contas_sicoob.json` já usa — senão a mesma empresa nasce com duas pastas de
grafias diferentes.

Sem o arquivo, a lista vem vazia e a aba diz isso. Não é erro: quem só usa
Sicoob nunca precisa dele.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

ARQUIVO = "contas_inter.json"


@dataclass(frozen=True)
class ContaInter:
    """Uma conta = um login = um perfil de Chrome = uma leitura de QR."""

    apelido: str
    empresa: str
    pasta: str = "INTER"

    @property
    def valida(self) -> bool:
        return bool(self.apelido.strip() and self.empresa.strip())


def caminho(pasta=None) -> Path:
    return Path(pasta or util.pasta_base()) / ARQUIVO


def carregar(pasta=None) -> list[ContaInter]:
    """As contas declaradas. Lista vazia quando não há arquivo.

    Nunca levanta: a aba precisa abrir mesmo sem o arquivo, mostrando as
    contas do Sicoob e dizendo que o Inter não foi declarado. Um arquivo
    torto não pode impedir o resto do trabalho."""
    alvo = caminho(pasta)
    try:
        dados = json.loads(alvo.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(dados, dict):
        return []
    saida = []
    for linha in dados.get("contas") or []:
        if not isinstance(linha, dict):
            continue
        conta = ContaInter(
            apelido=str(linha.get("apelido") or "").strip(),
            empresa=str(linha.get("empresa") or "").strip(),
            pasta=str(linha.get("pasta") or "INTER").strip() or "INTER")
        if conta.valida:
            saida.append(conta)
    return saida
