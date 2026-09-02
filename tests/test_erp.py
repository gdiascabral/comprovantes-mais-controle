# -*- coding: utf-8 -*-
"""O pacote `erp/`: a regra dos dois tokens, os cabeçalhos e os transportes.

Nenhum teste daqui abre navegador nem toca na rede. O que se está guardando é
justamente o conhecimento que estava espalhado por oito arquivos e se
contradizia entre eles — ver `docs/ERP-CLIENTES.md`.
"""
import re

import pytest

from erp import hosts, pagina, sessao


# --------------------------------------------------------------- a identidade
#: O corpo de um `POST /users/login`, com o formato REAL e valores inventados.
#: Os tamanhos importam e são o que distingue os dois tokens: o `jwtToken` tem
#: ~348 chars e é JWT; o `accessToken` tem 27 e não é.
CORPO_DO_LOGIN = {
    "jwtToken": "j" * 348,
    "accessToken": "a" * 27,
    "id": "user-1111",
    "organizationUnitId": "unidade-2222",
    "username": "fulano@exemplo.test",
    "companies": [{"id": "empresa-3333", "tradeName": "Empresa de Teste"}],
}


@pytest.fixture
def sessao_logada():
    return sessao.Sessao.de_login(CORPO_DO_LOGIN)


def test_o_login_traz_os_dois_tokens_e_a_identidade_inteira(sessao_logada):
    """É o que torna o HTTP direto possível sem navegador.

    Os quatro cabeçalhos que o legado exige saem TODOS da resposta do login —
    não é preciso capturá-los do tráfego da página."""
    assert sessao_logada.jwt_token == "j" * 348
    assert sessao_logada.access_token == "a" * 27
    assert sessao_logada.company_id == "empresa-3333"
    assert sessao_logada.user_id == "user-1111"
    assert sessao_logada.organization_unit_id == "unidade-2222"


# ------------------------------------------------------- qual token para qual
def test_o_prod_erp_api_quer_o_jwt_token(sessao_logada):
    """`conciliacao/erp/api.py:33`: "o token E o jwtToken, NAO o accessToken"."""
    assert sessao_logada.token_para(hosts.ERP_API) == CORPO_DO_LOGIN["jwtToken"]
    assert sessao_logada.token_para(
        f"{hosts.ERP_API}/financial/bank-accounts/balances?x=1"
    ) == CORPO_DO_LOGIN["jwtToken"]


def test_o_legacy_api_quer_o_access_token(sessao_logada):
    """`fontes/vigia-boletos/mc_sessao.py:9`: "accessToken -> API legada"."""
    assert sessao_logada.token_para(hosts.LEGACY) == CORPO_DO_LOGIN["accessToken"]
    assert sessao_logada.token_para(
        f"{hosts.LEGACY}/payable-installments/paginated-result?page=0"
    ) == CORPO_DO_LOGIN["accessToken"]


def test_os_dois_tokens_nunca_se_confundem(sessao_logada):
    """A troca é o defeito que este pacote existe para impedir: o `jwtToken`
    no legado responde `401 invalid_token` (`mc_sessao.py:8`)."""
    assert (sessao_logada.token_para(hosts.ERP_API)
            != sessao_logada.token_para(hosts.LEGACY))


# ------------------------------------------------------ cabeçalhos, por host
def test_os_cabecalhos_do_prod_erp_api(sessao_logada):
    """Dois de identidade, e o `user-id` NÃO entra: o `prod-erp-api` não o
    manda (`aportes/mc_catalogos.py:171-172`, `lancar_mc.py:77`)."""
    cab = sessao_logada.cabecalhos_para(hosts.ERP_API)
    assert cab["authorization"] == f"Bearer {CORPO_DO_LOGIN['jwtToken']}"
    assert cab["company-id"] == "empresa-3333"
    assert "user-id" not in cab
    assert "organization-unit-id" not in cab


def test_os_cabecalhos_do_legacy_api(sessao_logada):
    """Os QUATRO. Faltando o `user-id`, o ERP recusa o lançamento com "não
    achei o usuário responsável" (`aportes/erp_sessao.py:25-30`)."""
    cab = sessao_logada.cabecalhos_para(hosts.LEGACY)
    assert cab["authorization"] == f"Bearer {CORPO_DO_LOGIN['accessToken']}"
    assert cab["company-id"] == "empresa-3333"
    assert cab["user-id"] == "user-1111"
    assert cab["organization-unit-id"] == "unidade-2222"


