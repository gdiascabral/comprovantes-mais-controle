# -*- coding: utf-8 -*-
"""
Leitura dos pagamentos e dos anexos pela MESMA API que a tela de Pagamentos usa.

Como funciona: com o Chrome aberto e logado (Playwright), o app observa as
requisições que a própria página faz e reaproveita os cabeçalhos de
autenticação (o token fica só na memória, nada é salvo em disco). As chamadas
são então feitas DE DENTRO da própria página (fetch), com os mesmos cookies,
User-Agent e origem da tela do sistema — o servidor não distingue do uso
normal. Com isso:

  - lista os títulos PAGOS do período (type=PAID, dateField=DATE_OF_PAYMENT),
    sem filtro de conta — a seleção de contas é feita no app, por checkbox;
  - verifica, pago a pago, se há arquivo anexado no nível do sub-pagamento
    (endpoint de attachments com entityOrigin=PAID);
  - SOBE o comprovante para o sub-pagamento (`anexar_por_api`): POST batch →
    PUT no S3 pré-assinado → GET de prova, sem o diálogo da tela.
"""
import base64
import datetime
import re
from pathlib import Path
from urllib.parse import urlsplit, parse_qsl, urlencode

from . import config
from erp.pagina import JS_POST_JSON

import util


_diag = config.diag              # o registro de diagnóstico agora mora no config
_log = util.log(__name__)        # o traceback do que não deu, no diagnostico.log


def _so_digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def _host_path_diag(url) -> str:
    """host+caminho de uma URL, sem a query — URLs de anexo vêm assinadas e a
    query carrega credencial temporária, que não pode ir para o log."""
    try:
        s = urlsplit(url or "")
        return f"{s.scheme}://{s.netloc}{s.path}" or "(sem url)"
    except Exception:
        return "(url ilegível)"

# cabeçalhos que interessam (o resto o navegador completa sozinho)
_H_PAGOS = {"accept", "authorization", "organization-unit-id", "user-id", "company-id"}
_H_ANEXO = {"accept", "authorization", "company-id"}

_JS_FETCH_JSON = """async ({ url, headers }) => {
  const r = await fetch(url, { headers });
  if (!r.ok) return { __erro: r.status };
  return await r.json();
}"""

_JS_FETCH_B64 = """async ({ url, headers }) => {
  const r = await fetch(url, { headers });
  if (!r.ok) return { __erro: r.status };
  const b = await r.arrayBuffer();
  let s = '';
  const u = new Uint8Array(b);
  for (let i = 0; i < u.length; i += 32768)
    s += String.fromCharCode.apply(null, u.subarray(i, i + 32768));
  return { b64: btoa(s) };
}"""

_JS_FETCH_LOTE = """async ({ urls, headers }) => {
  const out = {};
  await Promise.all(urls.map(async ({ chave, url }) => {
    try {
      const r = await fetch(url, { headers });
      out[chave] = r.ok ? await r.json() : { __erro: r.status };
    } catch (e) { out[chave] = { __erro: String(e) }; }
  }));
  return out;
}"""

_JS_FETCH_ANEXOS = """async ({ base, ids, headers }) => {
  const out = {};
  await Promise.all(ids.map(async (pid) => {
    try {
      const r = await fetch(base + '?entityIds=' + encodeURIComponent(pid) +
                            '&entityOrigin=PAID', { headers });
      if (!r.ok) { out[pid] = -1; return; }
      const j = await r.json();
      out[pid] = Array.isArray(j) ? j.length : 0;
    } catch (e) { out[pid] = -1; }
  }));
  return out;
}"""


#: PUT cru do binário na URL pré-assinada do S3. SÓ `Content-Type`: qualquer
#: cabeçalho do ERP (authorization, company-id) quebra a assinatura da URL. O
#: binário chega em base64 porque `page.evaluate` só transporta JSON. Mesmo
#: padrão que subiu 29 anexos em produção em 28/08/2026
#: (`agua_energia/coletor/lancar_mc.py`, `_JS_PUT_S3`).
_JS_PUT_S3 = """async ({ url, b64, contentType }) => {
  const bin = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
  const r = await fetch(url, { method: 'PUT',
    headers: { 'Content-Type': contentType }, body: bin });
  return { status: r.status, body: (await r.text()).slice(0, 500) };
}"""


#: Os três desfechos possíveis da consulta de anexos de UM pagamento.
COM_ANEXO = "com anexo"
SEM_ANEXO = "sem anexo"
NAO_VERIFICADO = "não verificado"

#: Os desfechos de `MCApi.anexar_por_api`. Os dois primeiros são sucesso; os
#: `erro:` se dividem pelo que JÁ FOI MANDADO ao ERP quando a falha aconteceu —
#: é isso que decide se a tela pode tentar (`tela_pode_tentar`).
ANEXADO = "anexado"
JA_ANEXADO = "ja_anexado"
ERRO_SEM_CREDENCIAL = "erro:sem_credencial"
ERRO_NAO_CONFIRMADO = "erro:nao_confirmado"
_PREFIXO_BATCH = "erro:batch:"
_PREFIXO_UPLOAD = "erro:upload:"

#: `contentType` do item do batch, pela extensão. O matcher só entrega PDF; o
#: resto está aqui para o modo "Por lista" não mandar um PNG como PDF.
_TIPOS_DE_ARQUIVO = {"pdf": "application/pdf", "png": "image/png",
                     "jpg": "image/jpeg", "jpeg": "image/jpeg"}


def tela_pode_tentar(estado: str) -> bool:
    """A tela (⋮ → Editar pagamento) pode tentar depois deste desfecho da API?

    Só quando NADA subiu para o ERP: sem credencial capturada, ou o ERP
    respondeu antes de o arquivo sair (a listagem prévia, a lista de etiquetas
    ou o próprio POST do batch recusados com 4xx/5xx). Nos outros erros o
    arquivo pode já estar lá — o PUT saiu e o GET de prova não o listou, ou o
    batch criou o registro e o PUT falhou — e a tela anexaria uma segunda vez.
    Comprovante em dobro se desfaz à mão, no ERP, um a um; comprovante
    relatado como erro se confere abrindo o lançamento. O segundo é barato.
    """
    return estado == ERRO_SEM_CREDENCIAL or estado.startswith(_PREFIXO_BATCH)


def _primeira_url_s3(objeto) -> str | None:
    """A URL pré-assinada na resposta do batch — o nome do campo varia, então
    procura a primeira string http com cara de S3, em ordem de leitura."""
    for u in _coletar_urls(objeto):
        ul = u.lower()
        if "s3" in ul or "amazonaws" in ul:
            return u
    return None


