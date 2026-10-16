# -*- coding: utf-8 -*-
"""Transações pendentes de assinatura do Sicoob, por conta — só LEITURA.

É o que a tela mostra em lupa → "Transações pendentes" → "Transações
pendentes de assinaturas" (`#/pendencia-assinatura`): tudo que alguém
agendou e ainda não foi assinado. O app nunca assina, cancela nem altera
nada ali; quem assina é o master, na tela do banco.

O que a tela faz, e que aqui se faz direto (endereços medidos em 15/10/2026
lendo a Rede do navegador):

    GET  /api/conta/transacao-pendente/contas
         a conta aberta: `[{cooperativa, contaCorrente, nomeCliente, …}]`
    POST /api/conta/transacao-pendente/consultar
         {"tipo": 0, "numOperadores": [], "periodoInicial": ISO,
          "periodoFinal": ISO, "contasCorrentes": [contaCorrente]}
         devolve a lista; conta sem nada responde 400 "Não existem
         resultados para o período informado."

`tipo` 0 é "Todas" (as outras opções da tela são "Gravadas por mim",
"Assinadas por mim" e "Não assinadas por mim"). Cada item traz `valor`,
`detalhe` (quem recebe), `observacao`, `nomeTransacao`, `situacao` e
`lancamentoEm` (milissegundos).

**A conta é implícita na sessão, e por isso é CONFERIDA antes de pedir.**
O mesmo cuidado do `baixar_comprovantes.sicoob_baixar`: a consulta leva o
número da conta, mas é a conta ABERTA que o servidor aceita; perguntar com
a conta errada na tela devolveria — ou recusaria — a de outra empresa sem
nada denunciar. O `contas` diz qual está aberta, e a consulta só vai se ela
for a pedida.

**Os endereços são do Sicoob, que os troca sem aviso** (fez isso com os
comprovantes em 25/09/2026). Quando mudarem, a falha diz o endereço e o que
o servidor respondeu; a tela do banco continua sendo o caminho à mão.
"""
from __future__ import annotations

import datetime as _dt
import re

BASE = "https://ib.sicoob.com.br/sicoobnet/api/conta/transacao-pendente/"
ROTA_CONTAS = BASE + "contas"
ROTA_CONSULTAR = BASE + "consultar"

#: "Todas" no campo Transações da tela.
TIPO_TODAS = 0

DIZERES_DE_VAZIO = ("não existem resultados", "nao existem resultados")


class PendenciasFalhou(RuntimeError):
    """A leitura de uma conta falhou; a mensagem diz o que o banco disse."""


_JS = """
async ([url, metodo, corpo]) => {
    const opcoes = {method: metodo, credentials: 'include',
                    headers: {'Content-Type': 'application/json'}};
    if (corpo) opcoes.body = JSON.stringify(corpo);
    const r = await fetch(url, opcoes);
    let texto = '';
    try { texto = await r.text(); } catch (e) { texto = ''; }
    return {status: r.status, corpo: texto};
}
"""


def so_digitos(numero: str) -> str:
    """`"12.345-6"` -> `"123456"`, o `contaCorrente` que a API usa."""
    return re.sub(r"\D", "", numero or "")


def _instante(dia: _dt.date, fim: bool) -> str:
    """O começo (ou o fim) do dia LOCAL, em UTC, no formato que a tela manda.

    A tela manda `2026-10-01T03:00:00.000Z` para o dia 01/10 em Brasília:
    meia-noite local em UTC. Montar em UTC direto ("T00:00Z") cortaria as
    últimas três horas do último dia."""
    hora = _dt.time(23, 59, 59) if fim else _dt.time(0, 0, 0)
    local = _dt.datetime.combine(dia, hora).astimezone()
    utc = local.astimezone(_dt.timezone.utc)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def corpo_da_consulta(conta_corrente: int, inicio: _dt.date,
                      fim: _dt.date) -> dict:
    return {"tipo": TIPO_TODAS, "numOperadores": [],
            "periodoInicial": _instante(inicio, fim=False),
            "periodoFinal": _instante(fim, fim=True),
            "contasCorrentes": [conta_corrente]}