def test_o_user_agent_de_navegador_vai_em_toda_chamada(sessao_logada):
    """É a única coisa que separa 200 de 403 (`conciliacao/erp/api.py:23-29`).

    Vale para os dois hosts e para o login, que sai sem token nenhum."""
    for alvo in (hosts.ERP_API, hosts.LEGACY):
        cab = sessao_logada.cabecalhos_para(alvo)
        assert cab["user-agent"] == sessao.USER_AGENT
        assert "Chrome/" in cab["user-agent"]
        assert cab["origin"] == hosts.ACESSAR
    assert sessao.cabecalhos_base()["user-agent"] == sessao.USER_AGENT


def test_a_origem_e_a_tela_e_nao_o_back_end():
    """O ERP espera ser chamado de `acessar.`; é o que o WAF confere."""
    base = sessao.cabecalhos_base()
    assert base["origin"] == "https://acessar.maiscontroleerp.com.br"
    assert base["referer"].startswith(base["origin"])


# --------------------------------------------------- repetir GET, nunca POST
def test_o_get_repete_em_504_e_o_post_nao():
    """A política inteira, conferida pela função que o urllib3 chama.

    Reenviar um POST que criou algo e perdeu a resposta duplica o que foi
    criado — e aqui os POSTs criam lançamento e dão baixa em pagamento."""
    politica = sessao.politica()
    for codigo in (502, 503, 504):
        assert politica.is_retry("GET", codigo) is True
        assert politica.is_retry("POST", codigo) is False
    # 4xx não é transitório: repetir não muda a resposta.
    assert politica.is_retry("GET", 404) is False
    assert politica.total == 3
    assert politica.raise_on_status is False


def test_a_politica_esta_montada_na_sessao_do_modulo():
    """Uma política correta que ninguém montou no transporte não repete nada."""
    adaptador = sessao._SESSAO.get_adapter("https://prod-erp-api.exemplo.test")
    montada = adaptador.max_retries
    assert montada.total == 3
    assert set(montada.status_forcelist) == {502, 503, 504}
    assert montada.is_retry("POST", 504) is False


class _TransporteFalso:
    """Um `requests.Session` de mentira: guarda a chamada e devolve o combinado."""

    def __init__(self, status=200, corpo=None):
        self.status, self.corpo = status, corpo or {}
        self.chamadas = []

    def request(self, metodo, url, headers=None, json=None, timeout=None):
        self.chamadas.append({"metodo": metodo, "url": url,
                              "headers": headers, "json": json})
        return self

    # a resposta é o próprio objeto — basta ter estes três nomes
    @property
    def status_code(self):
        return self.status

    text = ""

    def json(self):
        return self.corpo


def test_o_login_sai_com_user_agent_e_sem_token():
    falso = _TransporteFalso(corpo=CORPO_DO_LOGIN)
    logada = sessao.Sessao.logar("fulano@exemplo.test", "senha", transporte=falso)

    chamada = falso.chamadas[0]
    assert chamada["metodo"] == "POST"
    assert chamada["url"] == hosts.URL_LOGIN
    assert chamada["headers"]["user-agent"] == sessao.USER_AGENT
    assert "authorization" not in chamada["headers"]
    assert logada.access_token == CORPO_DO_LOGIN["accessToken"]


def test_pedir_manda_os_cabecalhos_do_host_da_url(sessao_logada):
    falso = _TransporteFalso(corpo={"items": []})
    sessao_logada.transporte = falso
    sessao_logada.pedir(f"{hosts.LEGACY}/participants?page=0")
    assert falso.chamadas[-1]["headers"]["user-id"] == "user-1111"

    sessao_logada.pedir(f"{hosts.ERP_API}/contacts/participants")
    assert "user-id" not in falso.chamadas[-1]["headers"]


def test_o_401_vira_excecao_com_nome(sessao_logada):
    """"sem rede" e "sua sessão venceu" pedem coisas diferentes de quem lê."""
    sessao_logada.transporte = _TransporteFalso(status=401)
    with pytest.raises(sessao.SessaoRecusada):
        sessao_logada.pedir(f"{hosts.ERP_API}/financial/bank-accounts/balances")


def test_o_403_aponta_para_o_user_agent(sessao_logada):
    """É quase sempre ele; dizer isso na mensagem poupa a próxima investigação."""
    sessao_logada.transporte = _TransporteFalso(status=403)
    with pytest.raises(sessao.ErpErro, match="user-agent"):
        sessao_logada.pedir(f"{hosts.ERP_API}/bank-integration/bank-accounts")


