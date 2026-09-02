# -*- coding: utf-8 -*-
"""Quem fala com o ERP: os dois tokens, os cabeçalhos por host, e o transporte.

Tudo que os oito consumidores redescobriram por conta própria mora aqui, uma
vez só. O inventário que levantou cada regra — com a evidência em
`arquivo:linha` — está em `docs/ERP-CLIENTES.md`.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import hosts

__all__ = ["USER_AGENT", "ErpErro", "Sessao", "SessaoRecusada"]

#: O `user-agent` é OBRIGATÓRIO, e é a única coisa que separa 200 de 403:
#:
#:     COM user-agent de Chrome ......... 200
#:     SEM user-agent (Python-urllib) ... 403, pagina HTML do WAF
#:
#: Medido em `conciliacao/erp/api.py:23-29`. O WAF nunca implicou com HTTP
#: puro — implica com quem se identifica como robô; é o mesmo guarda que
#: recusa o navegador em modo headless (`conciliacao/erp/browser.py:5-8`).
#: Se um dia ele apertar, é aqui que se mexe.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

#: Generoso porque a alternativa é pior: uma leitura que desiste cedo custa a
#: rodada inteira, e o ERP fica lento em lote.
ESPERA = 45


class ErpErro(RuntimeError):
    """Raiz de tudo que pode dar errado ao falar com o ERP.

    `codigo` é o status HTTP que gerou a falha, ou `0` quando nem houve
    resposta (rede caída, 200 que não era JSON). Ele existe porque a MESMA
    exceção nomeada nasce de causas com desfechos diferentes: um 401 do legado
    pede relogin (o token dele vive segundos), e um 401 do `prod-erp-api` — ou
    a senha recusada no login — pede gente. Ler o motivo do texto da mensagem
    seria decidir por `str`, que é o tipo de conferência que quebra na primeira
    vez que alguém melhora a frase.
    """

    def __init__(self, mensagem: str = "", *, codigo: int = 0):
        super().__init__(mensagem)
        self.codigo = codigo


class SessaoRecusada(ErpErro):
    """O ERP recusou a identidade: senha errada, sessão vencida, 401.

    Nome próprio porque o desfecho é outro: aqui a pessoa precisa entrar de
    novo, e repetir a chamada não resolve.
    """


#: Quantas vezes um GET insiste. Três é o número da RODADA de produção — ver
#: `montar_transporte` —, e é o padrão de tudo aqui.
TENTATIVAS = 3


def montar_transporte(tentativas: int = TENTATIVAS) -> requests.Session:
    """Uma conexão viva, com nova tentativa automática em 5xx.

    **Só GET repete.** Reenviar um POST que criou algo e perdeu a resposta
    duplica o que foi criado — e aqui os POSTs criam lançamento, criam baixa e
    movem dinheiro (`aportes/mc_lancamentos.py`, `pagamentos_dia/baixa_erp.py`).
    Quem chama um POST vê a falha uma vez e decide se tenta de novo.

    `raise_on_status=False`: esgotadas as tentativas, a ÚLTIMA resposta 5xx
    volta como resposta comum, para quem chama traduzir status em exceção
    NOMEADA num lugar só — duplicar essa tradução aqui criaria duas fontes
    para a mesma regra.

    É a MESMA política de `nuvem/rest.py:_montar_sessao` (3 tentativas, 502 a
    504), e a repetição não é acaso: um 504 real do `prod-erp-api` já custou
    uma rodada de conciliação, e `conciliacao/erp/api.py` teve de escrevê-la à
    mão por falar via `urllib.request`. Aqui, falando por `requests`, o `Retry`
    vem pronto.

    `tentativas` é parâmetro porque nem todo mundo quer o relógio da rodada:
    `ferramentas/sonda.py` mede se o ERP RESPONDEU, e três tentativas com
    espera dobrada esticam uma pergunta de 10 s para mais de meio minuto —
    escondendo justamente a lentidão que a sonda existe para notar. Com o
    número da casa, devolve a sessão única do módulo; com outro, uma sessão
    própria, para que apertar o relógio de uma ferramenta não mexa no
    transporte que o app está usando.
    """
    if tentativas == TENTATIVAS and _SESSAO is not None:
        return _SESSAO
    sessao = requests.Session()
    sessao.mount("https://", HTTPAdapter(max_retries=politica(tentativas)))
    return sessao


def politica(tentativas: int = TENTATIVAS) -> Retry:
    """A política de novas tentativas, exposta para poder ser conferida.

    Sem isto, "GET repete e POST não" seria uma frase de comentário. Com ela,
    `politica().is_retry("POST", 504)` responde por escrito — é a mesma função
    que o urllib3 chama para decidir.
    """
    return Retry(
        total=tentativas,
        backoff_factor=1,
        status_forcelist=[502, 503, 504],
        allowed_methods=frozenset(["GET"]),
        raise_on_status=False,
    )


#: O pacote inteiro fala com o mesmo ERP, então uma sessão só basta — e é o
#: ponto único que os testes trocam para simular o transporte. Nasce `None`
#: para que o `montar_transporte` da linha seguinte não procure por ele antes
#: de ele existir.
_SESSAO = None
_SESSAO = montar_transporte()


@dataclass
class Sessao:
    """Uma identidade no ERP: os dois tokens e os três campos de identidade.

    Nasce de `logar()` (que faz o `POST /users/login`) ou de `de_login()`, que
    recebe o corpo desse login já pronto — é o que permite testar sem rede e o
    que deixa o `conciliacao/erp/api.py`, que já loga, migrar sem relogar.
    """

    jwt_token: str = ""
    access_token: str = ""
    company_id: str = ""
    user_id: str = ""
    organization_unit_id: str = ""
    usuario: str = ""
    empresa: str | None = None
    #: Qualquer coisa com `.request(metodo, url, headers=…, json=…, timeout=…)`.
    #: `None` usa a sessão do módulo; os testes injetam a sua.
    transporte: object | None = field(default=None, repr=False)
    #: Quantos segundos esperar por cada resposta. `None` usa o `ESPERA` do
    #: módulo. É por sessão, e não uma constante só, porque quem PERGUNTA se o
    #: ERP respondeu (`ferramentas/sonda.py`) precisa desistir cedo, enquanto
    #: quem faz a rodada precisa esperar — ver `montar_transporte`.
    espera: float | None = field(default=None, repr=False)
    #: A credencial que fez este login, guardada só em memória e para uma
    #: coisa: refazer o login quando o `accessToken` do legado vencer no meio
    #: do trabalho (ver `relogar`). `repr=False` porque objeto de sessão vai
    #: parar em log e em traceback, e senha não. Sessão nascida de `de_login`
    #: (que recebe o corpo pronto) fica sem elas — e então não há relogin, que
    #: é o certo: ninguém pode relogar em nome de quem não entregou a senha.
    _email: str = field(default="", repr=False)
    _senha: str = field(default="", repr=False)
    #: O endereço de login que ESTA sessão usou. Relogar noutro endereço
    #: seria trocar de ERP no meio do trabalho.
    _url_login: str = field(default="", repr=False)

    # ----------------------------------------------------------------- login

    @classmethod
    def de_login(cls, corpo: dict, *, transporte=None) -> "Sessao":
        """Monta a sessão a partir do corpo do `POST /users/login`.

        O login é UM só e devolve OS DOIS tokens, mais a identidade inteira —
        `companies[0].id`, `id` e `organizationUnitId`. É por isso que quem
        fala por HTTP direto não precisa de navegador para ter os quatro
        cabeçalhos que o legado exige: eles saem daqui
        (`fontes/vigia-boletos/mc_sessao.py:114-117`).
        """
        corpo = corpo or {}
        empresas = corpo.get("companies") or []
        if not empresas:
            raise ErpErro("o login nao devolveu nenhuma empresa (companies vazio).")
        if corpo.get("mfaEnabled"):
            raise SessaoRecusada(
                "esta conta passou a exigir segundo fator (MFA).\n"
                "O login automatico nao passa por MFA — me avise para ajustar."
            )
        if corpo.get("needsPasswordChange"):
            raise SessaoRecusada(
                "o ERP esta exigindo troca de senha deste usuario.\n"
                "Entre no site, troque a senha e guarde a nova."
            )
        primeira = empresas[0] or {}
        return cls(
            jwt_token=str(corpo.get("jwtToken") or ""),
            access_token=str(corpo.get("accessToken") or ""),
            company_id=str(primeira.get("id") or ""),
            user_id=str(corpo.get("id") or ""),
            organization_unit_id=str(corpo.get("organizationUnitId") or ""),
            usuario=str(corpo.get("username") or ""),
            empresa=primeira.get("tradeName") or primeira.get("name"),
            transporte=transporte,
        )

    @classmethod
    def logar(cls, email: str, senha: str, *, transporte=None,
              url: str = "", espera: float | None = None) -> "Sessao":
        """`POST {legacy}/users/login`. É a única chamada sem token nenhum.

        `url` existe para quem já tinha o endereço em arquivo de configuração —
        é o caso do `conciliacao/erp/api.py`, cujo `config.yaml` traz
        `legacy_api_base`. Ignorar essa chave ao migrar seria aceitá-la e
        descartá-la em silêncio, que é a armadilha que o próprio inventário
        registra do lado do ERP (`anexar/mc_api.py:537-540`). Vazio usa o
        `hosts.URL_LOGIN`, que é o endereço de verdade.
        """
        if not (email and senha):
            raise SessaoRecusada("sem credenciais para entrar no Mais Controle.")
        url = url or hosts.URL_LOGIN
        corpo = _pedir(
            url,
            metodo="POST",
            corpo={"username": email, "password": senha},
            cabecalhos=cabecalhos_base(),
            transporte=transporte,
            espera=espera,
        )
        sessao = cls.de_login(corpo, transporte=transporte)
        if not sessao.usuario:
            sessao.usuario = email
        sessao.espera = espera
        sessao._email, sessao._senha = email, senha
        sessao._url_login = url
        return sessao

    def relogar(self) -> None:
        """Refaz o login NESTE objeto, trocando os dois tokens de uma vez.

        Os dois, e não só o do legado: o login é um só e devolve o par, então
        guardar metade do que ele respondeu deixaria o `jwtToken` velho ao lado
        do `accessToken` novo — duas idades na mesma sessão, que é exatamente o
        tipo de estado que ninguém consegue depurar depois.

        Veio de `fontes/vigia-boletos/mc_sessao.py:131-133`, que é quem convive
        com o legado há mais tempo e resolveu isso do mesmo jeito.
        """
        if not (self._email and self._senha):
            raise SessaoRecusada(
                "a sessao do ERP venceu e nao ha credencial guardada nesta\n"
                "sessao para entrar de novo — refaca o login.")
        nova = Sessao.logar(self._email, self._senha, transporte=self.transporte,
                            url=self._url_login, espera=self.espera)
        self.jwt_token = nova.jwt_token
        self.access_token = nova.access_token
        self.company_id = nova.company_id
        self.user_id = nova.user_id
        self.organization_unit_id = nova.organization_unit_id

    # ------------------------------------------------------- a regra central

    def token_para(self, url_ou_host: str) -> str:
        """O token que ESTE host aceita. Trocar os dois devolve 401.

        A regra, escrita uma vez:

            prod-erp-api  ->  jwtToken     (~348 chars, JWT, vale 24 h)
            legacy-api    ->  accessToken  (27 chars, nem é JWT, vive segundos)

        As duas evidências, cada uma no arquivo que a sustenta:

        1. `conciliacao/erp/api.py:33` — "O TOKEN E O `jwtToken` (~348 chars),
           NAO o `accessToken` (27 chars, que nem e JWT)". E o código faz isso:
           pega `jwtToken` do login (`:120`) e o usa só contra o `prod-erp-api`
           (`:175` contas, `:200` saldos).
        2. `fontes/vigia-boletos/mc_sessao.py:8-9` — "jwtToken (348 chars) ->
           API nova. **Na legada da 401 invalid_token.** accessToken (27
           chars) -> API legada." E o código faz isso: guarda `accessToken`
           (`:111-114`) e só chama o `legacy-api`.

        Os dois estavam certos, para back-ends diferentes, e nenhum dizia isso
        inteiro. Vale igual para o token capturado do navegador: reaproveitar
        o cabeçalho de um host noutro dá 401 — foi assim que o token da
        telemetria acabou usado contra o `prod-erp-api`
        (`aportes/mc_catalogos.py:124-127`).
        """
        if hosts.eh_legacy(url_ou_host):
            return self.access_token
        return self.jwt_token

    def cabecalhos_para(self, url_ou_host: str, extras: dict | None = None) -> dict:
        """Os cabeçalhos que ESTE host exige, prontos para sair.

        São conjuntos diferentes, e a diferença já custou duas falhas:

            prod-erp-api  ->  authorization, company-id
            legacy-api    ->  authorization, company-id, user-id,
                              organization-unit-id

        **Só o legado manda `user-id`** (`aportes/mc_catalogos.py:171-172`), e
        é ele o responsável pelo lançamento: sem o cabeçalho, o ERP recusa com
        "não achei o usuário responsável", que não aponta para lugar nenhum.
        A mesma divisão está medida fora do app, em
        `agua_energia/coletor/lancar_mc.py:76-77`.

        O `authorization` sai do `token_para`, então errar o host não é
        possível sem errar os dois juntos.
        """
        cabecalhos = cabecalhos_base()
        token = self.token_para(url_ou_host)
        if token:
            cabecalhos["authorization"] = f"Bearer {token}"
        if self.company_id:
            cabecalhos["company-id"] = self.company_id
        if hosts.eh_legacy(url_ou_host):
            if self.user_id:
                cabecalhos["user-id"] = self.user_id
            if self.organization_unit_id:
                cabecalhos["organization-unit-id"] = self.organization_unit_id
        cabecalhos.update(extras or {})
        return cabecalhos

    # ------------------------------------------------------------ transporte

    def pedir(self, url: str, *, metodo: str = "GET", corpo=None,
              extras: dict | None = None, idempotente: bool = False):
        """Chamada autenticada por HTTP direto, sem navegador.

        Quem repete 5xx é o transporte, e só em GET — ver `_montar_sessao`.
        Quem repete **401 do legado** é este método, e uma vez só.

        POR QUE O 401 DO LEGADO É OUTRA COISA
        -------------------------------------
        Os dois tokens têm idades incomparáveis (`token_para`):

            prod-erp-api  ->  jwtToken     vale 24 h
            legacy-api    ->  accessToken  vive SEGUNDOS

        Então o mesmo 401 quer dizer coisas opostas. No legado ele é rotina:
        o token venceu entre uma chamada e a seguinte, e quem fala por HTTP
        direto precisa relogar no meio do trabalho (`docs/ERP-CLIENTES.md`,
        seção 1, consequência 2; `fontes/vigia-boletos/mc_sessao.py:135-146`,
        que descobriu isso primeiro). No `prod-erp-api` ele é notícia: um
        token de 24 h recusado é sessão derrubada de verdade — o ERP aceita
        UMA sessão por usuário, e outro login pode ter tomado esta
        (`conciliacao/erp/collect.py:98-108`). Relogar ali seria tomar a
        sessão de volta de quem estiver com ela, em silêncio; a exceção
        nomeada sobe e quem chamou decide.

        E POR QUE SÓ GET (E O QUE O CHAMADOR PODE MARCAR)
        -------------------------------------------------
        É a mesma razão do `Retry` de 5xx, e vale ainda mais aqui: um POST
        que criou lançamento e perdeu a resposta duplica o que foi criado —
        e os POSTs deste app criam lançamento e dão baixa em pagamento
        (`aportes/mc_lancamentos.py`, `pagamentos_dia/baixa_erp.py`). O 401
        chega ANTES de o pedido ser processado quase sempre; "quase sempre"
        não é garantia, e dinheiro duplicado se desfaz à mão, lançamento por
        lançamento (`CLAUDE.md`, "Aporte não se repete").

        Daí `idempotente`: um PUT/POST que possa ser reenviado sem criar nada
        (escrita que sobrescreve o mesmo lançamento, por exemplo) é marcado
        pelo CHAMADOR, que é quem conhece a rota. O padrão é `False`, e o
        padrão é o seguro: esquecer a marca custa uma exceção; pôr a marca
        onde não cabe custa uma segunda baixa.
        """
        try:
            return self._uma_chamada(url, metodo, corpo, extras)
        except SessaoRecusada as recusa:
            if not self._da_para_relogar(url, metodo, recusa, idempotente):
                raise
        # Fora do `except` de propósito: um 401 na SEGUNDA volta sobe como
        # veio, sem virar "durante o tratamento de X ocorreu Y" — e sem
        # chance de laço, porque daqui não se tenta de novo.
        self.relogar()
        return self._uma_chamada(url, metodo, corpo, extras)

    def _uma_chamada(self, url: str, metodo: str, corpo, extras):
        return _pedir(url, metodo=metodo, corpo=corpo,
                      cabecalhos=self.cabecalhos_para(url, extras),
                      transporte=self.transporte, espera=self.espera)

    def _da_para_relogar(self, url: str, metodo: str, recusa: SessaoRecusada,
                         idempotente: bool) -> bool:
        """As quatro condições do relogin, cada uma com o seu motivo acima."""
        if recusa.codigo != 401:
            return False
        if not hosts.eh_legacy(url):
            return False
        if not (self._email and self._senha):
            return False
        return metodo.upper() == "GET" or idempotente


def cabecalhos_base() -> dict:
    """O que TODA chamada leva, com ou sem sessão.

    O `user-agent` é o que separa 200 de 403; `origin` e `referer` apontam
    para a TELA, que é de onde o ERP espera ser chamado.
    """
    return {
        "accept": "application/json, text/plain, */*",
        "accept-language": "pt-BR",
        "content-type": "application/json",
        "origin": hosts.ACESSAR,
        "referer": hosts.ACESSAR + "/",
        "user-agent": USER_AGENT,
    }


def _pedir(url: str, *, metodo: str, corpo, cabecalhos: dict, transporte=None,
           espera: float | None = None):
    """Uma chamada HTTP, com o status traduzido em exceção NOMEADA.

    A tradução mora aqui e só aqui: o transporte devolve a última resposta 5xx
    como resposta comum (`raise_on_status=False`), e duplicar a leitura de
    status criaria duas fontes para a mesma regra.
    """
    alvo = transporte if transporte is not None else _SESSAO
    try:
        resposta = alvo.request(metodo, url, headers=cabecalhos,
                                json=corpo, timeout=espera or ESPERA)
    except requests.RequestException as e:
        raise ErpErro(f"nao deu para falar com o ERP: {e}") from e

    codigo = getattr(resposta, "status_code", 0)
    if codigo in (401, 403) and "/users/login" in url:
        # `codigo=0`: o login é a única chamada que não tem token para vencer,
        # então repetir com credencial nova é repetir com a MESMA credencial.
        # Zerar o código aqui é o que impede o relogin de tentar isso.
        raise SessaoRecusada(
            "o ERP recusou a senha guardada.\n"
            "Guarde a senha correta e tente de novo."
        )
    if codigo == 403:
        raise ErpErro(
            "403 do WAF do Mais Controle. Quase sempre e o cabecalho\n"
            "'user-agent' — confira a constante USER_AGENT em erp/sessao.py.",
            codigo=403,
        )
    if codigo == 401:
        raise SessaoRecusada("a sessao do ERP foi recusada (401).", codigo=401)
    if codigo >= 400:
        detalhe = (getattr(resposta, "text", "") or "")[:200]
        raise ErpErro(f"HTTP {codigo} ao chamar {url.split('?')[0]}\n{detalhe}",
                      codigo=codigo)
    try:
        return resposta.json()
    except ValueError as e:
        # 200 que não é JSON costuma ser página de manutenção, do WAF, ou
        # portal de wi-fi sequestrando a conexão. É problema de rede.
        raise ErpErro(f"o ERP respondeu algo que nao e JSON ({e})") from e
