# -*- coding: utf-8 -*-
"""Ler o ERP pelo Chrome central SEM Playwright: o jeito oficial (18/11/2026).

POR QUE EXISTE
--------------
Os chats que fazem conferência e lançamento à mão (`ferramentas/<tarefa>/`,
fora do repositório) aprenderam em 04/11/2026 que o `connect_over_cdp` do
Playwright trava no Chrome central, e passaram a falar com ele por CDP cru:
abrem uma aba por `PUT /json/new`, capturam os cabeçalhos do tráfego da tela e
fazem `fetch` de dentro dela. Cada chat copiou um `cdp.py` próprio — 31 cópias
em 18/11 — e nenhuma passava pela faxina nem por fila nenhuma. Na tarde de
18/11 o app falhou várias vezes seguidas ("não respondeu em 45 s para o robô
conectar") com um desses scripts puxando centenas de páginas do ERP no mesmo
Chrome. Script cortado no meio deixa a aba no Chrome, porque o `atexit` não
roda quando o processo é morto, e cada aba do ERP a mais é uma página pesada
que pode ficar calada. Este módulo é a cópia única, com as três coisas que
faltavam:

1. **A fila** (`central.fila`): a aba nasce e a página carrega dentro da vez
   de conectar, porque é o instante em que uma aba do ERP fica calada, e uma
   aba calada derruba o `connect_over_cdp` do app.
2. **O registro na faxina** (`faxina.registrar`): morreu o processo, a faxina
   fecha a aba que ele deixou (o porteiro a cada ciclo, e o app antes de
   conectar).
3. **Fechar sempre**: `with`, `fechar()` ou o fim do programa. Só a aba que
   ela abriu, nunca a de ninguém. Também não recarrega a aba de quem está
   usando o Chrome: a captura navega a aba nova, que é dela.

COMO USAR (num script de `ferramentas/`)
----------------------------------------
    import sys; sys.path.insert(0, r"C:/AUTOMAÇÕES MAIS CONTROLE/_app/codigo")
    from erp.cdp_cru import SessaoCdp
    with SessaoCdp() as s:
        dados = s.pedir(f"{hosts.LEGACY}/payable-installments/...")

Uma `SessaoCdp` por script e usada numa thread só. Só a biblioteca padrão e
o `_CanalCdp` do `central` (o `websockets` não está no exe)."""
from __future__ import annotations

import contextlib
import json
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from erp import central, faxina, hosts
from erp.sessao import ErpErro

#: Onde a aba captura os cabeçalhos: a tela carrega os dois back-ends.
URL_CAPTURA = f"{hosts.ACESSAR}/#/app/dashboard"
#: Hosts cujos cabeçalhos a captura guarda, e os cabeçalhos que interessam.
HOSTS = (hosts.HOST_LEGACY, hosts.HOST_ERP_API)
CHAVES = ("authorization", "user-id", "company-id", "organization-unit-id")
#: Teto da captura (dentro da fila: segura os outros só esse tanto).
PRAZO_CAPTURA = 30.0
#: Teto de um `fetch` de dentro da página.
PRAZO_PEDIDO = 120.0
#: "Failed to fetch" num GET (a página navegou no meio): tenta de novo.
TENTATIVAS_GET = 3
ESPERA_TENTATIVA = 3.0

_JS_FETCH = """async (a) => {
  const r = await fetch(a.url, {method: a.metodo,
    headers: Object.assign({'content-type': 'application/json'}, a.headers),
    body: a.corpo === null ? undefined : JSON.stringify(a.corpo)});
  const t = await r.text(); let d = null;
  try { d = t ? JSON.parse(t) : null; } catch (e) { d = t.slice(0, 800); }
  return {status: r.status, dados: d};
}"""


