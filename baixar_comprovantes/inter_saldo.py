# -*- coding: utf-8 -*-
"""O saldo ATUAL de UMA conta do Inter, com print — para a Prova de saldos.

Medido ao vivo em 27/10/2026 (dono leu o QR): a tela inicial
(`inter_baixar.URL_LOGIN`, ".../home") pede `GET {API_INTER}/cc/saldo/v3/` e
recebe JSON com `disponivel` (o "Saldo em conta" da tela),
`chequeEspecialDisponivel` e `disponivelComChequeEspecial`. O texto da tela
traz no alto "Saldo / R$ … / <número da conta> / <NOME DA EMPRESA>".

**O valor é OUVIDO da resposta que a própria tela pede** (`escutar_saldo`);
se ela não pedir em `TEMPO_SALDO`, o pedido é repetido DE DENTRO da página
com o cabeçalho de sessão que a página usou (`inter_baixar.
escutar_autorizacao`). Nunca por fora do navegador. O cabeçalho nunca é
gravado nem escrito no Registro.

**Confere a conta antes de usar o número**: o número e o nome da empresa na
tela têm de ser os da linha do painel (`conferir_conta`). Outra conta aberta
= "não lida" com o motivo — nunca o saldo de uma empresa na linha de outra.

Perfil POR CONTA (`inter_baixar.pasta_do_perfil`), o mesmo do Baixar
comprovantes: os dois não rodam juntos (trava em `comprovantes_app.py`). O
Inter pede o QR a cada abertura (conferido em 31/08/2026): quem chama avisa a
tela ANTES (`avisar_qr`), para ela dizer de QUAL conta é o QR.

Só leitura: nada é clicado além do "gerar um novo QR" do `esperar_login`.

**O extrato completo como segunda fonte** (medido em 29/10/2026 na MORAIS
ENG, que mostra o saldo SÓ no extrato): quando a tela inicial não dá o
saldo, ou não mostra o número da conta para conferir, a leitura vai à tela
do extrato (`URL_EXTRATO_COMPLETO`) e ouve a resposta que ELA pede
(`ROTA_EXTRATO_COMPLETO`): o saldo vem em `balance.data.balances[
DIGITAL_ACCOUNT].available` (`saldo_do_extrato`) e a conta é conferida pelo
texto daquela tela. O mesmo corpo serve ao "Autenticar no banco" (`extra`).

**`extra(page, autorizacao, extrato)`**: quem chama pode usar a MESMA sessão
(um QR por conta) depois de a conta ser conferida — o "Autenticar no banco"
lista ali o Pix, a 2ª via e o extrato completo. `extrato()` devolve o corpo
do extrato completo (lido uma vez só). Falha do `extra` não perde o saldo:
vem no `LidoInter.extra_erro`.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path

import util

from . import inter_baixar as ib

ROTA_SALDO = "/cc/saldo/v3/"
URL_SALDO = ib.API_INTER + ROTA_SALDO
CAMPO = "disponivel"
CENTAVO = Decimal("0.01")
TEMPO_SALDO = 30
URL_EXTRATO_COMPLETO = "https://contadigital.inter.co/extrato"
ROTA_EXTRATO_COMPLETO = "/ib-pfj/cc/extrato/bff/"
TEMPO_EXTRATO = 25
SALDO_DA_CONTA = "DIGITAL_ACCOUNT"
#: Seletor da área do saldo na tela inicial (medir ao vivo, Tarefa 8);
#: "" = fotografa a parte visível da tela.
SELETOR_AREA_SALDO = ""
#: Botão "mostrar saldo" (o olho) da tela inicial, se o saldo vier
#: mascarado — medir ao vivo (Tarefa 8). "" = não clica.
SELETOR_MOSTRAR_SALDO = ""
SEM_PRINT_OUTRA_CONTA = "sem print: a conta aberta era outra"
SEM_PRINT_SEM_CONFERIR = "sem print: não deu para conferir de quem era a conta aberta"
SEM_NUMERO = ("não achei o número da conta na tela inicial do Inter — não "
              "leio o saldo sem saber de quem é")
SEM_COMO_CONFERIR = ("o ERP não tem o número desta conta Inter — confira o "
                     "cadastro (sem ele, só a razão social inteira na tela "
                     "confere a conta aberta)")

_JS_SALDO = """
async ([url, cabecalho]) => {
    const r = await fetch(url, {headers: {Authorization: cabecalho}});
    let dado = null;
    try { dado = await r.json(); } catch (e) { dado = null; }
    return {status: r.status, dado};
}
"""


class SaldoInterFalhou(RuntimeError):
    """O saldo desta conta do Inter não foi lido; a mensagem diz o porquê."""


@dataclass(frozen=True)
class LidoInter:
    saldo: Decimal | None = None
    lido_em: datetime | None = None
    motivo: str = ""
    imagem: Path | None = None
    sem_imagem: str = ""
    #: De onde veio o saldo: "inicio" (a tela inicial) ou "extrato".
    via: str = ""
    #: O que o `extra` de quem chamou devolveu (ou o porquê de ter falhado).
    extra: object = None
    extra_erro: str = ""


def _digitos(texto) -> str:
    return "".join(ch for ch in str(texto or "") if ch.isdigit())


def _primeira_linha(erro) -> str:
    texto = (str(erro or "").strip().splitlines() or [""])[0].strip()
    return texto[:160] or type(erro).__name__


def saldo_da_resposta(status: int, dado) -> Decimal:
    if status in (401, 403):
        raise SaldoInterFalhou(f"a sessão do Inter não vale mais (HTTP {status}) — "
                               "leia o QR de novo")
    if status != 200:
        raise SaldoInterFalhou(f"o Inter respondeu HTTP {status} ao pedir o saldo")
    if not isinstance(dado, dict) or CAMPO not in dado:
        raise SaldoInterFalhou("a resposta do saldo do Inter veio sem 'disponivel' — "
                               "o formato do banco mudou")
    valor = dado[CAMPO]
    if isinstance(valor, bool) or not isinstance(valor, (int, float, str, Decimal)):
        raise SaldoInterFalhou(f"o saldo do Inter veio como {valor!r}, que não é número")
    try:
        d = Decimal(str(valor))
    except InvalidOperation:
        raise SaldoInterFalhou(f"o saldo do Inter veio como {str(valor)[:30]!r}, "
                               "que não é número") from None
    if not d.is_finite():
        raise SaldoInterFalhou("o saldo do Inter veio como um número inválido")
    return d.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def conferir_conta(texto: str, numero_esperado: str, nomes, razoes=()) -> str:
    """"" quando a tela é da conta pedida; senão, o porquê (vira ⚠).

    Com o número do ERP: o número da tela tem de ser ele, e um dos `nomes`
    tem de aparecer na tela. SEM o número do ERP (revisão de dinheiro de
    27/10/2026): o nome curto não basta — "EMPRESA X" também está dentro de
    "EMPRESA X 2 LTDA"; só vale uma linha da tela IGUAL (normalizada) a uma
    das `razoes` sociais inteiras do cadastro."""
    na_tela = ib.numero_no_texto(texto)
    if not na_tela:
        return SEM_NUMERO
    esperado = _digitos(numero_esperado).lstrip("0")
    if not esperado:
        linhas = {util.norm_espaco(ln) for ln in (texto or "").splitlines()}
        inteiras = {util.norm_espaco(r) for r in razoes or () if (r or "").strip()}
        return "" if linhas & inteiras else SEM_COMO_CONFERIR
    if _digitos(na_tela).lstrip("0") != esperado:
        return (f"a tela do Inter está na conta {na_tela}, e a desta linha do "
                f"painel é {numero_esperado} — outra conta aberta, não leio")
    validos = [util.norm_espaco(n) for n in nomes or () if (n or "").strip()]
    if validos:
        tela = util.norm_espaco(texto)
        if not any(n in tela for n in validos):
            return ("o nome da empresa na tela do Inter não é o desta conta ("
                    + ", ".join(n for n in nomes if (n or "").strip())
                    + ") — outra conta aberta, não leio")
    return ""


def saldo_do_extrato(corpo) -> Decimal | None:
    """O saldo da conta digital no corpo do extrato completo, ou None."""
    balance = (corpo or {}).get("balance") if isinstance(corpo, dict) else None
    for b in ((balance or {}).get("data") or {}).get("balances") or ():
        if str((b or {}).get("id") or "").upper() == SALDO_DA_CONTA:
            texto = str(b.get("available") or "").replace("R$", "").replace("\xa0", " ")
            texto = texto.strip()
            negativo = texto.startswith("-")
            texto = texto.lstrip("-").strip()
            if "," in texto:
                texto = texto.replace(".", "").replace(",", ".")
            try:
                d = Decimal(texto).quantize(CENTAVO, rounding=ROUND_HALF_UP)
            except (InvalidOperation, ValueError):
                return None
            return -d if negativo else d
    return None


def escutar_extrato(page) -> list:
    """As respostas do extrato completo que a tela do extrato recebe."""
    ouvidas: list = []

    def ouvir(resposta):
        if ROTA_EXTRATO_COMPLETO in resposta.url:
            ouvidas.append(resposta)

    page.on("response", ouvir)
    return ouvidas


def ler_extrato_completo(page, ouvidas: list, tempo: float | None = None):
    """Abre a tela do extrato e devolve o corpo da resposta que ela pede
    (JSON), ou None se não veio em `tempo`."""
    ouvidas.clear()
    page.goto(URL_EXTRATO_COMPLETO)
    limite = time.time() + (TEMPO_EXTRATO if tempo is None else tempo)
    while time.time() < limite and not ouvidas:
        page.wait_for_timeout(500)
    for resposta in reversed(ouvidas):
        try:
            corpo = resposta.json()
        except Exception:                                    # noqa: BLE001
            continue
        if isinstance(corpo, dict):
            return corpo
    return None


def escutar_saldo(page) -> list:
    """As respostas do saldo que a própria tela recebe (o objeto, e não o
    corpo: o corpo é lido depois, fora do evento)."""
    ouvidas: list = []

    def ouvir(resposta):
        if ROTA_SALDO in resposta.url and "cdpj-api" in resposta.url:
            ouvidas.append(resposta)

    page.on("response", ouvir)
    return ouvidas


def _resposta_do_saldo(page, ouvidas: list, autorizacao: dict,
                       tempo: float = TEMPO_SALDO) -> tuple:
    limite = time.time() + tempo
    while time.time() < limite and not ouvidas:
        page.wait_for_timeout(500)
    if ouvidas:
        resposta = ouvidas[-1]
        try:
            return resposta.status, resposta.json()
        except Exception:                                    # noqa: BLE001
            return resposta.status, None
    if autorizacao.get("valor"):
        r = page.evaluate(_JS_SALDO, [URL_SALDO, autorizacao["valor"]]) or {}
        return int(r.get("status") or 0), r.get("dado")
    raise SaldoInterFalhou(f"a tela inicial do Inter não pediu o saldo em {int(tempo)} s "
                           "e não há sessão para pedir de dentro da página")


def _fotografar(page, arquivo: Path) -> tuple:
    util.revelar(page, SELETOR_MOSTRAR_SALDO)
    alvo = page
    if SELETOR_AREA_SALDO:
        area = page.locator(SELETOR_AREA_SALDO).first
        if area.count():
            alvo = area
    motivo = util.fotografar(alvo, arquivo)
    return (None, motivo) if motivo else (arquivo, "")


def ler_conta(apelido: str, numero_esperado: str, nomes, arquivo: Path, *,
              razoes=(), log=print, avisar_qr=lambda apelido: None, agora=datetime.now,
              tempo_login: int = ib.TEMPO_LOGIN, parar=lambda: False,
              ao_entrar=lambda apelido: None, extra=None) -> LidoInter:
    """Abre o Chrome no perfil da conta, espera o QR, confere a conta, lê o
    `disponivel` e fotografa. Nunca levanta: o desfecho vem no `LidoInter`."""
    try:
        return _ler_no_chrome(apelido, numero_esperado, nomes, arquivo, razoes=razoes,
                              log=log,
                              avisar_qr=avisar_qr, agora=agora,
                              tempo_login=tempo_login, parar=parar, ao_entrar=ao_entrar,
                              extra=extra)
    except Exception as e:                                   # noqa: BLE001
        # O Chrome nem abriu (perfil preso, Chrome ausente): o desfecho ainda
        # vem no `LidoInter`, e não numa exceção que derrubaria a rodada.
        return LidoInter(motivo=f"o Chrome do Inter não abriu: {_primeira_linha(e)}",
                         sem_imagem="a leitura parou antes do print")


def _ler_na_pagina(page, ouvidas, autorizacao, numero_esperado, nomes, razoes,
                   arquivo, *, agora, extratos=None, extra=None) -> LidoInter:
    """Com a sessão aberta na tela inicial: resposta do saldo, CONFERE a
    conta e só então fotografa. Conta errada não tem print (revisão de
    27/10/2026: o print da outra empresa ia para a página desta conta).
    Sem saldo ou sem número na tela inicial, a tela do extrato completo é a
    segunda fonte (ver o docstring do módulo)."""
    extratos = extratos if extratos is not None else []
    guardado: dict = {}

    def extrato():
        if "corpo" not in guardado:
            guardado["corpo"] = ler_extrato_completo(page, extratos)
        return guardado["corpo"]

    try:
        status, dado = _resposta_do_saldo(page, ouvidas, autorizacao)
    except SaldoInterFalhou as e:
        status, dado, erro_inicio = None, None, e
    else:
        erro_inicio = None
    motivo = conferir_conta(ib._texto_da_tela(page), numero_esperado, nomes, razoes)
    no_extrato = False
    if motivo == SEM_NUMERO:
        extrato()
        no_extrato = True
        motivo = conferir_conta(ib._texto_da_tela(page), numero_esperado, nomes, razoes)
    if motivo:
        sem = (SEM_PRINT_OUTRA_CONTA if "outra conta aberta" in motivo
               else SEM_PRINT_SEM_CONFERIR)
        return LidoInter(motivo=motivo, sem_imagem=sem)
    via = "inicio"
    try:
        if erro_inicio is not None:
            raise erro_inicio
        saldo = saldo_da_resposta(status, dado)
    except SaldoInterFalhou as e:
        saldo = saldo_do_extrato(extrato())
        if saldo is None:
            raise e
        via = "extrato"
        if not no_extrato:
            extrato()
    imagem, sem_imagem = _fotografar(page, Path(arquivo))
    resultado, erro = None, ""
    if extra is not None:
        try:
            resultado = extra(page, autorizacao, extrato)
        except Exception as e:                               # noqa: BLE001
            erro = _primeira_linha(e)
    return LidoInter(saldo, agora(), "", imagem, sem_imagem, via, resultado, erro)


def _ler_no_chrome(apelido, numero_esperado, nomes, arquivo, *, razoes, log, avisar_qr,
                   agora, tempo_login, parar, ao_entrar, extra=None) -> LidoInter:
    from playwright.sync_api import sync_playwright

    perfil = ib.pasta_do_perfil(apelido)
    perfil.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(perfil), channel="chrome", headless=False,
            args=["--start-maximized"], no_viewport=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ouvidas = escutar_saldo(page)
        extratos = escutar_extrato(page)
        autorizacao = ib.escutar_autorizacao(page)
        try:
            page.goto(ib.URL_LOGIN)
            avisar_qr(apelido)
            ib.esperar_login(page, tempo=tempo_login, log=log, parar=parar)
            ao_entrar(apelido)
            ouvidas.clear()
            page.goto(ib.URL_LOGIN)
            return _ler_na_pagina(page, ouvidas, autorizacao, numero_esperado, nomes,
                                  razoes, arquivo, agora=agora, extratos=extratos,
                                  extra=extra)
        except (ib.InterFalhou, SaldoInterFalhou) as e:
            return LidoInter(motivo=str(e), sem_imagem="a leitura parou antes do print")
        except Exception as e:                               # noqa: BLE001
            return LidoInter(motivo=f"erro inesperado no Inter: {_primeira_linha(e)}",
                             sem_imagem="a leitura parou antes do print")
        finally:
            autorizacao["valor"] = ""
            try:
                ctx.close()
            except Exception:                                # noqa: BLE001
                log("o Chrome do Inter pode ter ficado aberto — feche-o.")
