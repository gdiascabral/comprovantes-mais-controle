# tela_do_dia/controle_nuvem.py
# -*- coding: utf-8 -*-
"""Abertura, proporção e apontamentos do Controle de aportes, na nuvem.

Três tabelas (migration 20261022130000): `controle_aporte_conta`,
`controle_aporte_aportador` e `controle_aporte_atribuicao`. Ler: quem tem
conta liberada; escrever: só administrador (a RLS nega o resto — a tela só
esconde os botões). Números vão como TEXTO, nunca float.

Gravar insere ANTES de apagar (o mesmo de `aportes/rateio_subconta.gravar`):
se a rede cair no meio, sobra um aportador a mais — visível na próxima
leitura —, nunca uma conta sem ninguém.
"""
from __future__ import annotations

import datetime
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import util
from aportes.regras import como_dinheiro

from .controle_aportes import (Aportador, Apontamento, ContaControlada,
                               aportador_do_apontamento, problemas_da_conta)

CONTAS = "controle_aporte_conta"
APORTADORES = "controle_aporte_aportador"
APONTAMENTOS = "controle_aporte_atribuicao"


def _anotar_na_auditoria(acao: str, detalhe: str) -> None:
    from nuvem import auditoria
    auditoria.gravar_agora(acao, detalhe)


class NaoGravou(RuntimeError):
    """O banco respondeu sem erro, mas a linha não mudou (RLS barrou, ou a
    linha sumiu). Nunca vira "gravado" na auditoria."""


def _alterar_um(token: str, tabela: str, filtro: str, mudancas: dict, o_que: str) -> None:
    from nuvem import rest
    feitas = rest.alterar(tabela, token, filtro, mudancas)
    if len(feitas) != 1:
        raise NaoGravou(f"Não consegui gravar {o_que}: o banco não alterou a linha (sem "
                        "permissão, ou outro administrador a mexeu). Atualize a aba e tente de novo.")


def _apagar_conferido(token: str, tabela: str, filtro: str, quantas: int, o_que: str) -> None:
    """Apaga e CONFERE: lê antes (têm de ser `quantas`) e depois (nenhuma)."""
    from nuvem import rest
    antes = rest.ler(tabela, token, colunas="id", filtro=filtro)
    if len(antes) != quantas:
        raise NaoGravou(f"Não consegui apagar {o_que}: já não está na nuvem como estava. "
                        "Atualize a aba.")
    rest.apagar(tabela, token, filtro)
    if rest.ler(tabela, token, colunas="id", filtro=filtro):
        raise NaoGravou(f"Não consegui apagar {o_que}: o banco não apagou (sem permissão?).")


def _dec(valor, o_que: str) -> Decimal:
    try:
        d = Decimal(str(valor))
    except InvalidOperation:
        raise ValueError(f"{o_que} ilegível na nuvem: {valor!r}") from None
    if not d.is_finite():
        raise ValueError(f"{o_que} ilegível na nuvem: {valor!r}")
    return d


def _txt_dinheiro(v) -> str:
    return format(como_dinheiro(v), "f")


def _txt_peso(v) -> str:
    return format(Decimal(v).normalize(), "f")


def contas_das_linhas(contas: list, aportadores: list) -> list:
    saida = []
    for c in sorted(contas, key=lambda x: util.norm_espaco(x.get("conta_erp") or "")):
        deles = sorted((a for a in aportadores if a.get("conta_id") == c["id"]),
                       key=lambda a: a["id"])
        saida.append(ContaControlada(
            conta_erp=str(c["conta_erp"]),
            abertura=datetime.date.fromisoformat(str(c["abertura"])[:10]),
            id=int(c["id"]), ativa=bool(c.get("ativa", True)),
            aportadores=tuple(Aportador(nome_erp=str(a["nome_erp"]),
                                        peso=_dec(a["peso"], "parte"),
                                        abertura=como_dinheiro(_dec(a["abertura"], "já aportado")),
                                        id=int(a["id"])) for a in deles)))
    return saida


