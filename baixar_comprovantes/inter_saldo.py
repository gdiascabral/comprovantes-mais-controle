# -*- coding: utf-8 -*-
"""O saldo ATUAL de UMA conta do Inter, com print — para a Prova de saldos.

Medido ao vivo em 27/10/2026 (dono leu o QR): a tela inicial
(`inter_baixar.URL_LOGIN`, ".../home") pede `GET {API_INTER}/cc/saldo/v3/` e
recebe JSON com `disponivel` (o "Saldo em conta" da tela),
`chequeEspecialDisponivel` e `disponivelComChequeEspecial`. O texto da tela
traz no alto "Saldo / R$ … / <número da conta> / <NOME DA EMPRESA>".

**O valor é OUVIDO da resposta que a própria tela pede** (`escutar_saldo`);
se ela não pedir em `TEMPO_SALDO`, o pedido é repetido DE DENTRO da página
com os cabeçalhos de sessão que a página usou (`escutar_sessao`: o
`authorization` e os dois `x-inter-*` — só com o primeiro o Inter respondeu
HTTP 412 ao vivo em 29/10/2026). Nunca por fora do navegador. Os cabeçalhos
nunca são gravados nem escritos no Registro.

**Confere a conta antes de usar o número**: o número e o nome da empresa na
tela têm de ser os da linha do painel (`conferir_conta`). Outra conta aberta
= "não lida" com o motivo — nunca o saldo de uma empresa na linha de outra.

Perfil POR CONTA (`inter_baixar.pasta_do_perfil`), o mesmo do Baixar
comprovantes: os dois não rodam juntos (trava em `comprovantes_app.py`). O
Inter pede o QR a cada abertura (conferido em 31/08/2026): quem chama avisa a
tela ANTES (`avisar_qr`), para ela dizer de QUAL conta é o QR.

Só leitura: nada é clicado além do "gerar um novo QR" do `esperar_login`.

**O extrato completo como segunda fonte** (medido em 29/10/2026 numa conta
PJ que mostra o saldo SÓ no extrato): quando a tela inicial não dá o
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

**Menos idas de página (26/11/2026, medido pelas horas dos prints da Prova
de 18 a 25/11: ~2 min nas 3 contas).** Antes, depois do QR o login era
confirmado na tela do Pix (`inter_baixar.esperar_login`), a tela inicial era
aberta DE NOVO e, na conta que só tem saldo no extrato, ia-se ao extrato:
3 a 4 páginas por conta. Agora: (1) o login é confirmado na PRÓPRIA tela
inicial (`esperar_entrar`: sem marca de login e com o número da conta na
tela ou os três cabeçalhos da sessão), e o caminho antigo fica de reserva
quando a tela sai do login e não mostra nada disso em `FOLGA_SEM_SESSAO`;
(2) a conta que da última vez só deu saldo pelo extrato vai DIRETO a ele
(`ler_via`/`gravar_via`, um arquivo ao lado do perfil) e, sem saldo ali,
volta à tela inicial; (3) a resposta do saldo é esperada `TEMPO_SALDO` (12 s,
era 30) antes de pedir de dentro da página; (4) a tela "parada" é olhada a
cada `PASSO_TELA_MS`, até `TEMPO_TELA_PARADA`. O tempo de cada passo vai ao
Registro (`Cronometro`). A conferência da conta e as travas não mudaram.
"""
from __future__ import annotations

