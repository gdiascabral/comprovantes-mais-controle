# -*- coding: utf-8 -*-
"""As tarefas da obra em `aportes.mc_catalogos.Catalogos`, sem navegador.

Em 09/09/2026 `task_da_obra` estourava com
`TypeError: Catalogos._dados() takes 1 positional argument but 2 were given`.
Os métodos de tarefa vieram do ANEXAR BOLETOS, e quatro deles (`_dados`,
`_motivo`, `nome_da_tarefa`, `_ordem_do_indice`) foram escritos sem `self` e
sem `@staticmethod`: chamados como método, o Python passa a instância como
primeiro argumento e sobra um. E `tarefas_da_obra` lia `_cache_tarefas`,
`erros_tarefas` e `_host_graphql`, que a cópia de origem definia e o
`__init__` daqui não. Nenhum teste passava por ali — quem passou foi o
coletor de concessionárias, na máquina de quem usa.

Tudo aqui é sintético: obra, planejamento, host e tarefas são inventados.
"""
import pytest

from aportes.mc_catalogos import Catalogos

HOST = "abcd1234.execute-api.sa-east-1.amazonaws.com"
OBRA = "obra-0001"
PLANO = "plano-0001"

# De propósito fora de ordem, com "20.10" ANTES de "20.1": sem ordenar, o
# primeiro da lista venceria; ordenando como texto, "20.10" vem antes de
# "20.9". Só a ordem numérica escolhe "20.1".
TAREFAS = [
    {"id": "t-3", "index": "3", "name": "Fundação", "fullname": "3",
     "discriminator": "ITEM"},
    {"id": "t-20-10", "index": "20.10", "description": "INSS (pessoa física)",
     "fullname": "20.10", "discriminator": "ITEM"},
    {"id": "t-20-9", "index": "20.9", "description": "INSS (pessoa física)",
     "fullname": "20.9", "discriminator": "ITEM"},
    {"id": "t-20-1", "index": "20.1", "description": "INSS (pessoa física)",
     "fullname": "20.1", "discriminator": "ITEM"},
    # Etapa com o mesmo texto: não é item, não pode ser escolhida.
    {"id": "e-20", "index": "20", "name": "INSS", "fullname": "20",
     "discriminator": "STAGE"},
]


class PaginaFalsa:
    """Faz o papel da página do Playwright: `evaluate` recebe o JS e os
    argumentos, e responde conforme a consulta GraphQL do corpo."""

    def __init__(self, respostas: dict | None = None):
        self.respostas = respostas or {}
        self.chamadas: list[dict] = []

    def evaluate(self, _js, args):
        self.chamadas.append(args)
        consulta = (args.get("corpo") or {}).get("query", "")
        for trecho, resposta in self.respostas.items():
            if trecho in consulta:
                return resposta
        return {"__erro": 500}


RESPOSTAS_OK = {
    "planningByWork": {"data": {"planningByWork": {"id": PLANO,
                                                   "__typename": "Planning"}}},
    "allTasks": {"data": {"allTasks": TAREFAS}},
}

POR_HOST = {
    HOST: {"authorization": "Bearer token-do-graphql"},
    "prod-erp-api.maiscontroleerp.com.br": {"authorization": "Bearer outro"},
}


def catalogos(pagina=None, headers=None) -> Catalogos:
    return Catalogos(pagina or PaginaFalsa(), headers if headers is not None
                     else POR_HOST, log=lambda *_a, **_k: None)


# ------------------------------------------------------------ a causa
@pytest.mark.parametrize(
    "nome", ["_dados", "_motivo", "nome_da_tarefa", "_ordem_do_indice"])
def test_as_funcoes_sem_self_sao_staticmethod(nome):
    """É a guarda direta: sem o decorador, `self.x(arg)` manda dois
    argumentos para uma função que aceita um."""
    assert isinstance(Catalogos.__dict__[nome], staticmethod), (
        f"Catalogos.{nome} é chamada como método, mas foi escrita sem self")


def test_o_init_prepara_o_cache_e_os_erros_de_tarefas():
    cat = catalogos(headers={})
    assert cat._cache_tarefas == {}
    assert cat.erros_tarefas == {}


def test_task_da_obra_nao_estoura_com_tarefas_simuladas(monkeypatch):
    """O caso de 09/09: `task_da_obra` com `tarefas_da_obra` substituído.
    Passa por `nome_da_tarefa` e `_ordem_do_indice` como método."""
    cat = catalogos()
    monkeypatch.setattr(cat, "tarefas_da_obra", lambda _id: TAREFAS)
    achado = cat.task_da_obra(OBRA, "inss")
    assert achado == {
        "id": "t-20-1", "index": "20.1",
        "fullname": "20.1 - INSS (pessoa física)",
        "name": "INSS (pessoa física)", "discriminator": "ITEM",
    }


