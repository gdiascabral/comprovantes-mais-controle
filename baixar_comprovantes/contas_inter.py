# -*- coding: utf-8 -*-
"""Quais contas do Inter a fila percorre, e onde os PDFs de cada uma caem.

**Por que isto existe, sendo que o Sicoob nao precisa de nada parecido.** La
um login enumera as contas sozinho: basta entrar e perguntar. No Inter cada
conta e um LOGIN separado, entao ninguem tem como descobri-las — alguem
precisa declarar quais sao.

Quem declara e o cadastro na nuvem, junto das contas do Sicoob: la a conta do
Inter ja existe (banco "INTER", sem numero), e `nuvem/cadastro.py` a escreve
neste arquivo a cada abertura do app. Enquanto a declaracao era um arquivo
escrito a mao, ela existia numa maquina so — a aba mostrava 3 contas do Inter
aqui e nenhuma no computador de qualquer outra pessoa, sem erro na tela.

O arquivo mora FORA do repositorio, ao lado do `contas_sicoob.json` e pela
mesma razao: carrega nome de empresa real, e o repositorio e publico.

    {
      "contas": [
        {"apelido": "EMPRESA A", "empresa": "EMPRESA A", "pasta": "INTER"}
      ]
    }

`apelido` e o que da nome a pasta de perfil do Chrome daquela conta, e por
isso nao muda sem motivo: mudou, o QR daquela conta e pedido do zero.
`empresa` e `pasta` dizem onde arquivar, e saem do mesmo cadastro que o
`contas_sicoob.json` — e por isso a mesma empresa nao nasce com duas pastas de
grafias diferentes.

Sem o arquivo, a lista vem vazia e a aba diz isso. Nao e erro: quem so usa
Sicoob nunca precisa dele.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

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
