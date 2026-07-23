# -*- coding: utf-8 -*-
"""
Parte 3: automação do Mais Controle com Playwright.

- Abre o Chrome com um perfil salvo (login manual só na 1ª vez).
- Para cada pagamento: abre o lançamento, localiza o sub-pagamento pelo VALOR
  dentro da seção "Histórico de Pagamentos", verifica se já tem comprovante
  (pelo selo do clipe) e, se não tiver, anexa via ⋮ -> Editar pagamento ->
  Arquivos -> tag "Comprovante" -> Confirmar.

Observação-chave: o botão do clipe ("Abrir Arquivos do Pagamento") só existe
quando JÁ há anexo. Por isso ancoramos na seção "Histórico de Pagamentos" e no
menu ⋮ (MoreVertIcon), que existem tanto nos pendentes quanto nos já anexados.
"""
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

try:
    from . import config
except ImportError:
    import config


def _centavos(s) -> int | None:
    """Converte '796,28' / '2.000,00' / 'R$ 7.309,68' / 7309.68 -> centavos int."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return round(float(s) * 100)
    t = str(s)
    for ch in ("R$", " ", " ", "\t"):
        t = t.replace(ch, "")
    t = t.strip()
    if "," in t:                       # BR: ponto = milhar, vírgula = decimal
        t = t.replace(".", "").replace(",", ".")
    try:
        return round(float(t) * 100)
    except ValueError:
        return None


# lista os sub-pagamentos do histórico (valor, nº doc, se já têm anexo).
# Escopo = seção "Histórico de Pagamentos"; linhas = botões ⋮ dentro dela.
_JS_ROWS = r"""
() => {
  const all = [...document.querySelectorAll('*')];
  const head = all.find(e => [...e.childNodes].some(
      n => n.nodeType === 3 && /Histórico de Pagamentos/.test(n.textContent)));
  if (!head) return [];
  let card = head;
  for (let k = 0; k < 6; k++) {
    if (!card.parentElement) break;
    card = card.parentElement;
    if (card.querySelector('svg[data-testid="MoreVertIcon"]')) break;
  }
  const menus = [...card.querySelectorAll('button')]
      .filter(b => b.querySelector('svg[data-testid="MoreVertIcon"]'));
  return menus.map((m, i) => {
    let row = m;
    for (let k = 0; k < 8; k++) {
      if (!row.parentElement) break;
      row = row.parentElement;
      const t = row.innerText || '';
      if (/Doc:|Por:/i.test(t) || /\d[\d.]*,\d{2}/.test(t)) break;
    }
    const clean = (row.innerText || '').replace(/[\s ]+/g, ' ').trim();
    const val = (clean.match(/(\d[\d.]*,\d{2})/) || [])[1] || '';
    const doc = (clean.match(/N[º°o]\s*Doc:\s*([\w-]+)/i) || [])[1] || '';
    const clip = row.querySelector('button[aria-label="Abrir Arquivos do Pagamento"]');
    const badge = clip ? clip.querySelector('.MuiBadge-badge') : null;
    const attached = !!badge
        && !badge.className.includes('MuiBadge-invisible')
        && /\d/.test(badge.textContent || '');
    return { i, val, doc, attached };
  });
}
"""

# abre o menu ⋮ do i-ésimo sub-pagamento (mesmo escopo do histórico)
_JS_OPEN_MENU = r"""
(i) => {
  const all = [...document.querySelectorAll('*')];
  const head = all.find(e => [...e.childNodes].some(
      n => n.nodeType === 3 && /Histórico de Pagamentos/.test(n.textContent)));
  if (!head) return false;
  let card = head;
  for (let k = 0; k < 6; k++) {
    if (!card.parentElement) break;
    card = card.parentElement;
    if (card.querySelector('svg[data-testid="MoreVertIcon"]')) break;
  }
  const menus = [...card.querySelectorAll('button')]
      .filter(b => b.querySelector('svg[data-testid="MoreVertIcon"]'));
  if (!menus[i]) return false;
  menus[i].click();
  return true;
}
"""

_JS_CLICK_MENUITEM = r"""
(label) => {
  const it = [...document.querySelectorAll('[role="menuitem"], .MuiMenuItem-root')]
      .find(m => m.textContent.trim() === label);
  if (!it) return false;
  it.click();
  return true;
}
"""

_JS_SET_TAG = r"""
(tag) => {
  const dlg = document.querySelector('.MuiDialog-container, [role="dialog"]');
  if (!dlg) return 'sem_dialog';
  // abre o menu "Etiquetas": clica no chip de tag do arquivo ("sem tag" ou outro)
  let semtag = [...dlg.querySelectorAll('*')]
      .find(e => e.childNodes.length && e.textContent.trim().toLowerCase() === 'sem tag');
  if (!semtag) {
    // fallback: clica no chip de etiqueta ao lado do arquivo
    const chip = dlg.querySelector('.MuiChip-root');
    if (chip) { chip.click(); return 'clicou_chip'; }
    return 'sem_semtag';
  }
  semtag.click();
  return 'clicou_semtag';
}
"""

# no menu "Etiquetas", cada opção é um div.MuiStack com um input[type=radio] + texto
_JS_PICK_TAG = r"""
(tag) => {
  const rows = [...document.querySelectorAll('div.MuiStack-root')]
      .filter(d => d.querySelector('input[type=radio]'));
  for (const d of rows) {
    if ((d.innerText || '').trim() === tag) {
      const r = d.querySelector('input[type=radio]');
      (r || d).click();
      return true;
    }
  }
  const radios = [...document.querySelectorAll('input[type=radio]')];
  for (const r of radios) {
    let row = r;
    for (let k = 0; k < 5; k++) {
      if (!row.parentElement) break;
      row = row.parentElement;
      const t = (row.innerText || '').trim();
      if (t && t.length < 30) break;
    }
    if ((row.innerText || '').trim() === tag) { r.click(); return true; }
  }
  return false;
}
"""


class MCClient:
    def __init__(self, headless: bool = False):
        self.headless = headless
        self._pw = None
        self.ctx = None
        self.page = None
        self._respostas = []

    @staticmethod
    def _tamanho_tela() -> tuple[int, int] | None:
        """Resolução do monitor, para abrir o Chrome ocupando a tela inteira."""
        try:
            import tkinter
            r = tkinter.Tk()
            r.withdraw()
            w, h = r.winfo_screenwidth(), r.winfo_screenheight()
            r.destroy()
            return (w, h) if w > 100 and h > 100 else None
        except Exception:
            return None

    def __enter__(self):
        self._pw = sync_playwright().start()
        config.PASTA_PERFIL_CHROME.mkdir(parents=True, exist_ok=True)
        args = ["--start-maximized", "--window-position=0,0"]
        tela = self._tamanho_tela()
        if tela:
            args.append(f"--window-size={tela[0]},{tela[1]}")
        self.ctx = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(config.PASTA_PERFIL_CHROME),
            headless=self.headless,
            channel="chrome",
            args=args,
            no_viewport=True,   # a página usa o tamanho real da janela
            accept_downloads=True,
        )
        self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.page.on("response", self._on_response)
        return self

    def __exit__(self, *exc):
        try:
            if self.ctx:
                self.ctx.close()
        finally:
            if self._pw:
                self._pw.stop()

    def _on_response(self, resp):
        u = resp.url
        if "payable" in u or "paginated" in u or "installment" in u:
            try:
                if "application/json" in (resp.headers.get("content-type") or ""):
                    self._respostas.append({"url": u, "json": resp.json()})
            except Exception:
                pass

    # ------------------------------------------------------------- enumeração
    def capturar_pagamentos(self, salvar_inspecao: Path | None = None) -> list[dict]:
        """Coleta pagamentos a partir das respostas de rede da própria página."""
        import json as _json
        self._respostas.clear()
        self.page.goto(config.MC_URL_PAGAMENTOS, wait_until="domcontentloaded")
        self.page.wait_for_timeout(6000)
        if salvar_inspecao:
            salvar_inspecao.write_text(
                _json.dumps(self._respostas, ensure_ascii=False, indent=2),
                encoding="utf-8")
            print(f">>> Respostas de rede salvas em: {salvar_inspecao}")
        return self._normalizar(self._respostas)

    @staticmethod
    def _normalizar(respostas: list[dict]) -> list[dict]:
        out = []
        for r in respostas:
            data = r["json"]
            cands = []
            if isinstance(data, dict):
                for k in ("content", "data", "items", "result", "results", "records"):
                    if isinstance(data.get(k), list):
                        cands = data[k]; break
            elif isinstance(data, list):
                cands = data
            for it in cands:
                if not isinstance(it, dict):
                    continue
                lid = it.get("id") or it.get("launchId") or it.get("payableId")
                val = it.get("value") or it.get("amount") or it.get("paidValue")
                if lid is None or val is None:
                    continue
                out.append({
                    "launchId": str(lid), "valor": val,
                    "descricao": it.get("description") or it.get("historic") or "",
                    "doc": str(it.get("documentNumber") or it.get("document") or ""),
                    "raw": it,
                })
        return out

    # ------------------------------------------------------------------ login
    def garantir_login(self):
        self.page.goto(config.MC_URL_PAGAMENTOS, wait_until="domcontentloaded")
        print("\n>>> Se aparecer a tela de login, faça o login nesta janela do Chrome.")
        print(">>> Aguardando a área logada (até 30 segundos)...")
        for _ in range(30):
            try:
                if "login" not in self.page.url and self.page.locator(
                        "text=Pagamentos").first.is_visible():
                    print(">>> Login OK.\n")
                    return True
            except Exception:
                pass
            time.sleep(1)
        print("[!] Não detectei a área logada; continuo mesmo assim.")
        return False

    # ------------------------------------------------------------------ anexo
    def anexar(self, launch_id: str, valor_str: str, pdf_path: Path,
               doc: str | None = None, dry_run: bool = True,
               valores: list | None = None) -> str:
        """
        Retorna: 'anexado' | 'anexado_sem_tag' | 'ja_tinha' | 'nao_encontrado'
                 | 'ambiguo' | 'dry_run' | 'erro:...'
        valores: lista opcional de valores aceitos (nominal e valor pago com
        juros/multa/desconto); sem ela, usa apenas valor_str.
        """
        alvos = {a for a in (_centavos(v) for v in (valores or [valor_str]))
                 if a is not None}
        url = f"{config.MC_URL_BASE}/#/payable-installments/{launch_id}"
        try:
            self.page.goto(url, wait_until="domcontentloaded")
            self.page.wait_for_selector("text=Histórico de Pagamentos", timeout=20000)
            self.page.wait_for_timeout(1500)

            rows = self.page.evaluate(_JS_ROWS)
            cands = [r for r in rows if _centavos(r["val"]) in alvos]
            if doc:
                doc = str(doc).strip()
                refinado = [r for r in cands if r["doc"] and doc in r["doc"]]
                if refinado:
                    cands = refinado
            if not cands:
                return "nao_encontrado"
            pendentes = [r for r in cands if not r["attached"]]
            if not pendentes:
                return "ja_tinha"
            if len(pendentes) > 1:
                return "ambiguo"
            alvo_row = pendentes[0]

            if dry_run:
                return "dry_run"

            # abre ⋮ -> Editar pagamento
            if not self.page.evaluate(_JS_OPEN_MENU, alvo_row["i"]):
                return "erro:menu"
            self.page.wait_for_timeout(500)
            if not self.page.evaluate(_JS_CLICK_MENUITEM, "Editar pagamento"):
                return "erro:sem_editar_pagamento"

            self.page.wait_for_selector("text=Editar Pagamento", timeout=10000)
            self.page.wait_for_selector("text=Arquivos", timeout=10000)

            inp = self.page.wait_for_selector(
                "input[type=file]", timeout=8000, state="attached")
            inp.set_input_files(str(pdf_path))
            self.page.wait_for_timeout(3000)

            tag_ok = self._definir_tag(config.TAG_COMPROVANTE)

            self.page.get_by_role("button", name="Confirmar pagamento").first.click()
            self.page.wait_for_timeout(2500)
            return "anexado" if tag_ok else "anexado_sem_tag"

        except PWTimeout:
            self._print_erro("timeout", launch_id)
            return "erro:timeout"
        except Exception as e:
            self._print_erro(str(e)[:100], launch_id)
            return f"erro:{str(e)[:100]}"

    # --------------------------------------------------------------- tag
    def _definir_tag(self, tag: str) -> bool:
        # 1) abre o menu "Etiquetas"
        res = self.page.evaluate(_JS_SET_TAG, tag)
        self.page.wait_for_timeout(900)
        # 2) marca o rádio da linha "Comprovante"
        ok = False
        try:
            ok = bool(self.page.evaluate(_JS_PICK_TAG, tag))
        except Exception:
            ok = False
        if ok:
            self.page.wait_for_timeout(600)
            return True
        # 3) não conseguiu -> salva print para diagnóstico
        try:
            shot = config.ARQUIVO_LOG.parent / "tag_debug.png"
            self.page.screenshot(path=str(shot))
            print(f"   [aviso] não marquei a tag (res={res}); print em {shot}")
        except Exception:
            pass
        return False

    def _print_erro(self, motivo: str, launch_id: str):
        try:
            shot = config.ARQUIVO_LOG.parent / f"erro_{launch_id[:8]}.png"
            self.page.screenshot(path=str(shot))
            print(f"   [erro: {motivo}] print salvo em {shot}")
        except Exception:
            pass