class AbaCdp:
    """Uma aba própria no Chrome central, falada por CDP cru."""

    def __init__(self, acesso: central.Acesso | str = "principal", *,
                 pasta: Path | None = None, abrir=urllib.request.urlopen,
                 canal=None, garantir=None):
        a = central.acesso(acesso, pasta) if isinstance(acesso, str) else acesso
        if a is None:
            raise ErpErro(f"o Chrome central '{acesso}' não está ligado nesta "
                          "máquina (falta o _central/acessos.json)")
        self.acesso: central.Acesso = a
        self._pasta = pasta
        self._abrir = abrir
        self._canal_cls = canal or central._CanalCdp
        self._garantir = garantir or central.garantir_chrome
        self.alvo: str | None = None
        self._ws: str | None = None
        self._canal = None
        self._registro: Path | None = None
        self._fechada = False

    # ---------------------------------------------------------------- vida

    def abrir(self, url: str = "about:blank", *, carregar: float = PRAZO_CAPTURA,
              ao_carregar=None) -> "AbaCdp":
        """Abre a aba em `url` dentro da fila e registra na faxina.
        `ao_carregar(self)` roda ainda dentro da fila (a captura usa)."""
        endereco = self._garantir(self.acesso)
        # Antes de abrir a dela, as que robôs mortos deixaram (só essas).
        with contextlib.suppress(Exception):
            faxina.limpar_mortos(self.acesso, self._pasta)
        with central.fila(self.acesso):
            pedido = urllib.request.Request(
                f"{endereco}/json/new?{urllib.parse.quote('about:blank', safe='')}",
                method="PUT")        # o Chrome 111+ recusa GET
            with self._abrir(pedido, timeout=10) as r:
                t = json.loads(r.read().decode("utf-8"))
            self.alvo, self._ws = str(t["id"]), str(t["webSocketDebuggerUrl"])
            self._registro = faxina.registrar(self.alvo, self.acesso.porta, self._pasta)
            _fechar_no_fim(self)
            try:
                self._canal = self._canal_cls(self._ws, 10.0)
                if url != "about:blank":
                    self._navegar(url, carregar)
                if ao_carregar is not None:
                    ao_carregar(self)
            except BaseException:
                self.fechar()
                raise
        return self

    def fechar(self) -> None:
        """Fecha a aba (só a dela). Pode ser chamada mais de uma vez."""
        if self._fechada:
            return
        self._fechada = True
        if self._canal is not None:
            with contextlib.suppress(Exception):
                self._canal.fechar()
        if self.alvo:
            with contextlib.suppress(Exception):
                with self._abrir(f"{central.endereco(self.acesso)}/json/close/{self.alvo}",
                                 timeout=10) as r:
                    r.read()
        faxina.desregistrar(self._registro)

    def __enter__(self):
        return self if self.alvo else self.abrir()

    def __exit__(self, *exc):
        self.fechar()
        return False

    # ------------------------------------------------------------- conversa

    def _pedir(self, metodo: str, params: dict | None = None, *, prazo: float) -> dict:
        if self._canal is None or self._fechada:
            raise ErpErro("a aba do CDP cru não está aberta")
        try:
            r = self._canal.pedir(metodo, params, prazo=prazo)
        except central._SemResposta:
            raise ErpErro(f"a aba do Chrome central não respondeu em {prazo:.0f} s "
                          f"({metodo})") from None
        if r.get("error"):
            raise ErpErro(f"o Chrome recusou {metodo}: {r['error'].get('message')}")
        return r.get("result") or {}

    def _navegar(self, url: str, prazo: float) -> None:
        self._pedir("Page.navigate", {"url": url}, prazo=prazo)
        limite = time.monotonic() + prazo
        while time.monotonic() < limite:
            with contextlib.suppress(ErpErro):
                if self.avaliar("document.readyState", prazo=5) == "complete":
                    return
            time.sleep(0.5)

    def avaliar(self, js: str, *, prazo: float = PRAZO_PEDIDO):
        """O valor de `js` na página (promessas são esperadas)."""
        r = self._pedir("Runtime.evaluate", {"expression": js, "awaitPromise": True,
                                             "returnByValue": True}, prazo=prazo)
        if "exceptionDetails" in r:
            raise RuntimeError(json.dumps(r["exceptionDetails"], ensure_ascii=False)[:500])
        return (r.get("result") or {}).get("value")

    def capturar(self, url: str = URL_CAPTURA, *, prazo: float = PRAZO_CAPTURA) -> dict:
        """Navega a PRÓPRIA aba para `url` e guarda, por host, os cabeçalhos de
        autenticação que a tela mandou. Devolve {host: {cabeçalho: valor}}."""
        canal = self._canal
        cab: dict[str, dict[str, str]] = {}
        canal.enviar("Network.enable")
        canal.enviar("Page.navigate", {"url": url})
        limite = time.monotonic() + prazo
        try:
            while time.monotonic() < limite and not all(
                    "authorization" in cab.get(h, {}) for h in HOSTS):
                try:
                    m = canal.proxima(limite)
                except central._SemResposta:
                    break
                if m.get("method") not in ("Network.requestWillBeSent",
                                           "Network.requestWillBeSentExtraInfo"):
                    continue
                p = m.get("params") or {}
                req = p.get("request") or {}
                url_req = req.get("url") or ""
                hl = {str(k).lower(): v for k, v in
                      (req.get("headers") or p.get("headers") or {}).items()}
                for h in HOSTS:
                    if urllib.parse.urlsplit(url_req).hostname == h or hl.get(":authority") == h:
                        d = cab.setdefault(h, {})
                        for k in CHAVES:
                            if hl.get(k):
                                d[k] = hl[k]
        finally:
            with contextlib.suppress(Exception):
                canal.enviar("Network.disable")
        return cab