def _nomes_do_item(item: dict) -> set[str]:
    """As formas do nome de um anexo listado, em minúsculas.

    O campo pode ser `name` ou `filename`, e `extension` vem COM ponto na
    listagem — quando o nome vem sem ela, a versão com a extensão colada entra
    também, para casar com o `pdf_path.name` que o app mandou."""
    ext = str(item.get("extension") or "").strip().lower()
    if ext and not ext.startswith("."):
        ext = "." + ext
    nomes: set[str] = set()
    for k in ("name", "filename", "fileName", "originalName", "originalFileName"):
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            n = v.strip().lower()
            nomes.add(n)
            if ext and not n.endswith(ext):
                nomes.add(n + ext)
    return nomes


def _tamanho_do_item(item: dict) -> int | None:
    for k in ("sizeInBytes", "size", "fileSize", "length"):
        try:
            n = int(item.get(k))
        except (TypeError, ValueError):
            continue
        if n > 0:
            return n
    return None


def _mesmo_arquivo(item, nome: str, tamanho: int) -> bool:
    """Este anexo listado é o arquivo que o app tem na mão?

    Pelo NOME (sem caixa) ou, quando a listagem traz tamanho, pelos BYTES —
    o mesmo comprovante renomeado (" (2)", acento trocado) tem o mesmo
    tamanho, e subi-lo de novo é comprovante em dobro."""
    if not isinstance(item, dict):
        return False
    if nome.lower() in _nomes_do_item(item):
        return True
    t = _tamanho_do_item(item)
    return t is not None and t == tamanho


def _achar_tag(tags, nome: str) -> str | None:
    """O `id` da etiqueta chamada `nome`, sem acento nem caixa. None se não há.

    Aceita a lista crua ou o envelope paginado (`content`/`items`), porque os
    dois back-ends do ERP embrulham de jeitos diferentes."""
    if isinstance(tags, dict):
        tags = tags.get("content") or tags.get("items") or []
    alvo = util.norm(nome).strip()
    for t in (tags if isinstance(tags, list) else []):
        if not isinstance(t, dict):
            continue
        for k in ("name", "description", "label"):
            v = t.get(k)
            if isinstance(v, str) and util.norm(v).strip() == alvo and t.get("id"):
                return str(t["id"])
    return None


def estado_anexo(att: dict, paid_id: str) -> str:
    """Lê o resultado de `verificar_anexos` para um pagamento.

    O JS devolve -1 quando o fetch falha, e -1 NÃO é 0. Tratar os dois como
    "tem anexo" era o pior desfecho silencioso do app: a aba Anexar PULAVA o
    pagamento (nunca anexava) e a Conferência OMITIA a linha do relatório —
    as duas afirmando "está tudo certo" sobre algo que ninguém chegou a olhar.
    """
    n = att.get(paid_id)
    if n is None or n < 0:
        return NAO_VERIFICADO
    return COM_ANEXO if n > 0 else SEM_ANEXO


