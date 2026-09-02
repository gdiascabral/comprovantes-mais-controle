"""Cliente da API REST do Mais Controle — sem navegador.

POR QUE ESTE MODULO EXISTE
--------------------------
Em 10/08/2026 a tela #/accounts foi reescrita de AngularJS para React/MUI e a
raspagem parou de funcionar da noite para o dia: o programa logava, abria a
tela certa, e ainda assim falhava procurando `tr[ng-repeat]`, que deixou de
existir. Foi o segundo redesenho a quebrar a leitura de saldos.

Inspecionando o que a tela nova faz por baixo, apareceu a API REST que ela
propria consome. Duas chamadas entregam tudo que a tela mostra:

    GET {api}/bank-integration/bank-accounts?pageIndex=1&pageSize=200&isActive=true
    GET {api}/financial/bank-accounts/balances?bankAccountIds=<uuid>&...

Ler daqui e melhor em todos os aspectos que importam: nao depende de layout,
devolve numero em vez de "R$ 1.234,56", traz as 36 contas de uma vez (a tela
pagina de 10 em 10), nao precisa revelar saldo mascarado e nao espera valor
assincrono chegar celula a celula.

O QUE ESTE ARQUIVO E HOJE: UMA CASCA
------------------------------------
Ele foi o primeiro a falar HTTP direto com o ERP, e por isso descobriu sozinho
tudo que hoje mora no pacote `erp/`: o `user-agent` que passa pelo WAF, o
`company-id`, qual dos dois tokens vale para qual host e as novas tentativas so
em GET. O inventario que juntou essas descobertas — as daqui e as dos outros
sete consumidores, que se contradiziam por escrito — esta em
`docs/ERP-CLIENTES.md`, e a ordem de migracao dele poe este arquivo na linha 3.

Entao **nada disto e reimplementado aqui**:

    login e os dois tokens ......... erp.Sessao.logar / token_para
    cabecalhos por host ............ erp.Sessao.cabecalhos_para
    user-agent de navegador ........ erp.sessao.USER_AGENT
    novas tentativas (so GET) ...... erp.sessao.politica, montada no transporte
    enderecos ...................... erp.hosts

O laco de 3 tentativas escrito a mao saiu: ele existia porque este modulo
falava por `urllib.request` e nao tinha Session/HTTPAdapter para montar um
`Retry` pronto. Falando pelo `erp/`, que usa `requests`, o `Retry` vem pronto —
e a MESMA politica passa a valer para todo mundo que migrar, em vez de uma
copia por consumidor.

O QUE **NAO** MUDOU, E E DE PROPOSITO
-------------------------------------
A cara publica: `SessaoApi` com o mesmo nome, o mesmo construtor, os mesmos
metodos (`logar`, `listar_contas`, `saldos`, `contas`), os mesmos retornos e as
mesmas excecoes (`ErpError` / `SessaoExpirada`, de `conciliacao/errors.py`).
Quem depende daqui — `conciliacao/erp/accounts.py`, `nuvem/contas_novas.py` e
a sonda de `ferramentas/` — nao muda uma linha, e migra de graca.

As excecoes do `erp/` sao TRADUZIDAS na fronteira (`_traduzido`): quem chama
este pacote trata `ErpError`/`SessaoExpirada` desde sempre, e fazer vazar um
nome novo seria mudar a cara publica por dentro.

DUAS COISAS QUE NAO SAO OPCIONAIS (e agora moram no `erp/`)
-----------------------------------------------------------
1. `user-agent` de navegador. E a unica coisa que separa 200 de 403:

       COM user-agent de Chrome ......... 200
       SEM user-agent (Python-urllib) ... 403, pagina HTML do WAF

   O WAF nunca implicou com HTTP puro — implica com quem se identifica como
   robo. (E o mesmo guarda que recusa o navegador em modo headless.)

2. Header `company-id`, tirado de `companies[0].id` na resposta do login.

O TOKEN destas consultas e o `jwtToken` (~348 chars), NAO o `accessToken` (27
chars, que nem e JWT) — elas falam com o `prod-erp-api`. Vale 24 horas, tempo
de sobra para uma execucao, entao nao guardamos token em disco: cada execucao
loga de novo. Quem escolhe entre os dois e `erp.Sessao.token_para`, pelo HOST
da URL, e nao ha como errar sem errar o endereco junto.
"""

from __future__ import annotations

import contextlib
import urllib.parse
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from erp import hosts as erp_hosts
from erp import sessao as erp_sessao
from erp.sessao import ErpErro, Sessao, SessaoRecusada

from ..errors import ErpError, SessaoExpirada
from ..models import ErpAccount
from .auth import obter_credenciais

__all__ = ["SessaoApi", "coletar_contas_api"]

#: O `user-agent` que passa pelo WAF. O VALOR mora no `erp/` — aqui e so o
#: nome, que continua existindo porque `ferramentas/sonda.py:353` se apresenta
#: com ele ao perguntar aos portais se estao de pe. Copiar a string seria criar
#: a segunda verdade sobre o que separa 200 de 403.
USER_AGENT = erp_sessao.USER_AGENT

