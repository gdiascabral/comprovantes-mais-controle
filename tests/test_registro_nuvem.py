# -*- coding: utf-8 -*-
"""O registro central das remessas, sem rede.

A atomicidade da alocação é do Postgres e foi medida contra o projeto de
verdade (12 pedidos simultâneos, 12 números distintos). O que se testa aqui é
o que o Python decide: quem consome número e quem só olha, o que conta como
"já enviado", e a regra de que o espelho local não tem voto.
"""

import pytest

from cnab240 import historico
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


def test_remessa_rejeitada_continua_contando_como_enviada(falso):
    """Uma rejeição não devolve à remessa o direito de sair de novo.

    O retorno do banco marca a remessa como "rejeitado" quando UM item foi
    recusado. Se esse estado não fosse vivo, os outros pagamentos — inclusive
    os que o banco PAGOU — voltariam marcáveis na geração seguinte, com NSA
    novo e nenhum alarme: pagamento em dobro."""
    falso.respostas["remessa_item"] = _item(estado="rejeitado")
    achado = registro.Registro("tok").envio_de("34191790010104351004791020150008")
    assert achado and achado[0].estado == "rejeitado"

    # E a pergunta chega ao banco pedindo o estado: o dublê ignora o filtro,
    # então sem isto o teste passaria com "rejeitado" fora da lista.
    filtro = [c for c in falso.chamadas if c[0] == "ler"][0][2]
    assert "rejeitado" in filtro


def test_as_duas_listas_de_estado_sao_a_mesma(falso):
    """Não "espelham": são o MESMO objeto, importado de um lugar só.

    Enquanto foram duas listas escritas à mão elas divergiram em silêncio, e
    a divergência era dinheiro: faltava "rejeitado" aqui, e sobrava "aceito",
    que o `cnab240` nunca conheceu — logo o `Historico.marcar` local sempre o
    recusaria, e nenhuma remessa jamais foi gravada com ele."""
    assert registro.ESTADOS_VIVOS is historico.ESTADOS_VIVOS
    assert set(registro.ESTADOS_VIVOS) <= set(historico.ESTADOS)
    assert "aceito" not in registro.ESTADOS_VIVOS
    assert "rejeitado" in registro.ESTADOS_VIVOS
    # Descartar é o único jeito de devolver o direito de reenviar.
    assert set(historico.ESTADOS) - set(registro.ESTADOS_VIVOS) == {"descartado"}


def test_o_filtro_pede_so_estado_vivo(falso):
    falso.respostas["remessa_item"] = []
    registro.Registro("tok").envio_de("abc")
    filtro = [c for c in falso.chamadas if c[0] == "ler"][0][2]
    assert "estado=in." in filtro
    for estado in registro.ESTADOS_VIVOS:
        assert estado in filtro


# --------------------------------------------------- o retorno do banco

def _remessa_com_itens(*itens):
    """Uma remessa como o `remessas()` a devolve: com os itens dentro."""
    return [{"nsa": 31, "convenio": "1814", "remessa_item": list(itens)}]


def _gravado(falso, tabela="remessa_item"):
    """As mudanças de cada `alterar` naquela tabela, na ordem."""
    return [c[3] for c in falso.chamadas
            if c[0] == "alterar" and c[1] == tabela]


def test_o_retorno_grava_as_quatro_colunas(falso):
    """Código, quando, classificação e histórico — e o histórico começa nesta
    passagem, porque antes dela o banco nunca tinha falado deste item."""
    falso.respostas["remessa"] = _remessa_com_itens(
        {"id": 7, "seu_numero": "001", "retorno_historico": ""})
    reg = registro.Registro("tok")

    assert reg.aplicar_retorno("1814", 31,
                               {"001": {"codigo": "AG;BD",
                                        "estado": "rejeitado"}}) == 1
    mudancas = _gravado(falso)[0]
    assert mudancas["retorno_codigo"] == "AG;BD"
    assert mudancas["retorno_estado"] == "rejeitado"
    assert mudancas["retorno_em"]
    assert mudancas["retorno_historico"].endswith(" AG;BD=rejeitado")
    # O carimbo do histórico e o `retorno_em` são o MESMO instante: as duas
    # colunas contradizerem-se seria a pior forma de descobrir o erro.
    assert mudancas["retorno_historico"].startswith(mudancas["retorno_em"][:10])


