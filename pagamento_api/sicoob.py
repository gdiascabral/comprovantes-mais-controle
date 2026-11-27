# -*- coding: utf-8 -*-
"""Cliente das APIs de pagamento do Sicoob (Pix, boleto, convênio).

Só fala HTTP: não decide nada. Quem decide se paga é `executor.py`. A sessão
`requests` é injetada (o teste passa uma falsa); certificado e token vêm da
configuração do servidor e nunca passam por log. Endereços lidos do portal
developers.sicoob.com.br em 26/11/2026; no Sandbox o boleto mora em
`cobranca-bancaria-pagamentos/v3`, na produção em `pagamentos/v3`.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable


@dataclass(frozen=True)
class Ambiente:
    pix: str
    boleto: str
    convenio: str


SANDBOX = Ambiente(
    pix="https://sandbox.sicoob.com.br/sicoob/sandbox/pix-pagamentos/v2",
    boleto="https://sandbox.sicoob.com.br/sicoob/sandbox/cobranca-bancaria-pagamentos/v3",
    convenio="https://sandbox.sicoob.com.br/sicoob/sandbox/convenios-pagamentos/v2",
)
PRODUCAO = Ambiente(
    pix="https://api.sicoob.com.br/pix-pagamentos/v2",
    boleto="https://api.sicoob.com.br/pagamentos/v3",
    convenio="https://api.sicoob.com.br/convenios-pagamentos/v2",
)


#: Identificação fixa e honesta do cliente. O firewall do Sicoob recusa o
#: "python-requests" padrão com HTTP 200 e uma página HTML (medido no Sandbox
#: em 26/11/2026): por isso a identificação própria E a recusa de resposta
#: que não é JSON, abaixo. Não se troca este valor para "passar" no firewall.
USER_AGENT = "comprovantes-mais-controle/pagamento-api 1.0"


class ErroSicoob(RuntimeError):
    """O banco respondeu fora de 2xx, ou com um 2xx que não serve. `status` None =
    não houve resposta. Num POST que PAGA, qualquer ErroSicoob (sem resposta,
    5xx, ou 2xx sem o campo esperado) é ambíguo — o dinheiro pode ter saído — e
    quem decide é a retomada do executor, que pergunta ao banco."""

    def __init__(self, status, corpo: str):
        super().__init__(f"Sicoob {status}: {corpo[:300]}")
        self.status = status
        self.corpo = corpo


@dataclass(frozen=True)
class ContaApi:
    """A conta pagadora como o Sicoob a conhece (vem do arquivo do servidor)."""
    cooperativa: int
    numero: int
    tipo_pessoa: int     # o `personType` do Sicoob para esta conta (arquivo do servidor)


def _reais(valor: Decimal) -> float:
    """O JSON do Sicoob quer número; a conversão para float só existe aqui."""
    return float(Decimal(valor).quantize(Decimal("0.01")))


class Sicoob:
    def __init__(self, sessao, ambiente: Ambiente, client_id: str,
                 token: Callable[[], str], cert=None, timeout: float = 30.0,
                 relogio: Callable[[], float] = time.monotonic,
                 esperar: Callable[[float], None] = time.sleep):
        self._s = sessao
        self._a = ambiente
        self._cid = client_id
        self._token = token
        self._cert = cert
        self._timeout = timeout
        self._relogio, self._esperar = relogio, esperar
        self._ultimo_pix = None

    def _vez_do_pix(self) -> None:
        """A API de Pix aceita 1 requisição por segundo (documentação do Sicoob)."""
        if self._ultimo_pix is not None:
            falta = 1.0 - (self._relogio() - self._ultimo_pix)
            if falta > 0:
                self._esperar(falta)
        self._ultimo_pix = self._relogio()

    def _chamar(self, metodo: str, url: str, *, corpo=None, params=None, extra=None) -> dict:
        h = {"User-Agent": USER_AGENT,
             "Authorization": "Bearer " + self._token(), "client_id": self._cid,
             "Accept": "application/json", "Content-Type": "application/json"}
        h.update(extra or {})
        try:
            r = self._s.request(metodo, url, headers=h, params=params,
                                data=json.dumps(corpo) if corpo is not None else None,
                                cert=self._cert, timeout=self._timeout)
        except Exception as e:  # rede caiu: o executor trata como "não sei se saiu"
            raise ErroSicoob(None, repr(e)) from e
        texto = r.text or ""
        if not 200 <= r.status_code < 300:
            raise ErroSicoob(r.status_code, texto)
        if not texto.strip():
            return {}
        try:
            # Valores do banco já chegam em Decimal: dinheiro não passa por float.
            corpo = json.loads(texto, parse_float=Decimal)
        except ValueError:
            # 200 com HTML = recusa do firewall, não sucesso. Nunca vale como "pago".
            raise ErroSicoob(r.status_code, "resposta não é JSON: " + texto[:200]) from None
        if not isinstance(corpo, dict):
            raise ErroSicoob(r.status_code, "resposta não é um objeto JSON")
        return corpo

    # ------------------------------------------------------------------ Pix
    def pix_iniciar(self, chave: str) -> dict:
        self._vez_do_pix()
        return self._chamar("POST", self._a.pix + "/pagamentos", corpo={"chave": chave})

    def pix_confirmar(self, e2e: str, valor: Decimal, descricao: str) -> dict:
        corpo = {"endToEndId": e2e, "valor": f"{Decimal(valor):.2f}".replace(".", ","),
                 "descricao": descricao, "repeticao": False, "meioIniciacao": "MANUAL"}
        self._vez_do_pix()
        return _com(self._chamar("POST", self._a.pix + "/pagamentos/confirmacao", corpo=corpo),
                    "estado", "confirmação do Pix sem estado")

    def pix_qrcode(self, copia_e_cola: str, valor: Decimal, documento: str) -> dict:
        corpo = {"qrcode": copia_e_cola, "valor": f"{Decimal(valor):.2f}",
                 "pagarComJurosMulta": False, "destino": {"cpfCnpj": documento}}
        self._vez_do_pix()
        return _com(self._chamar("POST", self._a.pix + "/pagamentos/qrcode", corpo=corpo),
                    "estado", "Pix por QR sem estado")

    def pix_consultar(self, e2e: str) -> dict:
        self._vez_do_pix()
        return self._chamar("GET", self._a.pix + f"/pagamentos/{e2e}")

    # --------------------------------------------------------------- boleto
    def boleto_consultar(self, codigo: str, conta: ContaApi) -> dict:
        r = self._chamar("GET", self._a.boleto + f"/boletos/{codigo}",
                         params={"numeroConta": conta.numero})
        return r.get("resultado", r)

    def boleto_pagar(self, codigo: str, conta: ContaApi, consulta: dict, valor: Decimal,
                     descricao: str, chave: str, dia: str) -> dict:
        corpo = {"identificadorConsulta": consulta.get("identificadorConsulta", ""),
                 "valorBoleto": _reais(valor), "amount": _reais(valor),
                 "valorDescontoAbatimento": 0, "valorMultaMora": 0,
                 "aceitaValorDivergente": False, "descricaoObservacao": descricao,
                 "date": dia,
                 "debtorAccount": {"issuer": conta.cooperativa, "number": conta.numero,
                                   "accountType": 0, "personType": conta.tipo_pessoa}}
        r = self._chamar("POST", self._a.boleto + f"/boletos/pagamentos/{codigo}",
                         corpo=corpo, extra={"x-idempotency-key": chave})
        r = r.get("resultado", r)
        if not r:
            raise ErroSicoob(200, "pagamento de boleto sem resposta")
        return r

    def boleto_comprovante(self, chave: str) -> dict:
        r = self._chamar("GET", self._a.boleto
                         + f"/boletos/pagamentos/{chave}/idempotency/comprovantes")
        return r.get("resultado", r)

    # ------------------------------------------------------------- convênio
    def convenio_consultar(self, codigo: str, dia: str) -> dict:
        r = self._chamar("GET", self._a.convenio + f"/arrecadacao/codigo-barras/{codigo}",
                         params={"dataPagamento": dia})
        return r.get("resultado", r)

    def convenio_pagar(self, codigo: str, conta: ContaApi, valor: Decimal, dia: str,
                       transacao: int) -> dict:
        corpo = {"identificacao": {"instituicao": conta.cooperativa, "unidade": 0},
                 "pagamento": {"valorPago": _reais(valor), "valorDocumento": _reais(valor),
                               "dataPagamento": dia},
                 "transacao": transacao}
        r = self._chamar("POST", self._a.convenio
                         + f"/arrecadacao/codigo-barras/{codigo}/pagamentos", corpo=corpo)
        r = r.get("resultado", r)
        if not (r.get("arrecadacao") or r.get("comprovante")):
            raise ErroSicoob(200, "pagamento de convênio sem comprovante")
        return r


def _com(resposta: dict, campo: str, motivo: str) -> dict:
    """2xx sem o campo que diz o que aconteceu não é sucesso: vira ErroSicoob."""
    if campo not in resposta:
        raise ErroSicoob(200, motivo)
    return resposta


def chave_de_idempotencia(conta: ContaApi, uuid_: str) -> str:
    """O formato que o Sicoob pede: cooperativa (até 4), conta (até 14), UUID."""
    return f"{conta.cooperativa}-{conta.numero}-{uuid_}"
