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
    from . import config, credenciais
except ImportError:
    import config, credenciais


class SemRede(RuntimeError):
    """Rede/DNS fora do ar. A mensagem já vem pronta para o usuário — quem
    captura deve mostrar só o texto, sem traceback (não é bug do app)."""


# erros do Chrome que significam "problema de rede", não de automação
_ERROS_DE_REDE = ("ERR_NAME_NOT_RESOLVED", "ERR_INTERNET_DISCONNECTED",
                  "ERR_CONNECTION_", "ERR_TIMED_OUT", "ERR_NETWORK_CHANGED",
                  "ERR_PROXY_CONNECTION_FAILED", "ERR_ADDRESS_UNREACHABLE")


def _eh_erro_de_rede(e) -> bool:
    return any(c in str(e) for c in _ERROS_DE_REDE)


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


# ------------------------------------------------------- seletores do ERP
# Textos/âncoras da tela de Pagamentos do Mais Controle. Se o ERP mudar
# rótulos ou estrutura, é AQUI que se ajusta — é o ponto mais provável de
# quebra do app.
TXT_HISTORICO = "Histórico de Pagamentos"   # seção que ancora as linhas
TXT_LOGADO = "Pagamentos"                   # (histórico: ver SINAIS_DE_LOGIN)

# Sinais de que a tela de LOGIN está à vista. A sessão é detectada pela
# AUSÊNCIA deles, não pela presença de algo da área logada.
#
# Procurar um sinal positivo (o TXT_LOGADO acima) parece natural e não
# funciona aqui: o ERP é single-spa, com AngularJS na tela de login e React no
# resto, e migra tela por tela — o texto muda de lugar e a detecção cega.
# Aconteceu em 10/08/2026, com o painel aberto na tela e o app insistindo que
# não havia sessão. A tela de login, essa, é estável.
#
# Regra herdada do projeto da Conciliação Diária, onde roda há meses.
SINAIS_DE_LOGIN = (
    'input[type="password"]',
    "text=Entre na sua conta",
    "text=não tem permissão",            # aparece enquanto o token não volta
)
MENU_EDITAR = "Editar pagamento"            # item do menu ⋮
TXT_DIALOGO_EDITAR = "Editar Pagamento"     # título do diálogo de edição
TXT_ARQUIVOS = "Arquivos"                   # seção de anexos no diálogo
BTN_CONFIRMAR = "Confirmar pagamento"       # botão que salva o anexo
# Âncoras de DOM usadas DENTRO dos blocos JS abaixo (aqui só para referência;
# se mudarem, editar nos respectivos _JS_*):
#   svg[data-testid="MoreVertIcon"]                  menu ⋮ de cada sub-pagamento
#   button[aria-label="Abrir Arquivos do Pagamento"] clipe (só existe se há anexo)
#   [role="menuitem"] / .MuiMenuItem-root            itens de menu
#   [role="dialog"] / .MuiDialog-container           diálogo
#   .MuiStack-root + input[type=radio]               opções de etiqueta


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


# preenche e-mail + senha (setter nativo: dispara input/change p/ Angular/React)
_JS_FILL_LOGIN = r"""
({ email, senha }) => {
  const vis = el => el && el.offsetParent !== null && !el.disabled;
  const set = (el, val) => {
    const proto = el.tagName === 'INPUT'
        ? window.HTMLInputElement.prototype : window.HTMLTextAreaElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
    setter.call(el, val);
    el.dispatchEvent(new Event('input', { bubbles: true }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
  };
  const inputs = [...document.querySelectorAll('input')].filter(vis);
  const pw = inputs.find(i => i.type === 'password');
  let em = inputs.find(i => i.type === 'email');
  if (!em) em = inputs.find(i => (i.type === 'text' || !i.type) && i !== pw);
  if (em) set(em, email);
  if (pw) set(pw, senha);
  return { email: !!em, senha: !!pw };
}
"""

