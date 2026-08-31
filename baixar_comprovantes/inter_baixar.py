# -*- coding: utf-8 -*-
"""Comprovantes Pix do Banco Inter, sem terminal.

Isto é o `fontes/baixar comprovantes inter/baixar_comprovantes_inter.py`
trazido para dentro do app. O miolo é o MESMO — os três blocos JS, a
digitação real no datepicker, o filtro "Saída", o laço por índice e as pausas
anti-bloqueio —, porque ele funciona e reescrevê-lo só criaria um segundo
jeito de errar. O que saiu foi a casca de terminal.

**O que mudou, e por quê:**

`input()` não existe mais. Eram cinco: um depois do QR, um se o filtro não
pegasse, um se o "Saída" não aparecesse, um se a lista viesse vazia e um
antes de começar. Num exe `--noconsole` não há onde digitar, e "aperte
ENTER" num robô que roda sozinho é um robô que não roda sozinho. No lugar,
duas coisas: a espera pelo login OLHA a tela, e o que antes pedia confirmação
agora vira desfecho declarado (`Resultado.motivo`) para quem chamou decidir.

**A armadilha do sinal de login.** O script provava "está logado" esperando
uma linha "Pix Enviado" aparecer. Isso confunde duas coisas muito diferentes:
"a pessoa ainda não escaneou" e "a pessoa escaneou, e não há Pix no período".
O segundo caso virava um timeout de 60 s lido como falha de login — e o
período sem pagamento é justamente o mais comum numa segunda-feira. Aqui a
prova de login é o EXTRATO ter carregado (`marcas_de_extrato`), e a contagem
de linhas é uma pergunta separada, feita depois.

**Perfil de Chrome por conta.** O script abria navegador limpo a cada
execução, então o QR era pedido de novo toda vez. O padrão copiado é o do
Sicoob (`launch_persistent_context`), com uma pasta POR conta — no Inter cada
conta é um login, e um perfil só faria a segunda conta herdar a sessão da
primeira.
"""
from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:                                     # utilitários compartilhados (raiz)
    import util
except ModuleNotFoundError:              # rodando este módulo isoladamente
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import util

URL_LOGIN = "https://contadigital.inter.co/home"
URL_EXTRATO = "https://contadigital.inter.co/pix/extrato"

#: Pausa entre um comprovante e outro. Não diminua: a API do Inter bloqueia
#: temporariamente quem clica rápido demais, e o bloqueio custa o lote todo.
PAUSA_ENTRE_ITENS = 2.0

#: A linha do extrato é um `<li>` que contém isto.
TEXTO_LINHA = "Pix Enviado"

#: Quanto se espera a pessoa escanear o QR. Generoso: ela vai buscar o
#: celular, e um timeout curto aqui transforma "demorei" em "falhou".
TEMPO_LOGIN = 300

#: Quanto se espera o extrato carregar DEPOIS de a sessão estar aberta.
TEMPO_EXTRATO = 45

#: Cinco falhas seguidas param o lote. Não é desistência: é o sinal de que o
#: site mudou ou bloqueou, e continuar clicando piora o bloqueio.
FALHAS_SEGUIDAS_QUE_PARAM = 5

JS_CONTAR_LINHAS = """
() => [...document.querySelectorAll('li')]
        .filter(li => li.textContent.includes('Pix Enviado')).length
"""

JS_CLICAR_LINHA = """
(i) => {
    const rows = [...document.querySelectorAll('li')]
        .filter(li => li.textContent.includes('Pix Enviado'));
    const row = rows[i];
    if (!row) return null;
    row.scrollIntoView({block: 'center'});
    (row.querySelector('button') || row).click();
    return row.textContent.trim().slice(0, 70);
}
"""

JS_TEM_ERRO = "() => document.body.innerText.includes('Ocorreu um erro')"

#: O que prova que o EXTRATO está na tela — e, portanto, que a sessão abriu.
#: São marcas da moldura da página, não do conteúdo dela: é essa diferença
#: que separa "não logou" de "logou e não tem Pix no período".
#:
#: Mais de uma porque nenhuma é garantida: o Inter muda rótulo sem avisar, e
#: bastar UMA delas é o que impede a troca de uma palavra de derrubar o motor.
#: A lista é confirmada na primeira rodada com QR de verdade — antes disso
#: ela é hipótese, e o `sondar` existe para transformá-la em fato.
MARCAS_DE_EXTRATO = ("Extrato", "Saída", "Entrada", "Filtrar", "Pix")