import re
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
#: Quanto se espera a tela inicial pedir o saldo antes de pedir de dentro
#: da página (com os cabeçalhos da sessão a resposta é a mesma). Era 30.
TEMPO_SALDO = 12
#: A tela inicial do Inter não termina o "load" em 30 s em algumas contas (a
#: VXZ estourou em 27/10/2026): abre-se no `domcontentloaded`, com folga, e a
#: espera de verdade é a do saldo e a de a tela parar de mudar.
TEMPO_ABRIR_MS = 90000
TEMPO_TELA_PRONTA = 20
#: A tela inicial "parada" (duas leituras iguais, nada carregando) antes do
#: print: no máximo isto, olhando a cada `PASSO_TELA_MS`. Era 20 s, de 1 em 1 s.
TEMPO_TELA_PARADA = 10
PASSO_TELA_MS = 500
#: Saiu do login e não apareceu nem o número da conta nem a sessão em tantos
#: segundos: confirma pelo caminho antigo (a tela do Pix).
FOLGA_SEM_SESSAO = 10
PASSO_LOGIN_MS = 700
#: O que a tela inicial mostra enquanto ainda carrega (os blocos cinza) —
#: medir ao vivo. Enquanto houver um visível, o print espera.
SELETOR_CARREGANDO = '[class*="skeleton" i], [class*="shimmer" i], [class*="loading" i]'
#: A faixa do alto da tela inicial: logo, saldo, número da conta e nome da
#: empresa (medida ao vivo em 29/10/2026; as classes de dentro são geradas e
#: mudam, estas são do Bootstrap). "" = fotografa a parte visível da tela.
SELETOR_AREA_SALDO = "div.col-12 > div.d-flex.justify-content-between"
URL_EXTRATO_COMPLETO = "https://contadigital.inter.co/extrato"
ROTA_EXTRATO_COMPLETO = "/ib-pfj/cc/extrato/bff/v2/home"
TEMPO_EXTRATO = 25
SALDO_DA_CONTA = "DIGITAL_ACCOUNT"
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
async ([url, cabecalhos]) => {
    const r = await fetch(url, {headers: cabecalhos});
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


#: O tipo da empresa no FIM da razão social: a tela do Inter o omite (medido
#: ao vivo em 29/10/2026: "… SPE" na tela, "… SPE LTDA" no cadastro).
_SUFIXO_LEGAL = re.compile(r"(?:\s+(?:LTDA?|S/?A|EIRELI|ME|EPP)\.?)+$")


def sem_sufixo_legal(nome: str) -> str:
    """O nome normalizado sem o tipo da empresa no fim. Só o FIM: "EMPRESA X"
    continua diferente de "EMPRESA X 2 LTDA" (revisão de 27/10/2026)."""
    return _SUFIXO_LEGAL.sub("", util.norm_espaco(nome or "")).strip()


def conferir_conta(texto: str, numero_esperado: str, nomes, razoes=()) -> str:
    """"" quando a tela é da conta pedida; senão, o porquê (vira ⚠).

    Com o número do ERP: o número da tela tem de ser ele, e um dos `nomes`
    tem de aparecer na tela. SEM o número do ERP (revisão de dinheiro de
    27/10/2026): o nome curto não basta — "EMPRESA X" também está dentro de
    "EMPRESA X 2 LTDA"; só vale uma linha da tela IGUAL (normalizada) a uma
    das `razoes` sociais inteiras do cadastro — sem o tipo da empresa no fim
    dos dois lados (`sem_sufixo_legal`), que a tela do Inter não escreve."""
    na_tela = ib.numero_no_texto(texto)
    if not na_tela:
        return SEM_NUMERO
    esperado = _digitos(numero_esperado).lstrip("0")
    if not esperado:
        linhas = {sem_sufixo_legal(ln) for ln in (texto or "").splitlines()}
        inteiras = {sem_sufixo_legal(r) for r in razoes or () if (r or "").strip()}
        linhas.discard("")
        inteiras.discard("")
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


#: Os cabeçalhos que a tela do Inter manda à API (medidos em 29/10/2026 no
#: pedido da exportação do extrato) e os endereços da API que ela chama.
CABECALHOS_DA_SESSAO = ("authorization", "x-inter-conta-corrente", "x-inter-organization")
HOSTS_DA_API = ("cdpj-api.bancointer.com.br", "cd.web.bancointer.com.br")


def cabecalhos_da_sessao(cabecalhos: dict) -> dict:
    """Só os cabeçalhos de sessão de um pedido da página; {} sem o
    `authorization` (pedido que não é da sessão logada)."""
    if not (cabecalhos or {}).get("authorization"):
        return {}
    return {k: cabecalhos[k] for k in CABECALHOS_DA_SESSAO if cabecalhos.get(k)}


def da_api(url: str) -> bool:
    return any(h in (url or "") for h in HOSTS_DA_API)


def escutar_sessao(page) -> dict:
    """Os cabeçalhos de sessão do pedido mais completo que a página fizer à
    API (o dicionário se preenche sozinho). Esvaziar no fim."""
    guardado: dict = {}

    def ouvir(pedido):
        if not da_api(pedido.url):
            return
        achados = cabecalhos_da_sessao(pedido.headers)
        if len(achados) >= len(guardado):
            guardado.clear()
            guardado.update(achados)

    page.on("request", ouvir)
    return guardado


#: "R$ 1.234,56", "-R$ 1.234,56", "R$ -1.234,56": milhar com ponto e SEMPRE
#: dois centavos. Outra forma ("R$ 1.234", sem centavos) não vira número:
#: 1.234 lido como 1,23 seria um saldo falso (revisão de dinheiro, 29/10/2026).
_SALDO_TEXTO = re.compile(r"^(-?)\s*(?:R\$)?\s*(-?)\s*(\d{1,3}(?:\.\d{3})*|\d+),(\d{2})$")


def saldo_do_extrato(corpo) -> Decimal | None:
    """O saldo da conta digital no corpo do extrato completo, ou None."""
    balance = (corpo or {}).get("balance") if isinstance(corpo, dict) else None
    for b in ((balance or {}).get("data") or {}).get("balances") or ():
        if str((b or {}).get("id") or "").upper() == SALDO_DA_CONTA:
            bruto = b.get("available")
            if isinstance(bruto, bool):
                return None
            if isinstance(bruto, (int, float)):
                return Decimal(str(bruto)).quantize(CENTAVO, rounding=ROUND_HALF_UP)
            texto = str(bruto or "").replace("\xa0", " ").replace("\u2212", "-").strip()
            achou = _SALDO_TEXTO.match(texto)
            if not achou:
                return None
            sinal = "-" if (achou[1] or achou[2]) else ""
            return Decimal(f"{sinal}{achou[3].replace('.', '')}.{achou[4]}")
    return None


def escutar_extrato(page) -> list:
    """As respostas do extrato completo que a tela do extrato recebe."""
    ouvidas: list = []

    def ouvir(resposta):
        # Só a rota do extrato (`v2/home`), e só o 200: outra rota do mesmo
        # BFF, ou um JSON de erro, viraria "extrato sem transações" — e a
        # conta passaria por lida com "nada no banco" (revisão de dinheiro).
        if ROTA_EXTRATO_COMPLETO in resposta.url.split("?")[0] and resposta.status == 200:
            ouvidas.append(resposta)

    page.on("response", ouvir)
    return ouvidas


def ler_extrato_completo(page, ouvidas: list, tempo: float | None = None):
    """Abre a tela do extrato e devolve o corpo da resposta que ela pede
    (JSON), ou None se não veio em `tempo`."""
    ouvidas.clear()
    _abrir(page, URL_EXTRATO_COMPLETO)
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
        # 401/403 é o pedido de ANTES do QR (a tela não é recarregada depois
        # do login): fica fora, e sem resposta nova o pedido de dentro da
        # página diz se a sessão vale.
        if (ROTA_SALDO in resposta.url and da_api(resposta.url)
                and resposta.status not in (401, 403)):
            ouvidas.append(resposta)

    page.on("response", ouvir)
    return ouvidas


def _cabecalhos_para_pedir(autorizacao, sessao) -> dict:
    """Os cabeçalhos do pedido de dentro da página: os três da sessão
    (`escutar_sessao`) quando a página já os mandou — só o `authorization`
    deu HTTP 412 ao vivo em 29/10/2026 —, senão o `authorization`."""
    if sessao and sessao.get("authorization"):
        return dict(sessao)
    valor = (autorizacao or {}).get("valor") or ""
    return {"authorization": valor} if valor else {}


def _resposta_do_saldo(page, ouvidas: list, sessao: dict,
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
    if sessao.get("authorization"):
        r = page.evaluate(_JS_SALDO, [URL_SALDO, dict(sessao)]) or {}
        return int(r.get("status") or 0), r.get("dado")
    raise SaldoInterFalhou(f"a tela inicial do Inter não pediu o saldo em {int(tempo)} s "
                           "e não há sessão para pedir de dentro da página")


def tela_parou(anterior: str, atual: str, carregando: bool) -> bool:
    """A tela inicial terminou de montar: nada carregando, o mesmo texto em
    duas leituras seguidas, e o saldo já escrito nela."""
    return (not carregando and bool(atual) and atual == anterior
            and "Saldo" in atual)


def _carregando(page) -> bool:
    try:
        return any(el.is_visible() for el in page.locator(SELETOR_CARREGANDO).all())
    except Exception:                                        # noqa: BLE001
        return False


def esperar_tela_pronta(page, tempo: float = TEMPO_TELA_PARADA) -> bool:
    """Espera a tela inicial parar de carregar antes do print (em 27/10/2026
    o print saiu com metade da tela em blocos cinza). True = parou; False =
    o tempo acabou e o print sai como estiver."""
    limite = time.time() + tempo
    anterior = ""
    while time.time() < limite:
        atual = ib._texto_da_tela(page)
        if tela_parou(anterior, atual, _carregando(page)):
            return True
        anterior = atual
        page.wait_for_timeout(PASSO_TELA_MS)
    return False


def _abrir(page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=TEMPO_ABRIR_MS)


def _fotografar(page, arquivo: Path) -> tuple:
    esperar_tela_pronta(page)
    util.revelar(page, SELETOR_MOSTRAR_SALDO)
    if SELETOR_AREA_SALDO:
        try:
            area = page.locator(SELETOR_AREA_SALDO).first
            pedaco = util.recorte_da_tela(page, area) if area.count() else None
            if pedaco is not None:
                arquivo.parent.mkdir(parents=True, exist_ok=True)
                pedaco[0].save(arquivo)
                return arquivo, ""
        except Exception:                                    # noqa: BLE001
            pass                             # cai no print da tela, abaixo
    motivo = util.fotografar(page, arquivo)
    return (None, motivo) if motivo else (arquivo, "")


class Cronometro:
    """O tempo de cada passo da leitura de uma conta, para o Registro."""

    def __init__(self, relogio=time.monotonic):
        self._relogio = relogio
        self._inicio = self._ultimo = relogio()
        self.passos: list = []

    def marcar(self, nome: str) -> None:
        agora = self._relogio()
        self.passos.append((nome, agora - self._ultimo))
        self._ultimo = agora

    def resumo(self) -> str:
        def seg(s):
            return f"{s:.1f}".replace(".", ",") + " s"
        partes = [f"{nome} {seg(s)}" for nome, s in self.passos]
        partes.append(f"total {seg(self._ultimo - self._inicio)}")
        return " · ".join(partes)


def entrou(texto: str, sessao: dict) -> bool:
    """A tela inicial já é da sessão aberta: nenhuma marca de login e, na
    tela, o número da conta — ou a página já mandou os três cabeçalhos."""
    if not texto or ib.tela_diz(texto, ib.MARCAS_DE_LOGIN):
        return False
    return bool(ib.numero_no_texto(texto)) or all(
        (sessao or {}).get(k) for k in CABECALHOS_DA_SESSAO)


def esperar_entrar(page, sessao: dict, *, tempo: int = ib.TEMPO_LOGIN, log=print,
                   parar=lambda: False, relogio=time.monotonic) -> bool:
    """Espera o QR na tela inicial. True = a sessão abriu ali mesmo; False =
    confirmou pelo caminho antigo (`inter_baixar.esperar_login`, que deixa a
    página na tela do Pix — quem chama abre a tela inicial de novo).
    Levanta `InterFalhou` no Parar e no estouro do tempo."""
    log("Escaneie o QR code com o app do Inter. Eu sigo sozinho depois.")
    limite = relogio() + tempo
    fora_desde = None
    while relogio() < limite:
        if parar():
            raise ib.InterFalhou(ib.PARADO_NO_LOGIN)
        texto = ib._texto_da_tela(page)
        if entrou(texto, sessao):
            log("Sessão aberta.")
            return True
        if ib.TEXTO_QR_VENCIDO in texto:
            try:
                page.get_by_text(ib.TEXTO_QR_VENCIDO, exact=False).first.click()
                log("O QR tinha vencido; gerei outro.")
            except Exception:                                # noqa: BLE001
                pass                     # se não der, o laço segue esperando
        if texto and not ib.tela_diz(texto, ib.MARCAS_DE_LOGIN):
            fora_desde = relogio() if fora_desde is None else fora_desde
            if relogio() - fora_desde >= FOLGA_SEM_SESSAO:
                resto = max(1, int(limite - relogio()))
                ib.esperar_login(page, tempo=resto, log=lambda m: None, parar=parar)
                log("Sessão aberta.")
                return False
        else:
            fora_desde = None
        page.wait_for_timeout(PASSO_LOGIN_MS)
    raise ib.InterFalhou(f"passaram {tempo}s e a sessão do Inter não abriu (o QR "
                         "não foi lido?)")


VIA_EXTRATO = "extrato"


def _arquivo_da_via(apelido: str) -> Path:
    perfil = ib.pasta_do_perfil(apelido)
    return perfil.with_name(perfil.name + ".via.txt")


def ler_via(apelido: str) -> str:
    """Por onde o saldo desta conta veio da última vez ("inicio",
    "extrato" ou "")."""
    try:
        return _arquivo_da_via(apelido).read_text(encoding="utf-8").strip()
    except Exception:                                        # noqa: BLE001
        return ""


def gravar_via(apelido: str, via: str) -> None:
    try:
        _arquivo_da_via(apelido).write_text(via or "", encoding="utf-8")
    except Exception:                                        # noqa: BLE001
        pass                             # só encurta a próxima; nunca para a leitura


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


TEXTO_SALDO_DO_DIA = "Saldo do dia"


def _fotografar_extrato(page, arquivo: Path) -> tuple:
    """Print da tela do Extrato: a faixa do alto (número e empresa) em cima
    da linha "Saldo do dia" mais recente."""
    try:
        linha = page.get_by_text(re.compile(TEXTO_SALDO_DO_DIA)).first
        linha.wait_for(timeout=TEMPO_TELA_PRONTA * 1000)
        page.evaluate("window.scrollTo(0, 0)")
        topo = util.recorte_da_tela(page, page.locator(SELETOR_AREA_SALDO).first)
        linha.scroll_into_view_if_needed()
        dia = util.recorte_da_tela(page, linha)
        if topo and dia:
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            util.empilhar([topo[0], dia[0]]).save(arquivo)
            return arquivo, ""
    except Exception:                                        # noqa: BLE001
        pass                                 # cai no print da tela, abaixo
    motivo = util.fotografar(page, arquivo)
    return (None, motivo) if motivo else (arquivo, "")


def _ler_na_pagina(page, ouvidas, autorizacao, numero_esperado, nomes, razoes,
                   arquivo, *, agora, extratos=None, extra=None,
                   sessao=None, comecar_no_extrato=False,
                   marcar=lambda nome: None) -> LidoInter:
    """Com a sessão aberta na tela inicial: resposta do saldo, CONFERE a
    conta e só então fotografa. Conta errada não tem print (revisão de
    27/10/2026: o print da outra empresa ia para a página desta conta).
    Sem saldo ou sem número na tela inicial, a tela do extrato completo é a
    segunda fonte (ver o docstring do módulo).

    `comecar_no_extrato` (a conta que da última vez só deu saldo ali): o
    extrato é a PRIMEIRA tela; conta conferida e saldo lido, nem passa pela
    inicial. Outra conta aberta para ali; sem saldo ou sem como conferir no
    extrato, volta à tela inicial e segue o caminho de sempre."""
    extratos = extratos if extratos is not None else []
    guardado: dict = {}

    def extrato():
        if "corpo" not in guardado:
            guardado["corpo"] = ler_extrato_completo(page, extratos)
        return guardado["corpo"]

    if comecar_no_extrato:
        corpo = extrato()
        motivo = conferir_conta(ib._texto_da_tela(page), numero_esperado, nomes, razoes)
        if motivo and "outra conta aberta" in motivo:
            return LidoInter(motivo=motivo, sem_imagem=SEM_PRINT_OUTRA_CONTA)
        saldo = None if motivo else saldo_do_extrato(corpo)
        if saldo is not None:
            lido_em = agora()
            marcar("saldo")
            imagem, sem_imagem = _fotografar_extrato(page, Path(arquivo))
            marcar("print")
            return _com_extra(page, autorizacao, extrato, extra, marcar,
                              LidoInter(saldo, lido_em, "", imagem, sem_imagem, VIA_EXTRATO))
        ouvidas.clear()
        _abrir(page, ib.URL_LOGIN)

    try:
        status, dado = _resposta_do_saldo(
            page, ouvidas, _cabecalhos_para_pedir(autorizacao, sessao))
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
    lido_em = agora()          # a hora do SALDO, antes das listas do `extra`
    marcar("saldo")
    if via == "extrato":
        imagem, sem_imagem = _fotografar_extrato(page, Path(arquivo))
    else:
        imagem, sem_imagem = _fotografar(page, Path(arquivo))
    marcar("print")
    return _com_extra(page, autorizacao, extrato, extra, marcar,
                      LidoInter(saldo, lido_em, "", imagem, sem_imagem, via))


def _com_extra(page, autorizacao, extrato, extra, marcar, lido: LidoInter) -> LidoInter:
    """O gancho de quem chamou, na mesma sessão; falha dele não perde o saldo."""
    if extra is None:
        return lido
    resultado, erro = None, ""
    try:
        resultado = extra(page, autorizacao, extrato)
    except Exception as e:                                   # noqa: BLE001
        erro = _primeira_linha(e)
    marcar("listas")
    return LidoInter(lido.saldo, lido.lido_em, "", lido.imagem, lido.sem_imagem, lido.via,
                     resultado, erro)


def _ler_no_chrome(apelido, numero_esperado, nomes, arquivo, *, razoes, log, avisar_qr,
                   agora, tempo_login, parar, ao_entrar, extra=None) -> LidoInter:
    from playwright.sync_api import sync_playwright

    perfil = ib.pasta_do_perfil(apelido)
    perfil.mkdir(parents=True, exist_ok=True)
    crono = Cronometro()
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            str(perfil), channel="chrome", headless=False,
            args=["--start-maximized"], no_viewport=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ouvidas = escutar_saldo(page)
        extratos = escutar_extrato(page)
        autorizacao = ib.escutar_autorizacao(page)
        sessao = escutar_sessao(page)
        try:
            _abrir(page, ib.URL_LOGIN)
            crono.marcar("Chrome")
            avisar_qr(apelido)
            na_inicial = esperar_entrar(page, sessao, tempo=tempo_login, log=log,
                                        parar=parar)
            crono.marcar("QR")
            ao_entrar(apelido)
            direto = ler_via(apelido) == VIA_EXTRATO
            if not na_inicial and not direto:
                ouvidas.clear()
                _abrir(page, ib.URL_LOGIN)
            lido = _ler_na_pagina(page, ouvidas, autorizacao, numero_esperado, nomes,
                                  razoes, arquivo, agora=agora, extratos=extratos,
                                  extra=extra, sessao=sessao, comecar_no_extrato=direto,
                                  marcar=crono.marcar)
            if lido.saldo is not None and lido.via:
                gravar_via(apelido, lido.via)
            log(f"tempos: {crono.resumo()}"
                + (" (direto no extrato)" if lido.via == VIA_EXTRATO and direto else ""))
            return lido
        except (ib.InterFalhou, SaldoInterFalhou) as e:
            return LidoInter(motivo=str(e), sem_imagem="a leitura parou antes do print")
        except Exception as e:                               # noqa: BLE001
            return LidoInter(motivo=f"erro inesperado no Inter: {_primeira_linha(e)}",
                             sem_imagem="a leitura parou antes do print")
        finally:
            sessao.clear()
            try:
                ctx.close()
            except Exception:                                # noqa: BLE001
                log("o Chrome do Inter pode ter ficado aberto — feche-o.")
