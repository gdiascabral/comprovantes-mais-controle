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
URL_FLUXO = URL_BASE + "/#/cash-flow"
SEL_VISUALIZAR = 'button:has-text("Visualizar Extrato")'
SEL_MULTISELECT = 'ng-multiple-select[ng-model="selectedAccounts"]'

PRAZO_TELA = 60_000
PRAZO_MODAL = 90_000


# --------------------------------------------------------------- lista de contas

# A lista sai do PRÓPRIO fluxo de caixa, não da tela de Contas bancárias.
#
# `#/accounts` foi migrada para React/MUI e não tem mais `tr[ng-repeat]`: a
# leitura antiga, que vencia a paginação escrevendo `pageSize` no scope, parou
# de funcionar junto com o HTML que ela raspava. O dropdown "Contas Ativas" do
# fluxo de caixa continua Angular e guarda `allAccounts` no escopo — a lista
# inteira de uma vez, sem paginação, com id, nome, proprietário e situação.
#
# É também a lista que a pessoa vê na tela ao escolher as contas, o que evita a
# divergência de uma origem mostrar uma coisa e o robô processar outra.
_JS_CONTAS = """
() => {
  const el = document.querySelector('ng-multiple-select[ng-model="selectedAccounts"]');
  if (!el) return 'sem-seletor';
  const inicial = angular.element(el).isolateScope() || angular.element(el).scope();
  for (let s = inicial, n = 0; s && n < 6; s = s.$parent, n++) {
    if (Array.isArray(s.allAccounts) && s.allAccounts.length) {
      return s.allAccounts.map(c => ({
        id: c.id, nome: c.name, proprietario: c.owner, ativa: c.status !== false,
      }));
    }
  }
  return 'sem-lista';
}
"""


def listar_contas(page, incluir_inativas: bool = False) -> list[dict]:
    """Todas as contas do fluxo de caixa (id + nome + proprietário + situação)."""
    page.goto(URL_FLUXO, wait_until="domcontentloaded")
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(2500)
    page.wait_for_function("() => typeof angular !== 'undefined'", timeout=PRAZO_TELA)
    page.wait_for_selector(SEL_MULTISELECT, state="attached", timeout=PRAZO_TELA)

    # allAccounts chega por requisição: esperar o seletor existir não basta.
    tem_lista = ("() => { const r = (" + _JS_CONTAS + ")();"
                 " return Array.isArray(r) && r.length > 0; }")
    if not _esperar(page, tem_lista, PRAZO_TELA):
        raise RuntimeError("a lista de contas não carregou a tempo.")

    resultado = page.evaluate(_JS_CONTAS)
    if isinstance(resultado, str):
        raise RuntimeError(f"não consegui ler a lista de contas ({resultado}).")
    itens = resultado
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
    conta: s.accounts || null,
    saldo_final: s.finalbalance,
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


def conferir_antes_de_salvar(estado: dict, conta_esperada: str) -> list[str]:
    """Problemas que impedem salvar o PDF. Vazio significa aprovado.

    Duas checagens, e as duas nasceram de erro real observado:

    - a conta carregada tem de ser a esperada. Um extrato gravado com o nome
      certo dentro da pasta de outra empresa não se denuncia sozinho;
    - a paginação tem de ter terminado. O botão "Carregar mais" fica DEPOIS do
      "Saldo final", então o extrato exibe totais como se estivesse completo
      enquanto ainda faltam lançamentos — o PDF sairia com cara de íntegro.

    Função pura de propósito: é o que permite testá-la sem navegador."""
    problemas = []
    if estado is None:
        return ["não consegui ler o estado do extrato"]

    carregada = estado.get("conta")
    if not carregada:
        problemas.append("o extrato não informa de que conta é")
    elif _chave(carregada) != _chave(conta_esperada):
        problemas.append(
            f"o extrato aberto é de '{carregada}', esperava '{conta_esperada}'")

    if estado.get("tem_mais"):
        problemas.append("a paginação não terminou — faltam lançamentos")
    return problemas


def _chave(texto: str) -> str:
    """Compara nomes de conta sem tropeçar em acento, caixa ou espaço duplo."""
    t = unicodedata.normalize("NFKD", texto or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().split())


def estado(page) -> dict:
    """Situação atual do modal: quantos lançamentos, se há mais, de que conta."""
    return page.evaluate(_JS_ESTADO)


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
