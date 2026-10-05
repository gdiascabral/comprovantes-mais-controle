# -*- coding: utf-8 -*-
"""Gravar "este cliente do ERP é desta empresa" onde a escolha sobrevive.

A aba Contratos pergunta, na hora de arquivar, de qual empresa é o cliente de
uma obra. Até 05/10/2026 a resposta ia só para o `contas_sicoob.json` — que é
CACHE: `nuvem.cadastro.sincronizar` o regrava inteiro a cada abertura a partir
da tabela `cliente_erp`. A escolha sumia na abertura seguinte e a casa voltava
a pedir resolução no mês seguinte.

Mesma ordem do "Novo cadastro" dos Aportes (`aportes/novo_cadastro.gravar`):
banco primeiro, cache depois. Banco recusou, o cache fica como estava — linha
só no cache seria a mesma ilusão de antes.

As travas de `sicoob_contas.adicionar_cliente_erp` valem aqui também, e são
conferidas contra o banco FRESCO, não contra o cache: outra máquina pode ter
gravado o mesmo cliente desde a última abertura.

1. cliente que já é de OUTRA empresa não muda de dono em silêncio;
2. cliente que já é DESTA empresa não é inserido de novo (o índice único em
   `lower(nome)` responderia 409) — só o cache é posto em dia.

Só INSERT, como em `entidade`: tirar um cliente de uma empresa continua sendo
assunto do painel.
"""
from __future__ import annotations

from pathlib import Path

import util
from extratos_sicoob import sicoob_contas

from . import rest


def gravar(token: str, empresa: str, cliente: str,
           caminho: Path | None = None) -> None:
    """Grava na nuvem e, só depois, no `contas_sicoob.json` desta máquina."""
    alvo, cliente = util.norm_espaco(empresa or ""), (cliente or "").strip()
    if not alvo or not cliente:
        raise sicoob_contas.MapaInvalido(
            "Preciso da empresa e do cliente para gravar.")

    empresas = rest.ler("empresa", token, colunas="id,nome_pasta")
    por_id = {e["id"]: e["nome_pasta"] for e in empresas}
    empresa_id = next((i for i, nome in por_id.items()
                       if util.norm_espaco(nome or "") == alvo), None)
    if empresa_id is None:
        raise sicoob_contas.MapaInvalido(
            f"A empresa '{empresa}' não está no cadastro da nuvem.")

    chave = util.norm_espaco(cliente)
    ja_tem = [c for c in rest.ler("cliente_erp", token,
                                  colunas="empresa_id,nome")
              if util.norm_espaco(c.get("nome") or "") == chave]
    dono = next((c["empresa_id"] for c in ja_tem), None)
    if dono is not None and dono != empresa_id:
        raise sicoob_contas.MapaInvalido(
            f"O cliente '{cliente}' já está na empresa "
            f"'{por_id.get(dono, dono)}'.\n"
            f"Um cliente do ERP em duas empresas manda o contrato para a "
            f"pasta errada. Tire de lá antes de pôr em '{empresa}'.")
    if dono is None:
        rest.inserir("cliente_erp", token,
                     [{"empresa_id": empresa_id, "nome": cliente}])

    sicoob_contas.adicionar_cliente_erp(empresa, cliente, caminho)