#: O que prova que a tela de LOGIN ainda está na frente. Enquanto qualquer uma
#: aparecer, ninguém escaneou nada.
MARCAS_DE_LOGIN = ("QR Code", "QR code", "Ler o QR", "Acesse sua conta",
                   "Entrar com", "Internet Banking")


class InterFalhou(RuntimeError):
    """O que impediu esta conta de terminar. Não derruba as outras da fila."""


@dataclass
class Resultado:
    """O que aconteceu com uma conta. Vira pill na tabela da fase 4."""

    conta: str = ""
    baixados: list[Path] = field(default_factory=list)
    falhas: list[int] = field(default_factory=list)
    total_na_tela: int = 0
    periodo_confirmado: str = ""
    motivo: str = ""                     # "" = deu certo

    @property
    def ok(self) -> bool:
        return not self.motivo

    @property
    def quantos(self) -> int:
        return len(self.baixados)

    def resumo(self) -> str:
        if self.motivo:
            return self.motivo
        if not self.total_na_tela:
            return "sem lançamentos no período"
        falhou = f" · {len(self.falhas)} falharam" if self.falhas else ""
        return f"{self.quantos} de {self.total_na_tela} comprovantes{falhou}"


# --------------------------------------------------------------- sem tela
# O que está abaixo não abre navegador: é o que dá para provar em teste.

def data_valida(texto: str) -> datetime | None:
    """dd/mm/aaaa -> datetime. None quando não é data."""
    try:
        return datetime.strptime((texto or "").strip(), "%d/%m/%Y")
    except (ValueError, TypeError):
        return None


def conferir_periodo(inicio: str, fim: str) -> tuple[str, str]:
    """Valida o par de datas e devolve-o normalizado. Levanta se não presta.

    Aqui, e não na tela: o período errado só apareceria depois do QR, com a
    pessoa esperando na frente do navegador."""
    d1, d2 = data_valida(inicio), data_valida(fim)
    if not d1 or not d2:
        raise InterFalhou("as datas do período precisam ser dd/mm/aaaa")
    if d2 < d1:
        raise InterFalhou("a data final vem antes da inicial")
    if (d2 - d1).days > 90:
        # O Inter só consulta os últimos 90 dias; pedir mais devolve uma tela
        # vazia que se lê como "não houve pagamento".
        raise InterFalhou("o Inter só mostra 90 dias — divida o período")
    return d1.strftime("%d/%m/%Y"), d2.strftime("%d/%m/%Y")


def periodo_confere(chip: str, inicio: str, fim: str) -> bool:
    """O site registrou o período que se pediu?

    O chip é a única confirmação que o Inter dá, e conferi-lo é o que impede
    baixar o mês errado inteiro achando que se filtrou."""
    return bool(chip) and inicio in chip and fim in chip


def nome_livre(pasta: Path, nome: str) -> Path:
    """Um caminho que ainda não existe, numerando o repetido.

    O Inter dá o mesmo `suggested_filename` a dois Pix do mesmo valor para o
    mesmo favorecido no mesmo dia — e sobrescrever perderia um comprovante de
    um pagamento que aconteceu.

    O nome base é relido do ORIGINAL a cada volta. O script de terminal relia
    do último tentado, e por isso o terceiro repetido saía
    `comprovante_1_2.pdf` — o sufixo empilhava, e o nome crescia a cada
    colisão."""
    base = Path(nome)
    destino = pasta / nome
    n = 1
    while destino.exists():
        destino = pasta / f"{base.stem}_{n}{base.suffix}"
        n += 1
    return destino


def deve_parar(falhas: list[int], atual: int) -> bool:
    """Cinco falhas nos últimos cinco itens: parar.

    Falha esparsa é comprovante problemático e o lote segue. Falha seguida é
    o site dizendo alguma coisa — bloqueio, mudança de tela, sessão caindo —,
    e insistir a partir daí só piora."""
    if len(falhas) < FALHAS_SEGUIDAS_QUE_PARAM:
        return False
    return falhas[-FALHAS_SEGUIDAS_QUE_PARAM] >= atual - FALHAS_SEGUIDAS_QUE_PARAM


