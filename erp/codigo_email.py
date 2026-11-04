# -*- coding: utf-8 -*-
"""O CÓDIGO DE AUTENTICAÇÃO do ERP, lido no e-mail e digitado na tela #/mfa.

Por que existe (04/11/2026): o Chrome central reiniciou às 06:31 e o ERP
pediu, além da senha, o código que manda por e-mail ("Seu código de
autenticação chegou", válido por 5 min). O porteiro preenchia a senha, a tela
de senha sumia e ele escrevia "ok" no porteiro.log — mas a aba estava parada
em `#/mfa`. Os robôs das 07:00 às 10:00 falharam todos até alguém digitar o
código à mão. Agora:

- `#/mfa` conta como FORA (`login_tela.tem_sinal_de_login`): ninguém mais diz
  "ok" com a aba na tela do código;
- quem entra pela tela (o porteiro, o login principal) lê o código no Gmail
  da conta por IMAP, com uma SENHA DE APP do Google, e digita.

A senha de app fica num arquivo de texto que a PESSOA cola (regra da pasta
do servidor: chaves e tokens a pessoa cola direto no arquivo; o código nunca
imprime, nunca loga e nunca manda para o diagnóstico o que está nele):

    <pasta do servidor>\\_chaves\\gmail-<acesso>.txt     (padrão)
    MC_CODIGO_EMAIL_ARQUIVO=<caminho>                     (outro lugar)

Formato: uma linha com o Gmail que recebe o código e outra com a senha de app
(16 letras; os espaços não importam). Sem a linha do e-mail, vale o e-mail do
login do ERP. Linha começando com # é comentário.

Só LEITURA no Gmail (`BODY.PEEK`, caixa aberta em `readonly`): nenhum e-mail
é marcado, movido ou apagado.

FORA DO EXE: este módulo usa `imaplib`, que o motor não embute. Quem o chama
importa tarde e trata o `ImportError` como "não sei passar o código" — no app
de mesa a tela do código continua sendo da pessoa, como sempre foi.

COMANDOS (a partir da raiz do repositório, com o Python da máquina):
    python -m erp.codigo_email testar --acesso principal
        confere o arquivo e entra no Gmail (só lê; não mostra a senha)
"""
from __future__ import annotations

import email
import html
import imaplib
import os
import re
import time
import unicodedata
from pathlib import Path

from erp.login_tela import na_tela_de_codigo

IMAP_SERVIDOR = ("imap.gmail.com", 993)
#: O remetente muda de subdomínio (`auth.`), por isso só o domínio.
REMETENTE = "maiscontroleerp.com.br"
#: Quanto esperar o e-mail chegar depois do pedido.
PRAZO_EMAIL = 150.0
#: Antes de olhar o Gmail pela 1ª vez (o e-mail leva alguns segundos).
ESPERA_INICIAL = 6.0
#: Entre uma olhada e outra.
INTERVALO = 6.0
#: Relógio do Gmail × relógio da máquina: e-mail recebido até isto ANTES do
#: pedido ainda vale.
FOLGA = 45.0
#: Depois de digitar, quanto esperar a tela sair do #/mfa.
PRAZO_ACEITE = 20.0

SEL_CAMPO_CODIGO = ("input:visible:not([type=checkbox]):not([type=radio])"
                    ":not([type=hidden]):not([type=password]):not([type=email])")
_BOTAO_CONFIRMAR = re.compile(
    r"validar|confirmar|autenticar|verificar|continuar|entrar|acessar|enviar", re.I)
_BOTAO_NAO = re.compile(r"reenviar|voltar|cancelar", re.I)
_BOTAO_REENVIAR = re.compile(r"reenviar|enviar novamente|novo c[oó]digo", re.I)
_LEMBRAR = re.compile(r"lembr|confi|dispositivo", re.I)


class CodigoErro(Exception):
    """Não deu para passar pelo código. A mensagem é para gente leiga e
    nunca carrega senha nem código."""


def _calado(_msg: str) -> None:
    pass


# ------------------------------------------------------ o arquivo da senha