# ------------------------------------------- o 401 do legado, que é rotina
#: O segundo login devolve tokens DIFERENTES do primeiro: é o que permite ao
#: teste provar que a chamada repetida saiu com o token novo, e não com o que
#: acabara de ser recusado.
CORPO_DO_RELOGIN = dict(CORPO_DO_LOGIN, jwtToken="J" * 348, accessToken="A" * 27)


class _TransporteEmSequencia:
    """Um `requests.Session` de mentira que responde uma coisa por chamada.

    O `_TransporteFalso` responde sempre o mesmo, e aqui o que importa é
    justamente a MUDANÇA entre uma chamada e a seguinte: 401, login, 200.
    """

    def __init__(self, *respostas):
        self.respostas = list(respostas)          # [(status, corpo), …]
        self.chamadas = []

    def request(self, metodo, url, headers=None, json=None, timeout=None):
        self.chamadas.append({"metodo": metodo, "url": url,
                              "headers": headers, "json": json})
        status, corpo = self.respostas[len(self.chamadas) - 1]
        return _Resposta(status, corpo)


class _Resposta:
    text = ""

    def __init__(self, status_code, corpo):
        self.status_code = status_code
        self._corpo = corpo

    def json(self):
        return self._corpo


def _com_credencial(transporte):
    """Uma sessão que ENTROU — só quem entregou a senha pode relogar."""
    falso = _TransporteFalso(corpo=CORPO_DO_LOGIN)
    logada = sessao.Sessao.logar("fulano@exemplo.test", "senha", transporte=falso)
    logada.transporte = transporte
    return logada


def test_o_401_do_legado_relogia_uma_vez_e_repete_o_get():
    """O `accessToken` vive SEGUNDOS: vencer no meio do trabalho é rotina.

    Sem isto, qualquer rotina que demore entre duas chamadas ao legado quebra
    no meio — e o desfecho não é um erro claro, é meia coleta
    (`docs/ERP-CLIENTES.md`, seção 1, consequência 2).
    """
    logada = _com_credencial(_TransporteEmSequencia(
        (401, {}),                      # o token venceu entre uma e outra
        (200, CORPO_DO_RELOGIN),        # o relogin
        (200, {"items": [{"id": "x"}]}),  # a mesma chamada, de novo
    ))
    alvo = f"{hosts.LEGACY}/payable-installments/paginated-result?page=0"

    assert logada.pedir(alvo) == {"items": [{"id": "x"}]}

    chamadas = logada.transporte.chamadas
    assert [c["metodo"] for c in chamadas] == ["GET", "POST", "GET"]
    assert chamadas[1]["url"] == hosts.URL_LOGIN
    # A repetição sai com o token NOVO. Repetir com o que acabou de ser
    # recusado seria pagar duas chamadas para levar o mesmo 401.
    assert chamadas[2]["headers"]["authorization"] == (
        f"Bearer {CORPO_DO_RELOGIN['accessToken']}")
    # E o jwt do outro host veio junto: metade do login guardada deixaria duas
    # idades na mesma sessão.
    assert logada.jwt_token == CORPO_DO_RELOGIN["jwtToken"]


def test_o_401_que_insiste_vira_excecao_e_nao_laco():
    """Duas voltas e para. Um ERP que responde 401 a tudo — conta bloqueada,
    sessão tomada por outro login — não pode virar login em loop contra o WAF,
    que penaliza justamente tentativa repetida."""
    logada = _com_credencial(_TransporteEmSequencia(
        (401, {}), (200, CORPO_DO_RELOGIN), (401, {}),
    ))
    with pytest.raises(sessao.SessaoRecusada):
        logada.pedir(f"{hosts.LEGACY}/categories/all")
    assert len(logada.transporte.chamadas) == 3


def test_o_401_do_prod_erp_api_nao_relogia():
    """Lá o token vale 24 h: 401 é sessão recusada de verdade.

    O ERP aceita UMA sessão por usuário, e relogar aqui tomaria de volta, em
    silêncio, a sessão que outro login pegou
    (`conciliacao/erp/collect.py:98-108`)."""
    logada = _com_credencial(_TransporteEmSequencia((401, {})))
    with pytest.raises(sessao.SessaoRecusada):
        logada.pedir(f"{hosts.ERP_API}/financial/bank-accounts/balances")
    assert len(logada.transporte.chamadas) == 1


