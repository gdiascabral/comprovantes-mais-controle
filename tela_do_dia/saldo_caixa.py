# -*- coding: utf-8 -*-
"""O saldo ATUAL das contas da Caixa, com print — para a Prova de saldos.

Medido ao vivo em 26/11/2026 (o dono entrou no Gerenciador CAIXA, segmento
Empresas): UM login vê as contas das empresas. Ao abrir o Painel de Controle
(`.../empresa/dashboard`) a própria tela pede

- `GET /sinbc-gerenciador-pj/nb/listarContas` — JSON com `conta[]`: `agencia`
  ("01234"), `tipo` ("1292"), `numero` ("000123456789-0"), `chaveRecurso`,
  `selecionada` e `cpfcnpj` (o CNPJ da empresa dona da conta);
- `POST /SIIBC/pcResumoContasConsultar.processa` — HTML do "Resumo de Saldos
  Consolidados por Conta": uma linha por conta ("1234 1292 123456789-0") com
  Saldo Bloqueado, Saldo Disponível s/ Limite, Saldo Disponível e Total;
- `GET /sinbc-saldo/nb/consultaTodosSaldos` — o "Saldo atual" e o "Saldo
  disponível" da conta SELECIONADA ("0,00 C").

**O saldo comparado é o "Saldo atual": só a conta corrente.** Conta com
aplicação automática mostra, no resumo, a conta MAIS o que a aplicação
devolve na hora (medido: "Saldo atual" R$ 0,00 e o resumo com o dinheiro da
aplicação). No ERP a aplicação é outra conta (dono, 26/11/2026: "tem a parte
mesmo"), então o resumo faria a linha da conta corrente sair "não bate" com
tudo certo. O valor do resumo vai como NOTA no PDF, ao lado do print dele.

**Como se lê o "Saldo atual" de cada conta**: de dentro da página, o mesmo
que o menu de contas faz — `POST /sinbc/nb/selecionaConta` (só a sessão) e o
`consultaTodosSaldos` com o `Authorization` que a própria página manda (o
token do login, OUVIDO dos pedidos dela, nunca gravado). No fim, a conta que
estava selecionada volta a ser a selecionada. Nada é clicado e o endereço
nunca é digitado depois do login (25/11/2026: no Gerenciador CAIXA, navegar
por URL derruba a sessão). A Caixa aceita UMA sessão por usuário: entrar
noutro navegador derruba esta.

**Conta incerta não bate**: o CNPJ da linha do painel tem de ter UMA conta no
login (e, se o ERP tiver o número da conta, ele tem de bater), a troca de
conta tem de ter caído na conta pedida e o valor tem de se ler em centavos.
Senão, ⚠ com o porquê — nunca o saldo de uma empresa na linha de outra. O
número nunca sai do print.
"""
from __future__ import annotations

import html as _html
import re
import time
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import util

from .prova_saldos import Leitura, digitos
from .valores import brl

URL_ENTRADA = "https://gerenciador.caixa.gov.br/"
HOST = "gerenciador.caixa.gov.br"
PAINEL = "/empresa/dashboard"
ROTA_CONTAS = "/sinbc-gerenciador-pj/nb/listarContas"
ROTA_RESUMO = "/SIIBC/pcResumoContasConsultar.processa"
ROTA_SELECIONA = "/sinbc/nb/selecionaConta"
ROTA_SALDO = "/sinbc-saldo/nb/consultaTodosSaldos"
#: O cartão "Saldos Consolidados por Conta" do Painel (medido em 26/11/2026).
SELETOR_CARTAO = "app-card-saldos-contas"
COLUNA = "SALDO DISPONIVEL S/ LIMITE"
SALDO_ATUAL = "SALDO ATUAL"
TEMPO_LOGIN = 300               # segundos para a pessoa entrar
TEMPO_RESUMO = 60               # segundos para o painel trazer as respostas
TEMPO_ABRIR_MS = 90000
NOME_DO_PRINT = "caixa banco.png"

LOGIN_ESGOTADO = ("o login da Caixa não terminou em {} minutos — entre de novo "
                  "pela Prova de saldos")
