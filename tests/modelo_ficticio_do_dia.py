# -*- coding: utf-8 -*-
"""Peças fictícias compartilhadas pelos testes do Excel do dia (workbook extras
e excel_do_dia): a configuração do painel, o mapa de contas e o carregador.
Nenhum dado real; o modelo de cada teste é montado no tmp_path."""
from datetime import date

from conciliacao.config import PlanilhaConfig
from conciliacao.mapping import AccountMapping

HOJE = date(2026, 10, 21)
ROTULOS = ("Conta Alfa - Banco", "Conta Beta - Banco", "Conta Gama - Banco")
PLANILHA = PlanilhaConfig(
    aba="Painel", primeira_linha=8, ultima_linha=10, linha_totais=12,
    ultima_coluna="M", celula_data="E4", celula_total_pagamentos="D12",
    formato_data="DD/MM/YYYY", col_saldo="C", col_pagamento="D",
    col_qtd_sistema="J", col_qtd_banco="K", colunas_formula=("E", "F", "G", "I", "L"))
MAPA = ("model_rows:\n"
        "- row: 8\n  label: Conta Alfa - Banco\n  uuid: uuid-alfa\n"
        "- row: 9\n  label: Conta Beta - Banco\n  uuid: uuid-beta\n"
        "- row: 10\n  label: Conta Gama - Banco\n  uuid: uuid-gama\n")


def carregar_mapa(tmp_path):
    caminho = tmp_path / "mapping.yaml"
    caminho.write_text(MAPA, encoding="utf-8")
    return AccountMapping.load(caminho)