def arquivo_do_acesso(acesso) -> Path:
    """Onde a pessoa cola o Gmail e a senha de app deste acesso."""
    fora = (os.environ.get("MC_CODIGO_EMAIL_ARQUIVO") or "").strip()
    if fora:
        return Path(fora)
    base = Path(acesso.credencial).parent if getattr(acesso, "credencial", None) \
        else Path(acesso.perfil).parent
    # <servidor>\_central\principal.login.dat -> <servidor>\_chaves\gmail-principal.txt
    return base.parent / "_chaves" / f"gmail-{acesso.nome}.txt"


def ler_arquivo(caminho: Path, email_do_login: str = "") -> tuple[str, str] | None:
    """(gmail, senha_de_app) do arquivo, ou None se não existe / está vazio.

    Levanta `CodigoErro` (sem o conteúdo) se o arquivo existe mas não dá para
    entender."""
    try:
        texto = Path(caminho).read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        return None
    except OSError as e:
        raise CodigoErro(f"não consegui ler {Path(caminho).name} ({type(e).__name__})") from None
    conta, senha = "", ""
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        if "@" in linha and not conta:
            conta = linha
        elif not senha:
            senha = re.sub(r"\s+", "", linha)
    if not senha:
        return None
    conta = conta or email_do_login
    if "@" not in conta:
        raise CodigoErro(f"{Path(caminho).name}: falta a linha com o Gmail que "
                         "recebe o código")
    return conta, senha


# ------------------------------------------------------------- o e-mail


def _sem_acento(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper()


def extrair_codigo(texto: str) -> str | None:
    """O código do e-mail "Seu código de autenticação chegou". O corpo é HTML:
    tira as tags e pega o 1º número de 6 dígitos (4 a 8 como recuo) DEPOIS de
    "código abaixo" — evita CNPJ e telefone do rodapé."""
    t = re.sub(r"(?is)<(style|script)[^>]*>.*?</\1>", " ", str(texto or ""))
    t = re.sub(r"<[^>]+>", " ", t)
    t = _sem_acento(html.unescape(t))
    i = t.find("CODIGO ABAIXO")
    trecho = t[i:] if i >= 0 else t
    for padrao in (r"(?<![\d.,/-])(\d{6})(?![\d.,/-])",
                   r"(?<![\d.,/-])(\d{4,8})(?![\d.,/-])"):
        m = re.search(padrao, trecho)
        if m:
            return m.group(1)
    m = re.search(r"(?<!\d)((?:\d ){5}\d)(?!\d)", trecho)     # "5 9 6 1 6 4"
    return m.group(1).replace(" ", "") if m else None


def _corpo(bruto: bytes) -> str:
    msg = email.message_from_bytes(bruto)
    partes = []
    for parte in (msg.walk() if msg.is_multipart() else [msg]):
        if parte.get_content_type() in ("text/html", "text/plain"):
            try:
                carga = parte.get_payload(decode=True) or b""
                partes.append(carga.decode(parte.get_content_charset() or "utf-8", "replace"))
            except Exception:
                pass
    return "\n".join(partes)


def _data_imap(epoch: float) -> str:
    meses = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep",
             "Oct", "Nov", "Dec")
    t = time.gmtime(epoch)
    return f"{t.tm_mday:02d}-{meses[t.tm_mon - 1]}-{t.tm_year}"


def _entrar_no_gmail(conta: str, senha: str, abrir):
    m = abrir(*IMAP_SERVIDOR, timeout=30)
    try:
        m.login(conta, senha)
    except imaplib.IMAP4.error:
        try:
            m.logout()
        except Exception:
            pass
        raise CodigoErro(
            f"o Gmail recusou a senha de app de {conta} — gere outra em "
            "myaccount.google.com/apppasswords (a verificação em duas etapas "
            "precisa estar ligada) e cole no arquivo") from None
    return m


