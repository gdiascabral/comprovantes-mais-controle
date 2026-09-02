# -*- coding: utf-8 -*-
"""A sonda diária, com o transporte dublado. Nenhum teste aqui toca a rede.

Uma sonda é feita de duas metades, e as duas erram calado. A primeira é ler
certo o que o terceiro respondeu — e o que se testa dela é o **desfecho**: cada
sistema, respondendo ou não, tem de virar a linha certa do `sonda.log`, com
`ok`/`falhou` e um motivo que cabe numa linha. A segunda é o **ALERTA**: ele
tem de nascer quando algo falha e, principalmente, **sumir** quando tudo volta.
Alarme que fica para trás depois de resolvido é a forma mais rápida de ensinar
alguém a ignorar alarme — e é a metade que ninguém percebe estar quebrada,
porque um arquivo que sobra parece zelo.

O ponto que se troca em cada sistema é o MESMO que os testes que já existem
trocam: `urllib.request.urlopen` para o ERP e para os portais (é por ele que
`conciliacao/erp/api._requisitar` fala — ver `test_conciliacao_erp_api.py`) e
`rest._SESSAO` para a nuvem (o `nuvem/rest.py` diz, no próprio comentário, que
é "o ponto único que os testes trocam para simular o transporte").
"""
import base64
import io
import json
import logging
import socket
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import pytest
import requests

_RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_RAIZ))
sys.path.insert(0, str(_RAIZ / "ferramentas"))

import sonda                                                      # noqa: E402
from conciliacao.erp import api                                   # noqa: E402
from nuvem import rest, sessao                                    # noqa: E402


# ------------------------------------------------------------------ dublês

@pytest.fixture(autouse=True)
def _log_de_teste(monkeypatch):
    """A suíte não escreve no `diagnostico.log` de quem a roda.

    Mesma razão da fixture `atividade_gravada` do `conftest.py`: aquele arquivo
    é o que se consulta quando uma máquina de verdade diz só "não abriu", e
    encher de linhas de teste um diagnóstico de produção é tirar dele o pouco
    que ele tem — a certeza de que tudo ali aconteceu de verdade."""
    monkeypatch.setattr(sonda, "log", logging.getLogger("sonda_de_teste"))


class _RespostaHttp:
    """O bastante de `http.client.HTTPResponse` para o que a sonda usa:
    `read()` (o ERP) e `status` (os portais), dentro de um `with`."""

    def __init__(self, corpo=b"", status: int = 200):
        self._corpo = corpo
        self.status = status

    def read(self):
        return self._corpo

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def _urlopen(sequencia):
    """Um `urlopen` de mentira que consome `sequencia` na ordem.

    `bytes` vira resposta 200 com aquele corpo; `int` vira `HTTPError` com
    aquele código; uma exceção é levantada como está. `chamadas` guarda os
    métodos, que é o que os testes dos portais conferem."""
    estado = {"n": 0, "metodos": []}

    def falso(req, timeout=None):
        estado["n"] += 1
        estado["metodos"].append(req.get_method())
        item = sequencia[min(estado["n"], len(sequencia)) - 1]
        if isinstance(item, int):
            raise urllib.error.HTTPError(
                req.full_url, item, "recusado", {}, io.BytesIO(b""))
        if isinstance(item, Exception):
            raise item
        return _RespostaHttp(item)

    return falso, estado


class _SoqueteFalso:
    """Um soquete que só sabe entrar e sair de um `with` — é tudo o que o
    `_aperto_de_mao_tls` faz com ele."""

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


class _ContextoTlsFalso:
    def wrap_socket(self, _soquete, server_hostname=None):
        return _SoqueteFalso()


def _tls_responde(monkeypatch, erro: Exception | None = None):
    """Dubla o aperto de mão TLS no transporte — `socket.create_connection`.

    Sem isto, o caminho do portal mudo tentaria abrir uma conexão de verdade, e
    a suíte passaria a depender do DNS da máquina que a roda."""
    def create_connection(*_a, **_k):
        if erro is not None:
            raise erro
        return _SoqueteFalso()

    monkeypatch.setattr(sonda.socket, "create_connection", create_connection)
    monkeypatch.setattr(sonda.ssl, "create_default_context",
                        _ContextoTlsFalso)


