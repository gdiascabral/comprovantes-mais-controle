# -*- coding: utf-8 -*-
"""`conciliacao/erp/api.py` como casca sobre o `erp/`, sem tela e sem rede.

O QUE MUDOU AQUI, E POR QUÊ
---------------------------
Este arquivo trocava `urllib.request.urlopen` por um dublê, porque era ali que
o módulo falava de verdade: ele tinha um laço de novas tentativas escrito à mão
justamente por não ter `Session`/`HTTPAdapter` para montar um `Retry` pronto.

O módulo agora delega para `erp.Sessao`, que fala por `requests` — então o laço
à mão saiu (e `_TENTATIVAS_GET` com ele), e o `urlopen` deixou de ser chamado.
O alvo do dublê mudou para **`erp.sessao._SESSAO`**, que é o ponto único que o
pacote documenta para simular transporte (`erp/sessao.py:91-92`).

As três afirmações originais continuam sendo provadas, cada uma no lugar onde
agora vale:

    "GET insiste em 5xx, até 3 vezes"  -> a política do transporte que ESTAS
                                          consultas usam, conferida pela mesma
                                          função que o urllib3 chama
    "POST nunca insiste"               -> idem, e mais: o laço à mão não existe
                                          mais neste módulo
    "401 no login vira SessaoExpirada" -> igual, agora pelo `SessaoApi.logar`,
                                          que é a porta pública

O que não dá para provar com dublê é a CONTAGEM de tentativas: quem repete
passou a ser o `urllib3` dentro do adaptador, abaixo do ponto onde um dublê de
`requests.Session` entra. Por isso a prova virou a política montada — que é o
que o urllib3 consulta para decidir — em vez de contar chamadas de um laço que
não existe mais. Contar as chamadas de um laço escrito por nós continua sendo
feito onde ele existe: `tests/test_erp.py`, no relogin do 401.
"""
import pytest
from erp import hosts
from erp import sessao as erp_sessao

from conciliacao.erp import api


class _TransporteFalso:
    """Um `requests.Session` de mentira: guarda a chamada e devolve o combinado.

    Aceita uma sequência de `(status, corpo)` — é o que permite exercitar a
    paginação, em que a segunda resposta é diferente da primeira.
    """

    def __init__(self, *respostas):
        self.respostas = list(respostas) or [(200, {})]
        self.chamadas = []

    def request(self, metodo, url, headers=None, json=None, timeout=None):
        self.chamadas.append({"metodo": metodo, "url": url,
                              "headers": headers, "json": json})
        indice = min(len(self.chamadas), len(self.respostas)) - 1
        status, corpo = self.respostas[indice]
        return _Resposta(status, corpo)


class _Resposta:
    text = ""

    def __init__(self, status_code, corpo):
        self.status_code = status_code
        self._corpo = corpo

    def json(self):
        return self._corpo


class _ConfigFalso:
    """O bastante do `config` da Conciliação — o mesmo formato que o
    `_ConfigMinimo` de `nuvem/contas_novas.py` produz."""

    def __init__(self, **erp):
        self.erp = erp


def _sessao_pronta(config=None):
    """Um `SessaoApi` montado à MÃO, como a sonda e quem mais o construir.

    Sem passar pelo `logar`, de propósito: é o construtor público que precisa
    continuar servindo."""
    return api.SessaoApi(token="j" * 348, company_id="empresa-3333",
                         usuario="fulano@exemplo.test", empresa="Empresa",
                         config=config or _ConfigFalso())


# ------------------------------------------------- repetir GET, nunca POST
def test_get_repete_5xx_ate_o_sucesso():
    """Um 504 real do prod-erp-api (visto no diagnostico.log de produção,
    gateway openresty/apisix) não pode custar a rodada inteira: GET insiste,
    até 3 vezes.

    Quem repete agora é o transporte do `erp/`, e a política dele é a MESMA
    que estava escrita à mão aqui (3 tentativas, 502 a 504) — ver
    `erp/sessao.py:_montar_sessao`."""
    montada = erp_sessao._SESSAO.get_adapter(hosts.ERP_API).max_retries
    assert montada.total == 3
    assert set(montada.status_forcelist) == {502, 503, 504}
    for codigo in (502, 503, 504):
        assert montada.is_retry("GET", codigo) is True
    # 4xx não é transitório: repetir não muda a resposta.
    assert montada.is_retry("GET", 404) is False


