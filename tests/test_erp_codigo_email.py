# -*- coding: utf-8 -*-
"""O código de autenticação do ERP, lido no e-mail (04/11/2026). Sem Gmail e
sem navegador: o IMAP e a página são dublês."""
import email.message
import imaplib
import time

import pytest

from erp import central, codigo_email, login_principal, login_tela
from erp.sessao import ErpErro

HTML = ("<html><body><p>Olá! Use o código abaixo para entrar:</p>"
        "<h1 style='x'>482 913</h1><h2>482913</h2>"
        "<p>CNPJ 12.345.678/0001-90 · (48) 3333-4444</p></body></html>")


def _acesso(tmp_path):
    (tmp_path / "_central").mkdir(exist_ok=True)
    return central.Acesso("principal", tmp_path / "_central" / "perfis" / "principal", 9230,
                          tmp_path / "_central" / "principal.login.dat")


def _arquivo(tmp_path, texto):
    arq = tmp_path / "_chaves" / "gmail-principal.txt"
    arq.parent.mkdir(exist_ok=True)
    arq.write_text(texto, encoding="utf-8")
    return arq


# ------------------------------------------------------------------ e-mail


def test_extrai_o_codigo_depois_de_codigo_abaixo_e_nao_o_cnpj():
    assert codigo_email.extrair_codigo(HTML) == "482913"
    assert codigo_email.extrair_codigo("seu código abaixo: 5 9 6 1 6 4") == "596164"
    assert codigo_email.extrair_codigo("nada aqui") is None


# ----------------------------------------------------------------- arquivo


def test_arquivo_fica_em_chaves_ao_lado_da_central(tmp_path, monkeypatch):
    monkeypatch.delenv("MC_CODIGO_EMAIL_ARQUIVO", raising=False)
    a = _acesso(tmp_path)
    assert codigo_email.arquivo_do_acesso(a) == tmp_path / "_chaves" / "gmail-principal.txt"
    monkeypatch.setenv("MC_CODIGO_EMAIL_ARQUIVO", str(tmp_path / "outro.txt"))
    assert codigo_email.arquivo_do_acesso(a) == tmp_path / "outro.txt"


def test_le_o_arquivo_com_e_sem_a_linha_do_email(tmp_path):
    arq = _arquivo(tmp_path, "# comentário\nrobo@gmail.com\nabcd efgh ijkl mnop\n")
    assert codigo_email.ler_arquivo(arq) == ("robo@gmail.com", "abcdefghijklmnop")
    arq.write_text("abcd efgh ijkl mnop", encoding="utf-8")
    assert codigo_email.ler_arquivo(arq, "login@gmail.com") == ("login@gmail.com", "abcdefghijklmnop")
    with pytest.raises(codigo_email.CodigoErro) as e:
        codigo_email.ler_arquivo(arq)
    assert "abcd" not in str(e.value)                 # a senha nunca vai na mensagem
    arq.write_text("# só comentário\n", encoding="utf-8")
    assert codigo_email.ler_arquivo(arq) is None
    assert codigo_email.ler_arquivo(tmp_path / "nao-existe.txt") is None


# -------------------------------------------------------------------- IMAP


def _bruto(corpo):
    m = email.message.EmailMessage()
    m["From"] = "nao-responda@auth.maiscontroleerp.com.br"
    m["Subject"] = "Seu código de autenticação chegou"
    m.set_content(corpo, subtype="html")
    return m.as_bytes()


class _Imap:
    def __init__(self, emails, senha_ok="certa"):
        self.emails, self.senha_ok, self.chamadas = emails, senha_ok, []
    def __call__(self, host, porta, timeout=None):
        self.chamadas.append(("abrir", host, porta))
        return self
    def login(self, conta, senha):
        if senha != self.senha_ok:
            raise imaplib.IMAP4.error("AUTHENTICATIONFAILED")
    def select(self, caixa, readonly=False):
        self.chamadas.append(("select", caixa, readonly))
    def search(self, _charset, criterio):
        self.chamadas.append(("search", criterio))
        return "OK", [b" ".join(str(i + 1).encode() for i in range(len(self.emails)))]
    def fetch(self, num, partes):
        self.chamadas.append(("fetch", partes))
        quando, corpo = self.emails[int(num) - 1]
        data = time.strftime('%d-%b-%Y %H:%M:%S +0000', time.gmtime(quando))
        return "OK", [(f'1 (INTERNALDATE "{data}" BODY[] {{1}}'.encode(), _bruto(corpo)), b")"]
    def logout(self):
        self.chamadas.append(("logout",))


def test_le_so_os_codigos_novos_e_so_lendo(tmp_path):
    agora = time.time()
    imap = _Imap([(agora - 3600, "código abaixo 111111"),
                  (agora + 5, "código abaixo 222222"),
                  (agora + 20, "código abaixo 333333")])
    assert codigo_email.codigos_novos("r@gmail.com", "certa", agora, abrir=imap) == ["333333", "222222"]
    assert ("select", "INBOX", True) in imap.chamadas
    assert all("PEEK" in c[1] for c in imap.chamadas if c[0] == "fetch")
    assert any("maiscontroleerp.com.br" in c[1] for c in imap.chamadas if c[0] == "search")


def test_senha_de_app_recusada_vira_erro_claro_sem_a_senha():
    with pytest.raises(codigo_email.CodigoErro) as e:
        codigo_email.codigos_novos("r@gmail.com", "errada123", time.time(), abrir=_Imap([]))
    assert "apppasswords" in str(e.value) and "errada123" not in str(e.value)


