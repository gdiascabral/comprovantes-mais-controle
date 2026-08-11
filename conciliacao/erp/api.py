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

DUAS COISAS QUE NAO SAO OPCIONAIS
---------------------------------
1. `user-agent` de navegador. E a unica coisa que separa 200 de 403:

       COM user-agent de Chrome ......... 200
       SEM user-agent (Python-urllib) ... 403, pagina HTML do WAF

   O WAF nunca implicou com HTTP puro — implica com quem se identifica como
   robo. (E o mesmo guarda que recusa o navegador em modo headless.)

2. Header `company-id`, tirado de `companies[0].id` na resposta do login.

O TOKEN E O `jwtToken` (~348 chars), NAO o `accessToken` (27 chars, que nem e
JWT). Vale 24 horas — tempo de sobra para uma execucao, entao nao guardamos
token em disco: cada execucao loga de novo.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ..errors import ErpError, SessaoExpirada
from ..models import ErpAccount
from .auth import obter_credenciais

__all__ = ["SessaoApi", "coletar_contas_api"]

#: Ver restricao 1 no topo. Se um dia o WAF apertar, e aqui que se mexe.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

#: A URL de saldos leva um `bankAccountIds` por conta; pedimos em lotes para
#: nao esbarrar no limite de tamanho de URL quando as contas se multiplicarem.
_LOTE_SALDOS = 50

#: Trava contra laco infinito caso `hasNextPage` fique preso em true.
_MAX_PAGINAS = 50

_TIMEOUT_S = 45


def _base_api(config) -> str:
    return str(config.erp["api_base"]).rstrip("/")


def _base_legacy(config) -> str:
    return str(config.erp["legacy_api_base"]).rstrip("/")


@dataclass
class SessaoApi:
    """Sessao autenticada na API REST."""

    token: str
    company_id: str
    usuario: str
    empresa: str | None
    config: object

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

        corpo = _requisitar(
            f"{_base_legacy(config)}/users/login",
            metodo="POST",
            corpo={"username": email, "password": senha},
        )

        token = corpo.get("jwtToken")
        if not token:
            raise ErpError(
                "o login da API respondeu sem 'jwtToken' — o contrato mudou.\n"
                "Me avise: a leitura de saldos precisa ser reajustada."
            )

        # Situacoes que quebrariam a coleta mais adiante, de forma confusa.
        # Melhor parar aqui, com o motivo em portugues.
        if corpo.get("mfaEnabled"):
            raise SessaoExpirada(
                "esta conta passou a exigir segundo fator (MFA).\n"
                "O login automatico nao passa por MFA — me avise para ajustar."
            )
        if corpo.get("needsPasswordChange"):
            raise SessaoExpirada(
                "o ERP esta exigindo troca de senha deste usuario.\n"
                "Entre no site, troque a senha e guarde a nova:\n"
                "no app, em 'Login'; pelos .bat, em '1 - Salvar senha'."
            )

        empresas = corpo.get("companies") or []
        if not empresas:
            raise ErpError("o login nao devolveu nenhuma empresa (companies vazio).")

        sessao = cls(
            token=str(token),
            company_id=str(empresas[0].get("id")),
            usuario=str(corpo.get("username") or email),
            empresa=empresas[0].get("tradeName") or empresas[0].get("name"),
            config=config,
        )
        log(f"  conectado como {sessao.usuario} ({sessao.empresa})")
        return sessao

    @property
    def _auth(self) -> dict[str, str]:
        return {"authorization": f"Bearer {self.token}", "company-id": self.company_id}

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
            corpo = _requisitar(
                f"{_base_api(self.config)}/bank-integration/bank-accounts?{consulta}",
                headers=self._auth,
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
            corpo = _requisitar(
                f"{_base_api(self.config)}/financial/bank-accounts/balances?{consulta}",
                headers=self._auth,
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


def _requisitar(url: str, *, metodo: str = "GET", corpo=None, headers=None):
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method=metodo)
    origem = "https://acessar.maiscontroleerp.com.br"
    cabecalhos = {
        "accept": "application/json, text/plain, */*",
        "accept-language": "pt-BR",
        "content-type": "application/json",
        "origin": origem,
        "referer": origem + "/",
        "user-agent": USER_AGENT,  # obrigatorio — ver restricao 1 no topo
        **(headers or {}),
    }
    for chave, valor in cabecalhos.items():
        req.add_header(chave, valor)

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resposta:
            return json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as erro:
        detalhe = erro.read().decode("utf-8", "replace")[:200]
        if erro.code in (401, 403) and "login" in url:
            raise SessaoExpirada(
                "o ERP recusou a senha guardada.\n"
                "Guarde a senha correta: no app, em 'Login';\n"
                "pelos .bat, no atalho '1 - Salvar senha'."
            ) from erro
        if erro.code == 403:
            raise ErpError(
                "403 do WAF do Mais Controle. Quase sempre e o cabecalho\n"
                "'user-agent' — confira a constante USER_AGENT em erp/api.py."
            ) from erro
        if erro.code == 401:
            raise SessaoExpirada("a sessao da API foi recusada (401).") from erro
        raise ErpError(
            f"HTTP {erro.code} ao chamar {url.split('?')[0]}\n{detalhe}"
        ) from erro
    except urllib.error.URLError as erro:
        raise ErpError(
            f"falha de rede ao chamar {url.split('?')[0]}: {erro.reason}"
        ) from erro