#: A URL de saldos leva um `bankAccountIds` por conta; pedimos em lotes para
#: nao esbarrar no limite de tamanho de URL quando as contas se multiplicarem.
_LOTE_SALDOS = 50

#: Trava contra laco infinito caso `hasNextPage` fique preso em true.
_MAX_PAGINAS = 50

#: O RELOGIO destas consultas. Os dois numeros saem do `erp/` — nao ha um
#: segundo valor escrito aqui —, mas continuam tendo nome proprio porque
#: `ferramentas/sonda.py` os aperta (`_relogio_curto_do_erp`): ela mede se o
#: ERP RESPONDEU, e tres tentativas com espera dobrada esticam uma pergunta de
#: 10 s para mais de meio minuto, escondendo justamente a lentidao que ela
#: existe para notar. **Eles sao lidos a cada chamada** (`_relogio`), entao
#: troca-los muda o transporte de verdade; deixa-los aqui so de enfeite seria
#: pior que nao te-los, porque a sonda estaria apertando um botao desligado.
_TIMEOUT_S = erp_sessao.ESPERA
_TENTATIVAS_GET = erp_sessao.TENTATIVAS


@contextlib.contextmanager
def _traduzido():
    """As excecoes do `erp/` na lingua que este pacote fala, e so aqui.

    A hierarquia e a mesma dos dois lados (`SessaoRecusada` < `ErpErro`, como
    `SessaoExpirada` < `ErpError`), entao a traducao e um par de linhas — e
    espalha-la pelos metodos criaria varios lugares para esquecer um.
    """
    try:
        yield
    except SessaoRecusada as erro:
        raise SessaoExpirada(str(erro)) from erro
    except ErpErro as erro:
        raise ErpError(str(erro)) from erro


def _relogio() -> dict:
    """O transporte e a espera desta chamada, lidos AGORA.

    Lidos agora, e nao guardados na sessao, porque `ferramentas/sonda.py`
    troca os dois numeros em volta da chamada e os devolve no fim — e um
    valor congelado no login faria o `finally` dela restaurar algo que ja
    nao estava mais em uso.
    """
    return {"transporte": erp_sessao.montar_transporte(_TENTATIVAS_GET),
            "espera": _TIMEOUT_S}


def _base_api(config) -> str:
    """O `prod-erp-api`. O `config` manda; o `erp/hosts.py` e o padrao."""
    return _base(config, "api_base", erp_hosts.ERP_API)


def _base_legacy(config) -> str:
    """O `legacy-api`, onde mora o login."""
    return _base(config, "legacy_api_base", erp_hosts.LEGACY)


def _base(config, chave: str, padrao: str) -> str:
    """O endereco configurado, ou o do `erp/hosts.py`.

    O `config` continua mandando porque `conciliacao/config.yaml` tem essas
    duas chaves e mora FORA do repositorio: passar a ignora-las seria aceitar
    configuracao e descarta-la em silencio. O padrao passou a sair do
    `erp/hosts.py` — e e por isso que o `_ConfigMinimo` de
    `nuvem/contas_novas.py`, que so existe para satisfazer esta assinatura,
    pode desaparecer no PR dele sem que nada aqui mude.
    """
    valor = (getattr(config, "erp", None) or {}).get(chave)
    return str(valor or padrao).rstrip("/")