class MCApi:
    def __init__(self, cliente):
        """cliente = MCClient já aberto (não a página).

        Recebe o CLIENTE de propósito. O MCClient troca de aba sozinho quando
        o ERP abre a tela num alvo novo (`_adotar_aba`), e a MCApi guardava a
        página do momento da criação: ficava presa numa aba obsoleta e os
        fetch passavam a falhar sem explicação — a página existia, só não era
        mais a que estava logada e visível."""
        self._cliente = cliente
        self._pagina_ouvida = None
        self._req_pagos = None    # (url, headers) da lista de pagamentos
        self._req_anexos = None   # (url_base, headers) do endpoint de anexos
        self._diag_avisado = False
        self._tag_ids: dict[str, str] = {}   # etiqueta normalizada -> id (por execução)
        _ = self.page             # registra o listener na aba atual

    @property
    def page(self):
        """A aba ATUAL do cliente, com o listener de captura registrado nela."""
        pag = self._cliente.page
        if pag is not None and pag is not self._pagina_ouvida:
            pag.on("request", self._on_request)
            self._pagina_ouvida = pag
        return pag

    # ------------------------------------------------------------ captura
    def _on_request(self, req):
        try:
            u = req.url
            if "payable-installments/paginated-result" in u:
                h = {k: v for k, v in req.headers.items() if k.lower() in _H_PAGOS}
                if "authorization" in {k.lower() for k in h}:
                    self._req_pagos = (u, h)
            elif "/attachments" in u and "maiscontrole" in u:
                h = {k: v for k, v in req.headers.items() if k.lower() in _H_ANEXO}
                if "authorization" in {k.lower() for k in h}:
                    self._req_anexos = (u.split("?")[0], h)
        except Exception as e:
            if not self._diag_avisado:   # loga só a 1ª vez (evita spam)
                self._diag_avisado = True
                _diag(f"_on_request falhou ao ler cabeçalhos: {e!r}")

    def _esperar(self, attr, acao, timeout_s=30) -> bool:
        for _ in range(timeout_s * 2):
            if getattr(self, attr):
                return True
            acao()
            self.page.wait_for_timeout(500)
        return bool(getattr(self, attr))

    def capturar_credenciais(self, log=print) -> bool:
        """Espera a página fazer a 1ª requisição de pagamentos. Se ela já
        aconteceu (ex.: durante o login), retorna na hora, sem recarregar.

        `goto` para a rota em que a página JÁ ESTÁ é navegação de mesmo
        documento: o hash não muda, a SPA não re-roteia, a lista não é buscada
        de novo — e a captura esperava 30 segundos por uma requisição que nunca
        ia acontecer. Aconteceu em 20/08/2026, quando o login devolveu a página
        justamente na tela de Pagamentos: "a tela não carregou a lista", com a
        tela carregada na frente do usuário. Trocar de rota à mão e voltar
        resolvia — e é exatamente o que `reload` faz sozinho.
        """
        if self._req_pagos:
            return True
        self._abrir_pagamentos()
        ok = self._esperar("_req_pagos", lambda: None, timeout_s=30)
        if not ok:
            # Segunda chance com recarga completa: cobre o caso em que a página
            # estava na rota certa mas com a lista em algum estado que não
            # dispara a busca (filtro vazio, tela de boas-vindas).
            log("[!] A lista não veio; recarregando a tela de Pagamentos...")
            try:
                self.page.reload(wait_until="domcontentloaded")
            except Exception as e:
                _diag(f"reload da tela de Pagamentos falhou: {e!r}")
            ok = self._esperar("_req_pagos", lambda: None, timeout_s=30)
        if not ok:
            # O que a tela ESTAVA mostrando. Sem isto, "não carregou a lista"
            # cobre coisas diferentes demais — rota errada, sessão caída, ou a
            # tela de boas-vindas do ERP quando o filtro salvo não devolve
            # linha nenhuma. Em 20/08/2026 a causa foi a primeira, e descobrir
            # isso exigiu comparar horários de log com o que o usuário via.
            try:
                _diag(f"captura falhou; a página estava em {self.page.url}")
            except Exception:
                pass
            log("[!] A tela de Pagamentos não carregou a lista. "
                "Confira o login e tente de novo.")
        return ok

    def _abrir_pagamentos(self) -> None:
        """Leva a página à tela de Pagamentos, mesmo que ela já esteja nela."""
        pag = self.page
        atual = ""
        try:
            atual = pag.url or ""
        except Exception:
            atual = ""
        if "payable-installments" in atual:
            pag.reload(wait_until="domcontentloaded")
        else:
            pag.goto(config.MC_URL_PAGAMENTOS, wait_until="domcontentloaded")

    def capturar_credenciais_anexos(self, launch_id: str) -> bool:
        """Abre um lançamento (dispara a chamada de anexos) e captura os headers."""
        if self._req_anexos:
            return True
        self.page.goto(f"{config.MC_URL_BASE}/#/payable-installments/{launch_id}",
                       wait_until="domcontentloaded")
        ok = self._esperar("_req_anexos", lambda: None, timeout_s=20)
        self.page.goto(config.MC_URL_PAGAMENTOS, wait_until="domcontentloaded")
        return ok

    def garantir_credenciais_anexos(self, log=print, dias=365) -> bool:
        """Captura os cabeçalhos do outro back-end SEM receber um lançamento.

        `capturar_credenciais_anexos` precisa do id de um lançamento para abrir
        a tela dele e ouvir a chamada de anexos. Quem chega aqui por outro
        caminho não tem esse id: a aba Contratos parte de recebimentos e obras,
        e por isso ficava sem cabeçalho nenhum — a primeira leitura do ERP
        (listar as obras) morria com "Credenciais de anexos ainda não
        capturadas", que não diz ao usuário o que fazer.

        A isca passa a ser procurada aqui: serve QUALQUER lançamento pago
        recente, porque o que importa é a tela dele pedir os anexos. Também
        garante as credenciais de pagamentos, que são de onde a isca sai —
        assim uma chamada só deixa a API pronta para os dois back-ends."""
        if self._req_anexos:
            return True
        if not self.capturar_credenciais(log):
            return False
        isca = self._um_pagamento_recente(dias)
        if not isca:
            log(f"[!] Não achei nenhum pagamento nos últimos {dias} dias para "
                "abrir e capturar o acesso aos anexos. Abra um pagamento "
                "qualquer no Chrome e rode de novo.")
            return False
        return self.capturar_credenciais_anexos(isca)

    def _um_pagamento_recente(self, dias: int) -> str:
        """O id de UM lançamento pago nos últimos `dias`, ou "".

        Uma página de um item só: não interessa QUAL lançamento é, só que a
        tela dele exista para o navegador pedir os anexos dela."""
        hoje = datetime.date.today()
        url, headers = self._consulta_pagos([
            ("type", "PAID"), ("dateField", "DATE_OF_PAYMENT"),
            ("startDate", f"{hoje - datetime.timedelta(days=dias):%Y-%m-%d}"),
            ("endDate", f"{hoje:%Y-%m-%d}"),
            ("page", "0"), ("size", "1")])
        j = self._fetch_json(url, headers)
        if isinstance(j, dict) and j.get("__erro"):
            raise RuntimeError(
                f"A API respondeu {j['__erro']} ao procurar um pagamento "
                "recente. Recarregue a tela do Mais Controle no Chrome e "
                "tente de novo.")
        for item in ((j or {}).get("content") or []):
            if item.get("id"):
                return str(item["id"])
        return ""

    # ------------------------------------------------------------ fetch
    def _fetch_json(self, url: str, headers: dict):
        """Faz a chamada de dentro da página logada (mesma origem/cookies/UA)."""
        return self.page.evaluate(_JS_FETCH_JSON, {"url": url, "headers": headers})

    # ------------------------------------------------------------ pagos
    def _consulta_pagos(self, filtros: list[tuple[str, str]]) -> tuple[str, dict]:
        """A URL da lista de pagamentos capturada, com os filtros do app no
        lugar dos que vieram na requisição da tela.

        As três consultas desta lista (pagos, a pagar e a isca das credenciais
        de anexos) só mudam de filtro — o resto (host, caminho e os parâmetros
        da organização) tem de ser exatamente o que o navegador mandou. Isto
        já morava copiado em dois lugares; a terceira cópia seria a primeira
        chance de os três discordarem."""
        if not self._req_pagos:
            raise RuntimeError("Credenciais ainda não capturadas.")
        url_orig, headers = self._req_pagos
        partes = urlsplit(url_orig)
        base = f"{partes.scheme}://{partes.netloc}{partes.path}"
        params = [(k, v) for k, v in parse_qsl(partes.query)
                  if k not in ("page", "size", "startDate", "endDate",
                               "accountIds", "type", "dateField")]
        return base + "?" + urlencode(params + filtros), headers

    def listar_pagos(self, data_inicio: str, data_fim: str, log=print) -> list[dict]:
        """
        data_inicio / data_fim no formato 'aaaa-mm-dd'.
        Retorna a lista bruta de lançamentos (cada um com paids[]).
        SEMPRE filtra por títulos pagos (type=PAID) e data de pagamento.
        """
        filtros = [("type", "PAID"), ("dateField", "DATE_OF_PAYMENT"),
                   ("startDate", data_inicio), ("endDate", data_fim)]

        todos, pagina = [], 0
        while True:
            url, headers = self._consulta_pagos(
                filtros + [("page", str(pagina)), ("size", "500")])
            j = self._fetch_json(url, headers)
            if isinstance(j, dict) and j.get("__erro"):
                raise RuntimeError(
                    f"A API respondeu {j['__erro']} ao listar os pagos. "
                    "Recarregue a tela de Pagamentos no Chrome e tente de novo.")
            j = j or {}
            lote = j.get("content") or []
            todos.extend(lote)
            log(f"  ... página {pagina + 1}: {len(todos)} lançamento(s)")
            if not j.get("hasNextPage") or not lote:
                break
            pagina += 1
            if pagina > 50:
                # Truncar em silencio devolvia um resultado INCOMPLETO com cara
                # de completo: a Conferencia diria "tudo anexado" sobre um
                # periodo que nem foi lido inteiro.
                raise RuntimeError(
                    "o periodo tem mais de 50 paginas de lancamentos e eu "
                    "parei aqui para nao devolver uma lista pela metade.\n"
                    "Divida o periodo (por exemplo, quinzena a quinzena) e "
                    "rode de novo.")
        return todos

    # ------------------------------------------------------------ anexos
    def verificar_anexos(self, paid_ids: list[str], log=print,
                         progresso=None, cancelar=None) -> dict[str, int]:
        """Retorna {paidId: quantidade de arquivos anexados}, ou -1 se a
        consulta falhou. Use `estado_anexo()` para ler: -1 NÃO é zero.

        Lotes em paralelo de dentro da própria página (Promise.all).
        cancelar: função chamada entre lotes; retornando True, interrompe."""
        if not self._req_anexos:
            raise RuntimeError("Credenciais de anexos ainda não capturadas.")
        base, headers = self._req_anexos
        resultado: dict[str, int] = {}
        LOTE = 15

        def rodar(ids):
            # Uma falha de página (navegação no meio, sessão caindo) derrubava
            # o lote inteiro e a etapa toda. Aqui ela vira "não verificado"
            # para ESTES ids, e o resto do lote segue.
            try:
                parcial = self.page.evaluate(
                    _JS_FETCH_ANEXOS,
                    {"base": base, "ids": ids, "headers": headers})
            except Exception as e:
                _diag(f"verificar_anexos: lote de {len(ids)} falhou ({e!r}) — "
                      "marcados como NÃO VERIFICADO")
                resultado.update({i: -1 for i in ids if i not in resultado})
                return
            resultado.update(parcial or {})

        feitos = 0
        for i in range(0, len(paid_ids), LOTE):
            if cancelar and cancelar():
                return resultado
            rodar(paid_ids[i:i + LOTE])
            feitos = min(feitos + LOTE, len(paid_ids))
            if progresso:
                progresso(feitos, len(paid_ids))
            elif feitos and feitos % 195 == 0:
                log(f"  ... {feitos}/{len(paid_ids)} verificados")
        # tenta de novo os que falharam
        falhas = [p for p in paid_ids if resultado.get(p, -1) < 0]
        for i in range(0, len(falhas), LOTE):
            if cancelar and cancelar():
                break
            rodar(falhas[i:i + LOTE])
        restantes = [p for p in paid_ids
                     if estado_anexo(resultado, p) == NAO_VERIFICADO]
        if restantes:
            log(f"  [aviso] {len(restantes)} pagamento(s) NÃO VERIFICADOS "
                "(a consulta de anexos falhou neles)")
        return resultado


    # ------------------------------------------- a pagar (aba Pagamentos do dia)
    def listar_a_pagar(self, data_inicio: str, data_fim: str, log=print) -> list[dict]:
        """Títulos do período pela DATA PREVISTA (dateField=PLANNED).

        Espelho do `listar_pagos`, mas para o que ainda vai ser pago. Mantém
        `type=ALL` de propósito: o ERP devolve pagos e a pagar juntos e quem
        separa é o app (campo `paid`), assim o relatório consegue avisar
        "isto aqui já foi quitado" em vez de simplesmente sumir com a linha.

        `page` começa em 0 (Spring): pedir page=1 devolve a SEGUNDA página,
        com content vazio e sem erro nenhum.
        """
        filtros = [("type", "ALL"), ("dateField", "PLANNED"),
                   ("startDate", data_inicio), ("endDate", data_fim)]

        todos, pagina = [], 0
        while True:
            url, headers = self._consulta_pagos(
                filtros + [("page", str(pagina)), ("size", "500")])
            j = self._fetch_json(url, headers)
            if isinstance(j, dict) and j.get("__erro"):
                raise RuntimeError(
                    f"A API respondeu {j['__erro']} ao listar os lançamentos. "
                    "Recarregue a tela de Pagamentos no Chrome e tente de novo.")
            j = j or {}
            lote = j.get("content") or []
            todos.extend(lote)
            log(f"  ... página {pagina + 1}: {len(todos)} lançamento(s)")
            if not j.get("hasNextPage") or not lote:
                break
            pagina += 1
            if pagina > 50:
                # Truncar em silencio devolvia um resultado INCOMPLETO com cara
                # de completo: a Conferencia diria "tudo anexado" sobre um
                # periodo que nem foi lido inteiro.
                raise RuntimeError(
                    "o periodo tem mais de 50 paginas de lancamentos e eu "
                    "parei aqui para nao devolver uma lista pela metade.\n"
                    "Divida o periodo (por exemplo, quinzena a quinzena) e "
                    "rode de novo.")
        return todos

    def listar_overviews(self, installment_ids: list[str], log=print,
                         progresso=None, cancelar=None) -> dict[str, dict]:
        """Detalhe de cada parcela: {installmentId: overview}.

            GET .../payable-installments/<installmentId>/overview

        É o único lugar onde vivem dois campos que a lista não traz:

          purchaseOrder.number -> o NÚMERO da OC (na lista só existe o
                                  booleano hasPurchaseOrder);
          comment              -> o campo de observação do lançamento, que às
                                  vezes carrega a própria forma de pagar (já
                                  veio o Pix copia-e-cola inteiro de um pedido).

        O endpoint /comments responde 200 mas devolve items:[] — não é ali.
        """
        if not self._req_pagos:
            raise RuntimeError("Credenciais ainda não capturadas.")
        url_orig, headers = self._req_pagos
        partes = urlsplit(url_orig)
        raiz = f"{partes.scheme}://{partes.netloc}{partes.path}".rsplit("/", 1)[0]

        resultado: dict[str, dict] = {}
        LOTE = 12
        for i in range(0, len(installment_ids), LOTE):
            if cancelar and cancelar():
                break
            fatia = installment_ids[i:i + LOTE]
            parcial = self.page.evaluate(_JS_FETCH_LOTE, {
                "urls": [{"chave": str(x), "url": f"{raiz}/{x}/overview"} for x in fatia],
                "headers": headers,
            })
            for k, v in (parcial or {}).items():
                if isinstance(v, dict) and not v.get("__erro"):
                    resultado[k] = v
            if progresso:
                progresso(min(i + LOTE, len(installment_ids)), len(installment_ids))
        return resultado

    def anexos_de_titulos(self, trade_payable_ids: list[str], log=print,
                          progresso=None, cancelar=None) -> dict[str, list]:
        """{tradePayableId: [anexos]} — nível do TÍTULO, não do sub-pagamento.

        A aba Anexar olha `entityOrigin=PAID` (o comprovante fica no pagamento).
        Aqui é o contrário: queremos o boleto e a nota que vieram ANTES do
        pagamento, e esses ficam no título.
        """
        if not self._req_anexos:
            raise RuntimeError("Credenciais de anexos ainda não capturadas.")
        base, headers = self._req_anexos
        resultado: dict[str, list] = {}
        LOTE = 12
        for i in range(0, len(trade_payable_ids), LOTE):
            if cancelar and cancelar():
                break
            fatia = trade_payable_ids[i:i + LOTE]
            parcial = self.page.evaluate(_JS_FETCH_LOTE, {
                "urls": [{"chave": str(x),
                          "url": f"{base}?entityIds={x}&entityOrigin=TRADE_PAYABLE"}
                         for x in fatia],
                "headers": headers,
            })
            for k, v in (parcial or {}).items():
                resultado[k] = v if isinstance(v, list) else []
            if progresso:
                progresso(min(i + LOTE, len(trade_payable_ids)), len(trade_payable_ids))
        return resultado

    # ------------------------------------ contratos de financiamento
    # As três leituras da aba Contratos. Reaproveitam as credenciais já
    # capturadas trocando o CAMINHO: recebimentos vivem no mesmo host legado
    # dos pagamentos, obras e anexos no mesmo host dos anexos.
    def _base_legacy(self, caminho: str) -> tuple[str, dict]:
        if not self._req_pagos:
            raise RuntimeError("Credenciais ainda não capturadas.")
        url_orig, headers = self._req_pagos
        p = urlsplit(url_orig)
        raiz = p.path.split("/maiscontrole/services/")[0]
        return f"{p.scheme}://{p.netloc}{raiz}/maiscontrole/services/{caminho}", headers

    def _base_erp(self, caminho: str) -> tuple[str, dict]:
        if not self._req_anexos:
            raise RuntimeError("Credenciais de anexos ainda não capturadas.")
        base, headers = self._req_anexos
        p = urlsplit(base)
        return f"{p.scheme}://{p.netloc}/{caminho.lstrip('/')}", headers

    #: Naturezas que são venda. Vieram de GET /natures em 11/08/2026.
    NATUREZAS_DE_VENDA = (
        "85a40f0e-320c-4b0f-a0cc-54926c9d5aaf",   # Venda
        "af7b5fdf-ec24-441c-9eee-e925a94c3bb8",   # Venda de Bens
        "204c948d-ec08-49fb-9813-d06a7ed27746",   # Venda de Imóveis
    )

    def listar_recebimentos(self, data_inicio: str, data_fim: str,
                            log=print) -> list[dict]:
        """Recebimentos de VENDA já recebidos no período.

        `dateField=DATE_OF_RECEIPT` é o "Tipo de data por: Recebimento" da tela
        e `type=PAID` é o "Recebidos".

        Aqui os nomes da paginação são `page` (base 0) e `size` — e este é o
        ponto que mais engana: **`pageIndex`/`pageSize` são aceitos e IGNORADOS
        em silêncio**, e a resposta volta com o padrão de 20 registros como se
        estivesse completa. Foi assim que a sondagem quase concluiu que julho
        tinha 20 recebimentos no total.
        """
        base, headers = self._base_legacy("receipt-installments")
        todos: list[dict] = []
        pagina = 0
        while True:
            params = [("startDate", data_inicio), ("endDate", data_fim),
                      ("dateField", "DATE_OF_RECEIPT"), ("type", "PAID"),
                      ("page", str(pagina)), ("size", "200")]
            params += [("natureIds", n) for n in self.NATUREZAS_DE_VENDA]
            j = self._fetch_json(f"{base}?{urlencode(params)}", headers)
            if isinstance(j, dict) and j.get("__erro"):
                raise RuntimeError(
                    f"A API respondeu {j['__erro']} ao listar os recebimentos. "
                    "Recarregue a tela do Mais Controle no Chrome e tente de novo.")
            j = j or {}
            lote = j.get("content") or []
            todos.extend(lote)
            log(f"  ... página {pagina + 1}: {len(todos)} recebimento(s)")
            if j.get("last") or not lote:
                break
            pagina += 1
            if pagina > 50:
                raise RuntimeError(
                    "o período tem mais de 50 páginas de recebimentos e eu "
                    "parei aqui para não devolver uma lista pela metade.\n"
                    "Divida o período e rode de novo.")
        return todos

    #: Os três "papéis" do cadastro de Contatos. São as três telas do menu
    #: (`#/supplier`, `#/customer`, `#/employee`) sobre a MESMA tabela — e o
    #: endpoint recusa a chamada sem `role` ("O 'papel' do participante precisa
    #: ser especificado"). Pagamento pode ir para qualquer um dos três.
    PAPEIS_PARTICIPANTE = ("SUPPLIER", "CUSTOMER", "EMPLOYEE")

    def listar_participantes(self, log=print) -> dict[str, str]:
        """`{nome normalizado: CPF/CNPJ}` do cadastro de Contatos.

        Existe por causa do segmento B da remessa: ele exige o CPF/CNPJ de
        quem recebe, e o lançamento **não traz o id do participante** — só
        `paidTo`, que é o nome. Medido em 13/08/2026 sobre 300 lançamentos e
        455 participantes: 296 casaram pelo nome e todos os 296 tinham
        documento; as 4 sobras eram `paidTo` igual a "-".

        **Nome ambíguo é descartado.** Se dois participantes normalizam para o
        mesmo nome com documentos diferentes, não há como saber qual é — e
        escolher um seria pagar com o documento de outra pessoa. Some do mapa,
        e o pagamento cai na conferência como se não houvesse cadastro.
        """
        base, headers = self._base_legacy("participants")
        vistos: dict[str, set] = {}
        for papel in self.PAPEIS_PARTICIPANTE:
            pagina, quantos = 0, 0
            while True:
                params = [("page", str(pagina)), ("size", "200"),
                          ("role", papel), ("sort", "name")]
                j = self._fetch_json(f"{base}?{urlencode(params)}", headers)
                if isinstance(j, dict) and j.get("__erro"):
                    raise RuntimeError(
                        f"A API respondeu {j['__erro']} ao listar o cadastro de "
                        f"{papel.lower()}. Recarregue a tela do Mais Controle "
                        "no Chrome e tente de novo.")
                j = j or {}
                lote = j.get("content") or []
                for p in lote:
                    nome = util.norm_espaco(p.get("name") or "")
                    documento = _so_digitos(p.get("cnpj")) or _so_digitos(p.get("cpf"))
                    if nome and documento:
                        vistos.setdefault(nome, set()).add(documento)
                quantos += len(lote)
                if j.get("last") or not lote:
                    break
                pagina += 1
                if pagina > 50:
                    break
            log(f"  {papel.lower()}: {quantos} no cadastro")

        mapa = {n: docs.pop() for n, docs in vistos.items() if len(docs) == 1}
        ambiguos = len(vistos) - len(mapa)
        if ambiguos:
            log(f"  {ambiguos} nome(s) com documentos diferentes — fora do mapa, "
                "porque não dá para saber qual é o certo.")
        return mapa

    def listar_obras(self, log=print) -> list[dict]:
        """Todas as obras (id, name, customer).

        Paginação do OUTRO back-end: `pageIndex` começa em **1**, e o fim é
        `hasNextPage`. Trocar por `page`/`size` aqui devolve sempre a primeira
        página, sem erro."""
        base, headers = self._base_erp("work-management/works/detailed")
        todas: list[dict] = []
        indice = 1
        while True:
            j = self._fetch_json(
                f"{base}?{urlencode([('pageIndex', indice), ('pageSize', 200)])}",
                headers)
            if isinstance(j, dict) and j.get("__erro"):
                raise RuntimeError(
                    f"A API respondeu {j['__erro']} ao listar as obras.")
            j = j or {}
            itens = j.get("items") or []
            todas.extend(itens)
            log(f"  ... {len(todas)} obra(s)")
            if not j.get("hasNextPage") or not itens:
                break
            indice += 1
            if indice > 50:
                break
        return todas

    def detalhe_da_obra(self, work_id: str) -> dict:
        """O detalhe de UMA obra. O endereço só existe aqui.

        A lista não traz `address`, e é dele que saem a rua e a quadra/lote
        usadas para conferir o contrato — sem isto a conferência não existe."""
        base, headers = self._base_erp(
            f"work-management/works/{work_id}/detailed")
        j = self._fetch_json(base, headers)
        if isinstance(j, dict) and j.get("__erro"):
            raise RuntimeError(
                f"A API respondeu {j['__erro']} ao abrir a obra {work_id}.")
        return j if isinstance(j, dict) else {}

    def anexos_de_obras(self, work_ids: list[str], log=print,
                        progresso=None, cancelar=None) -> dict[str, list]:
        """{workId: [anexos]} — `entityOrigin=WORK`.

        O `downloadUrl` é URL pré-assinada do S3 com `Expires` curto: listar e
        baixar têm de acontecer na MESMA execução."""
        if not self._req_anexos:
            raise RuntimeError("Credenciais de anexos ainda não capturadas.")
        base, headers = self._req_anexos
        resultado: dict[str, list] = {}
        LOTE = 12
        for i in range(0, len(work_ids), LOTE):
            if cancelar and cancelar():
                break
            fatia = work_ids[i:i + LOTE]
            parcial = self.page.evaluate(_JS_FETCH_LOTE, {
                "urls": [{"chave": str(x),
                          "url": f"{base}?entityIds={x}&entityOrigin=WORK"}
                         for x in fatia],
                "headers": headers,
            })
            for k, v in (parcial or {}).items():
                resultado[k] = v if isinstance(v, list) else []
            if progresso:
                progresso(min(i + LOTE, len(work_ids)), len(work_ids))
        return resultado

    # ------------------------------------------------- anexos (conteúdo)
    def _anexos_brutos(self, paid_id: str):
        """O JSON cru da listagem de anexos de um sub-pagamento — a lista, ou
        `{"__erro": status}` quando o ERP recusa. Quem precisa distinguir
        "vazio" de "falhou" lê daqui; `listar_anexos` achata os dois."""
        if not self._req_anexos:
            raise RuntimeError("Credenciais de anexos ainda não capturadas.")
        base, headers = self._req_anexos
        return self._fetch_json(f"{base}?entityIds={paid_id}&entityOrigin=PAID",
                                headers)

    def listar_anexos(self, paid_id: str) -> list:
        """Lista os anexos (dados brutos da API) de um sub-pagamento."""
        j = self._anexos_brutos(paid_id)
        return j if isinstance(j, list) else []

    def _postar_json(self, url: str, headers: dict, corpo: dict):
        """POST de dentro da página. `{"__erro": status, "__corpo": …}` na recusa."""
        return self.page.evaluate(
            JS_POST_JSON, {"url": url, "headers": headers, "corpo": corpo})

    def _put_s3(self, url: str, dados: bytes, content_type: str) -> dict:
        """PUT cru do binário na URL pré-assinada. Devolve `{status, body}`."""
        return self.page.evaluate(_JS_PUT_S3, {
            "url": url, "contentType": content_type,
            "b64": base64.b64encode(dados).decode("ascii")})

    def _tag_id(self, nome: str) -> tuple[str | None, str]:
        """(id da etiqueta, motivo quando não há). Cacheado por execução: a
        lista de etiquetas não muda no meio de uma rodada, e pedi-la a cada
        comprovante é uma chamada a mais por arquivo, à toa."""
        chave = util.norm(nome).strip()
        if chave in self._tag_ids:
            return self._tag_ids[chave], ""
        url, headers = self._base_erp("attachments/tags")
        j = self._fetch_json(url, headers)
        if isinstance(j, dict) and j.get("__erro"):
            return None, f"tags:{j['__erro']}"
        tag_id = _achar_tag(j, nome)
        if not tag_id:
            return None, "sem_tag"
        self._tag_ids[chave] = tag_id
        return tag_id, ""

    def anexar_por_api(self, paid_id: str, pdf_path, *,
                       tag: str = config.TAG_COMPROVANTE, log=None,
                       dry_run: bool = False) -> str:
        """Sobe UM comprovante para o sub-pagamento `paid_id`, pela API.

        O contrato, verificado em produção para título (28/08/2026, 29 anexos)
        e igual para sub-pagamento, trocando só a origem:

            GET  {nova}/attachments/v2?entityIds=<paidId>&entityOrigin=PAID
            GET  {nova}/attachments/tags               -> id de "Comprovante"
            POST {nova}/attachments/v2/batch           -> URL S3 pré-assinada
            PUT  <URL S3>  (binário cru, só content-type)
            GET  {nova}/attachments/v2?entityIds=…     -> tem de listar o arquivo

        A identidade é o SUB-PAGAMENTO (`paids[].id`, o `paidId` que
        `montar_pagos` expõe), não a parcela (`launchId`): o comprovante mora
        no pagamento, e é ali que `verificar_anexos` e a Conferência o procuram.

        Devolve um destes, e o prefixo diz o que já tinha saído daqui:

            "anexado"                subiu, e a listagem de prova mostra o arquivo
            "ja_anexado"             a listagem prévia já tinha o arquivo (mesmo
                                     nome, ou mesmo tamanho); nada subiu
            "dry_run"                modo Simular: parou antes do POST, depois
                                     de provar credencial, listagem e etiqueta
            "erro:sem_credencial"    cabeçalhos de anexos não capturados; nada saiu
            "erro:batch:<motivo>"    o ERP RECUSOU antes de o arquivo sair (listagem
                                     prévia, etiquetas ou o POST com 4xx/5xx):
                                     nada subiu, e a tela pode tentar
            "erro:upload:<motivo>"   o POST saiu (ou pode ter saído) e o PUT não
                                     completou: o registro pode existir sem arquivo
            "erro:nao_confirmado"    o PUT respondeu 2xx e a listagem de prova não
                                     mostra o arquivo

        "anexado" só sai com PROVA, como na tela: subir sem conferir era
        relatar anexo que talvez não exista. E o POST NUNCA se repete daqui —
        um batch reenviado é um segundo registro de anexo no mesmo pagamento.
        """
        log = log or (lambda _m: None)
        if not self._req_anexos:
            return ERRO_SEM_CREDENCIAL
        pdf_path = Path(pdf_path)
        try:
            dados = pdf_path.read_bytes()
        except OSError as e:
            _log.warning("anexar_por_api: não li o arquivo (paid %s)", paid_id,
                         exc_info=True)
            return f"{_PREFIXO_BATCH}arquivo:{e.__class__.__name__}"
        nome, tamanho = pdf_path.name, len(dados)

        # (a) já está lá? Comparado pelo nome ou pelos bytes — sem upload.
        try:
            lista = self._anexos_brutos(paid_id)
        except Exception as e:
            _log.warning("anexar_por_api: a listagem prévia falhou (paid %s)",
                         paid_id, exc_info=True)
            return f"{_PREFIXO_BATCH}listagem:{e.__class__.__name__}"
        if isinstance(lista, dict) and lista.get("__erro"):
            return f"{_PREFIXO_BATCH}listagem:{lista['__erro']}"
        if any(_mesmo_arquivo(item, nome, tamanho)
               for item in (lista if isinstance(lista, list) else [])):
            return JA_ANEXADO

        try:
            tag_id, motivo = self._tag_id(tag)
        except Exception as e:
            _log.warning("anexar_por_api: a lista de etiquetas falhou",
                         exc_info=True)
            return f"{_PREFIXO_BATCH}tags:{e.__class__.__name__}"
        if not tag_id:
            return _PREFIXO_BATCH + motivo

        if dry_run:
            return "dry_run"

        # (b) o batch: o ERP cria o registro e devolve onde pôr o binário.
        ext = pdf_path.suffix.lstrip(".").lower() or "pdf"
        content_type = _TIPOS_DE_ARQUIVO.get(ext, "application/octet-stream")
        corpo = {"entityOrigin": "PAID", "entityId": str(paid_id),
                 "attachmentsItem": [{"name": nome, "contentType": content_type,
                                      "extension": ext, "sizeInBytes": tamanho,
                                      "tagId": tag_id}]}
        url_batch, headers = self._base_erp("attachments/v2/batch")
        try:
            resp = self._postar_json(url_batch, headers, corpo)
        except Exception:
            # Sem resposta não se sabe se o registro nasceu: fica do lado
            # "pode ter saído", que é o que impede a tela de duplicar.
            _log.warning("anexar_por_api: o POST do batch não respondeu "
                         "(paid %s)", paid_id, exc_info=True)
            return f"{_PREFIXO_UPLOAD}batch_sem_resposta"
        if isinstance(resp, dict) and resp.get("__erro"):
            _log.warning("anexar_por_api: o batch respondeu %s (paid %s)",
                         resp["__erro"], paid_id)
            return f"{_PREFIXO_BATCH}{resp['__erro']}"
        url_s3 = _primeira_url_s3(resp)
        if not url_s3:
            campos = sorted(resp) if isinstance(resp, dict) else type(resp).__name__
            _log.warning("anexar_por_api: o batch respondeu sem URL de S3 "
                         "(paid %s); campos: %s", paid_id, campos)
            return f"{_PREFIXO_UPLOAD}sem_url_s3"

        # (c) o binário, direto no S3.
        try:
            r = self._put_s3(url_s3, dados, content_type)
        except Exception:
            _log.warning("anexar_por_api: o PUT no S3 não respondeu (paid %s)",
                         paid_id, exc_info=True)
            return f"{_PREFIXO_UPLOAD}sem_resposta"
        status = r.get("status") if isinstance(r, dict) else None
        if not isinstance(status, int) or not 200 <= status < 300:
            _log.warning("anexar_por_api: o S3 respondeu %s (paid %s) — o registro "
                         "pode ter ficado sem arquivo; confira no ERP", status, paid_id)
            return f"{_PREFIXO_UPLOAD}{status}"

        # (d) a prova: a listagem tem de mostrar o arquivo. Sem ela não é
        # "anexado" — e a tela NÃO pode tentar, porque ele pode estar lá.
        try:
            depois = self._anexos_brutos(paid_id)
        except Exception:
            _log.warning("anexar_por_api: a listagem de prova falhou (paid %s)",
                         paid_id, exc_info=True)
            depois = None
        if isinstance(depois, list) and any(_mesmo_arquivo(i, nome, tamanho)
                                            for i in depois):
            log("   comprovante subiu pela API e aparece na listagem do pagamento")
            return ANEXADO
        campos = sorted({k for i in (depois if isinstance(depois, list) else [])
                         if isinstance(i, dict) for k in i})
        _log.warning("anexar_por_api: subiu, mas a listagem não mostra o arquivo "
                     "(paid %s); %d item(ns), campos: %s", paid_id,
                     len(depois) if isinstance(depois, list) else -1, campos)
        return ERRO_NAO_CONFIRMADO

    def baixar_anexo(self, url: str) -> bytes | None:
        """Baixa um anexo de dentro da página logada. Tenta primeiro SEM
        cabeçalhos (URLs pré-assinadas de armazenamento externo — S3 etc. —
        quebram se receberem o Authorization do ERP) e, se falhar, tenta COM
        os cabeçalhos de autenticação (arquivos servidos pelo próprio ERP)."""
        _, headers = self._req_anexos
        motivos = []
        for h in ({}, headers):
            rotulo = "sem cabeçalhos" if not h else "com cabeçalhos"
            try:
                r = self.page.evaluate(_JS_FETCH_B64, {"url": url, "headers": h})
            except Exception as e:
                motivos.append(f"{rotulo}: {e!r}")
                r = None
            if isinstance(r, dict) and not r.get("__erro") and "b64" in r:
                try:
                    return base64.b64decode(r["b64"])
                except Exception as e:
                    motivos.append(f"{rotulo}: base64 inválido ({e!r})")
                    continue
            elif isinstance(r, dict) and r.get("__erro"):
                motivos.append(f"{rotulo}: {str(r['__erro'])[:120]}")
        _diag(f"baixar_anexo falhou em {_host_path_diag(url)} — "
              + " | ".join(motivos or ["resposta inesperada"]))
        return None


