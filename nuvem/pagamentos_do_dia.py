# -*- coding: utf-8 -*-
"""O dia de trabalho da aba "Pagamentos do dia" na nuvem — só LER e ACRESCENTAR.

Migration `20261022100000_pagamentos_do_dia_na_nuvem.sql`. O app NÃO envia
`quem` nem `quem_nome`: o servidor carimba os dois (`default auth.uid()` e o
gatilho `privado.carimbar_quem_nome`, que lê o nome no perfil), e a RLS recusa
a linha cujo carimbo não bata. Mudar de ideia é uma linha nova — o estado é a
última, e quem dobra é `tela_do_dia.conferencia`.
Resposta sem a linha gravada levanta `NaoGravou`: "gravado" sem ter gravado é
pior que a recusa (a mesma conferência de `aportes.cadastros.gravar`).
"""
from __future__ import annotations

import datetime as _dt
from decimal import ROUND_HALF_UP, Decimal

from . import rest

DECISAO, A_MAO, AGENDADO = "pagamento_decisao", "pagamento_a_mao", "pagamento_agendado"
RESPOSTA, EM_ABERTO = "agendado_resposta", "agendado_em_aberto"
NOME, LISTA = "lista_diretor_nome", "lista_diretor"
LOTE = 100
#: Teto de `descricao` na tabela do agendado (constraint `_tamanho`).
LIMITE_DESCRICAO = 200
_COLUNAS_A_MAO = frozenset({"conta", "valor", "descricao", "motivo", "favorecido", "tipo",
                            "dados", "lancamento_id", "centro_custo", "nf", "oc",
                            "valor_em_aberto"})
#: Colunas que o app escreve em `pagamento_agendado` (o resto é descartado) e
#: as de texto, todas com teto de 200 na constraint `_tamanho`.
_COLUNAS_AGENDADO = frozenset({"conta", "alvo", "lancamento_id", "a_mao_id", "favorecido",
                               "valor", "descricao", "tipo", "foto"})
_TEXTO_AGENDADO = ("conta", "alvo", "lancamento_id", "favorecido", "tipo", "descricao")
#: Índice único (dia, alvo): a ÚNICA recusa que significa "já marcado".
_DUPLICADO = "23505"
#: Carimbo do servidor: nunca sai do app, nem que a linha de entrada o traga.
_CARIMBO = ("quem", "quem_nome", "quando")


class NaoGravou(rest.ErroDaNuvem):
    """O banco respondeu sem devolver as linhas pedidas."""


def _dinheiro(valor) -> str:
    """Decimal/int/str -> "10.50". Float é recusado: dinheiro não passa por ele."""
    if isinstance(valor, (float, bool)):
        raise TypeError(f"dinheiro em {type(valor).__name__}: use Decimal")
    try:
        return str(Decimal(str(valor).strip()).quantize(Decimal("0.01"), ROUND_HALF_UP))
    except ArithmeticError as e:
        raise ValueError(f"valor inválido: {valor!r}") from e


def _e_duplicado(erro: rest.RecusadoPeloBanco) -> bool:
    """Só o conflito do índice único. 400 de check, 409 de FK e 5xx não são."""
    if erro.codigo:
        return erro.codigo == _DUPLICADO
    return erro.status == 409 and "duplicate key" in str(erro).lower()


def _iso(dia: _dt.date) -> str:
    return dia.isoformat()


