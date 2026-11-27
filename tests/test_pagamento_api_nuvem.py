# -*- coding: utf-8 -*-
"""O lado do robô na nuvem, com o `rest` trocado por um dublê: nenhuma rede."""
from datetime import date
from decimal import Decimal

import pytest

from pagamento_api import executor as ex
from pagamento_api import nuvem_lote as nl
from pagamento_api import lote as lt

from test_pagamento_api_executor import DOC, Erp, Sicoob, _aberto, _item, _rodar


def _linha(ordem, valor):
    return {"ordem": ordem, "titulo": f"T{ordem}", "alvo": f"T{ordem}", "conta": "OBRA X - SICOOB",
            "tipo": "pix_chave", "dados": "a@b.com", "valor": valor, "favorecido": "F",
            "documento_esperado": DOC, "descricao": "D"}


class Rest:
    def __init__(self, tabelas):
        self.tabelas = tabelas
        self.gravados = []

    def ler(self, tabela, token, colunas="*", filtro=""):
        return self.tabelas.get(tabela, [])

    def inserir(self, tabela, token, linhas, devolver=True):
        self.gravados.append((tabela, linhas))
        return [] if tabela == "lote_evento" and self.tabelas.get("_recusa") else linhas


@pytest.fixture
def rest(monkeypatch):
    def fazer(tabelas):
        r = Rest(tabelas)
        monkeypatch.setattr(nl.rest, "ler", r.ler)
        monkeypatch.setattr(nl.rest, "inserir", r.inserir)
        return r
    return fazer


def test_lote_aprovado_vem_com_os_itens_aprovados(rest):
    rest({"lote_pagamento": [{"id": 7}],
          "lote_aprovacao": [{"lote": 7, "itens": [2, 1], "total": "300.00"}],
          "lote_item": [_linha(1, "100.00"), _linha(2, "200.00")]})
    (lote,) = nl.lotes_aprovados("tok", date(2026, 11, 27))
    assert lote.id == 7 and lote.total == Decimal("300.00")
    assert [i.ordem for i in lote.itens] == [1, 2] and lote.itens[0].tipo == lt.PIX_CHAVE


def test_leitura_incompleta_ou_soma_diferente_nao_paga_nada(rest):
    rest({"lote_pagamento": [{"id": 7}],
          "lote_aprovacao": [{"lote": 7, "itens": [1, 2], "total": "300.00"}],
          "lote_item": [_linha(1, "100.00")]})
    assert nl.lotes_aprovados("tok", date(2026, 11, 27)) == []
    rest({"lote_pagamento": [{"id": 7}],
          "lote_aprovacao": [{"lote": 7, "itens": [1], "total": "999.00"}],
          "lote_item": [_linha(1, "100.00")]})
    assert nl.lotes_aprovados("tok", date(2026, 11, 27)) == []


def test_parado_vale_o_ultimo_botao(rest):
    rest({"robo_parar": [{"acao": "parar"}]})
    assert nl.parado("tok") is True
    rest({"robo_parar": [{"acao": "retomar"}]})
    assert nl.parado("tok") is False
    rest({})
    assert nl.parado("tok") is False


def test_livro_no_teto_de_linhas_falha_fechado(rest):
    rest({"lote_evento": [{"ordem": 1, "estado": "iniciado"}] * nl.TETO_DE_LINHAS})
    with pytest.raises(nl.LeituraCortada):
        nl.LivroNaNuvem("tok", 7).eventos()


def test_um_lote_ilegivel_nao_derruba_os_outros(rest):
    rest({"lote_pagamento": [{"id": 7}, {"id": 8}],
          "lote_aprovacao": [{"lote": 7, "itens": [1], "total": "x"},
                             {"lote": 8, "itens": [], "total": "1.00"}],
          "lote_item": [_linha(1, "100.00")]})
    assert nl.lotes_aprovados("tok", date(2026, 11, 27)) == []


def test_recusa_do_banco_no_iniciado_sobe_sem_pagar(rest, monkeypatch, tmp_path):
    def recusa(tabela, token, linhas, devolver=True):
        raise nl.rest.RecusadoPeloBanco("duplicate key", status=409, codigo="23505")
    rest({})
    monkeypatch.setattr(nl.rest, "inserir", recusa)
    s = Sicoob(pix_iniciar={"endToEndId": "E1", "proprietario": {"identificador": DOC}},
               pix_confirmar={"estado": "REALIZADO"})
    with pytest.raises(nl.rest.RecusadoPeloBanco):
        _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, Erp({"T1": _aberto()}), tmp_path,
               nl.LivroNaNuvem("tok", 7))
    assert "pix_confirmar" not in s.chamadas


def test_evento_que_nao_volta_do_banco_impede_o_pagamento(rest, tmp_path):
    rest({"_recusa": True})
    livro = nl.LivroNaNuvem("tok", 7)
    s = Sicoob(pix_iniciar={"endToEndId": "E1", "proprietario": {"identificador": DOC}},
               pix_confirmar={"estado": "REALIZADO"})
    with pytest.raises(nl.NaoGravou):
        _rodar([_item(1, lt.PIX_CHAVE)], "100.00", s, Erp({"T1": _aberto()}), tmp_path, livro)
    assert "pix_confirmar" not in s.chamadas
    assert ex.INICIADO == "iniciado"