def pasta_do_perfil(conta: str) -> Path:
    """A pasta de Chrome DESTA conta.

    Uma por conta porque no Inter cada conta é um login: um perfil só faria a
    segunda conta entrar como a primeira, e o robô baixaria os comprovantes
    errados sem nada na tela dizendo isso."""
    limpo = re.sub(r"[^A-Za-z0-9_-]+", "_", (conta or "conta").strip())[:40]
    return util.pasta_base() / f".chrome_profile_inter_{limpo or 'conta'}"


def tela_diz(texto: str, marcas) -> bool:
    """Alguma das marcas aparece neste texto de tela?"""
    return any(m in (texto or "") for m in marcas)


# --------------------------------------------------------------- com tela
# Daqui para baixo tudo depende do navegador. Sem teste automatizado de
# propósito: o que há para provar é o site do banco, e um dublê dele provaria
# só que o dublê concorda com o código. A prova é a rodada com QR de verdade.

def _texto_da_tela(page) -> str:
    try:
        return page.evaluate("() => document.body.innerText") or ""
    except Exception:                                        # noqa: BLE001
        return ""                        # navegando: a página troca no meio


def esperar_login(page, tempo: int = TEMPO_LOGIN, log=print) -> None:
    """Espera a pessoa escanear o QR, olhando a tela em vez de o teclado.

    O laço vai ao extrato e pergunta se ele carregou. Enquanto a tela ainda
    mostrar marca de login, a resposta é "ninguém escaneou"; quando o extrato
    aparece, a sessão está aberta — e AÍ se conta quantos Pix há, que é outra
    pergunta.

    Levanta `InterFalhou` no estouro do tempo, com o que estava na tela: sem
    isso o recado seria "não deu", que não diz se foi o QR, a rede ou o site.
    """
    log("Escaneie o QR code com o app do Inter. Eu sigo sozinho depois.")
    limite = time.time() + tempo
    ultima = ""
    while time.time() < limite:
        texto = _texto_da_tela(page)
        if tela_diz(texto, MARCAS_DE_EXTRATO) and not tela_diz(texto, MARCAS_DE_LOGIN):
            log("Sessão aberta.")
            return
        if texto and texto != ultima:
            ultima = texto
        time.sleep(1.5)
        if not tela_diz(_texto_da_tela(page), MARCAS_DE_LOGIN):
            # Saiu do login: leva ao extrato e deixa o laço confirmar. Ir
            # antes seria pedir uma página que a sessão ainda não alcança.
            try:
                if URL_EXTRATO not in page.url:
                    page.goto(URL_EXTRATO)
            except Exception:                                # noqa: BLE001
                pass                     # a SPA ainda está trocando de tela
    raise InterFalhou(
        f"passaram {tempo}s e a tela do extrato não apareceu. O que estava "
        f"nela: {(ultima or '(vazia)')[:160]}")


def _indices_campos_data(page):
    """Índices dos inputs do popup cujo valor JÁ é uma data — é assim que se
    acha o campo certo sem depender do nome dele."""
    return page.evaluate("""() => {
        const modal = document.querySelector('.filter-modal');
        if (!modal) return [];
        return [...modal.querySelectorAll('input')]
            .map((inp, i) => /^\\d{2}\\/\\d{2}\\/\\d{4}$/.test(inp.value) ? i : -1)
            .filter(i => i >= 0);
    }""")


def texto_chip_periodo(page) -> str:
    try:
        return page.locator(".filter-item--title").first.inner_text().strip()
    except Exception:                                        # noqa: BLE001
        return ""


def aplicar_filtro_datas(page, inicio: str, fim: str, tentativas: int = 3,
                         log=print) -> str:
    """Digita o período no datepicker e CONFERE o que o site registrou.

    Digitação tecla a tecla porque o datepicker do Inter só reage a eventos
    reais — `fill()` muda o valor e o componente ignora."""
    for t in range(1, tentativas + 1):
        try:
            page.locator(".filter-item").first.click()
            time.sleep(1.2)
            idxs = _indices_campos_data(page)
            if len(idxs) < 2:
                raise InterFalhou("não achei os campos de data no popup")
            campos = page.locator(".filter-modal input")
            for idx, valor in ((idxs[0], inicio), (idxs[1], fim)):
                campo = campos.nth(idx)
                campo.click()
                time.sleep(0.3)
                campo.press("Control+a")
                campo.press("Delete")
                campo.type(valor, delay=60)
                time.sleep(0.4)
            page.locator(".filter-modal button", has_text="Filtrar").click()
            time.sleep(3)
            chip = texto_chip_periodo(page)
            if periodo_confere(chip, inicio, fim):
                return chip
            log(f"  tentativa {t}: o site registrou '{chip}'")
        except Exception as e:                               # noqa: BLE001
            log(f"  tentativa {t} não pegou: {e}")
            try:
                page.keyboard.press("Escape")
            except Exception:                                # noqa: BLE001
                pass
            time.sleep(1.5)
    return ""