def _coletar_urls(item, out=None) -> list:
    if out is None:
        out = []
    if isinstance(item, dict):
        for v in item.values():
            _coletar_urls(v, out)
    elif isinstance(item, list):
        for v in item:
            _coletar_urls(v, out)
    elif isinstance(item, str) and item.startswith("http"):
        out.append(item)
    return out


def achar_url_anexo(item) -> str | None:
    """Procura a URL do arquivo dentro do registro de anexo da API, preferindo
    a que tem cara de arquivo (extensão de doc/imagem ou palavra de download)."""
    import re as _re
    urls = _coletar_urls(item)
    if not urls:
        return None

    def pontos(u: str) -> int:
        ul = u.lower()
        s = 0
        if _re.search(r"\.(pdf|png|jpe?g|jpeg)(\?|$)", ul):
            s += 3
        if any(k in ul for k in ("download", "attachment", "anexo", "arquivo",
                                  "file", "s3", "storage", "blob", "amazonaws")):
            s += 2
        return s

    return max(urls, key=pontos)


# ---------------------------------------------------------------- utilidades
def _cents(x):
    """Converte um número da API para centavos (int) ou None."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    c = round(v * 100)
    return c if c else None


# O campo do favorecido é `paidTo` — confirmado lendo a API de produção
# (lançamentos de 07/08/2026). `paidWithWithhold` traz o mesmo nome e serve de
# reserva. Os demais são palpites de instalações diferentes do ERP, mantidos
# porque não custam nada; se nenhum servir, o diagnostico.log registra quais
# campos vieram (só os NOMES, sem os valores).
_CHAVES_FAVORECIDO = (
    "paidTo", "paidWithWithhold",
    "providerName", "providersNames", "provider",
    "supplierName", "supplier",
    "personName", "person",
    "favoredName", "favored",
    "beneficiaryName", "beneficiary",
    "creditorName", "creditor",
    "payeeName", "payee",
    "partnerName", "partner",
    "entityName", "entity",
    "clientName", "customerName",
)
_CHAVES_NOME = ("name", "socialName", "fantasyName", "corporateName",
                "tradeName", "fullName", "description")


def _nome_de(v) -> str:
    """Nome legível de um campo que pode vir string, dict ou lista."""
    if not v:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, list):
        return "; ".join(x for x in (_nome_de(i) for i in v) if x)
    if isinstance(v, dict):
        for k in _CHAVES_NOME:
            n = v.get(k)
            if isinstance(n, str) and n.strip():
                return n.strip()
    return ""


def _favorecido(l: dict) -> str:
    for k in _CHAVES_FAVORECIDO:
        nome = _nome_de(l.get(k))
        if nome:
            return nome
    return ""


RE_OC_NF = re.compile(r"\b(OC|NFS|NF|OS)\s*[:\-]?\s*(\d{2,})", re.I)


def _ocs_nfs(*textos) -> list[str]:
    """OC/NF citados no lançamento — é o sinal mais forte do casamento, então
    vale mostrar separado em vez de deixar escondido no meio da descrição."""
    achados = []
    for t in textos:
        for m in RE_OC_NF.finditer(t or ""):
            marca = f"{m.group(1).upper()} {m.group(2)}"
            if marca not in achados:
                achados.append(marca)
    return achados


def montar_pagos(lancamentos: list[dict]) -> list[dict]:
    """Achata lançamentos -> um registro por sub-pagamento (paid).

    Além do valor principal, guarda em "valores" todas as variações
    conhecidas — valor nominal e VALOR PAGO (nominal + juros/multa − desconto)
    — para o casamento aceitar boletos pagos com acréscimos ou descontos."""
    pagos = []
    achou_favorecido = False
    for l in lancamentos:
        cat = l.get("category")
        cat = "" if not cat else (cat if isinstance(cat, str)
                                  else (cat.get("name") or cat.get("description") or ""))
        favorecido = _favorecido(l)
        achou_favorecido = achou_favorecido or bool(favorecido)
        doc = str(l.get("documentNumber") or "")
        desc = l.get("description") or ""
        for p in (l.get("paids") or []):
            pd = (p.get("payingDate") or "")[:10]  # aaaa-mm-dd
            valores = set()
            for k in ("paidValue", "value", "paymentValue", "netValue"):
                c = _cents(p.get(k))
                if c:
                    valores.add(c)
            # "totalValue" e "amount" saíram da lista: em título parcelado elas
            # trazem o valor CHEIO do título, e aceitá-las casava o PDF do
            # total com UMA parcela — comprovante errado no lançamento certo.
            # Ficam registradas quando divergem, para o dia em que o ERP mudar
            # de novo e estes nomes voltarem a ser os únicos com o valor.
            for k in ("totalValue", "amount"):
                c = _cents(p.get(k))
                if c and c not in valores:
                    _diag(f"montar_pagos: {k}={c} difere dos valores aceitos "
                          f"{sorted(valores)} (paid {p.get('id')}) — ignorado")
            base = _cents(p.get("value"))
            acrescimos = sum(c for c in (_cents(p.get(k)) for k in
                             ("interest", "interestValue", "fine", "fineValue",
                              "addition", "additionValue", "fees", "feeValue"))
                             if c)
            descontos = sum(c for c in (_cents(p.get(k)) for k in
                            ("discount", "discountValue")) if c)
            if base and (acrescimos or descontos):
                valores.add(base + acrescimos - descontos)
            valor = _cents(p.get("paidValue")) or base or (max(valores) if valores else 0)
            pagos.append({
                "launchId": l.get("id") or l.get("tradePayableId"),
                "paidId": p.get("id"),
                "valor": valor,
                "valores": sorted(valores) or [valor],
                "data": (pd[8:10] + pd[5:7]) if len(pd) == 10 else "",
                "dataFull": pd,
                "doc": doc,
                "works": l.get("worksNames") or [],
                "desc": desc,
                "conta": p.get("accountName") or "",
                "categoria": cat,
                "favorecido": favorecido,
                "ocs": _ocs_nfs(desc, doc),
            })
    if lancamentos and not achou_favorecido:
        # não achamos o campo: registra quais existem (só os NOMES) para dar
        # para acertar _CHAVES_FAVORECIDO sem chutar
        _diag("favorecido não encontrado nos lançamentos. Campos disponíveis: "
              + ", ".join(sorted(str(k) for k in lancamentos[0]))[:900])
    return pagos