def test_o_post_no_legado_nao_relogia_sem_a_marca():
    """Um POST que criou lançamento e perdeu a resposta duplica o que criou.

    O padrão é não repetir, e o padrão é o seguro: esquecer a marca custa uma
    exceção; pôr a marca onde não cabe custa uma segunda baixa."""
    logada = _com_credencial(_TransporteEmSequencia((401, {})))
    with pytest.raises(sessao.SessaoRecusada):
        logada.pedir(f"{hosts.LEGACY}/payable-installments/p1/paids",
                     metodo="POST", corpo={"value": 1})
    assert len(logada.transporte.chamadas) == 1


def test_o_post_marcado_como_idempotente_relogia():
    """Quem conhece a rota é o chamador, e é ele que assume a marca."""
    logada = _com_credencial(_TransporteEmSequencia(
        (401, {}), (200, CORPO_DO_RELOGIN), (200, {"ok": True}),
    ))
    resposta = logada.pedir(f"{hosts.LEGACY}/payable-installments/p1",
                            metodo="PUT", corpo={"value": 1}, idempotente=True)
    assert resposta == {"ok": True}
    assert [c["metodo"] for c in logada.transporte.chamadas] == [
        "PUT", "POST", "PUT"]


def test_sem_credencial_guardada_nao_ha_relogin(sessao_logada):
    """`de_login` recebe o corpo pronto e não vê senha nenhuma.

    Relogar ali seria relogar em nome de quem não entregou a credencial — e
    não há credencial para entregar."""
    sessao_logada.transporte = _TransporteEmSequencia((401, {}))
    with pytest.raises(sessao.SessaoRecusada):
        sessao_logada.pedir(f"{hosts.LEGACY}/categories/all")
    assert len(sessao_logada.transporte.chamadas) == 1


def test_a_senha_recusada_no_login_nao_vira_relogin():
    """401 no PRÓPRIO login é senha errada: repetir leva a mesma senha."""
    falso = _TransporteEmSequencia((401, {}))
    with pytest.raises(sessao.SessaoRecusada, match="recusou a senha"):
        sessao.Sessao.logar("fulano@exemplo.test", "errada", transporte=falso)
    assert len(falso.chamadas) == 1


def test_a_senha_nao_aparece_no_repr_da_sessao():
    """Objeto de sessão vai parar em log e em traceback; senha, não.

    O `usuario` continua aparecendo, e é de propósito: é ele que responde
    "conectado como quem?" no log da coleta."""
    falso = _TransporteFalso(corpo=CORPO_DO_LOGIN)
    logada = sessao.Sessao.logar("fulano@exemplo.test", "senha-secreta",
                                 transporte=falso)
    assert "senha-secreta" not in repr(logada)


# ------------------------------------------------------- transporte de página
def _js_do_arquivo(caminho, nome):
    """O bloco JS atribuído a `nome` no arquivo, ou None se não existir mais."""
    if not caminho.is_file():
        return None
    texto = caminho.read_text(encoding="utf-8")
    achado = re.search(rf'{nome}\s*=\s*"""(.*?)"""', texto, re.S)
    return achado.group(1) if achado else None


def _sem_espacos(js):
    """Compara SEMÂNTICA, não espaçamento: as duas cópias só diferem nos
    espaços dentro das chaves (`{ url, headers }` × `{url, headers}`)."""
    return re.sub(r"\s+", "", js or "")


def test_o_js_do_transporte_de_pagina_existe():
    assert "fetch(" in pagina.JS_FETCH_JSON
    assert "__erro: r.status" in pagina.JS_FETCH_JSON
    assert "method: 'POST'" in pagina.JS_POST_JSON


def test_o_js_e_o_mesmo_para_os_dois_usos(request):
    """`anexar/mc_api.py` e `aportes/mc_catalogos.py` escreveram o MESMO bloco.

    Duas cópias de um transporte é uma divergência esperando acontecer — a
    mesma razão que juntou as três capturas de cabeçalho em
    `aportes/erp_sessao.py`. Enquanto os dois consumidores não migram, este
    teste guarda que o bloco daqui continua sendo o deles: divergir agora
    faria a migração mudar comportamento sem ninguém pedir.
    """
    raiz = request.config.rootpath
    copias = {
        "anexar/mc_api.py": _js_do_arquivo(raiz / "anexar" / "mc_api.py",
                                           "_JS_FETCH_JSON"),
        "aportes/mc_catalogos.py": _js_do_arquivo(
            raiz / "aportes" / "mc_catalogos.py", "_JS_FETCH"),
    }
    presentes = {onde: js for onde, js in copias.items() if js}
    if not presentes:
        pytest.skip("os dois consumidores ja migraram para o erp/pagina.py")

    alvo = _sem_espacos(pagina.JS_FETCH_JSON)
    divergentes = {onde: js for onde, js in presentes.items()
                   if _sem_espacos(js) != alvo}
    assert not divergentes, (
        "o JS de erp/pagina.py deixou de ser o mesmo destes arquivos: "
        f"{sorted(divergentes)}. Ou o pacote muda junto, ou a migração deles "
        "vai trocar o comportamento sem ninguém pedir.")


