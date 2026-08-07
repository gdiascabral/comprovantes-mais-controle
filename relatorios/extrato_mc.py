# -*- coding: utf-8 -*-
"""
Extrato do fluxo de caixa por conta bancária, salvo em PDF.

Tudo aqui roda sobre a página JÁ LOGADA do MCClient (a mesma do Anexar) e,
portanto, SEMPRE na thread dona do navegador.

O caminho na mão seria: Contas bancárias → clicar na conta → Extrato → mudar
as datas → Visualizar Extrato → "carregar mais" até o fim → Imprimir. Cada um
desses passos tem uma armadilha, resolvida abaixo:

- a lista de contas é paginada (10 por vez) e o `pageSize` precisa ser escrito
  no scope DONO da propriedade — o scope que sai de `angular.element(tr)` é o
  filho do ng-repeat e a escrita vira sombra (herança prototípica do AngularJS);
- não é preciso clicar conta por conta: o botão Extrato chama
  `stateGoNewTab('base.cashFlow')`, então dá para ir direto a
  `#/cash-flow?accountId=...`;
- as datas moram em `fromDate`/`toDate` (objetos moment) do controller, não nos
  inputs — escrever no DOM não propaga;
- o "carregar mais" tem fim conhecido: `pageInfo.hasNextPage` do modal;
- "Imprimir" só chama `window.print()`; neutralizamos o diálogo e geramos o PDF
  pelo CDP (`Page.printToPDF`), que funciona com o Chrome visível.
"""
from __future__ import annotations

import base64
import re
import unicodedata
from pathlib import Path

URL_BASE = "https://acessar.maiscontroleerp.com.br"
URL_CONTAS = URL_BASE + "/#/accounts"
SEL_LINHAS = "tr[ng-repeat]"
SEL_VISUALIZAR = 'button:has-text("Visualizar Extrato")'

PRAZO_TELA = 60_000
PRAZO_MODAL = 90_000


# --------------------------------------------------------------- lista de contas

# Percorre a paginação da tela de Contas bancárias. Ver a nota do módulo sobre
# hasOwnProperty: sem isso só vêm as 10 primeiras.
_JS_CONTAS = """
async () => {
  const tr = document.querySelector('tr[ng-repeat]');
  if (!tr) return 'sem-linhas';
  let alvo = null;
  for (let s = angular.element(tr).scope(); s; s = s.$parent) {
    if (Object.prototype.hasOwnProperty.call(s, 'load') &&
        Object.prototype.hasOwnProperty.call(s, 'pageSize') && s.page) { alvo = s; break; }
  }
  if (!alvo) return 'sem-scope';

  const raiz = alvo.$root || alvo;
  const aplicar = (f) => { if (raiz.$$phase) f(); else raiz.$apply(f); };
  const extrair = () => alvo.page.items.map(c => ({
    id: c.id, nome: c.name, proprietario: c.owner, ativa: c.isActive,
  }));

  const esperado = alvo.page.totalElements || 0;
  const porId = new Map();
  for (const item of extrair()) porId.set(item.id, item);

  aplicar(() => { alvo.pageSize = Math.max(esperado, 50) + 10; alvo.currentPage = 1; alvo.load(); });
  let limite = Date.now() + 20000;
  while (Date.now() < limite && alvo.page.items.length < esperado) {
    await new Promise(r => setTimeout(r, 250));
  }
  for (const item of extrair()) porId.set(item.id, item);

  if (porId.size < esperado) {           // servidor limitou: vai de página em página
    aplicar(() => { alvo.pageSize = 10; alvo.currentPage = 1; alvo.load(); });
    await new Promise(r => setTimeout(r, 1500));
    const paginas = alvo.page.totalPages || 1;
    for (let p = 2; p <= paginas; p++) {
      const antes = (alvo.page.items[0] || {}).id;
      aplicar(() => { alvo.currentPage = p; alvo.load(); });
      limite = Date.now() + 20000;
      while (Date.now() < limite && (alvo.page.items[0] || {}).id === antes) {
        await new Promise(r => setTimeout(r, 250));
      }
      for (const item of extrair()) porId.set(item.id, item);
    }
  }
  return {total: esperado, itens: [...porId.values()]};
}
"""


