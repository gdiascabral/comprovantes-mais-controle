# -*- coding: utf-8 -*-
"""O lado do ERP na Prova de saldos: saldo atual + print da conta.

**Roda na thread da vaga do Anexar** (`anx.submeter(..., dona=tela)`): o
`MCClient` e o Playwright dele só vivem lá. O saldo vem do MESMO caminho do
Buscar (`erp_do_dia.ler_saldos`: porteiro com o central ligado; aba do robô
desligado — nunca login HTTP), casado com as linhas do painel pela régua do
painel (`saldos.montar_saldos`).

**O print** é uma FICHA: o cabeçalho da grade `#/accounts` em cima e a
linha da conta embaixo (React/MUI; cada linha tem `data-id` = UUID da conta;
seletores de `conciliacao/erp/browser.py`, levantados em 10/08/2026), só com
as colunas que têm texto na linha, ampliada até a largura útil do PDF
(`montar_ficha`). Na rodada ao vivo de 27/10/2026 o recorte que UNIA as
duas caixas pegava todas as linhas entre o cabeçalho e a conta, e a grade
inteira (2.266 px, quase toda vazia) ficava miúda no PDF. Sem cabeçalho
visível ou sem colunas, fica a foto só da linha. Numa aba PRÓPRIA do robô
(`MCClient._nova_aba_do_robo`), fechada e esquecida no fim — nunca a aba da
pessoa, nunca `ctx.close()`. Os únicos cliques: "Exibir valores" (só mostra
o que está mascarado) e "próxima página". Linha que não aparece vira "sem
print" com o motivo; o saldo continua o da API.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path

import util
from conciliacao.erp.browser import SEL_CONTAS_LINHA, SEL_CONTAS_OLHO
from erp import hosts

from . import prova_saldos as ps
from . import saldos as sd

URL_CONTAS = hosts.ACESSAR + "/#/accounts"
#: O rótulo do botão depende do idioma da MUI (medir ao vivo, Tarefa 8).
SEL_PROXIMA_PAGINA = ('button[aria-label="Go to next page"], '
                      'button[aria-label="Ir para a próxima página"], '
                      'button[aria-label="Próxima página"]')
#: Cabeçalho da DataGrid da MUI (medir ao vivo, Tarefa 8).
SEL_CABECALHO_GRADE = ".MuiDataGrid-columnHeaders"
MAX_PAGINAS = 10
TEMPO_GRADE_MS = 30000
_UUID = re.compile(r"[0-9A-Fa-f-]{8,64}")
NAO_ACHEI = "a conta não apareceu na tela de contas do ERP (#/accounts)"
SEM_UUID = "o ERP não deu o identificador desta conta — sem print"
SEM_SALDO = "o ERP não trouxe o saldo desta conta"


def _primeira_linha(erro) -> str:
    texto = (str(erro or "").strip().splitlines() or [""])[0].strip()
    return texto[:160] or type(erro).__name__


#: As células da linha e, de cada uma, o cabeçalho da mesma coluna
#: (`data-field`), com a caixa do CONTEÚDO (o texto, não a célula de 682 px
#: quase vazia, medida ao vivo em 29/10/2026). Só lê a página.
_JS_COLUNAS = """(linha) => {
    const grade = linha.closest('.MuiDataGrid-root') || document;
    const caixa = (el) => { const g = document.createRange(); g.selectNodeContents(el);
                            const r = g.getBoundingClientRect();
                            return r.width ? {x: r.x, width: r.width} : null; };
    return [...linha.querySelectorAll('[data-field]')].map((c) => {
        const h = grade.querySelector('.MuiDataGrid-columnHeader[data-field="'
                                      + CSS.escape(c.dataset.field) + '"] '
                                      + '.MuiDataGrid-columnHeaderTitle');
        return {campo: c.dataset.field, texto: (c.innerText || '').trim(),
                celula: caixa(c), cabecalho: h ? caixa(h) : null};
    });
}"""
#: Colunas que não provam nada (medidas em 29/10/2026): o botão "Bloquear" e
#: o menu de ações.
CAMPOS_FORA = frozenset({"isFinancialBlock", "actions"})
#: Folga de cada lado do texto de uma coluna, em px de tela.
FOLGA = 10
#: Espaço entre duas colunas da ficha e a ampliação máxima (pixel de tela
#: virando pixel de PDF: mais que isso só borra).
VAO_FICHA = 24
AMPLIACAO_MAX = 2.0


def faixas_da_ficha(colunas) -> list[tuple[float, float]]:
    """As faixas horizontais (x da tela, em px) das colunas que têm texto NA
    LINHA e provam alguma coisa, na ordem da tela. Cada faixa cobre o texto
    da célula e o título da coluna juntos, com `FOLGA` dos dois lados."""
    faixas = []
    for col in colunas or []:
        if col.get("campo") in CAMPOS_FORA or not str(col.get("texto") or "").strip():
            continue
        caixas = [c for c in (col.get("celula"), col.get("cabecalho")) if c]
        if not caixas:
            continue
        x0 = min(c["x"] for c in caixas) - FOLGA
        x1 = max(c["x"] + c["width"] for c in caixas) + FOLGA
        faixas.append((x0, x1))
    return sorted(faixas)


def _corte(img, x_da_imagem: float, x0: float, x1: float, razao: float):
    a = max(0, round((x0 - x_da_imagem) * razao))
    b = min(img.width, round((x1 - x_da_imagem) * razao))
    return img.crop((a, 0, b, img.height)) if b > a else None


def montar_ficha(cabecalho, linha, faixas, *, largura_alvo: int, razao: float = 1.0,
                 x_cabecalho: float = 0.0, x_linha: float = 0.0):
    """A ficha (imagem do Pillow): cada faixa do cabeçalho em cima da mesma
    faixa da linha, lado a lado, ampliada até `largura_alvo` (no máximo
    `AMPLIACAO_MAX`). `x_cabecalho`/`x_linha` = onde cada foto começa na tela
    (as faixas vêm em x da tela); `razao` = pixels da imagem por px de tela
    (a escala do Windows). None sem faixa."""
    from PIL import Image, ImageDraw

    if not faixas:
        return None
    pedacos = []
    for x0, x1 in faixas:
        cab = _corte(cabecalho, x_cabecalho, x0, x1, razao)
        lin = _corte(linha, x_linha, x0, x1, razao)
        if cab is not None and lin is not None:
            largura = min(cab.width, lin.width)
            pedacos.append((cab.crop((0, 0, largura, cab.height)),
                            lin.crop((0, 0, largura, lin.height))))
    if not pedacos:
        return None
    vao = round(VAO_FICHA * razao)
    largura = sum(c.width for c, _ in pedacos) + vao * (len(pedacos) - 1)
    altura = cabecalho.height + 1 + linha.height
    ficha = Image.new("RGB", (largura, altura), "white")
    x = 0
    for cab, lin in pedacos:
        ficha.paste(cab.convert("RGB"), (x, 0))
        ficha.paste(lin.convert("RGB"), (x, cabecalho.height + 1))
        x += cab.width + vao
    ImageDraw.Draw(ficha).line((0, cabecalho.height, largura, cabecalho.height),
                               fill=(160, 160, 160))
    escala = min(AMPLIACAO_MAX, largura_alvo / largura)
    if escala > 1:
        ficha = ficha.resize((round(largura * escala), round(altura * escala)),
                             Image.Resampling.LANCZOS)
    return ficha


def _fotografar_linha(aba, alvo, arquivo) -> str:
    """A ficha (cabeçalho + linha, só colunas com texto); senão, só a linha.
    Dois prints da aba: um com a grade no alto (o cabeçalho à vista) e um com
    a linha rolada para a tela."""
    from . import prova_pdf
    try:
        razao = float(aba.evaluate("window.devicePixelRatio") or 1)
        faixas = faixas_da_ficha(alvo.evaluate(_JS_COLUNAS))
        aba.evaluate("window.scrollTo(0, 0)")
        cab = util.recorte_da_tela(aba, aba.locator(SEL_CABECALHO_GRADE).first)
        alvo.scroll_into_view_if_needed()
        lin = util.recorte_da_tela(aba, alvo)
        if cab and lin:
            ficha = montar_ficha(cab[0], lin[0], faixas,
                                 largura_alvo=prova_pdf.LARGURA_UTIL, razao=razao,
                                 x_cabecalho=cab[1], x_linha=lin[1])
            if ficha is not None:
                Path(arquivo).parent.mkdir(parents=True, exist_ok=True)
                ficha.save(arquivo)
                return ""
    except Exception:                                        # noqa: BLE001
        pass                                 # cai na foto só da linha, abaixo
    return util.fotografar(alvo, arquivo)


def fotografar_contas(mc, pedidos, pasta, *, log=print, parar=lambda: False,
                      ao_abrir_aba=lambda: None) -> dict:
    """{linha: (arquivo, "") ou (None, porquê)} para cada (linha, uuid).

    `ao_abrir_aba()` roda logo depois de a aba do robô abrir: o Chrome a traz
    para a frente, e a prova só abre os bancos DEPOIS disso (senão ela pula
    por cima do login do Sicoob ou do QR do Inter)."""
    saida: dict = {}
    faltam: dict = {}
    for linha, uuid in pedidos:
        if _UUID.fullmatch(str(uuid or "")):
            faltam[linha] = uuid
        else:
            saida[linha] = (None, SEM_UUID)
    if not faltam:
        return saida
    pasta = Path(pasta)
    try:
        aba = mc._nova_aba_do_robo()
    except Exception as e:                                   # noqa: BLE001
        motivo = f"print do ERP falhou: {_primeira_linha(e)}"
        log(f"  ERP: {motivo}")
        return {**saida, **{linha: (None, motivo) for linha in faltam}}
    try:
        ao_abrir_aba()
    except Exception:                                        # noqa: BLE001
        pass                     # aviso para a tela; o print segue de todo jeito
    try:
        aba.goto(URL_CONTAS, wait_until="domcontentloaded")
        aba.wait_for_selector(SEL_CONTAS_LINHA, timeout=TEMPO_GRADE_MS)
        olho = aba.locator(SEL_CONTAS_OLHO).first
        if olho.count():
            olho.click()               # só mostra os valores mascarados
            aba.wait_for_timeout(1500)
        for _ in range(MAX_PAGINAS):
            for linha, uuid in list(faltam.items()):
                if parar():
                    break
                alvo = aba.locator(f'{SEL_CONTAS_LINHA}[data-id="{uuid}"]').first
                if alvo.count():
                    arquivo = pasta / ps.nome_do_print(linha, "erp")
                    alvo.scroll_into_view_if_needed()
                    motivo = _fotografar_linha(aba, alvo, arquivo)
                    saida[linha] = (None, motivo) if motivo else (arquivo, "")
                    del faltam[linha]
            if not faltam or parar():
                break
            proxima = aba.locator(SEL_PROXIMA_PAGINA).first
            if not proxima.count() or not proxima.is_enabled():
                break
            proxima.click()
            aba.wait_for_timeout(1500)
        for linha in faltam:
            saida[linha] = (None, ps.INTERROMPIDA if parar() else NAO_ACHEI)
    except Exception as e:                                   # noqa: BLE001
        motivo = f"print do ERP falhou: {_primeira_linha(e)}"
        log(f"  ERP: {motivo}")
        for linha in faltam:
            saida.setdefault(linha, (None, motivo))
    finally:
        try:
            aba.close()
        except Exception:                                    # noqa: BLE001
            pass
        mc._minhas.discard(aba)
    return saida


def ler(anx, cfg, mapping, contas, pasta, *, log=print, parar=lambda: False,
        agora=_dt.datetime.now, ler_saldos=None, ao_abrir_aba=lambda: None) -> dict:
    """{linha: ps.Leitura do ERP}. Erro do ERP vira motivo em todas as
    linhas (nunca saldo zero) e nenhuma aba é aberta."""
    if ler_saldos is None:
        from . import erp_do_dia
        ler_saldos = erp_do_dia.ler_saldos
    try:
        # A sessão também é do ERP: se ela falhar, é motivo em todas as
        # linhas, e não uma exceção que derrubaria a prova inteira.
        api = anx.garantir_sessao(log)
        contas_erp = ler_saldos(cfg, api, log=log)
    except Exception as e:                                   # noqa: BLE001
        motivo = _primeira_linha(e)
        log(f"  ERP: não li os saldos — {motivo}")
        return {c.linha: ps.Leitura(None, motivo=motivo) for c in contas}
    hora = agora()
    sistema = {ln.linha: ln.sistema for ln in sd.montar_saldos(contas_erp, mapping)}
    da_linha = ps.conta_erp_da_linha(contas_erp, mapping)
    pedidos = [(c.linha, str(getattr(da_linha.get(c.linha), "id", "") or c.erp_id))
               for c in contas]
    prints = fotografar_contas(anx.mc, pedidos, pasta, log=log, parar=parar,
                               ao_abrir_aba=ao_abrir_aba)
    saida = {}
    for c in contas:
        valor = sistema.get(c.linha)
        imagem, sem = prints.get(c.linha, (None, NAO_ACHEI))
        saida[c.linha] = ps.Leitura(valor, hora if valor is not None else None,
                                    "" if valor is not None else SEM_SALDO, imagem, sem)
    return saida
