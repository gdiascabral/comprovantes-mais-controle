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

from urllib.parse import urlencode

import util

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
#
# O argumento `specification` NÃO é opcional na prática: sem ele o servidor
# responde "Object reference not set to an instance of an object" — ele
# desreferencia o objeto sem checar nulo. A assinatura e o conteúdo abaixo
# foram copiados da chamada que a própria tela faz.
_GQL_OBRAS = """query ($first: PaginationAmount, $afterCursor: String,
                       $specification: WorkSpecificationInput) {
  works(first: $first, after: $afterCursor, specification: $specification) {
    edges { node { id name status } }
    pageInfo { hasNextPage endCursor }
  }
}"""

# Consultas trazidas do ANEXAR BOLETOS junto dos metodos de
# tarefa/planejamento (ver o cabecalho da classe).

# O GraphQL do ERP muda os subcampos de `defaultAccount` conforme a versao, e
# pedir um campo que nao existe derruba a consulta inteira. Em vez de fixar um
# formato, tentamos do mais completo para o mais simples.
SUBCAMPOS_DE_CONTA = (
    "{ id name openingBalanceDate }",
    "{ id name }",
    "{ id }",
)
_GQL_TIPO = """query ($nome: String!) {
  __type(name: $nome) { fields { name type { name kind ofType { name kind } } } }
}"""

_GQL_PLANEJAMENTO = """query ($workId: Uuid) {
  planningByWork(workId: $workId) { id __typename }
}"""

_GQL_TAREFAS = """query ($planningId: Uuid!) {
  allTasks(planningId: $planningId) {
    id index name itemName fullname description discriminator __typename
  }
}"""

_GQL_TAREFAS_SIMPLES = """query ($planningId: Uuid!) {
  allTasks(planningId: $planningId) {
    id index name itemName fullname discriminator __typename
  }
}"""