# Login pelo controller do AngularJS, não pela UI.
#
# POR QUE NÃO BASTA PREENCHER E CLICAR: a tela de login é AngularJS. Escrever
# no input (mesmo com o setter nativo e disparando input/change, como faz o
# _JS_FILL_LOGIN) altera o DOM mas não garante a propagação para o ng-model,
# então `$ctrl.credentials` continua vazio. E o botão ENTRAR fica habilitado
# assim mesmo, porque o ng-disabled aceita `$ctrl.getAutoFill()` como
# alternativa — o clique chama login() com credencial vazia e falha em
# SILÊNCIO: sem requisição de rede e sem mensagem na tela. Escrever direto no
# scope e chamar login() fecha esse buraco.
_JS_LOGIN_ANGULAR = r"""
(dados) => {
  if (typeof angular === 'undefined') return {ok: false, motivo: 'AngularJS ausente'};
  const campo = document.querySelector('#username')
             || document.querySelector('#userpassword')
             || document.querySelector('input[type=password]');
  if (!campo) return {ok: false, motivo: 'campos de login não encontrados'};
  let escopo = null;
  try { escopo = angular.element(campo).scope(); } catch (e) {
    return {ok: false, motivo: 'scope inacessível: ' + e.message};
  }
  while (escopo && !escopo.$ctrl) escopo = escopo.$parent;
  if (!escopo || !escopo.$ctrl || typeof escopo.$ctrl.login !== 'function') {
    return {ok: false, motivo: 'controller de login não encontrado'};
  }
  const ctrl = escopo.$ctrl;
  escopo.$apply(() => {
    ctrl.credentials = ctrl.credentials || {};
    ctrl.credentials.username = dados.email;
    ctrl.credentials.password = dados.senha;
  });
  if (!ctrl.credentials.username || !ctrl.credentials.password) {
    return {ok: false, motivo: 'não consegui gravar as credenciais no scope'};
  }
  try { ctrl.login(); } catch (e) {
    return {ok: false, motivo: 'login() lançou: ' + e.message};
  }
  return {ok: true};
}
"""

# clica no botão ENTRAR (fallback, quando os seletores do Playwright não pegam)
_JS_CLICK_ENTRAR = r"""
() => {
  const b = [...document.querySelectorAll('button, input[type=submit]')]
      .find(e => /entrar/i.test((e.textContent || e.value || '')));
  if (b) { b.click(); return true; }
  return false;
}
"""


