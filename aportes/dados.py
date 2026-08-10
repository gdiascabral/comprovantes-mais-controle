# -*- coding: utf-8 -*-
"""
Cadastro local: contas e grupos de investidores.

Estes dados NÃO ficam no repositório — ele é público. Moram em arquivos ao
lado do executável, que o usuário edita no Excel/Bloco de Notas:

    contas.csv      nome_exibicao ; nome_oficial ; conta ; nome_descricao
    subcontas.json  grupos de investidores por subconta (opcional)

Efeito colateral bom de estarem no disco: cadastrar conta pela tela passa a
valer de verdade. Na versão web isso não persistia, porque o servidor apagava
o disco a cada reinício.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    _AQUI = Path(sys.executable).resolve().parent
else:
    _AQUI = Path(__file__).resolve().parent

ARQUIVO_CONTAS = _AQUI / "contas.csv"
ARQUIVO_SUBCONTAS = _AQUI / "subcontas.json"

COLUNAS = ["nome_exibicao", "nome_oficial", "conta", "nome_descricao"]

CENTRO_DE_CUSTO_PADRAO = "Obra"

FORMAS = ["Pix", "Transferência Bancária", "Boleto", "Depósito em conta",
          "Dinheiro"]
TIPOS = ["Aporte de Capital", "Distribuição de Lucro"]
MODOS = ["Pagamento + Recebimento", "Só recebimento", "Só pagamento"]

INVESTIDOR_PREFIXO = "Investidor conta "


def carregar_contas() -> dict:
    """Lê o contas.csv. Devolve {} se não existir — a tela avisa."""
    if not ARQUIVO_CONTAS.exists():
        return {}
    entidades = {}
    with open(ARQUIVO_CONTAS, encoding="utf-8-sig", newline="") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            nome = (linha.get("nome_exibicao") or "").strip()
            if not nome:
                continue
            conta = (linha.get("conta") or "").strip()
            apelido = (linha.get("nome_descricao") or "").strip()
            entidades[nome] = {
                "nome_oficial": (linha.get("nome_oficial") or "").strip(),
                "conta": conta or None,
                # Apelido usado SÓ no texto da descrição: existe para conta
                # conjunta, em que o lançamento sai no nome de uma pessoa mas
                # a descrição precisa citar as duas.
                "nome_descricao": apelido or None,
            }
    return entidades


def acrescentar_conta(nome_exibicao: str, nome_oficial: str,
                      conta: str | None, nome_descricao: str | None = None) -> None:
    novo = not ARQUIVO_CONTAS.exists()
    with open(ARQUIVO_CONTAS, "a", encoding="utf-8-sig", newline="") as f:
        escritor = csv.writer(f, delimiter=";")
        if novo:
            escritor.writerow(COLUNAS)
        escritor.writerow([nome_exibicao.strip(), nome_oficial.strip(),
                           (conta or "").strip(), (nome_descricao or "").strip()])


def carregar_subcontas() -> dict:
    """Grupos de investidores por subconta. Formato:

        {"55696-3": {"obras": ["..."], "investidores": ["..."]}}

    Opcional: sem o arquivo, o app funciona, só não oferece o rateio."""
    if not ARQUIVO_SUBCONTAS.exists():
        return {}
    try:
        dados = json.loads(ARQUIVO_SUBCONTAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def config_obra_padrao() -> str:
    """Obra usada nos lançamentos comuns. Fica no subcontas.json para não
    precisar de mais um arquivo; se faltar, a tela pede."""
    return (carregar_subcontas().get("_obra_padrao") or "").strip()
