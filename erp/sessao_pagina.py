# -*- coding: utf-8 -*-
"""Pedidos ao ERP pela aba do Chrome central — sem login nenhum.

Regra do dono (14/10/2026): o ERP é acessado SEMPRE pelo Chrome do app. Esta
classe é o que `erp.Sessao.logar` devolve quando o modo central está ligado
(`erp/central.py`): uma aba própria no Chrome central, numa thread própria, que
copia a autenticação do tráfego da tela e faz `fetch` de dentro da página.

Playwright sync só pode ser tocado pela thread que o criou. Por isso TODO
pedido, venha de que thread vier, passa por uma fila até a thread dona.

O CICLO DE VIDA
---------------
A thread dona entra na `AbaCentral`, liga o ouvinte de requests, navega para
`URL_CAPTURA` e fica no laço: tira um pedido da fila ou, sem pedido, deixa o
Playwright respirar (`wait_for_timeout`) para os eventos de request chegarem.
Ninguém fica pendurado: quando ela sai — por `fechar()` ou porque a aba
morreu —, todo `Future` que ainda estiver na fila recebe `ErpErro`, e quem
chamar `pedir` depois disso recebe o mesmo erro na hora.

A TELA DE LOGIN NÃO É DESISTÊNCIA (28/10/2026)
-----------------------------------------------
Até aqui esta aba nunca entrava: caindo no login, desistia com "o porteiro
precisa entrar". No notebook não há porteiro, e ela nascia em CORRIDA com o
login da aba do Anexar (diagnostico.log do dono, 22 a 28/10). Agora:

1. ANTES de navegar, pede o LOGIN PRINCIPAL (`erp.login_principal`): logado,
   volta na hora; fora, espera a única aba que entra (sob as travas);
2. caindo mesmo assim na tela de login (a sessão caiu no meio, ou o 401),
   RECARREGA a rota de captura a cada `_RECARGA_NO_LOGIN` s — pega o login
   que outra aba do MESMO Chrome fez;
3. só depois de `_SO_RECARGA` s sem ninguém entrar, pede o login principal
   de novo (`caiu=True`) e relê a autenticação do tráfego.

Esta aba nunca entra sozinha, e nunca por `POST /users/login` (derrubaria a
sessão do Chrome).
"""
from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as _PrazoFuture
from urllib.parse import urlsplit

from . import central, hosts, login_tela
from .pagina import TransportePagina
from .sessao import ErpErro, SessaoRecusada

URL_CAPTURA = "https://acessar.maiscontroleerp.com.br/#/payable-installments"
_CHAVES = {"authorization", "company-id", "user-id", "organization-unit-id"}
_PRAZO_PEDIDO = 300.0
#: Quanto a recaptura do 401 espera a tela voltar a chamar os dois hosts.
_PRAZO_RECAPTURA = 30.0
#: Quanto a tela de login precisa ficar à vista para valer: nos primeiros
#: segundos o ERP a mostra mesmo com sessão boa (o Firebase restaura o token
#: do IndexedDB de forma assíncrona) — o MCClient espera 2,5 s pelo mesmo motivo.
_CARENCIA_LOGIN = 3.0
#: Na tela de login, de quanto em quanto recarregar a rota de captura (pega o
#: login que outra aba do mesmo Chrome acabou de fazer).
_RECARGA_NO_LOGIN = 5.0
#: Quanto tempo só recarregando antes de pedir o login principal.
_SO_RECARGA = 15.0
#: Depois do login principal, quanto esperar a tela chamar os dois hosts.
_PRAZO_LOGIN = 90.0
#: Folga do Playwright entre um pedido e outro (é nela que os eventos chegam).
_RESPIRO_MS = 200
#: Para a thread dona sair, e `fechar()` não esperar para sempre por ela.
_PRAZO_SAIDA = 15.0
_FIM = object()


def _sem_bearer(valor: str | None) -> str | None:
    if not valor:
        return None
    return valor[7:] if valor[:7].lower() == "bearer " else valor