def test_esperar_pula_o_codigo_ja_usado_e_desiste_no_prazo():
    t = [0.0]
    usados = {"111111"}
    cod = codigo_email.esperar_codigo("c", "s", 0, usados, ler=lambda *a: ["111111", "222222"],
                                      dormir=lambda s: t.__setitem__(0, t[0] + s),
                                      relogio=lambda: t[0])
    assert cod == "222222" and "222222" in usados
    nada = codigo_email.esperar_codigo("c", "s", 0, usados, prazo=30, ler=lambda *a: ["222222"],
                                       dormir=lambda s: t.__setitem__(0, t[0] + s),
                                       relogio=lambda: t[0])
    assert nada is None


# ------------------------------------------------------------------ a tela


class _Loc:
    def __init__(self, page, n=1):
        self.page, self.n = page, n
    def count(self): return self.n
    def nth(self, _i): return self
    def get_attribute(self, _nome): return "6"
    @property
    def first(self): return self
    def fill(self, valor): self.page.digitados.append(valor)
    def filter(self, **_k): return _Loc(self.page, 0)
    def check(self, **_k): pass
    def click(self, **_k): pass


class _Pag:
    """Página na tela do código; aceita o código `aceita` (None = nenhum)."""
    def __init__(self, aceita=None):
        self.url, self.aceita, self.digitados = "https://acessar.maiscontroleerp.com.br/#/mfa", aceita, []
        self.keyboard = self
    def locator(self, _sel): return _Loc(self)
    def get_by_label(self, _r): return _Loc(self, 0)
    def get_by_text(self, _r): return _Loc(self, 0)
    def wait_for_timeout(self, _ms): pass
    def press(self, tecla):
        if self.digitados and self.digitados[-1] == self.aceita:
            self.url = "https://acessar.maiscontroleerp.com.br/#/app/dashboard"


def test_a_tela_do_codigo_e_fora_para_todo_mundo():
    p = _Pag()
    assert login_tela.na_tela_de_codigo(p)
    assert login_tela.tem_sinal_de_login(p) and login_tela.tem_sinal_forte(p)
    from anexar import mc_client
    assert mc_client.MCClient._tem_sinal_de_login(p)


def test_passa_o_codigo_e_tenta_o_proximo_quando_recusado(tmp_path, monkeypatch):
    monkeypatch.delenv("MC_CODIGO_EMAIL_ARQUIVO", raising=False)
    a = _acesso(tmp_path)
    _arquivo(tmp_path, "r@gmail.com\nsenha\n")
    fila = ["111111", "222222"]
    pag = _Pag(aceita="222222")
    t = [0.0]
    log = []
    codigo_email.passar_codigo(pag, a, 0, log=log.append,
                               esperar=lambda *a, **k: fila.pop(0),
                               dormir=lambda s: t.__setitem__(0, t[0] + s), relogio=lambda: t[0])
    assert pag.digitados == ["111111", "222222"] and "/mfa" not in pag.url
    assert any("aceito" in m for m in log)
    assert not any("222222" in m for m in log)         # o código não vai para o log


def test_sem_o_arquivo_diz_onde_colar(tmp_path, monkeypatch):
    monkeypatch.delenv("MC_CODIGO_EMAIL_ARQUIVO", raising=False)
    with pytest.raises(codigo_email.CodigoErro) as e:
        codigo_email.passar_codigo(_Pag(), _acesso(tmp_path), 0, esperar=lambda *a, **k: "1")
    assert "_chaves/gmail-principal.txt" in str(e.value)


def test_codigo_que_nao_chega_vira_erro(tmp_path, monkeypatch):
    monkeypatch.delenv("MC_CODIGO_EMAIL_ARQUIVO", raising=False)
    _arquivo(tmp_path, "r@gmail.com\nsenha\n")
    with pytest.raises(codigo_email.CodigoErro, match="não chegou"):
        codigo_email.passar_codigo(_Pag(), _acesso(tmp_path), 0, esperar=lambda *a, **k: None)


# ------------------------------------------------- o login principal com MFA


class _PagLogin:
    def __init__(self):
        self.url = ""
    def goto(self, url, **_k):
        if "/mfa" not in self.url or "dashboard" in url:
            self.url = url
    def locator(self, _sel):
        raise RuntimeError("sem DOM no dublê")      # tem_sinal_de_login trata como "não"


def test_login_principal_passa_pelo_codigo(monkeypatch):
    pag = _PagLogin()
    def disparar(page, *_a, **_k):
        page.url = "https://acessar.maiscontroleerp.com.br/#/mfa"
        return True
    monkeypatch.setattr(login_tela, "entrar_pelo_controller", disparar)
    chamado = []
    def codigo(page, desde, email):
        chamado.append(email)
        page.url = "https://acessar.maiscontroleerp.com.br/#/app/dashboard"
        return True
    login_principal._entrar("principal", pag, lambda: ("r@gmail.com", "x"), lambda m: None,
                            lambda s: None, time.monotonic, codigo)
    assert chamado == ["r@gmail.com"] and pag.url.endswith("#/app/dashboard")


def test_login_principal_sem_quem_passe_o_codigo_diz_isso(monkeypatch):
    pag = _PagLogin()
    def disparar(page, *_a, **_k):
        page.url = "https://acessar.maiscontroleerp.com.br/#/mfa"
        return True
    monkeypatch.setattr(login_tela, "entrar_pelo_controller", disparar)
    with pytest.raises(ErpErro, match="código de autenticação"):
        login_principal._entrar("principal", pag, lambda: ("r@gmail.com", "x"), lambda m: None,
                                lambda s: None, time.monotonic, lambda *a: False)