def listar_contas(page, incluir_inativas: bool = False) -> list[dict]:
    """Todas as contas bancárias (id + nome), vencendo a paginação da tela."""
    page.goto(URL_CONTAS, wait_until="domcontentloaded")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    page.wait_for_function("() => typeof angular !== 'undefined'", timeout=PRAZO_TELA)
    page.wait_for_selector(SEL_LINHAS, state="attached", timeout=PRAZO_TELA)
    page.wait_for_timeout(1200)

    resultado = page.evaluate(_JS_CONTAS)
    if isinstance(resultado, str):
        raise RuntimeError(f"não consegui ler a lista de contas ({resultado}).")
    itens = resultado["itens"]
    if not incluir_inativas:
        itens = [c for c in itens if c.get("ativa") is not False]
    return sorted(itens, key=lambda c: (c["nome"] or "").lower())


# ------------------------------------------------------------------- extrato

_JS_CTRL_CASHFLOW = """
() => {
  const btn = Array.from(document.querySelectorAll('button'))
    .find(b => /Visualizar Extrato/i.test(b.innerText || ''));
  if (!btn) return 'sem-botao';
  for (let s = angular.element(btn).scope(); s; s = s.$parent) {
    if (typeof s.getStatements === 'function') { window.__cf = s; return 'ok'; }
  }
  return 'sem-scope';
}
"""

# fromDate/toDate são moment: clonamos o que já existe em vez de depender de um
# moment global.
_JS_PERIODO = """
([ini, fim]) => {
  const s = window.__cf;
  const mk = (txt) => {
    const [d, m, a] = txt.split('/').map(Number);
    const c = s.fromDate.clone();
    c.year(a); c.month(m - 1); c.date(d);
    c.hour(0); c.minute(0); c.second(0); c.millisecond(0);
    return c;
  };
  const raiz = s.$root || s;
  const aplicar = () => s.onChangeDateInterval({startDate: mk(ini), endDate: mk(fim)});
  if (raiz.$$phase) aplicar(); else raiz.$apply(aplicar);
  return {de: s.fromDate.format('DD/MM/YYYY'), ate: s.toDate.format('DD/MM/YYYY')};
}
"""

_JS_VISUALIZAR = """
() => {
  const s = window.__cf, raiz = s.$root || s;
  if (raiz.$$phase) s.getStatements(); else raiz.$apply(() => s.getStatements());
}
"""

_JS_CTRL_MODAL = """
() => {
  const ancora =
    Array.from(document.querySelectorAll('[ng-click]'))
      .find(b => /loadMore|printLandscapeMode/.test(b.getAttribute('ng-click') || ''))
    || document.querySelector('#table-id')
    || document.querySelector('.l-statement-table');
  if (!ancora) return 'sem-ancora';
  for (let s = angular.element(ancora).scope(); s; s = s.$parent) {
    if (s.$ctrl && typeof s.$ctrl.loadMore === 'function') {
      window.__ext = s.$ctrl; window.__extScope = s; return 'ok';
    }
  }
  return 'sem-ctrl';
}
"""

_JS_ESTADO = """
() => {
  const c = window.__ext;
  if (!c) return null;
  const s = c.summary || {};
  return {
    transacoes: (s.statementTransactions || []).length,
    tem_mais: !!(c.pageInfo && c.pageInfo.hasNextPage),
    carregando: !!c.loading,
  };
}
"""

_JS_LOAD_MORE = """
() => {
  const c = window.__ext, s = window.__extScope, r = s.$root || s;
  if (r.$$phase) c.loadMore(); else r.$apply(() => c.loadMore());
}
"""

_JS_PREPARAR_IMPRESSAO = """
() => {
  window.print = () => {};                     // sem a janela de impressão
  const c = window.__ext, s = window.__extScope, r = s.$root || s;
  const f = () => c.printLandscapeMode('table-id', '11px');
  if (r.$$phase) f(); else r.$apply(f);
}
"""

# O CSS de impressão do ERP esconde a barra de botões, mas não a tela de fluxo
# de caixa atrás do modal — ela vazava para o PDF. Promover o modal a único
# filho do body resolve e mantém o CSS do app. (visibility:hidden +
# position:absolute não serve: zera a paginação e sai PDF em branco.)
_CSS_IMPRESSAO = """
.no-print { display: none !important; }
.cash-flow-modal-print {
  position: static !important;
  width: 100% !important; max-width: none !important;
  height: auto !important; max-height: none !important;
  margin: 0 !important; box-shadow: none !important; overflow: visible !important;
}
.modal-body, .modal-report { overflow: visible !important; max-height: none !important; }
body { background: #fff !important; }
"""

