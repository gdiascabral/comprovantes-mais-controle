# -*- coding: utf-8 -*-
"""Conta nova no ERP: a conferência que roda na abertura do app.

Sem rede e sem navegador. O que se prova aqui é que a pergunta certa é feita
(e só ela), que a resposta grava no NOSSO cadastro com os campos que o banco
exige, e que nada disso pode impedir o app de abrir.
"""
import json

from nuvem import contas_novas as conferencia


class ContaErp:
    """O bastante de um `ErpAccount` para a comparação."""

    def __init__(self, nome, ativa=True, id_erp="uuid-1",
                 banco="756", agencia="3299", numero="58123-4"):
        self.id = id_erp
        self.name = nome
        self.is_active = ativa
        self.bank_code = banco
        self.agency = agencia
        self.account_number = numero


# ------------------------------------------------------------- comparação
def test_conta_que_o_ERP_tem_e_o_cadastro_nao_e_novidade():
    novas = conferencia.comparar([ContaErp("MORAIS ENG - SUBCONTA 58123-4")],
                                 {"OUTRA CONTA"})
    assert [c.nome for c in novas] == ["MORAIS ENG - SUBCONTA 58123-4"]
    assert novas[0].banco == "756" and novas[0].agencia == "3299"


def test_conta_ja_cadastrada_nao_pergunta():
    novas = conferencia.comparar([ContaErp("CONTA X")], {"CONTA X"})
    assert novas == []


def test_acento_e_caixa_nao_criam_novidade_falsa():
    """Sem a régua normalizada, a janela perguntaria todo dia pela mesma."""
    ja = {conferencia.util.norm_espaco("Morais Participações - SUBCONTA 1")}
    novas = conferencia.comparar(
        [ContaErp("MORAIS PARTICIPACOES - SUBCONTA 1")], ja)
    assert novas == []


def test_conta_inativa_no_ERP_fica_de_fora():
    """Perguntar sobre conta que ninguém usa mais é ruído."""
    assert conferencia.comparar([ContaErp("VELHA", ativa=False)], set()) == []


def test_a_mesma_conta_duas_vezes_pergunta_uma_vez():
    novas = conferencia.comparar([ContaErp("REPETIDA"), ContaErp("REPETIDA")],
                                 set())
    assert len(novas) == 1


def test_listas_vazias_nao_estouram():
    assert conferencia.comparar([], set()) == []
    assert conferencia.comparar(None, set()) == []


# ------------------------------------------------------------ nosso lado
def test_le_os_nomes_do_cadastro_local(tmp_path):
    (tmp_path / "contas_mc.json").write_text(json.dumps(
        {"raiz": "x", "contas": [{"erp": "CONTA A"}, {"erp": "Conta B"}]}),
        encoding="utf-8")
    nomes = conferencia.nomes_cadastrados(tmp_path)
    assert conferencia.util.norm_espaco("conta a") in nomes
    assert conferencia.util.norm_espaco("CONTA B") in nomes


def test_sem_o_arquivo_o_cadastro_e_vazio_e_nao_estoura(tmp_path):
    """Máquina nova, antes da primeira sincronização."""
    assert conferencia.nomes_cadastrados(tmp_path) == set()


# ------------------------------------------------------------- validação
def test_marcada_sem_pasta_nao_grava():
    """`pasta` é not null: mandar vazio trocaria a pergunta por erro de SQL."""
    assert conferencia.validar({"nome_erp": "X", "empresa_id": 1, "pasta": " "})


def test_marcada_sem_empresa_nao_grava():
    assert conferencia.validar({"nome_erp": "X", "pasta": "SICOOB"})


def test_escolha_completa_passa():
    assert conferencia.validar(
        {"nome_erp": "X", "empresa_id": 1, "pasta": "SICOOB"}) == ""


# -------------------------------------------------------------- gravação
def test_grava_no_nosso_cadastro_com_os_campos_do_banco(monkeypatch):
    gravadas = {}

    def falso_inserir(tabela, token, linhas, **_kw):
        gravadas["tabela"], gravadas["linhas"] = tabela, linhas

    monkeypatch.setattr(conferencia.rest, "inserir", falso_inserir)
    avisos = conferencia.gravar("tok", [{
        "nome_erp": "MORAIS ENG - SUBCONTA 58123-4", "empresa_id": 7,
        "pasta": "SICOOB 58123-4", "banco": "756", "agencia": "3299",
        "numero": "58123-4"}])
    assert avisos == []
    assert gravadas["tabela"] == "conta"
    linha, = gravadas["linhas"]
    assert linha["nome_erp"] == "MORAIS ENG - SUBCONTA 58123-4"
    assert linha["empresa_id"] == 7 and linha["pasta"] == "SICOOB 58123-4"


def test_a_incompleta_vira_aviso_e_a_boa_grava(monkeypatch):
    """Uma escolha pela metade não pode derrubar as outras."""
    linhas = {}
    monkeypatch.setattr(conferencia.rest, "inserir",
                        lambda t, tok, ls, **k: linhas.setdefault("ls", ls))
    avisos = conferencia.gravar("tok", [
        {"nome_erp": "SEM PASTA", "empresa_id": 1, "pasta": ""},
        {"nome_erp": "BOA", "empresa_id": 1, "pasta": "P"}])
    assert len(avisos) == 1 and "SEM PASTA" in avisos[0]
    assert [l["nome_erp"] for l in linhas["ls"]] == ["BOA"]


def test_nada_escolhido_nao_chama_o_banco(monkeypatch):
    def nao_deveria(*_a, **_k):
        raise AssertionError("chamou o banco sem ter o que gravar")

    monkeypatch.setattr(conferencia.rest, "inserir", nao_deveria)
    assert conferencia.gravar("tok", []) == []


def test_a_gravacao_nunca_apaga(monkeypatch):
    """A decisão de 14/08 muda no mínimo: insere sim, apaga nunca."""
    def nao_deveria(*_a, **_k):
        raise AssertionError("a conferência tentou APAGAR cadastro")

    monkeypatch.setattr(conferencia.rest, "apagar", nao_deveria)
    monkeypatch.setattr(conferencia.rest, "inserir", lambda *a, **k: None)
    conferencia.gravar("tok", [{"nome_erp": "X", "empresa_id": 1, "pasta": "P"}])


# ----------------------------------------------------- falha não derruba
def test_erro_ao_falar_com_o_ERP_devolve_vazio_e_nao_levanta(monkeypatch):
    """Isto roda na ABERTURA do app: nada aqui pode impedir o app de abrir.

    Sem rede, login vencido, MFA ligado ou contrato mudado — o desfecho é o
    mesmo: uma linha no log e lista vazia. É a mesma regra que já protege o
    `sincronizar`, logo acima desta chamada.
    """
    def explode():
        raise OSError("sem rede")

    recados = []
    monkeypatch.setattr(conferencia, "_ConfigMinimo", explode)
    assert conferencia.contas_do_erp(log=recados.append) == []
    assert any("ERP" in r for r in recados)


def test_sem_contas_do_ERP_nao_ha_o_que_perguntar(monkeypatch):
    monkeypatch.setattr(conferencia, "contas_do_erp", lambda log=print: [])
    assert conferencia.novidades(log=lambda _m: None) == []