FECHADO = "o Chrome da Caixa foi fechado antes de ler o saldo"
PARADO = "parado pelo botão Parar antes de ler a Caixa"
SEM_RESUMO = ("o Painel de Controle da Caixa não trouxe a lista de contas em "
              "{} s")
FORMATO = "a Caixa respondeu num formato que não conheço ({})"
FORA_DO_LOGIN = "nenhuma conta deste CNPJ aparece no login da Caixa"
NUMERO_NAO_BATE = ("a conta {} do ERP não aparece no login da Caixa (o login vê "
                   "outra conta desta empresa)")
DUAS_CONTAS = ("a empresa tem mais de uma conta neste login da Caixa — não sei "
               "qual é a desta linha")
SEM_SALDO = "não li o saldo atual da conta {} na Caixa: {}"
SEM_VALOR = "o saldo atual da conta {} na Caixa veio como {!r}, que não leio"
NOTA = ("o quadro do banco mostra {} nesta conta: é a conta mais a aplicação "
        "automática ou o que está bloqueado — a prova compara só o saldo atual "
        "da conta ({})")
SESSAO = "a sessão da Caixa não vale mais (HTTP {}) — entre de novo"


class CaixaFalhou(RuntimeError):
    """A leitura da Caixa parou; a mensagem diz o porquê."""


@dataclass(frozen=True)
class ContaCaixa:
    chave: str          # agência-tipo-número, sem zeros à esquerda
    numero: str         # como a Caixa escreve, sem os zeros da frente
    documento: str      # CNPJ da dona, só dígitos
    recurso: str = ""   # `chaveRecurso`: o que a troca de conta pede
    selecionada: bool = False


def chave(agencia, tipo, numero) -> str:
    def sem_zero(t):
        return digitos(t).lstrip("0") or "0"
    return f"{sem_zero(agencia)}-{sem_zero(tipo)}-{sem_zero(numero)}"


def contas_do_login(dado) -> list[ContaCaixa]:
    """As contas que o login vê, da resposta do `listarContas`."""
    if not isinstance(dado, dict) or not isinstance(dado.get("conta"), list):
        raise CaixaFalhou(FORMATO.format("lista de contas sem 'conta'"))
    saida = []
    for c in dado["conta"]:
        if not isinstance(c, dict) or not digitos(c.get("numero")):
            continue
        numero = str(c.get("numero") or "").strip().lstrip("0")
        saida.append(ContaCaixa(chave(c.get("agencia"), c.get("tipo"), c.get("numero")),
                                numero, digitos(c.get("cpfcnpj")),
                                str(c.get("chaveRecurso") or ""),
                                c.get("selecionada") is True))
    return saida


#: "R$ 1.234,56", "-R$ 1.234,56", "R$ -1.234,56", "1.234,56 D": milhar com
#: ponto e SEMPRE dois centavos (a régua do texto do Inter: "R$ 1.234" sem
#: centavos lido como 1,23 seria um saldo falso).
_VALOR = re.compile(r"^(-?)\s*(?:R\$)?\s*(-?)\s*(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})\s*([CD]?)$")


def valor(texto) -> Decimal | None:
    t = str(texto or "").replace("\xa0", " ").replace("−", "-").strip().upper()
    m = _VALOR.match(t)
    if not m:
        return None
    menos = bool(m.group(1) or m.group(2)) or m.group(5) == "D"
    d = Decimal(f"{m.group(3).replace('.', '')}.{m.group(4)}")
    return -d if menos else d


def saldo_atual(dado) -> str:
    """O texto do "Saldo atual" na resposta do `consultaTodosSaldos`."""
    itens = dado.get("consultaLancamentoBean") if isinstance(dado, dict) else None
    if not isinstance(itens, list):
        raise CaixaFalhou(FORMATO.format("saldo sem 'consultaLancamentoBean'"))
    achados = [i.get("valor") for i in itens
               if isinstance(i, dict) and util.norm_espaco(str(i.get("descricao") or "")) == SALDO_ATUAL]
    if len(achados) != 1:
        raise CaixaFalhou(FORMATO.format(f"{len(achados)} 'Saldo atual' na resposta"))
    return str(achados[0] or "")


