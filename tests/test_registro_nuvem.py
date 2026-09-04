# -*- coding: utf-8 -*-
"""O registro central das remessas, sem rede.

A atomicidade da alocação é do Postgres e foi medida contra o projeto de
verdade (12 pedidos simultâneos, 12 números distintos). O que se testa aqui é
o que o Python decide: quem consome número e quem só olha, o que conta como
"já enviado", e a regra de que o espelho local não tem voto.
"""

import datetime as _dt
import types
from decimal import Decimal

import pytest

from cnab240 import historico
from nuvem import registro, rest


class _RestFalso:
    """Anota o que foi pedido, devolve o que o teste mandar."""

    def __init__(self, **respostas):
        self.respostas = respostas
        self.chamadas = []
        #: {tabela: exceção} — o que o banco RECUSA ao inserir. É como se
        #: encena um índice único batendo no meio de uma gravação de duas
        #: idas.
        self.recusa_inserir = {}

    def ler(self, tabela, _token, *, colunas="*", filtro=""):
        self.chamadas.append(("ler", tabela, filtro))
        return self.respostas.get(tabela, [])

    def inserir(self, tabela, _token, linhas, *, devolver=True):
        self.chamadas.append(("inserir", tabela, len(linhas)))
        if tabela in self.recusa_inserir:
            raise self.recusa_inserir[tabela]
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


# ------------------------------------------------------ a ordem do dia

DIA = _dt.date(2026, 9, 4)


def _filtros_lidos(falso, tabela):
    return [c[2] for c in falso.chamadas if c[0] == "ler" and c[1] == tabela]


def test_a_ordem_do_dia_e_uma_consulta_filtrada(falso):
    """UMA ida, UMA linha — e o dia dentro do filtro.

    Antes, quem numerava varria `remessas()`: todas as remessas com todos os
    itens dentro, a cada geração (0,44 s com sete). O `like` por prefixo do dia
    com `order` desc e `limit` 1 devolve o maior de uma vez porque a ordem tem
    quatro dígitos com zero à esquerda — o formato ordena lexicograficamente
    igual ao numérico.
    """
    falso.respostas["remessa_item"] = [{"seu_numero": "260904-0031"}]
    assert registro.Registro("tok").maior_ordem_do_dia(DIA) == 31

    filtro, = _filtros_lidos(falso, "remessa_item")
    assert "seu_numero=like.260904-*" in filtro     # `*` é o curinga do PostgREST
    assert "order=seu_numero.desc" in filtro
    assert "limit=1" in filtro


def test_a_consulta_do_dia_nao_filtra_por_convenio_nem_por_estado(falso):
    """A ordem é do DIA, de todas as contas e de todas as máquinas.

    É ela que o banco devolve no retorno para casar cada pagamento, e o índice
    único que a protege (`remessa_item_seu_numero_unico_no_dia`) não olha
    convênio nem estado. Filtrar aqui daria dois pagamentos com o mesmo número
    — e o segundo arquivo recusado no INSERT, depois da conferência.
    """
    falso.respostas["remessa_item"] = []
    registro.Registro("tok").maior_ordem_do_dia(DIA)

    filtro, = _filtros_lidos(falso, "remessa_item")
    assert "convenio" not in filtro
    assert "estado" not in filtro


@pytest.mark.parametrize("seu_numero, esperado", [
    ("260904-0007", 7),
    ("260904-0007-OC5825", 7),        # a OC vem depois da ordem, e não a muda
    ("260903-0099", 0),               # outro dia: não empurra a numeração
    ("", 0),
    ("sem forma nenhuma", 0),
])
def test_o_numero_da_ordem_sai_da_linha_que_voltou(falso, seu_numero, esperado):
    falso.respostas["remessa_item"] = [{"seu_numero": seu_numero}]
    assert registro.Registro("tok").maior_ordem_do_dia(DIA) == esperado