def e_vazio(resposta: dict) -> bool:
    """Este 400 é "a conta não tem pendência"? Conta parada é normal."""
    if int(resposta.get("status") or 0) != 400:
        return False
    dito = (resposta.get("corpo") or "").lower()
    return any(m in dito for m in DIZERES_DE_VAZIO)


def _json(resposta: dict, rota: str):
    import json

    status = int(resposta.get("status") or 0)
    corpo = resposta.get("corpo") or ""
    if status != 200:
        raise PendenciasFalhou(
            f"{rota} respondeu HTTP {status}: {corpo.strip()[:200]}")
    try:
        return json.loads(corpo)
    except ValueError as e:
        raise PendenciasFalhou(f"{rota} não devolveu JSON") from e


def conta_aberta(page) -> list[str]:
    """Os `contaCorrente` que a tela de pendências enxerga agora."""
    dado = _json(page.evaluate(_JS, [ROTA_CONTAS, "GET", None]), ROTA_CONTAS)
    if not isinstance(dado, list):
        raise PendenciasFalhou(f"{ROTA_CONTAS} devolveu um formato novo")
    return [str(c.get("contaCorrente") or "") for c in dado
            if isinstance(c, dict)]


def consultar(page, numero: str, inicio: _dt.date, fim: _dt.date) -> list[dict]:
    """As pendências da conta `numero`, que tem de ser a ABERTA na tela."""
    alvo = so_digitos(numero)
    abertas = conta_aberta(page)
    if abertas != [alvo]:
        raise PendenciasFalhou(
            f"pedi a conta {numero} e a tela está em "
            f"{', '.join(abertas) or '(nenhuma)'} — não vou ler as pendências "
            "de outra conta com o nome desta")
    resposta = page.evaluate(_JS, [ROTA_CONSULTAR, "POST",
                                   corpo_da_consulta(int(alvo), inicio, fim)])
    if e_vazio(resposta):
        return []
    dado = _json(resposta, ROTA_CONSULTAR)
    if not isinstance(dado, list):
        raise PendenciasFalhou(f"{ROTA_CONSULTAR} devolveu um formato novo")
    return [p for p in dado if isinstance(p, dict)]


def ler_conta(cli, numero: str, inicio: _dt.date, fim: _dt.date) -> list[dict]:
    """Entra na conta pelo seletor do app e lê as pendências dela.

    `cli` é um `SicoobClient` já logado. Na tela "Novo", depois de várias
    trocas seguidas o cabeçalho com o ⇄ some da Home (visto em 15/10/2026);
    recarregar a página o traz de volta, então a troca é tentada uma segunda
    vez depois de um `reload`. `False` do `acessar_conta` é conta que este
    login não enxerga — vira falha com essa frase, não "nada pendente"."""
    try:
        entrou = cli.acessar_conta(numero)
    except Exception:                                        # noqa: BLE001
        cli.page.reload()
        cli.page.wait_for_timeout(3000)
        entrou = cli.acessar_conta(numero)
    if not entrou:
        raise PendenciasFalhou("esta conta não aparece neste login do Sicoob")
    vistas, todas = set(), []
    for de, ate in meses(inicio, fim):
        for p in consultar(cli.page, numero, de, ate):
            chave = p.get("pendencia")
            if chave is not None and chave in vistas:
                continue
            vistas.add(chave)
            todas.append(p)
    return todas


def meses(inicio: _dt.date, fim: _dt.date) -> list[tuple[_dt.date, _dt.date]]:
    """O período em pedaços de um mês cada.

    A lista de comprovantes do mesmo banco recusa período que atravessa o
    mês ("O intervalo de datas deve estar dentro do mesmo mês"); a de
    pendências foi medida só dentro do mês. Pedir mês a mês custa uma
    chamada a mais e não depende de a regra ser igual nas duas."""
    pedacos = []
    de = inicio
    while de <= fim:
        proximo = (de.replace(day=1) + _dt.timedelta(days=32)).replace(day=1)
        ate = min(fim, proximo - _dt.timedelta(days=1))
        pedacos.append((de, ate))
        de = proximo
    return pedacos