_LINHA = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.S | re.I)
_CELULA = re.compile(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")


def _texto(celula: str) -> str:
    return util.norm_espaco(_html.unescape(_TAG.sub(" ", celula)))


def saldos_do_resumo(html: str) -> dict:
    """{chave da conta: texto da coluna "Saldo Disponível s/ Limite"} — só
    para a NOTA do PDF. Sem o cabeçalho, ou com linha de conta de outra
    largura, levanta. Conta em duas linhas com textos diferentes: None."""
    cabecalho = None
    saida: dict = {}
    for linha in _LINHA.findall(html or ""):
        celulas = [_texto(c) for c in _CELULA.findall(linha)]
        if cabecalho is None:
            if COLUNA in celulas:
                cabecalho = celulas
            continue
        partes = (celulas[0].split() if celulas else [])
        if len(partes) != 3 or not all(p.replace("-", "").isdigit() for p in partes):
            continue                       # "Saldo total (R$)" e afins
        if len(celulas) != len(cabecalho):
            raise CaixaFalhou(FORMATO.format("linha do resumo com outra largura"))
        k, texto = chave(*partes), celulas[cabecalho.index(COLUNA)]
        saida[k] = texto if saida.get(k, texto) == texto else None
    if cabecalho is None:
        raise CaixaFalhou(FORMATO.format("resumo sem 'Saldo Disponível s/ Limite'"))
    return saida


def conta_da_linha(documento: str, numero_erp: str, contas) -> tuple:
    """(ContaCaixa, "") ou (None, porquê)."""
    delas = [c for c in contas if c.documento == documento]
    if not delas:
        return None, FORA_DO_LOGIN
    alvo = digitos(numero_erp).lstrip("0")
    if alvo:
        delas = [c for c in delas if digitos(c.numero).lstrip("0") == alvo]
        if not delas:
            return None, NUMERO_NAO_BATE.format(numero_erp)
    if len(delas) > 1:
        return None, DUAS_CONTAS
    return delas[0], ""


def leituras(documentos: dict, contas, atuais: dict, resumo: dict, *,
             lido_em: datetime, imagem: Path | None, sem_imagem: str = "") -> dict:
    """{CNPJ: Leitura}. `documentos` = {CNPJ: número que o ERP tem da conta
    ("" = não tem)}; `atuais` = {chave: texto do Saldo atual, ou
    CaixaFalhou com o porquê}; `resumo` só vira nota."""
    saida = {}
    for doc, numero_erp in documentos.items():
        conta, porque = conta_da_linha(doc, numero_erp, contas)
        if conta is None:
            saida[doc] = Leitura(None, motivo=porque)
            continue
        lido = atuais.get(conta.chave, CaixaFalhou("a conta não foi lida"))
        if isinstance(lido, Exception):
            saida[doc] = Leitura(None, motivo=SEM_SALDO.format(conta.numero, lido))
            continue
        saldo = valor(lido)
        if saldo is None:
            saida[doc] = Leitura(None, motivo=SEM_VALOR.format(conta.numero, lido))
            continue
        no_quadro = valor(resumo.get(conta.chave))
        nota = (NOTA.format(brl(no_quadro), brl(saldo))
                if no_quadro is not None and no_quadro != saldo else "")
        saida[doc] = Leitura(saldo, lido_em, "", imagem, sem_imagem, nota)
    return saida


# --------------------------------------------------------------- navegador
_JS_SELECIONA = """
async ([recurso]) => {
    const corpo = new URLSearchParams({chaveConta: recurso, userAgent: navigator.userAgent,
                                       versaoPlugin: '', retornoF10: ''});
    const r = await fetch('%s', {method: 'POST', body: corpo, headers: {
        'content-type': 'application/x-www-form-urlencoded; charset=UTF-8',
        'x-requested-with': 'XMLHttpRequest'}});
    let dado = null;
    try { dado = await r.json(); } catch (e) { dado = null; }
    const marcada = ((dado || {}).contas || []).find(c => c.selecionada === true);
    return {status: r.status, marcada: marcada ? String(marcada.chaveRecurso || '') : ''};
}
""" % ROTA_SELECIONA

_JS_SALDO = """
async ([token]) => {
    const r = await fetch('%s', {headers: token ? {Authorization: token} : {}});
    let dado = null;
    try { dado = await r.json(); } catch (e) { dado = null; }
    return {status: r.status, dado};
}
""" % ROTA_SALDO


def _primeira_linha(erro) -> str:
    texto = (str(erro or "").strip().splitlines() or [""])[0].strip()
    return texto[:160] or type(erro).__name__


def escutar(page) -> dict:
    """As respostas da lista de contas e do resumo que a tela recebe (o
    objeto; o corpo é lido depois, fora do evento) e o `Authorization` mais
    recente dos pedidos dela. Esvaziar o token no fim."""
    ouvidas: dict = {"contas": [], "resumo": [], "token": ""}

    def ouvir(resposta):
        url = resposta.url or ""
        if HOST not in url:
            return
        if ROTA_CONTAS in url:
            ouvidas["contas"].append(resposta)
        elif ROTA_RESUMO in url:
            ouvidas["resumo"].append(resposta)

    def pedido(req):
        if HOST in (req.url or ""):
            token = (req.headers or {}).get("authorization") or ""
            if token.lower().startswith("bearer "):
                ouvidas["token"] = token

    page.on("response", ouvir)
    page.on("request", pedido)
    return ouvidas


def _no_painel(page) -> bool:
    try:
        return PAINEL in (page.url or "")
    except Exception:                                        # noqa: BLE001
        return False


def esperar_painel(page, ouvidas, *, tempo_login, tempo_resumo, parar, log):
    """Espera a pessoa entrar (a tela chega ao Painel de Controle) e o
    painel trazer a lista de contas, o resumo e o token."""
    limite = time.time() + tempo_login
    avisou = False
    while not _no_painel(page):
        if parar():
            raise CaixaFalhou(PARADO)
        if page.is_closed():
            raise CaixaFalhou(FECHADO)
        if time.time() > limite:
            raise CaixaFalhou(LOGIN_ESGOTADO.format(max(1, tempo_login // 60)))
        if not avisou:
            log("entre no Gerenciador CAIXA (Empresas) no Chrome que abriu")
            avisou = True
        page.wait_for_timeout(500)
    limite = time.time() + tempo_resumo
    while not (ouvidas["contas"] and ouvidas["resumo"] and ouvidas["token"]):
        if parar():
            raise CaixaFalhou(PARADO)
        if page.is_closed():
            raise CaixaFalhou(FECHADO)
        if time.time() > limite:
            if not ouvidas["contas"]:
                raise CaixaFalhou(SEM_RESUMO.format(tempo_resumo))
            break                     # sem resumo ou token: lê o que der
        page.wait_for_timeout(500)


def _corpo(resposta, como: str):
    if resposta.status in (401, 403):
        raise CaixaFalhou(SESSAO.format(resposta.status))
    if resposta.status != 200:
        raise CaixaFalhou(f"a Caixa respondeu HTTP {resposta.status} ao pedir {como}")
    return resposta.json() if como == "a lista de contas" else resposta.text()


def _selecionar(page, recurso: str) -> None:
    r = page.evaluate(_JS_SELECIONA, [recurso]) or {}
    if int(r.get("status") or 0) in (401, 403):
        raise CaixaFalhou(SESSAO.format(r.get("status")))
    if r.get("marcada") != recurso:
        raise CaixaFalhou("a Caixa não trocou para esta conta "
                          f"(HTTP {r.get('status')})")


def ler_atuais(page, contas, token: str, parar) -> dict:
    """{chave: texto do Saldo atual, ou CaixaFalhou}, conta por conta, e a
    conta que estava selecionada volta a ser a selecionada."""
    saida: dict = {}
    original = next((c.recurso for c in contas if c.selecionada), "")
    try:
        for c in contas:
            if parar():
                saida[c.chave] = CaixaFalhou(PARADO)
                continue
            try:
                _selecionar(page, c.recurso)
                r = page.evaluate(_JS_SALDO, [token]) or {}
                status = int(r.get("status") or 0)
                if status in (401, 403):
                    raise CaixaFalhou(SESSAO.format(status))
                if status != 200:
                    raise CaixaFalhou(f"a Caixa respondeu HTTP {status} ao pedir o saldo")
                saida[c.chave] = saldo_atual(r.get("dado"))
            except CaixaFalhou as e:
                saida[c.chave] = e
            except Exception as e:                           # noqa: BLE001
                saida[c.chave] = CaixaFalhou(_primeira_linha(e))
    finally:
        if original:
            try:
                _selecionar(page, original)
            except Exception:                                # noqa: BLE001
                pass                  # o saldo já lido vale; a tela fecha a seguir
    return saida


def _fotografar(page, arquivo: Path) -> tuple:
    try:
        cartao = page.locator(SELETOR_CARTAO).first
        cartao.wait_for(timeout=20000)
        cartao.scroll_into_view_if_needed()
        page.wait_for_timeout(800)
        pedaco = util.recorte_da_tela(page, cartao)
        if pedaco is not None:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            pedaco[0].save(arquivo)
            return arquivo, ""
    except Exception:                                        # noqa: BLE001
        pass                                 # cai no print da tela, abaixo
    motivo = util.fotografar(page, arquivo)
    return (None, motivo) if motivo else (arquivo, "")


def ler(documentos: dict, pasta: Path, *, parar=lambda: False, log=print,
        agora=datetime.now, tempo_login: int = TEMPO_LOGIN,
        tempo_resumo: int = TEMPO_RESUMO) -> dict:
    """{CNPJ: Leitura} das contas pedidas ({CNPJ: número do ERP ou ""}), num
    login só. Nunca levanta: a falha vira a mesma ⚠ em todas, com o porquê."""
    documentos = {d: n for d, n in dict(documentos).items() if d}
    if not documentos:
        return {}
    try:
        return _ler_no_chrome(documentos, Path(pasta), parar=parar, log=log, agora=agora,
                              tempo_login=tempo_login, tempo_resumo=tempo_resumo)
    except CaixaFalhou as e:
        motivo = str(e)
    except Exception as e:                                   # noqa: BLE001
        motivo = f"o Chrome da Caixa parou: {_primeira_linha(e)}"
    return {d: Leitura(None, motivo=motivo, sem_imagem="a leitura parou antes do print")
            for d in documentos}


def _ler_no_chrome(documentos, pasta, *, parar, log, agora, tempo_login, tempo_resumo):
    from playwright.sync_api import sync_playwright

    perfil = util.pasta_do_perfil("caixa")
    perfil.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(perfil), channel="chrome", headless=False,
            args=["--start-maximized"], no_viewport=True)
        ouvidas: dict = {"token": ""}
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ouvidas = escutar(page)
            page.goto(URL_ENTRADA, wait_until="domcontentloaded", timeout=TEMPO_ABRIR_MS)
            esperar_painel(page, ouvidas, tempo_login=tempo_login,
                           tempo_resumo=tempo_resumo, parar=parar, log=log)
            contas = contas_do_login(_corpo(ouvidas["contas"][-1], "a lista de contas"))
            resumo: dict = {}
            if ouvidas["resumo"]:
                try:
                    resumo = saldos_do_resumo(_corpo(ouvidas["resumo"][-1], "o resumo"))
                except CaixaFalhou as e:
                    log(f"sem a nota do quadro: {e}")
            pedidas = []
            for doc, numero in documentos.items():
                conta, _ = conta_da_linha(doc, numero, contas)
                if conta is not None:
                    pedidas.append(conta)
            atuais = ler_atuais(page, pedidas, ouvidas["token"], parar)
            lido_em = agora()
            imagem, sem_imagem = _fotografar(page, pasta / NOME_DO_PRINT)
            log(f"{len(contas)} conta(s) no login; saldo atual lido de "
                f"{sum(1 for v in atuais.values() if not isinstance(v, Exception))} "
                f"de {len(pedidas)}")
            return leituras(documentos, contas, atuais, resumo, lido_em=lido_em,
                            imagem=imagem, sem_imagem=sem_imagem)
        finally:
            ouvidas["token"] = ""
            try:
                ctx.close()
            except Exception:                                # noqa: BLE001
                log("o Chrome da Caixa pode ter ficado aberto — feche-o.")