def apontamentos_das_linhas(linhas: list) -> dict:
    saida: dict = {}
    for l in linhas:
        saida.setdefault(int(l["conta_id"]), []).append(Apontamento(
            recebimento_id=str(l["recebimento_erp"]),
            aportador_id=None if l.get("aportador_id") is None else int(l["aportador_id"]),
            valor=como_dinheiro(_dec(l["valor"], "valor apontado")),
            motivo=str(l.get("motivo") or ""), id=int(l["id"])))
    return saida


def ler(token: str) -> tuple:
    """([ContaControlada], {conta_id: [Apontamento]}) — como o BANCO tem agora."""
    from nuvem import rest
    contas = rest.ler(CONTAS, token, colunas="id,conta_erp,abertura,ativa")
    aps = rest.ler(APORTADORES, token, colunas="id,conta_id,nome_erp,peso,abertura")
    atrs = rest.ler(APONTAMENTOS, token,
                    colunas="id,conta_id,recebimento_erp,aportador_id,valor,motivo")
    return contas_das_linhas(contas, aps), apontamentos_das_linhas(atrs)


def gravar_conta(token: str, conta: ContaControlada, hoje: datetime.date, outras=(),
                 anotar=None, vistos=None) -> None:
    """`vistos` = ids dos aportadores que o formulário CARREGOU desta conta
    (obrigatório para conta já gravada). Se o banco tiver outro, um
    administrador o incluiu depois: recusa sem gravar, para nunca apagá-lo."""
    from nuvem import rest
    erros = problemas_da_conta(conta, hoje, outras)
    if erros:
        raise ValueError(" ".join(erros))
    anotar = anotar or _anotar_na_auditoria
    campos = {"conta_erp": conta.conta_erp.strip(), "abertura": conta.abertura.isoformat(),
              "ativa": bool(conta.ativa)}
    antes, sair = [], []
    if conta.id is not None:
        antes = rest.ler(APORTADORES, token, colunas="id,nome_erp,peso,abertura",
                         filtro=f"conta_id=eq.{int(conta.id)}")
        ficam = {util.norm_espaco(a.nome_erp) for a in conta.aportadores}
        if vistos is None:
            raise ValueError("Faltou informar os aportadores que o formulário carregou.")
        conhecidos = {int(v) for v in vistos}
        novos_no_banco = [l["nome_erp"] for l in antes if int(l["id"]) not in conhecidos]
        if novos_no_banco:
            raise ValueError(f"{', '.join(novos_no_banco)} foi incluído(s) por outro administrador "
                             "depois que você abriu a conta. Nada foi gravado: atualize a aba e "
                             "refaça a edição.")
        sair = [l for l in antes if util.norm_espaco(l["nome_erp"]) not in ficam]
        if sair:
            # ANTES de escrever qualquer coisa: o banco recusaria o apagar no
            # fim, com a conta e os novos já gravados.
            apontados = {l.get("aportador_id") for l in rest.ler(
                APONTAMENTOS, token, colunas="aportador_id",
                filtro=f"conta_id=eq.{int(conta.id)}")}
            presos = [l["nome_erp"] for l in sair if l["id"] in apontados]
            if presos:
                raise ValueError(f"{', '.join(presos)} tem recebimento(s) apontado(s) nesta "
                                 "conta: desfaça os apontamentos antes de tirá-lo(s).")
    escreveu = False
    try:
        if conta.id is None:
            ident = int(rest.inserir(CONTAS, token, [campos])[0]["id"])
        else:
            ident = int(conta.id)
            _alterar_um(token, CONTAS, f"id=eq.{ident}", campos, "a conta")
        escreveu = True
        por_chave = {util.norm_espaco(l["nome_erp"]): l for l in antes}
        novos, mudados = [], []
        for a in conta.aportadores:
            linha = {"nome_erp": a.nome_erp.strip(), "peso": _txt_peso(a.peso),
                     "abertura": _txt_dinheiro(a.abertura)}
            velho = por_chave.get(util.norm_espaco(a.nome_erp))
            if velho is None:
                novos.append(dict(linha, conta_id=ident))
            elif (velho["nome_erp"] != linha["nome_erp"]
                  or _dec(velho["peso"], "parte") != Decimal(a.peso)
                  or como_dinheiro(_dec(velho["abertura"], "já aportado")) != como_dinheiro(a.abertura)):
                mudados.append((int(velho["id"]), linha))
        if novos:
            rest.inserir(APORTADORES, token, novos, devolver=False)
        for i, linha in mudados:
            _alterar_um(token, APORTADORES, f"id=eq.{i}", linha, "um aportador")
        if sair:
            _apagar_conferido(token, APORTADORES,
                              "id=in.(" + ",".join(str(int(l["id"])) for l in sair) + ")",
                              len(sair), "aportador(es) retirado(s)")
    except Exception as e:
        if not escreveu or isinstance(e, (rest.SemRede, rest.PrecisaEntrar)):
            raise      # nada gravado, ou erro que o chamador trata como está
        raise RuntimeError(f"{e}\n\nA gravação parou no meio. Atualize a aba para ver o que "
                           "ficou na nuvem e grave de novo o que você quer.") from e
    anotar("Controle de aportes: conta gravada",
           f"{conta.conta_erp} | abertura {conta.abertura:%d/%m/%Y} | " + "; ".join(
               f"{a.nome_erp} parte {_txt_peso(a.peso)} já aportado {_txt_dinheiro(a.abertura)}"
               for a in conta.aportadores))


