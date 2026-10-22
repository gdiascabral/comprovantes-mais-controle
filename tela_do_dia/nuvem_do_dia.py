# -*- coding: utf-8 -*-
"""O que a aba lê da nuvem a cada Buscar — sem tela, com dublês no teste.

Nuvem que não responde (sem sessão, rede, tabela não aplicada) devolve
`erro` e uma conferência VAZIA, sem pendentes: a tela volta a ser a da
entrega 1 e trava liberar/editar/à mão/agendar (falha fechada). ERP ou
registro de remessas mudos só tiram PROVAS: os agendados aparecem, nenhum
pré-marcado por eles.

Retorno "ok" só vale como prova se o envio for DESTE agendamento: a remessa
tem de ter sido gerada no dia do agendado ou depois. Remessa antiga do mesmo
lançamento, ou envio sem data comparável, não prova nada.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import agendados as ag
from .conferencia import Conferencia


@dataclass
class LidoDaNuvem:
    conferencia: Conferencia
    agendados_hoje: list = field(default_factory=list)
    pendentes: list = field(default_factory=list)    # [(Agendado, Situacao, Resposta|None)]
    nomes_curtos: dict = field(default_factory=dict)
    lista_anterior: list = field(default_factory=list)
    erro: str = ""
    avisos: list = field(default_factory=list)


def _envio_deste_agendamento(envio, agendado):
    """O envio só vale se a remessa saiu no dia do agendado ou depois."""
    gerado = getattr(envio, "gerado_em", None)
    if envio is None or gerado is None:
        return None
    try:
        dia = (gerado.astimezone() if gerado.tzinfo else gerado).date()
        return envio if dia >= agendado.dia else None
    except (AttributeError, TypeError, ValueError):
        return None


def ler(nuvem, dia, hoje, *, api=None, registro=None, log=print) -> LidoDaNuvem:
    if nuvem is None:
        return LidoDaNuvem(Conferencia(), erro="sem sessão na nuvem — entre de novo no app")
    try:
        conf = Conferencia.da_nuvem(nuvem.decisoes_do_dia(dia), nuvem.pagamentos_a_mao(dia))
        de_hoje = [ag.Agendado.de_linha(x) for x in nuvem.agendados_do_dia(dia)]
        abertos = [ag.Agendado.de_linha(x) for x in nuvem.agendados_em_aberto()]
        respostas = [ag.Resposta.de_linha(x) for x in nuvem.respostas([a.id for a in abertos])]
        nomes, anterior = nuvem.nomes_curtos(), nuvem.lista_anterior(dia)
    except Exception as e:                                   # noqa: BLE001
        return LidoDaNuvem(Conferencia(), erro=f"não li a nuvem ({e})")
    ultimas = ag.ultima_resposta(respostas)
    pend = ag.pendentes(abertos, respostas)
    avisos, titulos, relido = [], {}, False
    janela = ag.intervalo_de_releitura(pend, hoje)
    if janela and api is not None:
        try:
            ini, fim = janela
            itens = api.listar_a_pagar(f"{ini:%Y-%m-%d}", f"{fim:%Y-%m-%d}", log=log) or ()
            titulos = {str(i.get("id")): i for i in itens if i.get("id")}
            relido = True
        except Exception as e:                               # noqa: BLE001
            avisos.append(f"não reli os títulos agendados no ERP ({e}): nada foi pré-marcado")
    elif janela:
        avisos.append("sem a sessão do ERP: os títulos agendados não foram relidos")
    envios = {}
    refs = [a.lancamento_id for a in pend if a.lancamento_id]
    if refs and registro is not None:
        try:
            _por_id, envios = registro.envios_em_lote([], refs)
        except Exception as e:                               # noqa: BLE001
            envios = {}
            avisos.append(f"não perguntei os retornos do banco ({e})")
    linhas = []
    for a in pend:
        envio = _envio_deste_agendamento((envios.get(a.lancamento_id) or (None,))[0], a)
        try:
            sit = ag.situacao(a, titulos.get(a.lancamento_id), envio,
                              relido=relido or not a.lancamento_id)
        except Exception as e:                               # noqa: BLE001
            sit = ag.Situacao("atencao", "não consegui ler o título no ERP — responda")
            avisos.append(f"título {a.lancamento_id or a.alvo} ilegível no ERP ({e}): sem pré-marca")
        linhas.append((a, sit, ultimas.get(a.id)))
    return LidoDaNuvem(conf, de_hoje, linhas, nomes, anterior, "", avisos)
