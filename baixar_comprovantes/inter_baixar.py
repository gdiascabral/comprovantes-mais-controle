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

**Perfil de Chrome por conta.** Uma pasta POR conta, no padrão do Sicoob
(`launch_persistent_context`). No Inter cada conta é um login, e um perfil só
faria a segunda conta herdar a sessão da primeira — baixando os comprovantes
da errada, sem nada na tela dizendo isso.

O que o perfil **não** faz é poupar o QR. Conferido em 31/08/2026: o Inter
pede o código de novo a cada abertura, mesmo com a sessão anterior gravada na
pasta. É trava do banco, e não defeito daqui — a expectativa contrária estava
escrita neste comentário e era falsa. A consequência para a fila da aba (fase
4) é de desenho, não de detalhe: **uma leitura de QR por conta, toda vez**, e
é por isso que o Sicoob vem primeiro na fila (um QR resolve N contas).
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

try:
    from . import ja_baixados
except ImportError:                      # rodando este módulo isoladamente
    import ja_baixados

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
#:
#: CONFERIDAS na tela logada em 31/08/2026 (`sondar`): "Extrato Pix", "Saldo",
#: "Bloqueados", "Ordenação", "Saída" e "Entrada" estavam todas lá. "Filtrar"
#: NÃO estava — ele mora dentro do modal do filtro, e não no corpo da página.
#:
#: O "Pix" solto saiu de propósito: ele aparece no menu de QUALQUER tela do
#: banco, inclusive antes de entrar, e uma marca que também vale deslogado não
#: prova login nenhum.
MARCAS_DE_EXTRATO = ("Extrato Pix", "Ordenação", "Bloqueados",
                     "Saída", "Entrada")

#: O que prova que a tela de LOGIN ainda está na frente. Enquanto qualquer uma
#: aparecer, ninguém escaneou nada.
#:
#: A conferência de 31/08/2026 mostrou que NENHUMA delas sobra na tela logada
#: — que é a metade que importa: uma marca de login que também aparecesse
#: depois de entrar travaria o motor para sempre, esperando um login que já
#: aconteceu.
MARCAS_DE_LOGIN = ("QR Code", "QR code", "Ler o QR", "Acesse sua conta",
                   "Entrar com", "Internet Banking")

#: O QR do Inter VENCE, e a tela troca o código por um convite a gerar outro.
#: Quem estiver esperando na frente da tela clica; um robô, não — e na fila da
#: aba (fase 4) ele chega na vez de cada conta quando chega, que pode ser dez
#: minutos depois de alguém ter saído para o café. Sem isto, o desfecho é
#: "passaram 300s e a tela não apareceu" para um QR que só precisava de um
#: clique.
TEXTO_QR_VENCIDO = "gerar um novo QR"


# ------------------------------------------------------- comprovante 2ª via
# A segunda tela do Inter, e o segundo passe da MESMA sessão: terminado o Pix,
# o motor vai direto para cá sem novo QR.
#
# **Por que os Pix NÃO vêm daqui.** O mesmo pagamento aparece nas duas telas, e
# o PDF desta vem SEM a descrição — que é exatamente o campo pelo qual o Anexar
# casa o comprovante com o lançamento. Baixar tudo de um lugar só pareceria uma
# simplificação e quebraria o casamento sem quebrar teste nenhum. Cada tipo tem
# a sua origem, e ela é fixa: Pix pelo Extrato Pix, boleto por aqui.
URL_2VIA = "https://contadigital.inter.co/segunda-via-comprovantes"

#: Os tipos que a 2ª via traz, e o texto que cada um mostra na coluna "Tipo".
#: Conferido na tela em 31/08/2026, que oferece seis: Resgate/Aplicação,
#: Transferência, Pagamento, Pix, DARF e Débito Automático.
#:
#: Uma BUSCA POR TIPO, e não uma só com tudo: o dropdown escolhe um de cada
#: vez, e filtrar no servidor mantém cada página curta — com todos os tipos
#: juntos, os Pix (que são a maioria) empurrariam os pagamentos para a segunda
#: página, que este passe não percorre.
#:
#: Pix fica de fora e não é esquecimento: o PDF desta tela vem SEM descrição, e
#: é a descrição que faz o Anexar casar. Os Pix vêm do Extrato Pix, com ela.
TIPOS_DA_2VIA = (("Pagamento", "PAGAMENTO"),
                 ("DARF", "DARF"))

#: As classes da tela são geradas (`sc-fgSWkL jVOOTC`, styled-components) e
#: mudam a cada build do banco — ancorar nelas é escrever código com data de
#: validade. O que se usa é o que descreve função: papéis ARIA, o tipo do
#: input, e o texto visível.
SEL_LINHA = "tr[role=row]"