class SessaoCdp:
    """A cara da `SessaoPelaPagina` (`pedir`, `cabecalhos_para`, `fechar`)
    por CDP cru, numa aba própria aberta na fila e registrada na faxina."""

    def __init__(self, acesso: central.Acesso | str = "principal", *,
                 pasta: Path | None = None, aba: AbaCdp | None = None):
        self.aba = aba or AbaCdp(acesso, pasta=pasta)
        self._cab: dict[str, dict[str, str]] = {}
        if not self.aba.alvo:
            self.aba.abrir(ao_carregar=self._capturar)
        else:
            self._capturar(self.aba)

    def _capturar(self, aba: AbaCdp) -> None:
        self._cab = aba.capturar()
        if "authorization" not in self._cab.get(hosts.HOST_LEGACY, {}):
            raise ErpErro("não capturei a autenticação do ERP pela aba nova: o "
                          "Chrome central está logado? (o porteiro ou o app "
                          "precisam ter entrado)")

    def cabecalhos_para(self, url: str, extras: dict | None = None) -> dict:
        h = urllib.parse.urlsplit(url).hostname or ""
        c = dict(self._cab.get(h) or self._cab.get(hosts.HOST_LEGACY) or {})
        c.update(extras or {})
        return c

    def _uma(self, url, metodo, corpo, extras):
        arg = {"url": url, "metodo": metodo, "headers": self.cabecalhos_para(url, extras),
               "corpo": corpo}
        js = f"({_JS_FETCH})({json.dumps(arg, ensure_ascii=False, default=str)})"
        for tentativa in range(TENTATIVAS_GET if metodo == "GET" else 1):
            try:
                return self.aba.avaliar(js)
            except RuntimeError as e:
                if (metodo != "GET" or "Failed to fetch" not in str(e)
                        or tentativa == TENTATIVAS_GET - 1):
                    raise
                time.sleep(ESPERA_TENTATIVA)

    def pedir(self, url: str, *, metodo: str = "GET", corpo=None,
              extras: dict | None = None, idempotente: bool = False):
        """Os dados da resposta. 401 num GET (ou num pedido marcado
        `idempotente`) recaptura e repete UMA vez; nos outros, sobe — um POST
        que criou algo e perdeu a resposta duplicaria (ver `erp.sessao`)."""
        metodo = metodo.upper()
        r = self._uma(url, metodo, corpo, extras)
        if r["status"] == 401 and (metodo == "GET" or idempotente):
            self._capturar(self.aba)
            r = self._uma(url, metodo, corpo, extras)
        if r["status"] >= 400:
            raise ErpErro(f"o ERP respondeu {r['status']}: {str(r['dados'])[:300]}",
                          codigo=r["status"])
        return r["dados"]

    def fechar(self) -> None:
        self.aba.fechar()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.fechar()
        return False


def _fechar_no_fim(aba: AbaCdp) -> None:
    """Fecha a aba no começo da saída do programa (mesmo truque da
    `SessaoPelaPagina._fechar_no_fim`: o `atexit` comum chega tarde)."""
    import weakref
    ref = weakref.ref(aba)

    def _fechar():
        a = ref()
        if a is not None:
            a.fechar()
    with contextlib.suppress(Exception):
        threading._register_atexit(_fechar)