def _corpo(dados) -> bytes:
    return json.dumps(dados).encode()


_LOGIN_OK = _corpo({"jwtToken": "j" * 348, "username": "quem@exemplo.com",
                    "companies": [{"id": "empresa-1", "tradeName": "Empresa"}]})


def _contas(quantas: int) -> bytes:
    return _corpo({"items": [{"id": f"c{i}", "name": f"CONTA {i}"}
                             for i in range(quantas)],
                   "hasNextPage": False})


class _RespostaRequests:
    """O bastante de `requests.Response` para o `nuvem/rest._resposta`."""

    def __init__(self, status: int, corpo=None):
        self.status_code = status
        self._corpo = corpo
        self.text = json.dumps(corpo) if corpo is not None else ""
        self.content = self.text.encode()

    def json(self):
        if self._corpo is None:
            raise ValueError("não é JSON")
        return self._corpo


def _nuvem_responde(monkeypatch, resposta):
    def falso(*_a, **_k):
        if isinstance(resposta, Exception):
            raise resposta
        return resposta
    monkeypatch.setattr(rest._SESSAO, "request", falso)
    monkeypatch.setattr(rest._SESSAO, "post", falso)


def _jwt(exp: int) -> str:
    """Um JWT de mentira: só o miolo importa, ninguém verifica assinatura."""
    miolo = base64.urlsafe_b64encode(
        json.dumps({"exp": exp, "email": "quem@exemplo.com",
                    "sub": "11111111-1111-1111-1111-111111111111"})
        .encode()).decode().rstrip("=")
    return f"cabecalho.{miolo}.assinatura"


@pytest.fixture
def sessao_valida(monkeypatch):
    """Sessão COMPLETA e no prazo: `sessao.token` devolve sem falar com rede.

    Completa (com papel e situação) porque é assim que ela fica desde o
    primeiro login; sem `situacao`, o `_recuperar_o_perfil` sairia buscando o
    perfil no servidor e o teste passaria a depender do transporte errado."""
    bom = _jwt(int(time.time()) + 3600)
    monkeypatch.setattr(sessao, "_ler", lambda _p=None: {
        "acesso": bom, "renovacao": "r", "email": "quem@exemplo.com",
        "papel": "operador", "situacao": "ativo"})
    return bom


@pytest.fixture
def com_senha_do_erp(monkeypatch):
    """Há senha guardada — sem ler o `login.dat` de quem roda a suíte."""
    monkeypatch.setattr(sonda.credenciais, "carregar",
                        lambda: ("quem@exemplo.com", "senha"))
    monkeypatch.delenv("MC_EMAIL", raising=False)
    monkeypatch.delenv("MC_SENHA", raising=False)


# ---------------------------------------------------------------------- ERP

def test_erp_que_responde_vira_uma_linha_ok(monkeypatch, com_senha_do_erp):
    """Login + listagem: o desfecho bom, e o número de contas no motivo.

    O GET vai junto de propósito — o login pode continuar respondendo depois
    de a listagem mudar de contrato, e foi a listagem que quebrou as duas
    vezes que o ERP surpreendeu a gente."""
    falso, _ = _urlopen([_LOGIN_OK, _contas(3)])
    monkeypatch.setattr(urllib.request, "urlopen", falso)

    r = sonda.sondar_erp()

    assert (r.sistema, r.ok, r.motivo) == ("erp", True, "3 contas")
    assert "  erp        ok      " in sonda.linha(r)


def test_erp_que_recusa_a_senha_vira_falhou(monkeypatch, com_senha_do_erp):
    """403 no `/users/login` é o WAF ou a senha — nos dois casos, notícia.

    E o motivo tem de caber numa linha: o `erp/api.py` responde a isso com
    três linhas de instrução, certas na tela do app e impossíveis num log de
    uma linha por sistema."""
    falso, _ = _urlopen([403])
    monkeypatch.setattr(urllib.request, "urlopen", falso)

    r = sonda.sondar_erp()

    assert r.ok is False
    assert "\n" not in r.motivo and r.motivo
    assert "falhou" in sonda.linha(r)


def test_erp_sem_rede_vira_falhou(monkeypatch, com_senha_do_erp):
    falso, _ = _urlopen([urllib.error.URLError("sem DNS")])
    monkeypatch.setattr(urllib.request, "urlopen", falso)

    r = sonda.sondar_erp()

    assert r.ok is False
    assert "falha de rede" in r.motivo


