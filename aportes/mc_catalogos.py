# -*- coding: utf-8 -*-
"""
Catálogos do Mais Controle: nome -> UUID.

Por que isso existe
-------------------
O lançamento de aporte era feito gerando duas planilhas e importando na mão.
A importação casa tudo por TEXTO: se o nome digitado não for idêntico ao
cadastro do ERP, a validação trava em "Validando Arquivo" — e você só descobre
depois de subir o arquivo, sem saber qual linha causou.

A tela de "Novo Lançamento" do próprio ERP não trabalha assim: ela manda
UUID em todo campo (participante, categoria, conta, obra, forma). Este módulo
carrega esses catálogos e resolve os nomes ANTES de qualquer envio, para o
erro aparecer na tela do app, com o nome do culpado, e não no meio do ERP.

Restrição herdada (ver anexar/mc_api.py): requisição feita de fora do
navegador leva 403. Tudo aqui sai de dentro da página logada, com os mesmos
cabeçalhos que a tela usa.

Este arquivo NÃO contém dado da empresa — o repositório é público. Nomes de
contas, sócios e investidores ficam em arquivos locais, fora do Git.
"""
from __future__ import annotations

import unicodedata
from urllib.parse import urlencode

ERP_API = "https://prod-erp-api.maiscontroleerp.com.br"
LEGACY = "https://legacy-api.maiscontroleerp.com.br/maiscontrole/services"

# Páginas a mais que isso é sinal de laço infinito, não de cadastro grande.
MAX_PAGINAS = 60

_JS_FETCH = """async ({url, headers}) => {
  const r = await fetch(url, {headers});
  if (!r.ok) return {__erro: r.status};
  return await r.json();
}"""