def test_dia_sem_remessa_nenhuma_comeca_do_zero(falso):
    falso.respostas["remessa_item"] = []
    assert registro.Registro("tok").maior_ordem_do_dia(DIA) == 0


def test_a_consulta_do_dia_nao_engole_erro_de_rede(falso, monkeypatch):
    """Devolver 0 aqui é a segunda remessa do dia recomeçando em 0001.

    Era inofensivo enquanto ninguém conferia; com o índice único, vira arquivo
    recusado DEPOIS de a pessoa ter conferido a lista inteira."""
    def _cai(*_a, **_k):
        raise rest.SemRede("sem internet")

    monkeypatch.setattr(registro.rest, "ler", _cai)
    with pytest.raises(rest.SemRede):
        registro.Registro("tok").maior_ordem_do_dia(DIA)


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


# ------------------------- de que remessa este retorno fala ("seu número")

def _achado(seu_numero, remessa_id, *, nsa=31, convenio="1814",
            estado="gerado", arquivo="REM_000031.REM"):
    """Uma linha do `remessa_item` com a `remessa` embutida, como o PostgREST
    a devolve quando se pede `remessa(...)` no `select`."""
    return {"seu_numero": seu_numero, "remessa_id": remessa_id,
            "remessa": {"id": remessa_id, "convenio": convenio, "nsa": nsa,
                        "estado": estado, "arquivo": arquivo}}


def _linha_da_remessa(nsa=31, convenio="1814"):
    """A remessa COM os itens, que é o que a segunda ida busca."""
    return [{"nsa": nsa, "convenio": convenio, "arquivo": "REM_000031.REM",
             "remessa_item": [{"seu_numero": "260904-0001",
                               "referencia": "id-erp-1"},
                              {"seu_numero": "260904-0002",
                               "referencia": "id-erp-2"}]}]


def test_a_pergunta_pelos_seus_numeros_usa_o_filtro_in(falso):
    """UMA ida com a lista inteira, e não uma consulta por pagamento.

    E a segunda ida traz a remessa COM TODOS os itens: os que o banco não
    citou são justamente os que respondem o que ficou faltando."""
    falso.respostas["remessa_item"] = [_achado("260904-0001", 5)]
    falso.respostas["remessa"] = _linha_da_remessa()

    achada = registro.Registro("tok").remessa_dos_seus_numeros(
        ["260904-0001", "260904-0002"])

    assert achada["nsa"] == 31 and achada["convenio"] == "1814"
    assert len(achada["remessa_item"]) == 2
    filtro, = _filtros_lidos(falso, "remessa_item")
    assert filtro == "seu_numero=in.(260904-0001,260904-0002)"


def test_a_pergunta_pelos_seus_numeros_nao_filtra_estado(falso):
    """Ao contrário do `_procurar`: aqui não se procura onde o pagamento ainda
    vale, e sim de que remessa o arquivo fala. Uma remessa descartada que
    compartilhe o número não é para ser ignorada — é para ser a segunda
    candidata que faz esta consulta recusar."""
    falso.respostas["remessa_item"] = []
    registro.Registro("tok").remessa_dos_seus_numeros(["260904-0001"])

    filtro, = _filtros_lidos(falso, "remessa_item")
    assert "estado" not in filtro


def test_seus_numeros_em_duas_remessas_nao_casam(falso):
    """A regra inteira deste método.

    O índice `remessa_item_seu_numero_unico_no_dia` é PARCIAL pela data
    (`criado_em >= 2026-09-05`), porque o histórico é append-only e a
    repetição de 20/08/2026 continua lá dentro — naquele dia a segunda remessa
    repetiu `260820-0004`…`0010`. Escolher uma das duas é aplicar o retorno na
    remessa errada: dar por pago o pagamento de outra conta e baixar o
    lançamento errado no ERP."""
    falso.respostas["remessa_item"] = [_achado("260820-0004", 5, nsa=31),
                                       _achado("260820-0004", 6, nsa=32)]
    falso.respostas["remessa"] = _linha_da_remessa()

    assert registro.Registro("tok").remessa_dos_seus_numeros(
        ["260820-0004"]) is None
    # E nem chega a perguntar pelos itens: não há remessa para pedir.
    assert not _filtros_lidos(falso, "remessa")