def test_erp_que_loga_e_devolve_lista_vazia_e_falha(monkeypatch,
                                                    com_senha_do_erp):
    """Zero conta ATIVA não acontece nesta empresa.

    Ou o filtro parou de filtrar, ou o contrato da resposta mudou — e é
    exatamente esta a forma de quebra que a raspagem antiga tinha: continuava
    "funcionando", só que sem trazer nada."""
    falso, _ = _urlopen([_LOGIN_OK, _contas(0)])
    monkeypatch.setattr(urllib.request, "urlopen", falso)

    r = sonda.sondar_erp()

    assert r.ok is False
    assert "sem nenhuma conta" in r.motivo


def test_sem_senha_guardada_a_sonda_nem_tenta(monkeypatch):
    """Falha, e com o motivo que diz o que fazer.

    Sem `login.dat` o app não entra sozinho no ERP amanhã de manhã, então
    alarma; mas o recado não pode ser "o ERP recusou a senha", que mandaria
    procurar defeito no lugar errado."""
    monkeypatch.setattr(sonda.credenciais, "carregar", lambda: None)
    monkeypatch.delenv("MC_EMAIL", raising=False)
    monkeypatch.delenv("MC_SENHA", raising=False)
    monkeypatch.setattr(
        urllib.request, "urlopen",
        lambda *_a, **_k: pytest.fail("não devia ter chamado a rede"))

    r = sonda.sondar_erp()

    assert r.ok is False
    assert "login.dat" in r.motivo


def test_a_sonda_devolve_o_relogio_do_erp_como_estava(monkeypatch,
                                                      com_senha_do_erp):
    """Apertar o relógio é da sonda; o app depende dos números originais.

    Os 45 s e as 3 tentativas do `erp/api.py` são o certo para uma rodada de
    verdade. Se a sonda os deixasse trocados, ela teria mudado o produto —
    e num processo em que os dois rodam, a coleta perderia o 504 passageiro
    que aquelas tentativas existem para absorver."""
    antes = (api._TIMEOUT_S, api._TENTATIVAS_GET)
    falso, _ = _urlopen([403])
    monkeypatch.setattr(urllib.request, "urlopen", falso)

    sonda.sondar_erp()

    assert (api._TIMEOUT_S, api._TENTATIVAS_GET) == antes


# ------------------------------------------------------------------- nuvem

def test_nuvem_que_responde_vira_uma_linha_ok(monkeypatch, sessao_valida):
    _nuvem_responde(monkeypatch, _RespostaRequests(200, [{"id": 1}]))

    r = sonda.sondar_supabase()

    assert (r.sistema, r.ok, r.motivo) == ("supabase", True, "1 linha(s)")


def test_nuvem_muda_vira_falhou(monkeypatch, sessao_valida):
    _nuvem_responde(monkeypatch,
                    requests.RequestException("conexão recusada"))

    r = sonda.sondar_supabase()

    assert r.ok is False
    assert "falhou" in sonda.linha(r)


def test_sessao_vencida_registra_e_nao_falha(tmp_path, monkeypatch):
    """O caso que decide se este arquivo vira ruído.

    O token é NOSSO, vence sozinho e a sonda não tem — nem pode ter — a senha
    de ninguém para renová-lo. Contar isso como falha do Supabase encheria o
    ALERTA todo dia e ensinaria a ignorá-lo justamente no dia em que ele
    dissesse outra coisa. `tmp_path` sem `sessao.dat` é exatamente a máquina
    de quem ainda não entrou."""
    monkeypatch.setattr(
        rest._SESSAO, "request",
        lambda *_a, **_k: pytest.fail("não devia ter chamado a rede"))

    r = sonda.sondar_supabase(tmp_path)

    assert r.ok is True
    assert r.motivo == "sessão vencida"
    assert sonda.registrar([r], tmp_path) == []
    assert not (tmp_path / sonda.ARQUIVO_ALERTA).exists()