def test_task_da_obra_devolve_none_sem_candidato(monkeypatch):
    cat = catalogos()
    monkeypatch.setattr(cat, "tarefas_da_obra", lambda _id: TAREFAS)
    assert cat.task_da_obra(OBRA, "pintura") is None


# ------------------------------------------------------------- a ordem
def test_a_ordem_do_indice_e_numerica_e_nao_de_texto():
    indices = ["20.10", "3", "20.1", "20.9", "10"]
    ordem = sorted(indices, key=lambda i: Catalogos._ordem_do_indice({"index": i}))
    assert ordem == ["3", "10", "20.1", "20.9", "20.10"]
    # O que a ordem de texto faria — e o item errado que ela escolheria.
    assert sorted(indices) == ["10", "20.1", "20.10", "20.9", "3"]


def test_indice_vazio_ou_estranho_nao_derruba_a_ordenacao():
    ordem = Catalogos._ordem_do_indice
    assert ordem({"index": None}) == (0,)
    assert ordem({}) == (0,)
    assert ordem({"index": "20.a"}) == (20, 0)
    assert ordem({"index": 7}) == (7,)


# ------------------------------------------------- o caminho inteiro
def test_tarefas_da_obra_percorre_planejamento_e_tarefas_e_guarda_no_cache():
    """Sem substituir nada: só a página é falsa. Prova `_dados` como método,
    os dois atributos do `__init__` e o `_host_graphql` calculado."""
    pagina = PaginaFalsa(RESPOSTAS_OK)
    cat = catalogos(pagina)

    assert cat.tarefas_da_obra(OBRA) == TAREFAS
    assert cat.erros_tarefas == {}
    assert cat._cache_tarefas[OBRA] == TAREFAS
    assert len(pagina.chamadas) == 2
    assert all(c["url"] == f"https://{HOST}/prod/graphql" for c in pagina.chamadas)
    assert pagina.chamadas[0]["corpo"]["variables"] == {"workId": OBRA}
    assert pagina.chamadas[1]["corpo"]["variables"] == {"planningId": PLANO}
    # Cabeçalho do host certo, não o do prod-erp-api.
    assert pagina.chamadas[0]["headers"] == POR_HOST[HOST]

    # Segunda vez: do cache, sem voltar à página.
    assert cat.tarefas_da_obra(OBRA) == TAREFAS
    assert len(pagina.chamadas) == 2

    assert cat.task_da_obra(OBRA, "INSS")["id"] == "t-20-1"


def test_tarefas_parecidas_usa_o_nome_como_a_tela_mostra():
    cat = catalogos(PaginaFalsa(RESPOSTAS_OK))
    parecidas = cat.tarefas_parecidas(OBRA, "INSS pessoa")
    assert "INSS (pessoa física)" in parecidas
    assert all(isinstance(p, str) for p in parecidas)


def test_obra_sem_orcamento_registra_o_motivo_e_nao_consulta_tarefas():
    pagina = PaginaFalsa({"planningByWork": {"data": {"planningByWork": None}}})
    cat = catalogos(pagina)
    assert cat.tarefas_da_obra(OBRA) == []
    assert cat.erros_tarefas[OBRA] == "a obra não tem orçamento: veio vazio"
    assert len(pagina.chamadas) == 1
    assert cat.task_da_obra(OBRA, "INSS") is None


def test_erro_http_vira_motivo_legivel():
    pagina = PaginaFalsa({"planningByWork": {"__erro": 403}})
    cat = catalogos(pagina)
    assert cat.tarefas_da_obra(OBRA) == []
    assert cat.erros_tarefas[OBRA] == "a obra não tem orçamento: HTTP 403"


def test_sem_host_graphql_nao_vai_a_pagina():
    """Mapa plano de cabeçalhos: não há como saber o host do GraphQL."""
    pagina = PaginaFalsa(RESPOSTAS_OK)
    cat = catalogos(pagina, headers={"authorization": "Bearer plano"})
    assert cat._host_graphql is None
    assert cat.tarefas_da_obra(OBRA) == []
    assert cat.erros_tarefas[OBRA] == "sem host GraphQL"
    assert pagina.chamadas == []


# ------------------------------------------------------ _host_graphql
def test_host_graphql_e_o_primeiro_execute_api_do_mapa_por_host():
    assert catalogos()._host_graphql == HOST
    sem = catalogos(headers={"prod-erp-api.maiscontroleerp.com.br": {"authorization": "x"}})
    assert sem._host_graphql is None
    assert catalogos(headers={})._host_graphql is None


def test_host_graphql_aceita_ser_fixado_de_fora():
    """O contorno do coletor fazia `cat._host_graphql = ...` antes de a
    propriedade existir; ele não pode passar a estourar na atualização."""
    cat = catalogos(headers={"authorization": "Bearer plano"})
    cat._host_graphql = "zzz.execute-api.sa-east-1.amazonaws.com"
    assert cat._host_graphql == "zzz.execute-api.sa-east-1.amazonaws.com"
    cat._host_graphql = None
    assert cat._host_graphql is None