def ativar_saida(page) -> bool:
    """Liga o filtro 'Saída' e confere que ficou ligado."""
    padrao = re.compile(r"Sa[ií]da")
    btn = None
    for _ in range(3):
        btn = page.locator("button", has_text=padrao).first
        if btn.count() == 0:
            return False
        if "active" in (btn.get_attribute("class") or ""):
            return True
        btn.click()
        time.sleep(2.5)
    return bool(btn) and "active" in (btn.get_attribute("class") or "")


def esperar_botao(page, texto: str, tempo: float = 10.0):
    """O locator de um botão que apareceu E está habilitado. None se não veio."""
    limite = time.time() + tempo
    while time.time() < limite:
        loc = page.locator("button", has_text=texto).first
        try:
            if loc.count() > 0 and loc.is_visible() and loc.is_enabled():
                return loc
        except Exception:                                    # noqa: BLE001
            pass
        time.sleep(0.5)
    return None


def fechar_modal(page) -> None:
    """Fecha o modal do comprovante.

    Continua sendo "o último botão sem texto que tem svg" — heurística que o
    script original usava e que acerta pelo layout de hoje. O `Escape` fica de
    rede embaixo dela."""
    try:
        page.evaluate("""() => {
            const btns = [...document.querySelectorAll('button')]
                .filter(b => !b.textContent.trim() && b.querySelector('svg'));
            if (btns.length) btns[btns.length - 1].click();
        }""")
    except Exception:                                        # noqa: BLE001
        try:
            page.keyboard.press("Escape")
        except Exception:                                    # noqa: BLE001
            pass
    time.sleep(1.2)


def baixar_da_pagina(page, pasta: Path, resultado: Resultado,
                     pular: int = 0, log=print) -> Resultado:
    """O laço: clica a linha, abre o comprovante, baixa o PDF.

    Conta as linhas UMA vez e itera por índice, reencontrando cada uma a cada
    clique — é o que o script fazia, e funciona porque o modal fecha e a lista
    continua na tela."""
    total = page.evaluate(JS_CONTAR_LINHAS)
    resultado.total_na_tela = total
    if not total:
        # Não é falha: segunda-feira sem Pix é um dia normal. Quem chamou
        # decide o que mostrar — e a pill dirá "sem lançamentos".
        log("Nenhum 'Pix Enviado' no período.")
        return resultado

    log(f"{total} comprovante(s) para baixar.")
    for i in range(pular, total):
        if page.evaluate(JS_TEM_ERRO):
            resultado.motivo = (f"o site mostrou 'Ocorreu um erro' no item "
                                f"{i + 1}; parei para não piorar o bloqueio")
            log(resultado.motivo)
            break
        try:
            if page.evaluate(JS_CLICAR_LINHA, i) is None:
                raise InterFalhou("a linha sumiu da lista")
            time.sleep(1.8)

            ver = esperar_botao(page, "Ver comprovante", 8)
            if not ver:
                raise InterFalhou("o botão 'Ver comprovante' não apareceu")
            ver.click()

            botao = esperar_botao(page, "Baixar PDF", 12)
            if not botao:
                raise InterFalhou("o botão 'Baixar PDF' não apareceu")

            with page.expect_download(timeout=30000) as espera:
                botao.click()
            arquivo = espera.value
            destino = nome_livre(pasta, arquivo.suggested_filename)
            arquivo.save_as(destino)
            resultado.baixados.append(destino)
            log(f"[{i + 1}/{total}] {destino.name}")
        except Exception as e:                               # noqa: BLE001
            # Amplo de propósito: um comprovante problemático não pode derrubar
            # o lote, e o índice dele sai no relatório.
            resultado.falhas.append(i)
            log(f"[{i + 1}/{total}] falhou ({e}) — seguindo")
            if deve_parar(resultado.falhas, i):
                resultado.motivo = (f"{FALHAS_SEGUIDAS_QUE_PARAM} falhas "
                                    f"seguidas a partir do item "
                                    f"{resultado.falhas[-FALHAS_SEGUIDAS_QUE_PARAM] + 1}")
                log(resultado.motivo)
                break
        finally:
            fechar_modal(page)
            time.sleep(PAUSA_ENTRE_ITENS)
    return resultado