def test_banco_que_recusa_a_permissao_tambem_nao_alarma(monkeypatch,
                                                        sessao_valida):
    """403 é o servidor RESPONDENDO — que é o que a sonda foi perguntar.

    Quem julga permissão é a RLS, e o dia em que ela mudar aparece na tela do
    app. Aqui isso seria alarme sobre um sistema que está de pé."""
    _nuvem_responde(monkeypatch,
                    _RespostaRequests(403, {"message": "sem permissão"}))

    r = sonda.sondar_supabase()

    assert r.ok is True
    assert r.motivo.startswith("sessão recusada")


def test_a_sonda_devolve_o_relogio_da_nuvem_como_estava(monkeypatch,
                                                        sessao_valida):
    antes = rest.ESPERA
    _nuvem_responde(monkeypatch, requests.RequestException("off"))

    sonda.sondar_supabase()

    assert rest.ESPERA == antes


# ------------------------------------------------------- portais de banco

def test_portal_que_responde_ao_head_nao_baixa_a_pagina(monkeypatch):
    """HEAD é a pergunta inteira sem trazer página nenhuma."""
    falso, estado = _urlopen([b""])
    monkeypatch.setattr(urllib.request, "urlopen", falso)

    r = sonda.sondar_portal("inter", "https://exemplo.invalido/login")

    assert (r.sistema, r.ok) == ("inter", True)
    assert estado["metodos"] == ["HEAD"]
    assert r.motivo == "HTTP 200 em HEAD"


def test_portal_que_recusa_head_e_perguntado_por_get(monkeypatch):
    """405 no HEAD é comum e não é o banco caindo.

    Tratar isso como falha daria alarme falso todo dia — e alarme falso ensina
    a ignorar alarme."""
    falso, estado = _urlopen([405, b""])
    monkeypatch.setattr(urllib.request, "urlopen", falso)

    r = sonda.sondar_portal("sicoob", "https://exemplo.invalido/login")

    assert r.ok is True
    assert estado["metodos"] == ["HEAD", "GET"]
    assert r.motivo == "HTTP 200 em GET"


def test_portal_fora_do_ar_vira_falhou(monkeypatch):
    """O servidor FALOU, e o que disse não serve: 503 na própria página de
    login é notícia sobre o portal, e não sobre a rede daqui."""
    falso, estado = _urlopen([503, 503])
    monkeypatch.setattr(urllib.request, "urlopen", falso)

    r = sonda.sondar_portal("sicoob", "https://exemplo.invalido/login")

    assert r.ok is False
    assert estado["metodos"] == ["HEAD", "GET"]
    assert r.motivo == "HTTP 503 em GET"


def test_silencio_no_head_nao_paga_o_segundo_timeout(monkeypatch):
    """Depois de um silêncio, o GET ouviria o mesmo nada.

    O GET de reserva existe para 405/403 — servidor de pé recusando o método.
    Insistir depois de um timeout dobra a espera da sonda para não descobrir
    nada de novo."""
    falso, estado = _urlopen([TimeoutError("read timed out")])
    monkeypatch.setattr(urllib.request, "urlopen", falso)
    _tls_responde(monkeypatch)

    sonda.sondar_portal("sicoob", "https://exemplo.invalido/login")

    assert estado["metodos"] == ["HEAD"]


def test_portal_mudo_com_a_porta_aberta_nao_alarma(monkeypatch):
    """O caso do Sicoob, medido em 02/09/2026.

    Ele não responde a cliente HTTP que não seja navegador — nem a `urllib`
    nem a `requests`, com o jogo completo de cabeçalhos, esperando até 30 s —,
    e o TLS fecha em ~180 ms. Contar isso como falha seria um alarme por dia
    sobre um sistema de pé. A sonda diz menos, e diz verdade: a frase da linha
    é a própria medida do que ficou provado."""
    falso, _ = _urlopen([TimeoutError("read timed out")])
    monkeypatch.setattr(urllib.request, "urlopen", falso)
    _tls_responde(monkeypatch)

    r = sonda.sondar_portal("sicoob", "https://exemplo.invalido/login")

    assert r.ok is True
    assert r.motivo == sonda.PORTA_ABERTA


