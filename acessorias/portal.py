# -*- coding: utf-8 -*-
"""Playwright sobre o portal Acessórias.

O login é MANUAL, por decisão de projeto, como no Sicoob: a aba abre o Chrome e
espera a pessoa entrar. Com "Manter conectado" marcado, o perfil persistente
guarda a sessão e das próximas vezes o robô já encontra tudo aberto. O app não
guarda senha do portal — uma senha a mais em outro cofre é mais uma chance de
uma envelhecer e o erro virar "login inválido" sem motivo aparente.

Navegador próprio, separado do Mais Controle e do Sicoob: são três sites e três
logins, e o Playwright síncrono não divide thread entre eles (ver CLAUDE.md).

O que este arquivo sabe do portal, e que não é óbvio:

- **É HTML puro, servido por página.** Sem Angular e sem React: navegar é
  `goto`, o estado vive na URL e não há SPA para esperar assentar.
- **`#SolAss` (o assunto) fica FORA do `<form>`**, recolhido por JS no envio.
  Por isso o preenchimento é sempre pela tela; um `multipart` montado à mão
  chegaria ao escritório sem título nenhum, e sem erro.
- **Os `value` dos dois `select` não seguem a ordem da tela** — DPTO_FINANCEIRO
  é o último item e vale 4; a prioridade é invertida (Baixa=3, Muito Alta=0).
  Toda escolha é por RÓTULO. Escolher por índice manda o fechamento para o
  departamento errado, e nada na tela denuncia.
- **`SolDptoDcvID` é um segundo `select`**, hoje sempre em "0". Se um dia ele
  passar a exigir escolha, este módulo PARA e diz — adivinhar sub-departamento
  é a mesma classe de erro que arquivar na empresa errada.
"""
from __future__ import annotations

import re
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from . import config as cfg

import util

#: "Conciliações bancárias Junho/2026 - Fulano [2601]" -> o id entre colchetes.
RE_ID = re.compile(r"\[(\d+)\]\s*$")

#: "06/07/2026 22:02:34 - Finalizado" -> data e situação.
RE_DATA = re.compile(r"^\s*(\d{2}/\d{2}/\d{4})[^-]*-\s*(.+?)\s*$")


class SessaoPerdida(RuntimeError):
    """Caímos para a tela de login no meio do trabalho."""


class EnvioNaoConfirmado(RuntimeError):
    """O Salvar/Enviar passou, mas a solicitação não apareceu com o anexo."""


class Solicitacao:
    """Uma linha da lista de solicitações."""

    __slots__ = ("id", "assunto", "data", "situacao")

    def __init__(self, id: str, assunto: str, data: str, situacao: str):
        self.id, self.assunto = id, assunto
        self.data, self.situacao = data, situacao

    def __repr__(self):                                       # pragma: no cover
        return f"<Solicitacao {self.id} {self.situacao}>"