def codigos_novos(conta: str, senha: str, desde: float, *, abrir=imaplib.IMAP4_SSL) -> list[str]:
    """Os códigos dos e-mails do ERP recebidos DEPOIS de `desde` (epoch, com
    `FOLGA`), do mais novo para o mais velho. Só leitura."""
    m = _entrar_no_gmail(conta, senha, abrir)
    try:
        m.select("INBOX", readonly=True)
        _, d = m.search(None, f'(FROM "{REMETENTE}" SINCE {_data_imap(desde - 86400)})')
        saida = []
        for num in reversed((d[0] or b"").split()[-15:]):          # mais novo primeiro
            _, dados = m.fetch(num, "(INTERNALDATE BODY.PEEK[])")
            cab = next((x for x in dados if isinstance(x, tuple)), None)
            if not cab:
                continue
            quando = imaplib.Internaldate2tuple(cab[0])
            if quando is None or time.mktime(quando) < desde - FOLGA:
                break                                  # daqui para trás é velho
            cod = extrair_codigo(_corpo(cab[1]))
            if cod:
                saida.append(cod)
        return saida
    finally:
        try:
            m.logout()
        except Exception:
            pass


def esperar_codigo(conta: str, senha: str, desde: float, usados: set, *,
                   prazo: float = PRAZO_EMAIL, ler=codigos_novos,
                   dormir=time.sleep, relogio=time.time, log=_calado) -> str | None:
    """O código mais novo ainda não usado, esperando até `prazo`; None se não
    chegou. Erro de rede: tenta de novo; senha recusada: `CodigoErro`."""
    fim = relogio() + prazo
    dormir(ESPERA_INICIAL)
    while True:
        try:
            for cod in ler(conta, senha, desde):
                if cod not in usados:
                    usados.add(cod)
                    return cod
        except CodigoErro:
            raise
        except Exception as e:
            log(f"código do e-mail: leitura do Gmail falhou ({type(e).__name__}) — tento de novo")
        if relogio() >= fim:
            return None
        dormir(INTERVALO)


# ------------------------------------------------------------- digitar


def _digitar(page, codigo: str) -> None:
    campos = page.locator(SEL_CAMPO_CODIGO)
    n = campos.count()
    caixas = 0
    for i in range(n):
        try:
            if (campos.nth(i).get_attribute("maxlength") or "") == "1":
                caixas += 1
        except Exception:
            pass
    if caixas >= 4:                                   # uma caixinha por dígito
        for i, dig in enumerate(codigo[:caixas]):
            campos.nth(i).click()
            campos.nth(i).press_sequentially(dig, delay=40)
    elif n:
        campos.first.fill(codigo)
    else:
        page.keyboard.type(codigo, delay=40)
    try:                                              # "confiar neste dispositivo"
        lembrar = page.get_by_label(_LEMBRAR)
        if lembrar.count():
            lembrar.first.check(timeout=2000)
    except Exception:
        pass
    page.wait_for_timeout(500)
    if not na_tela_de_codigo(page):                   # telas que já enviam sozinhas
        return
    bt = page.locator("button:visible, input[type=submit]:visible") \
        .filter(has_text=_BOTAO_CONFIRMAR).filter(has_not_text=_BOTAO_NAO)
    if bt.count():
        bt.first.click()
    else:
        page.keyboard.press("Enter")


def _escolher_email_se_pedir(page) -> None:
    """Tela de escolha do canal antes do código: e-mail, depois enviar."""
    if page.locator(SEL_CAMPO_CODIGO).count():
        return
    try:
        page.get_by_text(re.compile(r"e-?mail", re.I)).first.click(timeout=4000)
        page.wait_for_timeout(800)
        bt = page.locator("button:visible").filter(
            has_text=re.compile(r"enviar|continuar|receber", re.I))
        if bt.count():
            bt.first.click()
        page.wait_for_timeout(1500)
    except Exception:
        pass


def _reenviar(page) -> bool:
    try:
        bt = page.locator("button:visible, a:visible").filter(has_text=_BOTAO_REENVIAR)
        if bt.count():
            bt.first.click()
            return True
    except Exception:
        pass
    return False


def _saiu_do_codigo(page, prazo: float, dormir, relogio) -> bool:
    fim = relogio() + prazo
    while relogio() < fim:
        if not na_tela_de_codigo(page):
            return True
        dormir(1.0)
    return not na_tela_de_codigo(page)