def test_nenhum_seu_numero_achado_nao_casa(falso):
    falso.respostas["remessa_item"] = []
    reg = registro.Registro("tok")

    assert reg.remessa_dos_seus_numeros(["260904-0001"]) is None
    assert not _filtros_lidos(falso, "remessa")


def test_lista_vazia_nao_pergunta_nada(falso):
    """Perguntar por nada traria a primeira linha qualquer da tabela — é a
    mesma trava do `envio_de("")`."""
    reg = registro.Registro("tok")

    assert reg.remessa_dos_seus_numeros([]) is None
    assert reg.remessa_dos_seus_numeros(["", "   "]) is None
    assert not falso.chamadas


def test_a_pergunta_e_quebrada_em_lotes(falso):
    """O que aperta não é o banco, é o TAMANHO DA URL.

    Um retorno de 18 contas traz centenas de pagamentos, cada "seu número" tem
    20 posições, e uma URL de alguns milhares de caracteres é recusada por
    proxy antes de chegar ao PostgREST — o que apareceria como erro de rede
    numa consulta que estava certa."""
    falso.respostas["remessa_item"] = [_achado("260904-0001", 5)]
    falso.respostas["remessa"] = _linha_da_remessa()
    seus = [f"260904-{n:04d}" for n in range(1, 151)]

    assert registro.Registro("tok").remessa_dos_seus_numeros(seus) is not None

    filtros = _filtros_lidos(falso, "remessa_item")
    assert len(filtros) == 2
    assert filtros[0].count(",") == registro.LOTE_DE_SEUS_NUMEROS - 1
    assert filtros[1].count(",") == 49
    # Os lotes são pedaços da MESMA lista, na ordem: nada se perde no meio.
    assert filtros[0].startswith("seu_numero=in.(260904-0001,")
    assert filtros[1].endswith(",260904-0150)")


def test_o_que_nao_parece_seu_numero_nao_entra_no_filtro(falso):
    """Estes valores vêm do ARQUIVO que o banco devolveu, não de nós.

    Num `.RET` truncado ou de outro layout, uma vírgula ou um parêntese ali
    dentro não seriam um número que não achamos — seriam um filtro diferente
    do que se quis escrever."""
    falso.respostas["remessa_item"] = []
    registro.Registro("tok").remessa_dos_seus_numeros(
        ["260904-0001", "260904-0002,estado=eq.gerado", "(x)", "  ",
         "260904-0001"])

    filtro, = _filtros_lidos(falso, "remessa_item")
    assert filtro == "seu_numero=in.(260904-0001)"


def test_o_espelhado_repassa_a_pergunta_para_a_nuvem():
    """Pelo mesmo motivo do NSA e da ordem do dia: o arquivo local só conhece
    as remessas que saíram DESTE computador — e o caso que este caminho existe
    para resolver é justamente o retorno de uma gerada em outra máquina."""
    class Nuvem:
        def remessa_dos_seus_numeros(self, seus):
            return {"nsa": 31, "seus": list(seus)}

    class LocalCego:
        def remessa_dos_seus_numeros(self, _seus):
            raise AssertionError("o espelho local não responde por esta")

    esp = registro.Espelhado(Nuvem(), LocalCego())
    assert esp.remessa_dos_seus_numeros(["260904-0001"])["nsa"] == 31


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


# -------------------------------------------- a corrida vira recusa limpa

