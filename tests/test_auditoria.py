# -*- coding: utf-8 -*-
"""Quem fez o quê — e o que acontece quando o registro não sobe.

Esta é a parte do app em que a falha tem de ser silenciosa e a verdade tem de
ser do servidor. As duas coisas puxam para lados opostos, e é essa tensão que
os testes daqui seguram:

  o registro NUNCA derruba o trabalho — um pagamento que já saiu não pode ser
  desfeito porque a linha de auditoria não subiu;

  e o `quem` NUNCA vem do cliente — um campo que o app preenche não responde
  "quem fez", responde "quem o app disse que fez".
"""

import pytest

import widgets
from nuvem import auditoria, rest, sessao, usuarios


@pytest.fixture
def sem_thread(monkeypatch):
    """`registrar` manda a parte da nuvem para uma thread solta. Aqui ela roda
    na mesma, para o teste não depender de tempo."""
    class Agora:
        def __init__(self, target=None, args=(), daemon=None):
            self._alvo, self._args = target, args

        def start(self):
            self._alvo(*self._args)
    monkeypatch.setattr(auditoria.threading, "Thread", Agora)


@pytest.fixture
def nuvem(monkeypatch):
    """O que foi mandado ao PostgREST, sem rede nenhuma."""
    enviado = []
    monkeypatch.setattr(sessao, "token", lambda *_a, **_k: "tok")
    monkeypatch.setattr(
        rest, "inserir",
        lambda tabela, token, linhas, **kw: enviado.append(
            {"tabela": tabela, "token": token, "linhas": linhas, "kw": kw}))
    return enviado


@pytest.fixture
def local(monkeypatch):
    """O espelho no atividade.jsonl, sem tocar em disco."""
    anotado = []
    monkeypatch.setattr(widgets, "registrar_atividade",
                        lambda *a, **k: anotado.append((a, k)))
    return anotado


# ------------------------------------------------------------- quem assina

def test_o_app_nao_diz_quem_fez(nuvem):
    """A coluna tem `default auth.uid()` e a política tem
    `with check (quem = auth.uid())`: quem carimba é o servidor, a partir do
    token. Mandar o campo daqui seria oferecer ao cliente a chance de mentir
    justamente no dado que a tabela existe para guardar."""
    assert auditoria.gravar_agora("Gerar remessa", "3 arquivos") is True
    assert len(nuvem) == 1
    linha = nuvem[0]["linhas"][0]
    assert set(linha) == {"acao", "detalhe"}
    assert "quem" not in linha
    assert nuvem[0]["tabela"] == "auditoria"


def test_o_texto_e_cortado_antes_de_viajar(nuvem):
    """Traceback inteiro no `detalhe` entope a tabela que se vai ler depois."""
    auditoria.gravar_agora("A" * 500, "B" * 5000)
    linha = nuvem[0]["linhas"][0]
    assert len(linha["acao"]) == 200
    assert len(linha["detalhe"]) == 500


def test_acao_vazia_nao_chega_a_viajar(nuvem):
    """O banco recusaria (`check length(trim(acao)) > 0`), e a viagem seria só
    para ouvir não."""
    assert auditoria.gravar_agora("   ") is False
    assert nuvem == []


# ------------------------------------------------- falhar sem derrubar nada

@pytest.mark.parametrize("tropeco", [
    rest.SemRede("dns"),
    rest.PrecisaEntrar("a sessão venceu"),
    rest.RecusadoPeloBanco("tabela cheia"),
    RuntimeError("qualquer outra coisa"),
])
def test_registro_que_nao_sobe_nao_levanta(monkeypatch, tropeco):
    """O ponto inteiro deste módulo. Quem chama está no meio de um login, de
    uma aprovação ou de uma remessa — nenhuma delas pode parar aqui."""
    monkeypatch.setattr(sessao, "token", lambda *_a, **_k: "tok")

    def caiu(*_a, **_k):
        raise tropeco
    monkeypatch.setattr(rest, "inserir", caiu)
    assert auditoria.gravar_agora("Gerar remessa") is False


def test_sem_sessao_tambem_nao_levanta(monkeypatch):
    """Sem token não há a quem contar — e ainda assim o trabalho segue."""
    monkeypatch.setattr(sessao, "token", lambda *_a, **_k: (_ for _ in ()).throw(
        rest.PrecisaEntrar("ninguém entrou")))
    assert auditoria.gravar_agora("Entrou no app") is False


# ------------------------------------------------------ os dois espelhos

def test_registrar_grava_nos_dois(sem_thread, nuvem, local):
    auditoria.registrar("Gerar remessa", "3 arquivos", aba="pag",
                        resultado="ok", numeros={"total": 10.0})
    assert nuvem[0]["linhas"][0]["acao"] == "Gerar remessa"
    (aba, acao, resultado, detalhe, numeros), _kw = local[0]
    assert (aba, acao, resultado) == ("pag", "Gerar remessa", "ok")
    assert numeros == {"total": 10.0}


