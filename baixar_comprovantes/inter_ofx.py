# -*- coding: utf-8 -*-
"""O OFX de UMA conta do Inter num período (aba Conciliação, "Baixar OFX").

Medido ao vivo em 29/10/2026 (dono leu o QR): o botão "Exportar" da tela
do Extrato pede `GET {URL_EXPORTAR}?formato=OFX&data-inicio=DD-MM-AAAA&
data-fim=DD-MM-AAAA` com os três cabeçalhos da sessão da página
(`inter_saldo.escutar_sessao`); a resposta é `{fileUrl}`, um endereço
assinado do S3 que RECUSA `fetch` (CORS), e o arquivo vem como download do
próprio Chrome — por isso a página cria um `<a href=fileUrl>` e o clica. O
OFX traz `ACCTID` = o número da conta que a tela mostra, e o período pedido.

**Confere a conta ANTES de pedir** (`inter_saldo.conferir_conta`): no Inter
quem decide a conta é o celular que lê o QR, não o perfil do Chrome — em
29/10 os perfis da MORAIS ENG e da VXZ abriram um a conta do outro. Conta
errada = nada baixado, com o recado para ler o QR com a empresa certa.

Perfil POR CONTA (`inter_baixar.pasta_do_perfil`), o mesmo do Baixar
comprovantes e da Prova de saldos (a trava é do app). Os cabeçalhos nunca
são gravados nem escritos no Registro.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from . import inter_baixar as ib
from . import inter_saldo

URL_EXPORTAR = "https://cd.web.bancointer.com.br/ib-pfj/cc/extrato/exportar/v2"
TEMPO_DOWNLOAD_MS = 60000
QR_DA_EMPRESA_CERTA = ("leia o QR com a empresa certa escolhida no app do Inter "
                       "do celular")
SEM_SESSAO = ("a página do Inter não abriu a sessão (nenhum pedido com "
              "autorização) — leia o QR de novo")
SEM_ARQUIVO = "o Inter respondeu sem o arquivo do extrato"
NAO_ENTREGOU = "o Inter não entregou o arquivo do extrato a tempo"

_JS_OFX = """
async ([url, cabecalhos]) => {
    const r = await fetch(url, {headers: cabecalhos});
    if (!r.ok) return {status: r.status};
    let j = null;
    try { j = await r.json(); } catch (e) { j = null; }
    if (!j || !j.fileUrl) return {status: r.status, semArquivo: true};
    const a = document.createElement('a');
    a.href = j.fileUrl; a.download = '';
    document.body.appendChild(a); a.click(); a.remove();
    return {status: r.status};
}
"""


@dataclass(frozen=True)
class OfxInter:
    arquivo: Path | None
    numero_na_tela: str = ""        # o número da conta aberta (confere o ACCTID)
    motivo: str = ""


def _primeira_linha(erro) -> str:
    texto = (str(erro or "").strip().splitlines() or [""])[0].strip()
    return texto[:160] or type(erro).__name__


def url_do_ofx(ini, fim) -> str:
    return (f"{URL_EXPORTAR}?formato=OFX&data-inicio={ini:%d-%m-%Y}"
            f"&data-fim={fim:%d-%m-%Y}")


def _baixar_na_pagina(page, sessao, numero_erp, nomes, razoes, ini, fim,
                      arquivo) -> OfxInter:
    texto = ib._texto_da_tela(page)
    motivo = inter_saldo.conferir_conta(texto, numero_erp, nomes, razoes)
    if motivo:
        if "outra conta aberta" in motivo:
            motivo = f"{motivo} — {QR_DA_EMPRESA_CERTA}"
        return OfxInter(None, motivo=motivo)
    na_tela = ib.numero_no_texto(texto)
    if not sessao.get("authorization"):
        return OfxInter(None, na_tela, SEM_SESSAO)
    resposta: dict = {}
    try:
        with page.expect_download(timeout=TEMPO_DOWNLOAD_MS) as espera:
            resposta = page.evaluate(_JS_OFX, [url_do_ofx(ini, fim), dict(sessao)]) or {}
            if resposta.get("status") != 200 or resposta.get("semArquivo"):
                raise _SemDownload()
        arquivo = Path(arquivo)
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        espera.value.save_as(str(arquivo))
    except _SemDownload:
        if resposta.get("semArquivo"):
            return OfxInter(None, na_tela, SEM_ARQUIVO)
        return OfxInter(None, na_tela,
                        f"o Inter respondeu HTTP {resposta.get('status')} ao pedir o extrato")
    except Exception:                                        # noqa: BLE001
        return OfxInter(None, na_tela, NAO_ENTREGOU)
    return OfxInter(arquivo, na_tela, "")


class _SemDownload(Exception):
    """A API recusou: não há download para esperar."""


def baixar_conta(apelido: str, numero_erp: str, nomes, razoes, ini, fim, arquivo, *,
                 log=print, avisar_qr=lambda apelido: None, parar=lambda: False,
                 tempo_login: int = ib.TEMPO_LOGIN) -> OfxInter:
    """Abre o Chrome no perfil da conta, espera o QR, confere a conta e
    baixa o OFX do período. Nunca levanta: o desfecho vem no `OfxInter`."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:                                   # noqa: BLE001
        return OfxInter(None, motivo=f"o Chrome do Inter não abriu: {_primeira_linha(e)}")
    try:
        perfil = ib.pasta_do_perfil(apelido)
        perfil.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(
                str(perfil), channel="chrome", headless=False,
                args=["--start-maximized"], no_viewport=True, accept_downloads=True)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            sessao = inter_saldo.escutar_sessao(page)
            try:
                inter_saldo._abrir(page, ib.URL_LOGIN)
                avisar_qr(apelido)
                ib.esperar_login(page, tempo=tempo_login, log=log, parar=parar)
                inter_saldo._abrir(page, ib.URL_LOGIN)
                inter_saldo.esperar_tela_pronta(page)
                return _baixar_na_pagina(page, sessao, numero_erp, nomes, razoes,
                                         ini, fim, arquivo)
            except ib.InterFalhou as e:
                return OfxInter(None, motivo=str(e))
            except Exception as e:                           # noqa: BLE001
                return OfxInter(None, motivo=f"erro inesperado no Inter: {_primeira_linha(e)}")
            finally:
                sessao.clear()
                try:
                    ctx.close()
                except Exception:                            # noqa: BLE001
                    log("o Chrome do Inter pode ter ficado aberto — feche-o.")
    except Exception as e:                                   # noqa: BLE001
        return OfxInter(None, motivo=f"o Chrome do Inter não abriu: {_primeira_linha(e)}")
