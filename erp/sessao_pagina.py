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
"""
from __future__ import annotations

import queue
import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as _PrazoFuture
from urllib.parse import urlsplit

from . import central, hosts
from .pagina import TransportePagina
from .sessao import ErpErro, SessaoRecusada

URL_CAPTURA = "https://acessar.maiscontroleerp.com.br/#/payable-installments"
_CHAVES = {"authorization", "company-id", "user-id", "organization-unit-id"}
_PRAZO_PEDIDO = 300.0
#: Quanto a recaptura do 401 espera a tela voltar a chamar os dois hosts.
_PRAZO_RECAPTURA = 30.0
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
                 prazo_pedido: float = _PRAZO_PEDIDO):
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
                  prazo_pedido: float = _PRAZO_PEDIDO) -> "SessaoPelaPagina":
        if fabrica_aba is None:
            a = central.acesso(nome)
            if a is None:
                raise ErpErro(f"o acesso '{nome}' não está no acessos.json")
            fabrica_aba = lambda: central.AbaCentral(a)   # noqa: E731
        s = cls(nome, fabrica_aba, espera_captura, prazo_pedido)
        s._esperar_pronto()          # ErpErro "...porteiro precisa entrar..."
        return s

    # ------------------------------------------------------------ captura

    def _recado_porteiro(self) -> ErpErro:
        return ErpErro(f"o Chrome central '{self.nome}' não está logado no ERP — "
                       "o porteiro precisa entrar (python -m erp.porteiro estado)")

    def _esperar_pronto(self) -> None:
        """Espera a thread dona capturar os dois hosts, ou desiste limpo."""
        # Sai cedo quando a thread dona morre: exceção na captura inicial
        # (Chrome que não abre, aba que não conecta) chega aqui como ErpErro,
        # e não como `espera_captura` segundos de nada.
        limite = time.monotonic() + self._espera_captura
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
        raise self._recado_porteiro() from self._erro_navegar

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

    def _recapturar(self) -> None:
        """Na thread dona: joga fora a autenticação e a pega de novo da tela."""
        with self._trava:
            self._cab.clear()
            self._pronto.clear()
        self._navegar(self._page.reload)
        if not self._aguardar_captura(_PRAZO_RECAPTURA):
            raise self._recado_porteiro() from self._erro_navegar

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
                self._navegar(self._page.goto, URL_CAPTURA)
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
        """Recaptura a autenticação da tela. NÃO faz login: quem loga é o
        porteiro (`erp/porteiro.py`)."""
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