#: Forma comparável de um nome de cadastro. O ERP e o contas.csv divergem em
#: acentuação e espaçamento com frequência ("SÃO" x "SAO", espaço duplo no
#: meio): comparar pela forma crua transformaria diferença cosmética em erro
#: de cadastro. É a MESMA função usada pelos mapas de pasta (util.norm_espaco).
chave = util.norm_espaco


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

    def cabecalho(self, nome: str) -> str | None:
        """Valor de um cabeçalho, procurado em todos os hosts capturados.

        Nem todo serviço manda todos: o prod-erp-api não manda user-id, o
        legacy-api manda. Procurar em todos evita depender de qual tela o
        usuário abriu antes."""
        nome = nome.lower()
        conjuntos = ([self.headers] if not all(isinstance(v, dict)
                     for v in self.headers.values()) else list(self.headers.values()))
        for cabecalhos in conjuntos:
            for chave_h, valor in cabecalhos.items():
                if chave_h.lower() == nome and valor:
                    return valor
        return None

    def _hosts_graphql(self) -> list[str]:
        """Hosts com token capturado que parecem servir GraphQL."""
        if not all(isinstance(v, dict) for v in self.headers.values()):
            return []
        return [h for h in self.headers if "execute-api" in h]

    def carregar_obras(self) -> None:
        """Obras (works). Não há REST: só GraphQL, e o host varia — por isso
        tentamos os candidatos até um responder."""
        self.obras = {}
        self.erros_obras: list[str] = []
        candidatos = self._hosts_graphql()
        if not candidatos:
            self.erros_obras.append(
                "nenhum host GraphQL entre os cabeçalhos capturados — o "
                "filtro de captura precisa aceitar os hosts execute-api")

        # Mesmo filtro que a tela usa ao abrir o campo Obra do lançamento.
        especificacao = {
            "organizationUnitId": self.cabecalho("organization-unit-id"),
            "userAccountId": self.cabecalho("user-id"),
            "statusExcluded": ["QUOTING"],
            "enabledForPayment": True,
        }
        if not especificacao["organizationUnitId"] or not especificacao["userAccountId"]:
            self.erros_obras.append(
                "faltou organization-unit-id ou user-id nos cabeçalhos "
                "capturados; sem eles a consulta de obras não é aceita")

        for host in candidatos:
            url = f"https://{host}/prod/graphql"
            cursor, paginas = None, 0
            achou_algo = False
            while paginas < MAX_PAGINAS:
                resposta = self.postar(url, {
                    "query": _GQL_OBRAS,
                    "variables": {"first": 100, "afterCursor": cursor,
                                  "specification": especificacao},
                })
                # Guardar o motivo: sem isso, "obras: 0" não diz se foi host
                # errado, token errado ou consulta malformada.
                if not isinstance(resposta, dict):
                    self.erros_obras.append(f"{host}: resposta inesperada")
                    break
                if resposta.get("__erro"):
                    self.erros_obras.append(
                        f"{host}: HTTP {resposta['__erro']} "
                        f"{str(resposta.get('__corpo'))[:200]}")
                    break
                if resposta.get("errors"):
                    self.erros_obras.append(
                        f"{host}: GraphQL {str(resposta['errors'])[:300]}")
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

    def definir_obras(self, itens) -> None:
        """Obras vindas do REST (`mc_api.listar_obras`), e não do GraphQL.

        É a MESMA fonte que a aba Contratos usa em produção. O caminho antigo
        (`carregar_obras`, GraphQL) depende de um host `execute-api`, que só
        aparece nos cabeçalhos quando o ERP carrega o FORMULÁRIO de lançamento
        — e esta aba passa pela tela de Pagamentos, que nunca o chama. Dava
        `obras: 0`, e aí todo lançamento morria com "Obra não encontrado", que
        parece cadastro faltando no ERP e não é.

        Guarda o item inteiro, indexado pelo nome normalizado: quem lança
        precisa de `id`, `name` e `status`.
        """
        self.obras = {}
        self.erros_obras = []
        for o in itens or []:
            if isinstance(o, dict) and o.get("id") and o.get("name"):
                self.obras[chave(o["name"])] = o
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
        confiar nele.

        Pede páginas grandes: com o padrão de 10 por página, os ~440
        participantes viravam mais de 40 idas ao servidor, uma de cada vez, e
        a espera aparecia na tela. Se o ERP recusar o parâmetro, refazemos sem
        ele — vale tentar porque o ganho é grande e o custo de errar é uma
        requisição."""
        for tamanho in (100, None):
            base_params = dict(params)
            if tamanho:
                base_params["pageSize"] = tamanho
            itens: list = []
            pagina_n = 1
            recusou = False
            while pagina_n <= MAX_PAGINAS:
                url = (f"{base}?"
                       f"{urlencode({**base_params, 'pageIndex': pagina_n}, doseq=True)}")
                resposta = self._buscar(url)
                if isinstance(resposta, dict) and resposta.get("__erro"):
                    if tamanho:            # pode ter sido o pageSize
                        recusou = True
                        break
                    raise RuntimeError(
                        f"o ERP respondeu {resposta['__erro']} em {base}. "
                        "Recarregue a tela do Mais Controle e tente de novo.")
                lote = self._lista(resposta)
                itens.extend(lote)
                tem_proxima = isinstance(resposta, dict) and resposta.get("hasNextPage")
                if not tem_proxima or not lote:
                    break
                pagina_n += 1
            if not recusou:
                return itens
        return []

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

    # ------------------------------------------------------------
    # Tarefas e planejamento da obra. Vieram do `ANEXAR BOLETOS`, que
    # mantinha uma copia INTEIRA deste arquivo so para te-los: os
    # boletos do INSS precisam da tarefa da obra, e nao so da obra.
    # Uma copia de arquivo inteiro para ganhar 11 metodos e como as
    # duas versoes divergem — a copia ja tinha perdido o aviso de
    # seguranca do cabecalho.

    def _gql(self, host: str, query: str, variaveis: dict):
        return self.postar(f"https://{host}/prod/graphql",
                           {"query": query, "variables": variaveis})

    def _dados(resposta) -> dict | None:
        """`data` de uma resposta GraphQL, ou None se veio erro."""
        if not isinstance(resposta, dict):
            return None
        if resposta.get("__erro") or resposta.get("errors"):
            return None
        return resposta.get("data") or None

    def campos_do_tipo(self, host: str, nome: str) -> set[str]:
        """Nomes de campo de um tipo GraphQL, via introspecção.

        Existe para não precisar adivinhar: pedir um campo inexistente não
        devolve o resto sem ele — invalida a consulta inteira."""
        dados = self._dados(self._gql(host, _GQL_TIPO, {"nome": nome}))
        tipo = (dados or {}).get("__type") or {}
        return {c.get("name") for c in (tipo.get("fields") or []) if c.get("name")}

    def _selecoes_de_obra(self, host: str) -> list[str]:
        """Seleções de campo a tentar, da mais rica para a mais pobre.

        A última é sempre só o básico: obra sem conta ainda serve para lançar
        (o CSV pode trazer a conta na mão), mas nenhuma obra não serve para
        nada."""
        basico = "id name status"
        disponiveis = self.campos_do_tipo(host, "Work")
        tentativas = []
        if not disponiveis or "defaultAccount" in disponiveis:
            tentativas += [f"{basico} defaultAccount {s}" for s in SUBCAMPOS_DE_CONTA]
        tentativas.append(basico)
        return tentativas

    def tarefas_da_obra(self, id_obra: str) -> list[dict]:
        """Itens do orçamento da obra. Duas consultas: a obra tem um
        planejamento, e o planejamento tem as tarefas."""
        if id_obra in self._cache_tarefas:
            return self._cache_tarefas[id_obra]
        tarefas: list[dict] = []
        self.erros_tarefas.pop(id_obra, None)
        host = self._host_graphql
        if not host:
            self.erros_tarefas[id_obra] = "sem host GraphQL"
            self._cache_tarefas[id_obra] = tarefas
            return tarefas

        resposta = self._gql(host, _GQL_PLANEJAMENTO, {"workId": id_obra})
        plano = (self._dados(resposta) or {}).get("planningByWork") or {}
        if not plano.get("id"):
            self.erros_tarefas[id_obra] = (
                f"a obra não tem orçamento: {self._motivo(resposta)}")
            self._cache_tarefas[id_obra] = tarefas
            return tarefas

        for query in (_GQL_TAREFAS, _GQL_TAREFAS_SIMPLES):
            resposta = self._gql(host, query, {"planningId": plano["id"]})
            tarefas = (self._dados(resposta) or {}).get("allTasks") or []
            if tarefas:
                break
            self.erros_tarefas[id_obra] = self._motivo(resposta)
        self._cache_tarefas[id_obra] = tarefas
        return tarefas

    def _motivo(resposta) -> str:
        """O porquê de uma resposta GraphQL não ter servido, em uma linha."""
        if not isinstance(resposta, dict):
            return "resposta inesperada"
        if resposta.get("__erro"):
            return f"HTTP {resposta['__erro']}"
        if resposta.get("errors"):
            return str(resposta["errors"])[:160]
        return "veio vazio"

    def nome_da_tarefa(t: dict) -> str:
        """O texto que a tela mostra para um item do orçamento.

        `description` vem primeiro porque é ele que carrega "INSS (pessoa
        física)" nos itens; `name` e `itemName` ficam como reserva, que é
        onde as ETAPAS guardam o texto delas ("Documentação final")."""
        return (t.get("description") or t.get("name")
                or t.get("itemName") or "")

    def task_da_obra(self, id_obra: str, termo: str) -> dict | None:
        """Item do orçamento cujo nome contém `termo` (ex.: "INSS").

        Devolve o item no formato que o lançamento espera. Havendo mais de um
        candidato, prefere o de menor índice — os itens do orçamento são
        numerados em ordem, e o primeiro é o principal."""
        alvo = chave(termo)
        achados = [t for t in self.tarefas_da_obra(id_obra)
                   if (t.get("discriminator") or "ITEM") == "ITEM"
                   and alvo in chave(self.nome_da_tarefa(t))]
        if not achados:
            return None
        achados.sort(key=self._ordem_do_indice)
        t = achados[0]
        nome = self.nome_da_tarefa(t)
        base = t.get("fullname") or f"Item {t.get('index')}"
        return {"id": t["id"], "index": t.get("index"),
                "fullname": f"{base} - {nome}" if nome else base,
                "name": nome,
                "discriminator": t.get("discriminator") or "ITEM"}

    def _ordem_do_indice(t: dict) -> tuple:
        """"20.1" antes de "20.10", e ambos antes de "3" — comparar como texto
        põe "10" na frente de "3" e escolheria o item errado."""
        partes = str(t.get("index") or "").split(".")
        return tuple(int(p) if p.isdigit() else 0 for p in partes)

    def tarefas_parecidas(self, id_obra: str, termo: str, quantos: int = 5) -> list[str]:
        """Itens do orçamento parecidos, para quando o termo não achar nada."""
        import difflib
        universo = {self.nome_da_tarefa(t): t for t in self.tarefas_da_obra(id_obra)
                    if self.nome_da_tarefa(t)}
        achados = difflib.get_close_matches(termo, list(universo), quantos, 0.4)
        return achados or sorted(universo)[:quantos]

    def conta_por_id(self, id_conta: str) -> dict | None:
        """A conta que a obra indicou vem como UUID; aqui vira o registro."""
        if not id_conta:
            return None
        return next((c for c in self.contas.values() if c.get("id") == id_conta), None)