def test_a_nuvem_muda_e_o_painel_de_inicio_continua_de_pe(
        sem_thread, local, monkeypatch):
    """O `atividade.jsonl` é o que a tela de Início lê, e ele funciona sem
    internet. Um dia sem rede não pode virar um dia sem histórico na tela."""
    monkeypatch.setattr(sessao, "token", lambda *_a, **_k: "tok")
    monkeypatch.setattr(rest, "inserir", lambda *_a, **_k: (_ for _ in ()).throw(
        rest.SemRede("caiu")))
    auditoria.registrar("Buscar lançamentos", "87 lançamentos", aba="pag")
    assert local, "o espelho local tinha de ter sido escrito assim mesmo"


def test_o_espelho_local_nao_derruba_a_nuvem(sem_thread, nuvem, monkeypatch):
    """E o contrário também: disco cheio na hora de anotar não pode impedir o
    registro que interessa para a pergunta de depois."""
    monkeypatch.setattr(widgets, "registrar_atividade",
                        lambda *_a, **_k: (_ for _ in ()).throw(OSError("disco")))
    auditoria.registrar("Gerar remessa", "3 arquivos", aba="pag")
    assert nuvem, "a linha da nuvem tinha de ter subido assim mesmo"


def test_registrar_nao_espera_o_servidor(monkeypatch, local):
    """O `rest` espera até 20 segundos por uma resposta, e alguns destes
    pontos são o clique de um botão."""
    saiu = {"em_thread": False}

    class Espiao:
        def __init__(self, target=None, args=(), daemon=None):
            self._daemon = daemon

        def start(self):
            saiu["em_thread"] = self._daemon is True
    monkeypatch.setattr(auditoria.threading, "Thread", Espiao)
    auditoria.registrar("Entrou no app")
    assert saiu["em_thread"], "a parte da nuvem tem de sair numa thread solta"
    assert local, "e a parte local tem de acontecer na hora"


# ------------------------------------------------- os pontos que o plano pede

def test_aprovar_uma_conta_vira_linha_de_auditoria(sem_thread, nuvem,
                                                   local, monkeypatch):
    """O critério de pronto da fase 5: a aprovação aparece na tabela."""
    monkeypatch.setattr(rest, "alterar", lambda *_a, **_k: [
        {"user_id": "2", "nome": "Fulano De Tal", "email": "f@x.com",
         "papel": "aprovador", "situacao": "ativo"}])
    usuarios.aprovar("tok", "2", "aprovador")
    linha = nuvem[0]["linhas"][0]
    assert linha["acao"] == "Liberou o acesso de Fulano De Tal"
    assert "aprovador" in linha["detalhe"] and "ativo" in linha["detalhe"]


def test_a_aprovacao_so_e_anotada_DEPOIS_de_valer(nuvem, monkeypatch):
    """Anotar antes registraria algo que não aconteceu — pior do que não ter
    registro nenhum."""
    monkeypatch.setattr(rest, "alterar", lambda *_a, **_k: [])
    with pytest.raises(rest.RecusadoPeloBanco):
        usuarios.aprovar("tok", "2", "aprovador")
    assert nuvem == []


@pytest.mark.parametrize("chamar,esperado", [
    (lambda: usuarios.mudar_papel("tok", "2", "operador"), "Trocou o papel"),
    (lambda: usuarios.desativar("tok", "2"), "Desativou"),
    (lambda: usuarios.reativar("tok", "2"), "Reativou"),
])
def test_toda_decisao_sobre_conta_deixa_rastro(sem_thread, nuvem, local,
                                               monkeypatch, chamar, esperado):
    monkeypatch.setattr(rest, "alterar", lambda *_a, **_k: [
        {"user_id": "2", "nome": "Fulano De Tal", "email": "f@x.com"}])
    chamar()
    assert nuvem[0]["linhas"][0]["acao"].startswith(esperado)


# ---------------------------------------------------------------- leitura

def test_recentes_pede_as_mais_novas(monkeypatch):
    pedido = {}
    monkeypatch.setattr(sessao, "token", lambda *_a, **_k: "tok")

    def ler(tabela, token, *, colunas="", filtro=""):
        pedido.update(tabela=tabela, colunas=colunas, filtro=filtro)
        return [{"id": 1}]
    monkeypatch.setattr(rest, "ler", ler)
    assert auditoria.recentes(10) == [{"id": 1}]
    assert "order=quando.desc" in pedido["filtro"]
    assert "limit=10" in pedido["filtro"]


def test_recentes_sem_rede_devolve_lista_vazia(monkeypatch):
    monkeypatch.setattr(sessao, "token", lambda *_a, **_k: "tok")
    monkeypatch.setattr(rest, "ler", lambda *_a, **_k: (_ for _ in ()).throw(
        rest.SemRede("caiu")))
    assert auditoria.recentes() == []
