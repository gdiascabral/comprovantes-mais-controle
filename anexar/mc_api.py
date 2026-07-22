# -*- coding: utf-8 -*-
"""
Leitura dos pagamentos e dos anexos pela MESMA API que a tela de Pagamentos usa.

Como funciona: com o Chrome aberto e logado (Playwright), o app observa as
requisições que a própria página faz e reaproveita os cabeçalhos de
autenticação (o token fica só na memória, nada é salvo em disco). Com eles:

  - lista os títulos PAGOS do período (type=PAID, dateField=DATE_OF_PAYMENT),
    sem filtro de conta — a seleção de contas é feita no app, por checkbox;
  - verifica, pago a pago, se há arquivo anexado no nível do sub-pagamento
    (endpoint attachments/v2 com entityOrigin=PAID).
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit, parse_qsl

import requests

try:
    from . import config
except ImportError:
    import config

# cabeçalhos que interessam (o resto é descartado)
_H_PAGOS = {"accept", "authorization", "organization-unit-id", "user-id", "company-id"}
_H_ANEXO = {"accept", "authorization", "company-id"}


class MCApi:
    def __init__(self, page):
        """page = página do Playwright já criada (MCClient.page)."""
        self.page = page
        self._req_pagos = None    # (url, headers) da lista de pagamentos
        self._req_anexos = None   # headers do endpoint de anexos
        page.on("request", self._on_request)

    # ------------------------------------------------------------ captura
    def _on_request(self, req):
        try:
            u = req.url
            if "payable-installments/paginated-result" in u:
                h = {k: v for k, v in req.headers.items() if k.lower() in _H_PAGOS}
                if "authorization" in {k.lower() for k in h}:
                    self._req_pagos = (u, h)
            elif "/attachments" in u and "prod-erp-api" in u:
                h = {k: v for k, v in req.headers.items() if k.lower() in _H_ANEXO}
                if "authorization" in {k.lower() for k in h}:
                    self._req_anexos = h
        except Exception:
            pass

    def _esperar(self, attr, acao, timeout_s=30) -> bool:
        for _ in range(timeout_s * 2):
            if getattr(self, attr):
                return True
            acao()
            self.page.wait_for_timeout(500)
        return bool(getattr(self, attr))

    def capturar_credenciais(self, log=print) -> bool:
        """Abre a tela de Pagamentos e espera a página fazer a 1ª requisição."""
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
            r = requests.get(base, params=q, headers=headers, timeout=120)
            r.raise_for_status()
            j = r.json()
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
                         progresso=None) -> dict[str, int]:
        """Retorna {paidId: quantidade de arquivos anexados}. Requisições em paralelo."""
        if not self._req_anexos:
            raise RuntimeError("Credenciais de anexos ainda não capturadas.")
        headers = self._req_anexos
        url = "https://prod-erp-api.maiscontroleerp.com.br/attachments/v2"
        resultado: dict[str, int] = {}

        def um(pid):
            r = requests.get(url, params={"entityIds": pid, "entityOrigin": "PAID"},
                             headers=headers, timeout=60)
            if r.status_code != 200:
                return pid, -1
            j = r.json()
            return pid, (len(j) if isinstance(j, list) else 0)

        feitos = 0
        with ThreadPoolExecutor(max_workers=15) as ex:
            futs = [ex.submit(um, pid) for pid in paid_ids]
            for f in as_completed(futs):
                try:
                    pid, n = f.result()
                    resultado[pid] = n
                except Exception:
                    pass
                feitos += 1
                if progresso:
                    progresso(feitos, len(paid_ids))
                elif feitos % 200 == 0:
                    log(f"  ... {feitos}/{len(paid_ids)} verificados")
        # tenta de novo os que falharam
        pendentes = [p for p in paid_ids if resultado.get(p, -1) < 0]
        for pid in pendentes:
            try:
                _, n = um(pid)
                resultado[pid] = n
            except Exception:
                resultado[pid] = -1
        return resultado


# ---------------------------------------------------------------- utilidades
def montar_pagos(lancamentos: list[dict]) -> list[dict]:
    """Achata lançamentos -> um registro por sub-pagamento (paid)."""
    pagos = []
    for l in lancamentos:
        cat = l.get("category")
        cat = "" if not cat else (cat if isinstance(cat, str)
                                  else (cat.get("name") or cat.get("description") or ""))
        for p in (l.get("paids") or []):
            pd = (p.get("payingDate") or "")[:10]  # aaaa-mm-dd
            pagos.append({
                "launchId": l.get("id") or l.get("tradePayableId"),
                "paidId": p.get("id"),
                "valor": round(float(p.get("value") or p.get("paidValue") or 0) * 100),
                "data": (pd[8:10] + pd[5:7]) if len(pd) == 10 else "",
                "dataFull": pd,
                "doc": str(l.get("documentNumber") or ""),
                "works": l.get("worksNames") or [],
                "desc": l.get("description") or "",
                "conta": p.get("accountName") or "",
                "categoria": cat,
            })
    return pagos
