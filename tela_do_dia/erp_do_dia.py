# -*- coding: utf-8 -*-
"""Os saldos do ERP pela tela do dia — SEMPRE pelo Chrome do app.

Regra do dono (14/10/2026, `erp/sessao.py:215`): nada de `POST /users/login`
por HTTP, que derruba a sessão do Chrome. Dois caminhos, nenhum com login:

- central ligado: `SessaoApi.logar` devolve um `SessaoApi` cuja `_sessao`
  (a `erp.Sessao` por baixo) é a `SessaoPelaPagina` do porteiro
  (`conciliacao/erp/api.py:216-227`, `erp/sessao.py:219`). Ele NÃO devolve a
  `SessaoPelaPagina` em si. É o mesmo caminho do "Saldo de pagamentos";
- central desligado: a MESMA aba do robô que acabou de ler os pagamentos
  (`mc_api._fetch_json`, com os cabeçalhos do `prod-erp-api` capturados da
  tela de um lançamento). A paginação e o lote de saldos continuam os do
  `SessaoApi`: esta classe só troca o transporte, instalado como `_sessao`.

`acessos.json` estragado: `central_ligado` levanta `ErpErro` e a leitura para
(falha FECHADA). Nunca cai no login HTTP.
"""
from __future__ import annotations

from conciliacao.erp.api import SessaoApi
from conciliacao.errors import ErpError
from erp import sessao as erp_sessao
from erp.sessao import ErpErro, Sessao


class PedirPelaAba:
    """O que `SessaoApi._pedir` exige de uma `_sessao`: `pedir(url)` e os
    atributos `transporte` e `espera` (que ele escreve antes de pedir)."""

    def __init__(self, api):
        self._api = api
        self.transporte = None      # `SessaoApi._pedir` escreve os dois
        self.espera = None

    def pedir(self, url: str):
        captura = getattr(self._api, "_req_anexos", None)
        if not captura:
            raise ErpError("o Chrome do app ainda não tem o acesso ao cadastro "
                           "de contas — busque de novo.")
        _base, cabecalhos = captura
        try:
            corpo = self._api._fetch_json(url, cabecalhos)
        except Exception as e:      # rede, aba fechada, resposta que não é JSON
            raise ErpError("não consegui ler as contas pela aba do app "
                           f"({type(e).__name__}). Recarregue o Mais Controle "
                           "no Chrome do app e busque de novo.") from e
        if isinstance(corpo, dict) and corpo.get("__erro"):
            raise ErpError(f"o Mais Controle respondeu {corpo['__erro']} ao ler as "
                           "contas pela aba do app. Recarregue o Mais Controle no "
                           "Chrome do app e busque de novo.")
        return corpo


def _logar_pela_pagina(config, log=print):
    """Sessão do porteiro, SEM nunca cair no login HTTP.

    Não usa `SessaoApi.logar`: ele relê `central_ligado()` e, se o central
    sumiu entre a leitura de `ler_saldos` e a dele, cai em `POST /users/login`.
    Aqui `Sessao.logar("", "")` relê o central e, desligado, levanta
    `SessaoRecusada` (sem credencial, sem HTTP). Traduzido para `ErpError`.
    """
    try:
        interna = Sessao.logar("", "")
    except ErpErro as e:
        raise ErpError(str(e)) from e
    if not interna.jwt_token:
        raise ErpError("o porteiro entrou sem 'jwtToken' — o contrato mudou.")
    return SessaoApi(token=interna.jwt_token, company_id=interna.company_id,
                     usuario=interna.usuario or "Chrome central",
                     empresa=interna.empresa, config=config, _sessao=interna)


def ler_saldos(config, api, *, central_ligado=None, logar=None, esquecer=None,
               log=print):
    """Contas ativas com saldo, só pelo Chrome do app.

    Erro do ERP vira `ErpError`, nunca saldo zero. Conta sem saldo no lote
    sai com `balance=None` ("não lido"). Com `acessos.json` estragado,
    `central_ligado` levanta `ErpErro` (a classe do pacote `erp/`, não a
    `ErpError` da conciliação) e a leitura para antes de tocar `api` ou login.

    Central ligado: erro do ERP na 1ª leitura descarta a sessão central
    guardada (`erp.sessao.esquecer_central`) e lê UMA vez de novo. Prova ao
    vivo 21 e 22/10/2026: quando o Chrome do app precisa logar no ERP na
    mesma rodada, a sessão guardada fica com a autenticação velha e a
    leitura caía; com a sessão já aberta, passava. Se a 2ª também falhar, sobe
    o erro dela, com o motivo real.
    """
    central_ligado = central_ligado or erp_sessao.central_ligado
    logar = logar or _logar_pela_pagina
    esquecer = esquecer or erp_sessao.esquecer_central
    if central_ligado():
        try:
            contas = logar(config, log=log).contas(ativas=True)
        except (ErpError, ErpErro) as e:
            log(f"  Saldos do ERP: a sessão do Chrome central falhou ({type(e).__name__}: "
                f"{e}) — abrindo uma nova e lendo de novo.")
            esquecer("principal")
            contas = logar(config, log=log).contas(ativas=True)
    else:
        if not getattr(api, "_req_anexos", None) and not api.garantir_credenciais_anexos(log):
            raise ErpError("não consegui o acesso do Chrome do app ao cadastro de "
                           "contas. Abra um lançamento qualquer no Chrome do app e "
                           "busque de novo.")
        sessao = SessaoApi(token="", company_id="", usuario="Chrome do app",
                           empresa=None, config=config, _sessao=PedirPelaAba(api))
        contas = sessao.contas(ativas=True)
    if not contas:
        raise ErpError("o ERP não devolveu nenhuma conta bancária.")
    return contas
