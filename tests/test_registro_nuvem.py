# -*- coding: utf-8 -*-
"""O registro central das remessas, sem rede.

A atomicidade da alocação é do Postgres e foi medida contra o projeto de
verdade (12 pedidos simultâneos, 12 números distintos). O que se testa aqui é
o que o Python decide: quem consome número e quem só olha, o que conta como
"já enviado", e a regra de que o espelho local não tem voto.
"""

import pytest

from nuvem import registro, rest


class _RestFalso:
    """Anota o que foi pedido, devolve o que o teste mandar."""

    def __init__(self, **respostas):
        self.respostas = respostas
        self.chamadas = []

    def ler(self, tabela, _token, *, colunas="*", filtro=""):
        self.chamadas.append(("ler", tabela, filtro))
        return self.respostas.get(tabela, [])

    def inserir(self, tabela, _token, linhas, *, devolver=True):
        self.chamadas.append(("inserir", tabela, len(linhas)))
        self.respostas.setdefault("_inseridos", {}).setdefault(tabela, []).extend(linhas)
        return [{"id": 1}] if devolver else []

    def alterar(self, tabela, _token, filtro, mudancas):
        self.chamadas.append(("alterar", tabela, filtro, mudancas))
        return [{"id": 1}]

    def chamar(self, funcao, _token, **argumentos):
        self.chamadas.append(("chamar", funcao, argumentos))
        return self.respostas.get(funcao, 1)


@pytest.fixture
def falso(monkeypatch):
    f = _RestFalso()
    for nome in ("ler", "inserir", "alterar", "chamar"):
        monkeypatch.setattr(registro.rest, nome, getattr(f, nome))
    return f


# ------------------------------------------------------------- contador

def test_espiar_nao_consome(falso):
    """A janela de conferência mostra o número antes de gerar. Se mostrar
    reservasse, abrir e desistir queimaria um NSA por vez."""
    falso.respostas["remessa_contador"] = [{"ultimo_nsa": 7}]
    reg = registro.Registro("tok")

    assert reg.proximo_nsa("1814") == 8
    assert reg.proximo_nsa("1814") == 8          # de novo: mesmo número
    assert not [c for c in falso.chamadas if c[0] == "chamar"]


def test_alocar_consome(falso):
    falso.respostas["alocar_nsa"] = 9
    reg = registro.Registro("tok")

    assert reg.alocar_nsa("1814") == 9
    assert ("chamar", "alocar_nsa", {"p_convenio": "1814"}) in falso.chamadas


def test_convenio_sem_contador_comeca_em_um(falso):
    assert registro.Registro("tok").proximo_nsa("novo") == 1


def test_ajuste_leva_o_motivo(falso):
    falso.respostas["ajustar_nsa"] = 12
    reg = registro.Registro("tok")

    assert reg.ajustar_nsa("1814", 500, motivo="alinhar com o banco") == 12
    chamada = [c for c in falso.chamadas if c[0] == "chamar"][0]
    assert chamada[2]["p_motivo"] == "alinhar com o banco"


# ------------------------------------------------- "isto ja foi mandado?"

def _item(nsa=31, estado="gerado"):
    return [{"seu_numero": "260813-0001",
             "remessa": {"nsa": nsa, "convenio": "1814", "estado": estado,
                         "gerado_em": "2026-08-13T10:00:00+00:00"}}]


def test_boleto_ja_enviado_e_encontrado(falso):
    falso.respostas["remessa_item"] = _item()
    achado = registro.Registro("tok").envio_de("34191790010104351004791020150008")
    assert achado and achado[0].nsa == 31
    assert achado[0].gerado_em.year == 2026


def test_lancamento_ja_enviado_e_encontrado(falso):
    """A pergunta que pega o Pix, que não tem código de barras."""
    falso.respostas["remessa_item"] = _item()
    assert registro.Registro("tok").envio_da_referencia("12345") is not None


def test_chave_vazia_nao_pergunta(falso):
    """Pix sem código de barras: perguntar por "" traria a primeira linha
    qualquer da tabela."""
    reg = registro.Registro("tok")
    assert reg.envio_de("") is None
    assert reg.envio_da_referencia("") is None
    assert not falso.chamadas


def test_remessa_descartada_nao_conta_como_enviada(falso):
    """`descartar` existe justamente para devolver o direito de reenviar.

    O PostgREST devolve a linha com `remessa: null` quando o filtro do
    relacionamento não casa, em vez de omiti-la — sem tratar isso, uma
    remessa descartada passaria por envio vivo e travaria o reenvio."""
    falso.respostas["remessa_item"] = [{"seu_numero": "x", "remessa": None}]
    assert registro.Registro("tok").envio_de("qualquer") is None


def test_o_filtro_pede_so_estado_vivo(falso):
    falso.respostas["remessa_item"] = []
    registro.Registro("tok").envio_de("abc")
    filtro = [c for c in falso.chamadas if c[0] == "ler"][0][2]
    assert "estado=in." in filtro
    for estado in registro.ESTADOS_VIVOS:
        assert estado in filtro


# ------------------------------------------------------------- espelho

class _LocalFalso:
    def __init__(self, erro=None):
        self.erro = erro
        self.registrou = False

    def registrar(self, *_a, **_k):
        if self.erro:
            raise self.erro
        self.registrou = True

    def marcar(self, *_a, **_k):
        if self.erro:
            raise self.erro

    def ajustar_nsa(self, *_a, **_k):
        if self.erro:
            raise self.erro


class _NuvemFalsa:
    def __init__(self, erro=None):
        self.erro = erro
        self.registrou = False

    def registrar(self, *_a, **_k):
        if self.erro:
            raise self.erro
        self.registrou = True

    def marcar(self, *_a, **_k):
        pass

    def ajustar_nsa(self, *_a, **_k):
        return 5


def test_espelho_local_nao_tem_voto():
    """O arquivo já foi gerado com um NSA que a nuvem reservou. Recusar a
    remessa porque o BACKUP falhou seria trocar o problema pequeno pelo
    grande."""
    recados = []
    esp = registro.Espelhado(_NuvemFalsa(), _LocalFalso(OSError("disco cheio")),
                             recados.append)
    esp.registrar(object(), caminho_arquivo="x.REM")          # não levanta
    assert recados and "espelho local" in recados[0]


def test_recusa_da_nuvem_derruba_tudo():
    """A nuvem é quem pode recusar por NSA repetido, e essa recusa TEM de
    impedir o arquivo de virar definitivo."""
    local = _LocalFalso()
    esp = registro.Espelhado(_NuvemFalsa(rest.RecusadoPeloBanco("nsa repetido")),
                             local)
    with pytest.raises(rest.RecusadoPeloBanco):
        esp.registrar(object())
    assert not local.registrou      # e o espelho nem chega a ser tocado


def test_o_numero_vem_sempre_da_nuvem():
    class Nuvem:
        def alocar_nsa(self, _c):
            return 42

        def proximo_nsa(self, _c):
            return 42

        def ultimo_nsa(self, _c):
            return 41

    class LocalAdiantado:
        def alocar_nsa(self, _c):
            raise AssertionError("o local não pode ser consultado para o NSA")
        proximo_nsa = ultimo_nsa = alocar_nsa

    esp = registro.Espelhado(Nuvem(), LocalAdiantado())
    assert esp.alocar_nsa("1814") == 42
    assert esp.proximo_nsa("1814") == 42
    assert esp.ultimo_nsa("1814") == 41