class SessaoPelaPagina:
    """O mesmo contrato público de `erp.Sessao`, falando pela aba central."""

    def __init__(self, nome: str, fabrica_aba, espera_captura: float,
                 prazo_pedido: float = _PRAZO_PEDIDO, *, login_principal=None,
                 diag=None, reentrou: bool = False):
        self.nome = nome
        self.jwt_token: str | None = None
        self.access_token: str | None = None
        self.company_id: str | None = None
        self.user_id: str | None = None
        self.organization_unit_id: str | None = None
        self.usuario = f"Chrome central ({nome})"
        self.empresa = None
        #: Aceitos e ignorados: `conciliacao/erp/api.py` os atribui antes de
        #: pedir. Aqui quem transporta é a página.
        self.transporte = None
        self.espera = None

        self._fabrica_aba = fabrica_aba
        self._espera_captura = espera_captura
        self._prazo_pedido = prazo_pedido
        #: `(caiu: bool) -> bool`: o login principal (True = entrou agora).
        self._login_principal = login_principal or (lambda caiu=False: False)
        self._diag = diag or (lambda _m: None)
        #: Entrou no ERP (pelo login principal) desde a última pergunta.
        self._reentrou = bool(reentrou)
        #: A aba parou de responder (um `fetch` pendurado prende a dona):
        #: daí em diante todo `pedir` falha na hora, em vez de 300 s cada.
        self._quebrada = False
        #: Erro do `goto`/`reload`, guardado só para explicar a desistência.
        self._erro_navegar: BaseException | None = None
        self._cab: dict[str, dict] = {}
        self._trava = threading.Lock()        # protege _cab, campos e _fechada
        self._fila: queue.Queue = queue.Queue()
        self._pronto = threading.Event()      # capturou legacy E prod-erp-api
        self._saiu = threading.Event()        # a thread dona terminou
        self._fechada = False
        self._erro_inicio: BaseException | None = None
        self._page = None
        self._thread = threading.Thread(target=self._laco, daemon=True,
                                        name=f"erp-central-{nome}")
        self._thread.start()

    @classmethod
    def do_acesso(cls, nome: str = "principal", *, fabrica_aba=None,
                  espera_captura: float = 90.0,
                  prazo_pedido: float = _PRAZO_PEDIDO, login_principal=None,
                  diag=None) -> "SessaoPelaPagina":
        """A sessão do acesso, já com a autenticação capturada.

        Pede o login principal ANTES de abrir a aba: a leitura nunca nasce na
        tela de login. Sem `fabrica_aba` (o caso real) o acesso vem do
        `acessos.json`, e o login principal é o de `erp.login_principal`. Com
        `fabrica_aba` (os dublês dos testes) nada é lido do disco."""
        if fabrica_aba is None:
            a = central.acesso(nome)
            if a is None:
                raise ErpErro(f"o acesso '{nome}' não está no acessos.json")
            fabrica_aba = lambda: central.AbaCentral(a)   # noqa: E731
            if diag is None:
                diag = _diag_do_app
            if login_principal is None:
                from . import login_principal as _lp

                def login_principal(caiu=False):
                    return _lp.garantir_logado(a, caiu=caiu, log=diag)
        login_principal = login_principal or (lambda caiu=False: False)
        entrou = login_principal(False)        # ErpErro com o motivo real
        s = cls(nome, fabrica_aba, espera_captura, prazo_pedido,
                login_principal=login_principal, diag=diag, reentrou=bool(entrou))
        s._esperar_pronto()
        return s

    # ------------------------------------------------------------ captura

    def _recado_sem_tela(self) -> ErpErro:
        return ErpErro(f"a aba do ERP no Chrome central '{self.nome}' não mostrou "
                       "nem a área logada nem a tela de login — o ERP pode estar "
                       "fora do ar ou lento; tente de novo")

    def _esperar_pronto(self) -> None:
        """Espera a thread dona capturar os dois hosts, ou desiste limpo."""
        # Sai cedo quando a thread dona morre: exceção na captura inicial
        # (Chrome que não abre, aba que não conecta, login que não deu) chega
        # aqui como ErpErro, e não como minutos de nada. O teto cobre a pior
        # sequência da dona: captura, recargas, trava, login e releitura.
        teto = (self._espera_captura + _PRAZO_RECAPTURA + _SO_RECARGA
                + login_tela.VELHA_TRAVA + _PRAZO_LOGIN + 30)
        limite = time.monotonic() + teto
        while time.monotonic() < limite:
            if self._pronto.is_set() or self._saiu.is_set():
                break
            self._pronto.wait(0.05)
        if self._pronto.is_set() and not self._saiu.is_set():
            return
        erro = self._erro_inicio
        self.fechar()
        if erro is not None:
            if isinstance(erro, ErpErro):
                raise erro
            raise ErpErro(f"não consegui abrir a aba no Chrome central "
                          f"'{self.nome}': {erro}") from erro
        raise self._recado_sem_tela() from self._erro_navegar

    def _ouvir(self, req) -> None:
        """Ouvinte de `page.on("request")`: guarda a autenticação por host.

        Mesma regra de `aportes/erp_sessao.py`: só host do ERP que valha a
        pena (telemetria tem token próprio) e só request com `authorization`.
        """
        try:
            host = hosts.host_de(req.url)
            if not hosts.vale_a_pena(host):
                return
            cab = {k.lower(): v for k, v in (req.headers or {}).items()
                   if k.lower() in _CHAVES and v}
        except Exception:
            return                                # ouvinte nunca derruba a aba
        if "authorization" not in cab:
            return
        with self._trava:
            self._cab[host] = cab
            if hosts.HOST_LEGACY in self._cab and hosts.HOST_ERP_API in self._cab:
                self._atualizar_campos()
                self._pronto.set()

    def _atualizar_campos(self) -> None:
        """Os campos públicos a partir do que foi capturado (sob `_trava`)."""
        leg = self._cab.get(hosts.HOST_LEGACY, {})
        api = self._cab.get(hosts.HOST_ERP_API, {})
        self.jwt_token = _sem_bearer(api.get("authorization"))
        self.access_token = _sem_bearer(leg.get("authorization"))
        self.company_id = leg.get("company-id") or api.get("company-id")
        self.user_id = leg.get("user-id")
        self.organization_unit_id = leg.get("organization-unit-id")

    def _aguardar_captura(self, prazo: float) -> bool:
        """Na thread dona: deixa o Playwright trabalhar até ficar pronto."""
        passos = max(1, int(prazo * 1000 / _RESPIRO_MS))
        for _ in range(passos):
            if self._pronto.is_set():
                return True
            self._page.wait_for_timeout(_RESPIRO_MS)
        return self._pronto.is_set()

    def _aguardar_tela(self, prazo: float) -> str:
        """Na thread dona: "pronto" (capturou os dois hosts), "login" (a tela
        de login ficou à vista além de `_SO_RECARGA`, recarregando a rota de
        captura a cada `_RECARGA_NO_LOGIN`) ou "prazo"."""
        passos = max(1, int(prazo * 1000 / _RESPIRO_MS))
        carencia = int(_CARENCIA_LOGIN * 1000 / _RESPIRO_MS)
        cada = max(1, int(_RECARGA_NO_LOGIN * 1000 / _RESPIRO_MS))
        so_recarga = int(_SO_RECARGA * 1000 / _RESPIRO_MS)
        no_login = None                     # o passo em que o login apareceu
        for i in range(passos):
            if self._pronto.is_set():
                return "pronto"
            if i >= carencia and login_tela.tem_sinal_de_login(self._page):
                if no_login is None:
                    no_login = i
                if i - no_login >= so_recarga:
                    return "pronto" if self._pronto.is_set() else "login"
                if (i - no_login) % cada == cada - 1:
                    # Outra aba do mesmo Chrome pode ter acabado de entrar.
                    self._navegar(self._page.goto, URL_CAPTURA)
                    self._navegar(self._page.reload)
            self._page.wait_for_timeout(_RESPIRO_MS)
        if self._pronto.is_set():
            return "pronto"
        return "login" if no_login is not None else "prazo"

    def _limpar_captura(self) -> None:
        with self._trava:
            self._cab.clear()
            self._pronto.clear()

    def _preparar(self) -> None:
        """Na thread dona, ao abrir: a tela e a autenticação dela."""
        self._navegar(self._page.goto, URL_CAPTURA)
        self._capturar(self._espera_captura)

    def _recapturar(self) -> None:
        """Na thread dona: joga fora a autenticação e a pega de novo da tela
        (recarregando; caída no login, ver `_capturar`)."""
        self._limpar_captura()
        self._navegar(self._page.reload)
        self._capturar(_PRAZO_RECAPTURA)

    def _capturar(self, prazo: float) -> None:
        tela = self._aguardar_tela(prazo)
        if tela == "pronto":
            return
        if tela == "prazo":
            raise self._recado_sem_tela() from self._erro_navegar
        # Ninguém entrou: pede o login principal (UM só, mesmo com outras
        # abas pedindo junto) e relê a autenticação da tela.
        entrou = self._login_principal(True)
        self._limpar_captura()
        self._navegar(self._page.goto, URL_CAPTURA)
        self._navegar(self._page.reload)
        if not self._aguardar_captura(_PRAZO_LOGIN):
            raise ErpErro(
                f"o ERP continua na tela de login no Chrome central '{self.nome}' "
                "mesmo depois do login automático — entre no ERP pelo app "
                "(Minha aba no ERP) e tente de novo") from self._erro_navegar
        if entrou:
            with self._trava:
                self._reentrou = True

    def reentrou(self) -> bool:
        """True uma vez depois de o login principal ter entrado no ERP para
        esta aba (a sessão tinha caído). Quem lê o aviso o consome: a tela do
        dia o põe no Registro."""
        with self._trava:
            r, self._reentrou = self._reentrou, False
        return r

    def _navegar(self, acao, *args) -> None:
        """`goto`/`reload` que não derruba ninguém.

        `wait_until="commit"`: o que interessa são os requests da tela, não o
        `load` — o ERP pode demorar a dispará-lo, e o prazo vencido do
        Playwright mataria a thread dona com a captura já feita. Quem decide
        se deu certo é a espera da captura; o erro fica guardado só para
        explicar a desistência.
        """
        self._erro_navegar = None
        try:
            acao(*args, wait_until="commit")
        except Exception as e:
            self._erro_navegar = e

    # ------------------------------------------------------- thread dona

    def _laco(self) -> None:
        try:
            with self._fabrica_aba() as aba:
                self._page = aba.page
                self._page.on("request", self._ouvir)
                self._preparar()
                while True:
                    try:
                        item = self._fila.get(timeout=0.05)
                    except queue.Empty:
                        self._page.wait_for_timeout(_RESPIRO_MS)
                        continue
                    if item is _FIM:
                        break
                    funcao, args, futuro = item
                    if not futuro.set_running_or_notify_cancel():
                        continue
                    # O prazo de quem espera conta a partir DAQUI, e não da
                    # entrada na fila: esperar atrás de outro pedido legítimo
                    # não é sinal de aba presa.
                    futuro.inicio = time.monotonic()
                    try:
                        futuro.set_result(funcao(*args))
                    except BaseException as e:      # vai para quem pediu
                        futuro.set_exception(e)
        except BaseException as e:
            self._erro_inicio = e
        finally:
            self._page = None
            with self._trava:
                self._fechada = True
            self._esvaziar_fila()
            self._saiu.set()

    def _esvaziar_fila(self) -> None:
        """Quem ainda espera na fila recebe erro, nunca o silêncio."""
        while True:
            try:
                item = self._fila.get_nowait()
            except queue.Empty:
                return
            if item is _FIM:
                continue
            futuro = item[2]
            if futuro.set_running_or_notify_cancel():
                futuro.set_exception(
                    ErpErro(f"a sessão do Chrome central '{self.nome}' foi fechada"))

    def _executar(self, metodo: str, url: str, corpo, extras, idempotente: bool):
        """Na thread dona: um pedido, com UMA recaptura no 401."""
        r = self._uma_chamada(metodo, url, corpo, extras)
        if self._status(r) == 401:
            self._recapturar()
            if not (metodo == "GET" or idempotente):
                # Mesma regra de `Sessao.pedir`: POST/PUT não idempotente não
                # se repete — um que criou lançamento e perdeu a resposta
                # duplicaria dinheiro. A sessão já foi recapturada; quem
                # chamou decide.
                raise SessaoRecusada(
                    f"o ERP recusou a sessão do Chrome central (401) num {metodo}"
                    " — recapturada, mas o pedido não foi repetido", codigo=401)
            r = self._uma_chamada(metodo, url, corpo, extras)
            if self._status(r) == 401:
                raise SessaoRecusada(
                    "o ERP recusou a sessão do Chrome central duas vezes (401)",
                    codigo=401)
        st = self._status(r)
        if st is not None:
            caminho = urlsplit(url).path     # nunca a URL inteira: pode ter id
            raise ErpErro(f"o ERP respondeu {st} em {caminho}", codigo=st)
        return r

    @staticmethod
    def _status(r):
        if isinstance(r, dict) and "__erro" in r:
            return r["__erro"]
        return None

    def _uma_chamada(self, metodo: str, url: str, corpo, extras):
        t = TransportePagina(self._page, self.cabecalhos_para(url, extras))
        metodo = metodo.upper()
        if metodo == "GET":
            return t.buscar(url)
        if metodo == "POST":
            return t.postar(url, corpo)
        if metodo == "PUT":
            return t.trocar(url, corpo)
        raise ErpErro(f"método {metodo} não suportado pela aba central")

    # ----------------------------------------------------- qualquer thread

    def _pela_fila(self, funcao, *args):
        if threading.current_thread() is self._thread:
            return funcao(*args)               # já na dona: a fila travaria
        futuro: Future = Future()
        with self._trava:
            if self._quebrada:
                raise self._recado_quebrada()
            if self._fechada:
                raise ErpErro(f"a sessão do Chrome central '{self.nome}' está fechada")
            self._fila.put((funcao, args, futuro))
        return self._esperar(futuro)

    def _esperar(self, futuro: Future):
        """Espera o pedido, com dois prazos de sentidos diferentes.

        - Parado na FILA além do prazo: a dona está ocupada com pedidos
          legítimos. Cancela só este e diz "ocupado"; a sessão segue.
        - Em EXECUÇÃO além do prazo, contado do início da execução: o
          `evaluate` está preso (o `fetch` de `erp/pagina.py` não tem prazo) e
          a dona não volta. Quebra a sessão, e quem vier depois falha na hora
          em vez de esperar o mesmo prazo.
        """
        entrou = time.monotonic()
        while True:
            inicio = getattr(futuro, "inicio", None)
            limite = (inicio if inicio is not None else entrou) + self._prazo_pedido
            falta = limite - time.monotonic()
            if falta <= 0:
                if inicio is None:
                    if futuro.cancel():
                        raise ErpErro(f"o Chrome central '{self.nome}' está "
                                      "ocupado; tente de novo")
                    continue        # acabou de começar: o prazo agora é outro
                with self._trava:
                    self._quebrada = True
                raise self._recado_quebrada()
            try:
                return futuro.result(timeout=min(falta, 0.1))
            except _PrazoFuture:
                continue

    def _recado_quebrada(self) -> ErpErro:
        return ErpErro(f"a aba do Chrome central '{self.nome}' parou de "
                       "responder; abra de novo a sessão")

    def pedir(self, url: str, *, metodo: str = "GET", corpo=None,
              extras: dict | None = None, idempotente: bool = False) -> dict:
        """GET/POST/PUT pela aba central. Recaptura e repete uma vez no 401
        (GET, ou o que o chamador marcar `idempotente`).

        CUIDADO com escrita: um POST ou PUT que estoura o prazo (`ErpErro`
        "parou de responder") pode CONCLUIR no ERP depois — o `fetch` dentro
        da página não é abortado, só deixamos de esperar por ele. Quem migrar
        escrita de dinheiro para cá precisa de idempotência ou de consultar o
        ERP antes de repetir; repetir às cegas pode duplicar o lançamento."""
        return self._pela_fila(self._executar, metodo.upper(), url, corpo,
                               extras, idempotente)

    def relogar(self) -> None:
        """Recaptura a autenticação da tela: recarrega e, se a página cair no
        login, pede o login principal (`erp.login_principal`, nunca HTTP)."""
        self._pela_fila(self._recapturar)

    def token_para(self, url: str) -> str:
        """O token que o host desta URL aceita, sem o `Bearer `."""
        return _sem_bearer(self.cabecalhos_para(url).get("authorization")) or ""

    def cabecalhos_para(self, url: str, extras: dict | None = None) -> dict:
        """As quatro chaves capturadas do host da URL (sem captura dele, as
        do legacy — mesma regra de `TransportePagina.cabecalhos_para`), mais
        `extras`."""
        host = hosts.host_de(url)
        with self._trava:
            cab = dict(self._cab.get(host) or self._cab.get(hosts.HOST_LEGACY) or {})
        cab.update(extras or {})
        return cab

    @property
    def viva(self) -> bool:
        """Serve para o próximo pedido: nem fechada, nem quebrada, dona viva.

        É o contrato público que o cache de `erp.sessao` consulta; ele não
        deve ler os campos privados.
        """
        return not (self._fechada or self._quebrada) and self._thread.is_alive()

    def fechar(self) -> None:
        """Fecha a aba (só a própria) e encerra a thread dona. Idempotente."""
        with self._trava:
            ja = self._fechada
            self._fechada = True
            if not ja:
                self._fila.put(_FIM)
        if threading.current_thread() is not self._thread and not self._quebrada:
            # Quebrada, a dona está presa num `evaluate`: esperar seria só
            # atraso. A sentinela fica na fila e ela sai quando se soltar.
            self._saiu.wait(_PRAZO_SAIDA)


def _diag_do_app(msg: str) -> None:
    """O diagnostico.log do app, quando há app. Nunca derruba a sessão."""
    try:
        import util
        util.log("erp.sessao_pagina").info(msg)
    except Exception:
        pass