#: O botão de baixar é o ÍCONE de arquivo na última coluna, e clicar nele já
#: baixa — sem marcar nada, sem confirmar. A caixa de seleção da primeira
#: coluna faz aparecer um "Download" em lote, mas ele fica de fora: ninguém
#: conferiu se ele devolve um arquivo POR comprovante ou um PDF só com todos
#: juntos, e um arquivo só seria inútil para o Anexar, que casa UM comprovante
#: com UM lançamento. O ícone não tem essa dúvida.
#:
#: Sem `:last-child`: o pseudo-seletor exige que a célula seja o último FILHO
#: do `<tr>`, e ela não é — bastou um elemento depois dela para o motor dizer
#: "a linha não tem a coluna do ícone" nas duas linhas que achou. Pega-se a
#: última que EXISTE (`.last`), que é o que se quer dizer.
SEL_CELULAS = "td[role=cell]"


class InterFalhou(RuntimeError):
    """O que impediu esta conta de terminar. Não derruba as outras da fila."""


@dataclass
class Resultado:
    """O que aconteceu com uma conta. Vira pill na tabela da fase 4."""

    conta: str = ""
    baixados: list[Path] = field(default_factory=list)
    falhas: list[int] = field(default_factory=list)
    total_na_tela: int = 0
    total_2via: int = 0                  # comprovantes de PAGAMENTO (boleto)
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
        se_houve = self.total_na_tela + self.total_2via
        if not se_houve:
            return "sem lançamentos no período"
        falhou = f" · {len(self.falhas)} falharam" if self.falhas else ""
        boleto = f" (+{self.total_2via} de boleto)" if self.total_2via else ""
        return (f"{self.quantos} de {se_houve} comprovantes{boleto}{falhou}")


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
        # QR vencido: renova sozinho, e conta que fez isso — quem está com o
        # celular na mão precisa saber que o código na tela é outro.
        if TEXTO_QR_VENCIDO in texto:
            try:
                page.get_by_text(TEXTO_QR_VENCIDO, exact=False).first.click()
                log("O QR tinha vencido; gerei outro.")
                time.sleep(2)
            except Exception:                                # noqa: BLE001
                pass                     # se não der, o laço segue esperando
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