class _PaginaFalsa:
    """A `page` do Playwright, do tamanho que este transporte usa."""

    def __init__(self, resposta=None):
        self.resposta = resposta if resposta is not None else {"ok": True}
        self.chamadas = []

    def evaluate(self, js, argumento):
        self.chamadas.append((js, argumento))
        return self.resposta


def test_o_transporte_de_pagina_escolhe_o_cabecalho_pelo_host():
    """Reaproveitar o cabeçalho de um host noutro devolve 401 — foi assim que
    o token da telemetria acabou usado contra o `prod-erp-api`."""
    falsa = _PaginaFalsa()
    transporte = pagina.TransportePagina(falsa, {
        hosts.HOST_ERP_API: {"authorization": "Bearer novo",
                             "company-id": "empresa-3333"},
        hosts.HOST_LEGACY: {"authorization": "Bearer legado",
                            "user-id": "user-1111"},
    })

    transporte.buscar(f"{hosts.ERP_API}/natures")
    assert falsa.chamadas[-1][1]["headers"]["authorization"] == "Bearer novo"

    transporte.buscar(f"{hosts.LEGACY}/categories/all")
    assert falsa.chamadas[-1][1]["headers"]["authorization"] == "Bearer legado"


def test_o_mapa_plano_de_cabecalhos_continua_valendo():
    """A forma antiga (um conjunto só, para tudo) não pode parar de funcionar:
    é a que `anexar/mc_api.py` produz."""
    falsa = _PaginaFalsa()
    transporte = pagina.TransportePagina(falsa, {"authorization": "Bearer um só"})
    transporte.buscar(f"{hosts.ERP_API}/natures")
    assert falsa.chamadas[-1][1]["headers"] == {"authorization": "Bearer um só"}


def test_o_cabecalho_e_procurado_em_todos_os_hosts():
    """O `user-id` só vem do legado, e quem precisa dele nem sempre sabe de
    qual tela ele veio (`aportes/mc_catalogos.py:168-181`)."""
    transporte = pagina.TransportePagina(_PaginaFalsa(), {
        hosts.HOST_ERP_API: {"authorization": "Bearer novo"},
        hosts.HOST_LEGACY: {"authorization": "Bearer legado",
                            "user-id": "user-1111"},
    })
    assert transporte.cabecalho("user-id") == "user-1111"
    assert transporte.cabecalho("organization-unit-id") is None


def test_o_transporte_de_pagina_serve_o_baixa_erp_sem_adaptador():
    """`pagamentos_dia/baixa_erp.py:208-214` exige `_buscar` e `postar`."""
    transporte = pagina.TransportePagina(_PaginaFalsa(), {})
    assert callable(transporte._buscar)
    assert callable(transporte.postar)
    assert transporte._buscar.__func__ is transporte.buscar.__func__


# ------------------------------------------------------------------- endereços
def test_os_hosts_sao_os_tres_conhecidos():
    assert hosts.host_de(hosts.ACESSAR) == hosts.HOST_ACESSAR
    assert hosts.eh_erp_api(hosts.ERP_API)
    assert hosts.eh_legacy(hosts.LEGACY)
    assert not hosts.eh_legacy(hosts.ERP_API)
    #: A raiz de serviço faz parte do endereço do legado: sem ela o caminho
    #: não existe.
    assert hosts.LEGACY.endswith("/maiscontrole/services")


def test_a_telemetria_fica_de_fora_da_captura():
    """Ela carrega token PRÓPRIO, e misturá-lo fez o `prod-erp-api` devolver
    401 (`aportes/erp_sessao.py:21-23`)."""
    assert hosts.vale_a_pena(hosts.HOST_ERP_API)
    assert hosts.vale_a_pena("abc123.execute-api.us-east-1.amazonaws.com")
    assert not hosts.vale_a_pena("api-data-event.maiscontroleerp.com.br")
    assert not hosts.vale_a_pena("faro.exemplo.test")
    assert not hosts.vale_a_pena("outro-sistema.com.br")