def test_post_nao_repete_5xx():
    """Reenviar um POST que talvez já tenha valido (aqui, o login) não pode
    virar uma segunda tentativa por conta própria.

    E o laço à mão saiu deste módulo: mantê-lo ao lado do `Retry` do
    transporte daria TRÊS vezes três tentativas, sem ninguém pedir."""
    montada = erp_sessao._SESSAO.get_adapter(hosts.ERP_API).max_retries
    assert montada.is_retry("POST", 504) is False
    assert not hasattr(api, "_CODIGOS_TRANSITORIOS")
    assert not hasattr(api, "_ESPERA_ENTRE_TENTATIVAS_S")


def test_o_relogio_do_modulo_nao_tem_numero_proprio():
    """Os dois valores continuam com nome aqui — `ferramentas/sonda.py` os
    aperta —, mas saem do `erp/`. Dois números para a mesma espera seriam duas
    verdades sobre quanto o ERP pode demorar."""
    assert api._TIMEOUT_S == erp_sessao.ESPERA
    assert api._TENTATIVAS_GET == erp_sessao.TENTATIVAS


def test_apertar_o_relogio_muda_o_transporte_de_verdade(monkeypatch):
    """Um botão que não liga em nada é pior que botão nenhum.

    A sonda troca os dois números em volta da chamada; se eles ficassem só de
    enfeite, ela estaria medindo com o relógio da rodada e escondendo a
    lentidão que existe para notar."""
    monkeypatch.setattr(api, "_TENTATIVAS_GET", 1)
    monkeypatch.setattr(api, "_TIMEOUT_S", 10)
    relogio = api._relogio()

    assert relogio["espera"] == 10
    montada = relogio["transporte"].get_adapter(hosts.ERP_API).max_retries
    assert montada.total == 1
    # E não é a sessão do app: apertar o relógio de uma ferramenta não pode
    # mexer no transporte que a rodada está usando.
    assert relogio["transporte"] is not erp_sessao._SESSAO
    assert erp_sessao._SESSAO.get_adapter(
        hosts.ERP_API).max_retries.total == erp_sessao.TENTATIVAS


def test_401_no_login_continua_virando_sessao_expirada(monkeypatch):
    """A tradução que já existia não pode se perder na migração: 401 na URL de
    login é `SessaoExpirada`, não `ErpError` genérico — e o login não tenta de
    novo, porque repetir levaria a MESMA senha."""
    falso = _TransporteFalso((401, {}))
    monkeypatch.setattr(erp_sessao, "_SESSAO", falso)
    monkeypatch.setattr(api, "obter_credenciais",
                        lambda: ("fulano@exemplo.test", "senha"))

    with pytest.raises(api.SessaoExpirada):
        api.SessaoApi.logar(_ConfigFalso(), log=lambda *_a, **_k: None)
    assert len(falso.chamadas) == 1
    assert falso.chamadas[0]["metodo"] == "POST"


def test_sem_credencial_guardada_o_recado_e_o_de_sempre(monkeypatch):
    """"não há senha guardada" e "o ERP recusou a senha" pedem coisas
    diferentes de quem lê, e a frase daqui diz onde clicar."""
    monkeypatch.setattr(api, "obter_credenciais", lambda: ("", ""))
    with pytest.raises(api.SessaoExpirada, match="Salvar senha"):
        api.SessaoApi.logar(_ConfigFalso())


# ------------------------------------------------------- a casca por fora
def test_a_cara_publica_do_SessaoApi_nao_mudou():
    """Quem depende daqui — `conciliacao/erp/accounts.py`,
    `nuvem/contas_novas.py` e a sonda de `ferramentas/` — não muda uma linha.

    O construtor com os cinco campos, os quatro métodos e as duas exceções são
    o contrato; o que ficou por dentro é assunto deste arquivo."""
    sessao = _sessao_pronta()
    assert (sessao.token, sessao.company_id) == ("j" * 348, "empresa-3333")
    for metodo in ("logar", "listar_contas", "saldos", "contas"):
        assert callable(getattr(sessao, metodo))
    assert issubclass(api.SessaoExpirada, api.ErpError)


def test_o_login_devolve_a_identidade_que_o_modulo_sempre_expos(monkeypatch):
    corpo = {"jwtToken": "j" * 348, "accessToken": "a" * 27, "id": "user-1",
             "organizationUnitId": "unidade-2", "username": "fulano@exemplo.test",
             "companies": [{"id": "empresa-3333", "tradeName": "Empresa"}]}
    monkeypatch.setattr(erp_sessao, "_SESSAO", _TransporteFalso((200, corpo)))
    monkeypatch.setattr(api, "obter_credenciais",
                        lambda: ("fulano@exemplo.test", "senha"))

    sessao = api.SessaoApi.logar(_ConfigFalso(), log=lambda *_a, **_k: None)
    assert sessao.token == "j" * 348          # o jwtToken, NÃO o accessToken
    assert sessao.company_id == "empresa-3333"
    assert sessao.empresa == "Empresa"