def _remessa_falsa(nsa=7, seu_numero="260904-0001"):
    """O mínimo de um `ArquivoRemessa` para `registrar` — sem tocar no cnab240.

    Convênio "123456" e conta "12.345-6" são os de mentira da casa: o
    repositório é público.
    """
    pagamento = types.SimpleNamespace(
        seu_numero=seu_numero, valor=Decimal("10.00"), codigo_barras="",
        nome_cedente="FORNECEDOR EXEMPLO")
    return types.SimpleNamespace(
        nsa=nsa,
        empresa=types.SimpleNamespace(
            convenio="123456", nome="EMPRESA EXEMPLO LTDA",
            documento="11.222.333/0001-81", agencia="4321", conta="12.345-6"),
        lotes=[types.SimpleNamespace(produto="TITULOS_COBRANCA",
                                     pagamentos=[pagamento])],
        texto=lambda: "conteudo do arquivo",
    )


def test_itens_recusados_nao_deixam_remessa_vazia_na_nuvem(falso):
    """São dois INSERTs, e o segundo pode ser recusado depois do primeiro.

    É o desfecho da corrida que o índice único do "seu número" do dia passou a
    julgar: duas máquinas leem a mesma "maior ordem", montam arquivos com os
    mesmos números, e a segunda a gravar perde os itens — com a linha da
    `remessa` já dentro e o NSA já queimado. Sem tratar isso, o que fica na
    nuvem é uma remessa `gerado` SEM ITEM NENHUM: ela conta como envio vivo em
    toda consulta e não tem de-para para o retorno do banco achar o caminho de
    volta.
    """
    falso.recusa_inserir["remessa_item"] = rest.RecusadoPeloBanco(
        'duplicate key value violates unique constraint '
        '"remessa_item_seu_numero_unico_no_dia"')

    with pytest.raises(rest.RecusadoPeloBanco):
        registro.Registro("tok").registrar(_remessa_falsa(nsa=7),
                                           caminho_arquivo="REM0007.REM")

    marcacoes = [c for c in falso.chamadas if c[0] == "alterar"]
    assert marcacoes, "a remessa ficou `gerado` e sem itens na nuvem"
    _, tabela, filtro, mudancas = marcacoes[0]
    assert tabela == "remessa"
    assert "convenio=eq.123456" in filtro and "nsa=eq.7" in filtro
    assert mudancas["estado"] == "descartado"
    assert "itens recusados pelo banco" in mudancas["observacao"]


def test_a_recusa_original_e_a_que_sobe(falso, monkeypatch):
    """Marcar é best-effort; a exceção do banco é que impede o `.tmp` de virar
    `.REM`, e quem apaga o `.tmp` é quem chamou."""
    falso.recusa_inserir["remessa_item"] = rest.RecusadoPeloBanco("seu numero repetido")

    def _alterar_tambem_cai(*_a, **_k):
        raise rest.SemRede("a rede caiu no meio")

    monkeypatch.setattr(registro.rest, "alterar", _alterar_tambem_cai)
    with pytest.raises(rest.RecusadoPeloBanco, match="seu numero repetido"):
        registro.Registro("tok").registrar(_remessa_falsa())


def test_remessa_gravada_com_sucesso_nao_e_descartada(falso):
    """A rede de segurança não pode disparar no caminho normal."""
    registro.Registro("tok").registrar(_remessa_falsa(), caminho_arquivo="x.REM")
    assert not [c for c in falso.chamadas if c[0] == "alterar"]
    assert falso.respostas["_inseridos"]["remessa_item"][0]["seu_numero"] == "260904-0001"


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


def test_a_ordem_do_dia_tambem_vem_sempre_da_nuvem():
    """Pelo mesmo motivo do NSA: o arquivo local só conhece as remessas que
    saíram DESTE computador, e a ordem do dia precisa valer entre máquinas."""
    class Nuvem:
        def maior_ordem_do_dia(self, _quando):
            return 12

    class LocalAtrasado:
        def maior_ordem_do_dia(self, _quando):
            raise AssertionError("o espelho local não responde a ordem do dia")

    esp = registro.Espelhado(Nuvem(), LocalAtrasado())
    assert esp.maior_ordem_do_dia(DIA) == 12
