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
    (endpoint de attachments com entityOrigin=PAID).
"""
import re
from urllib.parse import urlsplit, parse_qsl, urlencode

try:
    from . import config
except ImportError:
    import config


_diag = config.diag              # o registro de diagnóstico agora mora no config


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


class MCApi:
    def __init__(self, page):
        """page = página do Playwright já criada (MCClient.page)."""
        self.page = page
        self._req_pagos = None    # (url, headers) da lista de pagamentos
        self._req_anexos = None   # (url_base, headers) do endpoint de anexos
        self._diag_avisado = False
        page.on("request", self._on_request)

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
        aconteceu (ex.: durante o login), retorna na hora, sem recarregar."""
        if self._req_pagos:
            return True
        self.page.goto(config.MC_URL_PAGAMENTOS, wait_until="domcontentloaded")
        ok = self._esperar("_req_pagos", lambda: None, timeout_s=30)
        if not ok:
            log("[!] A tela de Pagamentos não carregou a lista. "
                "Confira o login e tente de novo.")
        return ok

    def capturar_credenciais_anexos(self, launch_id: str) -> bool:
        """Abre um lançamento (dispara a chamada de anexos) e captura os headers."""
        if self._req_anexos:
            return True
        self.page.goto(f"{config.MC_URL_BASE}/#/payable-installments/{launch_id}",
                       wait_until="domcontentloaded")
        ok = self._esperar("_req_anexos", lambda: None, timeout_s=20)
        self.page.goto(config.MC_URL_PAGAMENTOS, wait_until="domcontentloaded")
        return ok

    # ------------------------------------------------------------ fetch
    def _fetch_json(self, url: str, headers: dict):
        """Faz a chamada de dentro da página logada (mesma origem/cookies/UA)."""
        return self.page.evaluate(_JS_FETCH_JSON, {"url": url, "headers": headers})

    # ------------------------------------------------------------ pagos
    def listar_pagos(self, data_inicio: str, data_fim: str, log=print) -> list[dict]:
        """
        data_inicio / data_fim no formato 'aaaa-mm-dd'.
        Retorna a lista bruta de lançamentos (cada um com paids[]).
        SEMPRE filtra por títulos pagos (type=PAID) e data de pagamento.
        """
        if not self._req_pagos:
            raise RuntimeError("Credenciais ainda não capturadas.")
        url_orig, headers = self._req_pagos
        partes = urlsplit(url_orig)
        base = f"{partes.scheme}://{partes.netloc}{partes.path}"
        params = [(k, v) for k, v in parse_qsl(partes.query)
                  if k not in ("page", "size", "startDate", "endDate",
                               "accountIds", "type", "dateField")]
        params += [("type", "PAID"), ("dateField", "DATE_OF_PAYMENT"),
                   ("startDate", data_inicio), ("endDate", data_fim)]

        todos, pagina = [], 0
        while True:
            q = params + [("page", str(pagina)), ("size", "500")]
            j = self._fetch_json(base + "?" + urlencode(q), headers)
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
                break
        return todos

    # ------------------------------------------------------------ anexos
    def verificar_anexos(self, paid_ids: list[str], log=print,
                         progresso=None, cancelar=None) -> dict[str, int]:
        """Retorna {paidId: quantidade de arquivos anexados}. Lotes em paralelo
        de dentro da própria página (Promise.all).
        cancelar: função chamada entre lotes; retornando True, interrompe."""
        if not self._req_anexos:
            raise RuntimeError("Credenciais de anexos ainda não capturadas.")
        base, headers = self._req_anexos
        resultado: dict[str, int] = {}
        LOTE = 15

        def rodar(ids):
            parcial = self.page.evaluate(
                _JS_FETCH_ANEXOS, {"base": base, "ids": ids, "headers": headers})
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
        return resultado


    # ------------------------------------------------- anexos (conteúdo)
    def listar_anexos(self, paid_id: str) -> list:
        """Lista os anexos (dados brutos da API) de um sub-pagamento."""
        if not self._req_anexos:
            raise RuntimeError("Credenciais de anexos ainda não capturadas.")
        base, headers = self._req_anexos
        j = self._fetch_json(f"{base}?entityIds={paid_id}&entityOrigin=PAID",
                             headers)
        return j if isinstance(j, list) else []

    def baixar_anexo(self, url: str) -> bytes | None:
        """Baixa um anexo de dentro da página logada. Tenta primeiro SEM
        cabeçalhos (URLs pré-assinadas de armazenamento externo — S3 etc. —
        quebram se receberem o Authorization do ERP) e, se falhar, tenta COM
        os cabeçalhos de autenticação (arquivos servidos pelo próprio ERP)."""
        import base64
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


# O nome do favorecido não tem um campo fixo conhecido na API: cada instalação
# do ERP pode expor um. Tentamos os nomes prováveis e, se nenhum servir, o
# diagnostico.log registra quais campos vieram (só os NOMES, sem os valores),
# para ajustar sem precisar adivinhar de novo.
_CHAVES_FAVORECIDO = (
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
            for k in ("paidValue", "value", "paymentValue", "totalValue",
                      "netValue", "amount"):
                c = _cents(p.get(k))
                if c:
                    valores.add(c)
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