# ----------------------------------------------------- as consultas, por host
def test_as_consultas_levam_o_jwt_o_company_id_e_o_user_agent(monkeypatch):
    """As três coisas sem as quais a leitura de saldos não existe: o token
    certo para o `prod-erp-api`, o `company-id` e o `user-agent` que passa
    pelo WAF (403 sem ele). O `user-id` fica de fora — é cabeçalho do legado."""
    falso = _TransporteFalso((200, {"items": [], "hasNextPage": False}))
    monkeypatch.setattr(erp_sessao, "_SESSAO", falso)

    _sessao_pronta().listar_contas()

    cab = falso.chamadas[-1]["headers"]
    assert cab["authorization"] == f"Bearer {'j' * 348}"
    assert cab["company-id"] == "empresa-3333"
    assert "Chrome/" in cab["user-agent"]
    assert "user-id" not in cab


def test_a_listagem_pagina_ate_o_fim(monkeypatch):
    """Perder conta em silêncio é o tipo de erro que só aparece no fechamento
    do mês, e o caminho da requisição foi refeito: vale reconferir."""
    falso = _TransporteFalso(
        (200, {"items": [{"id": "a"}], "hasNextPage": True}),
        (200, {"items": [{"id": "b"}], "hasNextPage": False}),
    )
    monkeypatch.setattr(erp_sessao, "_SESSAO", falso)

    assert _sessao_pronta().listar_contas() == [{"id": "a"}, {"id": "b"}]
    assert "pageIndex=1" in falso.chamadas[0]["url"]
    assert "pageIndex=2" in falso.chamadas[1]["url"]


def test_o_401_de_uma_consulta_vira_sessao_expirada(monkeypatch):
    """"sem rede" e "sua sessão venceu" pedem coisas diferentes de quem lê."""
    monkeypatch.setattr(erp_sessao, "_SESSAO", _TransporteFalso((401, {})))
    with pytest.raises(api.SessaoExpirada):
        _sessao_pronta().saldos(["conta-1"])


def test_o_403_continua_apontando_para_o_user_agent(monkeypatch):
    """É quase sempre ele; dizer isso na mensagem poupa a próxima investigação
    — e a mensagem agora mora no `erp/`, num lugar só."""
    monkeypatch.setattr(erp_sessao, "_SESSAO", _TransporteFalso((403, {})))
    with pytest.raises(api.ErpError, match="user-agent"):
        _sessao_pronta().listar_contas()


# --------------------------------------------------------------- endereços
def test_o_config_continua_mandando_no_endereco(monkeypatch):
    """`conciliacao/config.yaml` tem essas duas chaves e mora FORA do repo:
    passar a ignorá-las seria aceitar configuração e descartá-la em silêncio."""
    falso = _TransporteFalso((200, {"items": [], "hasNextPage": False}))
    monkeypatch.setattr(erp_sessao, "_SESSAO", falso)
    config = _ConfigFalso(api_base="https://outro-erp.exemplo.test/",
                          legacy_api_base="https://outro-legado.exemplo.test")

    _sessao_pronta(config).listar_contas()
    assert falso.chamadas[-1]["url"].startswith(
        "https://outro-erp.exemplo.test/bank-integration/")

    monkeypatch.setattr(api, "obter_credenciais", lambda: ("a@b.test", "s"))
    with pytest.raises(api.ErpError):
        api.SessaoApi.logar(config, log=lambda *_a, **_k: None)
    assert falso.chamadas[-1]["url"] == (
        "https://outro-legado.exemplo.test/users/login")


def test_sem_config_os_enderecos_saem_do_erp_hosts(monkeypatch):
    """O padrão deixou de ser escrito aqui — e é por isso que o
    `_ConfigMinimo` de `nuvem/contas_novas.py` pode sumir no PR dele."""
    falso = _TransporteFalso((200, {"items": [], "hasNextPage": False}))
    monkeypatch.setattr(erp_sessao, "_SESSAO", falso)

    _sessao_pronta(_ConfigFalso()).listar_contas()
    assert falso.chamadas[-1]["url"].startswith(hosts.ERP_API)
    assert api._base_legacy(_ConfigFalso()) == hosts.LEGACY