def test_portal_sem_dns_vira_falhou(monkeypatch):
    """Nem HTTP nem porta: aí é o portal, e alarma.

    É o que separa "o Sicoob não fala com Python" de "o Sicoob mudou de
    endereço" — sem essa segunda metade, a sonda daria `ok` para um host que
    deixou de existir."""
    falso, _ = _urlopen([urllib.error.URLError("getaddrinfo falhou")])
    monkeypatch.setattr(urllib.request, "urlopen", falso)
    _tls_responde(monkeypatch, erro=socket.gaierror("getaddrinfo falhou"))

    r = sonda.sondar_portal("inter", "https://exemplo.invalido/login")

    assert r.ok is False
    assert "falhou" in sonda.linha(r)


def test_as_urls_dos_portais_saem_de_quem_ja_as_usa():
    """URL de terceiro escrita duas vezes é uma divergência esperando.

    Se um dos dois módulos mudar de endereço, a sonda tem de mudar junto — e
    isso só é de graça enquanto ela importar a constante em vez de copiá-la."""
    assert dict(sonda.PORTAIS) == {
        "inter": sonda.inter_baixar.URL_LOGIN,
        "sicoob": sonda.sicoob_config.URL_LOGIN,
    }


# ------------------------------------------------------ o log e o ALERTA

_QUANDO = datetime(2026, 9, 2, 7, 0, 0)


def _ok(sistema="erp"):
    return sonda.Resultado(sistema, True, 120, "3 contas")


def _falha(sistema="sicoob", motivo="HTTP 503 em GET"):
    return sonda.Resultado(sistema, False, 10_042, motivo)


def test_a_linha_do_log_tem_data_sistema_estado_ms_e_motivo():
    assert sonda.linha(_falha(), _QUANDO) == (
        "02/09/2026 07:00:00  sicoob     falhou   10042 ms  HTTP 503 em GET")


def test_o_alerta_nasce_quando_algo_falha(tmp_path):
    falhas = sonda.registrar([_ok(), _falha()], tmp_path, _QUANDO)

    assert [f.sistema for f in falhas] == ["sicoob"]
    alerta = (tmp_path / sonda.ARQUIVO_ALERTA).read_text(encoding="utf-8")
    assert "sicoob" in alerta and "HTTP 503 em GET" in alerta
    # O que PASSOU não entra no alerta: ele é o resumo do que está errado.
    assert "erp" not in alerta

    linhas = (tmp_path / sonda.ARQUIVO_LOG).read_text(
        encoding="utf-8").splitlines()
    assert len(linhas) == 2
    assert linhas[0].endswith("3 contas") and "falhou" in linhas[1]


def test_o_alerta_some_quando_tudo_volta(tmp_path):
    """A metade que ninguém percebe estar quebrada.

    Um arquivo de alarme que sobra depois de resolvido parece zelo e é o
    contrário: na terceira vez, ninguém abre mais."""
    sonda.registrar([_ok(), _falha()], tmp_path, _QUANDO)
    assert (tmp_path / sonda.ARQUIVO_ALERTA).exists()

    falhas = sonda.registrar([_ok(), _ok("sicoob")], tmp_path, _QUANDO)

    assert falhas == []
    assert not (tmp_path / sonda.ARQUIVO_ALERTA).exists()
    # O log é histórico e só cresce: as quatro linhas continuam lá.
    assert len((tmp_path / sonda.ARQUIVO_LOG).read_text(
        encoding="utf-8").splitlines()) == 4


def test_rodada_boa_sem_alerta_anterior_nao_reclama(tmp_path):
    """Apagar o que não existe é o caso NORMAL — todo dia em que tudo passa."""
    assert sonda.registrar([_ok()], tmp_path, _QUANDO) == []
    assert not (tmp_path / sonda.ARQUIVO_ALERTA).exists()


def test_o_alerta_e_reescrito_e_nao_acumulado(tmp_path):
    """O ALERTA é ESTADO, não histórico: ele diz o que está errado AGORA.

    Somar o de anteontem ao de hoje é ruído com cara de gravidade — e quem
    quiser o histórico tem o `sonda.log`, que é append."""
    sonda.registrar([_falha("inter", "sem DNS")], tmp_path, _QUANDO)
    sonda.registrar([_falha("sicoob", "HTTP 503 em GET")], tmp_path, _QUANDO)

    alerta = (tmp_path / sonda.ARQUIVO_ALERTA).read_text(encoding="utf-8")
    assert "sicoob" in alerta
    assert "inter" not in alerta