def apontar(token: str, conta: ContaControlada, recebimento, aportador_id, motivo: str,
            anotar=None) -> None:
    """Aponta (ou corrige) de quem é um recebimento sem dono desta conta.

    `aportador_id` None = "não é aporte desta conta". O aportador é conferido
    contra a conta ANTES de escrever (erro legível, em vez da recusa da chave
    composta do banco). O banco tem unique (conta_id, recebimento_erp): um
    recebimento tem um só apontamento, e apontar de novo CORRIGE o anterior.
    O autor não vai no corpo: `alterado_por` é carimbado pelo servidor."""
    from nuvem import rest
    if conta.id is None:
        raise ValueError("A conta ainda não foi gravada na nuvem: grave a conta antes de apontar.")
    conta_id = int(conta.id)
    aportador_do_apontamento(conta, aportador_id)
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Escreva o motivo do apontamento.")
    if recebimento.valor <= 0:
        raise ValueError("Recebimento sem valor não se aponta.")
    corpo = {"aportador_id": None if aportador_id is None else int(aportador_id),
             "valor": _txt_dinheiro(recebimento.valor), "motivo": motivo[:300]}
    filtro = (f"conta_id=eq.{int(conta_id)}"
              f"&recebimento_erp=eq.{quote(recebimento.id, safe='')}")
    achados = rest.ler(APONTAMENTOS, token, colunas="id", filtro=filtro)
    if not achados:
        try:
            rest.inserir(APONTAMENTOS, token, [dict(corpo, conta_id=int(conta_id),
                                                    recebimento_erp=recebimento.id)],
                         devolver=False)
        except rest.RecusadoPeloBanco as e:
            if "duplicate key" not in str(e) and "409" not in str(e):
                raise
            # corrida: outro administrador apontou este recebimento agora
            achados = rest.ler(APONTAMENTOS, token, colunas="id", filtro=filtro)
            if not achados:
                raise NaoGravou("Outro administrador acabou de apontar este recebimento; "
                                "atualize a aba.") from e
    if achados:
        try:
            _alterar_um(token, APONTAMENTOS, f"id=eq.{int(achados[0]['id'])}", corpo,
                        "o apontamento")
        except NaoGravou as e:
            raise NaoGravou("Outro administrador acabou de apontar este recebimento; "
                            "atualize a aba.") from e
    (anotar or _anotar_na_auditoria)(
        "Controle de aportes: recebimento apontado",
        f"conta {int(conta_id)} | recebimento {recebimento.id} | {corpo['valor']} | "
        f"aportador {corpo['aportador_id']} | {motivo[:200]}")


def desfazer(token: str, apontamento_id: int, anotar=None) -> None:
    _apagar_conferido(token, APONTAMENTOS, f"id=eq.{int(apontamento_id)}", 1,
                      "o apontamento")
    (anotar or _anotar_na_auditoria)("Controle de aportes: apontamento desfeito",
                                     f"apontamento {int(apontamento_id)}")