@dataclass
class SessaoApi:
    """Sessao autenticada na API REST."""

    token: str
    company_id: str
    usuario: str
    empresa: str | None
    config: object
    #: A `erp.Sessao` por baixo, quando esta veio de `logar()`. Fora do `repr`
    #: porque ela carrega a credencial que permite relogar.
    _sessao: Sessao | None = field(default=None, repr=False)

    # ------------------------------------------------------------------ login

    @classmethod
    def logar(cls, config, log=print) -> "SessaoApi":
        email, senha = obter_credenciais()
        if not (email and senha):
            raise SessaoExpirada(
                "nao ha credenciais guardadas para ler os saldos.\n"
                "No app: clique em 'Login' na aba Anexar Comprovantes.\n"
                "Pelos .bat: rode o atalho '1 - Salvar senha'."
            )

        # O `erp/` ja para com recado proprio no MFA, na troca de senha
        # obrigatoria e no login sem empresa — as tres situacoes que quebrariam
        # a coleta mais adiante, de forma confusa. Aqui so se traduz o nome da
        # excecao; a frase continua sendo a mesma que a pessoa lia.
        with _traduzido():
            interna = Sessao.logar(email, senha,
                                   url=f"{_base_legacy(config)}/users/login",
                                   **_relogio())

        if not interna.jwt_token:
            raise ErpError(
                "o login da API respondeu sem 'jwtToken' — o contrato mudou.\n"
                "Me avise: a leitura de saldos precisa ser reajustada."
            )

        sessao = cls(
            token=interna.jwt_token,
            company_id=interna.company_id,
            usuario=interna.usuario or email,
            empresa=interna.empresa,
            config=config,
            _sessao=interna,
        )
        log(f"  conectado como {sessao.usuario} ({sessao.empresa})")
        return sessao

    @property
    def _erp(self) -> Sessao:
        """A sessao do pacote `erp/` que fala por esta.

        Montado a mao (o construtor e publico, e ha quem o use), o objeto nao
        tem sessao interna: ela e reconstruida aqui a partir dos campos que ela
        mesma preencheria. Reconstruida a cada chamada, e nao guardada, para
        que trocar `self.token` continue valendo — e ela nasce sem credencial,
        logo sem relogin, que e o certo: ninguem entregou senha nenhuma.
        """
        if self._sessao is not None:
            return self._sessao
        return Sessao(jwt_token=self.token, company_id=self.company_id)

    def _pedir(self, url: str):
        """GET autenticado. Quem repete 5xx e o transporte, e so em GET."""
        sessao = self._erp
        relogio = _relogio()
        sessao.transporte, sessao.espera = relogio["transporte"], relogio["espera"]
        with _traduzido():
            return sessao.pedir(url)

    # --------------------------------------------------------------- consultas

    def listar_contas(self, *, ativas: bool = True) -> list[dict]:
        """Todas as contas, paginando ate o fim.

        `pageSize=200` cobre as 36 de hoje numa tacada; o laco existe para o
        dia em que passarem disso. Perder conta em silencio e o tipo de erro
        que so aparece no fechamento do mes.
        """
        itens: list[dict] = []
        pagina = 1
        while True:
            consulta = urllib.parse.urlencode(
                {"pageIndex": pagina, "pageSize": 200, "isActive": str(ativas).lower()}
            )
            corpo = self._pedir(
                f"{_base_api(self.config)}/bank-integration/bank-accounts?{consulta}"
            )
            itens.extend(corpo.get("items") or [])
            if not corpo.get("hasNextPage"):
                return itens
            pagina += 1
            if pagina > _MAX_PAGINAS:
                raise ErpError(
                    f"a listagem de contas nao terminou em {_MAX_PAGINAS} paginas."
                )

    def saldos(self, ids: list[str]) -> dict[str, Decimal]:
        """Saldo atual por UUID.

        ATENCAO: `currentBalance` vem NULL na listagem de contas — o saldo so
        existe neste endpoint. Na tela, e o que o botao do olho dispara.
        """
        resultado: dict[str, Decimal] = {}
        for inicio in range(0, len(ids), _LOTE_SALDOS):
            lote = ids[inicio : inicio + _LOTE_SALDOS]
            consulta = "&".join(
                f"bankAccountIds={urllib.parse.quote(str(i))}" for i in lote
            )
            corpo = self._pedir(
                f"{_base_api(self.config)}/financial/bank-accounts/balances?{consulta}"
            )
            if not isinstance(corpo, dict):
                continue
            for chave, valor in corpo.items():
                convertido = _para_decimal(valor)
                if convertido is not None:
                    resultado[str(chave)] = convertido
        return resultado

    def contas(self, *, ativas: bool = True) -> list[ErpAccount]:
        """Contas + saldos unidos — o equivalente ao que a tela mostra."""
        crus = self.listar_contas(ativas=ativas)
        mapa = self.saldos([c["id"] for c in crus if c.get("id")])
        return [
            ErpAccount(
                id=str(cru.get("id") or ""),
                name=str(cru.get("name") or ""),
                is_active=bool(cru.get("isActive", True)),
                bank_code=_texto(cru.get("bankCode")),
                agency=_texto(cru.get("agency")),
                account_number=_numero_conta(cru),
                raw_balance=_bruto(mapa, cru),
                balance=mapa.get(str(cru.get("id"))),
            )
            for cru in crus
        ]


def coletar_contas_api(config, *, log=print) -> list[ErpAccount]:
    """Le todas as contas ativas com saldo. Ponto de entrada do modulo.

    Contas inativas ficam de fora de proposito (decisao do Gustavo): elas nao
    entram no painel e so poluiriam o log de "conta nova no ERP".
    """
    sessao = SessaoApi.logar(config, log=log)
    contas = sessao.contas(ativas=True)
    if not contas:
        raise ErpError("a API nao devolveu nenhuma conta bancaria.")
    return contas


# ------------------------------------------------------------------ auxiliares


def _bruto(mapa: dict[str, Decimal], cru: dict) -> str | None:
    """Guarda o saldo cru para auditoria no snapshot."""
    valor = mapa.get(str(cru.get("id")))
    return None if valor is None else str(valor)


def _texto(valor) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _numero_conta(cru: dict) -> str | None:
    """Junta conta e digito quando o ERP tem esses campos preenchidos."""
    numero = _texto(cru.get("account"))
    if not numero:
        return None
    digito = _texto(cru.get("accountDigit"))
    return f"{numero}-{digito}" if digito else numero


def _para_decimal(valor) -> Decimal | None:
    """float da API -> Decimal. Passa por str para nao herdar lixo binario."""
    if valor is None:
        return None
    try:
        return Decimal(str(valor))
    except (InvalidOperation, ValueError):
        return None