class DiaNaNuvem:
    def __init__(self, token: str) -> None:
        self._token = token

    def _gravar(self, tabela: str, linhas: list[dict]) -> list[dict]:
        corpo = [{k: v for k, v in linha.items() if k not in _CARIMBO}
                 for linha in linhas]
        gravadas = rest.inserir(tabela, self._token, corpo) or []
        if len(gravadas) != len(corpo):
            raise NaoGravou(f"{tabela}: o banco devolveu {len(gravadas)} de "
                            f"{len(corpo)} linha(s)")
        return gravadas

    # ------------------------------------------------------------ passo 2
    def decisoes_do_dia(self, dia):
        return rest.ler(DECISAO, self._token, filtro=f"dia=eq.{_iso(dia)}&order=id.asc")

    def registrar_decisao(self, dia, *, alvo, conta, acao, motivo="", campos=None,
                          antes=None, corrigir_no_erp=False) -> dict:
        return self._gravar(DECISAO, [{
            "dia": _iso(dia), "alvo": str(alvo), "conta": str(conta), "acao": acao,
            "motivo": (motivo or "").strip(), "campos": dict(campos or {}),
            "antes": dict(antes or {}), "corrigir_no_erp": bool(corrigir_no_erp)}])[0]

    def pagamentos_a_mao(self, dia):
        return rest.ler(A_MAO, self._token, filtro=f"dia=eq.{_iso(dia)}&order=id.asc")

    def registrar_a_mao(self, dia, linha: dict) -> dict:
        corpo = {k: v for k, v in linha.items() if k in _COLUNAS_A_MAO}
        corpo["valor"] = _dinheiro(corpo["valor"])
        if corpo.get("valor_em_aberto") not in (None, ""):
            corpo["valor_em_aberto"] = _dinheiro(corpo["valor_em_aberto"])
        else:
            corpo.pop("valor_em_aberto", None)
        return self._gravar(A_MAO, [{"dia": _iso(dia), **corpo}])[0]

    # ---------------------------------------------------------- agendados
    def agendados_do_dia(self, dia):
        return rest.ler(AGENDADO, self._token, filtro=f"dia=eq.{_iso(dia)}&order=id.asc")

    def agendados_em_aberto(self):
        return rest.ler(EM_ABERTO, self._token, filtro="order=dia.asc,id.asc")

    def respostas(self, ids) -> list[dict]:
        ids = sorted({int(i) for i in ids})
        saida = []
        for i in range(0, len(ids), LOTE):
            bloco = ",".join(str(x) for x in ids[i:i + LOTE])
            saida.extend(rest.ler(RESPOSTA, self._token,
                                  filtro=f"agendado_id=in.({bloco})&order=id.asc"))
        return saida

    def marcar_agendados(self, dia, linhas) -> tuple[list[dict], list[dict]]:
        """(gravadas, já marcadas). O índice único (dia, alvo) recusa a
        segunda máquina; o lote recusado POR DUPLICIDADE é refeito um a um
        para gravar o resto. Qualquer outra recusa (check, coluna, FK, 5xx)
        SOBE: não é "já marcado". Se subir no meio do um a um, a exceção leva
        `gravadas` (o que já entrou) e `repetidas`, para a tela não dizer
        "não gravou" sobre o que gravou.

        Só as colunas da tabela vão, e os textos são cortados em 200. O
        tamanho dos campos DIGITADOS (motivo <= 200, dados <= 500, nome curto
        1 a 60) é validado pela tela, não aqui. `valor` é Decimal (float é
        recusado) e vai com 2 casas."""
        todas = []
        for l in linhas:
            nova = {k: v for k, v in l.items() if k in _COLUNAS_AGENDADO}
            for k in _TEXTO_AGENDADO:
                if k in nova:
                    nova[k] = str(nova[k] if nova[k] is not None else "")[:LIMITE_DESCRICAO]
            nova["valor"] = _dinheiro(nova["valor"])
            todas.append({"dia": _iso(dia), **nova})
        ja = {str(l.get("alvo")) for l in self.agendados_do_dia(dia)}
        repetidas = [l for l in todas if str(l["alvo"]) in ja]
        corpo = [l for l in todas if str(l["alvo"]) not in ja]
        if not corpo:
            return [], repetidas
        gravadas: list[dict] = []
        try:
            try:
                return self._gravar(AGENDADO, corpo), repetidas
            except rest.RecusadoPeloBanco as e:
                if not _e_duplicado(e):
                    raise
            for linha in corpo:
                try:
                    gravadas.extend(self._gravar(AGENDADO, [linha]))
                except rest.RecusadoPeloBanco as e:
                    if not _e_duplicado(e):
                        raise
                    repetidas.append(linha)
            return gravadas, repetidas
        except rest.ErroDaNuvem as e:
            e.gravadas, e.repetidas = gravadas, repetidas
            raise

    def responder(self, agendado_id, resposta, *, motivo="", nova_data=None, prova="") -> dict:
        return self._gravar(RESPOSTA, [{
            "agendado_id": int(agendado_id), "resposta": resposta,
            "motivo": (motivo or "").strip(),
            "nova_data": nova_data.isoformat() if nova_data else None,
            "prova": prova or ""}])[0]

    # ---------------------------------------------------- lista do diretor
    def nomes_curtos(self) -> dict[str, str]:
        nomes = {}
        for linha in rest.ler(NOME, self._token, colunas="conta,nome_curto",
                              filtro="order=id.desc"):
            # Mais novo primeiro: o teto de linhas do PostgREST corta só os velhos.
            nomes.setdefault(str(linha["conta"]), str(linha["nome_curto"]))
        return nomes

    def gravar_nome_curto(self, conta, nome) -> dict:
        return self._gravar(NOME, [{"conta": conta, "nome_curto": (nome or "").strip()}])[0]

    def lista_anterior(self, dia) -> list[dict]:
        linhas = rest.ler(LISTA, self._token, colunas="dia,ordem",
                          filtro=f"dia=lt.{_iso(dia)}&order=dia.desc,id.desc&limit=1")
        return list((linhas[0].get("ordem") if linhas else None) or [])

    def gravar_lista(self, dia, ordem, texto) -> dict:
        return self._gravar(LISTA, [{"dia": _iso(dia), "ordem": list(ordem), "texto": texto}])[0]
