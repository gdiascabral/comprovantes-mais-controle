# -*- coding: utf-8 -*-
"""
Playwright sobre o SicoobNet Empresarial.

O login é MANUAL, por decisão de projeto: a tela tem reCAPTCHA, e nada aqui
tenta contorná-lo. O cliente abre o navegador, espera a pessoa entrar e assume
o controle depois que a sessão já está aberta — o trabalho automatizado é o
repetitivo (percorrer 13 contas), não o que exige credencial.

Navegador próprio, separado do Mais Controle: são sites e logins diferentes, e
o Playwright síncrono não divide thread entre eles (ver CLAUDE.md).

Armadilhas resolvidas aqui:

- **O PDF não é download.** O botão chama `window.print()` e abre o diálogo do
  Windows. Neutralizamos o `print()` e geramos o arquivo por `Page.printToPDF`
  do CDP — `page.pdf()` do Playwright recusa navegador com janela. Mesma
  solução de `relatorios/extrato_mc.py`.
- **O período não aceita digitação.** É um datepicker de intervalo, mas tem
  `select` de mês e de ano: dá para escolher direto, sem navegar mês a mês
  pelas setas. O `select` de mês é 0-indexed (julho = "6").
- **Classes `ng-tns-c97-35` são geradas por build** e mudam sem aviso. Todo
  seletor daqui ancora em texto, `role` ou classe estável do PrimeNG.
"""
import base64
import re
from pathlib import Path

from playwright.sync_api import TimeoutError as PWTimeout
from playwright.sync_api import sync_playwright

from . import sicoob_config as cfg

import util

_norm = util.norm_espaco

# A sessão do Sicoob expira por inatividade (~20 min), mas cada interação
# renova. Como o robô nunca fica parado, o timeout generoso só cobre lentidão.
TEMPO_PADRAO = 45_000
TEMPO_LOGIN = 10 * 60 * 1000        # a pessoa precisa digitar e passar o captcha

RE_CONTA = re.compile(r"\b(\d{2}\.\d{3}-\d)\b")


class SessaoPerdida(RuntimeError):
    """Caímos para a tela de login no meio do trabalho."""


