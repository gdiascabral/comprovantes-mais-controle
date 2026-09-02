# -*- coding: utf-8 -*-
"""Falar com o ERP de DENTRO da página logada, quando não dá para sair dela.

QUANDO ESTE TRANSPORTE É NECESSÁRIO
-----------------------------------
Menos vezes do que se pensava. A regra "o ERP bloqueia chamada HTTP feita de
fora do navegador (403)", repetida no `CLAUDE.md`, no `anexar/mc_api.py:6-10` e
no `aportes/mc_catalogos.py:17-19`, está desatualizada: o que o WAF recusa é o
`user-agent` de robô (medido em `conciliacao/erp/api.py:23-29`), e três
clientes já leem — e um deles ESCREVE — por HTTP puro. Ver
`docs/ERP-CLIENTES.md`, seção 2.

O que sobra e continua precisando do navegador de verdade:

  - o upload do comprovante, que é diálogo de tela (`anexar/mc_client.py`);
  - o PDF do extrato, gerado pela própria página (`relatorios/extrato_mc.py`);
  - o GraphQL das obras, cujo host `execute-api` só aparece nos cabeçalhos
    quando o ERP carrega o FORMULÁRIO de lançamento
    (`aportes/mc_catalogos.py:255-259`).

E há o motivo prático, que vale para quem já está com o Chrome na mão: o ERP
aceita UMA sessão por usuário, e um `POST /users/login` por HTTP derruba a
sessão do navegador (`conciliacao/erp/collect.py:98-108`). Quem já tem a página
logada fala por ela e não paga esse preço.

O JS ESTAVA ESCRITO DUAS VEZES
------------------------------
`_JS_FETCH_JSON` em `anexar/mc_api.py:55-59` e `_JS_FETCH` em
`aportes/mc_catalogos.py:42-46` são o MESMO bloco, com espaçamento diferente
dentro das chaves. Duas cópias de um transporte é uma divergência esperando
acontecer — a mesma razão que juntou as três capturas de cabeçalho em
`aportes/erp_sessao.py`. Aqui ele é um só, e `tests/test_erp.py` confere que
continua sendo.

O CONTRATO DE ERRO NÃO MUDA
---------------------------
Resposta com `r.ok` falso volta como `{"__erro": status}`, exatamente como
hoje. Quem migrar não precisa mexer em uma linha de tratamento de erro — e
`pagamentos_dia/baixa_erp.py:130-133`, que já lê `__erro`, funciona sem
adaptador nenhum.
"""
from __future__ import annotations

from . import hosts

__all__ = ["JS_FETCH_JSON", "JS_POST_JSON", "TransportePagina"]

#: GET de dentro da página logada: mesma origem, mesmos cookies, mesmo
#: user-agent da tela. O servidor não distingue do uso normal.
JS_FETCH_JSON = """async ({url, headers}) => {
  const r = await fetch(url, {headers});
  if (!r.ok) return {__erro: r.status};
  return await r.json();
}"""

#: POST. O `content-type` vem PRIMEIRO no `Object.assign` para que um
#: cabeçalho capturado da página possa sobrescrevê-lo, e não o contrário.
JS_POST_JSON = """async ({url, headers, corpo}) => {
  const r = await fetch(url, {
    method: 'POST',
    headers: Object.assign({'content-type': 'application/json'}, headers),
    body: JSON.stringify(corpo),
  });
  let dados = null;
  try { dados = await r.json(); } catch (e) { dados = null; }
  if (!r.ok) return {__erro: r.status, __corpo: dados};
  return dados;
}"""


class TransportePagina:
    """Chamadas ao ERP feitas pela página do Playwright já logada.

    `cabecalhos` aceita as duas formas que o app já produz:

        {"authorization": …}                  -> vale para tudo
        {"host": {"authorization": …}, …}     -> um conjunto por host

    A forma por host não é firula: cada serviço do ERP emite o SEU token, e
    reaproveitar o cabeçalho de um host noutro devolve 401 — foi assim que o
    token da telemetria acabou usado contra o `prod-erp-api`
    (`aportes/mc_catalogos.py:124-127`). É a mesma regra que
    `erp/sessao.py:token_para` aplica do lado do HTTP direto.
    """

    def __init__(self, pagina, cabecalhos: dict | None = None):
        self.pagina = pagina
        self.cabecalhos = cabecalhos or {}

    # ------------------------------------------------------------ cabeçalhos

    def _por_host(self) -> bool:
        """O mapa é {host: cabeçalhos} ou um conjunto plano?"""
        valores = list(self.cabecalhos.values())
        return bool(valores) and all(isinstance(v, dict) for v in valores)

    def cabecalhos_para(self, url: str) -> dict:
        """Os cabeçalhos do host desta URL.

        Sem captura para este host, vale qualquer conjunto que tenha token: a
        tela pode simplesmente ainda não ter chamado aquele serviço, e recusar
        aqui transformaria "espere a página carregar" em erro definitivo.
        """
        if not self._por_host():
            return dict(self.cabecalhos)
        host = hosts.host_de(url)
        if host in self.cabecalhos:
            return dict(self.cabecalhos[host])
        for conjunto in self.cabecalhos.values():
            if any(k.lower() == "authorization" for k in conjunto):
                return dict(conjunto)
        return {}

    def cabecalho(self, nome: str) -> str | None:
        """O valor de um cabeçalho, procurado em TODOS os hosts capturados.

        Nem todo serviço manda todos: o `prod-erp-api` não manda `user-id`, o
        `legacy-api` manda. Procurar em todos evita depender de qual tela a
        pessoa abriu antes (`aportes/mc_catalogos.py:168-181`).
        """
        nome = nome.lower()
        conjuntos = (list(self.cabecalhos.values()) if self._por_host()
                     else [self.cabecalhos])
        for conjunto in conjuntos:
            for chave, valor in conjunto.items():
                if chave.lower() == nome and valor:
                    return valor
        return None

    # ------------------------------------------------------------ transporte

    def buscar(self, url: str):
        """GET. Devolve o JSON, ou `{"__erro": status}` quando o ERP recusa."""
        return self.pagina.evaluate(
            JS_FETCH_JSON, {"url": url, "headers": self.cabecalhos_para(url)})

    def postar(self, url: str, corpo: dict):
        """POST. Devolve o JSON, ou `{"__erro": status, "__corpo": …}`."""
        return self.pagina.evaluate(
            JS_POST_JSON,
            {"url": url, "headers": self.cabecalhos_para(url), "corpo": corpo})

    #: `pagamentos_dia/baixa_erp.py:208-214` já depende de um transporte com
    #: `_buscar`/`postar` — foi escrito assim justamente para ser testável sem
    #: navegador. Manter o nome antigo faz o consumidor mais fácil de migrar
    #: não precisar de adaptador nenhum.
    _buscar = buscar