def test_o_segundo_retorno_nao_apaga_o_primeiro(falso):
    """É o defeito que este PR existe para fechar.

    Quem gera não é quem assina: o retorno do mesmo dia vem `PD` e o de
    depois da liberação vem `00`. O `00` é a resposta certa para "e agora?" —
    e escrevê-lo por cima do `PD` apagava a única prova de que o arquivo tinha
    sido ACEITO pelo banco."""
    item = {"id": 7, "seu_numero": "001", "retorno_historico": ""}
    falso.respostas["remessa"] = _remessa_com_itens(item)
    reg = registro.Registro("tok")

    reg.aplicar_retorno("1814", 31, {"001": {"codigo": "PD",
                                             "estado": "pendente"}})
    primeira = _gravado(falso)[0]["retorno_historico"]

    # A segunda leitura enxerga o que a primeira gravou — é o que o
    # `remessas()` devolve, porque ele pede `remessa_item(*)`.
    item["retorno_historico"] = primeira
    reg.aplicar_retorno("1814", 31, {"001": {"codigo": "00", "estado": "ok"}})
    segunda = _gravado(falso)[1]

    assert segunda["retorno_codigo"] == "00"        # a resposta de agora
    assert segunda["retorno_estado"] == "ok"
    assert segunda["retorno_historico"].startswith(primeira + ";")
    assert "PD=pendente" in segunda["retorno_historico"]
    assert "00=ok" in segunda["retorno_historico"]


def test_o_silencio_do_banco_nao_apaga_resposta_anterior(falso):
    """Item que o retorno não citou fica exatamente como estava: nem `alterar`
    é chamado para ele."""
    falso.respostas["remessa"] = _remessa_com_itens(
        {"id": 7, "seu_numero": "001", "retorno_historico": "x"},
        {"id": 8, "seu_numero": "002", "retorno_historico": ""})
    reg = registro.Registro("tok")

    assert reg.aplicar_retorno("1814", 31,
                               {"002": {"codigo": "00", "estado": "ok"}}) == 1
    filtros = [c[2] for c in falso.chamadas
               if c[0] == "alterar" and c[1] == "remessa_item"]
    assert filtros == ["id=eq.8"]


def test_o_formato_antigo_continua_valendo(falso):
    """Uma string no lugar do dicionário vira `{"codigo": s, "estado": ""}`.

    Não é gentileza com quem chama: é o que permite este PR não ter de mudar,
    no mesmo commit, todo lugar que já sabia gravar retorno."""
    falso.respostas["remessa"] = _remessa_com_itens(
        {"id": 7, "seu_numero": "001", "retorno_historico": ""})

    assert registro.Registro("tok").aplicar_retorno("1814", 31,
                                                    {"001": "00"}) == 1
    mudancas = _gravado(falso)[0]
    assert mudancas["retorno_codigo"] == "00"
    assert mudancas["retorno_estado"] == ""
    assert mudancas["retorno_historico"].endswith(" 00=")


def test_o_retorno_de_remessa_desconhecida_e_recusado(falso):
    """Gravar num item qualquer seria pior que não gravar: a resposta do banco
    entraria no pagamento errado."""
    falso.respostas["remessa"] = _remessa_com_itens(
        {"id": 7, "seu_numero": "001"})
    with pytest.raises(rest.RecusadoPeloBanco):
        registro.Registro("tok").aplicar_retorno("1814", 99, {"001": "00"})


def test_o_estado_da_remessa_vai_junto_quando_pedido(falso):
    falso.respostas["remessa"] = _remessa_com_itens(
        {"id": 7, "seu_numero": "001", "retorno_historico": ""})
    registro.Registro("tok").aplicar_retorno(
        "1814", 31, {"001": {"codigo": "AG", "estado": "rejeitado"}},
        estado="rejeitado")
    assert {"estado": "rejeitado"} in _gravado(falso, "remessa")


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


def test_o_retorno_so_vai_para_a_nuvem():
    """O espelho local é backup do que SAIU. O que o banco respondeu depois
    nunca esteve nele, e o `cnab240.Historico` não tem onde pôr."""
    pedidos = []

    class Nuvem:
        def aplicar_retorno(self, convenio, nsa, respostas, *, estado=""):
            pedidos.append((convenio, nsa, respostas, estado))
            return len(respostas)

    class LocalSemRetorno:
        def __getattr__(self, nome):
            raise AssertionError(f"o espelho local não guarda retorno ({nome})")

    esp = registro.Espelhado(Nuvem(), LocalSemRetorno())
    quantos = esp.aplicar_retorno(
        "1814", 31, {"001": {"codigo": "00", "estado": "ok"}},
        estado="processado")

    assert quantos == 1
    assert pedidos == [("1814", 31, {"001": {"codigo": "00", "estado": "ok"}},
                        "processado")]


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