class SicoobClient:
    def __init__(self, log=print, cdp_url: str | None = None, headless: bool = False):
        self.log = log
        self._cdp_url = cdp_url        # desenvolvimento: usa um Chrome já aberto
        self._headless = headless
        self._pw = None
        self._browser = None
        self.ctx = None
        self.page = None

    # ------------------------------------------------------------ ciclo

    def __enter__(self):
        self._pw = sync_playwright().start()
        if self._cdp_url:
            # Só para desenvolvimento: aproveita uma sessão já aberta à mão.
            self._browser = self._pw.chromium.connect_over_cdp(self._cdp_url)
            self.ctx = self._browser.contexts[0]
            self.page = self.ctx.pages[-1]
        else:
            cfg.PASTA_PERFIL_CHROME.mkdir(parents=True, exist_ok=True)
            # O Playwright põe `--disable-extensions` nos argumentos padrão, e
            # o Sicoob pede a extensão "Sicoob Internet Banking" no login. Com
            # a flag, a Chrome Web Store recusa com "a instalação não está
            # ativada" — e, mesmo já instalada, a extensão ficaria desligada a
            # cada execução. Tirá-la é o que torna o perfil persistente útil
            # aqui: instala-se uma vez, à mão, e vale para as próximas.
            self.ctx = self._pw.chromium.launch_persistent_context(
                str(cfg.PASTA_PERFIL_CHROME), channel="chrome",
                headless=self._headless, accept_downloads=True,
                ignore_default_args=["--disable-extensions"],
                args=["--start-maximized"], no_viewport=True)
            self.page = self.ctx.pages[0] if self.ctx.pages else self.ctx.new_page()
        self.ctx.set_default_timeout(TEMPO_PADRAO)
        return self

    def __exit__(self, *exc):
        self.fechar()

    def fechar(self):
        for alvo, metodo in ((self.ctx, "close"), (self._browser, "close"),
                             (self._pw, "stop")):
            try:
                if alvo is not None:
                    getattr(alvo, metodo)()
            except Exception:
                pass                    # fechando: erro aqui não interessa
        self._pw = self._browser = self.ctx = self.page = None

    # ------------------------------------------------------------- login

    def aguardar_login(self, tempo: int = TEMPO_LOGIN):
        """Abre a tela de login e espera a pessoa entrar.

        O sinal de que entrou é a lista de contas na tela. Não mexemos em
        campo de senha nem no captcha."""
        if not self.page.url.startswith("https://ib.sicoob.com.br"):
            self.page.goto(cfg.URL_LOGIN)
        if self._na_selecao_de_contas():
            self.log("Sessão já estava aberta.")
            return
        self.log("Faça o login no Chrome que abriu (cooperativa, chave e senha).")
        self.log("Assim que a lista de contas aparecer, eu assumo daqui.")
        self.page.wait_for_selector("div.seletor-conta", timeout=tempo)
        self.log("Login concluído.")

    def _na_selecao_de_contas(self) -> bool:
        try:
            return self.page.locator("div.seletor-conta").count() > 0
        except Exception:
            return False

    def _conferir_sessao(self):
        if "#/login" in self.page.url or "#/operador" in self.page.url:
            raise SessaoPerdida("A sessão do Sicoob caiu.")

    # ------------------------------------------------------------ contas

    def ir_para_selecao(self):
        """Volta para a lista de contas, de onde estiver."""
        if self._na_selecao_de_contas():
            return
        self._fechar_painel()      # um drawer aberto bloquearia o clique
        trocar = self.page.locator("a.cursor.texto-trocar-conta")
        if trocar.count():
            trocar.first.click()
        else:
            self.page.goto(cfg.URL_SELECAO_CONTAS)
        self.page.wait_for_selector("div.seletor-conta", timeout=TEMPO_PADRAO)
        self._conferir_sessao()

    def listar_contas(self) -> list[str]:
        """Números das contas visíveis na lista, na ordem da tela."""
        self.ir_para_selecao()
        numeros = []
        for texto in self.page.locator("div.seletor-conta").all_inner_texts():
            achado = RE_CONTA.search(texto)
            if achado:
                numeros.append(achado.group(1))
        return numeros

    def acessar_conta(self, numero: str) -> bool:
        """Entra na conta pelo número. False se ela não estiver na lista."""
        self.ir_para_selecao()
        linha = self.page.locator("div.seletor-conta").filter(
            has_text=numero).first
        if not linha.count():
            return False
        botao = linha.get_by_text("Acessar conta", exact=False).first
        (botao if botao.count() else linha).click()
        self.page.wait_for_url(re.compile(r"#/home"), timeout=TEMPO_PADRAO)
        self._conferir_sessao()
        return True

    # ----------------------------------------------------------- extrato

    def abrir_extrato(self):
        self.page.goto(cfg.URL_EXTRATO)
        self.page.wait_for_selector("text=Movimentações", timeout=TEMPO_PADRAO)
        self._conferir_sessao()

    def _dropdown(self, rotulo: str, opcao: str):
        """Escolhe um valor num p-dropdown, achando-o pelo RÓTULO.

        A posição fixa (Ordenação = 0, Agrupar = 1...) valia enquanto o banco
        não mexesse na tela. Um dropdown a mais e "Ordenação" vira "Agrupar
        lançamentos": o extrato sairia agrupado, o app não reclamaria de nada e
        o arquivo iria para a pasta certa com o conteúdo errado. Achar pelo
        rótulo custa uma consulta e sobrevive a mudança de ordem.
        """
        campo = self._campo_do_rotulo(rotulo)
        campo.click()
        self.page.locator("p-dropdownitem, .ui-dropdown-item").filter(
            has_text=opcao).first.click()
        self.page.wait_for_timeout(400)

        # Confere o que ficou escrito no campo. Escolher a opção errada aqui
        # não dá erro nenhum — só um extrato diferente do pedido.
        try:
            escolhido = (campo.inner_text(timeout=2000) or "").strip()
        except Exception:
            return
        if escolhido and _norm(opcao) not in _norm(escolhido):
            raise RuntimeError(
                f'não consegui marcar "{opcao}" em "{rotulo}": o campo ficou '
                f'com "{escolhido}". A tela do Sicoob provavelmente mudou.')

    def _campo_do_rotulo(self, rotulo: str):
        """O p-dropdown que está sob o rótulo dado (ou, na falta, por posição).

        A ordem histórica é Ordenação, Agrupar lançamentos, Agrupar por data,
        Tipo de transação — mantida só como último recurso."""
        alvo = self.page.locator(
            f'xpath=//*[contains(normalize-space(.), "{rotulo}")]'
            f'/following::p-dropdown[1]').first
        try:
            if alvo.count() and alvo.is_visible(timeout=2000):
                return alvo
        except Exception:
            pass
        ordem = {"Ordenação": 0, "Agrupar lançamentos": 1,
                 "Agrupar por data": 2, "Tipo de transação": 3}
        return self.page.locator("p-dropdown").nth(ordem[rotulo])

    def definir_ordenacao(self, opcao: str = cfg.ORDENACAO):
        self._dropdown("Ordenação", opcao)

    def definir_periodo(self, ano: int, mes: int):
        """Seleciona o mês fechado (dia 1 ao último dia) no datepicker.

        Usa os `select` de mês e ano em vez das setas: menos cliques e imune a
        quantos meses de distância está o alvo. O `select` de mês é 0-indexed.
        Ao final CONFERE o texto do campo — período errado significaria extrato
        errado arquivado com nome certo, o pior desfecho possível."""
        import calendar
        ultimo = calendar.monthrange(ano, mes)[1]

        self.page.locator("p-calendar input").first.click()
        cal = self.page.locator(".ui-datepicker").first
        cal.wait_for(state="visible", timeout=TEMPO_PADRAO)

        cal.locator("select.ui-datepicker-month").select_option(str(mes - 1))
        cal.locator("select.ui-datepicker-year").select_option(str(ano))
        self.page.wait_for_timeout(300)

        self._clicar_dia(cal, 1)
        self._clicar_dia(cal, ultimo)
        cal.get_by_text("Confirmar", exact=True).click()
        self.page.wait_for_timeout(1500)

        esperado = f"{1:02d}/{mes:02d}/{ano} - {ultimo:02d}/{mes:02d}/{ano}"
        obtido = self.texto_periodo()
        if esperado not in (obtido or ""):
            raise RuntimeError(
                f"O período não ficou como pedido: esperava '{esperado}', "
                f"o campo mostra '{obtido}'.")

    def _clicar_dia(self, cal, dia: int):
        """Clica num dia da grade.

        Os dias do mês exibido são `<a>`; os vizinhos em cinza, que pertencem
        ao mês anterior ou ao seguinte, são `<span>` dentro de
        `td.ui-datepicker-other-month`. Mirar no `<a>` dentro de um `td` que
        NÃO é other-month resolve as duas coisas de uma vez: o elemento certo
        e o mês certo — senão o dia 1 clicado poderia ser o do mês vizinho."""
        alvo = cal.locator(
            f"td:not(.ui-datepicker-other-month) > a:text-is('{dia}')")
        if not alvo.count():
            raise RuntimeError(
                f"não achei o dia {dia} no calendário — o mês exibido pode "
                "estar errado ou o dia está desabilitado")
        alvo.first.click()
        self.page.wait_for_timeout(250)

    def texto_periodo(self) -> str | None:
        campo = self.page.locator("p-calendar input").first
        return campo.input_value() if campo.count() else None

    # --------------------------------------------------------- exportar

    # "Exportar extrato" aparece três vezes quando o painel está aberto: dois
    # botões da página (`primary low`, um no topo e outro no rodapé da lista,
    # que em mês cheio fica a milhares de pixels de distância) e o do painel
    # (`primary high`, desabilitado até um formato ser marcado). A classe
    # separa os dois papéis sem depender de posição na tela.
    _BTN_PAGINA = "button.new-btn-sicoob.primary.low"
    _BTN_PAINEL = "button.new-btn-sicoob.primary.high"

    def _painel_aberto(self) -> bool:
        return self.page.locator(self._BTN_PAINEL).filter(
            has_text="Exportar extrato").count() > 0

    def _abrir_painel_exportacao(self):
        if self._painel_aberto():
            return
        botao = self.page.locator(self._BTN_PAGINA).filter(
            has_text="Exportar extrato").last
        botao.scroll_into_view_if_needed()
        botao.click()
        self.page.wait_for_selector("text=Selecione o formato", timeout=TEMPO_PADRAO)

    def _marcar_formato(self, rotulo: str):
        """Marca o formato do painel.

        O rádio não é PrimeNG: é um componente próprio, `ib-sicoob-input-radio`,
        onde o `input[type=radio]` fica escondido atrás de um `span.checkmark`.
        Só o clique NO checkmark marca. Clicar no texto do rótulo ou no card
        não levanta erro nenhum e deixa o botão de exportar desabilitado — a
        falha só apareceria um passo adiante, por isso `_confirmar_exportacao`
        confere o estado do botão antes de clicar.

        O card também costuma nascer fora da área visível do drawer, daí o
        scroll explícito."""
        rotulo_loc = self.page.locator(
            f'span.home-extrato-titulo-card-exportar:text-is("{rotulo}")')
        if not rotulo_loc.count():
            raise RuntimeError(f"o painel não oferece o formato '{rotulo}'")
        card = self.page.locator("div.home-extrato-card-tipo-export").filter(
            has=rotulo_loc)
        marca = card.locator("span.checkmark").first
        marca.scroll_into_view_if_needed()
        marca.click()
        self.page.wait_for_timeout(400)

    def _confirmar_exportacao(self):
        """O botão do painel só habilita depois que um formato é marcado."""
        botao = self.page.locator(self._BTN_PAINEL).filter(
            has_text="Exportar extrato").first
        if botao.is_disabled():
            raise RuntimeError(
                "o botão de exportar continua desabilitado — o formato não foi "
                "marcado")
        botao.click()

    def _baixar_formato(self, rotulo: str, destino: Path) -> Path:
        """Marca um formato no painel e captura o download."""
        self._abrir_painel_exportacao()
        self._marcar_formato(rotulo)
        with self.page.expect_download(timeout=TEMPO_PADRAO) as espera:
            self._confirmar_exportacao()
        destino.parent.mkdir(parents=True, exist_ok=True)
        espera.value.save_as(str(destino))
        self._fechar_painel()
        return destino

    def exportar_ofx(self, destino: Path) -> Path:
        """Baixa o OFX. O nome que o Sicoob dá é descartável — traz a data de
        hoje, não a conta."""
        return self._baixar_formato(cfg.FORMATO_OFX, destino)

    def exportar_pdf(self, destino: Path) -> Path:
        """Gera o PDF a partir do HTML exportado, NÃO do botão "PDF".

        O botão PDF do painel chama `window.print()` e abre o preview de
        impressão do Chrome, que é **modal**: trava o navegador inteiro e não
        fecha nem por `Target.closeTarget` do CDP — o lote morre ali, e um
        clique distraído manda 4 folhas para a impressora. Substituir
        `window.print` não resolve: o site guarda a referência antes de a
        substituição valer, e o preview abre assim mesmo.

        O painel oferece HTML, que é download comum e traz o MESMO extrato
        formatado (cabeçalho SISBR, conta, período, movimentações). Baixamos
        esse HTML, abrimos numa aba própria e imprimimos com
        `Page.printToPDF`. Sem diálogo nativo, e o PDF sai com o extrato — não
        com a tela do internet banking por baixo do painel, que é o que a
        impressão da própria SPA produzia."""
        import tempfile
        with tempfile.TemporaryDirectory(prefix="sicoob_pdf_") as tmp:
            html = Path(tmp) / "extrato.html"
            self._baixar_formato(cfg.FORMATO_HTML, html)

            aba = self.ctx.new_page()
            try:
                aba.goto(html.as_uri(), wait_until="load")
                aba.wait_for_timeout(800)          # fontes e imagens
                sessao = self.ctx.new_cdp_session(aba)
                resposta = sessao.send("Page.printToPDF", {
                    "printBackground": True,
                    "marginTop": 0.4, "marginBottom": 0.4,
                    "marginLeft": 0.4, "marginRight": 0.4,
                })
            finally:
                aba.close()

        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(base64.b64decode(resposta["data"]))
        return destino

    def _fechar_painel(self):
        """Fecha o painel de exportação.

        Deixá-lo aberto trava a conta seguinte: o painel é um drawer com
        `div.overlay.visivel` por cima da página, e esse overlay intercepta
        todo clique — inclusive o do "Trocar conta". Clicar no próprio overlay
        (longe do drawer, que fica à direita) fecha o painel."""
        overlay = self.page.locator("div.overlay.visivel")
        if overlay.count():
            try:
                overlay.first.click(position={"x": 5, "y": 5})
                self.page.wait_for_timeout(600)
            except PWTimeout:
                pass
        if overlay.count():
            self.page.keyboard.press("Escape")
            self.page.wait_for_timeout(400)