class MCClient:
    def __init__(self, headless: bool = False, log=print):
        self.headless = headless
        # sem o log da janela estas mensagens iam para o stdout — que no exe
        # (--noconsole) não existe, e o usuário nunca soube por que o login
        # automático não pegou
        self.log = log
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
            chromium_sandbox=True,   # mantém o sandbox (some o aviso "--no-sandbox")
            no_viewport=True,        # a página usa o tamanho real da janela
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
        self._ir_para(config.MC_URL_PAGAMENTOS)
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
    def _esta_logado(self) -> bool:
        """Estamos dentro do ERP?

        Procurar um texto da área logada (`TXT_LOGADO`) era o único teste, e
        ele falhou em 10/08/2026 com o usuário JÁ no painel: o `.first` pega a
        primeira ocorrência do texto no DOM, que pode ser um elemento oculto,
        e o ERP está migrando de AngularJS para React tela por tela — o texto
        muda de lugar sem aviso.

        Agora o texto é só um dos sinais. O que sustenta a resposta é o par
        "estou numa URL do ERP que não é a de login" + "não há campo de senha
        na tela", que não depende de layout.
        """
        return self._aba_logada() is not None

    def _aba_logada(self):
        """A aba onde o ERP está aberto e logado, ou None.

        A regra é a do projeto da Conciliação, que roda há meses sem tropeçar
        nisto: em vez de procurar um sinal de que ESTÁ logado, procura sinais
        de que NÃO está (ver `_SINAIS_DE_LOGIN`). Não achando nenhum, está
        logado.

        A diferença importa porque o ERP é single-spa com dois front-ends
        convivendo — AngularJS na tela de login, React no resto — e vem sendo
        migrado tela por tela. Um sinal positivo (o texto "Pagamentos", que
        este cliente usava) muda de lugar a cada redesenho e cega a detecção;
        a tela de login é estável.

        Olha TODAS as abas, não só `self.page`: o ERP abre aba nova em vários
        fluxos (`stateGoNewTab`) e o cliente nasce preso em `ctx.pages[0]`.
        Quando encontra, ADOTA a aba — é nela que o trabalho continua.
        """
        try:
            abas = list(self.ctx.pages) if self.ctx else []
        except Exception:
            abas = []
        if self.page is not None and self.page not in abas:
            abas.insert(0, self.page)

        for aba in abas:
            try:
                if "maiscontroleerp" not in (aba.url or ""):
                    continue
                if self._tem_sinal_de_login(aba):
                    continue
                self.page = aba
                return aba
            except Exception:
                continue
        return None

    @staticmethod
    def _tem_sinal_de_login(aba) -> bool:
        """A tela de login está à vista nesta aba?"""
        for seletor in SINAIS_DE_LOGIN:
            try:
                if aba.locator(seletor).first.is_visible(timeout=1200):
                    return True
            except Exception:
                continue
        return False

    def _diagnostico_sessao(self) -> str:
        """O estado real das abas, para o log quando a detecção falha.

        Sem isto, "não detectei a área logada" com o painel aberto na tela é
        um beco sem saída: não dá para saber se foi a URL, o campo de senha ou
        a aba errada."""
        partes = []
        try:
            for i, aba in enumerate(self.ctx.pages):
                url = (aba.url or "")[:70]
                try:
                    senha = self._tem_campo_senha(aba)
                except Exception:
                    senha = "?"
                partes.append(f"aba{i}: {url} (campo de senha: {senha})")
        except Exception as e:
            partes.append(f"não consegui listar as abas: {e}")
        return "; ".join(partes) or "nenhuma aba aberta"

    def _ir_para(self, url: str, tentativas: int = 3):
        """Navega tolerando queda momentânea de rede/DNS.

        Uma oscilação de segundos derrubava a etapa inteira com um traceback
        de Playwright na tela — que não diz nada a quem usa o app."""
        for k in range(tentativas):
            try:
                self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
                return
            except Exception as e:
                if not _eh_erro_de_rede(e):
                    raise
                if k + 1 >= tentativas:
                    raise SemRede(
                        "não consegui acessar o Mais Controle: o computador "
                        "está sem internet ou o endereço não respondeu "
                        f"({tentativas} tentativas). Verifique a conexão (e a "
                        "VPN, se usar) e tente de novo.") from e
                self.log(f"Rede não respondeu; tentando de novo "
                         f"({k + 2}/{tentativas})...")
                time.sleep(3)

    def garantir_login(self):
        """Garante a área logada. Se cair na tela de login: usa a credencial
        salva (opcional, botão 🔑) OU deixa o Chrome autopreencher a senha
        guardada por ele, e clica em ENTRAR sozinho — aguardando a tela mudar.
        Se nada disso resolver (1ª vez), o usuário loga na própria janela do
        Chrome (que então oferece salvar a senha)."""
        self._ir_para(config.MC_URL_PAGAMENTOS)
        self.page.wait_for_timeout(1500)
        if self._esta_logado():
            self.log("Login OK (sessão ainda aberta).")
            return True
        self._tentar_entrar()
        # Espera única e tolerante. O ERP usa Firebase Auth, e o token volta do
        # IndexedDB de forma ASSÍNCRONA: nos primeiros segundos ele mostra a
        # tela de login — às vezes com "você não tem permissão" — mesmo com a
        # sessão perfeitamente válida. Desistir na primeira olhada é o erro
        # clássico aqui, e o Chrome ainda pode completar o login sozinho com a
        # senha que ele guarda.
        for _ in range(90):
            if self._esta_logado():
                self.log("Login OK.")
                return True
            time.sleep(1)
        self.log("[!] Não detectei a área logada. Entre na janela do Chrome "
                 "— depois o app segue sozinho.")
        self.log(f"    {self._diagnostico_sessao()}")
        return False

    def _tentar_entrar(self):
        """Preenche (credencial salva) ou deixa o Chrome autopreencher, e clica
        em ENTRAR. Nunca levanta exceção — na dúvida, login manual."""
        try:
            if "login" not in self.page.url:
                return
            try:
                self.page.wait_for_selector("input[type=password]", timeout=8000)
            except Exception:
                pass
            creds = credenciais.carregar()
            if creds:
                # 1º pelo controller do Angular (é o caminho que funciona);
                # se o ERP mudar e o scope não estiver lá, cai no DOM + clique
                if not self._login_pelo_controller(*creds):
                    self._preencher(*creds)
                    self._clicar_entrar()
            else:
                self.page.wait_for_timeout(2500)   # deixa o Chrome autopreencher
                self._clicar_entrar()
            # Aqui NÃO se conclui nada nem se avisa nada.
            #
            # Este é só o empurrão inicial: preencher e clicar. Quem decide se
            # entrou é o `garantir_login`, que espera bem mais — e é lá que o
            # aviso sai, uma vez só.
            #
            # Antes, este trecho esperava 25s e já anunciava "não consegui
            # entrar com o login salvo". Como o Chrome costuma completar o
            # login sozinho depois disso (senha guardada no próprio
            # navegador), o recado saía à toa em execução que dava certo — e
            # ainda sugeria mexer numa senha que estava correta.
            #
            # Também não se apaga mais a credencial por conta própria: em
            # 10/08/2026 o login funcionou, o painel abriu, e mesmo assim ela
            # foi descartada porque a espera acabou no meio do carregamento.
            # Isso derrubou junto a leitura de saldos da Conciliação, que usa
            # a mesma senha. Falso negativo aqui custa caro; senha de fato
            # errada custa barato (erro claro na tentativa seguinte). Remover
            # é decisão de quem sabe se trocou a senha — o botão Login tem
            # "Remover".
        except Exception as e:
            self.log(f">>> login automático: {str(e)[:120]}")

    def _tem_campo_senha(self, aba=None) -> bool:
        alvo = aba if aba is not None else self.page
        try:
            return alvo.locator("input[type=password]").first.is_visible(
                timeout=1500)
        except Exception:
            return False

    def _login_pelo_controller(self, email: str, senha: str) -> bool:
        """Grava as credenciais no scope do AngularJS e chama login().
        True se conseguiu disparar o login; False para tentar pela UI."""
        try:
            self.page.fill("#username", email, timeout=3000)
            self.page.fill("#userpassword", senha, timeout=3000)
        except Exception:
            pass            # a tela é secundária: o que vale é o scope abaixo
        try:
            r = self.page.evaluate(_JS_LOGIN_ANGULAR,
                                   {"email": email, "senha": senha})
        except Exception as e:
            config.diag(f"login pelo controller falhou: {e!r}")
            return False
        if isinstance(r, dict) and r.get("ok"):
            return True
        motivo = r.get("motivo") if isinstance(r, dict) else r
        config.diag(f"login pelo controller não rodou: {motivo}")
        return False

    def _preencher(self, email: str, senha: str):
        try:
            self.page.evaluate(_JS_FILL_LOGIN, {"email": email, "senha": senha})
        except Exception as e:
            config.diag(f"preenchimento do login falhou: {e!r}")

    def _clicar_entrar(self):
        for tentativa in (
                lambda: self.page.get_by_role("button", name="ENTRAR").first.click(timeout=4000),
                lambda: self.page.locator("button:has-text('ENTRAR')").first.click(timeout=4000),
                lambda: self.page.evaluate(_JS_CLICK_ENTRAR),
                lambda: self.page.locator("input[type=password]").first.press("Enter")):
            try:
                if tentativa() is not False:
                    return
            except Exception:
                pass

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
            self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
            # o ERP fica lento em lotes grandes; espera generosa
            self.page.wait_for_selector(f"text={TXT_HISTORICO}", timeout=45000)
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
            if not self.page.evaluate(_JS_CLICK_MENUITEM, MENU_EDITAR):
                return "erro:sem_editar_pagamento"

            self.page.wait_for_selector(f"text={TXT_DIALOGO_EDITAR}", timeout=10000)
            self.page.wait_for_selector(f"text={TXT_ARQUIVOS}", timeout=10000)

            inp = self.page.wait_for_selector(
                "input[type=file]", timeout=8000, state="attached")
            inp.set_input_files(str(pdf_path))
            self.page.wait_for_timeout(3000)

            tag_ok = self._definir_tag(config.TAG_COMPROVANTE)

            self.page.get_by_role("button", name=BTN_CONFIRMAR).first.click()
            self.page.wait_for_timeout(2500)
            return "anexado" if tag_ok else "anexado_sem_tag"

        except PWTimeout:
            self._print_erro("timeout", launch_id)
            return "erro:timeout"
        except Exception as e:
            self._print_erro(str(e)[:100], launch_id)
            return f"erro:{str(e)[:100]}"

    def resetar(self):
        """Volta para a tela de Pagamentos (recupera o ERP após timeout)."""
        try:
            self.page.goto(config.MC_URL_PAGAMENTOS,
                           wait_until="domcontentloaded", timeout=60000)
            self.page.wait_for_timeout(2500)
        except Exception as e:
            # é recuperação de melhor esforço: segue mesmo falhando, mas o
            # motivo fica registrado — senão o erro seguinte parece sem causa
            config.diag(f"resetar() não conseguiu voltar para Pagamentos: {e!r}")

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
            self.log(f"   [aviso] não marquei a tag (res={res}); print em {shot}")
        except Exception as e:
            config.diag(f"não consegui salvar o print da tag: {e!r}")
        return False

    def _print_erro(self, motivo: str, launch_id: str):
        try:
            shot = config.ARQUIVO_LOG.parent / f"erro_{launch_id[:8]}.png"
            self.page.screenshot(path=str(shot))
            self.log(f"   [erro: {motivo}] print salvo em {shot}")
        except Exception as e:
            config.diag(f"não consegui salvar o print do erro '{motivo}': {e!r}")
