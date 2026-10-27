# -*- coding: utf-8 -*-
"""O lado do ERP na Prova de saldos: saldo atual + print da conta.

**Roda na thread da vaga do Anexar** (`anx.submeter(..., dona=tela)`): o
`MCClient` e o Playwright dele só vivem lá. O saldo vem do MESMO caminho do
Buscar (`erp_do_dia.ler_saldos`: porteiro com o central ligado; aba do robô
desligado — nunca login HTTP), casado com as linhas do painel pela régua do
painel (`saldos.montar_saldos`).

**O print** é do cabeçalho da grade `#/accounts` JUNTO com a linha da conta
(React/MUI; cada linha tem `data-id` = UUID da conta; seletores de
`conciliacao/erp/browser.py`, levantados em 10/08/2026): só a linha, sem o
nome das colunas, não provava nada no celular (revisão de 27/10/2026). O
recorte (`recorte`) une as duas caixas; sem cabeçalho visível ou com o
recorte recusado, fica a foto só da linha. Numa aba PRÓPRIA do robô
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


def recorte(cabecalho, linha) -> dict | None:
    """O retângulo que une a caixa do cabeçalho e a da linha (coordenadas da
    tela, `bounding_box` do Playwright); None sem uma das duas ou com o
    cabeçalho fora da tela (rolado para cima)."""
    if not cabecalho or not linha or cabecalho["y"] < 0:
        return None
    x0 = min(cabecalho["x"], linha["x"])
    y0 = min(cabecalho["y"], linha["y"])
    x1 = max(cabecalho["x"] + cabecalho["width"], linha["x"] + linha["width"])
    y1 = max(cabecalho["y"] + cabecalho["height"], linha["y"] + linha["height"])
    return {"x": x0, "y": y0, "width": x1 - x0, "height": y1 - y0}


def _fotografar_linha(aba, alvo, arquivo) -> str:
    """Cabeçalho + linha num recorte da aba; senão, só a linha."""
    try:
        clip = recorte(aba.locator(SEL_CABECALHO_GRADE).first.bounding_box(),
                       alvo.bounding_box())
    except Exception:                                        # noqa: BLE001
        clip = None
    if clip is not None and not util.fotografar(aba, arquivo, clip=clip):
        return ""
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