def baixar(conta: str, inicio: str, fim: str, pasta, *, pular: int = 0,
           log=print, headless: bool = False) -> Resultado:
    """Baixa os comprovantes Pix de UMA conta do Inter. Um QR, um lote.

    Não levanta por conta que falhou: o desfecho vem no `Resultado`, porque a
    fila da aba (fase 4) precisa seguir para a próxima conta."""
    from playwright.sync_api import sync_playwright

    resultado = Resultado(conta=conta)
    try:
        inicio, fim = conferir_periodo(inicio, fim)
    except InterFalhou as e:
        resultado.motivo = str(e)
        return resultado

    destino = Path(pasta)
    destino.mkdir(parents=True, exist_ok=True)
    perfil = pasta_do_perfil(conta)
    perfil.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        # Persistente e com pasta por conta: é o que faz o QR ser pedido uma
        # vez por dia, e não uma vez por execução.
        ctx = pw.chromium.launch_persistent_context(
            str(perfil), channel="chrome", headless=headless,
            accept_downloads=True, args=["--start-maximized"],
            no_viewport=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(URL_LOGIN)
            esperar_login(page, log=log)
            if URL_EXTRATO not in page.url:
                page.goto(URL_EXTRATO)
                time.sleep(2)

            chip = aplicar_filtro_datas(page, inicio, fim, log=log)
            if not chip:
                resultado.motivo = (f"não consegui aplicar o período "
                                    f"{inicio} a {fim} na tela do Inter")
                return resultado
            resultado.periodo_confirmado = chip
            log(f"Período na tela: {chip}")

            if not ativar_saida(page):
                # Sem o "Saída" viriam também os Pix RECEBIDOS, e comprovante
                # de entrada na pasta de pagamento é o erro que a validação da
                # fase 3 existe para pegar. Melhor não baixar nada.
                resultado.motivo = "não consegui ligar o filtro 'Saída'"
                return resultado

            baixar_da_pagina(page, destino, resultado, pular=pular, log=log)
        except InterFalhou as e:
            resultado.motivo = str(e)
        except Exception as e:                               # noqa: BLE001
            resultado.motivo = f"erro inesperado: {e}"
        finally:
            try:
                ctx.close()
            except Exception:                                # noqa: BLE001
                pass
    return resultado


def sondar(conta: str = "sonda", log=print) -> dict:
    """Abre o Inter, espera o QR e conta o que EXISTE na tela. Não baixa nada.

    Existe para a primeira rodada com QR de verdade: as marcas de login e de
    extrato aqui em cima são hipótese até alguém escanear e olhar. Esta função
    é o que transforma a hipótese em fato — e some quando isso acontecer.
    """
    from playwright.sync_api import sync_playwright

    achados: dict = {}
    perfil = pasta_do_perfil(conta)
    perfil.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(perfil), channel="chrome", headless=False,
            accept_downloads=True, args=["--start-maximized"], no_viewport=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(URL_LOGIN)
            log("Escaneie o QR. Vou olhar a tela sozinho e contar o que vejo.")
            esperar_login(page, log=log)
            page.goto(URL_EXTRATO)
            time.sleep(4)
            texto = _texto_da_tela(page)
            achados = {
                "url": page.url,
                "linhas_pix_enviado": page.evaluate(JS_CONTAR_LINHAS),
                "chip_periodo": texto_chip_periodo(page),
                "marcas_de_extrato_vistas":
                    [m for m in MARCAS_DE_EXTRATO if m in texto],
                "marcas_de_login_ainda_na_tela":
                    [m for m in MARCAS_DE_LOGIN if m in texto],
                "primeiras_linhas": texto.splitlines()[:25],
            }
        finally:
            try:
                ctx.close()
            except Exception:                                # noqa: BLE001
                pass
    return achados