def passar_codigo(page, acesso, desde: float, *, email_do_login: str = "",
                  log=_calado, esperar=esperar_codigo, dormir=time.sleep,
                  relogio=time.time) -> None:
    """Na tela #/mfa: lê o código no Gmail, digita e confirma. Volta quando a
    tela saiu do #/mfa; senão levanta `CodigoErro` com o motivo.

    `desde` é o instante (epoch) de ANTES do pedido de login: e-mail mais
    velho que isso é de outro login e não vale."""
    arq = arquivo_do_acesso(acesso)
    dados = ler_arquivo(arq, email_do_login)
    if dados is None:
        raise CodigoErro(
            "o ERP pediu o código de autenticação do e-mail e falta a senha de "
            f"app do Gmail em {arq.parent.name}/{arq.name} — veja o "
            "'GRAVAR SENHA DO GMAIL DO PORTEIRO'")
    conta, senha = dados
    _escolher_email_se_pedir(page)
    usados: set = set()
    reenviou = False
    for tentativa in range(1, 4):
        codigo = esperar(conta, senha, desde, usados, log=log)
        if codigo is None and not reenviou and _reenviar(page):
            reenviou = True
            log("código do e-mail: não chegou — pedi para reenviar")
            desde = relogio()
            codigo = esperar(conta, senha, desde, usados, log=log)
        if codigo is None:
            raise CodigoErro("o ERP pediu o código de autenticação, mas o "
                             f"e-mail não chegou ao Gmail em {PRAZO_EMAIL:.0f} s")
        _digitar(page, codigo)
        del codigo
        if _saiu_do_codigo(page, PRAZO_ACEITE, dormir, relogio):
            log(f"código do e-mail digitado e aceito (tentativa {tentativa})")
            return
        log(f"código do e-mail: o ERP não aceitou (tentativa {tentativa}) — "
            "busco o próximo")
    raise CodigoErro("o ERP não aceitou o código de autenticação do e-mail "
                     "(3 tentativas)")


# -------------------------------------------------------------- comandos


def testar(acesso, *, abrir=imaplib.IMAP4_SSL, email_do_login: str = "") -> str:
    """Confere o arquivo e entra no Gmail. Devolve uma linha para a pessoa
    (sem a senha)."""
    arq = arquivo_do_acesso(acesso)
    dados = ler_arquivo(arq, email_do_login)
    if dados is None:
        raise CodigoErro(f"{arq} não existe ou está vazio — cole nele o Gmail "
                         "e a senha de app")
    conta, senha = dados
    m = _entrar_no_gmail(conta, senha, abrir)
    try:
        m.select("INBOX", readonly=True)
        _, d = m.search(None, f'(FROM "{REMETENTE}" SINCE {_data_imap(time.time() - 7 * 86400)})')
        n = len((d[0] or b"").split())
    finally:
        try:
            m.logout()
        except Exception:
            pass
    return (f"ok: entrei no Gmail {conta}; {n} e-mail(s) do Mais Controle nos "
            "últimos 7 dias. O porteiro já consegue ler o código.")


def _email_do_login(acesso) -> str:
    try:
        from erp import login_tela
        creds = login_tela.credencial_do_acesso(acesso)
        return creds[0] if creds else ""
    except Exception:
        return ""


def main(argv=None) -> int:
    import argparse
    import sys

    from erp import central
    p = argparse.ArgumentParser(prog="python -m erp.codigo_email")
    p.add_argument("comando", choices=["testar", "onde"])
    p.add_argument("--acesso", default="principal")
    args = p.parse_args(argv)
    acessos = central.carregar_acessos()
    a = acessos.get(args.acesso)
    if a is None:
        print(f"acesso '{args.acesso}' não existe", file=sys.stderr)
        return 2
    if args.comando == "onde":
        print(arquivo_do_acesso(a))
        return 0
    try:
        print(testar(a, email_do_login=_email_do_login(a)))
        return 0
    except CodigoErro as e:
        print(f"FALHOU: {e}")
        return 1
    except Exception as e:
        print(f"FALHOU: {type(e).__name__} ao falar com o Gmail")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