_JS_POST = """async ({url, headers, corpo}) => {
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

# As obras não têm endpoint REST: vêm por GraphQL, e o host varia conforme o
# ambiente. Em vez de fixar um, tentamos os que tiverem token capturado.
_GQL_OBRAS = """query ($first: PaginationAmount, $afterCursor: String) {
  works(first: $first, after: $afterCursor) {
    edges { node { id name status } }
    pageInfo { hasNextPage endCursor }
  }
}"""


def _sem_acento(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def chave(nome: str) -> str:
    """Forma comparável de um nome: sem acento, sem caixa, sem espaço dobrado.

    O cadastro do ERP e o arquivo de contas divergem em acentuação e
    espaçamento com frequência (por exemplo "SÃO" x "SAO", ou um espaço duplo
    no meio do nome). Comparar pela forma crua transformaria diferença
    cosmética em erro de cadastro."""
    return " ".join(_sem_acento(nome or "").upper().split())


class Catalogos:
    """Carrega e indexa os cadastros do ERP. Uma instância por sessão."""

    def __init__(self, pagina, headers: dict, log=print):
        """pagina  = página do Playwright já logada
        headers = cabeçalhos de autenticação capturados da própria tela.
                  Aceita duas formas:
                    {"authorization": ...}                    -> vale para tudo
                    {"host": {"authorization": ...}, ...}     -> um por host

        A forma por host não é firula: cada serviço do ERP emite o seu token.
        Reaproveitar o cabeçalho de um host em outro devolve 401 — foi assim
        que o token da telemetria (api-data-event.maiscontroleerp.com.br)
        acabou sendo usado contra o prod-erp-api."""
        self.pagina = pagina
        self.headers = headers
        self.log = log
        self.contas: dict[str, dict] = {}
        self.participantes: dict[str, dict] = {}
        self.categorias: dict[str, dict] = {}
        self.naturezas: dict[str, dict] = {}
        self.formas_pagamento: dict[str, dict] = {}
        self.formas_recebimento: dict[str, dict] = {}
        self.condicoes_pagamento: dict[str, dict] = {}
        self.condicoes_recebimento: dict[str, dict] = {}

    # ------------------------------------------------------------ transporte
    def _headers_para(self, url: str) -> dict:
        """Cabeçalhos do host da URL. Se o mapa for plano, usa ele para tudo."""
        valores = list(self.headers.values())
        if not valores or not all(isinstance(v, dict) for v in valores):
            return self.headers          # forma plana
        from urllib.parse import urlsplit
        host = urlsplit(url).netloc
        if host in self.headers:
            return self.headers[host]
        # Sem captura para este host: tenta qualquer um que tenha token. Serve
        # para o caso em que a tela ainda não chamou aquele serviço.
        for cabecalhos in valores:
            if any(k.lower() == "authorization" for k in cabecalhos):
                return cabecalhos
        return {}

    def _buscar(self, url: str):
        return self.pagina.evaluate(
            _JS_FETCH, {"url": url, "headers": self._headers_para(url)})

    def postar(self, url: str, corpo: dict):
        """POST de dentro da página logada. Devolve o JSON, ou
        {"__erro": status, "__corpo": ...} quando o ERP recusa."""
        return self.pagina.evaluate(
            _JS_POST,
            {"url": url, "headers": self._headers_para(url), "corpo": corpo})

    def _hosts_graphql(self) -> list[str]:
        """Hosts com token capturado que parecem servir GraphQL."""
        if not all(isinstance(v, dict) for v in self.headers.values()):
            return []
        return [h for h in self.headers if "execute-api" in h]

    def carregar_obras(self) -> None:
        """Obras (works). Não há REST: só GraphQL, e o host varia — por isso
        tentamos os candidatos até um responder."""
        self.obras = {}
        for host in self._hosts_graphql():
            url = f"https://{host}/prod/graphql"
            cursor, paginas = None, 0
            achou_algo = False
            while paginas < MAX_PAGINAS:
                resposta = self.postar(url, {
                    "query": _GQL_OBRAS,
                    "variables": {"first": 100, "afterCursor": cursor},
                })
                if not isinstance(resposta, dict) or resposta.get("__erro"):
                    break
                bloco = ((resposta.get("data") or {}).get("works") or {})
                arestas = bloco.get("edges") or []
                for aresta in arestas:
                    no = aresta.get("node") or {}
                    if no.get("id"):
                        self.obras[chave(no.get("name", ""))] = no
                        achou_algo = True
                info = bloco.get("pageInfo") or {}
                if not info.get("hasNextPage"):
                    break
                cursor = info.get("endCursor")
                paginas += 1
            if achou_algo:
                break
        self.log(f"  obras: {len(self.obras)}")

    def obra(self, nome: str) -> dict | None:
        return getattr(self, "obras", {}).get(chave(nome))

    @staticmethod
    def _lista(resposta) -> list:
        """A resposta ora é lista pura, ora vem embrulhada."""
        if isinstance(resposta, list):
            return resposta
        if isinstance(resposta, dict):
            for campo in ("content", "data", "items", "results"):
                if isinstance(resposta.get(campo), list):
                    return resposta[campo]
        return []

    def _buscar_tudo(self, base: str, params: dict) -> list:
        """Percorre TODAS as páginas.

        Ler só a primeira página já enganou uma vez: a lista de contas vem em
        ordem alfabética, ~10 por página, e a página 1 termina em "Cartão de
        Crédito" — as contas em M e T pareciam não existir. O ERP indica o fim
        por hasNextPage; totalPages às vezes vem null, então não dá para
        confiar nele."""
        itens: list = []
        pagina_n = 1
        while pagina_n <= MAX_PAGINAS:
            url = f"{base}?{urlencode({**params, 'pageIndex': pagina_n}, doseq=True)}"
            resposta = self._buscar(url)
            if isinstance(resposta, dict) and resposta.get("__erro"):
                raise RuntimeError(
                    f"o ERP respondeu {resposta['__erro']} em {base}. "
                    "Recarregue a tela do Mais Controle e tente de novo.")
            lote = self._lista(resposta)
            itens.extend(lote)
            tem_proxima = isinstance(resposta, dict) and resposta.get("hasNextPage")
            if not tem_proxima or not lote:
                break
            pagina_n += 1
        return itens

    @staticmethod
    def _indexar(itens: list) -> dict[str, dict]:
        return {chave(i.get("name", "")): i for i in itens if i.get("id")}

    # ------------------------------------------------------------- carga
    def carregar(self) -> None:
        """Puxa todos os cadastros. Barato: são poucas dezenas de registros."""
        # Contas: SEM o parâmetro owner. Com owner=ORGANIZATION_UNIT vêm só as
        # contas da unidade (4 a 7); sem ele vêm todas, e cada item diz se é
        # ORGANIZATION_UNIT ou CLIENT. Como nos aportes "Quem Paga" é sempre
        # Cliente, o que vale é a lista completa.
        self.contas = self._indexar(self._buscar_tudo(
            f"{ERP_API}/financial/bank-accounts",
            {"includeBlockedBankAccounts": "true", "isActive": "true"}))
        self.log(f"  contas: {len(self.contas)}")

        self.participantes = self._indexar(self._buscar_tudo(
            f"{ERP_API}/contacts/participants",
            {"statusesList": "ACTIVE",
             "rolesList": ["SUPPLIER", "CUSTOMER", "EMPLOYEE", "BOTH"]}))
        self.log(f"  participantes: {len(self.participantes)}")

        # Os demais não são paginados.
        simples = [
            ("categorias", f"{LEGACY}/categories/all"),
            ("formas_pagamento", f"{LEGACY}/payment-methods/all"),
            ("condicoes_pagamento", f"{LEGACY}/payment-conditions/all"),
            ("naturezas", f"{ERP_API}/natures"),
            ("formas_recebimento", f"{ERP_API}/receiving-methods/"),
            ("condicoes_recebimento", f"{ERP_API}/receiving-conditions"),
        ]
        for atributo, url in simples:
            resposta = self._buscar(url)
            if isinstance(resposta, dict) and resposta.get("__erro"):
                raise RuntimeError(f"o ERP respondeu {resposta['__erro']} em {url}")
            setattr(self, atributo, self._indexar(self._lista(resposta)))
            self.log(f"  {atributo}: {len(getattr(self, atributo))}")

    # ------------------------------------------------------------ consulta
    def conta(self, nome: str) -> dict | None:
        return self.contas.get(chave(nome))

    def participante(self, nome: str) -> dict | None:
        return self.participantes.get(chave(nome))

    def categoria(self, nome: str) -> dict | None:
        return self.categorias.get(chave(nome))

    def natureza(self, nome: str) -> dict | None:
        return self.naturezas.get(chave(nome))

    def forma_pagamento(self, nome: str) -> dict | None:
        return self.formas_pagamento.get(chave(nome))

    def forma_recebimento(self, nome: str) -> dict | None:
        return self.formas_recebimento.get(chave(nome))

    def condicao_a_vista_pagamento(self) -> dict | None:
        """A condição "À Vista" — identificada pelo type, não pelo nome, que
        pode variar de instalação para instalação."""
        for item in self.condicoes_pagamento.values():
            if item.get("type") == "IN_CASH" or item.get("inCash"):
                return item
        return None

    def condicao_a_vista_recebimento(self) -> dict | None:
        return self.condicoes_recebimento.get(chave("À Vista"))

    # ------------------------------------------------------- diagnóstico
    def parecidos(self, nome: str, onde: str = "contas", quantos: int = 3) -> list[str]:
        """Nomes parecidos, para a mensagem de erro ajudar em vez de só acusar.

        Um nome que não bate quase sempre é acento, abreviação ou espaço a
        mais — mostrar os candidatos economiza a ida ao ERP para conferir."""
        import difflib
        universo = {c: v.get("name", "") for c, v in getattr(self, onde, {}).items()}
        achados = difflib.get_close_matches(chave(nome), list(universo), quantos, 0.6)
        return [universo[a] for a in achados]

    def conferir(self, entidades: dict) -> dict:
        """Confere um cadastro de contas (o contas.csv) contra o ERP.

        Devolve {"ok": [...], "faltando": [{nome, o_que, procurado, parecidos}]}
        SEM enviar nada. É a checagem que antes só acontecia dentro do ERP,
        depois do upload da planilha, e sem dizer qual linha estava errada."""
        ok, faltando = [], []
        for exibicao, dados in entidades.items():
            problemas = []
            oficial = (dados.get("nome_oficial") or "").strip()
            if oficial and not self.participante(oficial):
                problemas.append({
                    "o_que": "participante (Cliente/Favorecido)",
                    "procurado": oficial,
                    "parecidos": self.parecidos(oficial, "participantes"),
                })
            conta = (dados.get("conta") or "").strip()
            if conta and not self.conta(conta):
                problemas.append({
                    "o_que": "conta bancária",
                    "procurado": conta,
                    "parecidos": self.parecidos(conta, "contas"),
                })
            if problemas:
                faltando.append({"nome": exibicao, "problemas": problemas})
            else:
                ok.append(exibicao)
        return {"ok": ok, "faltando": faltando}