class PortalClient:
    def __init__(self, vip_url: str, log=print, cdp_url: str | None = None,
                 headless: bool = False):
        #: O endereço do escritório vem do cadastro, nunca do código: ele
        #: carrega o nome de um fornecedor real e o repositório é público.
        self.vip_url = (vip_url or "").rstrip("/")
        self.log = log
        self._cdp_url = cdp_url          # desenvolvimento: Chrome já aberto
        self._headless = headless
        self._pw = None
        self._browser = None
        self.ctx = None
        self.page = None

    # ------------------------------------------------------------ ciclo

    def __enter__(self):
        if not self.vip_url:
            raise RuntimeError(
                "Falta o endereço do portal. Ponha \"vip_url\": "
                "\"https://vip.acessorias.com/<escritorio>\" no "
                "contas_sicoob.json.")
        self._pw = sync_playwright().start()
        if self._cdp_url:
            # Só para desenvolvimento: aproveita uma sessão já aberta à mão.
            self._browser = self._pw.chromium.connect_over_cdp(self._cdp_url)
            self.ctx = self._browser.contexts[0]
            self.page = self.ctx.pages[-1]
        else:
            cfg.PASTA_PERFIL_CHROME.mkdir(parents=True, exist_ok=True)
            self.ctx = self._pw.chromium.launch_persistent_context(
                str(cfg.PASTA_PERFIL_CHROME), channel="chrome",
                headless=self._headless, accept_downloads=True,
                args=["--start-maximized"], no_viewport=True)
            self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.ctx.set_default_timeout(cfg.TEMPO_PADRAO)
        # O portal confirma o envio por alert(). Sem tratar, o Playwright
        # DISPENSA todo diálogo — o que num confirm() significaria cancelar.
        self.page.on("dialog", self._dialogo)
        return self

    def __exit__(self, *exc):
        self.fechar()

    def _dialogo(self, dialogo):
        try:
            if dialogo.message:
                self.log(f"    (portal: {dialogo.message.strip()[:120]})")
            dialogo.accept()
        except Exception:
            pass                         # diálogo já fechado sozinho

    def fechar(self):
        for alvo, metodo in ((self.ctx, "close"), (self._browser, "close"),
                             (self._pw, "stop")):
            try:
                if alvo is not None:
                    getattr(alvo, metodo)()
            except Exception:
                pass                     # fechando: erro aqui não interessa
        self._pw = self._browser = self.ctx = self.page = None

    # ------------------------------------------------------------- login

    def _logado(self) -> bool:
        """O botão Sair só existe depois de entrar — é o sinal mais estável
        da tela, porque não depende de qual empresa está selecionada."""
        try:
            return self.page.locator('button[onclick*="?out"]').count() > 0
        except Exception:
            return False

    def aguardar_login(self, tempo: int = cfg.TEMPO_LOGIN):
        """Abre o portal e espera a pessoa entrar. Não toca em campo de senha."""
        if not self.page.url.startswith(self.vip_url):
            self.page.goto(self.vip_url, wait_until="domcontentloaded")
        if self._logado():
            self.log("Sessão do portal já estava aberta.")
            return
        self.log("Faça o login no Chrome que abriu (e-mail e senha).")
        self.log("Marque \"Manter conectado\" para não repetir todo mês.")
        self.page.wait_for_selector('button[onclick*="?out"]', timeout=tempo)
        self.log("Login concluído.")

    def _conferir_sessao(self):
        if not self._logado():
            raise SessaoPerdida("A sessão do portal Acessórias caiu.")

    def _ir(self, caminho: str, **fmt):
        self.page.goto(self.vip_url + caminho.format(**fmt),
                       wait_until="domcontentloaded")
        self.page.wait_for_timeout(400)  # o portal troca a página inteira
        self._conferir_sessao()

    # ------------------------------------------------------ solicitações

    def _itens_da_tela(self) -> list[Solicitacao]:
        """Lê os cartões da lista. O id vem do `data-id`, e não do texto: o
        `[2601]` do título é exibição, e exibição muda."""
        dados = self.page.evaluate(
            """() => [...document.querySelectorAll('div.go2link[data-id]')]
                  .map((e) => ({ id: e.getAttribute('data-id'),
                                 texto: (e.innerText || '').trim() }))""")
        itens = []
        for d in dados:
            linhas = [ln.strip() for ln in (d["texto"] or "").split("\n")
                      if ln.strip()]
            if not linhas:
                continue
            assunto = RE_ID.sub("", linhas[0]).strip()
            data = situacao = ""
            for ln in linhas[1:]:
                m = RE_DATA.match(ln)
                if m:
                    data, situacao = m.group(1), m.group(2)
                    break
            itens.append(Solicitacao(str(d["id"]), assunto, data, situacao))
        return itens

    def solicitacoes(self, vip_id: str) -> list[Solicitacao]:
        """Todas as solicitações da empresa: Abertas E Encerradas.

        As duas abas importam porque o que interessa é "esta já foi enviada?",
        e uma solicitação do mês passado já pode ter sido encerrada. A aba
        Encerradas carrega ao ser clicada, então não basta ler a tela como ela
        nasce."""
        self._ir(cfg.CAMINHO_SOLICITACOES, vip_id=vip_id)
        achados = {s.id: s for s in self._itens_da_tela()}
        try:
            aba = self.page.locator("#task-add-members-tab")
            if aba.count():
                aba.first.click()
                self.page.wait_for_timeout(1200)
                for s in self._itens_da_tela():
                    achados.setdefault(s.id, s)
        except Exception as e:                                # noqa: BLE001
            # Não achar a aba de encerradas não pode impedir o envio; só faz a
            # checagem de duplicata ficar mais fraca, e isso é registrado.
            self.log(f"    (não consegui abrir as encerradas: {e})")
        return list(achados.values())

    def procurar(self, vip_id: str, assunto: str) -> Solicitacao | None:
        """A solicitação com este assunto, ou None. Compara por
        `util.norm_espaco`: os dois lados são texto digitado por gente."""
        alvo = util.norm_espaco(assunto)
        for s in self.solicitacoes(vip_id):
            if util.norm_espaco(s.assunto) == alvo:
                return s
        return None

    # ------------------------------------------------------------- envio

    def _conferir_subdepartamento(self):
        """`SolDptoDcvID` hoje é um select mudo, em "0". Se ganhar opções de
        verdade, PARAR é a resposta certa: escolher sozinho um
        sub-departamento é a mesma classe de erro que arquivar na empresa
        errada — silencioso e descoberto tarde."""
        try:
            opcoes = self.page.evaluate(
                """() => { const e = document.getElementsByName('SolDptoDcvID')[0];
                           if (!e || !e.options) return [];
                           return [...e.options].map((o) => o.value); }""")
        except Exception:
            return
        reais = [v for v in opcoes if v not in ("", "0")]
        if reais:
            raise RuntimeError(
                "O portal passou a pedir um sub-departamento (SolDptoDcvID) "
                "que este app não sabe escolher. Envie esta empresa pela tela "
                "e me avise para eu ensinar a escolha certa.")

    def criar_solicitacao(self, vip_id: str, assunto: str, comentario: str,
                          anexo: Path, departamento: str = cfg.DEPARTAMENTO,
                          prioridade: str = cfg.PRIORIDADE) -> None:
        """Preenche e envia o formulário. Não confere nada: quem confere é
        `conferir_envio`, e é de propósito que sejam dois passos — "enviei" e
        "chegou" são afirmações diferentes."""
        anexo = Path(anexo)
        if not anexo.is_file():
            raise FileNotFoundError(f"O anexo sumiu: {anexo}")

        self._ir(cfg.CAMINHO_SOLICITACAO_NOVA, vip_id=vip_id)
        self.page.wait_for_selector(cfg.SEL_ASSUNTO, timeout=cfg.TEMPO_PADRAO)

        self.page.fill(cfg.SEL_ASSUNTO, assunto)
        # label=, nunca index=: os value dos selects não seguem a ordem da tela.
        self.page.select_option(cfg.SEL_DEPARTAMENTO, label=departamento)
        self._conferir_subdepartamento()
        self.page.fill(cfg.SEL_COMENTARIO, comentario)
        self.page.select_option(cfg.SEL_PRIORIDADE, label=prioridade)
        self.page.set_input_files(cfg.SEL_ANEXO, str(anexo))

        self.log(f"    enviando {anexo.name}...")
        self.page.click(cfg.SEL_SALVAR)
        # O upload de um zip de fechamento é o passo demorado daqui; a página
        # só troca quando o POST volta.
        try:
            self.page.wait_for_load_state("networkidle",
                                          timeout=cfg.TEMPO_ENVIO)
        except PWTimeout:
            pass                    # seguimos para a conferência, que decide

    def conferir_envio(self, vip_id: str, assunto: str,
                       nome_do_anexo: str) -> Solicitacao:
        """Relê a lista, abre a solicitação e confirma que o anexo está lá.

        Nada de "enviado" sem prova: o `mc_client.anexar` já deu "anexado" sem
        arquivo porque um `wait_for_timeout` fixo era menor que o upload."""
        s = self.procurar(vip_id, assunto)
        if s is None:
            raise EnvioNaoConfirmado(
                "a solicitação não apareceu na lista depois do envio")
        self._ir(cfg.CAMINHO_SOLICITACOES + s.id, vip_id=vip_id)
        texto = util.norm_espaco(self.page.inner_text("body"))
        if util.norm_espaco(nome_do_anexo) not in texto:
            raise EnvioNaoConfirmado(
                f"a solicitação {s.id} foi criada, mas o anexo "
                f"'{nome_do_anexo}' não aparece nela")
        return s
