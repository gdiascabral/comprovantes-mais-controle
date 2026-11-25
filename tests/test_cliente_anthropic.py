"""Cliente mínimo da API da Anthropic por `requests` (sem o pacote oficial no
exe). Sem rede: a sessão é um dublê. Chave fictícia."""
import json
from types import SimpleNamespace as NS

import pytest
import requests

from pagamentos_dia import leitura_ia as li
from pagamentos_dia.cliente_anthropic import ClienteAnthropic

CHAVE = "sk-ant-chave-ficticia-123"


class SessaoFalsa:
    def __init__(self, status=200, corpo=None, erro=None, texto=""):
        self.chamadas, self._status, self._erro = [], status, erro
        self._corpo, self._texto = corpo, texto

    def post(self, url, headers=None, data=None, timeout=None):
        self.chamadas.append({"url": url, "headers": headers, "data": data, "timeout": timeout})
        if self._erro:
            raise self._erro
        return NS(status_code=self._status, text=self._texto or json.dumps(self._corpo),
                  json=lambda: self._corpo)


def _ok():
    return {"content": [{"type": "thinking", "thinking": "..."},
                        {"type": "text", "text": "{\"a\": 1}"}],
            "usage": {"input_tokens": 1500, "output_tokens": 400},
            "stop_reason": "end_turn"}


def test_pedido_vai_com_cabecalhos_e_corpo_json():
    s = SessaoFalsa(corpo=_ok())
    cli = ClienteAnthropic(CHAVE, sessao=s, timeout=90)
    cli.beta.messages.create(model="m", max_tokens=10, betas=["b1", "b2"],
                             messages=[{"role": "user", "content": "oi"}], fallbacks="default")
    (c,) = s.chamadas
    assert c["url"] == "https://api.anthropic.com/v1/messages" and c["timeout"] == 90
    h = c["headers"]
    assert h["x-api-key"] == CHAVE and h["anthropic-version"] == "2023-06-01"
    assert h["anthropic-beta"] == "b1,b2" and h["content-type"] == "application/json"
    corpo = json.loads(c["data"])
    assert "betas" not in corpo
    assert corpo["model"] == "m" and corpo["fallbacks"] == "default" and corpo["max_tokens"] == 10


def test_resposta_vira_objeto_com_content_usage_e_stop_reason():
    r = ClienteAnthropic(CHAVE, sessao=SessaoFalsa(corpo=_ok())).beta.messages.create(model="m")
    assert [b.type for b in r.content] == ["thinking", "text"]
    assert r.content[1].text == "{\"a\": 1}"
    assert (r.usage.input_tokens, r.usage.output_tokens, r.stop_reason) == (1500, 400, "end_turn")


def test_sem_betas_nao_manda_o_cabecalho():
    s = SessaoFalsa(corpo=_ok())
    ClienteAnthropic(CHAVE, sessao=s).beta.messages.create(model="m")
    assert "anthropic-beta" not in s.chamadas[0]["headers"]


@pytest.mark.parametrize("sessao", [
    SessaoFalsa(erro=requests.Timeout("lento")),
    SessaoFalsa(erro=requests.ConnectionError("sem rede")),
    SessaoFalsa(status=429, corpo={"error": {"message": "limite"}}),
    SessaoFalsa(status=500, texto="<html>quebrou</html>"),
    SessaoFalsa(status=200, texto="isto não é json", corpo=None)])
def test_erro_vira_leitura_falhou(sessao):
    with pytest.raises(li.LeituraFalhou):
        ClienteAnthropic(CHAVE, sessao=sessao).beta.messages.create(model="m")


def test_a_chave_nunca_aparece_na_mensagem_de_erro():
    s = SessaoFalsa(status=401, texto=f"chave invalida {CHAVE}")
    with pytest.raises(li.LeituraFalhou) as e:
        ClienteAnthropic(CHAVE, sessao=s).beta.messages.create(model="m")
    assert CHAVE not in str(e.value) and "401" in str(e.value)


def test_sem_chave_nao_cria_cliente():
    with pytest.raises(ValueError):
        ClienteAnthropic("")


def test_funciona_com_pedir_leitura():
    leitura = {"tipo_papel": "recibo", "legivel": True, "total": "10,00",
               "total_por_extenso": "", "ordem_de_compra": "", "numero_documento": "",
               "data": "", "quadra": "", "lote": "", "itens": [], "cartao_valor": "",
               "cartao_nome": "", "duvidas": []}
    corpo = {"content": [{"type": "text", "text": json.dumps(leitura)}],
             "usage": {"input_tokens": 1, "output_tokens": 2}, "stop_reason": "end_turn"}
    lida, uso = li.pedir_leitura(ClienteAnthropic(CHAVE, sessao=SessaoFalsa(corpo=corpo)),
                                 b"\xff\xd8x", "image/jpeg")
    assert lida["total"] == "10,00" and uso.saida == 2


def test_prazo_padrao_e_45_segundos():
    s = SessaoFalsa(corpo=_ok())
    ClienteAnthropic(CHAVE, sessao=s).beta.messages.create(model="m")
    assert s.chamadas[0]["timeout"] == 45


@pytest.mark.parametrize("sessao", [
    SessaoFalsa(erro=requests.Timeout("lento")), SessaoFalsa(erro=requests.ConnectionError("x")),
    SessaoFalsa(status=429, corpo={"error": {"message": "limite"}}),
    SessaoFalsa(status=500, texto="quebrou")])
def test_falha_de_rede_prazo_ou_http_e_do_tipo_que_aciona_o_disjuntor(sessao):
    with pytest.raises(li.FalhaDeRede):
        ClienteAnthropic(CHAVE, sessao=sessao).beta.messages.create(model="m")


def test_corpo_que_nao_e_json_nao_aciona_o_disjuntor():
    with pytest.raises(li.LeituraFalhou) as e:
        ClienteAnthropic(CHAVE, sessao=SessaoFalsa(status=200, texto="não é json")
                         ).beta.messages.create(model="m")
    assert not isinstance(e.value, li.FalhaDeRede)