def baixar(conta: str, inicio: str, fim: str, pasta, *,
           log=print, headless: bool = False,
           tambem_2via: bool = True) -> Resultado:
    """Os comprovantes de UMA conta do Inter. Um QR, dois passes, uma pasta.

    Passe 1, o extrato Pix: todo Pix ENVIADO do período, com a descrição que
    o Anexar usa para casar.
    Passe 2, a 2ª via: PAGAMENTO e DARF.

    Os dois na MESMA sessão porque o Inter pede o QR a cada abertura — trava
    dele, conferida: perfil salvo não a vence. Tudo o que precisa da sessão
    tem de caber nela.

    Fala com a API, e não com a tela. A tela é uma casca sobre estas mesmas
    chamadas, e falar com elas resolveu de uma vez o que a casca cobrou caro:
    o filtro de data que ignorava calado, o teto de 100 linhas por página, os
    seletores de classe gerada, e os 2 s de pausa por clique. O caminho pela
    tela está em `0b9303d`, se um dia a API mudar de forma.

    Não levanta por conta que falhou: o desfecho vem no `Resultado`, porque a
    fila da aba (fase 4) precisa seguir para a próxima conta.
    """
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
        # Uma pasta de perfil por conta: no Inter cada conta é um login, e um
        # perfil só faria a segunda entrar como a primeira — baixando os
        # comprovantes da errada, sem nada na tela dizendo isso.
        ctx = pw.chromium.launch_persistent_context(
            str(perfil), channel="chrome", headless=headless,
            accept_downloads=True, args=["--start-maximized"],
            no_viewport=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        autorizacao = escutar_autorizacao(page)
        try:
            page.goto(URL_LOGIN)
            esperar_login(page, log=log)

            # O extrato precisa ser ABERTO mesmo usando a API: é a página que
            # carrega a sessão no cabeçalho, e é do cabeçalho de uma chamada
            # dela que sai a autorização. Sem passar por aqui, não há o que
            # escutar.
            page.goto(URL_EXTRATO)
            page.wait_for_timeout(6000)
            resultado.periodo_confirmado = f"{inicio} a {fim}"

            # O registro mora na RAIZ, e não na subpasta do dia: a
            # pergunta é "já baixei este comprovante alguma vez?", e ela
            # atravessa as rodadas.
            registro = ja_baixados.Registro(destino.parent)

            log("Comprovantes de Pix:")
            baixar_pix_pela_api(page, destino, resultado, inicio, fim,
                                autorizacao, log=log, registro=registro)

            if tambem_2via and not resultado.motivo:
                log("Comprovantes de pagamento (2ª via):")
                baixar_2via_pela_api(page, destino, resultado, inicio, fim,
                                     autorizacao, log=log, registro=registro)
            registro.gravar()
        except InterFalhou as e:
            resultado.motivo = str(e)
        except Exception as e:                               # noqa: BLE001
            resultado.motivo = f"erro inesperado: {e}"
        finally:
            # O cabeçalho some antes de qualquer outra coisa acontecer.
            autorizacao["valor"] = ""
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


def _escolher_tipo(page, tipo: str, log=print) -> bool:
    """Escolhe no dropdown "Tipos" (um react-select).

    O clique tem de ser no CONTAINER (`-control`), e não no texto do
    placeholder: clicar no texto dá timeout, porque quem escuta o clique é o
    componente de fora. Foi assim que a sonda descobriu — 30 s perdidos.
    """
    try:
        page.locator("[class*='-control']").first.click()
        page.wait_for_timeout(1200)
        opcao = page.locator("[id^=react-select]").filter(has_text=tipo).last
        if not opcao.count():
            log(f"  não achei a opção {tipo!r} no dropdown de tipos")
            return False
        opcao.click()
        page.wait_for_timeout(800)
        return True
    except Exception as e:                                   # noqa: BLE001
        log(f"  não consegui escolher o tipo: {e}")
        return False


def data_da_linha(texto):
    """A data que a própria linha mostra: "PAGAMENTO 28/08/2026 R$ 108,39".

    É por aqui que o período é respeitado, e NÃO pelo filtro de data da tela.
    O campo de lá é um seletor de INTERVALO: os dois inputs de cada campo
    andam em par, mexer no início APAGA o fim, e digitar neles não pegou em
    três tentativas. Na terceira ele ignorou o que foi digitado e a busca saiu
    com os três meses padrão, sem um erro sequer na tela — 71 comprovantes
    baixados no lugar de 13. Filtro que falha calado é o pior que existe:
    ninguém percebe o que não veio.

    A data escrita na linha não tem esse problema. É o que o banco afirma que
    aconteceu, e está à vista de quem confere.
    """
    achado = re.search(r"\b(\d{2}/\d{2}/\d{4})\b", texto or "")
    return data_valida(achado.group(1)) if achado else None


def dentro_do_periodo(texto: str, inicio: str, fim: str) -> bool:
    """A linha cai no período pedido? Linha sem data legível fica de FORA.

    De fora, e não dentro: o custo de pular um comprovante é ele aparecer sem
    anexo na conferência, que alguém vê. O de baixar o que não se sabe datar é
    três meses virarem "a semana passada" sem ninguém notar.
    """
    quando = data_da_linha(texto)
    d1, d2 = data_valida(inicio), data_valida(fim)
    if not quando or not d1 or not d2:
        return False
    return d1 <= quando <= d2


def _pedir_pagina_cheia(page, log=print) -> None:
    """100 linhas por página, para não ter de paginar.

    Best-effort: se não der, o motor ainda funciona — só percorre menos por
    vez. O `<select>` tem `id`, e não `name`: a primeira tentativa mirou o
    `name` e levou timeout."""
    for seletor in ("select#rows-per-page-options",
                    "select[name=rows-per-page-options]", "select"):
        try:
            page.select_option(seletor, "100", timeout=5000)
            page.wait_for_timeout(2500)
            return
        except Exception:                                    # noqa: BLE001
            continue
    log("  segui com o tamanho de página padrão")


def _linhas_do_tipo(page, texto: str):
    """As linhas cuja coluna Tipo diz esta palavra.

    Conferir de novo o que o servidor já filtrou é cinto e suspensório: se um
    dia o filtro de lá falhar calado — como o de DATA falhou —, é isto que
    impede o motor de baixar o que não devia."""
    return page.locator(SEL_LINHA).filter(has_text=texto)


def _onde_clicar_para_baixar(linha, log=print):
    """O que se clica para baixar UMA linha. Levanta dizendo o que viu.

    Três hipóteses em cascata, da mais específica para a mais frouxa, porque
    duas tentativas já morreram em "a linha não tem a coluna do ícone" — uma
    frase que diz o que faltou e não o que existe. Quando nenhuma serve, o
    erro carrega o HTML da linha: é ele que resolve, e não mais um palpite.
    """
    for descricao, seletor in (("a última célula", "td[role=cell]"),
                               ("a última célula sem papel", "td"),
                               ("o que envolve um svg", "span:has(svg)"),
                               ("qualquer svg", "svg")):
        alvo = linha.locator(seletor)
        if alvo.count():
            escolhido = alvo.last
            # O clique vai no PAI do svg quando houver um: svg não recebe
            # clique de forma confiável no Playwright.
            dentro = escolhido.locator("span:has(svg)")
            if dentro.count():
                return dentro.last
            return escolhido
        log(f"    (sem {descricao})")
    trecho = ""
    try:
        trecho = linha.evaluate("el => el.outerHTML")[:400]
    except Exception:                                        # noqa: BLE001
        pass
    raise InterFalhou(f"não achei onde clicar nesta linha. HTML: {trecho}")


def baixar_2via(page, pasta: Path, resultado: Resultado, inicio: str, fim: str,
                log=print) -> Resultado:
    """O segundo passe: os comprovantes de PAGAMENTO (boleto), na mesma sessão.

    Clica no ícone de arquivo da última coluna, que baixa direto — sem marcar,
    sem confirmar. Ver `SEL_BOTAO_BAIXAR` para por que não é o lote.
    """
    page.goto(URL_2VIA)
    page.wait_for_timeout(4000)
    for tipo, texto in TIPOS_DA_2VIA:
        log(f"\n2ª via — {tipo}:")
        _baixar_um_tipo(page, pasta, resultado, inicio, fim, tipo, texto,
                        log=log)
    return resultado


def _baixar_um_tipo(page, pasta: Path, resultado: Resultado, inicio: str,
                    fim: str, tipo: str, texto: str, log=print) -> Resultado:
    """Uma busca, um tipo. Falhar num tipo não derruba o outro."""
    if not _escolher_tipo(page, tipo, log=log):
        log(f"  não consegui filtrar por {tipo}; pulei")
        return resultado

    try:
        page.locator("button", has_text="Pesquisar").first.click()
    except Exception as e:                                   # noqa: BLE001
        log(f"  não consegui pesquisar {tipo}: {e}")
        return resultado
    page.wait_for_timeout(4000)
    _pedir_pagina_cheia(page, log=log)

    linhas = _linhas_do_tipo(page, texto)
    na_tela = linhas.count()
    if not na_tela:
        log(f"  nenhum {tipo} na tela.")
        return resultado

    # A tela traz o período padrão dela (três meses). O recorte é feito aqui,
    # pela data de cada linha, e o que fica de fora sai no log com a data —
    # para quem confere ver que foi decisão, e não esquecimento.
    # `dizeres`, e não `texto`: `texto` é o PARÂMETRO com o tipo procurado
    # ("PAGAMENTO"), e reusar o nome aqui o substituía pelo conteúdo da última
    # linha lida. O filtro do laço de baixo passava então a procurar linhas
    # contendo "PAGAMENTO 20/08/2026 R$ 750,00" — nenhuma casa, e cada linha
    # vinha vazia, sem td e sem HTML. Quatro leituras de QR atrás de um defeito
    # de tela que era uma variável pisada.
    escolhidas, fora = [], []
    for i in range(na_tela):
        dizeres = " ".join(linhas.nth(i).inner_text().split())
        (escolhidas if dentro_do_periodo(dizeres, inicio, fim)
         else fora).append((i, dizeres[:60]))
    log(f"{na_tela} na tela · {len(escolhidas)} dentro de {inicio}–{fim}")
    for _i, t in fora[:5]:
        log(f"  fora do período: {t}")
    # A lista vem da mais NOVA para a mais velha (conferido: 28/08, 20/08,
    # 19/08...). Então, com a página cheia, só há risco de faltar coisa se a
    # linha mais VELHA da página ainda estiver dentro do período — aí o
    # período continua na página seguinte. Avisar sempre que enchesse seria
    # gritar todo dia por um problema que quase nunca existe, e aviso que
    # sempre aparece é aviso que ninguém lê.
    if na_tela >= 100 and fora:
        mais_velha = data_da_linha(fora[-1][1]) if fora else None
        if mais_velha and mais_velha >= (data_valida(inicio) or mais_velha):
            log("  ATENÇÃO: a página encheu e o período continua além dela — "
                "pode haver comprovante numa segunda página.")
    elif na_tela >= 100 and not fora:
        log("  ATENÇÃO: as 100 linhas da página estão TODAS no período — "
            "quase certamente há mais numa segunda página.")
    if not escolhidas:
        return resultado

    total = len(escolhidas)
    for pos, (i, _t) in enumerate(escolhidas, start=1):
        try:
            linha = _linhas_do_tipo(page, texto).nth(i)
            alvo = _onde_clicar_para_baixar(linha, log=log)
            with page.expect_download(timeout=30000) as espera:
                alvo.click()
            arquivo = espera.value
            destino = nome_livre(pasta, arquivo.suggested_filename)
            arquivo.save_as(destino)
            resultado.baixados.append(destino)
            resultado.total_2via += 1
            log(f"[2ª via {pos}/{total}] {destino.name}")
        except Exception as e:                               # noqa: BLE001
            resultado.falhas.append(1000 + i)   # 1000+ = veio da 2ª via
            log(f"[2ª via {pos}/{total}] falhou ({e}) — seguindo")
        finally:
            # A pausa fica: é a mesma API do Inter do outro passe, e ela
            # bloqueia quem clica rápido demais.
            time.sleep(PAUSA_ENTRE_ITENS)
    return resultado


# ==========================================================================
# A 2ª via pela API
# ==========================================================================
#
# A tela é uma casca sobre estas duas chamadas, e falar com elas resolve de uma
# vez tudo o que a casca cobrou caro numa manhã inteira:
#
#   o filtro de data existia o tempo todo, em `dataInicio`/`dataFim`. O
#   datepicker é que era um seletor de intervalo que ignorava o que se
#   digitava — e ignorava CALADO;
#   a lista não pagina: 290 operações vieram numa resposta só, onde a tela
#   mostrava 100 e escondia o resto;
#   o pedido de PDF aceita VÁRIOS comprovantes e devolve uma URL assinada para
#   cada um, então o download em lote deixa de ser aposta;
#   e o histórico é de 24 meses, contra os 90 dias da tela do Pix.
#
# O que se perde é a garantia de contrato: endpoint interno muda sem aviso,
# como muda seletor. A diferença é o barulho — endpoint que mudou responde 4xx,
# e 4xx aparece no log. Seletor que mudou não casa com nada e fica quieto, que
# foi exatamente como 71 comprovantes desceram no lugar de 13.
#
# **O token nunca é gravado, impresso ou devolvido.** Ele é lido de uma chamada
# que a própria página fez, vive numa variável local durante a execução e some
# com ela. Ler de um pedido real, e não de `localStorage`, evita depender de
# adivinhar onde o app o guarda.

API_INTER = "https://cdpj-api.bancointer.com.br"

#: Os tipos, como a API os aceita. Conferido: `tipo=PAGAMENTO` responde 200 e
#: traz só pagamentos. A metadata lista seis códigos em minúsculas
#: (pagamento, transferencia, resgate, debito_automatico, pix, darf) e a API
#: aceitou o nome em maiúsculas — vale o que foi PROVADO na chamada.
TIPOS_DA_API = ("PAGAMENTO", "DARF")

_JS_LISTAR = """
async ([base, cabecalho, inicio, fim, tipo]) => {
    const url = `${base}/comprovantes/v2/segunda-via`
        + `?dataInicio=${encodeURIComponent(inicio)}`
        + `&dataFim=${encodeURIComponent(fim)}&tipo=${tipo}`;
    const r = await fetch(url, {headers: {Authorization: cabecalho}});
    if (!r.ok) return {erro: `HTTP ${r.status}`};
    const j = await r.json();
    return {operacoes: (j.data && j.data.operacoes) || []};
}
"""

_JS_PEDIR_PDF = """
async ([base, cabecalho, comprovantes]) => {
    const r = await fetch(`${base}/comprovantes/v2/pdf/segunda-via`, {
        method: 'POST',
        headers: {Authorization: cabecalho, 'Content-Type': 'application/json'},
        body: JSON.stringify({comprovantes}),
    });
    if (!r.ok) return {erro: `HTTP ${r.status}`};
    const j = await r.json();
    return {urls: j.urlAssinada || []};
}
"""


def escutar_autorizacao(page) -> dict:
    """Guarda o cabeçalho de sessão da primeira chamada que a página fizer.

    Devolve um dicionário que se preenche sozinho — quem chama espera a página
    conversar com a API e então lê `["valor"]`.

    De um pedido REAL, e não de `localStorage`: não depende de adivinhar onde o
    app guarda, e continua valendo quando ele mudar de lugar.
    """
    guardado = {"valor": ""}

    def ouvir(pedido):
        if guardado["valor"] or "cdpj-api" not in pedido.url:
            return
        valor = pedido.headers.get("authorization", "")
        if valor:
            guardado["valor"] = valor

    page.on("request", ouvir)
    return guardado


def pedido_de_pdf(item: dict) -> dict | None:
    """O que a API pede para gerar o PDF de UMA operação.

    O de-para foi lido da chamada que a própria tela faz:

        tipo            <- classificacao.tipo
        operacao        <- classificacao.operacao
        codigo          <- pagamento.codigoLancamento
        dataEfetivacao  <- dataEfetivacao

    `None` quando falta peça: pedir com campo vazio devolveria erro do
    servidor, e o motivo ficaria escondido num HTTP 400 genérico.
    """
    classificacao = item.get("classificacao") or {}
    pagamento = item.get("pagamento") or {}
    pedido = {
        "tipo": classificacao.get("tipo") or "",
        "operacao": classificacao.get("operacao") or "",
        "codigo": str(pagamento.get("codigoLancamento") or ""),
        "dataEfetivacao": item.get("dataEfetivacao") or "",
    }
    return pedido if all(pedido.values()) else None


def nome_do_comprovante(item: dict) -> str:
    """`PAGAMENTO_2026-08-28_108-39_554362970.pdf`.

    O nome que a API sugere é um carimbo de hora — inútil para quem procura na
    pasta e inútil para o Anexar. Aqui entram data, valor e o código do
    lançamento, que é o que identifica o pagamento sem ambiguidade.
    """
    classificacao = item.get("classificacao") or {}
    pagamento = item.get("pagamento") or {}
    tipo = re.sub(r"[^A-Za-z]+", "", classificacao.get("tipo") or "COMPROVANTE")
    dia, mes, ano = (item.get("dataEfetivacao") or "00/00/0000").split("/")
    valor = re.sub(r"[^0-9,]+", "", item.get("valor") or "").replace(",", "-")
    codigo = re.sub(r"[^0-9A-Za-z]+", "", str(pagamento.get("codigoLancamento") or ""))
    return f"{tipo}_{ano}-{mes}-{dia}_{valor}_{codigo}.pdf"


def baixar_2via_pela_api(page, pasta: Path, resultado: Resultado, inicio: str,
                         fim: str, autorizacao: dict, log=print,
                         registro=None) -> Resultado:
    """Os comprovantes de PAGAMENTO e DARF do período, sem tocar na tela."""
    cabecalho = (autorizacao or {}).get("valor", "")
    if not cabecalho:
        resultado.motivo = ("não peguei o cabeçalho da sessão — a página não "
                            "chegou a chamar a API")
        return resultado

    for tipo in TIPOS_DA_API:
        try:
            resposta = page.evaluate(_JS_LISTAR,
                                     [API_INTER, cabecalho, inicio, fim, tipo])
        except Exception as e:                               # noqa: BLE001
            log(f"  {tipo}: não deu para listar ({e})")
            continue
        if resposta.get("erro"):
            log(f"  {tipo}: a API recusou a lista ({resposta['erro']})")
            continue

        operacoes = resposta.get("operacoes") or []
        pedidos, itens = [], []
        for item in operacoes:
            pedido = pedido_de_pdf(item)
            if pedido is None:
                log(f"  {tipo}: operação sem código, pulei "
                    f"({item.get('dataEfetivacao')} {item.get('valor')})")
                continue
            pedidos.append(pedido)
            itens.append(item)
        log(f"  {tipo}: {len(operacoes)} no período · {len(pedidos)} com código")
        if not pedidos:
            continue

        # UM comprovante por chamada. O endpoint aceita uma lista, mas o que
        # ele devolve não é uma URL por item: pedindo DOIS, veio UMA — ele
        # GRUDA os comprovantes num PDF só. Foi a trava de contagem que
        # descobriu isso, e ela existia justamente porque o casamento seria
        # por posição: dois arquivos com o mesmo conteúdo e nomes de
        # pagamentos diferentes, e ninguém veria até procurar um comprovante e
        # achar outro.
        #
        # (É também a resposta da dúvida sobre o botão "Download" em lote da
        # tela: lote ali significa PDF grudado, inútil para o Anexar, que casa
        # UM comprovante com UM lançamento.)
        for item, pedido in zip(itens, pedidos):
            marca = ja_baixados.chave("inter2via", pedido.get("codigo", ""))
            if registro is not None and registro.tem(marca):
                log(f"  já baixado antes: {nome_do_comprovante(item)}")
                continue
            try:
                gerado = page.evaluate(_JS_PEDIR_PDF,
                                       [API_INTER, cabecalho, [pedido]])
                if gerado.get("erro"):
                    raise InterFalhou(f"a API recusou o PDF ({gerado['erro']})")
                urls = gerado.get("urls") or []
                if len(urls) != 1:
                    raise InterFalhou(f"esperava 1 URL e vieram {len(urls)}")

                resposta = page.request.get(urls[0])
                if not resposta.ok:
                    raise InterFalhou(f"HTTP {resposta.status} ao baixar")
                destino = nome_livre(pasta, nome_do_comprovante(item))
                destino.write_bytes(resposta.body())
                resultado.baixados.append(destino)
                resultado.total_2via += 1
                if registro is not None:
                    registro.anotar(marca, destino)
                log(f"  {destino.name}")
            except Exception as e:                           # noqa: BLE001
                resultado.falhas.append(1000 + len(resultado.falhas))
                log(f"  falhou ({e}) — seguindo")
            finally:
                # Bem menor que a pausa da tela (2 s), mas não zero: a API do
                # Inter bloqueia quem bate rápido demais, e foi por isso que o
                # script original andava devagar entre cliques.
                time.sleep(0.4)
    return resultado


# ==========================================================================
# O Pix pela API
# ==========================================================================
#
# O mesmo molde da 2ª via, e o mesmo ganho: some o laço de 46 cliques com 2 s
# de pausa entre cada, que levava cinco minutos.
#
# **O PDF sai do MESMO endpoint da 2ª via** — `/comprovantes/v2/pdf/segunda-via`
# —, só que com outro corpo. O que muda: o `codigo` é o endToEnd da transação,
# entram `tipoConta` e `contaCorrente`, e não há `dataEfetivacao`.
#
# O endToEnd chegando de graça no JSON resolve, de lambuja, o que a fase 3 do
# plano ia buscar dentro do PDF: é ele o identificador que impede baixar o
# mesmo comprovante duas vezes.
#
# **Sobre a descrição, o que se sabe e o que não se sabe.** No item conferido
# ela vinha vazia — mas aquele era um pagamento por QR CODE
# (`origemMovimento: "QR_CODE"`), e QR quase nunca carrega descrição. Pix por
# CHAVE (CPF, CNPJ, e-mail) é outra história e ainda não foi medido. A regra
# "o Pix vem do extrato, e não da 2ª via" segue valendo por ora; o que a
# derruba ou confirma é contar, na lista inteira, quantos trazem descrição —
# e é o que `contar_descricoes` faz.

_JS_EXTRATO_PIX = """
async ([base, cabecalho]) => {
    const r = await fetch(`${base}/cc/pix/v1/extrato`,
                          {headers: {Authorization: cabecalho}});
    if (!r.ok) return {erro: `HTTP ${r.status}`};
    const j = await r.json();
    // A resposta vem agrupada por mês; o que interessa é a lista achatada.
    const secoes = j.sections || [];
    const movs = [];
    for (const s of secoes) for (const m of (s.movimentacoes || [])) movs.push(m);
    return {movimentacoes: movs};
}
"""


def conta_da_pagina(page) -> str:
    """O número da conta, lido do cabeçalho da própria tela.

    O pedido do PDF de Pix exige `contaCorrente`, e ele não vem no item da
    lista. Está no alto da página, ao lado do nome da empresa — de onde a
    própria tela o tira.
    """
    try:
        texto = page.evaluate("() => document.body.innerText || ''")
    except Exception:                                        # noqa: BLE001
        return ""
    # Sete a dez dígitos soltos numa linha: é a forma da conta do Inter
    # (362674043). Data e valor não passam por aqui — têm barra e vírgula.
    for linha in texto.splitlines()[:40]:
        achado = re.fullmatch(r"\s*(\d{7,10})\s*", linha)
        if achado:
            return achado.group(1)
    return ""


def e_pix_enviado(mov: dict) -> bool:
    """Saída, e não entrada.

    `tipo == "D"` é o que a tela chamava de filtro "Saída". Conferir os dois
    (o tipo do extrato e a natureza) porque comprovante de Pix RECEBIDO na
    pasta de pagamento é o erro que a validação da fase 3 existe para pegar.
    """
    return ((mov.get("tipoExtrato") or "").upper() == "PIX"
            and (mov.get("tipo") or "").upper() == "D")


def pedido_de_pdf_pix(mov: dict, conta: str) -> dict | None:
    """O corpo que gera o PDF de UM Pix. `None` quando falta peça.

    O de-para saiu da chamada que a própria tela faz:

        tipo           "PIX"            (fixo)
        operacao       "PAGAMENTO_PIX"  (fixo)
        tipoConta      "PJ"             (fixo — é conta empresa)
        codigo         <- detalhePix.endToEnd
        contaCorrente  <- o número da conta, do cabeçalho da tela
    """
    detalhe = mov.get("detalhePix") or {}
    codigo = detalhe.get("endToEnd") or ""
    if not codigo or not conta:
        return None
    return {"tipo": "PIX", "operacao": "PAGAMENTO_PIX", "tipoConta": "PJ",
            "codigo": codigo, "contaCorrente": conta}


def descricao_do_pix(mov: dict) -> str:
    """A descrição do pagamento, de onde ela estiver.

    Vale muito: MEDIDO no extrato de 31/08/2026, 44 de 46 Pix por CHAVE
    trazem descrição (e 0 de 7 por QR Code, que é o caso onde ela não existe
    mesmo). É o campo pelo qual o Anexar casa o comprovante com o lançamento —
    e ele vem do JSON, não do PDF. Quem tirava do documento estava indo ao
    lugar mais difícil buscar o que a API entrega pronto.
    """
    detalhe = mov.get("detalhePix") or {}
    for onde in (mov.get("descricao"), detalhe.get("descricaoPagamento"),
                 detalhe.get("campoLivre")):
        if (onde or "").strip():
            return onde.strip()
    return ""


def nome_do_pix(mov: dict) -> str:
    """`PIX_2026-08-28_116-56_Pex_NF 1234.pdf`.

    Data, valor, para quem foi e — quando existe — a descrição. Ela entra
    porque é por ela que o Anexar casa, e tê-la no NOME dispensa abrir o PDF.

    O valor vem formatado com duas casas: ele chega como número (116.56), e
    apenas tirar a pontuação produzia `11656` — que se lê como onze mil.
    """
    dia, mes, ano = (mov.get("data") or "00/00/0000").split("/")
    try:
        valor = f"{float(mov.get('valor') or 0):.2f}".replace(".", "-")
    except (TypeError, ValueError):
        valor = "0-00"
    limpar = lambda t: re.sub(r"[^A-Za-z0-9 ]+", " ", t or "").strip()  # noqa: E731
    quem = limpar(mov.get("nome"))[:36] or "sem-nome"
    detalhe = limpar(descricao_do_pix(mov))[:40]
    miolo = f"{quem}_{detalhe}" if detalhe else quem
    return f"PIX_{ano}-{mes}-{dia}_{valor}_{miolo}.pdf"


def contar_descricoes(movimentacoes) -> dict:
    """Quantos Pix trazem descrição, separados por ORIGEM.

    Existe para uma pergunta de desenho não ser respondida por amostra: o
    primeiro item que se olhou vinha sem descrição, mas era um QR Code, e QR
    quase nunca traz. Se o Pix por CHAVE trouxer, a origem única volta à mesa
    — e aí um caminho a menos para manter.
    """
    contas: dict = {}
    for mov in movimentacoes:
        detalhe = mov.get("detalhePix") or {}
        origem = detalhe.get("origemMovimento") or "(sem origem)"
        tem = bool((mov.get("descricao") or "").strip()
                   or (detalhe.get("descricaoPagamento") or "").strip()
                   or (detalhe.get("campoLivre") or "").strip())
        registro = contas.setdefault(origem, {"total": 0, "com_descricao": 0})
        registro["total"] += 1
        registro["com_descricao"] += 1 if tem else 0
    return contas


def baixar_pix_pela_api(page, pasta: Path, resultado: Resultado, inicio: str,
                        fim: str, autorizacao: dict, log=print,
                        registro=None) -> Resultado:
    """Os comprovantes de Pix ENVIADO do período, sem clicar em nada."""
    cabecalho = (autorizacao or {}).get("valor", "")
    if not cabecalho:
        resultado.motivo = ("não peguei o cabeçalho da sessão — a página não "
                            "chegou a chamar a API")
        return resultado

    conta = conta_da_pagina(page)
    if not conta:
        resultado.motivo = ("não achei o número da conta na tela, e o pedido "
                            "do PDF de Pix exige ele")
        return resultado

    try:
        resposta = page.evaluate(_JS_EXTRATO_PIX, [API_INTER, cabecalho])
    except Exception as e:                                   # noqa: BLE001
        resultado.motivo = f"não deu para ler o extrato Pix: {e}"
        return resultado
    if resposta.get("erro"):
        resultado.motivo = f"a API recusou o extrato Pix ({resposta['erro']})"
        return resultado

    movs = resposta.get("movimentacoes") or []
    # O recorte é feito aqui, pela data que cada movimentação declara — o mesmo
    # princípio da 2ª via, e pelo mesmo motivo: filtro de tela que falha calado
    # já custou 71 arquivos no lugar de 13.
    enviados = [m for m in movs if e_pix_enviado(m)]
    no_periodo = [m for m in enviados
                  if dentro_do_periodo(m.get("data") or "", inicio, fim)]
    log(f"  Pix: {len(movs)} no extrato · {len(enviados)} enviados · "
        f"{len(no_periodo)} entre {inicio} e {fim}")
    resultado.total_na_tela = len(no_periodo)

    for mov in no_periodo:
        detalhe = mov.get("detalhePix") or {}
        marca = ja_baixados.chave("pix", detalhe.get("endToEnd") or "")
        if registro is not None and registro.tem(marca):
            log(f"  já baixado antes: {nome_do_pix(mov)}")
            continue
        try:
            pedido = pedido_de_pdf_pix(mov, conta)
            if pedido is None:
                raise InterFalhou("movimentação sem endToEnd")
            gerado = page.evaluate(_JS_PEDIR_PDF,
                                   [API_INTER, cabecalho, [pedido]])
            if gerado.get("erro"):
                raise InterFalhou(f"a API recusou o PDF ({gerado['erro']})")
            urls = gerado.get("urls") or []
            if len(urls) != 1:
                raise InterFalhou(f"esperava 1 URL e vieram {len(urls)}")

            baixado = page.request.get(urls[0])
            if not baixado.ok:
                raise InterFalhou(f"HTTP {baixado.status} ao baixar")
            destino = nome_livre(pasta, nome_do_pix(mov))
            destino.write_bytes(baixado.body())
            resultado.baixados.append(destino)
            if registro is not None:
                registro.anotar(marca, destino)
            log(f"  {destino.name}")
        except Exception as e:                               # noqa: BLE001
            resultado.falhas.append(len(resultado.falhas))
            log(f"  falhou ({e}) — seguindo")
        finally:
            time.sleep(0.4)
    return resultado