_JS_ISOLAR = """
(css) => {
  const modal = document.querySelector('.cash-flow-modal-print');
  if (!modal) return 'sem-modal';
  const tag = document.createElement('style');
  tag.textContent = css;
  document.body.replaceChildren(modal);
  document.head.appendChild(tag);
  return 'ok';
}
"""


def _esperar(page, condicao_js: str, prazo_ms: int = 60_000) -> bool:
    passo = 500
    for _ in range(max(1, prazo_ms // passo)):
        try:
            if page.evaluate(condicao_js):
                return True
        except Exception:
            pass
        page.wait_for_timeout(passo)
    return False


def abrir_extrato(page, conta_id: str, inicio: str, fim: str) -> None:
    """Deixa o modal do extrato aberto, com o período aplicado (dd/mm/aaaa).

    O reload não é desperdício: gerar o PDF promove o modal a único filho do
    body e deixa o SPA quebrado — trocar só o hash não reconstrói nada, e a
    conta seguinte ficaria esperando para sempre pelo botão Visualizar.
    """
    page.goto(f"{URL_BASE}/#/cash-flow?accountId={conta_id}",
              wait_until="domcontentloaded")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(3500)
    page.wait_for_selector(SEL_VISUALIZAR, timeout=PRAZO_MODAL)
    page.wait_for_timeout(1500)

    if page.evaluate(_JS_CTRL_CASHFLOW) != "ok":
        raise RuntimeError("não achei o controller do fluxo de caixa.")
    page.evaluate(_JS_PERIODO, [inicio, fim])
    page.wait_for_timeout(3500)          # o filtro dispara recarga do fluxo

    page.evaluate(_JS_VISUALIZAR)
    page.wait_for_selector("#table-id", state="attached", timeout=PRAZO_MODAL)
    page.wait_for_timeout(2500)
    if page.evaluate(_JS_CTRL_MODAL) != "ok":
        raise RuntimeError("o modal do extrato não abriu.")
    _esperar(page, "() => window.__ext && !window.__ext.loading")


def carregar_tudo(page, limite: int = 300, parar=None) -> int:
    """Equivale a clicar "carregar mais" até o fim. Devolve o nº de lançamentos."""
    for _ in range(limite):
        _esperar(page, "() => window.__ext && !window.__ext.loading")
        estado = page.evaluate(_JS_ESTADO)
        if not estado["tem_mais"] or (parar and parar()):
            return estado["transacoes"]
        antes = estado["transacoes"]
        page.evaluate(_JS_LOAD_MORE)
        page.wait_for_timeout(1200)
        _esperar(page, "() => window.__ext && !window.__ext.loading")
        if page.evaluate(_JS_ESTADO)["transacoes"] == antes:
            break                        # parou de crescer: não insiste
    return page.evaluate(_JS_ESTADO)["transacoes"]


def salvar_pdf(page, destino: Path, escala: float = 0.8) -> Path:
    """Aplica o layout de impressão do ERP e grava o PDF pelo CDP.

    page.pdf() do Playwright recusa navegador com janela; o CDP cru aceita.
    """
    page.evaluate(_JS_PREPARAR_IMPRESSAO)
    page.wait_for_timeout(2500)
    if page.evaluate(_JS_ISOLAR, _CSS_IMPRESSAO) != "ok":
        raise RuntimeError("não achei o modal para isolar na impressão.")
    page.wait_for_timeout(800)

    sessao = page.context.new_cdp_session(page)
    resposta = sessao.send("Page.printToPDF", {
        "landscape": True,
        "printBackground": True,
        "scale": escala,
        "paperWidth": 11.69, "paperHeight": 8.27,      # A4 deitado
        "marginTop": 0.3, "marginBottom": 0.3,
        "marginLeft": 0.3, "marginRight": 0.3,
    })
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(base64.b64decode(resposta["data"]))
    return destino


def nome_de_arquivo(texto: str, limite: int = 90) -> str:
    """Nome de arquivo seguro no Windows, ainda legível."""
    texto = unicodedata.normalize("NFC", texto or "").strip()
    texto = re.sub(r'[\\/:*?"<>|]+', "-", texto)
    texto = re.sub(r"\s+", " ", texto).strip(" .-")
    return texto[:limite] or "conta"


def restaurar_pagina(page) -> None:
    """Devolve o navegador a um estado usável pelas outras abas.

    Depois de imprimir, o body é só o modal: sem isto, a aba Anexar ou a
    Conferência encontrariam uma página sem app nenhum.
    """
    try:
        page.goto(URL_CONTAS, wait_until="domcontentloaded")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_timeout(1500)
    except Exception:
        pass
